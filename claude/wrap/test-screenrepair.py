#!/usr/bin/env python3
"""Unit tests for the pure ScreenRepair primitive in claude-theme-wrap.py.

Drives ScreenRepair with the captured byte streams and synthetic inputs — no
live `claude`, no PTY, fully deterministic. Imports the wrapper as a module the
same way test-framemux.py / test-palette.py do, so it also proves ScreenRepair
is importable and side-effect-free at load.

The hard acceptance gate is the regression invariant, checked by a GENERIC
oracle harness over every testdata/cap-*.bin:

    clamp_model( repair(stream) ).grid() == noclamp_model(stream).grid()

using the INDEPENDENT checker testdata/vtmodel.py (vt.VT(41,129,clamp=True) is
byte-identical to a real tmux capture-pane; clamp=False is claude's intended
grid). ScreenRepair is the production code; vtmodel is the checker — they are
deliberately separate so a shared bug can't hide a failure.

Run:  python3 ~/.config/claude/wrap/test-screenrepair.py
Exit: 0 all pass, 1 a behavioral assertion failed (regression), 2 driver error.
"""
import glob
import importlib.util
import os
import random
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WRAP = os.path.join(HERE, "claude-theme-wrap.py")
TESTDATA = os.path.join(HERE, "testdata")
VTMODEL = os.path.join(TESTDATA, "vtmodel.py")

# The captures were taken at this geometry; the oracle and ScreenRepair must use
# the same H x W. (See the plan's HARD ACCEPTANCE GATE.)
ROWS, COLS = 41, 129


def load_wrapper():
    spec = importlib.util.spec_from_file_location("claude_theme_wrap", WRAP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_oracle():
    """Load testdata/vtmodel.py — the INDEPENDENT clamp/no-clamp checker. It is
    not production code and ScreenRepair never imports it; we load it here only
    to assert the regression invariant."""
    spec = importlib.util.spec_from_file_location("vtmodel", VTMODEL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def captures():
    """Every captured corruption stream. Sorted for deterministic ordering."""
    return sorted(glob.glob(os.path.join(TESTDATA, "cap-*.bin")))


# --- tiny assertion harness (no third-party deps) -------------------------
_FAILS = []


def check(cond, msg):
    if not cond:
        _FAILS.append(msg)


def eq(got, want, msg):
    if got != want:
        _FAILS.append(f"{msg}\n    got:  {got!r}\n    want: {want!r}")


_SGR_RE = re.compile(rb"\x1b\[[0-9;]*m")


def _strip_sgr(data: bytes) -> bytes:
    """Remove SGR (color/attribute) tokens from a byte stream, leaving cursor
    moves, EL, and printable glyphs. Lets a scrollback-preservation check assert
    on a line's CHARACTERS without the now-interleaved color bytes."""
    return _SGR_RE.sub(b"", data)


def _count_sgr(data: bytes) -> int:
    """Count SGR tokens in a byte stream (for the color-preservation evidence)."""
    return len(_SGR_RE.findall(data))


# --- repair drivers (the three adversarial chunkings) ---------------------
def repair_whole(mod, data):
    sr = mod.ScreenRepair(ROWS, COLS)
    return sr.feed(data) + sr.drain()


def repair_one_byte(mod, data):
    sr = mod.ScreenRepair(ROWS, COLS)
    out = bytearray()
    for i in range(len(data)):
        out += sr.feed(data[i:i + 1])
    out += sr.drain()
    return bytes(out)


def repair_random_chunks(mod, data, seed):
    sr = mod.ScreenRepair(ROWS, COLS)
    rng = random.Random(seed)
    out = bytearray()
    i = 0
    while i < len(data):
        k = rng.randint(1, 500)
        out += sr.feed(data[i:i + k])
        i += k
    out += sr.drain()
    return bytes(out)


def _clamp_grid(vt, repaired):
    m = vt.VT(ROWS, COLS, clamp=True)
    m.feed(repaired)
    return m.grid()


def _noclamp_grid(vt, raw):
    m = vt.VT(ROWS, COLS, clamp=False)
    m.feed(raw)
    return m.grid()


def _clamp_styled(vt, repaired):
    """Color-aware: per-cell (char, style_key) of the repaired stream on a
    clamping terminal."""
    m = vt.VT(ROWS, COLS, clamp=True)
    m.feed(repaired)
    return m.styled_grid()


def _noclamp_styled(vt, raw):
    """Color-aware: per-cell (char, style_key) of claude's INTENDED grid."""
    m = vt.VT(ROWS, COLS, clamp=False)
    m.feed(raw)
    return m.styled_grid()


# ==========================================================================
# DW-1.1: The regression invariant — clamp(repair(stream)) == noclamp(stream)
#         for EVERY testdata/cap-*.bin, under (a) whole-stream, (b) 1-byte, and
#         (c) random chunk boundaries. This is the hard acceptance gate.
# ==========================================================================
# The DW-1.1 invariant is now COLOR-AWARE: it compares styled_grid() — per-cell
# (char, active-SGR) — so a repair that drops claude's colors FAILS the gate even
# though the char-only grid would still match. We also assert the char-only grid
# to keep any cursor/positioning regression distinctly diagnosable.
def test_DW_1_1_oracle_invariant_whole_stream(mod):
    vt = load_oracle()
    caps = captures()
    check(len(caps) >= 1, "DW-1.1: at least one testdata/cap-*.bin must exist")
    for fn in caps:
        raw = open(fn, "rb").read()
        repaired = repair_whole(mod, raw)
        eq(_clamp_grid(vt, repaired), _noclamp_grid(vt, raw),
           f"DW-1.1 (whole, chars): clamp(repair) chars must equal intent for {os.path.basename(fn)}")
        eq(_clamp_styled(vt, repaired), _noclamp_styled(vt, raw),
           f"DW-1.1 (whole, COLOR): clamp(repair) per-cell color must equal claude-intent for {os.path.basename(fn)}")


def test_DW_1_1_oracle_invariant_one_byte_chunks(mod):
    vt = load_oracle()
    for fn in captures():
        raw = open(fn, "rb").read()
        repaired = repair_one_byte(mod, raw)
        eq(_clamp_grid(vt, repaired), _noclamp_grid(vt, raw),
           f"DW-1.1 (1-byte, chars): clamp(repair) chars must equal intent for {os.path.basename(fn)}")
        eq(_clamp_styled(vt, repaired), _noclamp_styled(vt, raw),
           f"DW-1.1 (1-byte, COLOR): clamp(repair) per-cell color must equal claude-intent for {os.path.basename(fn)}")


def test_DW_1_1_oracle_invariant_random_chunks(mod):
    vt = load_oracle()
    # Sweep several seeds so the random boundaries genuinely vary the splits.
    for seed in (1, 7, 42, 123, 999):
        for fn in captures():
            raw = open(fn, "rb").read()
            repaired = repair_random_chunks(mod, raw, seed)
            eq(_clamp_grid(vt, repaired), _noclamp_grid(vt, raw),
               f"DW-1.1 (random seed={seed}, chars): clamp(repair) chars must equal intent "
               f"for {os.path.basename(fn)}")
            eq(_clamp_styled(vt, repaired), _noclamp_styled(vt, raw),
               f"DW-1.1 (random seed={seed}, COLOR): clamp(repair) per-cell color must equal intent "
               f"for {os.path.basename(fn)}")


def test_DW_1_1_repair_actually_fixes_the_corruption(mod):
    # Sanity that the gate is meaningful: on the real captures, the RAW stream on
    # a clamping terminal is corrupted (clamp(raw) != intent). So repair is doing
    # real work, not passing through a stream that was already correct.
    vt = load_oracle()
    caps = captures()
    any_corrupt = False
    for fn in caps:
        raw = open(fn, "rb").read()
        if _clamp_grid(vt, raw) != _noclamp_grid(vt, raw):
            any_corrupt = True
    check(any_corrupt,
          "DW-1.1: at least one capture must be corrupted raw (else the gate is vacuous)")


# ==========================================================================
# DW-1.2: Scrollback preservation — lines scrolled off the virtual top are
#         present, IN ORDER, in the emitted byte stream (so tmux history keeps
#         them). Tested on a controlled synthetic stream AND on a real capture.
# ==========================================================================
def test_DW_1_2_scrolloff_lines_preserved_in_order(mod):
    # Print H+N distinct lines into an H-row screen. The first N lines must
    # scroll off the top; assert each appears in the emitted bytes, in order.
    extra = 6
    lines = [f"LINE{i:03d}" for i in range(ROWS + extra)]
    stream = b""
    for ln in lines:
        stream += ln.encode() + b"\r\n"
    sr = mod.ScreenRepair(ROWS, COLS)
    emitted = sr.feed(stream) + sr.drain()
    # The first `extra` lines scrolled off the top (printing row H+extra lines
    # with one newline each pushes `extra` lines past the top of an H-row grid).
    scrolled_off = lines[:extra]
    positions = []
    for ln in scrolled_off:
        idx = emitted.find(ln.encode())
        check(idx != -1,
              f"DW-1.2: scrolled-off line {ln!r} must appear in the emitted stream")
        positions.append(idx)
    # In order: each scrolled-off line must appear before the next.
    check(positions == sorted(positions),
          "DW-1.2: scrolled-off lines must appear in scroll order in the emitted stream")


def test_DW_1_2_scrolloff_followed_by_real_newline(mod):
    # Each scrolled-off line must be emitted with a trailing CRLF at the bottom
    # row, which is the REAL scroll that pushes it into tmux scrollback.
    extra = 3
    stream = b""
    for i in range(ROWS + extra):
        stream += f"ROW{i:03d}".encode() + b"\r\n"
    sr = mod.ScreenRepair(ROWS, COLS)
    emitted = sr.feed(stream) + sr.drain()
    # The very first scrolled-off line is ROW000; it must be followed by \r\n
    # somewhere (the history-pushing newline).
    idx = emitted.find(b"ROW000")
    check(idx != -1, "DW-1.2: first scrolled-off line must be emitted")
    check(b"\r\n" in emitted[idx:idx + 32],
          "DW-1.2: a scrolled-off line must be followed by a real CRLF (history push)")


def test_DW_1_2_capture_scrolloff_lines_present(mod):
    # On a real capture, claude's tree/table content scrolls off the top. Drive
    # the INDEPENDENT intent model's scroll behavior via the oracle to learn what
    # SHOULD scroll off, then assert those lines are in ScreenRepair's emission.
    vt = load_oracle()
    for fn in captures():
        raw = open(fn, "rb").read()
        # Reconstruct the scrolled-off lines from a no-clamp model that records
        # them (the same definition ScreenRepair uses: top row captured pre-pop).
        recorded = []
        m = vt.VT(ROWS, COLS, clamp=False)
        orig = m.scroll

        def cap(_m=m, _rec=recorded, _orig=orig):
            _rec.append("".join(_m.g[0]).rstrip())
            _orig()

        m.scroll = cap
        m.feed(raw)
        emitted = repair_whole(mod, raw)
        # The emission now re-themes claude's colors, so a scrolled-off line's
        # glyphs are interleaved with SGR tokens (\x1b[...m). Strip SGR first,
        # then assert the line's CHARACTERS are preserved in order — scrollback
        # preservation is about the glyphs reaching history, not their bytes
        # being contiguous. (We strip from the emission, not the line.)
        plain = _strip_sgr(emitted)
        for ln in recorded:
            if ln.strip():
                check(ln.encode("utf-8", "replace") in plain,
                      f"DW-1.2: scrolled-off line {ln!r} from {os.path.basename(fn)} "
                      f"must be in the emitted stream (scrollback preserved)")


# ==========================================================================
# DW-1.3: Defensive fallback — malformed/garbage CSI and truncated UTF-8 never
#         raise, and never produce fewer visible glyphs than passthrough would.
# ==========================================================================
def _visible_glyph_count(vt, data):
    """Count non-space glyphs the clamping terminal would show for `data`."""
    m = vt.VT(ROWS, COLS, clamp=True)
    m.feed(data)
    return sum(1 for row in m.g for ch in row if ch != " ")


def test_DW_1_3_garbage_csi_never_raises(mod):
    garbage = [
        b"\x1b[",                       # bare CSI introducer, no final
        b"\x1b[999999999999999999A",    # absurd param
        b"\x1b[;;;;;;m",                # empty params
        b"\x1b[?",                      # private-mode introducer, truncated
        b"\x1b[\x1b[\x1b[",             # stacked introducers
        b"\x1b]8;;http://x",            # truncated OSC hyperlink (no terminator)
        b"\x1b" * 100,                  # a wall of lone ESCs
        b"\x1bZ\x1bM\x1b=",             # assorted 2-byte ESCs
        b"hello\x1b[42world\x07",       # CSI with no final before text
    ]
    for g in garbage:
        sr = mod.ScreenRepair(ROWS, COLS)
        try:
            sr.feed(g)
            sr.drain()
        except Exception as e:  # noqa: BLE001 - the whole point is it must not raise
            _FAILS.append(f"DW-1.3: garbage CSI {g!r} raised {type(e).__name__}: {e}")


def test_DW_1_3_truncated_utf8_never_raises(mod):
    truncated = [
        b"\xe2\x8f",            # 3-byte char missing its last byte
        b"\xf0\x9f\x98",        # 4-byte emoji missing its last byte
        b"caf\xc3",            # 2-byte char start, no continuation
        b"\xff\xfe\x80\x80",    # invalid lead/continuation bytes
        b"ok\xe2\x8f\xbatail",  # a complete wide char surrounded by ASCII
    ]
    for t in truncated:
        sr = mod.ScreenRepair(ROWS, COLS)
        try:
            # Feed byte-by-byte to maximize the chance of a mid-char split.
            for i in range(len(t)):
                sr.feed(t[i:i + 1])
            sr.drain()
        except Exception as e:  # noqa: BLE001 - must never raise
            _FAILS.append(f"DW-1.3: truncated UTF-8 {t!r} raised {type(e).__name__}: {e}")


def test_DW_1_3_glyph_count_not_below_passthrough(mod):
    # The defensive floor: repairing a dirty stream must never show LESS than raw
    # passthrough would. We compare visible glyph counts of clamp(repair(x)) vs
    # clamp(x) for a mix of clean text and garbage.
    vt = load_oracle()
    # GENUINELY-MALFORMED sequences only (CSI with no final byte, truncated
    # UTF-8, OSC with no terminator). A well-formed-but-extreme cursor move like
    # \x1b[999A is NOT garbage — modeling it clamp-free is the correct repair, so
    # it does not belong in the defensive floor (its faithful handling can move
    # content off the intended grid exactly as the intended grid demands).
    samples = [
        b"plain text with no escapes at all",
        b"line one\r\nline two\r\nline three",
        b"text \x1b[1mbold\x1b[22m more text",
        b"garbage\x1b[ followed by real words",     # CSI with a non-final next byte
        b"unicode caf\xc3\xa9 r\xc3\xa9sum\xc3\xa9 \xe2\x9c\x93 done",
        b"\x1b]8;;http://example.com\x07linked\x1b]8;;\x07 text",
        b"stacked\x1b[\x1b[ then text",              # back-to-back malformed introducers
    ]
    for s in samples:
        repaired = repair_whole(mod, s)
        rep_glyphs = _visible_glyph_count(vt, repaired)
        raw_glyphs = _visible_glyph_count(vt, s)
        check(rep_glyphs >= raw_glyphs,
              f"DW-1.3: repaired glyph count ({rep_glyphs}) must not be below "
              f"passthrough ({raw_glyphs}) for {s!r}")


def test_DW_1_3_garbage_then_real_content_still_renders(mod):
    # After a garbage span, real content must still reach the grid (robustness:
    # one bad sequence doesn't poison the rest of the stream). The garbage here
    # is an incomplete CSI whose next byte is a SPACE (never a valid CSI final),
    # so the malformed introducer is swallowed inertly and the words survive —
    # and ScreenRepair must reproduce exactly the oracle's intended grid for it.
    vt = load_oracle()
    stream = b"\x1b[ \x1b[ REAL_CONTENT after the garbage"
    repaired = repair_whole(mod, stream)
    got = _clamp_grid(vt, repaired)
    intent = _noclamp_grid(vt, stream)
    eq(got, intent,
       "DW-1.3: clamp(repair) of a garbage-then-text stream must equal the intended grid")
    check("REAL_CONTENT" in got,
          "DW-1.3: real content after a garbage CSI span must still render")


# ==========================================================================
# DW-1.4: Pure / clockless — no time/Date/random in the class; feed is a
#         deterministic function of (state, bytes): same input → same output
#         across two fresh instances.
# ==========================================================================
def test_DW_1_4_deterministic_across_instances(mod):
    # Two independent instances fed the SAME chunked input must emit identical
    # bytes — proving feed depends only on (state, bytes), no hidden clock/random.
    for fn in captures():
        raw = open(fn, "rb").read()
        a = repair_random_chunks(mod, raw, seed=5)
        b = repair_random_chunks(mod, raw, seed=5)
        eq(a, b, f"DW-1.4: two instances must emit identical bytes for "
                 f"{os.path.basename(fn)} (deterministic feed)")
    # Also at the smallest synthetic scale.
    s = b"abc\r\ndef\x1b[2Aghi\x1b[1mX\x1b[22m"
    one = repair_one_byte(mod, s)
    whole = repair_whole(mod, s)
    # Whole vs 1-byte need not be byte-identical (diff vs full-repaint timing),
    # but two runs of the SAME chunking must be.
    eq(repair_one_byte(mod, s), one, "DW-1.4: 1-byte feed is reproducible")
    eq(repair_whole(mod, s), whole, "DW-1.4: whole feed is reproducible")


def test_DW_1_4_no_clock_or_random_in_class(mod):
    # Source-level guard: the ScreenRepair class body must not reference time,
    # datetime, or random — it is pure and clockless like FrameMux.
    import ast
    src = open(WRAP, "rb").read().decode()
    tree = ast.parse(src)
    cls = next((n for n in ast.walk(tree)
                if isinstance(n, ast.ClassDef) and n.name == "ScreenRepair"), None)
    check(cls is not None, "DW-1.4: ScreenRepair class must be defined in the wrapper")
    if cls is not None:
        banned = {"time", "datetime", "random", "monotonic", "perf_counter",
                  "clock", "now", "today", "gettimeofday"}
        used = set()
        for node in ast.walk(cls):
            if isinstance(node, ast.Name):
                used.add(node.id)
            elif isinstance(node, ast.Attribute):
                used.add(node.attr)
        leaked = used & banned
        check(not leaked,
              f"DW-1.4: ScreenRepair must not use clock/random names; found {sorted(leaked)}")


def test_DW_1_4_import_has_no_side_effects(mod):
    # Importing the module in a fresh interpreter must not write to stdout/stderr
    # or spawn anything, and ScreenRepair must be constructible + a no-op on b''.
    code = (
        "import importlib.util\n"
        f"spec = importlib.util.spec_from_file_location('w', {WRAP!r})\n"
        "m = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(m)\n"
        "assert hasattr(m, 'ScreenRepair')\n"
        "sr = m.ScreenRepair(41, 129)\n"
        "assert sr.feed(b'') == b''\n"
        "assert sr.drain() == b''\n"
        "assert sr.has_pending() is False\n"
    )
    res = subprocess.run([sys.executable, "-c", code], capture_output=True)
    eq(res.returncode, 0, f"DW-1.4: clean import/construct failed: {res.stderr.decode()!r}")
    eq(res.stdout, b"", "DW-1.4: importing the module must print nothing to stdout")
    eq(res.stderr, b"", "DW-1.4: importing the module must print nothing to stderr")


# ==========================================================================
# Beyond the DW floor: edge cases the implementation surfaced.
# ==========================================================================
def test_edge_empty_feed_is_noop(mod):
    sr = mod.ScreenRepair(ROWS, COLS)
    eq(sr.feed(b""), b"", "empty feed with no held tail is a no-op")
    check(not sr.has_pending(), "empty feed must not leave a pending tail")
    eq(sr.drain(), b"", "drain on a fresh instance is a no-op")


def test_edge_drain_idempotent(mod):
    sr = mod.ScreenRepair(ROWS, COLS)
    sr.feed(b"hello")
    sr.drain()
    eq(sr.drain(), b"", "drain is idempotent once the held tail is flushed")


def test_edge_held_tail_reports_pending(mod):
    # A trailing incomplete UTF-8 char is held; has_pending must report it so the
    # I/O loop's idle backstop knows to drain.
    sr = mod.ScreenRepair(ROWS, COLS)
    sr.feed(b"caf\xc3")              # 2-byte char start, continuation missing
    check(sr.has_pending(), "an incomplete trailing UTF-8 char must be held (pending)")
    out = sr.feed(b"\xa9!")           # completes 'é', then '!'
    check(not sr.has_pending(), "completing the char clears the pending tail")
    check(b"!" in out or sr.drain(),
          "the completed content eventually emits")


def test_edge_osc_hyperlink_not_dumped_into_grid(mod):
    # A long OSC 7/8 hyperlink split across 1-byte feeds must NOT leak its URL
    # body into the visible grid as text. (This was the real bug found in build:
    # a too-small holdback bound released the OSC body as printable glyphs.)
    vt = load_oracle()
    url = b"file://Ryans-Mac-Studio.local/private/tmp/some/deep/path/here"
    stream = b"prompt " + b"\x1b]7;" + url + b"\x07" + b"text"
    repaired = repair_one_byte(mod, stream)
    grid = _clamp_grid(vt, repaired)
    check("file://" not in grid,
          "DW-1.3/edge: an OSC hyperlink URL must never leak into the visible grid")
    check("prompt" in grid and "text" in grid,
          "edge: surrounding real text around the OSC must still render")


def test_edge_reset_clears_state(mod):
    # reset() (used by Phase 2's SIGWINCH path) must clear pending state and
    # resize cleanly — no stranded half-parsed token, no stale grid.
    sr = mod.ScreenRepair(ROWS, COLS)
    sr.feed(b"some text\x1b[1mbold")
    sr.feed(b"\xc3")                  # leave a pending tail
    check(sr.has_pending(), "precondition: a tail is pending before reset")
    sr.reset(50, 100)
    check(not sr.has_pending(), "reset must clear any held tail")
    eq(sr.feed(b""), b"", "reset leaves a clean, empty instance")


def test_edge_resize_geometry_applies(mod):
    sr = mod.ScreenRepair(ROWS, COLS)
    sr.reset(10, 20)
    check(sr.H == 10 and sr.W == 20, "reset must apply the new geometry")
    # A degenerate 0x0 resize is clamped to at least 1x1 (never divides by zero
    # or builds an empty grid that later index math would trip on).
    sr.reset(0, 0)
    check(sr.H >= 1 and sr.W >= 1, "reset must clamp degenerate geometry to >= 1x1")


def test_edge_sgr_run_survives_reposition(mod):
    # An SGR run spanning a cursor reposition (CUP) must be re-emitted so the
    # colored cells on BOTH rows keep their color. This is the exact edge case
    # the plan lists ("SGR run spanning a repositioning: re-emit active SGR after
    # each CUP") and that the REVIEW flagged as unhandled.
    vt = load_oracle()
    # red turned on, then text, then CUP to row 2, then more text — still red.
    stream = b"\x1b[31m\x1b[1;1HAAA\x1b[2;1HBBB\x1b[39m"
    repaired = repair_whole(mod, stream)
    # 1) Color survives: per-cell color of the repair == claude's intent.
    eq(_clamp_styled(vt, repaired), _noclamp_styled(vt, stream),
       "edge: an SGR run spanning a CUP must reproduce claude's per-cell color")
    # 2) Concretely, the red SGR byte token must appear in the repaired output
    #    (not dropped), and BOTH AAA and BBB must be styled red in the grid.
    check(b"\x1b[31m" in repaired,
          "edge: the original red SGR token must be re-emitted in the repair")
    m = vt.VT(ROWS, COLS, clamp=True)
    m.feed(repaired)
    red = ('idx', 31)
    # row 0 col 0 (AAA) and row 1 col 0 (BBB) both carry the red fg key.
    check(m.sty[0][0][2] is None and m.sty[0][0][1] == red,
          "edge: AAA on row 1 must be red after repair")
    check(m.sty[1][0][1] == red,
          "edge: BBB on row 2 (after the reposition) must STILL be red after repair")


def test_color_preserved_on_capture(mod):
    # On a REAL capture, claude's inline-code color (\x1b[38;5;153m) and a bold
    # run (\x1b[1m...\x1b[22m) must survive repair: the SGR bytes must be present
    # in the repaired output, and the colored cells must land at the right place
    # (asserted via the color-aware styled_grid equality). This is the regression
    # the REVIEW caught: the old emitter dropped ALL color.
    vt = load_oracle()
    for fn in captures():
        raw = open(fn, "rb").read()
        repaired = repair_whole(mod, raw)
        nsgr = _count_sgr(repaired)
        # Color is present at all (the monochrome bug emitted zero SGR).
        check(nsgr > 0,
              f"color: repaired {os.path.basename(fn)} must contain SGR tokens "
              f"(got {nsgr}); the monochrome bug emitted zero")
        # And it lands correctly: per-cell color equals claude's intent.
        eq(_clamp_styled(vt, repaired), _noclamp_styled(vt, raw),
           f"color: clamp(repair).styled_grid() must equal claude-intent for {os.path.basename(fn)}")
    # The xterm capture specifically carries the inline-code 153m needle; assert
    # its color reaches the repaired output for that capture.
    xterm = [f for f in captures() if "xterm" in f]
    if xterm:
        raw = open(xterm[0], "rb").read()
        if b"\x1b[38;5;153m" in raw:
            repaired = repair_whole(mod, raw)
            # The inline-code color token (256-color 153) must reach the repaired
            # output FAITHFULLY — its exact original bytes, so downstream
            # apply_subs (\x1b[38;5;153m -> orange) still matches in Phase 2. The
            # cells it colors may live in scrollback (claude scrolled them off),
            # so we assert on the emitted bytes, not the final viewport.
            check(b"\x1b[38;5;153m" in repaired,
                  "color: inline-code 256-color 153 token must survive repair on the xterm capture")


def test_monochrome_repair_would_fail_color_gate(mod):
    # Guard that the color-aware gate is NON-VACUOUS: stripping every SGR token
    # from the repaired stream (simulating the OLD monochrome emitter) must make
    # the styled_grid() invariant FAIL on a corrupted capture. If this ever
    # passes, the color gate has gone blind and is no longer protecting anything.
    vt = load_oracle()
    proved = False
    for fn in captures():
        raw = open(fn, "rb").read()
        repaired = repair_whole(mod, raw)
        mono = _strip_sgr(repaired)              # what the monochrome bug emitted
        intent = _noclamp_styled(vt, raw)
        if _clamp_styled(vt, mono) != intent and _clamp_styled(vt, repaired) == intent:
            proved = True
    check(proved,
          "color gate must be non-vacuous: a monochrome repair must FAIL styled_grid() "
          "on at least one colored capture while the real repair passes")


def test_edge_no_scroll_uses_cheap_diff(mod):
    # When nothing scrolls, only changed rows are repainted — steady typing stays
    # cheap. Feed two rows, then change only row 2; the second emit must touch
    # row 2 and not repaint row 1.
    sr = mod.ScreenRepair(ROWS, COLS)
    sr.feed(b"\x1b[1;1Hfirst row\x1b[2;1Hsecond row")
    out2 = sr.feed(b"\x1b[2;1Hsecond row CHANGED")
    check(b"\x1b[2;1H" in out2, "edge: changed row 2 must be repainted")
    check(b"first row" not in out2, "edge: unchanged row 1 must not be repainted (cheap diff)")


def test_edge_py_compile_clean(mod):
    res = subprocess.run([sys.executable, "-m", "py_compile", WRAP], capture_output=True)
    eq(res.returncode, 0,
       f"edge: py_compile must be clean (stderr: {res.stderr.decode()!r})")


def test_edge_test_file_is_stdlib_only(mod):
    import ast
    src = open(os.path.join(HERE, "test-screenrepair.py"), "rb").read().decode()
    tree = ast.parse(src)
    stdlib = {"glob", "importlib", "os", "random", "re", "subprocess", "sys", "ast"}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                imported.add(n.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    thirdparty = imported - stdlib
    check(not thirdparty,
          f"edge: test file must be stdlib-only; unexpected imports: {sorted(thirdparty)}")


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

    print(f"ran {len(tests)} ScreenRepair tests")
    if _FAILS:
        print(f"\nFAIL: {len(_FAILS)} assertion(s) failed:", file=sys.stderr)
        for f in _FAILS:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("OK: all ScreenRepair tests pass.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
