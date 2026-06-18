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
import fcntl, os, re, select, signal, struct, subprocess, sys, termios, tty

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

    Kept for the marker-only reasoning it documents; the out-of-frame and
    degraded steps now use the needle-aware `_held_tail_len` below.
    """
    max_tail = min(len(buf), len(_MARKER_PREFIX))
    # Longest first so we hold the smallest safe amount (a 1-byte ESC is the
    # weakest match; a 7-byte \x1b[?2026 is the strongest).
    for n in range(max_tail, 0, -1):
        if _MARKER_PREFIX.startswith(buf[-n:]):
            return n
    return 0

# Holdback alphabet: every SUBS needle plus the full BSU/ESU markers. A split
# that lands inside ANY of these at a read boundary must be withheld so the
# needle/marker is never emitted half-formed (and so apply_subs can match it,
# or find() can detect the marker, once the rest arrives on the next read).
# The FULL 8-byte markers are used (not the 7-byte shared prefix) so the rule
# is uniform: holding a *proper* prefix of a token is correct for both — e.g.
# the 7-byte _MARKER_PREFIX is a proper prefix of the 8-byte BSU, so it is
# still held. Derived from SUBS — never a hardcoded byte count — so adding a
# longer needle automatically widens the bound.
_HOLD_PREFIXES = tuple(n for n, _ in SUBS) + (BSU, ESU)
# Longest possible held tail = longest holdback token minus one. A complete
# token is matched (substituted, or framed by find()) before holdback runs, so
# we only ever hold a PROPER prefix — at most len-1 bytes.
_MAX_HOLD = max(len(p) for p in _HOLD_PREFIXES) - 1

def _held_tail_len(buf: bytes) -> int:
    """Length of the longest suffix of `buf` that is a proper prefix of any
    SUBS needle OR the 2026-marker prefix. Those trailing bytes might be the
    start of a needle/marker split across two reads, so the out-of-frame and
    degraded steps hold them back rather than emitting them un-substituted and
    missing the match on the next read.

    Returns 0.._MAX_HOLD. Only a PROPER (strictly shorter) prefix is held: a
    suffix that exactly equals a complete needle is left for apply_subs to
    rewrite in place, and a complete marker is found by the caller's find()
    before this runs — so only genuine partial tails are withheld. Bounded by
    _MAX_HOLD (= longest token len − 1), so feeding only prefix bytes can never
    grow the held tail without bound.
    """
    max_tail = min(len(buf), _MAX_HOLD)
    # Longest candidate first → hold the smallest amount that is still safe.
    for n in range(max_tail, 0, -1):
        suffix = buf[-n:]
        for prefix in _HOLD_PREFIXES:
            # `len(suffix) < len(prefix)` keeps this a PROPER prefix: a suffix
            # that is a whole needle is complete content (apply_subs handles
            # it), not an in-progress token to hold back.
            if len(suffix) < len(prefix) and prefix.startswith(suffix):
                return n
    return 0

class FrameMux:
    """Frame-aware byte multiplexer for Claude's Synchronized-Output stream.

    Pure and clockless: `feed` is a deterministic function of (state, bytes)
    with no I/O and no wall-clock dependency, so it is fully unit-testable
    against synthetic streams. The time backstop lives in the I/O loop, which
    calls `drain()` on idle timeout.

    States:
      out-of-frame  — substitute (apply_subs) the streamed bytes; hold back
                      only a ≤_MAX_HOLD tail that might be the start of a split
                      needle or marker. Claude emits 2026 frames only when the
                      terminal advertises sync support, so this is the common
                      path and themed content must be subbed here too.
      in-frame      — buffer the open frame; emit nothing until its ESU, then
                      emit apply_subs(whole frame) atomically.
      degraded      — an open frame crossed FRAME_BYTE_CAP; its head was
                      flushed, so substitute the rest until ESU (still holding
                      a ≤_MAX_HOLD partial needle/marker tail) to preserve
                      liveness.

    Robustness over correctness (this is an interactive tool): any malformed
    marker (ESU with no open BSU, an inner BSU, a never-closed frame) degrades
    to passthrough/flush — it never raises and never blocks the terminal.
    """

    def __init__(self) -> None:
        self._frame = bytearray()  # buffered open-frame bytes (in-frame state)
        self._in_frame = False     # True between a BSU and its ESU
        self._degraded = False     # True while streaming an oversized frame raw
        self._tail = b''           # held-back ≤_MAX_HOLD possible-partial needle/marker bytes

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
        returns b'' and stays in ground state. An open frame is closed with a
        synthesized ESU so the flush never strands the terminal mid-sync."""
        out = bytearray()
        if self._frame:
            # An open frame never reached its ESU. It begins with a BSU (added
            # in _step_out_of_frame), so flushing it as-is would leave that BSU
            # unmatched and strand the terminal mid-synchronized-update: it
            # keeps buffering this partial frame and drops the rest of its draw
            # ops — e.g. the input box's side/bottom borders, which redraw on
            # every keystroke — until some later ESU. Close the frame ourselves
            # with an ESU so the terminal paints what we have and exits sync
            # mode. The real ESU, when it finally arrives, lands out-of-frame
            # and is a harmless no-op (it just ends sync mode again on an
            # already-closed update).
            out += apply_subs(bytes(self._frame)) + ESU
            self._frame = bytearray()
        if self._tail:
            # A held partial needle/marker tail never completed. It is an
            # incomplete token (it would not match apply_subs anyway), so flush
            # it raw — an acceptable cosmetic miss, not a stranded marker.
            out += self._tail
            self._tail = b''
        self._in_frame = False
        self._degraded = False
        return bytes(out)

    def _step_out_of_frame(self, pending: bytes, out: bytearray) -> bytes:
        """Out-of-frame: substitute up to a BSU. On BSU, enter in-frame
        buffering. With no BSU, substitute all but a possible split needle/
        marker tail (held back). Claude emits 2026 frames only when the terminal
        advertises sync support, so out-of-frame is the common case (e.g. tmux
        with sync disabled) — themed content lives here too and MUST be subbed."""
        idx = pending.find(BSU)
        if idx != -1:
            # A needle cannot overlap the BSU bytes (\x1b[?2026h is not a
            # substring of any needle), so the pre-BSU slice is a hard cut and
            # apply_subs over it is safe.
            out += apply_subs(pending[:idx])   # themed bytes before the frame
            self._frame = bytearray(BSU)       # BSU is part of the atomic frame
            self._in_frame = True
            return pending[idx + len(BSU):]
        # No complete BSU: substitute everything except a possible partial
        # needle/marker tail (held so a split needle still matches next read).
        keep = _held_tail_len(pending)
        emit_len = len(pending) - keep
        out += apply_subs(pending[:emit_len])
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
        """Degraded (oversized frame): substitute the streamed bytes until the
        ESU, then return to out-of-frame. Hold a partial needle/marker tail so a
        split boundary is never missed across reads."""
        idx = pending.find(ESU)
        if idx != -1:
            # Substitute the pre-ESU slice; emit the ESU VERBATIM. The ESU is
            # not a needle — wrapping it in apply_subs risks corrupting the
            # sync-close marker, so it is a hard cut (apply_subs(pre) + ESU,
            # never apply_subs(pre + ESU)).
            out += apply_subs(pending[:idx]) + pending[idx:idx + len(ESU)]
            self._degraded = False
            return pending[idx + len(ESU):]
        # No ESU: substitute all but a possible partial needle/marker tail.
        keep = _held_tail_len(pending)
        emit_len = len(pending) - keep
        out += apply_subs(pending[:emit_len])
        self._tail = pending[emit_len:]
        return b''

# Compiled token recognizers for the ScreenRepair intent parser. These match
# the SAME subset of sequences claude emits that the test oracle (testdata/
# vtmodel.py) understands — but this is an INDEPENDENT implementation. The
# oracle is the checker; ScreenRepair is the production code. Keeping them
# separate is deliberate: a bug shared between model and checker could hide a
# failure, so neither imports the other.
_SR_CSI = re.compile(rb'\x1b\[([0-9;?]*)([A-Za-z@])')
_SR_OSC = re.compile(rb'\x1b\][^\x07]*(?:\x07|\x1b\\)')
_SR_ESC1 = re.compile(rb'\x1b[^\[\]]')
# Holdback bounds for an incomplete trailing ESC sequence split across reads.
# A partial UTF-8 char is at most 3 trailing bytes. A partial CSI is short, so a
# small bound suffices and a runaway (never-terminated) garbage CSI can't grow
# the held tail without limit. A partial OSC, however, can be long and
# LEGITIMATE — claude emits OSC 7 hyperlinks carrying file:// URLs (and OSC 8
# links) that easily exceed the CSI bound; releasing such an OSC half-formed
# would dump its body into the grid as visible text (the bug this guards). So
# OSC gets a far larger bound; past it we give up and let the parser skip it.
_SR_MAX_HOLD_CSI = 64
_SR_MAX_HOLD_OSC = 4096
_SR_MAX_HOLD = _SR_MAX_HOLD_OSC   # the widest tail we will ever hold

# --- SGR (color/attribute) state engine ----------------------------------
# ECMA-48 character-attribute flags claude uses, each as (on-codes, off-code).
# The off-code is the canonical cancel for that flag; bold and dim BOTH cancel
# with 22, which we model below. These let us re-emit claude's intent: a cell's
# active style is the set of flags + fg + bg in effect when it was written, and
# the emitter replays the EXACT original byte tokens that set them so downstream
# apply_subs still matches needles like \x1b[1mSkill\x1b[22m and \x1b[38;5;153m.
_SGR_FLAG_BY_CODE = {
    1: ("bold", b'\x1b[1m', b'\x1b[22m'),
    2: ("dim", b'\x1b[2m', b'\x1b[22m'),
    3: ("italic", b'\x1b[3m', b'\x1b[23m'),
    4: ("underline", b'\x1b[4m', b'\x1b[24m'),
    5: ("blink", b'\x1b[5m', b'\x1b[25m'),
    7: ("inverse", b'\x1b[7m', b'\x1b[27m'),
    8: ("hidden", b'\x1b[8m', b'\x1b[28m'),
    9: ("strike", b'\x1b[9m', b'\x1b[29m'),
}
# off-code -> the flag name(s) it cancels (22 cancels both bold and dim).
_SGR_OFF = {22: ("bold", "dim"), 23: ("italic",), 24: ("underline",),
            25: ("blink",), 27: ("inverse",), 28: ("hidden",), 29: ("strike",)}
# Flag emit order: deterministic so two equal states produce byte-identical
# replay (run-coalescing + the DW-1.4 determinism gate both rely on this).
_SGR_FLAG_ORDER = ("bold", "dim", "italic", "underline", "blink",
                   "inverse", "hidden", "strike")


class _SGR:
    """Faithful, sticky SGR attribute state with original-byte memory.

    Models terminal SGR accumulation (a token mutates only the attributes it
    names; others persist) over the subset claude emits: flags 1/2/3/4/5/7/8/9
    and their cancels, 256-color fg (38;5;n) / bg (48;5;n), the 8/16 named
    fg/bg (30-37/90-97, 40-47/100-107), default fg 39 / bg 49, and full reset 0.

    For each active attribute it remembers the EXACT original byte token claude
    used to set it, so the emitter can replay claude's intent byte-for-byte and
    downstream apply_subs needles (\x1b[38;5;153m, \x1b[1mBash\x1b[22m, ...) still
    match. Pure: no clock, no I/O; a deterministic function of (state, token).
    """

    __slots__ = ("flags", "fg", "bg")

    def __init__(self):
        # flags: name -> on-token bytes (presence == active).
        self.flags = {}
        self.fg = None   # (token_bytes,) or None for default
        self.bg = None   # (token_bytes,) or None for default

    def copy_key(self):
        """A hashable snapshot of the active style, used as the per-cell style
        key. Two cells with equal keys render under the same replayed run."""
        return (tuple(sorted(self.flags.items())), self.fg, self.bg)

    def apply(self, params: bytes) -> None:
        """Mutate state by one SGR token's param string (the bytes between
        \x1b[ and m). Empty params == reset (\x1b[m). Unrecognized sub-params
        are ignored (defensive: never raise on odd input)."""
        nums = params.split(b';') if params else [b'']
        i = 0
        while i < len(nums):
            raw = nums[i]
            try:
                code = int(raw) if raw != b'' else 0
            except ValueError:
                i += 1
                continue
            if code == 0:
                self.flags.clear(); self.fg = None; self.bg = None
            elif code in _SGR_FLAG_BY_CODE:
                name, on_tok, _ = _SGR_FLAG_BY_CODE[code]
                self.flags[name] = on_tok
            elif code in _SGR_OFF:
                for name in _SGR_OFF[code]:
                    self.flags.pop(name, None)
            elif code == 38 or code == 48:
                # Extended color: 38;5;n / 48;5;n (256) or 38;2;r;g;b (truecolor).
                tok, consumed = self._ext_color_token(nums, i)
                if tok is not None:
                    if code == 38:
                        self.fg = (tok,)
                    else:
                        self.bg = (tok,)
                i += consumed
                continue
            elif code == 39:
                self.fg = None
            elif code == 49:
                self.bg = None
            elif 30 <= code <= 37 or 90 <= code <= 97:
                self.fg = (b'\x1b[' + raw + b'm',)
            elif 40 <= code <= 47 or 100 <= code <= 107:
                self.bg = (b'\x1b[' + raw + b'm',)
            # any other code: no modeled effect (defensive ignore)
            i += 1

    @staticmethod
    def _ext_color_token(nums, i):
        """Reconstruct a faithful single 38/48 color token from nums[i:] and
        report how many params it consumed. Real captures use only single-attr
        tokens (so this round-trips byte-exact); a combined token is rebuilt
        canonically, which still re-themes correctly even if not byte-identical."""
        if i + 1 >= len(nums):
            return None, 1
        try:
            mode = int(nums[i + 1] or b'0')
        except ValueError:
            return None, 1
        if mode == 5 and i + 2 < len(nums):
            tok = b'\x1b[' + nums[i] + b';5;' + nums[i + 2] + b'm'
            return tok, 3
        if mode == 2 and i + 4 < len(nums):
            tok = (b'\x1b[' + nums[i] + b';2;' + nums[i + 2] + b';'
                   + nums[i + 3] + b';' + nums[i + 4] + b'm')
            return tok, 5
        return None, 1

    def replay_from(self, prev: "_SGR", out: bytearray) -> None:
        """Emit into `out` the minimal faithful token sequence to transition the
        terminal from `prev`'s active style to this style. Flags that turn OFF
        emit their exact cancel token (so \x1b[1m...\x1b[22m round-trips); flags
        that turn ON emit their remembered original token; fg/bg changes emit the
        new color or the 39/49 default. Order is deterministic."""
        # Turn OFF flags active in prev but not now.
        for name in _SGR_FLAG_ORDER:
            if name in prev.flags and name not in self.flags:
                # off-token for this flag (bold/dim share 22).
                out += self._off_token(name)
        # Turn ON flags active now but not in prev (or changed token bytes).
        for name in _SGR_FLAG_ORDER:
            if name in self.flags and prev.flags.get(name) != self.flags[name]:
                out += self.flags[name]
        # fg transition.
        if self.fg != prev.fg:
            out += self.fg[0] if self.fg else b'\x1b[39m'
        # bg transition.
        if self.bg != prev.bg:
            out += self.bg[0] if self.bg else b'\x1b[49m'

    def replay_full(self, out: bytearray) -> None:
        """Emit the full active style from a known-clean (reset) baseline. Used
        at the start of each repainted run after an explicit \x1b[0m reset."""
        for name in _SGR_FLAG_ORDER:
            if name in self.flags:
                out += self.flags[name]
        if self.fg:
            out += self.fg[0]
        if self.bg:
            out += self.bg[0]

    def is_default(self) -> bool:
        return not self.flags and self.fg is None and self.bg is None

    @staticmethod
    def _off_token(name: str) -> bytes:
        for code, (n, _on, off) in _SGR_FLAG_BY_CODE.items():
            if n == name:
                return off
        return b''


def _sgr_from_key(key) -> _SGR:
    """Reconstruct an _SGR from a copy_key() snapshot (used by the emitter to
    replay a cell's stored style). The key is (sorted-flag-items, fg, bg)."""
    s = _SGR()
    flags, fg, bg = key
    s.flags = dict(flags)
    s.fg = fg
    s.bg = bg
    return s


class ScreenRepair:
    """Scroll-aware intended-grid re-renderer for claude's clamp-desynced TUI.

    Pure and clockless, exactly like FrameMux: `feed` is a deterministic
    function of (state, bytes) with no I/O and no wall-clock/random dependency,
    so it is fully unit-testable against the captured streams. Time backstops
    stay in the I/O loop.

    THE BUG IT FIXES: claude 2.1.181 renders with relative cursor moves and no
    absolute anchor, walking the cursor PAST screen edges (oversized [40A/[40B,
    [2K][1B] clear loops). Real terminals CLAMP the cursor at the edges; claude's
    internal row model does not, so its row counter desyncs and later content
    lands on the wrong rows. We track claude's INTENDED (clamp-free) grid and
    re-emit it to the real (clamping) terminal via absolute positioning, so
    edge-clamping can no longer desync what the user sees.

    THE CONTRACT (Phase 2 depends only on this): for each captured stream,
        clamp_model( b"".join(feed-chunks) + drain() ).grid()
            == noclamp_model(raw).grid()
    holds under whole-stream, 1-byte, and random chunk boundaries.

    Robustness over correctness (interactive tool): any unparseable span never
    raises and never freezes — it degrades to a safe render. The visible glyph
    count never drops below raw passthrough (a defensive floor).
    """

    def __init__(self, rows: int, cols: int) -> None:
        self.reset(rows, cols)

    def reset(self, rows: int, cols: int) -> None:
        """(Re)initialize for a (possibly new) terminal size. Phase 2 calls this
        from the SIGWINCH path after set_winsize. Clears all pending state so a
        resize mid-stream can never strand a half-parsed token or stale grid."""
        self.H = max(1, rows)
        self.W = max(1, cols)
        # Intent grid: claude's clamp-FREE visible screen. Cursor is tracked
        # clamp-free (the bug is the desync), but writes are clipped to the grid.
        self._g = [[' '] * self.W for _ in range(self.H)]
        # Style plane: per-cell active-SGR snapshot key (parallel to _g). A cell's
        # key is _SGR.copy_key() at write time; blank/erased cells carry the
        # default-style key so the emitter re-themes claude's colors faithfully.
        self._sgr = _SGR()                       # live SGR state, sticky across feeds
        self._default_key = _SGR().copy_key()    # the "no style" key (cached)
        self._sty = [[self._default_key] * self.W for _ in range(self.H)]
        self._r = 0
        self._c = 0
        self._pending = False        # magic-margin wrap (am+xenl): stay, set pending
        self._scrolloff = []         # top lines that scrolled off THIS feed, in order
        self._scrolloff_sty = []     # style rows for the scrolled-off lines, in order
        # Last-emitted viewport snapshot, for diffing. Starts blank: the real
        # terminal is assumed blank-or-whatever; the first feed's diff repaints
        # only the rows that differ from blank, which is correct on a fresh pane
        # and self-corrects on any pane because we use absolute CUP + clear.
        self._prev = [[' '] * self.W for _ in range(self.H)]
        self._prev_sty = [[self._default_key] * self.W for _ in range(self.H)]
        self._hold = b''             # incomplete-token tail held across feeds

    def has_pending(self) -> bool:
        """True while an incomplete-token tail is held (a partial ESC sequence or
        partial UTF-8 char waiting for its continuation bytes). The loop uses this
        to decide whether the idle-timeout backstop needs to drain."""
        return bool(self._hold)

    # --- public stream API -------------------------------------------------

    def feed(self, data: bytes) -> bytes:
        """Advance the intent model over `data` and return corrected bytes that,
        on a clamping terminal, reproduce claude's intended grid. Holds back any
        trailing incomplete token so the model only ever sees complete sequences.
        `feed(b'')` with no held tail is a no-op returning b''."""
        buf = self._hold + data
        complete, self._hold = self._split_incomplete_tail(buf)
        self._scrolloff = []
        self._scrolloff_sty = []
        self._advance(complete)
        return self._emit()

    def drain(self) -> bytes:
        """Flush any held incomplete-token tail (best-effort parse) and emit the
        resulting grid. Called by the loop on idle timeout and at shutdown so a
        partial sequence at end-of-stream still paints. Idempotent once empty."""
        if not self._hold:
            return b''
        tail = self._hold
        self._hold = b''
        self._scrolloff = []
        self._scrolloff_sty = []
        self._advance(tail)
        return self._emit()

    # --- emission ----------------------------------------------------------

    def _emit(self) -> bytes:
        """Re-render the intent viewport to absolute-positioned bytes.

        Two paths:
          * scroll happened this feed → emit each scrolled-off line at the bottom
            row + CRLF (real scroll: pushes the top line into tmux scrollback),
            then a FULL absolute repaint of the viewport. A scroll shifts every
            row, so a per-row diff against the pre-scroll snapshot would be wrong;
            a full repaint re-syncs the clamping terminal to intent deterministically.
          * no scroll → cheap diff: only rows that changed since the last emit are
            repainted (CUP to the row, clear it, rewrite). Steady typing / spinner
            updates stay cheap (a few rows), never a full-screen repaint per byte.
        Either way the emitted bytes use absolute CUP + EL, so edge-clamping in
        the real terminal cannot desync the result.
        """
        out = bytearray()
        if self._scrolloff:
            for line, sty in zip(self._scrolloff, self._scrolloff_sty):
                # Park at the bottom row, clear it, write the scrolled-off line
                # WITH its colors, then CRLF. The CRLF at the bottom is a REAL
                # scroll on the clamping terminal, so this colored line enters
                # its scrollback history exactly as claude intended it.
                out += b'\x1b[%d;1H' % self.H
                out += b'\x1b[2K'
                out += self._render_row(list(line) + [' '] * self.W, sty)
                out += b'\r\n'
            for r in range(self.H):
                row = self._g[r]
                out += b'\x1b[%d;1H' % (r + 1)
                out += b'\x1b[2K'
                out += self._render_row(row, self._sty[r])
                self._prev[r] = list(row)
                self._prev_sty[r] = list(self._sty[r])
        else:
            for r in range(self.H):
                row = self._g[r]
                # Repaint when EITHER the chars OR the style changed since last
                # emit — a pure recolor (same glyphs, new SGR) must still repaint.
                if row != self._prev[r] or self._sty[r] != self._prev_sty[r]:
                    out += b'\x1b[%d;1H' % (r + 1)
                    out += b'\x1b[2K'
                    out += self._render_row(row, self._sty[r])
                    self._prev[r] = list(row)
                    self._prev_sty[r] = list(self._sty[r])
        return bytes(out)

    def _render_row(self, row, sty) -> bytes:
        """Render one row's chars to bytes, re-emitting claude's SGR per styled
        run so colors/attributes match intent EXACTLY. We walk to the last
        non-blank cell (trailing blanks are trimmed, like the old rstrip), and at
        each cell whose style key differs from the run in effect we emit the
        faithful SGR transition (original on-tokens, exact off-tokens) BEFORE the
        char. A leading reset (\x1b[0m) opens every row from a known-clean
        baseline so a colored run on a prior line can't bleed across the CUP, and
        a trailing reset closes any still-active style so it can't leak past the
        row. Default-style rows emit no SGR at all (byte-identical to the old
        monochrome path for uncolored content)."""
        # Find the last non-blank column so trailing blanks are trimmed.
        last = -1
        for c in range(len(row) - 1, -1, -1):
            if row[c] != ' ':
                last = c
                break
        if last < 0:
            return b''                       # fully blank row → nothing to paint
        out = bytearray()
        cur = _SGR()                          # the style currently on the stream
        opened = False                        # have we opened the row baseline yet?
        for c in range(last + 1):
            key = sty[c] if c < len(sty) else self._default_key
            if key != cur.copy_key():
                want = _sgr_from_key(key)
                if not want.is_default() and not opened:
                    # Open the row from a clean baseline (\x1b[0m) before the FIRST
                    # styled run so a colored run on a prior line can't bleed in
                    # across the CUP. cur is already default here.
                    out += b'\x1b[0m'
                    opened = True
                # Emit the faithful transition: precise off-tokens for flags/fg/bg
                # turning OFF (so \x1b[1m..\x1b[22m round-trips for apply_subs) and
                # original on-tokens for those turning ON. Returning to default
                # therefore emits \x1b[22m/\x1b[39m/\x1b[49m as needed — NOT a
                # blanket reset that would break the bold-pair needle.
                want.replay_from(cur, out)
                cur = want
            ch = row[c]
            out += ch.encode('utf-8', 'replace') if ch != ' ' else b' '
        if not cur.is_default():
            out += b'\x1b[0m'                 # close any active style at row end
        return bytes(out)

    # --- incomplete-token holdback -----------------------------------------

    def _split_incomplete_tail(self, buf: bytes):
        """Return (complete_prefix, incomplete_tail). The tail is the longest
        suffix of `buf` that could be the START of an ESC sequence or a partial
        UTF-8 multibyte char split across reads. Holding it back means the intent
        parser only ever sees COMPLETE tokens — so a sequence split across feed
        calls (the 1-byte / random-chunk adversarial cases) parses identically to
        the whole-stream case. Bounded by _SR_MAX_HOLD so a never-terminated ESC
        can't grow the held tail without limit."""
        n = len(buf)
        # 1) Incomplete trailing ESC sequence. Find the last ESC; if the run from
        #    there isn't a complete CSI / OSC / 2-byte ESC, it may still complete
        #    on the next read — hold it (within the per-kind bound). An OSC body
        #    (a hyperlink URL) can be long but legitimate, so it gets the larger
        #    bound; anything else is short, so the small CSI bound applies and a
        #    runaway garbage ESC can't grow the held tail without limit.
        last_esc = buf.rfind(0x1b)
        if last_esc != -1:
            rest = buf[last_esc:]
            if not (self._complete_csi(rest) or _SR_OSC.match(rest)
                    or _SR_ESC1.match(rest)):
                # rest[:2] == b'\x1b]' marks an OSC introducer; bound it widely.
                bound = _SR_MAX_HOLD_OSC if rest[:2] == b'\x1b]' else _SR_MAX_HOLD_CSI
                if (n - last_esc) <= bound:
                    return buf[:last_esc], rest
        # 2) Incomplete trailing UTF-8 multibyte char (≤3 dangling bytes).
        k = 0
        while k < 3 and (n - 1 - k) >= 0:
            b = buf[n - 1 - k]
            if b < 0x80:
                break                       # ASCII byte: nothing partial here
            if b >= 0xc0:                    # a UTF-8 start byte
                need = 1 if b < 0xe0 else 2 if b < 0xf0 else 3
                if k < need:                 # missing continuation bytes → hold
                    return buf[:n - 1 - k], buf[n - 1 - k:]
                break                        # the char is complete
            k += 1                           # a continuation byte; keep walking back
        return buf, b''

    @staticmethod
    def _complete_csi(rest: bytes) -> bool:
        """True if `rest` begins with a COMPLETE CSI (final byte present)."""
        m = _SR_CSI.match(rest)
        return bool(m and m.start() == 0)

    # --- the intent model (independent of the oracle) ----------------------

    def _scroll(self) -> None:
        # Capture the top line (chars + its style row) BEFORE it leaves so it can
        # enter scrollback WITH its color, then scroll: drop row 0, append a blank
        # bottom row in BOTH the char grid and the style plane.
        self._scrolloff.append(''.join(self._g[0]).rstrip())
        self._scrolloff_sty.append(list(self._sty[0]))
        self._g.pop(0)
        self._g.append([' '] * self.W)
        self._sty.pop(0)
        self._sty.append([self._default_key] * self.W)
        # The last-emitted snapshot (chars AND style) must scroll in lockstep so
        # the no-scroll diff in a LATER feed compares against aligned rows.
        self._prev.pop(0)
        self._prev.append([' '] * self.W)
        self._prev_sty.pop(0)
        self._prev_sty.append([self._default_key] * self.W)

    def _lf(self) -> None:
        self._pending = False
        if self._r == self.H - 1:
            self._scroll()
        else:
            self._r += 1

    def _cr(self) -> None:
        self._pending = False
        self._c = 0

    def _putch(self, ch: str) -> None:
        if self._pending:                    # magic-margin wrap deferred from last col
            self._cr()
            self._lf()
        if 0 <= self._r < self.H and 0 <= self._c < self.W:
            self._g[self._r][self._c] = ch   # write clipped to the visible grid
            # Record the SGR in effect at this cell so the emitter re-themes it.
            self._sty[self._r][self._c] = self._sgr.copy_key()
        if self._c == self.W - 1:
            self._pending = True             # at last column: stay, defer the wrap
        else:
            self._c += 1

    def _advance(self, data: bytes) -> None:
        """Drive the intent grid over a span of COMPLETE tokens. Never raises:
        an unrecognized ESC is skipped one byte at a time (defensive), and a
        malformed UTF-8 char decodes to a replacement glyph rather than throwing.
        Cursor moves are modeled CLAMP-FREE (claude's intent); writes are clipped
        to the grid by _putch."""
        i = 0
        n = len(data)
        while i < n:
            b = data[i]
            if b == 0x1b:
                m = _SR_CSI.match(data, i)
                if m and m.start() == i:
                    i = self._apply_csi(m)
                    continue
                m = _SR_OSC.match(data, i)
                if m and m.start() == i:
                    i = m.end()              # OSC (title etc): no grid effect
                    continue
                m = _SR_ESC1.match(data, i)
                if m and m.start() == i:
                    i = m.end()              # 2-byte ESC: no grid effect we model
                    continue
                # Unrecognized/malformed ESC introducer (e.g. \x1b[ with a
                # non-final next byte, or \x1b] with no terminator). Swallow the
                # ESC AND the following byte as one inert unit — exactly what a
                # real terminal does, and what the oracle's \x1b. fallback does.
                # Rendering that next byte ([ , ; , a digit) as literal text
                # would show MORE/other glyphs than the terminal would, breaking
                # the grid alignment. A trailing lone ESC (no next byte) is just
                # skipped.
                i += 2 if i + 1 < n else 1
                continue
            if b == 0x0d:                     # CR
                self._cr()
                i += 1
                continue
            if b == 0x0a:                     # LF
                self._lf()
                i += 1
                continue
            if b == 0x08:                     # BS
                self._c = max(0, self._c - 1)
                i += 1
                continue
            if b < 0x20:                      # other C0 control: ignore for the grid
                i += 1
                continue
            if b < 0x80:                      # ASCII printable
                self._putch(chr(b))
                i += 1
                continue
            # UTF-8 multibyte. The incomplete tail was already held back, so a
            # decode failure here is genuinely malformed input — substitute a
            # replacement glyph (a deliberate, documented swallow) so one bad
            # byte never crashes the live session.
            length = 2 if b < 0xe0 else 3 if b < 0xf0 else 4
            try:
                ch = data[i:i + length].decode('utf-8')
            except UnicodeDecodeError:
                ch = '�'
                length = 1                    # advance one byte; resync on the next
            self._putch(ch)
            i += length

    def _apply_csi(self, m) -> int:
        """Apply one complete CSI to the intent cursor/grid. Private-mode (`?`)
        sequences (cursor-visibility, sync, etc.) have no grid effect and are
        skipped. Unknown finals are no-ops. Returns the index past the match."""
        params = m.group(1)
        fin = m.group(2)
        if params.startswith(b'?'):
            return m.end()                    # private modes: no grid effect
        if fin == b'm':                       # SGR: mutate the live style state.
            self._sgr.apply(params)           # no cursor/grid-position effect
            return m.end()
        nums = [int(x) if x else 0 for x in params.split(b';')] if params else []

        def p(k: int, default: int = 1) -> int:
            # CSI params default to 1 when omitted or zero (per ECMA-48).
            return nums[k] if k < len(nums) and nums[k] != 0 else default

        if fin == b'A':                       # CUU — clamp-FREE (the desync we track)
            self._r = self._r - p(0)
        elif fin == b'B':                     # CUD — clamp-free
            self._r = self._r + p(0)
        elif fin == b'C':                     # CUF
            self._c = self._c + p(0)
            self._pending = False
        elif fin == b'D':                     # CUB
            self._c = self._c - p(0)
            self._pending = False
        elif fin == b'G':                     # CHA — absolute column
            self._c = p(0) - 1
            self._pending = False
        elif fin == b'H' or fin == b'f':      # CUP — absolute row;col
            self._r = p(0) - 1
            self._c = p(1) - 1
            self._pending = False
        elif fin == b'd':                     # VPA — absolute row
            self._r = p(0) - 1
        elif fin == b'K':                     # EL — erase in line (0/1/2)
            self._erase_line(nums[0] if nums else 0)
        elif fin == b'J':                     # ED — erase display (only 2 modeled)
            if (nums[0] if nums else 0) == 2:
                self._g = [[' '] * self.W for _ in range(self.H)]
                self._sty = [[self._default_key] * self.W for _ in range(self.H)]
        # SGR (m) is handled above (mutates the style plane). DSR (n) and any
        # other final: no grid-position effect here.
        return m.end()

    def _erase_line(self, mode: int) -> None:
        """EL: clear to-end (0), to-start (1), or whole line (2). A no-op when the
        cursor row is off-screen (claude walks it off during the desync) — the bug
        is that those erases hit the wrong row on a clamping terminal; modeling
        them clamp-free + clipping the write is exactly the repair."""
        if not (0 <= self._r < self.H):
            return
        row = self._g[self._r]
        sty = self._sty[self._r]
        dk = self._default_key
        if mode == 0:
            for c in range(max(0, self._c), self.W):
                row[c] = ' '; sty[c] = dk
        elif mode == 1:
            for c in range(0, min(self.W, self._c + 1)):
                row[c] = ' '; sty[c] = dk
        else:
            for c in range(self.W):
                row[c] = ' '; sty[c] = dk

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
