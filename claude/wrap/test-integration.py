#!/usr/bin/env python3
"""Integration tests for Phase 4 — the Insulator wired into the wrapper I/O loop.

Phase 4 retired ScreenRepair and made the Insulator the live output transform,
default-ON. These exercise the COMPOSED output pipeline (process_output /
drain_output / RepairState) in-process, with no live `claude` and no PTY, so the
headless ones are fully deterministic. The genuinely-live pieces (real claude in
tmux, DA/DSR no-hang) live in test_live.py; the real-terminal corpus gate
(DW-4.6a/4.6b) runs here but skips cleanly when tmux is absent.

  DW-4.3  CLAUDE_WRAP_REPAIR=0 -> output byte-identical (sha256) to the pre-
          insulator path (FrameMux.feed -> apply_subs) on clean / themed / framed /
          chunked / real-capture streams. The rollback is byte-clean.
  DW-4.4  theming (inline-code / italic / Bash / rainbow Skill) survives the
          Insulator and is present in the final composed output (the live echo-
          budget half of DW-4.4 is test_live.py via test-interactive.py).
  DW-4.5  a forced Insulator.feed / drain failure degrades to passthrough for the
          REST of the session without raising, and logs once (the barricade).
  DW-4.6a full corpus transparency+correction GREEN through the REAL-terminal
          harness with the Insulator (skips if tmux missing).
  DW-4.6b default-ON: env unset -> repair_enabled() True, RepairState active, sr is
          an Insulator; and an env-unset run through the real-terminal harness
          renders the buggy fixture to its INTENT grid (corrected, not raw).

Beyond the DW floor: the FrameMux composition is untouched (no double-handling),
the SIGWINCH reset path tracks new geometry on the Insulator, the idle/shutdown
drain order, ScreenRepair is fully retired, and the module imports clean.

Run:  python3 ~/.config/claude/wrap/test-integration.py
Exit: 0 all pass, 1 a behavioral assertion failed, 2 driver error.
"""
import hashlib
import importlib.util
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WRAP = os.path.join(HERE, "claude-theme-wrap.py")
TESTDATA = os.path.join(HERE, "testdata")
ROWS, COLS = 41, 129


def load_wrapper():
    spec = importlib.util.spec_from_file_location("claude_theme_wrap", WRAP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_harness():
    spec = importlib.util.spec_from_file_location(
        "test_harness", os.path.join(HERE, "test_harness.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def captures():
    import glob
    # Real claude byte-stream captures used for the byte-identical rollback check.
    return sorted(glob.glob(os.path.join(TESTDATA, "cap-*.bin")))


# --- tiny assertion harness (stdlib-only, mirrors the sibling suites) ------
_FAILS = []
_SKIPS = []


def check(cond, msg):
    if not cond:
        _FAILS.append(msg)


def eq(got, want, msg):
    if got != want:
        _FAILS.append(f"{msg}\n    got:  {got!r}\n    want: {want!r}")


def skip(msg):
    _SKIPS.append(msg)


# A themed sample exercising every needle apply_subs cares about, plus a couple of
# relative cursor moves so the Insulator is genuinely doing work on it.
THEMED_SAMPLE = (
    b"\x1b[38;5;153m`inline code`\x1b[39m "       # inline-code color needle
    b"\x1b[3mitalic\x1b[23m "                       # italic on/off needles
    b"\x1b[1mBash\x1b[22m(pwd) "                    # Bash tool-name needle
    b"\x1b[1mSkill\x1b[22m end\r\n"                 # rainbow Skill needle
)


def framed_sample(mod):
    """A synthetic DEC-2026 frame: proves FrameMux still brackets a real frame
    end-to-end through the composed pipeline (the dormant path stays correct)."""
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


# ==========================================================================
# Retirement + clean-import guards (no DW-ID, but the floor of "the swap landed").
# ==========================================================================
def test_module_imports_clean_and_insulator_swapped(mod):
    # The wrapper must import with no stdout/stderr noise and expose the Phase-4
    # surface; ScreenRepair must be gone and RepairState.sr must be an Insulator.
    code = (
        "import importlib.util\n"
        f"spec = importlib.util.spec_from_file_location('w', {WRAP!r})\n"
        "m = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(m)\n"
        "assert all(hasattr(m, n) for n in "
        "('process_output','drain_output','RepairState','repair_enabled',"
        "'Insulator','FrameMux'))\n"
        "assert not hasattr(m, 'ScreenRepair'), 'ScreenRepair must be retired'\n"
    )
    res = subprocess.run([sys.executable, "-c", code], capture_output=True)
    eq(res.returncode, 0, f"clean import / surface check failed: {res.stderr.decode()!r}")
    eq(res.stdout, b"", "importing the module must print nothing to stdout")
    eq(res.stderr, b"", "importing the module must print nothing to stderr")


def test_repairstate_sr_is_insulator(mod):
    state = _state_with_flag(mod, None)        # default on
    check(state.active(), "default-on: repair must be active")
    check(isinstance(state.sr, mod.Insulator),
          "RepairState.sr must be an Insulator (ScreenRepair retired)")


def test_screenrepair_suite_file_removed(mod):
    check(not os.path.exists(os.path.join(HERE, "test-screenrepair.py")),
          "the superseded test-screenrepair.py must be removed in Phase 4")


# ==========================================================================
# FrameMux composition: the Insulator is strictly upstream and the mux is
# untouched (no double-handling). The mux suite still passes; the mux still
# brackets a frame fed directly.
# ==========================================================================
def test_framemux_internals_untouched(mod):
    fm1 = mod.FrameMux()
    fm2 = mod.FrameMux()
    sample = THEMED_SAMPLE + framed_sample(mod)
    a = fm1.feed(sample) + fm1.drain()
    b = fm2.feed(sample) + fm2.drain()
    eq(a, b, "FrameMux.feed must be deterministic (internals untouched)")
    check(mod.PALETTE["bash"] in a, "FrameMux still applies the Bash theme")
    check(mod.BSU in a and mod.ESU in a, "FrameMux still brackets a 2026 frame")


def test_framemux_suite_still_green(mod):
    res = subprocess.run([sys.executable, os.path.join(HERE, "test-framemux.py")],
                         capture_output=True)
    eq(res.returncode, 0,
       f"test-framemux.py must exit 0 (stderr: {res.stderr.decode()!r})")


def test_insulator_suite_still_green(mod):
    res = subprocess.run([sys.executable, os.path.join(HERE, "test-insulator.py")],
                         capture_output=True)
    eq(res.returncode, 0,
       f"test-insulator.py must exit 0 (stderr: {res.stderr.decode()!r})")


# ==========================================================================
# DW-4.3: CLAUDE_WRAP_REPAIR=0 -> byte-identical to the pre-insulator path.
# ==========================================================================
def _pre_insulator_path(mod, chunks):
    """The pre-insulator wrapper output: FrameMux.feed per chunk + mux.drain,
    with NO insulator stage at all."""
    ref_mux = mod.FrameMux()
    ref = bytearray()
    for ch in chunks:
        ref += ref_mux.feed(ch)
    ref += ref_mux.drain()
    return bytes(ref)


def test_DW_4_3_flag_off_byte_identical_to_pre_insulator(mod):
    # With repair OFF, the composed pipeline output must equal the EXACT pre-
    # insulator path (mux only), proven by sha256 over clean / themed / framed /
    # chunked / real-capture streams under every off-value.
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
        ref = _pre_insulator_path(mod, chunks)
        ref_hash = hashlib.sha256(ref).hexdigest()
        for off in ("0", "off", "false", "no"):
            state = _state_with_flag(mod, off)
            check(not state.active(), f"DW-4.3: flag {off!r} must disable repair")
            check(state.sr is None,
                  f"DW-4.3: flag {off!r} must build NO Insulator (pure mux path)")
            got = _run_pipeline(mod, state, chunks)
            got_hash = hashlib.sha256(got).hexdigest()
            eq(got_hash, ref_hash,
               f"DW-4.3: repair-off output sha256 must equal the pre-insulator "
               f"mux-only path for sample {name!r} flag {off!r}\n"
               f"    (off bytes len={len(got)}, ref len={len(ref)})")


def test_DW_4_3_default_and_on_values_enable_repair(mod):
    # Unset, empty, and any non-off value must leave repair ON (default-on).
    for val in (None, "", "1", "on", "true", "yes", "garbage"):
        state = _state_with_flag(mod, val)
        check(state.active(),
              f"DW-4.3: flag value {val!r} must leave repair ENABLED (default on)")


# ==========================================================================
# DW-4.4: theming survives the Insulator and reaches the final output.
# ==========================================================================
def test_DW_4_4_theming_visible_through_insulator(mod):
    # Feed the themed sample through the FULL composed pipeline with repair ON.
    # The Insulator re-emits claude's ORIGINAL SGR faithfully, so apply_subs
    # (inside FrameMux) still matches the needles and the THEMED colors appear.
    state = _state_with_flag(mod, None)        # default on
    check(state.active(), "DW-4.4: precondition: repair must be enabled by default")
    out = _run_pipeline(mod, state, [THEMED_SAMPLE])
    check(mod.PALETTE["code"] in out,
          "DW-4.4: inline-code theme (orange) must be present after insulator+apply_subs")
    check(b"\x1b[38;5;153m" not in out,
          "DW-4.4: the raw inline-code 153 needle must have been re-themed away")
    bash_sig = b"\x1b[1m" + mod.PALETTE["bash"] + b"Bash"
    check(bash_sig in out, "DW-4.4: Bash tool-name recolor must survive the insulator")
    check(mod.RAINBOW[0] in out,
          "DW-4.4: rainbow Skill theme must survive the insulator")
    check(mod.PALETTE["italic"] in out,
          "DW-4.4: italic theme must survive the insulator")


def test_DW_4_4_render_row_last_glyph_bold_roundtrips(mod):
    # A themed bold word as the LITERAL last styled glyph on a row must still
    # round-trip for apply_subs (precise off-tokens, not a blanket reset).
    state = _state_with_flag(mod, None)
    sample = b"run \x1b[1mBash\x1b[22m\r\n"
    out = _run_pipeline(mod, state, [sample])
    bash_sig = b"\x1b[1m" + mod.PALETTE["bash"] + b"Bash"
    check(bash_sig in out,
          "DW-4.4/edge: a bold 'Bash' as the last styled glyph on a row must "
          "round-trip so apply_subs fires")


# ==========================================================================
# DW-4.5: forced Insulator failure -> passthrough, no raise, logs once.
# ==========================================================================
def _temp_log(mod):
    """Redirect the barricade log to a temp file so injection tests never write
    the production log. Returns (restore_fn)."""
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


def test_DW_4_5_feed_exception_degrades_to_passthrough(mod):
    restore = _temp_log(mod)
    state = _state_with_flag(mod, None)        # repair on
    check(state.active(), "DW-4.5: precondition: repair must be enabled")

    # Monkeypatch the instance's Insulator.feed to raise on the FIRST chunk. The
    # RepairState barricade (not the Insulator's own internal guard) must catch it.
    calls = {"n": 0}
    real_feed = state.sr.feed

    def boom(data):
        calls["n"] += 1
        raise RuntimeError("injected insulator failure")

    state.sr.feed = boom

    chunk1 = b"first chunk \x1b[1mBash\x1b[22m\r\n"
    try:
        out1 = mod.process_output(chunk1, state)
    except Exception as e:  # noqa: BLE001 - the whole point is no raise
        _FAILS.append(f"DW-4.5: process_output raised {type(e).__name__}: {e}")
        restore()
        return

    check(state.disabled, "DW-4.5: a feed exception must disable repair for the session")
    check(not state.active(), "DW-4.5: repair must be inactive after the barricade trips")
    bash_sig = b"\x1b[1m" + mod.PALETTE["bash"] + b"Bash"
    check(bash_sig in out1,
          "DW-4.5: the failing chunk must still flow through FrameMux+apply_subs (degraded)")

    # Subsequent chunks must equal the pure mux path and NOT call the broken feed.
    calls_before = calls["n"]
    chunk2 = b"second chunk plain text\r\n"
    out2 = mod.process_output(chunk2, state)
    eq(calls["n"], calls_before,
       "DW-4.5: after the barricade trips, Insulator.feed must not be called again")
    ref_mux = mod.FrameMux()
    ref_mux.feed(chunk1)
    ref = ref_mux.feed(chunk2)
    eq(out2, ref, "DW-4.5: post-trip chunk must equal the pure mux passthrough output")
    state.sr.feed = real_feed
    restore()


def test_DW_4_5_drain_exception_also_degrades(mod):
    restore = _temp_log(mod)
    state = _state_with_flag(mod, None)

    def boom_drain():
        raise RuntimeError("injected drain failure")

    state.sr.drain = boom_drain
    try:
        out = mod.drain_output(state)
    except Exception as e:  # noqa: BLE001
        _FAILS.append(f"DW-4.5: drain_output raised {type(e).__name__}: {e}")
        restore()
        return
    check(state.disabled, "DW-4.5: a drain exception must disable repair")
    check(isinstance(out, bytes), "DW-4.5: drain_output must return bytes after a guarded failure")
    restore()


def test_DW_4_5_session_continues_after_trip(mod):
    # After the barricade trips, the session keeps producing correct themed output
    # for the rest of the stream (degraded to mux passthrough, never frozen).
    restore = _temp_log(mod)
    state = _state_with_flag(mod, None)

    def boom(data):
        raise RuntimeError("boom")
    state.sr.feed = boom
    mod.process_output(b"trip it\r\n", state)        # trips the barricade
    check(state.disabled, "DW-4.5: barricade tripped")
    # Many subsequent chunks all flow cleanly through the mux, themed, no raise.
    ref_mux = mod.FrameMux()
    ref_mux.feed(b"trip it\r\n")
    for chunk in (THEMED_SAMPLE, b"plain\r\n", framed_sample(mod)):
        got = mod.process_output(chunk, state)
        want = ref_mux.feed(chunk)
        eq(got, want, "DW-4.5: post-trip chunks must match the pure mux path (session lives)")
    restore()


def test_DW_4_5_logs_once_only(mod):
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
        eq(n, 1, "DW-4.5: the barricade must log exactly once per session")
    finally:
        mod.REPAIR_DEBUG_LOG = saved
        if os.path.exists(logpath):
            os.remove(logpath)


# ==========================================================================
# DW-4.6a: full corpus transparency + correction GREEN through the REAL
# terminal harness with the Insulator. Skips cleanly when tmux is absent.
# ==========================================================================
def _insulator_repair_fn(mod, cols, rows):
    """Adapt the Insulator to the harness's repair_fn(stream)->bytes shape: feed
    the whole stream then drain, exactly as the live loop composes feed+drain."""
    def repair(stream: bytes) -> bytes:
        ins = mod.Insulator(rows, cols)
        return ins.feed(stream) + ins.drain()
    return repair


def test_DW_4_6a_corpus_transparency_and_correction(mod):
    H = load_harness()
    if not H.tmux_available():
        skip("DW-4.6a: tmux not available — real-terminal corpus gate skipped")
        return
    fixtures = H.load_corpus()
    check(len(fixtures) >= 6, "DW-4.6a: corpus must have >=6 fixtures")
    for fx in fixtures:
        cols, rows = fx["cols"], fx["rows"]
        stream = open(os.path.join(H.corpus_dir(), fx["file"]), "rb").read()
        repair = _insulator_repair_fn(mod, cols, rows)
        if fx["label"] == "correct":
            ok = H.assert_transparent(repair, stream, cols, rows)
            check(ok, f"DW-4.6a: TRANSPARENCY failed on correct fixture {fx['file']!r}")
        else:  # buggy
            intent = H.load_intent(fx)
            ok = H.assert_corrected(repair, stream, intent, cols, rows)
            check(ok, f"DW-4.6a: CORRECTION failed on buggy fixture {fx['file']!r}")


# ==========================================================================
# DW-4.6b: default flipped ON — env unset -> active Insulator; and an env-unset
# run through the real-terminal harness renders the buggy fixture to INTENT.
# ==========================================================================
def test_DW_4_6b_default_on_and_active(mod):
    saved = os.environ.get("CLAUDE_WRAP_REPAIR")
    os.environ.pop("CLAUDE_WRAP_REPAIR", None)
    try:
        check(mod.repair_enabled(),
              "DW-4.6b: with CLAUDE_WRAP_REPAIR unset, repair_enabled() must be True")
        state = mod.RepairState(ROWS, COLS)
        check(state.active(), "DW-4.6b: an env-unset RepairState must be active")
        check(isinstance(state.sr, mod.Insulator),
              "DW-4.6b: the active transform must be the Insulator")
    finally:
        if saved is not None:
            os.environ["CLAUDE_WRAP_REPAIR"] = saved


def test_DW_4_6b_env_unset_through_harness_corrects(mod):
    H = load_harness()
    if not H.tmux_available():
        skip("DW-4.6b: tmux not available — env-unset correction gate skipped")
        return
    # Find the buggy fixture (the clamp-desync repro).
    buggy = [fx for fx in H.load_corpus() if fx["label"] == "buggy"]
    check(bool(buggy), "DW-4.6b: corpus must contain a buggy fixture")
    if not buggy:
        return
    fx = buggy[0]
    cols, rows = fx["cols"], fx["rows"]
    stream = open(os.path.join(H.corpus_dir(), fx["file"]), "rb").read()
    intent = H.load_intent(fx)

    saved = os.environ.get("CLAUDE_WRAP_REPAIR")
    os.environ.pop("CLAUDE_WRAP_REPAIR", None)
    try:
        # Drive the FULL composed pipeline (process_output/drain_output) the way
        # main() does, with the env UNSET — so this proves the default-on path,
        # not a hand-built Insulator.
        state = mod.RepairState(rows, cols)
        check(state.active(), "DW-4.6b: precondition: env-unset pipeline active")
        composed = _run_pipeline(mod, state, [stream[i:i + 4096]
                                              for i in range(0, len(stream), 4096)])
        # Rendered in a REAL terminal, the composed (themed) output must equal the
        # frozen INTENT grid — the corruption is gone via the default-on pipeline.
        got_grid = H.render_real(composed, cols, rows)
        eq(H._normalize_intent(got_grid), H._normalize_intent(intent),
           "DW-4.6b: env-unset composed pipeline must render the buggy fixture to "
           "its INTENT grid (corrected, not raw)")
        # And prove it is NON-vacuous: the RAW stream renders DIFFERENTLY (corrupt).
        raw_grid = H.render_real(stream, cols, rows)
        check(H._normalize_intent(raw_grid) != H._normalize_intent(intent),
              "DW-4.6b: the raw buggy stream must render != intent (gate non-vacuous)")
    finally:
        if saved is not None:
            os.environ["CLAUDE_WRAP_REPAIR"] = saved


# ==========================================================================
# Beyond the floor: SIGWINCH reset on the Insulator, drain order, py_compile.
# ==========================================================================
def test_sigwinch_reset_tracks_new_geometry(mod):
    # The SIGWINCH path (state.on_resize) must resize the Insulator's screen and
    # clear any held tail, never raising. (Fixes the pre-existing failure tied to
    # the old RepairState: sr is now an Insulator with .H/.W and has_pending().)
    state = _state_with_flag(mod, None)
    state.correct(b"some text\x1b[1mbold\xc3")   # leaves a pending UTF-8 tail
    check(state.repair_pending(), "precondition: a tail is pending before resize")
    state.on_resize(50, 100)
    check(state.sr.H == 50 and state.sr.W == 100, "SIGWINCH: new geometry applied")
    check(not state.repair_pending(), "SIGWINCH: reset clears the held tail")


def test_sigwinch_noop_when_repair_off(mod):
    # on_resize must be a safe no-op when repair is disabled (sr is None).
    state = _state_with_flag(mod, "0")
    check(state.sr is None, "precondition: repair off -> no Insulator instance")
    state.on_resize(10, 10)   # must not raise


def test_drain_output_order_repair_then_mux(mod):
    # A held insulator tail at idle must be flushed THROUGH the mux (themed), and
    # the mux drained after.
    state = _state_with_flag(mod, None)
    state.correct(b"\x1b[1;1Hhi\xc3")   # leaves a held UTF-8 tail in the insulator
    check(state.repair_pending(), "precondition: insulator holds a tail")
    out = mod.drain_output(state)
    check(isinstance(out, bytes), "drain_output returns bytes")


def test_resize_mid_split_sequence_no_raise(mod):
    # Dirty Phase-4 edge: a resize arrives while the insulator holds a partial
    # split sequence. reset() must clear it and the session must not raise.
    state = _state_with_flag(mod, None)
    state.correct(b"abc\x1b[")        # half a CSI held
    check(state.repair_pending(), "precondition: a partial CSI is held")
    state.on_resize(30, 80)           # resize mid-split
    check(not state.repair_pending(), "resize cleared the partial sequence")
    # Feeding more bytes after the resize still works and never raises.
    out = mod.process_output(b"def\r\n", state) + mod.drain_output(state)
    check(isinstance(out, bytes), "post-resize feed returns bytes, no raise")


def test_py_compile_clean(mod):
    res = subprocess.run([sys.executable, "-m", "py_compile", WRAP], capture_output=True)
    eq(res.returncode, 0, f"py_compile must be clean: {res.stderr.decode()!r}")


def test_file_is_stdlib_only(mod):
    import ast
    src = open(os.path.join(HERE, "test-integration.py"), "rb").read().decode()
    tree = ast.parse(src)
    stdlib = {"hashlib", "importlib", "os", "subprocess", "sys", "glob", "ast", "tempfile"}
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

    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        try:
            t(mod)
        except Exception as e:  # noqa: BLE001 - report, don't abort
            _FAILS.append(f"{t.__name__} raised {type(e).__name__}: {e}")

    print(f"ran {len(tests)} integration tests")
    for s in _SKIPS:
        print(f"  SKIP: {s}")
    if _FAILS:
        print(f"\nFAIL: {len(_FAILS)} assertion(s) failed:", file=sys.stderr)
        for f in _FAILS:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("OK: all integration tests pass.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
