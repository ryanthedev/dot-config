#!/usr/bin/env python3
"""Smoke test that fails loudly when Claude Code's SGR palette drifts OR
when the wrapper's regex pipeline stops firing on real claude output.

Spawns real `claude` in a PTY, drives it to render a known markdown sample
and a Bash tool call, and verifies two things:

  1. Every needle in the wrapper's literal SUBS list is still present in
     claude's raw output bytes. If claude updates and changes (say) the
     inline-code color from 153 to something else, this fails.
  2. After running the wrapper's apply_subs() pipeline on the captured
     bytes, the regex pass actually fired — we look for the bash tool name
     recolor AND the shell highlighter's command-name signature around
     `pwd`. If the regex stops matching (e.g. claude changes the
     `\\e[1mBash\\e[22m(...)` envelope), this fails.

Run:  python3 ~/.config/claude/wrap/test-palette.py
Exit: 0 on success, 1 on drift, 2 on driver error.
"""
import fcntl, importlib.util, os, pty, select, struct, sys, termios, time

HERE = os.path.dirname(os.path.abspath(__file__))
WRAP = os.path.join(HERE, "claude-theme-wrap.py")

def load_wrapper():
    spec = importlib.util.spec_from_file_location("claude_theme_wrap", WRAP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

# Sample that exercises every element our SUBS list cares about: markdown
# styling AND a Bash tool call (so the gray ⏺ + ⎿ tool render appears
# AND the bold "Bash" tool name appears).
PROMPT = (
    b"Please do two things in your reply:\r\r"
    b"1) Render this markdown verbatim:\r"
    b"# Heading one\r"
    b"A paragraph with **bold**, *italic*, and `inline code`.\r"
    b"\r"
    b"2) Use the Bash tool to run `pwd`.\r"
)

# Interaction script: (t_seconds, bytes_to_send, label)
SCRIPT = [
    (3.0,  b"\r",       "accept trust dialog (no-op if already trusted)"),
    (6.0,  PROMPT,      "type markdown prompt"),
    (8.0,  b"\r",       "submit prompt"),
    (60.0, b"/quit\r",  "quit"),
]
DEADLINE = 75.0
ROWS, COLS = 50, 140

def set_winsize(fd):
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))

def capture():
    pid, fd = pty.fork()
    if pid == 0:
        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        env["FORCE_COLOR"] = "1"
        os.execvpe("claude", ["claude"], env)
        os._exit(127)

    set_winsize(fd)
    out = bytearray()
    start = time.time()
    idx = 0
    last_growth = start

    while True:
        now = time.time() - start
        if now > DEADLINE:
            break
        r, _, _ = select.select([fd], [], [], 0.2)
        if fd in r:
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                break
            if not chunk:
                break
            out.extend(chunk)
            last_growth = time.time()
        if idx < len(SCRIPT) and now >= SCRIPT[idx][0]:
            os.write(fd, SCRIPT[idx][1])
            idx += 1
        # If the response has been quiet for >8s after the prompt, assume done.
        # Tool calls take longer than pure markdown rendering.
        if idx >= 3 and (time.time() - last_growth) > 8.0:
            os.write(fd, b"/quit\r")
            time.sleep(0.5)
            break

    try:
        os.close(fd)
    except OSError:
        pass
    try:
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        pass
    return bytes(out)

def main():
    try:
        mod = load_wrapper()
    except Exception as e:
        print(f"FAIL: could not load wrapper module from {WRAP}: {e}", file=sys.stderr)
        return 2

    try:
        data = capture()
    except FileNotFoundError:
        print("FAIL: `claude` not on PATH", file=sys.stderr)
        return 2

    print(f"captured {len(data)} bytes from claude TUI\n")

    # 1) Literal SUBS — every needle must appear in raw claude output.
    # Some SUBS only fire on tool/UI elements that the test prompt doesn't
    # exercise (e.g. Skill needs an actual skill invocation). Skip those
    # needles instead of failing the test.
    untested_needles = {
        b'\x1b[1mSkill\x1b[22m',  # test prompt drives Bash, not a Skill call
    }
    print("=== literal SUBS (needles in raw claude output) ===")
    missing = []
    for needle, _ in mod.SUBS:
        if needle in untested_needles:
            print(f"  skip: {needle!r}  (no test scenario exercises this)")
            continue
        n = data.count(needle)
        status = "ok" if n > 0 else "MISSING"
        print(f"  {status}: {needle!r}  ({n} occurrences)")
        if n == 0:
            missing.append(needle)

    # 2) Regex pipeline — run apply_subs and check the highlighter actually
    # fired by looking for distinctive output byte sequences that ONLY come
    # from the regex pass (not from claude's stock theme).
    processed = mod.apply_subs(data)
    bash_name_sig = b'\x1b[1m' + mod.PALETTE['bash'] + b'Bash'
    cmd_word_sig  = b'\x1b[1m' + mod.PALETTE['cmd']  + b'pwd'

    print("\n=== regex SUBS (signatures in apply_subs output) ===")
    regex_missing = []
    for label, sig in [("bash name recolor", bash_name_sig),
                       ("shell highlighter on `pwd`", cmd_word_sig)]:
        n = processed.count(sig)
        status = "ok" if n > 0 else "MISSING"
        print(f"  {status}: {label}  ({n} occurrences)")
        if n == 0:
            regex_missing.append(label)

    if missing or regex_missing:
        if missing:
            print(
                f"\nFAIL: {len(missing)} literal needle(s) no longer appear in "
                "claude's output.\nClaude Code likely changed its SGR theme. "
                "Re-capture the palette and update SUBS in claude-theme-wrap.py.",
                file=sys.stderr,
            )
        if regex_missing:
            print(
                f"\nFAIL: {len(regex_missing)} regex signature(s) missing after "
                "apply_subs.\nThe Bash tool envelope or the shell highlighter "
                "tokenizer needs an update.",
                file=sys.stderr,
            )
        return 1

    print("\nOK: literal SUBS + regex SUBS both produce expected output.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
