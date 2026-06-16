#!/usr/bin/env python3
"""Unit tests for the pure FrameMux primitive in claude-theme-wrap.py.

Drives FrameMux with synthetic byte streams — no live `claude`, no PTY, fully
deterministic. Imports the wrapper as a module exactly the way test-palette.py
does, so it also proves FrameMux is importable and side-effect-free at load.

Run:  python3 ~/.config/claude/wrap/test-framemux.py
Exit: 0 all pass, 1 a behavioral assertion failed (regression), 2 driver error.
"""
import importlib.util, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
WRAP = os.path.join(HERE, "claude-theme-wrap.py")


def load_wrapper():
    spec = importlib.util.spec_from_file_location("claude_theme_wrap", WRAP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- tiny assertion harness (no third-party deps) -------------------------
_FAILS = []


def check(cond, msg):
    if not cond:
        _FAILS.append(msg)


def eq(got, want, msg):
    if got != want:
        _FAILS.append(f"{msg}\n    got:  {got!r}\n    want: {want!r}")


# ==========================================================================
# DW-1.1: Complete frame in one chunk → returned in full, SUBS applied,
#         nothing emitted before its ESU is seen.
# ==========================================================================
def test_DW_1_1_complete_frame_one_chunk_atomic_with_subs(mod):
    inner = b'\x1b[1mBash\x1b[22m'                      # a real SUBS needle
    frame = mod.BSU + inner + mod.ESU
    out = mod.FrameMux().feed(frame)
    expected = mod.BSU + mod.apply_subs(inner) + mod.ESU
    eq(out, expected, "DW-1.1: complete frame must emit BSU + apply_subs(body) + ESU")
    check(mod.PALETTE['bash'] in out, "DW-1.1: bash SUB must appear in emitted frame")


def test_DW_1_1_nothing_emitted_before_esu(mod):
    mux = mod.FrameMux()
    out = mux.feed(mod.BSU + b'hello world')           # frame opened, no ESU yet
    eq(out, b'', "DW-1.1: nothing may be emitted before the ESU arrives")
    check(mux.has_open_frame(), "DW-1.1: an opened-but-unclosed frame is 'open'")


# ==========================================================================
# DW-1.2: Frame split across multiple feeds → emitted atomically on ESU;
#         no partial frame escapes early.
# ==========================================================================
def test_DW_1_2_frame_split_across_feeds_atomic(mod):
    inner = b'AAAA' + b'\x1b[1mBash\x1b[22m' + b'BBBB'
    frame = mod.BSU + inner + mod.ESU
    mux = mod.FrameMux()
    emitted = bytearray()
    # Feed one byte at a time — the cruelest split.
    for i in range(len(frame)):
        emitted += mux.feed(frame[i:i + 1])
    expected = mod.BSU + mod.apply_subs(inner) + mod.ESU
    eq(bytes(emitted), expected, "DW-1.2: byte-split frame must reassemble atomically")


def test_DW_1_2_no_partial_frame_before_esu(mod):
    inner = b'partial-render-content'
    mux = mod.FrameMux()
    out1 = mux.feed(mod.BSU + inner[:10])
    out2 = mux.feed(inner[10:])
    eq(out1 + out2, b'', "DW-1.2: no frame content may escape before its ESU")
    out3 = mux.feed(mod.ESU)
    eq(out3, mod.BSU + mod.apply_subs(inner) + mod.ESU,
       "DW-1.2: full frame emits only once ESU arrives")


# ==========================================================================
# DW-1.3: BSU or ESU split across two feeds → detected; no marker bytes
#         leaked as passthrough, no missed boundary.
# ==========================================================================
def test_DW_1_3_bsu_split_across_feeds(mod):
    half = len(mod.BSU) // 2
    mux = mod.FrameMux()
    out1 = mux.feed(b'before' + mod.BSU[:half])        # split mid-BSU
    eq(out1, b'before', "DW-1.3: bytes before a split BSU emit; the BSU half is held")
    out2 = mux.feed(mod.BSU[half:] + b'body' + mod.ESU)
    eq(out2, mod.BSU + mod.apply_subs(b'body') + mod.ESU,
       "DW-1.3: split BSU completes and frame closes correctly")
    # The BSU bytes must NOT have leaked into out1 as passthrough.
    check(mod.BSU not in out1, "DW-1.3: a partial BSU must never leak as passthrough")


def test_DW_1_3_esu_split_across_feeds(mod):
    half = len(mod.ESU) // 2
    mux = mod.FrameMux()
    mux.feed(mod.BSU + b'body')
    out1 = mux.feed(mod.ESU[:half])                    # split mid-ESU, in-frame
    eq(out1, b'', "DW-1.3: a half-ESU mid-frame emits nothing yet")
    out2 = mux.feed(mod.ESU[half:])
    eq(out2, mod.BSU + mod.apply_subs(b'body') + mod.ESU,
       "DW-1.3: split ESU completes and the frame is emitted atomically")


def test_DW_1_3_no_partial_marker_leaked(mod):
    # Out-of-frame stream ending exactly on the shared marker prefix.
    mux = mod.FrameMux()
    out1 = mux.feed(b'xy' + mod._MARKER_PREFIX)        # could be BSU or ESU start
    eq(out1, b'xy', "DW-1.3: only the non-marker bytes emit; the prefix is held")
    out2 = mux.feed(b'h' + b'body' + mod.ESU)          # prefix + 'h' completes BSU
    eq(out2, mod.BSU + mod.apply_subs(b'body') + mod.ESU,
       "DW-1.3: held prefix + completing byte resolves to a real BSU boundary")


# ==========================================================================
# DW-1.4: Out-of-frame bytes → returned unmodified & promptly, except a
#         ≤len(marker)-1 trailing partial-marker tail.
# ==========================================================================
def test_DW_1_4_out_of_frame_passthrough_unmodified(mod):
    raw = b'\x1b[1mBash\x1b[22m plain boot chrome \x1b[0m'  # has a SUB needle
    out = mod.FrameMux().feed(raw)
    eq(out, raw, "DW-1.4: out-of-frame bytes pass through verbatim, no SUBS")


def test_DW_1_4_only_partial_marker_tail_held(mod):
    raw = b'lots of out of frame text'
    out = mod.FrameMux().feed(raw)
    eq(out, raw, "DW-1.4: out-of-frame bytes with no marker tail emit fully+promptly")
    # A tail that IS a partial marker is the only thing held back, and only ≤7.
    mux = mod.FrameMux()
    out = mux.feed(b'data' + b'\x1b[?2026')            # 7-byte partial-marker tail
    eq(out, b'data', "DW-1.4: exactly the partial-marker tail (<=7) is withheld")
    check(len(mux._tail) <= len(mod.BSU) - 1,
          "DW-1.4: held tail must be <= len(marker)-1 bytes")


# ==========================================================================
# DW-1.5: Size backstop — open frame > FRAME_BYTE_CAP is flushed; memory
#         bounded and stream stays live.
# ==========================================================================
def test_DW_1_5_size_backstop_flushes_oversized_frame(mod):
    mux = mod.FrameMux()
    big = b'Z' * (mod.FRAME_BYTE_CAP + 100)
    out = mux.feed(mod.BSU + big)                      # frame never closes within cap
    check(len(out) > 0, "DW-1.5: oversized open frame must flush, not buffer silently")
    check(mod.BSU in out, "DW-1.5: flushed head includes the BSU")


def test_DW_1_5_memory_bounded_during_oversize(mod):
    mux = mod.FrameMux()
    mux.feed(mod.BSU + b'Z' * (mod.FRAME_BYTE_CAP + 100))
    # After the flush the in-frame buffer must be released (degraded streaming).
    check(len(mux._frame) == 0,
          "DW-1.5: frame buffer must be released after the size backstop trips")
    out = mux.feed(b'more raw frame bytes')            # degraded → streams raw
    eq(out, b'more raw frame bytes',
       "DW-1.5: post-overflow bytes stream raw (stream stays live)")


def test_DW_1_5_esu_after_overflow_returns_to_ground(mod):
    mux = mod.FrameMux()
    mux.feed(mod.BSU + b'Z' * (mod.FRAME_BYTE_CAP + 100))
    out = mux.feed(b'tail' + mod.ESU + b'after')
    eq(out, b'tail' + mod.ESU + b'after',
       "DW-1.5: ESU closes the degraded frame and following bytes pass through")
    check(not mux.has_open_frame(),
          "DW-1.5: after the degraded ESU the mux is back in ground state")


# ==========================================================================
# DW-1.6: Time backstop — drain() flushes an open frame; a never-terminated
#         frame cannot freeze the screen.
# ==========================================================================
def test_DW_1_6_has_open_frame_then_drain_flushes(mod):
    mux = mod.FrameMux()
    inner = b'\x1b[1mBash\x1b[22m never closes'
    mux.feed(mod.BSU + inner)
    check(mux.has_open_frame(), "DW-1.6: an open unclosed frame reports has_open_frame")
    out = mux.drain()
    eq(out, mod.BSU + mod.apply_subs(inner) + mod.ESU,
       "DW-1.6: drain flushes the open frame (SUBS applied) AND closes it with an ESU")


def test_DW_1_6_drain_resets_to_ground_state(mod):
    mux = mod.FrameMux()
    mux.feed(mod.BSU + b'stuck')
    mux.drain()
    check(not mux.has_open_frame(), "DW-1.6: drain resets to out-of-frame ground state")
    # A held out-of-frame partial-marker tail is also flushed (raw) by drain.
    mux2 = mod.FrameMux()
    mux2.feed(b'abc' + b'\x1b[?2026')
    out = mux2.drain()
    eq(out, b'\x1b[?2026', "DW-1.6: a held partial-marker tail flushes raw on drain")


def test_DW_1_6_drain_idempotent_when_empty(mod):
    mux = mod.FrameMux()
    eq(mux.drain(), b'', "DW-1.6: drain on a fresh mux is a no-op")
    eq(mux.drain(), b'', "DW-1.6: drain is idempotent once buffers are empty")
    mux.feed(mod.BSU + b'x')
    mux.drain()
    eq(mux.drain(), b'', "DW-1.6: second drain after a flush returns nothing")


# ==========================================================================
# DW-1.6b: The box-drop regression. When the time-backstop drains an OPEN
#          frame (a BSU seen, its ESU not yet), the flush must close the
#          synchronized update with a synthesized ESU. Emitting the BSU
#          unmatched stranded the terminal mid-sync — it buffered the partial
#          frame and dropped the rest of its draw ops (the input box's
#          side/bottom borders), so typed text rendered "outside the box".
# ==========================================================================
def test_DW_1_6b_drain_of_open_frame_closes_the_sync_update(mod):
    mux = mod.FrameMux()
    mux.feed(mod.BSU + b'partial box draw ops')          # open frame, no ESU yet
    out = mux.drain()
    # Every BSU the drain emits must be matched by an ESU — no stranded BSU.
    eq(out.count(mod.BSU), out.count(mod.ESU),
       "DW-1.6b: a drained open frame must be BSU/ESU-balanced (no stranded BSU)")
    check(out.startswith(mod.BSU) and out.endswith(mod.ESU),
          "DW-1.6b: the drained frame must open with BSU and be closed by the synthesized ESU")


def test_DW_1_6b_real_esu_after_drain_is_harmless_passthrough(mod):
    # After the drain closes the frame, the rest of that same frame is still
    # upstream. It arrives out-of-frame on the next feed: the leftover ops and
    # the real ESU must pass through raw without re-opening or stalling.
    mux = mod.FrameMux()
    mux.feed(mod.BSU + b'head ops')
    mux.drain()                                          # closes with synthesized ESU
    leftover = mux.feed(b'tail ops' + mod.ESU + b'after')
    eq(leftover, b'tail ops' + mod.ESU + b'after',
       "DW-1.6b: the real ESU + trailing bytes pass through raw after a drain")
    check(not mux.has_open_frame(),
          "DW-1.6b: a drained-then-resumed frame leaves the mux in ground state")


# ==========================================================================
# DW-1.7: All existing SUBS (rainbow Skill + Bash) still fire, on complete
#         frames; out-of-frame content is NOT substituted.
# ==========================================================================
def test_DW_1_7_bash_sub_applied_in_frame(mod):
    frame = mod.BSU + b'\x1b[1mBash\x1b[22m' + mod.ESU
    out = mod.FrameMux().feed(frame)
    sig = b'\x1b[1m' + mod.PALETTE['bash'] + b'Bash'
    check(sig in out, "DW-1.7: Bash recolor must fire on a complete frame")


def test_DW_1_7_rainbow_skill_sub_applied_in_frame(mod):
    needle = b'\x1b[1mSkill\x1b[22m'
    frame = mod.BSU + needle + mod.ESU
    out = mod.FrameMux().feed(frame)
    check(needle not in out, "DW-1.7: the plain Skill envelope must be rewritten")
    check(mod.rainbow_text(b'Skill') in out,
          "DW-1.7: rainbow Skill rewrite must appear in the emitted frame")


def test_DW_1_7_rainbow_skill_sub_across_split_frame(mod):
    # The original bug class: a needle that lands across a feed boundary inside
    # a frame must still be rewritten, because SUBS run on the reassembled frame.
    needle = b'\x1b[1mSkill\x1b[22m'
    frame = mod.BSU + b'pre' + needle + b'post' + mod.ESU
    mux = mod.FrameMux()
    emitted = bytearray()
    for i in range(len(frame)):
        emitted += mux.feed(frame[i:i + 1])
    check(mod.rainbow_text(b'Skill') in bytes(emitted),
          "DW-1.7: a Skill needle split across feeds is still rewritten")


def test_DW_1_7_out_of_frame_subs_not_applied(mod):
    raw = b'\x1b[1mBash\x1b[22m'                       # same needle, but out of frame
    out = mod.FrameMux().feed(raw)
    eq(out, raw, "DW-1.7: out-of-frame bytes must NOT be substituted")


# ==========================================================================
# DW-1.8: stdin->master passthrough and the non-TTY execvp fast path are
#         unchanged (asserted at source level against the known-good lines).
# ==========================================================================
def test_DW_1_8_stdin_branch_unchanged_source(mod):
    src = open(WRAP, "rb").read().decode()
    # The stdin->master write is a verbatim passthrough (no mux, no SUBS).
    check("write_all(master_fd, data)" in src,
          "DW-1.8: stdin bytes must still be written straight to master_fd")
    # And the mux must NOT sit on the stdin path.
    check("mux.feed" not in src.split("if master_fd in r:")[0].split("if stdin_fd in r:")[-1],
          "DW-1.8: the stdin branch must not route through the mux")


def test_DW_1_8_execvp_fast_path_unchanged_source(mod):
    src = open(WRAP, "rb").read().decode()
    check("if not sys.stdin.isatty() or not sys.stdout.isatty():" in src,
          "DW-1.8: non-TTY guard unchanged")
    check('os.execvp("claude", ["claude"] + sys.argv[1:])' in src,
          "DW-1.8: non-TTY execvp fast path unchanged")


# ==========================================================================
# DW-1.9: py_compile clean; FrameMux has no import-time side effects.
# ==========================================================================
def test_DW_1_9_py_compile_clean(mod):
    res = subprocess.run([sys.executable, "-m", "py_compile", WRAP],
                         capture_output=True)
    eq(res.returncode, 0,
       f"DW-1.9: py_compile must be clean (stderr: {res.stderr.decode()!r})")


def test_DW_1_9_import_has_no_side_effects(mod):
    # Importing the module in a fresh interpreter must not write to stdout/stderr
    # or spawn anything — load it via importlib and capture all output.
    code = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('w', {WRAP!r})\n"
        "m = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(m)\n"
        "assert hasattr(m, 'FrameMux')\n"
        "assert m.FrameMux().feed(b'') == b''\n"        # constructible + no-op
        "assert m.FrameMux().drain() == b''\n"
    )
    res = subprocess.run([sys.executable, "-c", code], capture_output=True)
    eq(res.returncode, 0, f"DW-1.9: clean import failed: {res.stderr.decode()!r}")
    eq(res.stdout, b"", "DW-1.9: importing the module must print nothing to stdout")
    eq(res.stderr, b"", "DW-1.9: importing the module must print nothing to stderr")


# ==========================================================================
# Beyond the DW floor: edge cases the implementation surfaced.
# ==========================================================================
def test_edge_empty_feed_is_noop(mod):
    mux = mod.FrameMux()
    eq(mux.feed(b''), b'', "empty feed must be a safe no-op")
    check(not mux.has_open_frame(), "empty feed must not open a frame")


def test_edge_esu_without_bsu_passes_through(mod):
    # Malformed: ESU with no open frame (attach mid-render). Must not crash and
    # must pass through as ordinary out-of-frame bytes.
    out = mod.FrameMux().feed(b'before' + mod.ESU + b'after')
    eq(out, b'before' + mod.ESU + b'after',
       "stray ESU with no open BSU passes through raw")


def test_edge_inner_bsu_is_frame_content(mod):
    # Defensive: a BSU while already in-frame is treated as content; only ESU
    # ends the frame. Claude never nests, but we must not break if it appears.
    inner = b'x' + mod.BSU + b'y'
    frame = mod.BSU + inner + mod.ESU
    out = mod.FrameMux().feed(frame)
    eq(out, mod.BSU + mod.apply_subs(inner) + mod.ESU,
       "an inner BSU is frame content; only ESU ends the frame")


def test_edge_sequential_frames_in_one_chunk(mod):
    a = mod.BSU + b'first' + mod.ESU
    b = mod.BSU + b'second' + mod.ESU
    out = mod.FrameMux().feed(a + b)
    eq(out, mod.BSU + mod.apply_subs(b'first') + mod.ESU
            + mod.BSU + mod.apply_subs(b'second') + mod.ESU,
       "sequential frames ...ESU][BSU... in one chunk emit as two atomic frames")


def test_edge_out_of_frame_between_frames(mod):
    stream = (mod.BSU + b'one' + mod.ESU
              + b'RAW-BETWEEN'
              + mod.BSU + b'two' + mod.ESU)
    out = mod.FrameMux().feed(stream)
    expected = (mod.BSU + mod.apply_subs(b'one') + mod.ESU
                + b'RAW-BETWEEN'
                + mod.BSU + mod.apply_subs(b'two') + mod.ESU)
    eq(out, expected, "out-of-frame bytes between two frames pass through verbatim")


def test_edge_partial_marker_tail_resolves_to_non_marker(mod):
    # Held tail that turns out NOT to be a marker must be emitted raw, in order.
    mux = mod.FrameMux()
    out1 = mux.feed(b'data\x1b[?2026')                 # looks like a marker start
    out2 = mux.feed(b'X more')                         # ...but 'X' breaks the marker
    eq(out1 + out2, b'data\x1b[?2026X more',
       "a held tail that is not a real marker must be emitted raw, in order")


def test_edge_partial_marker_tail_is_bounded(mod):
    # Feeding only marker-prefix bytes repeatedly must never grow the held tail
    # beyond len(marker)-1.
    mux = mod.FrameMux()
    for _ in range(50):
        mux.feed(b'\x1b[?2026')
    check(len(mux._tail) <= len(mod.BSU) - 1,
          "held partial-marker tail stays bounded (<= len(marker)-1)")


# ==========================================================================
# DW-2.2: A rainbow-`Skill` needle split across TWO feed() calls (the seam
#         landing INSIDE the needle) is still rewritten in the emitted frame.
#         This is the original bug class: positional effects must survive a
#         read boundary because SUBS run on the reassembled whole frame.
# ==========================================================================
def test_DW_2_2_skill_needle_split_across_two_feeds(mod):
    needle = b'\x1b[1mSkill\x1b[22m'
    frame = mod.BSU + b'pre' + needle + b'post' + mod.ESU
    # Cut once, mid-needle, so neither half contains the whole needle. The
    # split point is chosen to land inside 'Skill' itself, not at a clean
    # SGR boundary — the cruelest realistic two-read split.
    cut = frame.index(b'Skill') + 2            # between 'Sk' and 'ill'
    first, second = frame[:cut], frame[cut:]
    check(needle not in first and needle not in second,
          "DW-2.2: precondition — the needle must straddle the two feeds")
    mux = mod.FrameMux()
    out1 = mux.feed(first)
    out2 = mux.feed(second)
    emitted = out1 + out2
    eq(out1, b'', "DW-2.2: nothing escapes before the closing ESU of the frame")
    check(mod.rainbow_text(b'Skill') in emitted,
          "DW-2.2: a Skill needle split across two feed() calls is still rewritten")
    check(needle not in emitted,
          "DW-2.2: the plain Skill envelope must not survive in the output")
    # And the whole frame must still be atomic: BSU…ESU intact around it.
    expected = mod.BSU + mod.apply_subs(b'pre' + needle + b'post') + mod.ESU
    eq(emitted, expected,
       "DW-2.2: the split needle reassembles into one atomic, themed frame")


def test_DW_2_2_skill_needle_split_at_every_seam(mod):
    # Stronger: no matter WHERE the two-feed seam falls inside the needle
    # span, the rewrite must still fire. Sweep every cut point across the
    # needle and assert the rainbow rewrite always lands.
    needle = b'\x1b[1mSkill\x1b[22m'
    frame = mod.BSU + b'A' + needle + b'B' + mod.ESU
    start = frame.index(needle)
    for cut in range(start, start + len(needle) + 1):
        mux = mod.FrameMux()
        emitted = mux.feed(frame[:cut]) + mux.feed(frame[cut:])
        check(mod.rainbow_text(b'Skill') in emitted,
              f"DW-2.2: Skill rewrite must fire for a seam at byte {cut}")
        check(not mux.has_open_frame(),
              f"DW-2.2: frame must close (no stall) for a seam at byte {cut}")


# ==========================================================================
# DW-2.3: Sequential-frames-in-one-chunk and the malformed cases
#         (ESU-without-BSU, nested BSU) are asserted to NEITHER CRASH
#         NOR STALL. "No stall" = the mux returns to ground state (no open
#         frame left hanging) and stays usable for the next feed.
# ==========================================================================
def test_DW_2_3_sequential_frames_no_crash_no_stall(mod):
    a = mod.BSU + b'first' + mod.ESU
    b = mod.BSU + b'second' + mod.ESU
    mux = mod.FrameMux()
    out = mux.feed(a + b)                       # must not raise
    eq(out, mod.BSU + mod.apply_subs(b'first') + mod.ESU
            + mod.BSU + mod.apply_subs(b'second') + mod.ESU,
       "DW-2.3: two back-to-back frames both emit, themed and atomic")
    check(not mux.has_open_frame(),
          "DW-2.3: after sequential frames the mux is back in ground state (no stall)")
    # Still usable for a third frame — proves no latched/broken state.
    out3 = mux.feed(mod.BSU + b'third' + mod.ESU)
    eq(out3, mod.BSU + mod.apply_subs(b'third') + mod.ESU,
       "DW-2.3: the mux keeps working after sequential frames (no stall)")


def test_DW_2_3_esu_without_bsu_no_crash_no_stall(mod):
    mux = mod.FrameMux()
    out = mux.feed(b'before' + mod.ESU + b'after')   # stray ESU, must not raise
    eq(out, b'before' + mod.ESU + b'after',
       "DW-2.3: a stray ESU with no open BSU passes through raw")
    check(not mux.has_open_frame(),
          "DW-2.3: a stray ESU must not leave the mux stalled in a frame")
    # A real frame after the malformed input must still work.
    out2 = mux.feed(mod.BSU + b'ok' + mod.ESU)
    eq(out2, mod.BSU + mod.apply_subs(b'ok') + mod.ESU,
       "DW-2.3: the mux recovers and frames normally after a stray ESU")


def test_DW_2_3_nested_bsu_no_crash_no_stall(mod):
    # Inner BSU while already in-frame is content; only an ESU ends the frame.
    inner = b'x' + mod.BSU + b'y'
    frame = mod.BSU + inner + mod.ESU
    mux = mod.FrameMux()
    out = mux.feed(frame)                            # must not raise
    eq(out, mod.BSU + mod.apply_subs(inner) + mod.ESU,
       "DW-2.3: a nested BSU is treated as frame content; the first ESU closes it")
    check(not mux.has_open_frame(),
          "DW-2.3: a nested BSU must not leave a second frame stuck open (no stall)")
    out2 = mux.feed(mod.BSU + b'next' + mod.ESU)
    eq(out2, mod.BSU + mod.apply_subs(b'next') + mod.ESU,
       "DW-2.3: the mux frames normally after a nested-BSU frame")


def test_DW_2_3_unterminated_then_drain_no_stall(mod):
    # The other no-stall axis: a frame that never closes must be drainable so
    # the screen advances instead of freezing (time-backstop liveness).
    mux = mod.FrameMux()
    mux.feed(mod.BSU + b'\x1b[1mSkill\x1b[22m hangs forever')
    check(mux.has_open_frame(), "DW-2.3: an unterminated frame is open before drain")
    out = mux.drain()                                # must not raise
    check(mod.rainbow_text(b'Skill') in out,
          "DW-2.3: drain flushes the stuck frame themed (no permanent stall)")
    check(not mux.has_open_frame(),
          "DW-2.3: after drain the mux is back in ground state")


# ==========================================================================
# DW-2.5: This test file is stdlib-only and follows the 0/1/2 exit
#         convention. Asserted as a tested invariant rather than left implicit.
# ==========================================================================
def test_DW_2_5_test_file_is_stdlib_only(mod):
    import ast
    src = open(os.path.join(HERE, "test-framemux.py"), "rb").read().decode()
    tree = ast.parse(src)
    stdlib = {
        "importlib", "os", "subprocess", "sys", "ast",  # module-level + local
    }
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                imported.add(n.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    thirdparty = imported - stdlib
    check(not thirdparty,
          f"DW-2.5: test file must be stdlib-only; unexpected imports: {sorted(thirdparty)}")


def test_DW_2_5_exit_convention_0_1_2(mod):
    # Running this file as a subprocess on the all-pass tree must exit 0.
    # (1 = behavioral regression, 2 = driver error — the documented contract.)
    # Guard against infinite self-recursion: the child sees _FRAMEMUX_NO_SUBPROC
    # and skips re-spawning, so it still runs every other test (exit code is a
    # real signal) without forking forever.
    if os.environ.get("_FRAMEMUX_NO_SUBPROC"):
        return
    env = dict(os.environ, _FRAMEMUX_NO_SUBPROC="1")
    res = subprocess.run([sys.executable, os.path.join(HERE, "test-framemux.py")],
                         capture_output=True, env=env)
    check(res.returncode in (0, 1, 2),
          f"DW-2.5: exit code must be one of 0/1/2, got {res.returncode}")
    eq(res.returncode, 0,
       f"DW-2.5: the green tree must exit 0 (stderr: {res.stderr.decode()!r})")


def main():
    try:
        mod = load_wrapper()
    except Exception as e:                              # noqa: BLE001 - driver setup
        print(f"FAIL: could not load wrapper module from {WRAP}: {e}", file=sys.stderr)
        return 2

    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        try:
            t(mod)
        except Exception as e:                          # noqa: BLE001 - report, don't abort
            _FAILS.append(f"{t.__name__} raised {type(e).__name__}: {e}")

    print(f"ran {len(tests)} FrameMux tests")
    if _FAILS:
        print(f"\nFAIL: {len(_FAILS)} assertion(s) failed:", file=sys.stderr)
        for f in _FAILS:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("OK: all FrameMux tests pass.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
