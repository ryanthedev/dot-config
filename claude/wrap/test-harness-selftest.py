#!/usr/bin/env python3
"""Self-test for the Phase-1 real-terminal validation harness (test_harness.py).

Proves DW-1.1 .. DW-1.4 against a REAL terminal (tmux). Plain-stdlib runner in
the house style: `python3 claude/wrap/test-harness-selftest.py`; exit 0 = all
pass, non-zero = a failure (or a clean SKIP when tmux is absent).

Test mix follows cc-quality-practices (dirty:clean ~5:1): beyond the four DW
floor cases we add non-vacuity guards, a leaked-escape negative check, an
empty-stream edge case, and a tmux-absent skip path.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_harness as H  # noqa: E402

PASSED = []
FAILED = []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print("  PASS  %s" % name)
    else:
        FAILED.append((name, detail))
        print("  FAIL  %s  %s" % (name, detail))


def _fixture(corpus, label=None, name=None):
    for fx in corpus:
        if name and fx["file"] == name:
            return fx
        if label and name is None and fx["label"] == label:
            return fx
    raise AssertionError("fixture not found label=%r name=%r" % (label, name))


def _read(corpus_fixture):
    with open(os.path.join(H.corpus_dir(), corpus_fixture["file"]), "rb") as f:
        return f.read()


# ---------------------------------------------------------------------------
# DW-1.1: render_real is deterministic across 3 runs for the same stream.
# ---------------------------------------------------------------------------
def test_DW_1_1_render_real_deterministic(corpus):
    for name in ("startup.bin", "agenttree-tmux256.bin"):
        fx = _fixture(corpus, name=name)
        data = _read(fx)
        runs = [H.render_real(data, fx["cols"], fx["rows"]) for _ in range(3)]
        check("DW-1.1 deterministic(%s)" % name,
              runs[0] == runs[1] == runs[2],
              "" if runs[0] == runs[1] == runs[2] else "runs differ")


# ---------------------------------------------------------------------------
# DW-1.2: corpus + manifest: >=3 fixtures incl. startup + clamp-bug, >=1 buggy
# and >=1 correct, every file exists, every buggy has an existing intent_file.
# ---------------------------------------------------------------------------
def test_DW_1_2_corpus_manifest(corpus):
    check("DW-1.2 >=3 fixtures", len(corpus) >= 3, "have %d" % len(corpus))
    labels = {fx["label"] for fx in corpus}
    check("DW-1.2 has a correct", "correct" in labels, str(labels))
    check("DW-1.2 has a buggy", "buggy" in labels, str(labels))
    names = {fx["file"] for fx in corpus}
    check("DW-1.2 startup present", "startup.bin" in names, str(names))
    check("DW-1.2 clamp-bug present", "agenttree-tmux256.bin" in names, str(names))
    all_exist = all(os.path.exists(os.path.join(H.corpus_dir(), fx["file"])) for fx in corpus)
    check("DW-1.2 all fixture files exist", all_exist)
    ok_intents = True
    for fx in corpus:
        if fx["label"] == "buggy":
            ip = os.path.join(H.corpus_dir(), fx.get("intent_file", ""))
            if not fx.get("intent_file") or not os.path.exists(ip):
                ok_intents = False
    check("DW-1.2 every buggy has an existing intent_file", ok_intents)


# ---------------------------------------------------------------------------
# DW-1.3: no-op repair -> startup transparent; clamp-bug NON-transparent vs
# intent AND assert_corrected(noop) FAILS. Proves the oracle is real & non-vacuous.
# ---------------------------------------------------------------------------
def test_DW_1_3_oracle_non_vacuous(corpus):
    startup = _fixture(corpus, name="startup.bin")
    sdata = _read(startup)
    check("DW-1.3 startup transparent under no-op",
          H.assert_transparent(H.noop_repair, sdata, startup["cols"], startup["rows"]))

    buggy = _fixture(corpus, label="buggy")
    bdata = _read(buggy)
    intent = H.load_intent(buggy)
    raw_grid = H.render_real(bdata, buggy["cols"], buggy["rows"])
    # The buggy stream, rendered RAW in a real terminal, must NOT equal its intent.
    check("DW-1.3 buggy raw != intent (real corruption detected)",
          raw_grid != intent,
          "raw==intent would mean no corruption")
    # And the no-op repair therefore must NOT be 'corrected'.
    corrected = H.assert_corrected(H.noop_repair, bdata, intent, buggy["cols"], buggy["rows"])
    check("DW-1.3 no-op repair does NOT correct the bug", not corrected)


# ---------------------------------------------------------------------------
# DW-1.4: documented intent helper -> static file per buggy fixture, recorded in
# manifest, with a human-readable dump; static file is the corrected target
# (!= raw render). build_intent_grid reproduces the frozen file.
# ---------------------------------------------------------------------------
def test_DW_1_4_intent_static_files(corpus):
    for fx in corpus:
        if fx["label"] != "buggy":
            continue
        ipath = os.path.join(H.corpus_dir(), fx["intent_file"])
        check("DW-1.4 static intent file exists (%s)" % fx["file"], os.path.exists(ipath))
        # human-readable dump next to it
        dump = ipath + ".txt"
        check("DW-1.4 human-readable dump exists (%s)" % fx["file"], os.path.exists(dump))
        static_intent = H.load_intent(fx)
        # the frozen file is the corrected target, not the raw render
        raw_grid = H.render_real(_read(fx), fx["cols"], fx["rows"])
        check("DW-1.4 intent != raw render (%s)" % fx["file"], static_intent != raw_grid)
        # documented helper reproduces the frozen file (vtmodel starting point is stable)
        minted = H.build_intent_grid(_read(fx), fx["cols"], fx["rows"])
        check("DW-1.4 helper reproduces frozen intent (%s)" % fx["file"], minted == static_intent)


# ---------------------------------------------------------------------------
# Dirty / beyond-floor cases.
# ---------------------------------------------------------------------------
def test_dirty_no_escape_leak_in_startup(corpus):
    startup = _fixture(corpus, name="startup.bin")
    grid = H.render_real(_read(startup), startup["cols"], startup["rows"])
    joined = "\n".join(grid)
    check("dirty: no ESC byte leaks as glyph in startup render", "\x1b" not in joined)


def test_dirty_empty_stream(corpus):
    grid = H.render_real(b"", 80, 24)
    check("dirty: empty stream renders to empty grid", grid == [], repr(grid))


def test_dirty_all_correct_streams_transparent(corpus):
    # every 'correct' fixture must be transparent under the no-op repair
    ok = True
    detail = ""
    for fx in corpus:
        if fx["label"] != "correct":
            continue
        if not H.assert_transparent(H.noop_repair, _read(fx), fx["cols"], fx["rows"]):
            ok = False
            detail = "non-transparent: %s" % fx["file"]
            break
    check("dirty: all 'correct' streams transparent under no-op", ok, detail)


def main():
    if not H.tmux_available():
        print("SKIP: tmux not available -- real-terminal harness cannot run.")
        return 0

    corpus = H.load_corpus()
    print("== DW-1.1 ==");  test_DW_1_1_render_real_deterministic(corpus)
    print("== DW-1.2 ==");  test_DW_1_2_corpus_manifest(corpus)
    print("== DW-1.3 ==");  test_DW_1_3_oracle_non_vacuous(corpus)
    print("== DW-1.4 ==");  test_DW_1_4_intent_static_files(corpus)
    print("== dirty ==")
    test_dirty_no_escape_leak_in_startup(corpus)
    test_dirty_empty_stream(corpus)
    test_dirty_all_correct_streams_transparent(corpus)

    print("\n%d passed, %d failed" % (len(PASSED), len(FAILED)))
    if FAILED:
        for name, detail in FAILED:
            print("  FAILED: %s  %s" % (name, detail))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
