#!/usr/bin/env python3
"""DW-2.2 live replay: prove the wrapper's output pipeline removes the cursor-
desync corruption inside a REAL tmux pane.

What it does
------------
1. Loads the wrapper module and the independent vt oracle.
2. Feeds testdata/cap-tmux256-agenttree.bin through the wrapper's PRODUCTION
   output path — process_output(...) + drain_output(...) with RepairState — the
   exact bytes main() would write to stdout. (We can't pipe through the full PTY
   because the wrapper execs the real `claude`; the corrected BYTE STREAM is the
   thing under test, and process_output is precisely that stream as it leaves the
   wrapper toward the terminal.)
3. Boots a detached tmux server with a 129x41 pane, cat's those corrected bytes
   into the pane, and runs `tmux capture-pane -p` to read the pane's real grid —
   tmux is the genuine CLAMPING terminal that exposed the bug.
4. Compares the pane grid against claude's INTENDED grid (the oracle's
   clamp=OFF model of the RAW capture). Equal == corruption gone.
5. Control assertion (non-vacuous): the RAW capture cat'd into the SAME tmux pane
   does NOT match intent (it's corrupted) — so the repair is doing real work.

Also asserts the specific DW-2.2 symptoms are fixed: input text sits on the `❯`
prompt line (not merged into a border) and the box-drawing borders are intact.

Run:  python3 ~/.config/claude/wrap/replay-live.py
Exit: 0 corruption gone, 1 grids differ (regression), 2 driver error (no tmux).
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WRAP = os.path.join(HERE, "claude-theme-wrap.py")
TESTDATA = os.path.join(HERE, "testdata")
VTMODEL = os.path.join(TESTDATA, "vtmodel.py")
CAPTURE = os.path.join(TESTDATA, "cap-tmux256-agenttree.bin")
ROWS, COLS = 41, 129


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def corrected_bytes(mod, raw):
    """The exact bytes the wrapper writes toward the terminal for `raw`, repair
    ON (default). Chunked to mimic real read() sizes; drained at the end."""
    os.environ.pop("CLAUDE_WRAP_REPAIR", None)   # ensure default-on
    state = mod.RepairState(ROWS, COLS)
    out = bytearray()
    for i in range(0, len(raw), 4096):
        out += mod.process_output(raw[i:i + 4096], state)
    out += mod.drain_output(state)
    return bytes(out)


def tmux(*args, **kw):
    return subprocess.run(["tmux", *args], capture_output=True, **kw)


def pane_grid_for(stream_bytes, sock):
    """Cat `stream_bytes` into a fresh 129x41 tmux pane on socket `sock` and
    return its capture-pane grid (trailing blanks trimmed per line, like the
    oracle's grid())."""
    # A unique session per call so the two runs (repaired vs raw) don't collide.
    sess = f"replay{int(time.time()*1e6)%10**9}"
    # Write the stream to a temp file and `cat` it from inside the pane so tmux's
    # own VT parser (the real clamping terminal) interprets it.
    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as tf:
        tf.write(stream_bytes)
        binpath = tf.name
    try:
        # Start a detached session at the exact capture geometry. `cat` then a
        # long sleep so the pane stays alive while we capture it.
        r = tmux("-S", sock, "new-session", "-d", "-s", sess,
                 "-x", str(COLS), "-y", str(ROWS),
                 f"cat {binpath}; sleep 30")
        if r.returncode != 0:
            raise RuntimeError(f"tmux new-session failed: {r.stderr.decode()!r}")
        # Give tmux time to render the stream into the pane grid.
        time.sleep(1.0)
        cap = tmux("-S", sock, "capture-pane", "-t", sess, "-p")
        if cap.returncode != 0:
            raise RuntimeError(f"capture-pane failed: {cap.stderr.decode()!r}")
        # Normalize: rstrip each line, drop trailing all-blank lines, to mirror
        # the oracle grid()'s per-line rstrip + join.
        lines = cap.stdout.decode("utf-8", "replace").split("\n")
        return "\n".join(ln.rstrip() for ln in lines).rstrip("\n")
    finally:
        tmux("-S", sock, "kill-session", "-t", sess)
        try:
            os.remove(binpath)
        except OSError:
            pass


def oracle_intent_grid(vt, raw):
    m = vt.VT(ROWS, COLS, clamp=False)
    m.feed(raw)
    # vt.grid() already rstrips each row; drop trailing blank rows for parity with
    # capture-pane (tmux trims a trailing all-blank tail).
    return m.grid().rstrip("\n")


def main():
    if subprocess.run(["which", "tmux"], capture_output=True).returncode != 0:
        print("SKIP/FAIL: tmux not on PATH — DW-2.2 live replay needs tmux", file=sys.stderr)
        return 2
    if not os.path.exists(CAPTURE):
        print(f"FAIL: capture not found: {CAPTURE}", file=sys.stderr)
        return 2

    mod = load(WRAP, "claude_theme_wrap")
    vt = load(VTMODEL, "vtmodel")
    raw = open(CAPTURE, "rb").read()

    # A private tmux socket so we never touch the user's running tmux server.
    sock = os.path.join(tempfile.gettempdir(), f"claude-replay-{os.getpid()}.sock")

    try:
        repaired = corrected_bytes(mod, raw)
        repaired_grid = pane_grid_for(repaired, sock)
        raw_grid = pane_grid_for(raw, sock)
        intent_grid = oracle_intent_grid(vt, raw)
    except Exception as e:  # noqa: BLE001 - driver/tmux failure
        print(f"FAIL(driver): {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    finally:
        subprocess.run(["tmux", "-S", sock, "kill-server"], capture_output=True)
        try:
            os.remove(sock)
        except OSError:
            pass

    ok = True

    # Control: raw cat'd into the SAME tmux is corrupted (proves the gate matters).
    if raw_grid == intent_grid:
        print("FAIL: control — RAW capture already matches intent in tmux; the "
              "replay gate is vacuous (the corruption did not reproduce).",
              file=sys.stderr)
        ok = False
    else:
        print("control OK: RAW capture is corrupted in tmux (grid != intent).")

    # The repair: the corrected stream's pane grid must equal claude's intent.
    if repaired_grid == intent_grid:
        print("DW-2.2 OK: repaired stream's tmux capture-pane == claude's intended grid "
              "(corruption gone).")
    else:
        ok = False
        print("DW-2.2 FAIL: repaired pane grid != intended grid.", file=sys.stderr)
        # Diff the first divergent lines for debugging.
        rep_lines = repaired_grid.split("\n")
        int_lines = intent_grid.split("\n")
        for i in range(max(len(rep_lines), len(int_lines))):
            a = rep_lines[i] if i < len(rep_lines) else "<none>"
            b = int_lines[i] if i < len(int_lines) else "<none>"
            if a != b:
                print(f"  row {i}:\n    repaired: {a!r}\n    intent:   {b!r}",
                      file=sys.stderr)
                # show a few then stop
                break

    # Symptom assertions: the `❯` prompt line carries the typed input (not merged
    # into a border) and box borders are intact. Derive from intent (the source of
    # truth) and require the repaired pane to reproduce them.
    def find_prompt_line(grid):
        for ln in grid.split("\n"):
            if "❯" in ln:
                return ln
        return None

    prompt_intent = find_prompt_line(intent_grid)
    prompt_repaired = find_prompt_line(repaired_grid)
    if prompt_intent is not None:
        if prompt_repaired == prompt_intent:
            print(f"DW-2.2 OK: prompt line reproduced: {prompt_repaired!r}")
        else:
            ok = False
            print(f"DW-2.2 FAIL: prompt (❯) line differs.\n"
                  f"    repaired: {prompt_repaired!r}\n    intent:   {prompt_intent!r}",
                  file=sys.stderr)

    # Border integrity: the set of box-drawing rows must match intent.
    BOX = set("─│╭╮╰╯├┤┬┴┼━┃┏┓┗┛")

    def border_rows(grid):
        return [i for i, ln in enumerate(grid.split("\n"))
                if any(ch in BOX for ch in ln)]

    if border_rows(intent_grid) == border_rows(repaired_grid):
        print("DW-2.2 OK: box-drawing border rows intact (same rows as intent).")
    else:
        ok = False
        print(f"DW-2.2 FAIL: border rows differ.\n"
              f"    repaired: {border_rows(repaired_grid)}\n"
              f"    intent:   {border_rows(intent_grid)}", file=sys.stderr)

    print("\n" + ("OK: DW-2.2 live replay — corruption gone." if ok
                  else "FAIL: DW-2.2 live replay had failures (see above)."))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
