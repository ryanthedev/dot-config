#!/usr/bin/env python3
"""Unit + REAL-terminal tests for the Insulator engine in claude-theme-wrap.py.

Phase 3 of the insulation layer. The Insulator consumes claude's byte stream
through the canonical VT500Parser, drives a clamp-free Screen from the typed
events, forwards the control plane verbatim at its correct stream position, and
re-renders the intent grid via absolute positioning. These tests prove the five
Phase-3 Done-When invariants, the correctness-critical ones gated by the
Phase-1 REAL-terminal oracle (tmux capture-pane), NOT a self-authored model:

  DW-3.1 TRANSPARENCY  - every `correct` corpus stream renders grid-identical to
                         raw in a REAL terminal (incl. startup: no leak, control
                         plane present).
  DW-3.2 CORRECTION    - the `buggy` stream renders to the FROZEN intent grid in
                         a REAL terminal (the clamp corruption is gone).
  DW-3.3 CONTROL PLANE - the control plane is forwarded verbatim WITH ORDERING:
                         each forwarded query/mode sits at its correct stream
                         position (between the cells before and after it), not
                         deferred past a flush. Presence alone is not enough.
  DW-3.4 THEMING       - inline-code/italic/bold SGR survives into the output so
                         apply_subs re-themes it; scrollback lines are preserved
                         in order.
  DW-3.5 DEFENSIVE     - malformed input never raises; feed is deterministic
                         across two instances and across whole/1-byte/random
                         chunking (real-terminal grid identical).

The wrapper is imported as a module (the way the other test-*.py do), proving
Insulator is importable and side-effect-free at load.

Run:  python3 ~/.config/claude/wrap/test-insulator.py
Exit: 0 all pass, 1 a behavioral assertion failed, 2 driver error.
A test needing a REAL terminal is SKIPPED (not failed) when tmux is absent.
"""
import importlib.util
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WRAP = os.path.join(HERE, "claude-theme-wrap.py")
CORPUS = os.path.join(HERE, "testdata", "corpus")


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


M = load_wrapper()
H = load_harness()


# ---- chunking helpers (the adversarial cases the parser/emitter must survive) --
def insu_whole(stream, rows, cols):
    ins = M.Insulator(rows, cols)
    return ins.feed(stream) + ins.drain()


def insu_one_byte(stream, rows, cols):
    ins = M.Insulator(rows, cols)
    out = bytearray()
    for b in stream:
        out += ins.feed(bytes([b]))
    out += ins.drain()
    return bytes(out)


def insu_random(stream, rows, cols, seed=1337):
    rng = random.Random(seed)
    ins = M.Insulator(rows, cols)
    out = bytearray()
    i = 0
    n = len(stream)
    while i < n:
        step = rng.randint(1, 7)
        out += ins.feed(stream[i:i + step])
        i += step
    out += ins.drain()
    return bytes(out)


def repair_factory(rows, cols, chunker=insu_whole):
    """A repair_fn closure (bytes->bytes) the Phase-1 predicates accept."""
    return lambda data: chunker(data, rows, cols)


def corpus_fixtures():
    out = []
    for fx in H.load_corpus():
        with open(os.path.join(CORPUS, fx["file"]), "rb") as f:
            out.append((fx, f.read()))
    return out


# =========================================================================
# DW-3.1 TRANSPARENCY (REAL terminal) — every correct stream, incl. startup
# =========================================================================
def test_DW_3_1_transparency_all_correct_corpus():
    if not H.tmux_available():
        print("  SKIP DW-3.1 transparency: tmux not available")
        return
    for fx, stream in corpus_fixtures():
        if fx["label"] != "correct":
            continue
        cols, rows = fx["cols"], fx["rows"]
        rep = repair_factory(rows, cols)
        assert H.assert_transparent(rep, stream, cols, rows), \
            f"DW-3.1 NON-transparent on correct fixture {fx['file']}"


def test_DW_3_1_startup_no_leak_in_output():
    """The startup capture must yield NO leaked control sequence as a printable
    glyph in the re-rendered grid: the box-drawing UI is intact, and the kitty/
    DA/OSC bytes appear only in the forwarded control plane, never as text."""
    if not H.tmux_available():
        print("  SKIP DW-3.1 no-leak: tmux not available")
        return
    with open(os.path.join(CORPUS, "startup.bin"), "rb") as f:
        stream = f.read()
    grid = H.render_real(insu_whole(stream, 41, 129), 129, 41)
    flat = "\n".join(grid)
    # No raw ESC byte and no obvious leaked introducer text in the visible grid.
    assert "\x1b" not in flat, "DW-3.1 leak: raw ESC visible in startup grid"
    for needle in (">1u", "?2004", "?25", "[?1049", "8;;file://"):
        assert needle not in flat, f"DW-3.1 leak: {needle!r} rendered as text"


# =========================================================================
# DW-3.2 CORRECTION (REAL terminal) — the buggy stream renders to frozen intent
# =========================================================================
def test_DW_3_2_correction_all_buggy_corpus():
    if not H.tmux_available():
        print("  SKIP DW-3.2 correction: tmux not available")
        return
    found_buggy = False
    for fx, stream in corpus_fixtures():
        if fx["label"] != "buggy":
            continue
        found_buggy = True
        cols, rows = fx["cols"], fx["rows"]
        intent = H.load_intent(fx)
        rep = repair_factory(rows, cols)
        assert H.assert_corrected(rep, stream, intent, cols, rows), \
            f"DW-3.2 NOT corrected to frozen intent on {fx['file']}"
    assert found_buggy, "DW-3.2 corpus has no buggy fixture to correct"


# =========================================================================
# DW-3.3 CONTROL PLANE — forwarded verbatim WITH ORDERING (not just presence)
# =========================================================================
def test_DW_3_3_startup_control_plane_present():
    """Every control-plane sequence claude emits at startup must appear VERBATIM
    in the Insulator's output (dropping any of these breaks/hangs claude)."""
    with open(os.path.join(CORPUS, "startup.bin"), "rb") as f:
        stream = f.read()
    out = insu_whole(stream, 41, 129)
    for needle in (b"\x1b[c",        # Primary DA query (hang if dropped)
                   b"\x1b[?2004h", b"\x1b[?2004l",  # bracketed paste
                   b"\x1b[?25h", b"\x1b[?25l",      # cursor visibility
                   b"\x1b[>1u", b"\x1b[<u"):        # kitty keyboard push/pop
        assert needle in out, f"DW-3.3 control plane DROPPED: {needle!r}"
    assert b"\x1b]" in out, "DW-3.3 OSC dropped from startup output"


def test_DW_3_3_ordering_query_between_two_cells():
    """ORDERING gate: a forwarded query that sits BETWEEN two printed cells in
    the stream must appear in the output BETWEEN the render of the first cell and
    the render of the second — not deferred to the end of the flush (the prior
    regression). We print 'A', then a DA query, then 'B'."""
    ins = M.Insulator(10, 40)
    out = ins.feed(b"A\x1b[cB") + ins.drain()
    qi = out.find(b"\x1b[c")
    assert qi != -1, "DW-3.3 query missing from output"
    # The query must appear AFTER the first paint of 'A' ...
    first_a = out.find(b"A")
    assert 0 <= first_a < qi, "DW-3.3 query emitted before 'A' was painted"
    # ... and BEFORE the final segment that paints 'B' (the 'B' glyph only ever
    # appears in a repaint that comes AFTER the query).
    bi = out.find(b"B")
    assert bi > qi, "DW-3.3 query deferred PAST the 'B' render (wrong order)"


def test_DW_3_3_da_before_next_token_render():
    """A DA query between two distinct text tokens lands before the second
    token's rendered bytes — verified with a multi-char interleave."""
    ins = M.Insulator(5, 40)
    out = ins.feed(b"XY\x1b[6nZW") + ins.drain()
    qi = out.find(b"\x1b[6n")
    assert qi != -1, "DW-3.3 DSR query missing"
    # 'Z' and 'W' are only printed in the post-query repaint segment.
    zw = out.rfind(b"ZW")
    assert zw == -1 or zw > qi, "DW-3.3 DSR query deferred past later tokens"


def test_DW_3_3_query_not_lost_across_feed_boundary():
    """A query split across feed calls is still forwarded exactly once, in order."""
    ins = M.Insulator(5, 40)
    out = ins.feed(b"A\x1b[") + ins.feed(b"cB") + ins.drain()
    assert out.count(b"\x1b[c") == 1, "DW-3.3 split query lost or duplicated"


# =========================================================================
# DW-3.4 THEMING composes + scrollback preserved in order
# =========================================================================
def test_DW_3_4_sgr_survives_for_apply_subs():
    """inline-code (38;5;153m), bold (Bash), and italic SGR must survive into the
    output as PAIRED tokens so the downstream apply_subs needles still match."""
    ins = M.Insulator(10, 60)
    out = ins.feed(b"\x1b[38;5;153minline\x1b[39m "
                   b"\x1b[1mBash\x1b[22m \x1b[3mital\x1b[23m") + ins.drain()
    assert b"\x1b[38;5;153m" in out, "DW-3.4 256-color fg token lost"
    assert b"\x1b[1m" in out and b"\x1b[22m" in out, "DW-3.4 bold pair lost"
    assert b"\x1b[3m" in out and b"\x1b[23m" in out, "DW-3.4 italic pair lost"


def test_DW_3_4_themed_word_pair_roundtrips_at_row_end():
    """A bold word that is the LAST styled glyph on a row must close with the
    precise off-token (\x1b[22m), not a blanket reset, so \x1b[1mBash\x1b[22m
    stays paired for apply_subs."""
    ins = M.Insulator(5, 40)
    out = ins.feed(b"see \x1b[1mBash\x1b[22m") + ins.drain()
    # The emitter closes the row with 22 (bold off), never stranding the 1m.
    assert b"\x1b[1m" in out and b"\x1b[22m" in out, "DW-3.4 row-end bold unpaired"
    assert b"\x1b[0mBash" not in out, "DW-3.4 used blanket reset, breaks needle"


def test_DW_3_4_scrollback_lines_preserved_in_order():
    """The synthetic long-scroll: lines that scroll off the top must be emitted
    (bottom-row + CRLF) in their original order so tmux scrollback history is
    faithful."""
    with open(os.path.join(CORPUS, "scroll.bin"), "rb") as f:
        stream = f.read()
    out = insu_whole(stream, 41, 129)
    i0 = out.find(b"line 000")
    i1 = out.find(b"line 001")
    i2 = out.find(b"line 002")
    assert -1 < i0 < i1 < i2, "DW-3.4 scrollback lines out of order"


def test_DW_3_4_scrollback_real_terminal_grid():
    """REAL-terminal check: the final visible grid after the long scroll shows the
    LAST window of lines (the scrolled-off ones are in history, not the view)."""
    if not H.tmux_available():
        print("  SKIP DW-3.4 scrollback grid: tmux not available")
        return
    with open(os.path.join(CORPUS, "scroll.bin"), "rb") as f:
        stream = f.read()
    grid = H.render_real(insu_whole(stream, 41, 129), 129, 41)
    assert grid and grid[0].startswith("line 040"), \
        f"DW-3.4 scrolled view wrong top row: {grid[0]!r}"


# =========================================================================
# DW-3.5 DEFENSIVE / DETERMINISM
# =========================================================================
_GARBAGE = [
    b"\x1b[<<<<m",                       # malformed CSI (private after params)
    b"\x1b]999999",                      # never-terminated OSC
    b"\x1bP" + b"x" * 100,               # never-terminated DCS
    bytes(range(256)),                   # every byte value
    b"\xff\xfe\xc0\xc1",                 # invalid UTF-8 lead bytes
    b"\x1b" * 50,                        # ESC storm
    b"\x1b[999999999999A" + b"text",     # absurd cursor move
    b"\x1bk" + b"t" * 5000,              # runaway title string
]


def test_DW_3_5_malformed_never_raises():
    for bad in _GARBAGE:
        for chunker in (insu_whole, insu_one_byte, insu_random):
            try:
                chunker(bad, 10, 40)
            except Exception as e:  # noqa: BLE001 - the whole point is no raise
                raise AssertionError(
                    f"DW-3.5 feed RAISED on {bad[:12]!r}/{chunker.__name__}: "
                    f"{type(e).__name__}: {e}")


def test_DW_3_5_feed_returns_bytes_on_garbage():
    for bad in _GARBAGE:
        out = insu_whole(bad, 10, 40)
        assert isinstance(out, (bytes, bytearray)), \
            f"DW-3.5 feed returned non-bytes on {bad[:12]!r}"


def test_DW_3_5_determinism_two_instances():
    """Two fresh Insulators fed the same stream produce byte-identical output —
    pure/clockless, no hidden state."""
    for fx, stream in corpus_fixtures():
        a = insu_whole(stream, fx["rows"], fx["cols"])
        b = insu_whole(stream, fx["rows"], fx["cols"])
        assert a == b, f"DW-3.5 non-deterministic output on {fx['file']}"


def test_DW_3_5_chunk_determinism_internal_grid():
    """The internal intent grid is identical across whole/1-byte/random chunking
    (byte output may differ, but the modeled screen must not)."""
    for fx, stream in corpus_fixtures():
        rows, cols = fx["rows"], fx["cols"]
        # build three models and compare their internal grids
        gw = _model_grid(stream, rows, cols, insu_feed_whole)
        g1 = _model_grid(stream, rows, cols, insu_feed_1b)
        gr = _model_grid(stream, rows, cols, insu_feed_rand)
        assert gw == g1 == gr, \
            f"DW-3.5 internal grid differs across chunking on {fx['file']}"


def test_DW_3_5_chunk_determinism_real_terminal_grid():
    """The REAL-terminal grid is identical across whole/1-byte/random chunking —
    the strongest determinism gate (output bytes differ, rendered grid must not)."""
    if not H.tmux_available():
        print("  SKIP DW-3.5 chunk real-terminal grid: tmux not available")
        return
    for fx, stream in corpus_fixtures():
        rows, cols = fx["rows"], fx["cols"]
        gw = H.render_real(insu_whole(stream, rows, cols), cols, rows)
        g1 = H.render_real(insu_one_byte(stream, rows, cols), cols, rows)
        gr = H.render_real(insu_random(stream, rows, cols), cols, rows)
        assert gw == g1 == gr, \
            f"DW-3.5 real-terminal grid differs across chunking on {fx['file']}"


# -- helpers for the internal-grid determinism check --------------------------
def insu_feed_whole(ins, stream):
    ins.feed(stream)
    ins.drain()


def insu_feed_1b(ins, stream):
    for b in stream:
        ins.feed(bytes([b]))
    ins.drain()


def insu_feed_rand(ins, stream, seed=99):
    rng = random.Random(seed)
    i = 0
    n = len(stream)
    while i < n:
        step = rng.randint(1, 7)
        ins.feed(stream[i:i + step])
        i += step
    ins.drain()


def _model_grid(stream, rows, cols, feeder):
    ins = M.Insulator(rows, cols)
    feeder(ins, stream)
    return [''.join(r) for r in ins._screen._g]


# =========================================================================
# Bonus / edge coverage beyond the DW floor
# =========================================================================
def test_bonus_alt_screen_passthrough():
    """When claude enters the alternate buffer (?1049h), the Insulator STEPS
    ASIDE: alt-buffer bytes are forwarded VERBATIM (not re-rendered) until the
    matching ?1049l exit."""
    ins = M.Insulator(10, 40)
    out = ins.feed(b"main\x1b[?1049hALT\x1b[5;5Hxyz\x1b[?1049ldone") + ins.drain()
    assert b"\x1b[?1049h" in out and b"\x1b[?1049l" in out, "alt enter/exit lost"
    assert b"ALT" in out and b"\x1b[5;5H" in out, "alt-buffer bytes not verbatim"


def test_bonus_alt_screen_47_variant():
    ins = M.Insulator(10, 40)
    out = ins.feed(b"\x1b[?47hRAW\x1b[?47l") + ins.drain()
    assert b"RAW" in out and b"\x1b[?47h" in out and b"\x1b[?47l" in out, \
        "?47 alt-screen passthrough failed"


def test_bonus_has_pending_and_drain():
    ins = M.Insulator(5, 10)
    assert not ins.has_pending(), "fresh Insulator should not be pending"
    ins.feed(b"\x1b[")                       # partial CSI held by the parser
    assert ins.has_pending(), "partial CSI should be pending"
    ins.drain()
    assert not ins.has_pending(), "drain should clear pending"
    ins.feed(b"\xe2\x9c")                    # partial UTF-8
    assert ins.has_pending(), "partial UTF-8 should be pending"
    ins.drain()
    assert not ins.has_pending(), "drain should clear UTF-8 pending"


def test_bonus_reset_clears_state():
    ins = M.Insulator(5, 10)
    ins.feed(b"hello\x1b[")
    ins.reset(8, 20)
    assert not ins.has_pending(), "reset must clear held partial token"
    # A fresh feed after reset works at the new size.
    out = ins.feed(b"X") + ins.drain()
    assert b"X" in out, "Insulator broken after reset"


def test_bonus_osc_utf8_st_not_terminated_early():
    """A UTF-8 byte 0x9c inside an OSC title (e.g. ✳ = e2 9c b3) must NOT be read
    as the 8-bit ST terminator — the leak that put OSC-title text into the GRID.
    The title is forwarded verbatim (it is control plane), but it must NEVER be
    rendered as grid text: the rendered grid shows only 'AB'."""
    if not H.tmux_available():
        print("  SKIP osc-utf8-st: tmux not available")
        return
    grid = H.render_real(
        insu_whole(b"A\x1b]0;\xe2\x9c\xb3 title\x07B", 5, 40), 40, 5)
    flat = "\n".join(grid)
    assert "title" not in flat, "OSC title leaked into grid (0x9c misread as ST)"
    assert flat.replace("\n", "").strip() == "AB", \
        f"OSC title perturbed the grid: {grid!r}"


def test_bonus_esc_k_title_body_consumed():
    """ESC k <title> ST (screen/tmux window title) must not be RENDERED as grid
    text — matches what the real tmux oracle does (it consumes the body). The
    bytes are forwarded verbatim, but the rendered grid shows only 'AB'."""
    if not H.tmux_available():
        print("  SKIP esc-k-title: tmux not available")
        return
    grid = H.render_real(insu_whole(b"A\x1bk/tmp\x1b\\B", 5, 40), 40, 5)
    flat = "\n".join(grid)
    assert "/tmp" not in flat, "ESC k title body rendered as grid text"
    assert flat.replace("\n", "").strip() == "AB", \
        f"ESC k title perturbed the grid: {grid!r}"


def test_bonus_empty_feed_is_empty():
    ins = M.Insulator(5, 10)
    assert ins.feed(b"") == b"", "empty feed should produce no output"
    assert ins.drain() == b"", "empty drain should produce no output"


def test_bonus_screenrepair_retired():
    """Phase 4 retires ScreenRepair: the Insulator is the sole output transform.
    The class (and its _SR_* regex helpers) must be GONE from the module so no
    dead, leaky parser can be reintroduced by accident."""
    assert not hasattr(M, "ScreenRepair"), "ScreenRepair must be retired in Phase 4"
    assert not hasattr(M, "_SR_CSI"), "ScreenRepair's _SR_* regexes must be removed too"
    # The Insulator carries the same public surface the loop depends on.
    ins = M.Insulator(10, 40)
    assert all(hasattr(ins, n) for n in ("feed", "drain", "reset", "has_pending")), \
        "Insulator must expose the feed/drain/reset/has_pending contract"


def main():
    if not os.path.isdir(CORPUS):
        print(f"FAIL: corpus dir missing: {CORPUS}", file=sys.stderr)
        return 2
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    fails = []
    for t in tests:
        try:
            t()
        except Exception as e:  # noqa: BLE001 - report, don't abort the suite
            fails.append(f"{t.__name__}: {type(e).__name__}: {e}")
    print(f"ran {len(tests)} Insulator tests")
    if fails:
        print(f"\nFAIL: {len(fails)} assertion(s) failed:", file=sys.stderr)
        for f in fails:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("OK: all Insulator tests pass.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
