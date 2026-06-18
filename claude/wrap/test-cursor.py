#!/usr/bin/env python3
"""Cursor-POSITION regression tests for the Insulator, gated by a REAL terminal.

The content oracle (capture-pane) cannot see cursor position, so a default-on
regression shipped where typing a SPACE did not advance the visible cursor: the
diff emitter repainted grid cells but never re-placed the terminal cursor at
claude's tracked cursor, and a space (an invisible blank that also changes no
grid cell) produced zero feedback. These tests assert the cursor via tmux
`#{cursor_x},#{cursor_y}`:

  - SPACE symptom: typing "ab " advances the cursor exactly as the raw stream.
  - Transparency: on a correct stream, the insulated cursor == the raw cursor.
  - Empty/no-op feed stays byte-empty (no spurious CUP).
"""
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "testdata", "corpus")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    saved = list(sys.argv)
    sys.argv = [name]
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = saved
    return mod


H = _load(os.path.join(HERE, "test_harness.py"), "harness")
W = _load(os.path.join(HERE, "claude-theme-wrap.py"), "ctw")

_FAILS = []


def check(cond, msg):
    if not cond:
        _FAILS.append(msg)


def _insulate(stream, cols, rows):
    ins = W.Insulator(rows, cols)
    return ins.feed(stream) + ins.drain()


def test_empty_feed_is_byte_empty():
    ins = W.Insulator(24, 80)
    check(ins.feed(b"") == b"", "empty feed must produce b'' (no spurious CUP)")
    check(ins.drain() == b"", "empty drain must produce b''")


def test_space_advances_cursor_like_raw():
    if not H.tmux_available():
        return
    stream = b"ab "          # type two chars then a space
    raw = H.render_real_cursor(stream, 80, 24)
    ins = H.render_real_cursor(_insulate(stream, 80, 24), 80, 24)
    check(raw == ins,
          "typed space: insulated cursor %r must match raw cursor %r" % (ins, raw))
    check(ins[0] == 3,
          "typed 'ab ' must leave the cursor at column 3 (got %r)" % (ins,))


def test_cursor_transparency_on_correct_corpus():
    if not H.tmux_available():
        return
    manifest = json.load(open(os.path.join(CORPUS, "corpus.json")))
    fixtures = manifest.get("fixtures", manifest)
    fixtures = list(fixtures.values()) if isinstance(fixtures, dict) else fixtures
    for fx in fixtures:
        if fx.get("label") != "correct":
            continue
        data = open(os.path.join(CORPUS, fx["file"]), "rb").read()
        cols, rows = fx["cols"], fx["rows"]
        raw = H.render_real_cursor(data, cols, rows)
        ins = H.render_real_cursor(_insulate(data, cols, rows), cols, rows)
        check(raw == ins,
              "cursor transparency on %s: insulated %r != raw %r"
              % (fx["file"], ins, raw))


def main():
    if not H.tmux_available():
        print("SKIP: tmux unavailable — cursor tests need a real terminal")
        return 0
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    if _FAILS:
        print("FAIL: %d assertion(s) failed:" % len(_FAILS), file=sys.stderr)
        for m in _FAILS:
            print("  - " + m, file=sys.stderr)
        return 1
    print("ran %d cursor tests" % len(tests))
    print("OK: all cursor tests pass.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
