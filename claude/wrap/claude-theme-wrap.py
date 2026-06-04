#!/usr/bin/env python3
"""Wrap `claude` in a PTY and rewrite specific SGR sequences in its stdout
stream to re-theme markdown rendering.

Zero-dependency by design (stdlib only) so the supply chain is exactly
this file. Falls through to direct exec when stdin/stdout aren't a TTY,
so non-interactive uses (`claude -p`, hooks, scripts) skip the PTY entirely.

Intentionally simple: ONLY literal byte substitutions — no regex state
machine, no nested span processing, no recursion. An earlier version
tried to collapse MCP tool envelopes and colorize nested paren/quote/
shell content, but those rules shattered on Claude's dynamic TUI redraws
and mid-word line wraps (e.g. `grug-recall` wrapping to `grug-rec` +
`all (MCP)` across two bold envelopes). We only touch exact byte
sequences we're certain about.
"""
import fcntl, os, select, signal, struct, subprocess, sys, termios, tty

# Palette: named foreground colors. TERM_DEFAULT defers to whatever your
# terminal has configured as its default fg, so styled elements blend with
# the surrounding text color.
TERM_DEFAULT = b'\x1b[39m'

def c256(n: int) -> bytes:
    return f'\x1b[38;5;{n}m'.encode()

PALETTE = {
    "code":   c256(214),      # inline `code` — orange
    "italic": c256(212),      # *italic* prose — pink/magenta
    "h1":     c256(220),      # # heading 1 — gold
    "tool":   c256(39),       # tool call ⏺ / result ⎿ marker — bright cyan
    "bash":   c256(208),      # Bash tool name — bright orange
}

# Rainbow palette: per-character colors for the Skill tool name. ROYGBIV-ish
# rotated through the 256-color cube.
RAINBOW = [c256(196), c256(208), c256(220), c256(46), c256(51), c256(141)]

def rainbow_text(text: bytes) -> bytes:
    out = bytearray()
    for i in range(len(text)):
        out += RAINBOW[i % len(RAINBOW)] + text[i:i+1]
    out += TERM_DEFAULT
    return bytes(out)

# Literal byte substitutions in claude's stdout stream. Order matters:
# earlier rules run first, and replacements aren't re-scanned by later rules.
SUBS = [
    # H1 first: catch the bold+italic+underline triple BEFORE the generic
    # italic rule below mutates the inner \e[3m. Combined-form SGR
    # (\e[1;3;4m) means the literal \e[3m disappears, so the italic rule
    # won't double-match this site.
    (b'\x1b[1m\x1b[3m\x1b[4m', b'\x1b[1;3;4m' + PALETTE["h1"]),
    # Inline code: replace claude's hardcoded pale blue (256-color 153).
    (b'\x1b[38;5;153m',        PALETTE["code"]),
    # Italic on: append palette color.
    (b'\x1b[3m',               b'\x1b[3m' + PALETTE["italic"]),
    # Italic off: always reset fg so any italic color doesn't bleed into
    # a following bold span.
    (b'\x1b[23m',              b'\x1b[23m' + TERM_DEFAULT),
    # Tool call ⏺ marker: claude uses gray 246 + ⏺ for the tool execution
    # bullet, distinct from the assistant's white 231 + ⏺ message bullet.
    # Recolor only the gray-⏺ pair so we don't touch other gray-246 chrome.
    (b'\x1b[38;5;246m\xe2\x8f\xba',     PALETTE["tool"] + b'\xe2\x8f\xba'),
    # Tool result connector: gray 246 + 2 spaces + ⎿. The color carries
    # through the rest of the line until \e[39m, so the entire result text
    # picks up the new color.
    (b'\x1b[38;5;246m  \xe2\x8e\xbf',   PALETTE["tool"] + b'  \xe2\x8e\xbf'),
    # Bash tool name: recolor the word "Bash" inside its bold envelope.
    # Leaves the (command) bytes untouched — no shell highlighter, no paren
    # coloring, so nothing can shatter if the envelope line-wraps.
    (b'\x1b[1mBash\x1b[22m',
     b'\x1b[1m' + PALETTE["bash"] + b'Bash' + TERM_DEFAULT + b'\x1b[22m'),
    # Skill tool name: bold envelope, replaced with rainbow per-character.
    (b'\x1b[1mSkill\x1b[22m',
     b'\x1b[1m' + rainbow_text(b'Skill') + b'\x1b[22m'),
]

# Hold back this many bytes from each chunk of claude's stdout so that
# literal SUBS needles straddling a chunk boundary still match on the next
# pass. Longest needle is ~14 bytes; 64 gives comfortable headroom.
MAX_HOLDBACK = 64

# When master_fd has been quiet for this many seconds, flush whatever's in
# the residue buffer. Without this, single-character TUI updates (input
# echo, cursor moves) are smaller than MAX_HOLDBACK and would otherwise
# sit in the residue forever, making interactive typing feel frozen.
IDLE_FLUSH_SECS = 0.03

def apply_subs(buf: bytes) -> bytes:
    for needle, repl in SUBS:
        buf = buf.replace(needle, repl)
    return buf

def set_pane_title() -> None:
    # OSC 2 sets tmux pane title (and iTerm/kitty window title). Independent
    # of `allow-rename`, which only gates the legacy \ek...\e\\ sequence.
    # Default to bare "claude" so we still win over "python" even if the
    # version probe fails (e.g. claude not on PATH at wrap start).
    title = "🤖"
    try:
        out = subprocess.run(
            ["claude", "--version"], capture_output=True, text=True, timeout=2
        )
        ver = out.stdout.strip().split()[0] if out.stdout.strip() else ""
        if ver:
            title = f"🤖 {ver}"
    except (OSError, subprocess.TimeoutExpired, IndexError):
        pass
    try:
        os.write(sys.stdout.fileno(), f"\x1b]2;{title}\x1b\\".encode())
    except OSError:
        pass
    # Inside tmux, claude overwrites the pane title and `allow-rename off`
    # blocks the \ek window-rename. A direct `tmux rename-window` side-steps
    # both: tmux marks the window manually-renamed so nothing clobbers it.
    if os.environ.get("TMUX"):
        try:
            subprocess.run(["tmux", "rename-window", title], timeout=2, check=False)
        except (OSError, subprocess.TimeoutExpired):
            pass

def get_term_size() -> tuple[int, int]:
    for fd in (sys.stdin.fileno(), sys.stdout.fileno(), sys.stderr.fileno()):
        try:
            sz = os.get_terminal_size(fd)
            return sz.lines, sz.columns
        except (OSError, ValueError):
            continue
    return 40, 120

def set_winsize(fd: int, rows: int, cols: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

def main() -> int:
    # Non-interactive: skip the wrapper entirely.
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        os.execvp("claude", ["claude"] + sys.argv[1:])

    set_pane_title()

    stdin_fd = sys.stdin.fileno()
    stdout_fd = sys.stdout.fileno()
    old_attrs = termios.tcgetattr(stdin_fd)
    # Raw mode BEFORE fork so the terminal never locally echoes the DA reply
    # that claude triggers the instant it starts.
    tty.setraw(stdin_fd)

    rows, cols = get_term_size()
    master_fd, slave_fd = os.openpty()
    set_winsize(slave_fd, rows, cols)
    # Disable ECHO on slave so wrapper-forwarded stdin doesn't bounce back
    # through master during the boot window before claude sets its own termios.
    slave_attrs = termios.tcgetattr(slave_fd)
    slave_attrs[3] &= ~(termios.ECHO | termios.ECHONL | termios.ECHOE | termios.ECHOK)
    termios.tcsetattr(slave_fd, termios.TCSANOW, slave_attrs)

    pid = os.fork()
    if pid == 0:
        os.close(master_fd)
        os.setsid()
        try:
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
        except OSError:
            pass
        os.dup2(slave_fd, 0)
        os.dup2(slave_fd, 1)
        os.dup2(slave_fd, 2)
        if slave_fd > 2:
            os.close(slave_fd)
        os.execvp("claude", ["claude"] + sys.argv[1:])
        os._exit(127)

    os.close(slave_fd)

    def on_resize(*_):
        r, c = get_term_size()
        set_winsize(master_fd, r, c)
    signal.signal(signal.SIGWINCH, on_resize)

    residue = b''
    try:
        while True:
            r, _, _ = select.select([stdin_fd, master_fd], [], [], IDLE_FLUSH_SECS)
            if not r:
                if residue:
                    os.write(stdout_fd, apply_subs(residue))
                    residue = b''
                continue
            if stdin_fd in r:
                try:
                    data = os.read(stdin_fd, 65536)
                except OSError:
                    break
                if not data:
                    break
                os.write(master_fd, data)
            if master_fd in r:
                try:
                    data = os.read(master_fd, 65536)
                except OSError:
                    break
                if not data:
                    break
                buf = residue + data
                if len(buf) > MAX_HOLDBACK - 1:
                    flush, residue = buf[:-(MAX_HOLDBACK - 1)], buf[-(MAX_HOLDBACK - 1):]
                else:
                    flush, residue = b'', buf
                os.write(stdout_fd, apply_subs(flush))
    finally:
        if residue:
            try:
                os.write(stdout_fd, apply_subs(residue))
            except OSError:
                pass
        termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_attrs)
    try:
        _, status = os.waitpid(pid, 0)
        return os.waitstatus_to_exitcode(status)
    except ChildProcessError:
        return 0

if __name__ == "__main__":
    sys.exit(main())
