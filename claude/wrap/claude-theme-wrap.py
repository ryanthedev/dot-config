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

# DEC private mode 2026 (Synchronized Output) markers. Claude's Ink-fork
# renderer wraps every render-op batch in BSU … ops … ESU so the terminal
# applies the whole frame atomically (no tearing). The wrapper MUST keep
# each BSU…ESU span intact: slicing it strands the closing ESU and the
# terminal shows a stale/partial frame (the ghosting bug). Both markers are
# 8 bytes and share the 7-byte prefix \x1b[?2026, differing only in the
# final h/l — so a straddling-read holdback of len(marker)-1 = 7 bytes is
# enough to never emit a partial marker.
BSU = b'\x1b[?2026h'   # Begin Synchronized Update
ESU = b'\x1b[?2026l'   # End Synchronized Update
_MARKER_PREFIX = b'\x1b[?2026'  # shared 7-byte prefix of BSU/ESU

# Size backstop. An open frame that never sees its ESU (malformed stream,
# attach mid-render) must not buffer without bound. When the open frame
# crosses this cap we flush what we have (SUBS applied) and stream the rest
# of that frame raw until the ESU arrives — atomicity degrades for one
# oversized frame, but memory stays bounded and the stream stays live.
# 256 KiB comfortably exceeds any real Claude render batch.
FRAME_BYTE_CAP = 256 * 1024

# When master_fd has been quiet for this many seconds, flush whatever's in
# the FrameMux's open frame (time backstop). Without this, a frame whose
# ESU never arrives — or single-character TUI updates that open no frame at
# all — would sit buffered forever, making the screen look frozen. The mux
# itself is clockless; this timeout is the loop's responsibility.
IDLE_FLUSH_SECS = 0.03

def apply_subs(buf: bytes) -> bytes:
    for needle, repl in SUBS:
        buf = buf.replace(needle, repl)
    return buf

def _partial_marker_tail_len(buf: bytes) -> int:
    """Length of the longest suffix of `buf` that is a proper prefix of a
    marker (BSU/ESU share _MARKER_PREFIX). These bytes might be the start of
    a marker split across two reads, so out-of-frame scanning holds them back
    rather than emitting them as passthrough and missing the boundary.

    Returns 0..len(_MARKER_PREFIX) (i.e. ≤7). A complete marker is matched by
    the caller's find() before this runs, so we only look for partial ones.
    """
    max_tail = min(len(buf), len(_MARKER_PREFIX))
    # Longest first so we hold the smallest safe amount (a 1-byte ESC is the
    # weakest match; a 7-byte \x1b[?2026 is the strongest).
    for n in range(max_tail, 0, -1):
        if _MARKER_PREFIX.startswith(buf[-n:]):
            return n
    return 0

class FrameMux:
    """Frame-aware byte multiplexer for Claude's Synchronized-Output stream.

    Pure and clockless: `feed` is a deterministic function of (state, bytes)
    with no I/O and no wall-clock dependency, so it is fully unit-testable
    against synthetic streams. The time backstop lives in the I/O loop, which
    calls `drain()` on idle timeout.

    States:
      out-of-frame  — pass bytes through raw; hold back only a ≤7-byte tail
                      that might be the start of a split marker.
      in-frame      — buffer the open frame; emit nothing until its ESU, then
                      emit apply_subs(whole frame) atomically.
      degraded      — an open frame crossed FRAME_BYTE_CAP; its head was
                      flushed, so stream the rest raw until ESU (still holding
                      a ≤7-byte partial-ESU tail) to preserve liveness.

    Robustness over correctness (this is an interactive tool): any malformed
    marker (ESU with no open BSU, an inner BSU, a never-closed frame) degrades
    to passthrough/flush — it never raises and never blocks the terminal.
    """

    def __init__(self) -> None:
        self._frame = bytearray()  # buffered open-frame bytes (in-frame state)
        self._in_frame = False     # True between a BSU and its ESU
        self._degraded = False     # True while streaming an oversized frame raw
        self._tail = b''           # held-back ≤7-byte possible-partial-marker bytes

    def has_open_frame(self) -> bool:
        """True while any bytes are buffered awaiting an ESU (or a held tail
        exists). The loop uses this to decide whether the idle-timeout backstop
        needs to drain."""
        return self._in_frame or self._degraded or bool(self._frame) or bool(self._tail)

    def feed(self, data: bytes) -> bytes:
        """Process a chunk; return bytes safe to write now = completed frames
        (BSU…ESU span, SUBS applied) plus raw out-of-frame bytes. Buffers the
        open frame and any trailing partial-marker bytes; emits nothing for an
        open frame until its ESU. `feed(b'')` is a no-op returning b''."""
        # Re-attach any tail held from the previous read so a marker split
        # across reads is scanned as one contiguous span.
        pending = self._tail + data
        self._tail = b''
        out = bytearray()
        while pending:
            if self._in_frame:
                pending = self._step_in_frame(pending, out)
            elif self._degraded:
                pending = self._step_degraded(pending, out)
            else:
                pending = self._step_out_of_frame(pending, out)
        return bytes(out)

    def drain(self) -> bytes:
        """Flush everything buffered now (SUBS applied to frame content) and
        reset to out-of-frame ground state. Called by the loop on idle timeout
        (time backstop) and at shutdown. Idempotent once buffers are empty:
        returns b'' and stays in ground state."""
        out = bytearray()
        if self._frame:
            # An open frame never reached its ESU; emit it themed anyway so the
            # screen advances rather than freezing.
            out += apply_subs(bytes(self._frame))
            self._frame = bytearray()
        if self._tail:
            # A held partial-marker tail turned out not to complete; it is
            # ordinary out-of-frame content, so emit it raw.
            out += self._tail
            self._tail = b''
        self._in_frame = False
        self._degraded = False
        return bytes(out)

    def _step_out_of_frame(self, pending: bytes, out: bytearray) -> bytes:
        """Out-of-frame: emit raw up to a BSU. On BSU, enter in-frame buffering.
        With no BSU, emit all but a possible split-marker tail (held back)."""
        idx = pending.find(BSU)
        if idx != -1:
            out += pending[:idx]            # raw bytes before the frame
            self._frame = bytearray(BSU)    # BSU is part of the atomic frame
            self._in_frame = True
            return pending[idx + len(BSU):]
        # No complete BSU: everything except a possible partial-marker tail is
        # safe out-of-frame passthrough. Hold the tail for the next read.
        keep = _partial_marker_tail_len(pending)
        emit_len = len(pending) - keep
        out += pending[:emit_len]
        self._tail = pending[emit_len:]
        return b''  # tail is parked; nothing left actionable this call

    def _step_in_frame(self, pending: bytes, out: bytearray) -> bytes:
        """In-frame: buffer toward the ESU. On ESU, emit apply_subs(frame)
        atomically and return to out-of-frame. Only an ESU ends a frame, so an
        inner BSU is treated as frame content. Trip the size backstop if the
        open frame outgrows FRAME_BYTE_CAP before its ESU.

        The ESU can straddle the already-buffered frame tail and `pending`, so
        we append first and search the whole buffer from just before the seam
        (len(ESU)-1 bytes back) — never missing a split-marker boundary."""
        seam = max(0, len(self._frame) - (len(ESU) - 1))
        self._frame += pending
        idx = self._frame.find(ESU, seam)
        if idx != -1:
            end = idx + len(ESU)                 # ESU closes the atomic frame
            leftover = bytes(self._frame[end:])
            out += apply_subs(bytes(self._frame[:end]))
            self._frame = bytearray()
            self._in_frame = False
            return leftover
        # No ESU yet: keep waiting — unless we've buffered too much, in which
        # case flush and degrade to raw streaming to keep memory bounded.
        if len(self._frame) > FRAME_BYTE_CAP:
            out += apply_subs(bytes(self._frame))
            self._frame = bytearray()
            self._in_frame = False
            self._degraded = True
        return b''

    def _step_degraded(self, pending: bytes, out: bytearray) -> bytes:
        """Degraded (oversized frame): stream raw until the ESU, then return to
        out-of-frame. Hold a ≤7-byte partial-ESU tail so the boundary is never
        missed across reads."""
        idx = pending.find(ESU)
        if idx != -1:
            out += pending[:idx + len(ESU)]   # ESU still written so sync mode closes
            self._degraded = False
            return pending[idx + len(ESU):]
        # No ESU: emit all but a possible partial-marker tail, hold the tail.
        keep = _partial_marker_tail_len(pending)
        emit_len = len(pending) - keep
        out += pending[:emit_len]
        self._tail = pending[emit_len:]
        return b''

def write_all(fd: int, data: bytes) -> None:
    """Write every byte, looping on short writes.

    os.write to a tty/pty can return fewer bytes than requested when the
    downstream buffer is full or a write is interrupted. Ignoring the count
    silently drops the tail of a frame — a dropped erase/cursor sequence
    leaves stale glyphs on screen (redraw ghosting). Loop until drained.
    Python retries EINTR for us (PEP 475); we only need to handle partials.
    """
    mv = memoryview(data)
    while mv:
        n = os.write(fd, mv)
        mv = mv[n:]

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

    mux = FrameMux()
    try:
        while True:
            r, _, _ = select.select([stdin_fd, master_fd], [], [], IDLE_FLUSH_SECS)
            if not r:
                # Time backstop: an open frame whose ESU hasn't arrived (or a
                # held partial-marker tail) would otherwise freeze the screen.
                # The mux is clockless, so the loop owns this flush.
                if mux.has_open_frame():
                    write_all(stdout_fd, mux.drain())
                continue
            if stdin_fd in r:
                try:
                    data = os.read(stdin_fd, 65536)
                except OSError:
                    break
                if not data:
                    break
                write_all(master_fd, data)
            if master_fd in r:
                try:
                    data = os.read(master_fd, 65536)
                except OSError:
                    break
                if not data:
                    break
                write_all(stdout_fd, mux.feed(data))
    finally:
        # Drain whatever the mux still holds so the final frame isn't lost.
        try:
            write_all(stdout_fd, mux.drain())
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
