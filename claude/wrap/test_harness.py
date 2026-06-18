#!/usr/bin/env python3
"""Real-terminal validation harness for the claude-theme-wrap insulator.

THE PRIMARY ORACLE IS A REAL TERMINAL. This module renders any byte stream
through a fresh, detached tmux pane (a genuine clamping terminal — the same
thing that exposed the original corruption) and returns the resulting grid.
Every later phase of the insulator is gated by predicates built on top of
`render_real`. `testdata/vtmodel.py` is used ONLY as a one-time STARTING POINT
to mint the static intent grid (see `build_intent_grid`); it is NEVER the live
gate. This is the #1 lesson from the prior regression: a self-authored model
shared the implementation's parser blindspot, so its tests passed while the
output broke live.

Zero third-party dependencies (stdlib only) — the single-file supply chain of
the wrapper is preserved.

Public surface:
    tmux_available() -> bool
    render_real(stream, cols, rows, *, settle=...) -> list[str]
    noop_repair(data) -> data                       # identity repair
    build_intent_grid(stream, cols, rows) -> list[str]   # vtmodel STARTING POINT
    assert_transparent(repair_fn, stream, cols, rows) -> bool
    assert_corrected(repair_fn, stream, intent, cols, rows) -> bool
    corpus_dir() -> str
    load_corpus() -> list[dict]
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS_DIR = os.path.join(HERE, "testdata", "corpus")
CORPUS_MANIFEST = os.path.join(CORPUS_DIR, "corpus.json")

# Settle policy: a single fixed sleep races tmux's replay of a 100KB+ stream
# (one capture can fire mid-drain), which makes render_real non-deterministic
# under load. Instead we capture-until-quiesced: poll until two consecutive
# captures (DEFAULT_POLL apart) are identical, i.e. the grid has stopped
# changing. DEFAULT_SETTLE is the initial wait before the first poll; the
# deadline bounds total wait so a pathological stream can't hang.
DEFAULT_SETTLE = 0.25
DEFAULT_POLL = 0.1
DEFAULT_DEADLINE = 8.0


def tmux_available() -> bool:
    """True iff a usable tmux binary is on PATH (plan edge case: skip cleanly)."""
    return shutil.which("tmux") is not None


def render_real(stream: bytes, cols: int, rows: int, *, settle: float = DEFAULT_SETTLE) -> list[str]:
    """Render `stream` through a REAL terminal and return its normalized grid.

    Deterministic by construction: a fresh blank-origin pane of fixed size, a
    fixed settle wait, then `capture-pane -p`. The pane runs
    `sh -c '/bin/cat FILE; sleep 600'` — `sh` + the absolute `/bin/cat` dodge the
    user's zsh `rtk` hook that would otherwise rewrite `cat`. The session is
    ALWAYS killed (even on error) so no panes leak.

    Normalization: split on newlines, rstrip each line (capture-pane right-pads
    with spaces), and drop trailing blank lines (capture-pane emits blank rows to
    the bottom of the pane). Returns list[str], one entry per surviving row.
    """
    if not tmux_available():
        raise RuntimeError("tmux not available; cannot render in a real terminal")

    session = "cthrness_" + uuid.uuid4().hex[:12]
    fd, path = tempfile.mkstemp(suffix=".bin", prefix="cthrness_")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(stream)
        subprocess.run(
            ["tmux", "new-session", "-d", "-s", session,
             "-x", str(cols), "-y", str(rows),
             "sh", "-c", "/bin/cat %s; sleep 600" % path],
            check=True,
        )
        captured = _settle_capture(session, settle)
    finally:
        subprocess.run(["tmux", "kill-session", "-t", session],
                       stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        try:
            os.unlink(path)
        except OSError:
            pass
    return _normalize(captured)


def _capture_pane(session: str) -> str:
    return subprocess.run(
        ["tmux", "capture-pane", "-p", "-t", session],
        capture_output=True, text=True, check=True,
    ).stdout


def _settle_capture(session: str, settle: float,
                    poll: float = DEFAULT_POLL, deadline: float = DEFAULT_DEADLINE) -> str:
    """Capture once the pane grid has quiesced: wait `settle`, then capture
    repeatedly `poll` apart until two consecutive captures match (replay done) or
    `deadline` elapses. Returns the final, stable capture. Deterministic: the
    result is the settled grid regardless of how fast tmux replayed the stream."""
    time.sleep(settle)
    prev = _capture_pane(session)
    start = time.monotonic()
    while time.monotonic() - start < deadline:
        time.sleep(poll)
        cur = _capture_pane(session)
        if cur == prev:
            return cur
        prev = cur
    return prev


def _normalize(captured: str) -> list[str]:
    """Trim trailing per-line spaces and trailing blank rows for stable compares."""
    lines = [line.rstrip() for line in captured.split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def noop_repair(data: bytes) -> bytes:
    """Identity repair. Phase 3 injects the real Insulator; until then this proves
    the harness is non-vacuous (transparent on correct streams, fails to correct
    a buggy one)."""
    return data


def build_intent_grid(stream: bytes, cols: int, rows: int) -> list[str]:
    """Mint the known-correct intent grid for a buggy stream — STARTING POINT ONLY.

    Renders `stream` through testdata/vtmodel.py with clamp=False (claude's
    cursor moves WITHOUT a real terminal's edge-clamp, recovering claude's
    INTENT). This is used ONCE to write a STATIC `.intent` file which is then
    eyeball-checked and frozen. It is deliberately NOT wired into the live gate:
    trusting vtmodel as the runtime oracle is precisely the regression this phase
    exists to prevent.
    """
    sys.path.insert(0, os.path.join(HERE, "testdata"))
    try:
        from vtmodel import VT  # type: ignore
    finally:
        # leave testdata on path is harmless, but keep it clean
        pass
    vt = VT(rows, cols, clamp=False)
    vt.feed(stream)
    return _normalize(vt.grid())


def assert_transparent(repair_fn, stream: bytes, cols: int, rows: int) -> bool:
    """True iff the repaired stream renders grid-identical to the raw stream in a
    real terminal. The transparency invariant: invisible when claude is correct."""
    return render_real(stream, cols, rows) == render_real(repair_fn(stream), cols, rows)


def assert_corrected(repair_fn, stream: bytes, intent: list[str], cols: int, rows: int) -> bool:
    """True iff the repaired stream renders to the known-correct `intent` grid in a
    real terminal. `intent` is the normalized list[str] loaded from the static
    `.intent` file (NOT recomputed live)."""
    return render_real(repair_fn(stream), cols, rows) == _normalize_intent(intent)


def _normalize_intent(intent) -> list[str]:
    """Accept either a list[str] or a raw newline-joined str; normalize identically
    to render_real output so comparisons are apples-to-apples."""
    if isinstance(intent, str):
        return _normalize(intent)
    return _normalize("\n".join(intent))


def corpus_dir() -> str:
    return CORPUS_DIR


def load_corpus() -> list[dict]:
    """Load corpus.json; returns the list of fixture dicts."""
    with open(CORPUS_MANIFEST, "r") as f:
        manifest = json.load(f)
    return manifest["fixtures"]


def load_intent(fixture: dict) -> list[str]:
    """Load the static intent grid for a buggy fixture (from its intent_file)."""
    path = os.path.join(CORPUS_DIR, fixture["intent_file"])
    with open(path, "r") as f:
        return _normalize(f.read())
