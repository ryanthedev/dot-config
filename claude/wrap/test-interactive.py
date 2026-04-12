#!/usr/bin/env python3
"""Interactive responsiveness test for claude-theme-wrap.

Spawns the wrapper in a PTY (so test stdin/stdout becomes the wrapper's
"user terminal"), waits for claude to boot, types a single sentinel
character, and asserts the character appears in the wrapper's output
stream within a latency budget. This catches buffering bugs — e.g., a
too-large holdback that leaves keystrokes stuck in the residue buffer
forever — which the byte-counting smoke test would never detect.

Run:  python3 ~/.config/claude/wrap/test-interactive.py
Exit: 0 on success, 1 on visible regression, 2 on driver error.
"""
import fcntl, os, pty, select, struct, sys, termios, time

WRAPPER = "/Users/r/.config/claude/wrap/claude-theme-wrap.py"
# Single ASCII char that should NOT appear anywhere in claude's startup
# chrome. '@' is safe — verified empirically against claude 2.1.101.
SENTINEL = b"@"
# How long after sending the sentinel we'll wait for it to echo back.
# 30ms idle flush + double-PTY overhead + claude render = well under 500ms.
LATENCY_BUDGET_MS = 500
# Total deadline for the whole test (boot + interaction + cleanup).
DEADLINE_S = 25.0
ROWS, COLS = 50, 140

def set_winsize(fd: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))

def main() -> int:
    pid, fd = pty.fork()
    if pid == 0:
        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        env["FORCE_COLOR"] = "1"
        os.execvpe("python3", ["python3", WRAPPER], env)
        os._exit(127)

    set_winsize(fd)
    out = bytearray()
    start = time.time()

    # Drive plan:
    #   t=3.0  send Enter (accept trust dialog if present, no-op otherwise)
    #   t=5.0  send sentinel '@', start latency timer
    #   then watch for sentinel to appear in subsequent bytes
    sent_trust = False
    sentinel_sent_at = None
    sentinel_send_offset = 0
    sentinel_seen_at = None

    while True:
        now = time.time() - start
        if now > DEADLINE_S:
            break
        if sentinel_seen_at is not None:
            break

        r, _, _ = select.select([fd], [], [], 0.05)
        if fd in r:
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                break
            if not chunk:
                break
            out.extend(chunk)
            # Only count bytes that arrived AFTER we sent the sentinel.
            if sentinel_sent_at is not None and sentinel_seen_at is None:
                tail = bytes(out[sentinel_send_offset:])
                if SENTINEL in tail:
                    sentinel_seen_at = time.time()

        if not sent_trust and now >= 3.0:
            os.write(fd, b"\r")
            sent_trust = True
        if sent_trust and sentinel_sent_at is None and now >= 5.0:
            sentinel_send_offset = len(out)
            os.write(fd, SENTINEL)
            sentinel_sent_at = time.time()

    # Cleanup: try to quit cleanly so we don't leave a zombie wrapper.
    try:
        os.write(fd, b"\x1b")  # escape any modal
        time.sleep(0.1)
        os.write(fd, b"/quit\r")
        time.sleep(0.3)
    except OSError:
        pass
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        pass

    # Save the captured stream for debugging when something goes wrong.
    debug_path = "/tmp/claude-theme-wrap-test-interactive.raw"
    try:
        with open(debug_path, "wb") as f:
            f.write(bytes(out))
    except OSError:
        pass

    print(f"captured {len(out)} bytes from wrapper")
    print(f"debug dump: {debug_path}")

    if sentinel_sent_at is None:
        print("FAIL: never reached the point of sending the sentinel "
              "(wrapper or claude failed to boot)", file=sys.stderr)
        return 2

    if sentinel_seen_at is None:
        print(
            f"FAIL: sentinel {SENTINEL!r} sent at t={sentinel_sent_at-start:.2f}s "
            f"but never appeared in wrapper output within {DEADLINE_S}s.\n"
            "This means the wrapper is buffering interactive bytes — either "
            "MAX_HOLDBACK is too large with no idle flush, or the residue "
            "logic is broken. Inspect /tmp/claude-theme-wrap-test-interactive.raw.",
            file=sys.stderr,
        )
        return 1

    latency_ms = (sentinel_seen_at - sentinel_sent_at) * 1000
    print(f"sentinel echo latency: {latency_ms:.0f}ms (budget {LATENCY_BUDGET_MS}ms)")

    if latency_ms > LATENCY_BUDGET_MS:
        print(
            f"FAIL: sentinel echoed but latency {latency_ms:.0f}ms exceeds "
            f"budget {LATENCY_BUDGET_MS}ms — interactive feel is degraded.",
            file=sys.stderr,
        )
        return 1

    print("OK: wrapper echoes single keystrokes within latency budget.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
