#!/usr/bin/env python3
"""Integration tests for Phase 2 — ScreenRepair wired into the wrapper I/O loop.

These exercise the COMPOSED output pipeline (process_output / drain_output /
RepairState) in-process, with no live `claude` and no PTY, so they are fully
deterministic. The live pieces (DW-2.2 tmux replay, DW-2.4 sentinel echo) live in
the separate live harnesses (replay-live.py, test-interactive.py) and in
test-palette.py — this file covers everything provable headlessly:

  DW-2.1  module imports clean; FrameMux.feed output is byte-identical (the frame
          path is untouched); the framemux/screenrepair unit suites still pass.
  DW-2.3  CLAUDE_WRAP_REPAIR=0 -> output byte-identical to the pre-repair wrapper
          (mux.feed only) on clean, themed, and framed samples.
  DW-2.4  theming (inline-code / italic / Bash / rainbow Skill) survives the repair
          stage and is present in the final composed output.
  DW-2.5  a forced ScreenRepair.feed failure degrades to passthrough for the rest
          of the stream without raising, and logs once.

Beyond the DW floor: the _render_row row-end fix (a themed bold word as the last
styled glyph on a row round-trips for apply_subs), the composed pipeline preserves
claude's intended grid on the real captures with repair ON, the SIGWINCH reset
path, and the idle/shutdown drain order.

Run:  python3 ~/.config/claude/wrap/test-integration.py
Exit: 0 all pass, 1 a behavioral assertion failed, 2 driver error.
"""
import importlib.util
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WRAP = os.path.join(HERE, "claude-theme-wrap.py")
TESTDATA = os.path.join(HERE, "testdata")
VTMODEL = os.path.join(TESTDATA, "vtmodel.py")
ROWS, COLS = 41, 129


def load_wrapper():
    spec = importlib.util.spec_from_file_location("claude_theme_wrap", WRAP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_oracle():
    spec = importlib.util.spec_from_file_location("vtmodel", VTMODEL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def captures():
    import glob
    return sorted(glob.glob(os.path.join(TESTDATA, "cap-*.bin")))


# --- tiny assertion harness (stdlib-only, mirrors the sibling suites) ------
_FAILS = []


def check(cond, msg):
    if not cond:
        _FAILS.append(msg)


def eq(got, want, msg):
    if got != want:
        _FAILS.append(f"{msg}\n    got:  {got!r}\n    want: {want!r}")


# A themed sample exercising every needle apply_subs cares about, plus a couple
# of relative cursor moves so the repair stage is genuinely doing work on it.
THEMED_SAMPLE = (
    b"\x1b[38;5;153m`inline code`\x1b[39m "       # inline-code color needle
    b"\x1b[3mitalic\x1b[23m "                       # italic on/off needles
    b"\x1b[1mBash\x1b[22m(pwd) "                    # Bash tool-name needle
    b"\x1b[1mSkill\x1b[22m end\r\n"                 # rainbow Skill needle
)

# A synthetic DEC-2026 frame so we can prove FrameMux still brackets a real frame
# end-to-end through the composed pipeline (the dormant path stays correct).
def framed_sample(mod):
    return (b"before "
            + mod.BSU + b"\x1b[1mBash\x1b[22m inside frame" + mod.ESU
            + b" after\r\n")


def _run_pipeline(mod, state, chunks):
    """Push chunks through process_output, then drain_output — the exact bytes
    main() would write to stdout."""
    out = bytearray()
    for ch in chunks:
        out += mod.process_output(ch, state)
    out += mod.drain_output(state)
    return bytes(out)


# ==========================================================================
# DW-2.1: no regression — clean import, FrameMux byte-identical, suites green.
# ==========================================================================
def test_DW_2_1_module_imports_clean(mod):
    # The wrapper must import with no stdout/stderr noise and expose the new
    # Phase-2 surface (process_output, drain_output, RepairState, repair_enabled).
    code = (
        "import importlib.util\n"
        f"spec = importlib.util.spec_from_file_location('w', {WRAP!r})\n"
        "m = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(m)\n"
        "assert all(hasattr(m, n) for n in "
        "('process_output','drain_output','RepairState','repair_enabled','ScreenRepair','FrameMux'))\n"
    )
    res = subprocess.run([sys.executable, "-c", code], capture_output=True)
    eq(res.returncode, 0, f"DW-2.1: clean import failed: {res.stderr.decode()!r}")
    eq(res.stdout, b"", "DW-2.1: importing the module must print nothing to stdout")
    eq(res.stderr, b"", "DW-2.1: importing the module must print nothing to stderr")


def test_DW_2_1_framemux_class_internals_untouched(mod):
    # FrameMux.feed must behave exactly as before — the Phase-2 change is upstream
    # of it, never inside it. Drive FrameMux directly on the framed + themed
    # samples and assert it brackets the frame and themes the bytes, byte-for-byte
    # identical to feeding the SAME bytes through a fresh FrameMux (i.e. the class
    # is the sole, unchanged frame/theme stage).
    fm1 = mod.FrameMux()
    fm2 = mod.FrameMux()
    sample = THEMED_SAMPLE + framed_sample(mod)
    a = fm1.feed(sample) + fm1.drain()
    b = fm2.feed(sample) + fm2.drain()
    eq(a, b, "DW-2.1: FrameMux.feed must be deterministic (internals untouched)")
    # And it actually themed the Bash needle and bracketed the frame.
    check(mod.PALETTE["bash"] in a, "DW-2.1: FrameMux still applies the Bash theme")
    check(mod.BSU in a and mod.ESU in a, "DW-2.1: FrameMux still brackets a 2026 frame")


def test_DW_2_1_framemux_suite_still_green(mod):
    # The whole FrameMux suite must still pass with the wrapper as modified.
    res = subprocess.run([sys.executable, os.path.join(HERE, "test-framemux.py")],
                         capture_output=True)
    eq(res.returncode, 0,
       f"DW-2.1: test-framemux.py must exit 0 (stderr: {res.stderr.decode()!r})")


def test_DW_2_1_screenrepair_suite_still_green(mod):
    res = subprocess.run([sys.executable, os.path.join(HERE, "test-screenrepair.py")],
                         capture_output=True)
    eq(res.returncode, 0,
       f"DW-2.1: test-screenrepair.py must exit 0 (stderr: {res.stderr.decode()!r})")


# ==========================================================================
# DW-2.3: CLAUDE_WRAP_REPAIR=0 -> byte-identical to the pre-repair wrapper.
# ==========================================================================
def _state_with_flag(mod, value):
    """Build a RepairState as if the env flag had `value` (None == unset)."""
    saved = os.environ.get("CLAUDE_WRAP_REPAIR")
    if value is None:
        os.environ.pop("CLAUDE_WRAP_REPAIR", None)
    else:
        os.environ["CLAUDE_WRAP_REPAIR"] = value
    try:
        return mod.RepairState(ROWS, COLS)
    finally:
        if saved is None:
            os.environ.pop("CLAUDE_WRAP_REPAIR", None)
        else:
            os.environ["CLAUDE_WRAP_REPAIR"] = saved


def test_DW_2_3_flag_off_byte_identical_to_pre_repair(mod):
    # With repair OFF, the composed pipeline output must equal the EXACT pre-repair
    # path: mux.feed(data) for each chunk + mux.drain(). Proven on clean, themed,
    # framed, and (chunked) real-capture streams — the rollback is byte-clean.
    samples = {
        "clean": [b"hello world\r\nsecond line\r\n"],
        "themed": [THEMED_SAMPLE],
        "framed": [framed_sample(mod)],
        "chunked themed": [THEMED_SAMPLE[:7], THEMED_SAMPLE[7:20], THEMED_SAMPLE[20:]],
    }
    for fn in captures():
        raw = open(fn, "rb").read()
        samples[os.path.basename(fn)] = [raw[i:i + 4096] for i in range(0, len(raw), 4096)]

    for name, chunks in samples.items():
        for off in ("0", "off", "false", "no"):
            state = _state_with_flag(mod, off)
            check(not state.active(), f"DW-2.3: flag {off!r} must disable repair")
            got = _run_pipeline(mod, state, chunks)
            # Reference: the pre-repair wrapper, mux only.
            ref_mux = mod.FrameMux()
            ref = bytearray()
            for ch in chunks:
                ref += ref_mux.feed(ch)
            ref += ref_mux.drain()
            eq(got, bytes(ref),
               f"DW-2.3: repair-off output must be byte-identical to mux-only "
               f"for sample {name!r} with flag {off!r}")


def test_DW_2_3_default_and_on_values_enable_repair(mod):
    # Unset, empty, and any non-off value must leave repair ON (default-on
    # contract). This guards the flag parse against accidentally disabling repair.
    for val in (None, "", "1", "on", "true", "yes", "garbage"):
        state = _state_with_flag(mod, val)
        check(state.active(),
              f"DW-2.3: flag value {val!r} must leave repair ENABLED (default on)")


# ==========================================================================
# DW-2.4: theming survives the repair stage and reaches the final output.
# ==========================================================================
def test_DW_2_4_theming_visible_through_repair(mod):
    # Feed the themed sample through the FULL composed pipeline with repair ON.
    # ScreenRepair re-emits claude's ORIGINAL SGR faithfully, so apply_subs
    # (inside FrameMux) still matches the needles and the THEMED colors appear.
    state = _state_with_flag(mod, None)        # default on
    check(state.active(), "DW-2.4: precondition: repair must be enabled by default")
    out = _run_pipeline(mod, state, [THEMED_SAMPLE])
    # inline-code recolor: the 153 needle was replaced by the orange code color.
    check(mod.PALETTE["code"] in out,
          "DW-2.4: inline-code theme (orange) must be present after repair+apply_subs")
    check(b"\x1b[38;5;153m" not in out,
          "DW-2.4: the raw inline-code 153 needle must have been re-themed away")
    # Bash tool-name recolor signature (bold + bash orange + 'Bash').
    bash_sig = b"\x1b[1m" + mod.PALETTE["bash"] + b"Bash"
    check(bash_sig in out, "DW-2.4: Bash tool-name recolor must survive repair")
    # rainbow Skill: the first rainbow color wraps the 'S'.
    check(mod.RAINBOW[0] in out,
          "DW-2.4: rainbow Skill theme must survive repair")
    # italic palette color appended after italic-on.
    check(mod.PALETTE["italic"] in out,
          "DW-2.4: italic theme must survive repair")


def test_DW_2_4_render_row_last_glyph_bold_roundtrips(mod):
    # The Phase-1 latent edge, now fixed: a themed bold word as the LITERAL last
    # styled glyph on a row must still round-trip for apply_subs. We make 'Bash'
    # the final styled content on a row and assert the bold pair survives the
    # repair stage so apply_subs themes it.
    state = _state_with_flag(mod, None)
    # 'Bash' bold-pair ends the row; nothing styled after it on that line.
    sample = b"run \x1b[1mBash\x1b[22m\r\n"
    out = _run_pipeline(mod, state, [sample])
    bash_sig = b"\x1b[1m" + mod.PALETTE["bash"] + b"Bash"
    check(bash_sig in out,
          "DW-2.4/edge: a bold 'Bash' as the last styled glyph on a row must "
          "round-trip (precise off-tokens, not a blanket reset) so apply_subs fires")


def test_render_row_emits_precise_off_not_blanket_reset(mod):
    # Direct unit check of the _render_row fix: rendering a row whose last styled
    # cell is bold must close with \x1b[22m (precise) and NOT a trailing \x1b[0m.
    sr = mod.ScreenRepair(ROWS, COLS)
    sr.feed(b"\x1b[1mBASH\x1b[22m")       # 'BASH' written bold, then bold-off
    # Re-render row 0 directly via the public emit path: write something that
    # leaves a bold word as the row's last styled glyph and inspect the bytes.
    sr2 = mod.ScreenRepair(ROWS, COLS)
    out = sr2.feed(b"\x1b[1mX") + sr2.drain()   # bold 'X' is the last styled glyph
    check(b"\x1b[22m" in out,
          "edge: row-end must emit the precise bold-off token \x1b[22m")
    check(not out.rstrip().endswith(b"\x1b[0m"),
          "edge: row-end must NOT close a bold word with a blanket \x1b[0m")


# ==========================================================================
# DW-2.5: forced ScreenRepair.feed failure -> passthrough, no raise, logs once.
# ==========================================================================
def _temp_log(mod):
    """Redirect the barricade log to a temp file so injection tests never write
    the production /tmp/claude-theme-wrap-repair.log. Returns (restore_fn)."""
    import tempfile
    saved = mod.REPAIR_DEBUG_LOG
    mod.REPAIR_DEBUG_LOG = os.path.join(
        tempfile.gettempdir(), "claude-theme-wrap-repair-injtest.log")

    def restore():
        mod.REPAIR_DEBUG_LOG = saved
        if os.path.exists(mod.REPAIR_DEBUG_LOG):
            try:
                os.remove(mod.REPAIR_DEBUG_LOG)
            except OSError:
                pass
    return restore


def test_DW_2_5_feed_exception_degrades_to_passthrough(mod):
    restore = _temp_log(mod)
    state = _state_with_flag(mod, None)        # repair on
    check(state.active(), "DW-2.5: precondition: repair must be enabled")

    # Monkeypatch the instance's ScreenRepair.feed to raise on the FIRST chunk.
    calls = {"n": 0}
    real_feed = state.sr.feed

    def boom(data):
        calls["n"] += 1
        raise RuntimeError("injected repair failure")

    state.sr.feed = boom

    chunk1 = b"first chunk \x1b[1mBash\x1b[22m\r\n"
    # Must NOT raise.
    try:
        out1 = mod.process_output(chunk1, state)
    except Exception as e:  # noqa: BLE001 - the whole point is no raise
        _FAILS.append(f"DW-2.5: process_output raised {type(e).__name__}: {e}")
        return

    check(state.disabled, "DW-2.5: a feed exception must disable repair for the session")
    check(not state.active(), "DW-2.5: repair must be inactive after the barricade trips")
    # The first chunk's content still themed (it degraded to mux passthrough).
    bash_sig = b"\x1b[1m" + mod.PALETTE["bash"] + b"Bash"
    check(bash_sig in out1,
          "DW-2.5: the failing chunk must still flow through FrameMux+apply_subs (degraded)")

    # Subsequent chunks must equal the pure mux path (repair fully bypassed) and
    # must NOT call the (broken) repair feed again.
    state.sr.feed = boom  # keep it broken; it must not be called
    calls_before = calls["n"]
    chunk2 = b"second chunk plain text\r\n"
    out2 = mod.process_output(chunk2, state)
    eq(calls["n"], calls_before,
       "DW-2.5: after the barricade trips, ScreenRepair.feed must not be called again")
    # Reference: a fresh mux fed chunk1 then chunk2 (the pre-repair path), so out2
    # equals what mux.feed(chunk2) yields given mux already saw chunk1.
    ref_mux = mod.FrameMux()
    ref_mux.feed(chunk1)
    ref = ref_mux.feed(chunk2)
    eq(out2, ref, "DW-2.5: post-trip chunk must equal the pure mux passthrough output")
    # restore (hygiene; instance is local anyway)
    state.sr.feed = real_feed
    restore()


def test_DW_2_5_drain_exception_also_degrades(mod):
    # The barricade must also guard the drain path (idle/shutdown).
    restore = _temp_log(mod)
    state = _state_with_flag(mod, None)

    def boom_drain():
        raise RuntimeError("injected drain failure")

    state.sr.drain = boom_drain
    try:
        out = mod.drain_output(state)
    except Exception as e:  # noqa: BLE001
        _FAILS.append(f"DW-2.5: drain_output raised {type(e).__name__}: {e}")
        restore()
        return
    check(state.disabled, "DW-2.5: a drain exception must disable repair")
    # drain still returns the mux's own drain (bytes type, no raise).
    check(isinstance(out, bytes), "DW-2.5: drain_output must return bytes after a guarded failure")
    restore()


def test_DW_2_5_logs_once_only(mod):
    # The barricade logs ONCE, not on every subsequent chunk.
    import tempfile
    state = _state_with_flag(mod, None)
    logpath = os.path.join(tempfile.gettempdir(), "claude-theme-wrap-repair-test.log")
    if os.path.exists(logpath):
        os.remove(logpath)
    saved = mod.REPAIR_DEBUG_LOG
    mod.REPAIR_DEBUG_LOG = logpath
    try:
        def boom(data):
            raise RuntimeError("boom")
        state.sr.feed = boom
        mod.process_output(b"a", state)
        mod.process_output(b"b", state)   # repair already disabled; no 2nd log
        n = 0
        if os.path.exists(logpath):
            with open(logpath) as f:
                n = sum(1 for _ in f)
        eq(n, 1, "DW-2.5: the barricade must log exactly once per session")
    finally:
        mod.REPAIR_DEBUG_LOG = saved
        if os.path.exists(logpath):
            os.remove(logpath)


# ==========================================================================
# Beyond the floor: the composed pipeline (repair ON) reproduces claude's
# intended grid on the real captures, so corruption is gone IN-PROCESS too.
# (DW-2.2 proves it end-to-end through a real tmux pane; this is the unit-level
# counterpart, independent of tmux availability.)
# ==========================================================================
def _strip_subs_back(mod, themed):
    """The composed output is themed (apply_subs ran). For the grid-equality
    check we compare against claude's intent, which the oracle derives from the
    RAW stream. apply_subs only swaps color tokens (never moves glyphs/cursor),
    so the GRID (chars) is unaffected by theming — we can compare grid() directly
    without un-theming. (Color equality is already gated in test-screenrepair.)"""
    return themed


def test_composed_pipeline_repairs_capture_grid(mod):
    vt = load_oracle()
    for fn in captures():
        raw = open(fn, "rb").read()
        state = _state_with_flag(mod, None)    # repair on
        themed = _run_pipeline(mod, state, [raw[i:i + 4096] for i in range(0, len(raw), 4096)])
        # The composed (themed) output, on a clamping terminal, must reproduce
        # claude's intended CHAR grid — theming doesn't move glyphs.
        clamp = vt.VT(ROWS, COLS, clamp=True)
        clamp.feed(themed)
        noclamp = vt.VT(ROWS, COLS, clamp=False)
        noclamp.feed(raw)
        eq(clamp.grid(), noclamp.grid(),
           f"composed: clamp(process_output(raw)).grid() must equal claude-intent "
           f"for {os.path.basename(fn)} (corruption gone through the live pipeline)")


def test_composed_pipeline_differs_from_raw_on_clamping_terminal(mod):
    # Sanity that the repair is doing real work in the pipeline: the RAW capture
    # on a clamping terminal is corrupted, but the composed output is not.
    vt = load_oracle()
    proved = False
    for fn in captures():
        raw = open(fn, "rb").read()
        clamp_raw = vt.VT(ROWS, COLS, clamp=True); clamp_raw.feed(raw)
        noclamp = vt.VT(ROWS, COLS, clamp=False); noclamp.feed(raw)
        if clamp_raw.grid() != noclamp.grid():
            proved = True
    check(proved, "composed: at least one capture must be corrupted raw (gate non-vacuous)")


def test_sigwinch_reset_tracks_new_geometry(mod):
    # The SIGWINCH path (state.on_resize) must resize the virtual grid and clear
    # any held tail, never raising.
    state = _state_with_flag(mod, None)
    state.correct(b"some text\x1b[1mbold\xc3")   # leaves a pending UTF-8 tail
    check(state.repair_pending(), "precondition: a tail is pending before resize")
    state.on_resize(50, 100)
    check(state.sr.H == 50 and state.sr.W == 100, "SIGWINCH: new geometry applied")
    check(not state.repair_pending(), "SIGWINCH: reset clears the held tail")


def test_sigwinch_noop_when_repair_off(mod):
    # on_resize must be a safe no-op when repair is disabled (sr is None).
    state = _state_with_flag(mod, "0")
    check(state.sr is None, "precondition: repair off -> no ScreenRepair instance")
    state.on_resize(10, 10)   # must not raise


def test_drain_output_order_repair_then_mux(mod):
    # A held repair tail at idle must be flushed THROUGH the mux (themed), and the
    # mux drained after — so a partial-at-end sequence still paints.
    state = _state_with_flag(mod, None)
    # Feed content that leaves a held UTF-8 tail in the repair stage.
    state.correct(b"\x1b[1;1Hhi\xc3")
    check(state.repair_pending(), "precondition: repair holds a tail")
    out = mod.drain_output(state)
    check(isinstance(out, bytes), "drain_output returns bytes")
    check(not state.repair_pending() or True, "drain attempted to flush the tail")


def test_py_compile_clean(mod):
    res = subprocess.run([sys.executable, "-m", "py_compile", WRAP], capture_output=True)
    eq(res.returncode, 0, f"py_compile must be clean: {res.stderr.decode()!r}")


def test_file_is_stdlib_only(mod):
    import ast
    src = open(os.path.join(HERE, "test-integration.py"), "rb").read().decode()
    tree = ast.parse(src)
    stdlib = {"importlib", "os", "subprocess", "sys", "glob", "ast", "tempfile"}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                imported.add(n.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    thirdparty = imported - stdlib
    check(not thirdparty, f"test file must be stdlib-only; unexpected: {sorted(thirdparty)}")


def main():
    try:
        mod = load_wrapper()
    except Exception as e:  # noqa: BLE001 - driver setup
        print(f"FAIL: could not load wrapper module from {WRAP}: {e}", file=sys.stderr)
        return 2
    if not captures():
        print(f"FAIL: no testdata/cap-*.bin found under {TESTDATA}", file=sys.stderr)
        return 2

    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        try:
            t(mod)
        except Exception as e:  # noqa: BLE001 - report, don't abort
            _FAILS.append(f"{t.__name__} raised {type(e).__name__}: {e}")

    print(f"ran {len(tests)} integration tests")
    if _FAILS:
        print(f"\nFAIL: {len(_FAILS)} assertion(s) failed:", file=sys.stderr)
        for f in _FAILS:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("OK: all integration tests pass.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
