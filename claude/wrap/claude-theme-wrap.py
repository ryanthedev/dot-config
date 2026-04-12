#!/usr/bin/env python3
"""Wrap `claude` in a PTY and rewrite specific SGR sequences in its stdout
stream to re-theme markdown rendering.

Zero-dependency by design (stdlib only) so the supply chain is exactly
this file. Falls through to direct exec when stdin/stdout aren't a TTY,
so non-interactive uses (`claude -p`, hooks, scripts) skip the PTY entirely.
"""
import fcntl, os, re, select, signal, struct, sys, termios, tty

# Palette: named foreground colors. TERM_DEFAULT defers to whatever your
# terminal has configured as its default fg (Ghostty/iTerm/etc substitute it),
# so styled elements blend with the surrounding text color.
TERM_DEFAULT = b'\x1b[39m'

def c256(n: int) -> bytes:
    return f'\x1b[38;5;{n}m'.encode()

def rgb(r: int, g: int, b: int) -> bytes:
    return f'\x1b[38;2;{r};{g};{b}m'.encode()

PALETTE = {
    "code":   c256(214),      # inline `code` — orange
    "italic": c256(212),      # *italic* prose — pink/magenta
    "h1":     c256(220),      # # heading 1 — gold
    "tool":   c256(39),       # tool call marker + result line — bright cyan
    "bash":   c256(208),      # Bash tool name specifically — bright orange
    "mcp":    c256(42),       # MCP tool envelope — bright green
    "paren":  c256(141),      # any (parenthesized content) — purple
    "string": c256(186),      # any "double" or 'single' quoted text — yellow
                              # (also reused by the shell highlighter inside Bash(...) parens)
    # Shell command syntax highlighting (inside Bash(...) parens):
    "cmd":    c256(82),       # command name (first word) — bright green
    "flag":   c256(81),       # -x / --long-flag — cyan
    "redir":  c256(201),      # | > < >> ; & — magenta
}

# Rainbow palette: per-character colors for the Skill tool name. ROYGBIV-ish
# rotated through the 256-color cube — picked for visual punch on dark
# terminals, not color-theory purity.
RAINBOW = [c256(196), c256(208), c256(220), c256(46), c256(51), c256(141)]

def rainbow_text(text: bytes) -> bytes:
    """Color each byte of `text` with the next color in RAINBOW, cycling."""
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
    # Italic on: append palette color (no-op visual when palette = TERM_DEFAULT).
    (b'\x1b[3m',               b'\x1b[3m' + PALETTE["italic"]),
    # Italic off: always reset fg so any italic color we injected doesn't
    # bleed into a following bold span.
    (b'\x1b[23m',              b'\x1b[23m' + TERM_DEFAULT),
    # Tool call marker: claude uses gray 246 + ⏺ for the tool execution
    # bullet, distinct from the assistant's white 231 + ⏺ message bullet.
    # Recolor only the gray-⏺ pair so we don't touch other gray-246 chrome.
    (b'\x1b[38;5;246m\xe2\x8f\xba',     PALETTE["tool"] + b'\xe2\x8f\xba'),
    # Tool result connector: gray 246 + 2 spaces + ⎿. The color carries
    # through the rest of the line until \e[39m, so the entire result text
    # picks up the new color.
    (b'\x1b[38;5;246m  \xe2\x8e\xbf',   PALETTE["tool"] + b'  \xe2\x8e\xbf'),
    # Skill tool name: same bold-text envelope as Bash, replaced with a
    # rainbow per-character render. The replacement bytes are precomputed
    # once at module load.
    (b'\x1b[1mSkill\x1b[22m',
     b'\x1b[1m' + rainbow_text(b'Skill') + b'\x1b[22m'),
]

# Tokenizer for shell commands. Order in the alternation matters because
# Python regex is leftmost-match: try strings first (so quotes don't get
# split into words), then flags, then redirects, then plain words.
SHELL_TOKEN_RE = re.compile(
    rb'(?P<string>"[^"]*"|\'[^\']*\')'
    rb'|(?P<flag>--?[A-Za-z][A-Za-z0-9_-]*)'
    rb'|(?P<redir>\|\||&&|>>|<<|[|<>;&])'
    rb'|(?P<word>[^\s|<>;&\'"]+)'
    rb'|(?P<space>\s+)'
)

def highlight_shell(cmd: bytes, parent: bytes = TERM_DEFAULT) -> bytes:
    """Color a shell command with stdlib regex tokenization.

    First word becomes the bold "command name" colored from PALETTE['cmd'].
    Subsequent flags, quoted strings, and pipe/redirect/separator characters
    each get their own palette color. Other tokens (positional args, paths)
    pass through with default fg so they read against the surrounding text.

    `parent` is the color to restore to after each highlighted token, so
    that when this is called from inside a colored span (e.g. a paren rule)
    the surrounding color isn't lost.
    """
    out = bytearray()
    seen_command = False
    for m in SHELL_TOKEN_RE.finditer(cmd):
        kind = m.lastgroup
        text = m.group()
        if kind == 'string':
            out += PALETTE['string'] + text + parent
        elif kind == 'flag':
            out += PALETTE['flag'] + text + parent
        elif kind == 'redir':
            out += PALETTE['redir'] + text + parent
        elif kind == 'word' and not seen_command:
            out += b'\x1b[1m' + PALETTE['cmd'] + text + parent + b'\x1b[22m'
            seen_command = True
        else:
            out += text
    return bytes(out)

# =============================================================================
# State-machine semantic processor
# =============================================================================
# After literal SUBS run, we walk the byte stream once and recognize semantic
# spans (paren groups, quoted strings, Bash/MCP tool calls, etc.). Each span
# tracks its "parent color" — the color that was active in the surrounding
# context — so that when the span closes we restore THAT color instead of
# emitting a bare \e[39m (which resets to terminal default and would erase
# any outer color we were nested inside).
#
# Bare \e[39m bytes encountered in the input stream are also replaced with
# the current parent color, so previous SGR resets (from claude itself or
# from our literal SUBS) don't break nested coloring either.
# =============================================================================

RESET_FG = b'\x1b[39m'

# Bash tool envelope. Matches \e[1mBash\e[22m(<cmd>) with a contiguous
# non-escape command. Multi-line/wrapped commands (cursor codes interleaved)
# are silently skipped because the [^\x1b)]+ class excludes escape bytes.
BASH_CALL_RE = re.compile(rb'\x1b\[1mBash\x1b\[22m\(([^\x1b)]+)\)')

def handle_bash(m: 're.Match[bytes]', parent: bytes) -> bytes:
    cmd = m.group(1)
    return (
        b'\x1b[1m' + PALETTE['bash'] + b'Bash' + parent + b'\x1b[22m'
        + b'(' + highlight_shell(cmd, parent) + b')'
    )

# MCP tool envelope. Claude renders MCP tool calls as a bold prefix:
#   \e[1mplugin:server:server - toolname (MCP)\e[22m
# BUT the prefix is interleaved with cursor-positioning escapes — \e[1C
# (forward-1 as space substitute) between words in the trust dialog, and
# \r\e[2B (CR + cursor down) between (MCP) and the bold-off in the
# in-progress render. So we match ANY bold envelope and validate the inner
# content for the MCP shape after stripping cursor noise. Non-MCP bold
# envelopes return None and the state machine falls through.
MCP_BOLD_RE = re.compile(
    rb'\x1b\[1m((?:(?!\x1b\[22m).)*?)\x1b\[22m', re.DOTALL
)
# Cursor-forward escapes — claude uses these as space substitutes, so we
# expand them to literal spaces (one per column moved) before plain-text
# matching. Other cursor moves (up/down/left, clear) get stripped entirely.
CURSOR_FWD_RE = re.compile(rb'\x1b\[(\d*)C')
TUI_DROP_RE   = re.compile(rb'\x1b\[[0-9;]*[ABDEFGHJK]|\r')
# Once normalized, an MCP envelope reads exactly like this:
MCP_PLAIN_RE = re.compile(rb'^plugin:\S+ - (\S+) \(MCP\)$')

def normalize_tui(buf: bytes) -> bytes:
    """Expand cursor-forward escapes to spaces and drop other cursor noise.

    Claude's TUI saves bytes by emitting \\e[1C (cursor forward 1) instead
    of a literal space character between words. To match its bold envelopes
    against plain-text patterns, we need to undo that optimization."""
    buf = CURSOR_FWD_RE.sub(lambda m: b' ' * int(m.group(1) or b'1'), buf)
    buf = TUI_DROP_RE.sub(b'', buf)
    return buf

def handle_mcp(m: 're.Match[bytes]', parent: bytes):
    """Collapse a bold MCP envelope into "⚡ toolname (MCP)". Returns None
    if the matched bold envelope is NOT an MCP call, so the state machine
    falls through to the next matcher / passes the bytes through unchanged."""
    plain = normalize_tui(m.group(1))
    name_match = MCP_PLAIN_RE.match(plain)
    if name_match is None:
        return None
    tool = name_match.group(1)
    return (
        b'\x1b[1m'
        + PALETTE['mcp'] + b'\xe2\x9a\xa1 ' + tool + parent
        + b'\x1b[22m'
        + b' (MCP)'
    )

# Generic parenthesized content. The inner character class permits cursor-
# forward escapes (\e[<n>C) because claude uses \e[1C as a space-substitute.
# Other escape sequences inside the parens still cause the match to fail,
# which is desirable: it means already-styled regions (Bash output etc.) opt
# out of the generic paren rule.
PAREN_RE = re.compile(rb'\(((?:[^()\x1b]|\x1b\[[0-9]*C)+)\)')

def handle_paren(m: 're.Match[bytes]', parent: bytes):
    inner_raw = m.group(1)
    # Skip the literal "(MCP)" — that's part of an MCP tool render which
    # we'd rather see plain than purple-recolored as a generic paren.
    if inner_raw == b'MCP':
        return None
    inner = process(inner_raw, PALETTE['paren'])
    return b'(' + PALETTE['paren'] + inner + parent + b')'

# Double-quoted text.
DQUOTE_RE = re.compile(rb'"((?:[^"\x1b]|\x1b\[[0-9]*C)+)"')

def handle_dquote(m: 're.Match[bytes]', parent: bytes) -> bytes:
    inner = process(m.group(1), PALETTE['string'])
    return b'"' + PALETTE['string'] + inner + parent + b'"'

# Single-quoted text. Lookbehind/lookahead require the opening quote to NOT
# be preceded by a letter and the closing quote to NOT be followed by one,
# which excludes contractions and possessives ("don't", "it's", "Sam's car").
SQUOTE_RE = re.compile(
    rb"(?<![A-Za-z])'((?:[^'\x1b]|\x1b\[[0-9]*C)+)'(?![A-Za-z])"
)

def handle_squote(m: 're.Match[bytes]', parent: bytes) -> bytes:
    inner = process(m.group(1), PALETTE['string'])
    return b"'" + PALETTE['string'] + inner + parent + b"'"

# Span matchers. Each entry is (first_byte_set, regex, handler). The first-
# byte set is a fast-path filter so we don't try every regex at every
# position. ORDER MATTERS: specific envelopes (Bash, MCP) before generic
# rules (paren, dquote, squote) so the specific handlers claim the bytes
# first and the generic rules don't double-match the same content.
#
# Handlers may return None to mean "this isn't actually one of mine" — the
# state machine then tries the next matcher (or falls through to byte
# pass-through). This lets a permissive matcher like MCP_BOLD_RE — which
# matches ANY bold envelope — only consume the bytes it actually owns.
SPAN_MATCHERS: list = [
    (b'\x1b', BASH_CALL_RE,  handle_bash),
    (b'\x1b', MCP_BOLD_RE,   handle_mcp),
    (b'(',    PAREN_RE,      handle_paren),
    (b'"',    DQUOTE_RE,     handle_dquote),
    (b"'",    SQUOTE_RE,     handle_squote),
]

def process(buf: bytes, parent: bytes = TERM_DEFAULT) -> bytes:
    """Walk `buf` byte by byte, expanding semantic spans with proper nesting.

    `parent` is the color the surrounding context expects to be active.
    Inside this call, any literal \\e[39m in the input is rewritten as
    `parent` so that nested coloring restores correctly. Spans recurse with
    their own color as the new parent for their contents. Handlers may
    return None to decline a match — the state machine then tries the next
    matcher in priority order.
    """
    out = bytearray()
    i = 0
    n = len(buf)
    while i < n:
        # Replace bare \e[39m with the current parent so prior color resets
        # (from claude or from literal SUBS) don't break nested coloring.
        if buf[i:i+5] == RESET_FG:
            out += parent
            i += 5
            continue

        b = buf[i:i+1]
        consumed = False
        for first_set, regex, handler in SPAN_MATCHERS:
            if b not in first_set:
                continue
            m = regex.match(buf, i)
            if m is None:
                continue
            result = handler(m, parent)
            if result is None:
                # Handler declined this match. Try the next matcher.
                continue
            out += result
            i = m.end()
            consumed = True
            break

        if not consumed:
            out += buf[i:i+1]
            i += 1

    return bytes(out)

# Hold back this many bytes from each chunk of claude's stdout so that
# needles or regex matches straddling chunk boundaries still match on the
# next pass. 256 covers every literal SUB needle (max ~9 bytes) AND every
# realistic Bash(<cmd>) call where the command fits on one rendered line.
MAX_HOLDBACK = 256

# When master_fd has been quiet for this many seconds, flush whatever's in
# the residue buffer. Without this, single-character TUI updates (input
# echo, cursor moves) are smaller than MAX_HOLDBACK and would otherwise
# sit in the residue forever, making interactive typing feel frozen.
IDLE_FLUSH_SECS = 0.03

def apply_subs(buf: bytes) -> bytes:
    """Run literal SUBS first, then the state-machine semantic processor."""
    for needle, repl in SUBS:
        buf = buf.replace(needle, repl)
    return process(buf)

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
                # Idle: flush whatever's held back so interactive single-char
                # updates aren't stuck in the residue waiting for more bytes.
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
                # Hold back the tail so needles or regex patterns straddling
                # chunk boundaries still match on the next pass. The idle
                # flush above guarantees the held bytes don't sit forever.
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
