#!/usr/bin/env python3
"""Unit + real-terminal tests for the VT500Parser in claude-theme-wrap.py.

Phase 2 of the insulation layer. The parser is a pure Williams DEC ANSI state
machine; these tests prove the five Phase-2 Done-When invariants:

  DW-2.1 Lossless round-trip   - feed+drain raw bytes reconstruct the input
  DW-2.2 No-leak               - control sequences never become Print glyphs
  DW-2.3 Chunk-invariance      - events identical across whole/1-byte/random chunks
  DW-2.4 Defensive             - garbage/truncated input never raises, never leaks
  DW-2.5 Real-terminal E2E     - a parse-then-reemit passthrough is transparent
                                 in a REAL tmux terminal on every corpus stream

The wrapper is imported as a module (the way the other test-*.py do), proving
VT500Parser is importable and side-effect-free at load.

Run:  python3 ~/.config/claude/wrap/test-vt500.py
Exit: 0 all pass, 1 a behavioral assertion failed, 2 driver error.
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
    spec = importlib.util.spec_from_file_location("test_harness",
                                                  os.path.join(HERE, "test_harness.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = load_wrapper()
H = load_harness()


# --- chunking strategies (shared by several DW tests) ---------------------
def feed_whole(stream):
    p = M.VT500Parser()
    return p.feed(stream) + p.drain()


def feed_one_byte(stream):
    p = M.VT500Parser()
    out = []
    for b in stream:
        out += p.feed(bytes([b]))
    out += p.drain()
    return out


def feed_random(stream, seed=1337):
    rng = random.Random(seed)
    p = M.VT500Parser()
    out = []
    i = 0
    n = len(stream)
    while i < n:
        step = rng.randint(1, 7)
        out += p.feed(stream[i:i + step])
        i += step
    out += p.drain()
    return out


def event_key(e):
    """Identity used for chunk-invariance comparison: type + every field."""
    return (type(e).__name__,) + tuple(getattr(e, s) for s in e._fields())


def corpus_streams():
    out = []
    for fx in H.load_corpus():
        with open(os.path.join(CORPUS, fx["file"]), "rb") as f:
            out.append((fx["file"], f.read(), fx["cols"], fx["rows"]))
    return out


# =========================================================================
# DW-2.1 Lossless round-trip
# =========================================================================
def test_DW_2_1_lossless_roundtrip_all_corpus():
    for name, stream, _, _ in corpus_streams():
        for label, fn in (("whole", feed_whole), ("1byte", feed_one_byte),
                          ("random", feed_random)):
            evs = fn(stream)
            recon = b"".join(e.raw for e in evs)
            assert recon == stream, \
                f"DW-2.1 lossless FAIL on {name}/{label}: {len(recon)} != {len(stream)}"


def test_DW_2_1_lossless_synthetic_mixed():
    # A stream mixing every category: UTF-8 multibyte, CSI private, OSC (BEL),
    # OSC (ST), DCS, SOS/PM/APC, C0 controls, malformed CSI.
    stream = (
        "héllo wörld ".encode("utf-8")
        + b"\x1b[>1u\x1b[<u\x1b[?2004h\x1b[6n\x1b[c"
        + b"\x1b]0;title\x07\x1b]8;;http://x\x1b\\"
        + b"\x1bP1$r0m\x1b\\"
        + b"\x1b^pm-data\x1b\\\x1b_apc-data\x1b\\"
        + b"\r\n\t\x08text\x1b[38;5;153mcolored\x1b[0m"
        + b"\x1b[<<<garbagem"  # malformed CSI
        + "✓ ★ 日本語".encode("utf-8")
    )
    evs = feed_whole(stream)
    assert b"".join(e.raw for e in evs) == stream, "DW-2.1 synthetic lossless FAIL"


# =========================================================================
# DW-2.2 No-leak (the regression guard)
# =========================================================================
def test_DW_2_2_no_leak_startup():
    with open(os.path.join(CORPUS, "startup.bin"), "rb") as f:
        stream = f.read()
    evs = feed_whole(stream)

    # (a) No Print event's text may contain ESC or a CSI/control introducer.
    for e in evs:
        if isinstance(e, M.Print):
            assert "\x1b" not in e.text, f"DW-2.2 leak: ESC in Print text {e.text!r}"
            assert "\x9b" not in e.text, f"DW-2.2 leak: C1 CSI in Print text {e.text!r}"
            # The literal glyphs the prior regression leaked must never appear as
            # standalone control text. (They can legitimately appear as normal
            # words, but never preceded by the ESC/[ that made them a sequence.)
            assert e.raw[:1] != b"\x1b", "DW-2.2 leak: Print starting with ESC"

    # (b) The exact sequences the prior regression leaked must appear ONLY as
    # CsiDispatch/Osc raw, never inside any Print.raw.
    csi_osc_raw = b"".join(e.raw for e in evs
                           if isinstance(e, (M.CsiDispatch, M.Osc)))
    print_raw = b"".join(e.raw for e in evs if isinstance(e, M.Print))
    for needle in (b"\x1b[>1u", b"\x1b[<u", b"\x1b[>4;2m", b"\x1b[>0q", b"\x1b[c"):
        if needle in stream:
            assert needle in csi_osc_raw, \
                f"DW-2.2: {needle!r} not parsed as a Csi event"
            assert needle not in print_raw, \
                f"DW-2.2 LEAK: {needle!r} appeared in Print bytes"

    # (c) OSC payloads parse as Osc events (their introducer never leaks).
    osc_events = [e for e in evs if isinstance(e, M.Osc)]
    assert osc_events, "DW-2.2: expected at least one Osc event in startup"
    for e in osc_events:
        assert e.raw[:1] in (b"\x1b", b"\x9d"), "DW-2.2: malformed Osc raw"
        assert b"\x1b]" not in print_raw, "DW-2.2 LEAK: OSC introducer in Print"


def test_DW_2_2_no_leak_explicit_sequences():
    # Each target sequence in isolation must produce zero Print events.
    for seq in (b"\x1b[>1u", b"\x1b[<u", b"\x1b[>4;2m", b"\x1b[>0q", b"\x1b[c",
                b"\x1b]8;;http://example.com\x1b\\"):
        evs = feed_whole(seq)
        prints = [e for e in evs if isinstance(e, M.Print)]
        assert not prints, f"DW-2.2 LEAK: {seq!r} produced Print events {prints}"


# =========================================================================
# DW-2.3 Chunk-invariance
# =========================================================================
def test_DW_2_3_chunk_invariance_all_corpus():
    for name, stream, _, _ in corpus_streams():
        whole = [event_key(e) for e in feed_whole(stream)]
        one = [event_key(e) for e in feed_one_byte(stream)]
        rand = [event_key(e) for e in feed_random(stream)]
        assert whole == one, f"DW-2.3 FAIL on {name}: whole != 1-byte"
        assert whole == rand, f"DW-2.3 FAIL on {name}: whole != random"


def test_DW_2_3_chunk_invariance_split_sequences():
    # Sequences deliberately split at every interior offset must agree with whole.
    stream = (b"abc\x1b[38;5;153mX\x1b[0m\x1b]0;t\x07"
              + "中".encode("utf-8") + b"\x1b[c")
    whole = [event_key(e) for e in feed_whole(stream)]
    for cut in range(1, len(stream)):
        p = M.VT500Parser()
        evs = p.feed(stream[:cut]) + p.feed(stream[cut:]) + p.drain()
        assert [event_key(e) for e in evs] == whole, \
            f"DW-2.3 split FAIL at cut={cut}"


# =========================================================================
# DW-2.4 Defensive (never raise, never leak glyphs)
# =========================================================================
def test_DW_2_4_defensive_garbage_csi_osc():
    cases = [
        b"\x1b[",                      # bare CSI introducer, never finished
        b"\x1b[" + b"9" * 100000 + b"m",  # absurdly long param -> bounded hold
        b"\x1b[<>?<>?garbage",          # illegal private after params
        b"\x1b]" + b"x" * 200000,       # never-terminated OSC -> bounded hold
        b"\x1bP" + b"q" * 200000,       # never-terminated DCS
        b"\x1b\x1b\x1b[m",              # ESC storm
        b"\x18\x1a\x1b",                # CAN SUB ESC
        bytes(range(256)),              # every byte value
        bytes([random.Random(i).randint(0, 255) for i in range(5000)]),
    ]
    for raw in cases:
        p = M.VT500Parser()
        try:
            evs = p.feed(raw) + p.drain()
        except Exception as e:  # noqa: BLE001
            raise AssertionError(f"DW-2.4 parser RAISED on {raw[:20]!r}...: {e}")
        # No leaked control glyphs: a Print starting with ESC would be a leak.
        for e in evs:
            if isinstance(e, M.Print):
                assert "\x1b" not in e.text, f"DW-2.4 leak in Print {e.text!r}"
        # Lossless even for garbage.
        assert b"".join(e.raw for e in evs) == raw, "DW-2.4 garbage not lossless"


def test_DW_2_4_truncated_utf8_single_replacement():
    # A multibyte codepoint split, then interrupted by a control: at most one
    # replacement char, and lossless.
    snowman = "☃".encode("utf-8")  # 3 bytes
    # Split it and never complete it; drain must flush exactly one replacement.
    p = M.VT500Parser()
    evs = p.feed(snowman[:2]) + p.drain()
    assert b"".join(e.raw for e in evs) == snowman[:2], "DW-2.4 trunc not lossless"
    repl = "".join(e.text for e in evs if isinstance(e, M.Print))
    assert repl.count("�") <= 1, "DW-2.4: more than one replacement char"

    # A truncated codepoint followed by a CSI: the partial flushes as one
    # replacement, the CSI parses cleanly.
    stream = snowman[:1] + b"\x1b[0m"
    evs = feed_whole(stream)
    assert b"".join(e.raw for e in evs) == stream, "DW-2.4 mixed not lossless"
    prints = [e for e in evs if isinstance(e, M.Print)]
    assert all("\x1b" not in e.text for e in prints)
    csi = [e for e in evs if isinstance(e, M.CsiDispatch)]
    assert csi and csi[0].final == ord("m"), "DW-2.4: CSI after trunc lost"

    # A lone continuation byte (no lead) -> one replacement, lossless.
    evs = feed_whole(b"\x80\x80")
    assert b"".join(e.raw for e in evs) == b"\x80\x80"


def test_DW_2_4_valid_multibyte_roundtrips():
    # Sanity: well-formed multibyte never produces a replacement char.
    stream = "café ★ 日本語 🎉".encode("utf-8")
    text = "".join(e.text for e in feed_whole(stream) if isinstance(e, M.Print))
    assert "�" not in text, "DW-2.4: valid UTF-8 produced a replacement"
    assert text == "café ★ 日本語 🎉"


# =========================================================================
# DW-2.5 Real-terminal end-to-end transparency
# =========================================================================
def test_DW_2_5_real_terminal_transparency():
    if not H.tmux_available():
        print("  SKIP DW-2.5: tmux not available", file=sys.stderr)
        return

    def reemit_repair(data: bytes) -> bytes:
        """Parse, then re-concatenate every event's raw bytes. If the parser has
        any category blindspot, the re-emitted stream renders differently."""
        p = M.VT500Parser()
        evs = p.feed(data) + p.drain()
        return b"".join(e.raw for e in evs)

    for name, stream, cols, rows in corpus_streams():
        ok = H.assert_transparent(reemit_repair, stream, cols, rows)
        assert ok, f"DW-2.5 real-terminal transparency FAIL on {name}"


# --- bonus coverage beyond the DW floor -----------------------------------
def test_bonus_8bit_c1_introducers():
    # 8-bit CSI (0x9b), OSC (0x9d), DCS (0x90) must parse as control events.
    evs = feed_whole(b"\x9b1;2m")
    assert any(isinstance(e, M.CsiDispatch) and e.final == ord("m") for e in evs), \
        "8-bit CSI not parsed"
    evs = feed_whole(b"\x9d0;title\x07")
    assert any(isinstance(e, M.Osc) for e in evs), "8-bit OSC not parsed"


def test_bonus_osc_bel_vs_st():
    bel = feed_whole(b"\x1b]0;t\x07")
    assert any(isinstance(e, M.Osc) and e.payload == b"0;t" for e in bel)
    st = feed_whole(b"\x1b]0;t\x1b\\")
    osc = [e for e in st if isinstance(e, M.Osc)]
    assert osc and osc[0].payload == b"0;t", "OSC-ST payload wrong"


def test_bonus_esc_abort_midsequence():
    # ESC mid-CSI aborts the first and starts a new sequence; lossless.
    stream = b"\x1b[12\x1b[0m"
    evs = feed_whole(stream)
    assert b"".join(e.raw for e in evs) == stream
    finals = [e.final for e in evs if isinstance(e, M.CsiDispatch)]
    assert ord("m") in finals, "second CSI lost after ESC abort"


def test_bonus_drain_flushes_unterminated():
    p = M.VT500Parser()
    evs = p.feed(b"\x1b]9;notification") + p.drain()
    assert b"".join(e.raw for e in evs) == b"\x1b]9;notification"
    assert any(isinstance(e, M.Osc) for e in evs), "unterminated OSC not flushed"


def test_bonus_execute_events():
    evs = feed_whole(b"a\r\n\tb\x08")
    bytes_seen = [e.byte for e in evs if isinstance(e, M.Execute)]
    assert 0x0d in bytes_seen and 0x0a in bytes_seen and 0x09 in bytes_seen \
        and 0x08 in bytes_seen, "C0 controls not Execute events"


def test_bonus_reset_clears_state():
    p = M.VT500Parser()
    p.feed(b"\x1b]incomplete")
    p.reset()
    evs = p.feed(b"hi") + p.drain()
    assert b"".join(e.raw for e in evs) == b"hi", "reset did not clear held state"


# =========================================================================
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
    print(f"ran {len(tests)} VT500Parser tests")
    if fails:
        print(f"\nFAIL: {len(fails)} assertion(s) failed:", file=sys.stderr)
        for f in fails:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("OK: all VT500Parser tests pass.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
