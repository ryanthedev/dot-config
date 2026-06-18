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

# === VT500 parser state machine (Phase 2: insulation layer) ================
#
# A pure, table-driven implementation of the Paul Williams DEC ANSI / VT500
# parser (vt100.net/emu/dec_ansi_parser). The state machine classifies EVERY
# byte, so a control sequence can NEVER leak to the terminal as a printable
# glyph — the exact regression the prior ad-hoc-regex parser shipped
# (`\x1b[>1u` rendered as text). Each emitted event carries the RAW bytes that
# produced it; concatenating every event's `.raw` (feed + drain) reconstructs
# the input EXACTLY (losslessness), which Phase 3's control-plane forwarding
# depends on.
#
# Pure and clockless: `feed(bytes) -> list[Event]` / `drain() -> list[Event]`
# are a deterministic function of (parser state, input). No I/O, no time, no
# screen semantics, no forwarding decisions — those belong to Phase 3.

# Cap on bytes held mid-sequence. A hostile or buggy stream can open an OSC/DCS
# (or a pathologically long CSI) and never terminate it; without a cap the hold
# buffer would grow unbounded. On overflow we flush the held bytes as an inert
# event and reset to GROUND — losslessness is preserved (the flushed event
# still carries the raw bytes), memory is not.
MAX_VT500_HOLD = 1 << 16

_REPLACEMENT = "�"  # U+FFFD, emitted for malformed/truncated UTF-8


class Event:
    """Base for parser events. Equality and repr are by (type, raw) so the
    chunk-invariance test can compare event streams directly."""
    __slots__ = ("raw",)

    def __init__(self, raw: bytes):
        self.raw = raw

    def __eq__(self, other):
        return type(self) is type(other) and self.__dict__like() == other.__dict__like()

    def __dict__like(self):
        return tuple(getattr(self, s) for s in self._fields())

    def _fields(self):
        return ("raw",)

    def __hash__(self):
        return hash((type(self).__name__,) + self.__dict__like())

    def __repr__(self):
        body = ", ".join("%s=%r" % (s, getattr(self, s)) for s in self._fields())
        return "%s(%s)" % (type(self).__name__, body)


class Print(Event):
    """One or more printable characters (a decoded UTF-8 run)."""
    __slots__ = ("text",)

    def __init__(self, text: str, raw: bytes):
        super().__init__(raw)
        self.text = text

    def _fields(self):
        return ("text", "raw")


class Execute(Event):
    """A C0/C1 control byte to execute (e.g. LF, CR, BS, HT, BEL)."""
    __slots__ = ("byte",)

    def __init__(self, byte: int, raw: bytes):
        super().__init__(raw)
        self.byte = byte

    def _fields(self):
        return ("byte", "raw")


class EscDispatch(Event):
    """A non-CSI escape sequence: ESC <intermediates> <final>."""
    __slots__ = ("intermediates", "final")

    def __init__(self, intermediates: bytes, final: int, raw: bytes):
        super().__init__(raw)
        self.intermediates = intermediates
        self.final = final

    def _fields(self):
        return ("intermediates", "final", "raw")


class CsiDispatch(Event):
    """A CSI sequence: ESC [ <private> <params> <intermediates> <final>."""
    __slots__ = ("private", "params", "intermediates", "final")

    def __init__(self, private: bytes, params: bytes, intermediates: bytes,
                 final: int, raw: bytes):
        super().__init__(raw)
        self.private = private
        self.params = params
        self.intermediates = intermediates
        self.final = final

    def _fields(self):
        return ("private", "params", "intermediates", "final", "raw")


class Osc(Event):
    """An OSC string (ESC ] ... BEL|ST). `payload` is the bytes between the
    introducer and the terminator; `raw` is the whole sequence incl. terminator."""
    __slots__ = ("payload",)

    def __init__(self, payload: bytes, raw: bytes):
        super().__init__(raw)
        self.payload = payload

    def _fields(self):
        return ("payload", "raw")


class Dcs(Event):
    """A DCS string (ESC P ... ST). Inert here; carries raw for forwarding."""


class Sos(Event):
    """A SOS string (ESC X ... ST)."""


class Pm(Event):
    """A PM string (ESC ^ ... ST)."""


class Apc(Event):
    """An APC string (ESC _ ... ST)."""


# Byte-class helpers (Williams tables are expressed over these ranges).
def _is_intermediate(b: int) -> bool:
    return 0x20 <= b <= 0x2f  # SP ! " # $ % & ' ( ) * + , - . /


def _is_param(b: int) -> bool:
    return 0x30 <= b <= 0x3b  # 0-9 : ;


def _is_csi_private(b: int) -> bool:
    return 0x3c <= b <= 0x3f  # < = > ?


def _is_final(b: int) -> bool:
    return 0x40 <= b <= 0x7e  # @ ... ~


def _is_c0_execute(b: int) -> bool:
    # C0 controls passed through 'execute' in most states. ESC/CAN/SUB are
    # handled before this as transitions; 0x7f (DEL) is ignored, not executed.
    return b <= 0x1f and b not in (0x18, 0x1a, 0x1b)


class VT500Parser:
    """Williams DEC ANSI parser. `feed` returns the events fully resolved by the
    bytes seen so far, HOLDING any incomplete trailing sequence or UTF-8
    codepoint for the next feed; `drain` flushes whatever is still held.

    No-leak guarantee: a byte is classified as printable ONLY in the GROUND
    state via the UTF-8 decoder. Every escape-introduced sequence is consumed by
    a non-GROUND state and emitted as a typed control event, never as Print.
    """

    # State constants.
    _GROUND = 0
    _ESCAPE = 1
    _ESCAPE_INTERMEDIATE = 2
    _CSI_ENTRY = 3
    _CSI_PARAM = 4
    _CSI_INTERMEDIATE = 5
    _CSI_IGNORE = 6
    _OSC_STRING = 7
    _DCS_ENTRY = 8
    _DCS_PARAM = 9
    _DCS_INTERMEDIATE = 10
    _DCS_PASSTHROUGH = 11
    _DCS_IGNORE = 12
    _SOS_PM_APC_STRING = 13

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        """Return to a pristine GROUND state, dropping any in-flight sequence and
        UTF-8 tail. Phase 4 will call this on resize; safe to call any time."""
        self._state = self._GROUND
        self._seq = b""          # raw bytes of the in-flight control sequence
        self._private = b""
        self._params = b""
        self._intermediates = b""
        self._osc_payload = b""
        self._utf8_buf = b""     # raw bytes of an incomplete trailing codepoint
        self._string_kind = None  # which of SOS/PM/APC we are inside
        self._str_cont = 0       # UTF-8 continuation bytes still expected in a
        #                          string control (OSC/DCS/...). claude emits
        #                          UTF-8 titles/labels inside OSC; a 0x9c that is
        #                          a UTF-8 continuation byte must NOT be mistaken
        #                          for the 8-bit ST terminator (the leak that put
        #                          an OSC title's tail into the grid as text).

    # -- public API ---------------------------------------------------------
    def feed(self, data: bytes) -> list:
        """Consume `data`; return events resolved so far. Incomplete trailing
        sequence/codepoint is held for the next feed. Never raises on any bytes."""
        out: list = []
        for b in data:
            self._step(b, out)
        return out

    def has_pending(self) -> bool:
        """True while the parser is holding an incomplete trailing token — a
        partial control sequence (non-GROUND state / collected bytes) or a
        partial UTF-8 codepoint. The Insulator/I-O loop uses this to decide
        whether the idle-timeout backstop must drain a stuck partial sequence."""
        return bool(self._seq) or bool(self._utf8_buf) or self._state != self._GROUND

    def drain(self) -> list:
        """Flush any held sequence/codepoint as terminal events. After drain the
        held state is empty so feed+drain raw bytes reconstruct the full input."""
        out: list = []
        # Flush an incomplete trailing UTF-8 codepoint: each held byte is
        # un-decodable on its own, so emit one replacement char but carry the
        # exact raw bytes (losslessness). Then clear.
        self._flush_utf8_tail(out)
        # Flush an unterminated control sequence as the right inert event type so
        # its raw bytes are not lost. OSC/strings/DCS/CSI that never terminated
        # still carry their bytes forward.
        if self._seq:
            self._emit_unterminated(out)
        self._reset_seq()
        self._state = self._GROUND
        return out

    # -- helpers ------------------------------------------------------------
    def _flush_utf8_tail(self, out: list) -> None:
        """Emit a held, incomplete UTF-8 codepoint as one replacement char,
        carrying its exact raw bytes so reconstruction stays byte-exact."""
        if self._utf8_buf:
            out.append(Print(_REPLACEMENT, self._utf8_buf))
            self._utf8_buf = b""

    def _reset_seq(self) -> None:
        self._seq = b""
        self._private = b""
        self._params = b""
        self._intermediates = b""
        self._osc_payload = b""
        self._string_kind = None
        self._str_cont = 0

    @staticmethod
    def _utf8_len(b: int) -> int:
        """UTF-8 continuation-byte count expected AFTER lead byte `b` (0 if `b`
        is not a lead byte)."""
        if 0xc0 <= b <= 0xdf:
            return 1
        if 0xe0 <= b <= 0xef:
            return 2
        if 0xf0 <= b <= 0xf7:
            return 3
        return 0

    def _str_is_8bit_st(self, b: int) -> bool:
        """True iff byte `b` should terminate the current string control as an
        8-bit ST (0x9c). It is NOT a terminator when it is a UTF-8 continuation
        byte of a multibyte codepoint inside the string body — claude's OSC
        titles carry UTF-8 (e.g. ✳ = \\xe2\\x9c\\xb3, whose \\x9c byte must not be
        read as ST). Tracks remaining continuation bytes as the body is
        collected (see `_str_collect_utf8`)."""
        return b == 0x9c and self._str_cont == 0

    def _str_collect_utf8(self, b: int) -> None:
        """Advance the in-string UTF-8 continuation tracker for one body byte."""
        if self._str_cont > 0:
            self._str_cont -= 1
        else:
            self._str_cont = self._utf8_len(b)

    def _emit_unterminated(self, out: list) -> None:
        """Emit the held, never-terminated sequence as its inert event type."""
        raw = self._seq
        st = self._state
        if st in (self._OSC_STRING,):
            out.append(Osc(self._osc_payload, raw))
        elif st in (self._DCS_ENTRY, self._DCS_PARAM, self._DCS_INTERMEDIATE,
                    self._DCS_PASSTHROUGH, self._DCS_IGNORE):
            out.append(Dcs(raw))
        elif st == self._SOS_PM_APC_STRING:
            out.append({"sos": Sos, "pm": Pm, "apc": Apc, "esck": Pm}.get(
                self._string_kind, Sos)(raw))
        else:
            # An incomplete ESC/CSI: no dispatch happened, but the bytes are
            # real — surface them as an EscDispatch-shaped inert event with no
            # final so nothing is lost and nothing is mistaken for Print.
            out.append(EscDispatch(self._intermediates, -1, raw))

    def _overflow(self) -> bool:
        return len(self._seq) > MAX_VT500_HOLD

    # -- UTF-8 (GROUND printable) ------------------------------------------
    def _ground_byte(self, b: int, out: list) -> None:
        """Decode one GROUND printable/continuation byte, accumulating multibyte
        codepoints across calls. External, untrusted input: validate, never
        raise. Every byte routed here is preserved in some emitted event's raw,
        so the GROUND path is lossless by construction.

        On a malformed sequence we follow the Unicode "maximal subpart"
        substitution rule's *spirit*: emit ONE replacement char for the bytes
        already held that cannot start/continue a valid codepoint, then RE-feed
        the current byte fresh (it may legitimately begin a new codepoint, e.g.
        a stray lead byte followed by a normal ASCII letter)."""
        buf = self._utf8_buf + bytes([b])
        try:
            text = buf.decode("utf-8")
        except UnicodeDecodeError as e:
            if e.start > 0:
                # A complete codepoint precedes a fresh (in)complete tail: emit
                # the good prefix, then re-evaluate the remainder byte by byte.
                good = buf[:e.start]
                out.append(Print(good.decode("utf-8"), good))
                self._utf8_buf = b""
                for rb in buf[e.start:]:
                    self._ground_byte(rb, out)
                return
            if e.reason == "unexpected end of data":
                # A still-valid prefix of a multibyte codepoint: hold for the
                # next feed. Bounded by max UTF-8 length, so it cannot grow.
                self._utf8_buf = buf
                return
            # Invalid from the first byte. If we were already holding lead bytes,
            # THOSE are the bad bytes: replace them and re-feed the current byte
            # fresh (it might start a valid codepoint). If nothing was held, the
            # current byte itself is the lone invalid byte.
            if self._utf8_buf:
                bad = self._utf8_buf
                self._utf8_buf = b""
                out.append(Print(_REPLACEMENT, bad))
                self._ground_byte(b, out)
            else:
                out.append(Print(_REPLACEMENT, bytes([b])))
            return
        # Decoded cleanly to one or more chars.
        self._utf8_buf = b""
        out.append(Print(text, buf))

    # -- core dispatch ------------------------------------------------------
    def _step(self, b: int, out: list) -> None:
        # --- "anywhere" transitions (Williams): these fire from any state. ---
        # A pending UTF-8 tail can never complete once a control byte arrives;
        # flush it FIRST so its bytes keep their stream position (losslessness).
        if b in (0x18, 0x1a):  # CAN / SUB: abort the current sequence to ground
            self._flush_utf8_tail(out)
            self._abort_to_ground(out)
            out.append(Execute(b, bytes([b])))
            return
        if b == 0x1b:  # ESC: abort current, begin a new escape sequence
            self._flush_utf8_tail(out)
            self._abort_to_ground(out)
            self._seq = bytes([b])
            self._state = self._ESCAPE
            return
        # 8-bit C1 introducers (high-bit controls) when not mid-UTF-8. Inside a
        # GROUND multibyte tail these byte values are continuation bytes, so only
        # treat them as introducers when no UTF-8 tail is pending.
        if self._state == self._GROUND and not self._utf8_buf:
            c1 = self._c1_introducer(b)
            if c1 is not None:
                self._seq = bytes([b])
                self._state = c1
                if c1 == self._OSC_STRING:
                    self._osc_payload = b""
                return

        handler = self._DISPATCH[self._state]
        handler(self, b, out)

    def _c1_introducer(self, b: int):
        """Map an 8-bit C1 introducer byte to its state, or None."""
        if b == 0x9b:  # CSI
            return self._CSI_ENTRY
        if b == 0x9d:  # OSC
            return self._OSC_STRING
        if b == 0x90:  # DCS
            return self._DCS_ENTRY
        if b == 0x98:  # SOS
            self._string_kind = "sos"
            return self._SOS_PM_APC_STRING
        if b == 0x9e:  # PM
            self._string_kind = "pm"
            return self._SOS_PM_APC_STRING
        if b == 0x9f:  # APC
            self._string_kind = "apc"
            return self._SOS_PM_APC_STRING
        return None

    def _abort_to_ground(self, out: list) -> None:
        """ESC/CAN/SUB arrived mid-sequence: the in-flight bytes are real and
        must not be lost. Emit them as their inert type, then reset to GROUND.
        Does NOT touch the UTF-8 tail (a pending codepoint is unrelated)."""
        if self._seq:
            self._emit_unterminated(out)
        self._reset_seq()
        self._state = self._GROUND

    # -- per-state handlers -------------------------------------------------
    def _st_ground(self, b: int, out: list) -> None:
        if _is_c0_execute(b):
            self._ground_byte_flush(out)
            out.append(Execute(b, bytes([b])))
            return
        if b == 0x7f:  # DEL: ignored in ground (per Williams) but lossless-kept
            self._ground_byte_flush(out)
            out.append(Execute(b, bytes([b])))
            return
        self._ground_byte(b, out)

    def _ground_byte_flush(self, out: list) -> None:
        """A C0 control interrupts a printable run; a pending UTF-8 tail can't
        complete, so flush it as a replacement (lossless) before the control."""
        self._flush_utf8_tail(out)

    def _collect_seq(self, b: int, out: list) -> bool:
        """Append b to the in-flight raw sequence; on overflow flush and reset.
        Returns True if the caller should keep processing b, False if aborted."""
        self._seq += bytes([b])
        if self._overflow():
            self._emit_unterminated(out)
            self._reset_seq()
            self._state = self._GROUND
            return False
        return True

    def _st_escape(self, b: int, out: list) -> None:
        if not self._collect_seq(b, out):
            return
        if _is_intermediate(b):
            self._intermediates += bytes([b])
            self._state = self._ESCAPE_INTERMEDIATE
            return
        if b == 0x5b:  # '[' -> CSI
            self._state = self._CSI_ENTRY
            return
        if b == 0x5d:  # ']' -> OSC
            self._osc_payload = b""
            self._state = self._OSC_STRING
            return
        if b == 0x50:  # 'P' -> DCS
            self._state = self._DCS_ENTRY
            return
        if b == 0x58:  # 'X' -> SOS
            self._string_kind = "sos"
            self._state = self._SOS_PM_APC_STRING
            return
        if b == 0x5e:  # '^' -> PM
            self._string_kind = "pm"
            self._state = self._SOS_PM_APC_STRING
            return
        if b == 0x5f:  # '_' -> APC
            self._string_kind = "apc"
            self._state = self._SOS_PM_APC_STRING
            return
        if b == 0x6b:  # 'k' -> screen/tmux window-title string (ESC k ... ST).
            # NOT standard VT500, but the wrapper runs under tmux, which (like
            # GNU screen) consumes ESC k <title> ST as the window name. Treating
            # it as a 2-byte ESC dispatch would PRINT the title body as text (the
            # leak that put "/tmp" / agent labels into the grid). It terminates
            # on ST ONLY (a BEL inside the title is data) — modeled by the
            # SOS/PM/APC string state, which terminates on ST. Emitted inert
            # (kind "esck") and forwarded verbatim by the Router.
            self._string_kind = "esck"
            self._state = self._SOS_PM_APC_STRING
            return
        if 0x30 <= b <= 0x7e:  # final byte -> esc_dispatch
            out.append(EscDispatch(self._intermediates, b, self._seq))
            self._reset_seq()
            self._state = self._GROUND
            return
        # 0x20..0x2f handled above; anything else (0x7f) is ignored but kept.

    def _st_escape_intermediate(self, b: int, out: list) -> None:
        if not self._collect_seq(b, out):
            return
        if _is_intermediate(b):
            self._intermediates += bytes([b])
            return
        if 0x30 <= b <= 0x7e:
            out.append(EscDispatch(self._intermediates, b, self._seq))
            self._reset_seq()
            self._state = self._GROUND
            return

    def _st_csi_entry(self, b: int, out: list) -> None:
        if not self._collect_seq(b, out):
            return
        if _is_csi_private(b):
            self._private += bytes([b])
            self._state = self._CSI_PARAM
            return
        if _is_param(b):
            self._params += bytes([b])
            self._state = self._CSI_PARAM
            return
        if _is_intermediate(b):
            self._intermediates += bytes([b])
            self._state = self._CSI_INTERMEDIATE
            return
        if _is_final(b):
            self._csi_dispatch(b, out)
            return

    def _st_csi_param(self, b: int, out: list) -> None:
        if not self._collect_seq(b, out):
            return
        if _is_param(b):
            self._params += bytes([b])
            return
        if _is_csi_private(b):
            # Private marker after params is illegal -> ignore the rest.
            self._state = self._CSI_IGNORE
            return
        if _is_intermediate(b):
            self._intermediates += bytes([b])
            self._state = self._CSI_INTERMEDIATE
            return
        if _is_final(b):
            self._csi_dispatch(b, out)
            return

    def _st_csi_intermediate(self, b: int, out: list) -> None:
        if not self._collect_seq(b, out):
            return
        if _is_intermediate(b):
            self._intermediates += bytes([b])
            return
        if _is_param(b) or _is_csi_private(b):
            # param/private after an intermediate is illegal -> ignore.
            self._state = self._CSI_IGNORE
            return
        if _is_final(b):
            self._csi_dispatch(b, out)
            return

    def _st_csi_ignore(self, b: int, out: list) -> None:
        if not self._collect_seq(b, out):
            return
        if _is_final(b):
            # A malformed CSI: consume through the final but emit NO dispatch.
            # The bytes are surfaced as an inert CsiDispatch with final=-1 so
            # nothing is lost and nothing leaks as Print.
            out.append(CsiDispatch(self._private, self._params,
                                   self._intermediates, -1, self._seq))
            self._reset_seq()
            self._state = self._GROUND
            return

    def _csi_dispatch(self, b: int, out: list) -> None:
        out.append(CsiDispatch(self._private, self._params,
                               self._intermediates, b, self._seq))
        self._reset_seq()
        self._state = self._GROUND

    def _st_osc_string(self, b: int, out: list) -> None:
        # OSC terminates on BEL (0x07) or 8-bit ST (0x9c). The 7-bit ST form
        # (ESC \) terminates via the anywhere ESC-transition: the ESC aborts the
        # OSC (emitting it as an Osc event for the bytes so far) and the trailing
        # '\' becomes an EscDispatch — both typed control events, never Print, so
        # the OSC introducer can never leak. Losslessness holds across the split.
        if b == 0x07 or self._str_is_8bit_st(b):
            self._seq += bytes([b])
            out.append(Osc(self._osc_payload, self._seq))
            self._reset_seq()
            self._state = self._GROUND
            return
        if not self._collect_seq(b, out):
            return
        self._str_collect_utf8(b)
        self._osc_payload += bytes([b])

    def _st_dcs_entry(self, b: int, out: list) -> None:
        if not self._collect_seq(b, out):
            return
        if _is_csi_private(b):
            self._private += bytes([b])
            self._state = self._DCS_PARAM
            return
        if _is_param(b):
            self._params += bytes([b])
            self._state = self._DCS_PARAM
            return
        if _is_intermediate(b):
            self._intermediates += bytes([b])
            self._state = self._DCS_INTERMEDIATE
            return
        if _is_final(b):
            self._state = self._DCS_PASSTHROUGH
            return

    def _st_dcs_param(self, b: int, out: list) -> None:
        if not self._collect_seq(b, out):
            return
        if _is_param(b):
            self._params += bytes([b])
            return
        if _is_csi_private(b):
            self._state = self._DCS_IGNORE
            return
        if _is_intermediate(b):
            self._intermediates += bytes([b])
            self._state = self._DCS_INTERMEDIATE
            return
        if _is_final(b):
            self._state = self._DCS_PASSTHROUGH
            return

    def _st_dcs_intermediate(self, b: int, out: list) -> None:
        if not self._collect_seq(b, out):
            return
        if _is_intermediate(b):
            self._intermediates += bytes([b])
            return
        if _is_param(b) or _is_csi_private(b):
            self._state = self._DCS_IGNORE
            return
        if _is_final(b):
            self._state = self._DCS_PASSTHROUGH
            return

    def _st_dcs_passthrough(self, b: int, out: list) -> None:
        # Body bytes pass through until ST. The 7-bit ST (ESC \) is routed by the
        # anywhere ESC-transition (which flushes this DCS as a Dcs event); an
        # 8-bit ST (0x9c) terminates here directly — unless it is a UTF-8
        # continuation byte of a multibyte char in the body (then it is data).
        if self._str_is_8bit_st(b):
            self._seq += bytes([b])
            out.append(Dcs(self._seq))
            self._reset_seq()
            self._state = self._GROUND
            return
        if self._collect_seq(b, out):
            self._str_collect_utf8(b)

    def _st_dcs_ignore(self, b: int, out: list) -> None:
        if self._str_is_8bit_st(b):
            self._seq += bytes([b])
            out.append(Dcs(self._seq))
            self._reset_seq()
            self._state = self._GROUND
            return
        if self._collect_seq(b, out):
            self._str_collect_utf8(b)

    def _st_sos_pm_apc_string(self, b: int, out: list) -> None:
        cls = {"sos": Sos, "pm": Pm, "apc": Apc, "esck": Pm}.get(
            self._string_kind, Sos)
        if self._str_is_8bit_st(b):  # 8-bit ST (not a UTF-8 continuation byte)
            self._seq += bytes([b])
            out.append(cls(self._seq))
            self._reset_seq()
            self._state = self._GROUND
            return
        if self._collect_seq(b, out):
            self._str_collect_utf8(b)

    # State -> handler dispatch table (built after methods are defined).
    _DISPATCH = {}


# Populate the dispatch table now that the methods exist.
VT500Parser._DISPATCH = {
    VT500Parser._GROUND: VT500Parser._st_ground,
    VT500Parser._ESCAPE: VT500Parser._st_escape,
    VT500Parser._ESCAPE_INTERMEDIATE: VT500Parser._st_escape_intermediate,
    VT500Parser._CSI_ENTRY: VT500Parser._st_csi_entry,
    VT500Parser._CSI_PARAM: VT500Parser._st_csi_param,
    VT500Parser._CSI_INTERMEDIATE: VT500Parser._st_csi_intermediate,
    VT500Parser._CSI_IGNORE: VT500Parser._st_csi_ignore,
    VT500Parser._OSC_STRING: VT500Parser._st_osc_string,
    VT500Parser._DCS_ENTRY: VT500Parser._st_dcs_entry,
    VT500Parser._DCS_PARAM: VT500Parser._st_dcs_param,
    VT500Parser._DCS_INTERMEDIATE: VT500Parser._st_dcs_intermediate,
    VT500Parser._DCS_PASSTHROUGH: VT500Parser._st_dcs_passthrough,
    VT500Parser._DCS_IGNORE: VT500Parser._st_dcs_ignore,
    VT500Parser._SOS_PM_APC_STRING: VT500Parser._st_sos_pm_apc_string,
}

# === end VT500 parser ======================================================


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

    def replay_to_default(self, out: bytearray) -> None:
        """Emit the PRECISE per-attribute off-tokens that return `self`'s active
        style to default — \x1b[22m/\x1b[23m/.../\x1b[39m/\x1b[49m as needed —
        rather than a blanket \x1b[0m reset. Closing a row this way matters when a
        themed bold word (Bash/Skill) is the LITERAL last styled glyph on a row:
        \x1b[1mBash\x1b[22m must round-trip so the downstream apply_subs needle
        still matches; a trailing \x1b[0m would strand the \x1b[1m unpaired and
        break the needle. Equivalent to transitioning from `self` to a fresh
        default _SGR (reusing replay_from), so the off-token set stays correct
        and deterministic without duplicating the cancel logic."""
        _SGR().replay_from(self, out)

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
            # Close any still-active style at row end with PRECISE per-attribute
            # off-tokens (\x1b[22m/\x1b[39m/...), NOT a blanket \x1b[0m. If a
            # themed bold word (Bash/Skill) is the literal last styled glyph on
            # the row, \x1b[1mBash\x1b[22m must stay paired so the downstream
            # apply_subs needle still matches; a trailing \x1b[0m would strand
            # the \x1b[1m and break the needle.
            cur.replay_to_default(out)
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


# === Insulator engine (Phase 3) ============================================
#
# The insulation layer proper. It supersedes ScreenRepair's two fatal flaws by
# construction:
#
#   1. ScreenRepair parsed the stream with ad-hoc regex, so a sequence outside
#      its regex vocabulary (e.g. \x1b[>1u) LEAKED to the terminal as glyphs.
#      The Insulator instead drives a canonical VT500Parser, whose state machine
#      classifies EVERY byte — a control sequence can never be mistaken for text.
#
#   2. ScreenRepair DROPPED claude's entire non-grid control plane (cursor
#      visibility, bracketed paste, kitty keyboard, mouse, OSC, and the DA/DSR
#      queries claude waits on). The Insulator's Router FORWARDS the control
#      plane VERBATIM, at its correct stream position, so behavior is preserved.
#
# Pipeline per chunk:
#   bytes -> VT500Parser -> [events] -> Router{ GRID -> _Screen (clamp-free) |
#            CONTROL -> forward event.raw verbatim } ; on each control event the
#            Emitter first diff-renders the Screen mutated so far (painting prior
#            visible state), then the control raw is appended, then rendering
#            continues -> a forwarded query lands BETWEEN the cells before and
#            after it, not deferred past the flush (the ORDERING gate, DW-3.3).
#
# Pure and clockless: feed/drain are a deterministic function of (state, bytes).
# Defensive: feed never raises on any input (the caller's barricade, Phase 4,
# falls back to passthrough on any escaped exception, but feed itself must not
# escalate malformed input into a crash).

# CSI finals the Router treats as GRID operations (cursor motion / erase / SGR).
# This set is INTENTIONALLY EXACTLY the subset the intent oracle (vtmodel, which
# minted the frozen correction intent) models — A/B/C/D/G/H/f/d/K/J/m — so the
# re-rendered grid equals the frozen intent byte-for-byte (the DW-3.2 gate).
# Everything else (DECSTBM r, save/restore s/u, scroll-region motion, CUE/CUF1
# E/F, HPA `, ESC 7/8) is routed CONTROL and FORWARDED verbatim rather than
# dropped: those reach the real terminal, but the emitter's absolute-CUP repaint
# owns final positioning, so forwarding them is grid-inert in the output while
# still preserving the control plane (the improvement over ScreenRepair, which
# dropped them). Honoring them in the Screen would desync from claude's intent
# exactly the way the clamp does, which is the corruption we exist to absorb.
_INSU_GRID_FINALS = frozenset(b"ABCDGHfdKJm")
# CSI finals that are device QUERIES — CONTROL even though they carry no private
# marker (DA primary \x1b[c, DSR \x1b[6n). Dropping these hangs claude.
_INSU_QUERY_FINALS = frozenset(b"cn")
# Private-mode params that ENTER the alternate screen buffer. When seen, the
# Insulator steps aside (forwards everything verbatim) until the matching exit,
# since claude's alt-screen — if it ever uses one — is full-screen app output
# that should not be re-rendered through the intent grid.
_INSU_ALT_ENTER = frozenset((b"?1049", b"?47", b"?1047"))
_INSU_ALT_EXIT = frozenset((b"?1049", b"?47", b"?1047"))


class _Screen:
    """Clamp-free authoritative screen, driven by VT500Parser EVENTS.

    Same intent model as ScreenRepair (clamp-free cursor; grid + per-cell SGR
    plane; scroll + scrollback capture; CR/LF/BS; CUU..CUP/VPA/CHA; EL/ED; SGR;
    DECSC/DECRC) — but every mutation is applied from a typed Event whose params
    were already parsed by the canonical state machine, so no byte is ever
    re-parsed (and thus no byte can leak). Writes are clipped to the visible
    grid; the cursor is tracked clamp-free (recovering claude's INTENT — the
    desync the insulator exists to absorb).

    This is a containment helper of Insulator, not a public class.
    """

    __slots__ = ("H", "W", "_g", "_sgr", "_default_key", "_sty", "_r", "_c",
                 "_pending", "_scrolloff", "_scrolloff_sty")

    def __init__(self, rows: int, cols: int) -> None:
        self.reset(rows, cols)

    def reset(self, rows: int, cols: int) -> None:
        self.H = max(1, rows)
        self.W = max(1, cols)
        self._g = [[' '] * self.W for _ in range(self.H)]
        self._sgr = _SGR()
        self._default_key = _SGR().copy_key()
        self._sty = [[self._default_key] * self.W for _ in range(self.H)]
        self._r = 0
        self._c = 0
        self._pending = False
        self._scrolloff = []
        self._scrolloff_sty = []

    def take_scrolloff(self):
        """Return (lines, styles) that scrolled off since the last call, then
        clear them. The Emitter consumes these to push real scroll history."""
        lines, styles = self._scrolloff, self._scrolloff_sty
        self._scrolloff, self._scrolloff_sty = [], []
        return lines, styles

    # -- grid primitives (mirrors ScreenRepair, event-fed) -----------------
    def _scroll(self) -> None:
        self._scrolloff.append(''.join(self._g[0]).rstrip())
        self._scrolloff_sty.append(list(self._sty[0]))
        self._g.pop(0)
        self._g.append([' '] * self.W)
        self._sty.pop(0)
        self._sty.append([self._default_key] * self.W)

    def _lf(self) -> None:
        # Match ScreenRepair exactly: a bottom-row LF scrolls; any other LF
        # advances the (clamp-free) virtual row counter. This is the intent
        # model the frozen agenttree intent was minted against.
        self._pending = False
        if self._r == self.H - 1:
            self._scroll()
        else:
            self._r += 1

    def _cr(self) -> None:
        self._pending = False
        self._c = 0

    def _bs(self) -> None:
        self._pending = False
        self._c = max(0, self._c - 1)

    def _putch(self, ch: str) -> None:
        if self._pending:
            self._cr()
            self._lf()
        if 0 <= self._r < self.H and 0 <= self._c < self.W:
            self._g[self._r][self._c] = ch
            self._sty[self._r][self._c] = self._sgr.copy_key()
        if self._c == self.W - 1:
            self._pending = True
        else:
            self._c += 1

    def ri(self) -> None:
        """RI (ESC M) — reverse index: move the cursor UP one row, clamp-free.
        A real terminal scrolls DOWN if at the top margin; claude only uses RI to
        step back up after an LF (the startup '/tmp' line), and the emitter owns
        absolute positioning, so a plain clamp-free decrement is the faithful
        intent without injecting a real-terminal scroll."""
        self._pending = False
        self._r -= 1

    def ind(self) -> None:
        """IND (ESC D) — index: move the cursor DOWN one row (LF semantics)."""
        self._lf()

    def nel(self) -> None:
        """NEL (ESC E) — next line: CR + LF."""
        self._cr()
        self._lf()

    def print(self, text: str) -> None:
        for ch in text:
            self._putch(ch)

    def execute(self, byte: int) -> None:
        if byte == 0x0d:
            self._cr()
        elif byte == 0x0a:
            self._lf()
        elif byte == 0x08:
            self._bs()
        elif byte == 0x09:                  # HT: advance to next 8-col tab stop
            self._pending = False
            nxt = (self._c // 8 + 1) * 8
            self._c = min(nxt, self.W - 1)
        # other C0 (BEL etc.): no grid effect

    def csi(self, private: bytes, params: bytes, final: int) -> None:
        """Apply one GRID CsiDispatch. The Router only routes the intent-model
        subset here (A/B/C/D/G/H/f/d/K/J/m); params were already validated by the
        parser, but we still parse defensively (never raise on odd values). The
        cursor is moved CLAMP-FREE — that is the desync the insulator recovers."""
        fin = chr(final).encode()
        if fin == b'm':                                 # SGR
            self._sgr.apply(params)
            return
        nums = []
        for x in params.split(b';'):
            try:
                nums.append(int(x) if x else 0)
            except ValueError:
                nums.append(0)

        def p(k: int, default: int = 1) -> int:
            return nums[k] if k < len(nums) and nums[k] != 0 else default

        if fin == b'A':                                 # CUU — clamp-free
            self._r -= p(0)
        elif fin == b'B':                               # CUD — clamp-free
            self._r += p(0)
        elif fin == b'C':                               # CUF
            self._c += p(0); self._pending = False
        elif fin == b'D':                               # CUB
            self._c -= p(0); self._pending = False
        elif fin == b'G':                               # CHA — absolute col
            self._c = p(0) - 1; self._pending = False
        elif fin in (b'H', b'f'):                        # CUP / HVP — absolute
            self._r = p(0) - 1; self._c = p(1) - 1; self._pending = False
        elif fin == b'd':                                # VPA — absolute row
            self._r = p(0) - 1
        elif fin == b'K':                                # EL
            self._erase_line(nums[0] if nums else 0)
        elif fin == b'J':                                # ED
            self._erase_display(nums[0] if nums else 0)
        # any other routed final: no modeled position effect (defensive)

    def _erase_line(self, mode: int) -> None:
        if not (0 <= self._r < self.H):
            return
        row = self._g[self._r]; sty = self._sty[self._r]; dk = self._default_key
        if mode == 0:
            rng = range(max(0, self._c), self.W)
        elif mode == 1:
            rng = range(0, min(self.W, self._c + 1))
        else:
            rng = range(self.W)
        for c in rng:
            row[c] = ' '; sty[c] = dk

    def _erase_display(self, mode: int) -> None:
        """ED — erase in display. Mode 2/3 clears everything; mode 0 clears from
        the cursor to the end of the screen; mode 1 from the start to the cursor.
        A real terminal honors all of these, so to stay transparent on correct
        streams we model them too — but ONLY when the cursor is within the
        visible grid. During claude's clamp-desync the cursor is walked off-grid;
        honoring a cursor-relative erase against an off-grid virtual cursor would
        wipe valid intent rows (the corruption), so an off-grid ED 0/1 is a
        no-op. ED 2 is absolute (whole screen) and always applies. This matches
        BOTH the real-terminal oracle on correct streams and the no-clamp intent
        on the buggy stream."""
        dk = self._default_key
        if mode == 2 or mode == 3:
            self._g = [[' '] * self.W for _ in range(self.H)]
            self._sty = [[dk] * self.W for _ in range(self.H)]
            return
        if not (0 <= self._r < self.H):
            return                                       # off-grid relative erase: skip
        if mode == 0:
            self._erase_line(0)
            for r in range(self._r + 1, self.H):
                self._g[r] = [' '] * self.W
                self._sty[r] = [dk] * self.W
        elif mode == 1:
            for r in range(0, self._r):
                self._g[r] = [' '] * self.W
                self._sty[r] = [dk] * self.W
            self._erase_line(1)


class Insulator:
    """Terminal-insulation engine: maintain claude's intended screen from the
    VT500 event stream, re-render it correctly via absolute positioning, and
    forward the control plane verbatim at its correct stream position.

    Public surface (the Phase-4 contract, identical shape to ScreenRepair so the
    swap is mechanical):
        __init__(rows, cols)
        feed(data: bytes) -> bytes      # corrected + forwarded-control output
        drain() -> bytes                # flush held tail + final repaint
        reset(rows, cols)               # SIGWINCH
        has_pending() -> bool           # an incomplete token is held

    GUARANTEES
      * No leak: every byte is classified by the canonical state machine; a
        control sequence is never emitted as a printable glyph.
      * Transparency: on a stream claude renders correctly, the Insulator's
        output rendered in a REAL terminal is grid-identical to the raw stream
        (control plane forwarded, grid re-painted to the same result).
      * Correction: on the clamp-desync stream, the output renders to claude's
        INTENT grid (the corruption is gone).
      * Ordering: a forwarded query (\x1b[c, \x1b[6n, ...) appears in the output
        between the rendered cells before and after it — never deferred past a
        flush boundary (the prior regression).
      * Defensive: feed never raises on any input; pure/clockless/deterministic.
    """

    def __init__(self, rows: int, cols: int) -> None:
        self.reset(rows, cols)

    def reset(self, rows: int, cols: int) -> None:
        """(Re)initialize for a (new) size. Clears the parser, screen, last-
        emitted snapshot, and alt-screen state so a resize mid-stream can never
        strand a half-parsed token or a stale grid."""
        self.H = max(1, rows)
        self.W = max(1, cols)
        self._parser = VT500Parser()
        self._screen = _Screen(rows, cols)
        self._default_key = _SGR().copy_key()
        # Last-emitted viewport snapshot, for the diff. Blank origin: the first
        # flush repaints only rows differing from blank (correct on a fresh pane,
        # self-correcting on any pane via absolute CUP + clear).
        self._prev = [[' '] * self.W for _ in range(self.H)]
        self._prev_sty = [[self._default_key] * self.W for _ in range(self.H)]
        self._alt = False             # inside the alternate screen buffer?

    def has_pending(self) -> bool:
        """True while the parser holds an incomplete token (partial ESC sequence
        or partial UTF-8 codepoint). The loop uses this to decide whether the
        idle-timeout backstop must drain."""
        return self._parser.has_pending()

    # -- public stream API --------------------------------------------------
    def feed(self, data: bytes) -> bytes:
        """Consume `data`; return the corrected + forwarded-control output. Never
        raises on any bytes (defensive: malformed input degrades, never crashes).
        `feed(b'')` with no held tail is b''."""
        try:
            events = self._parser.feed(data)
            return self._route(events)
        except Exception:                # noqa: BLE001 - feed must never raise
            # Should be unreachable (the parser is total and the screen clips all
            # writes), but the insulator's #1 contract is "never crash the live
            # session": surface the bytes unchanged so the terminal still gets
            # them rather than freezing on an internal defect.
            return data

    def drain(self) -> bytes:
        """Flush the parser's held tail and emit the resulting repaint. Called by
        the loop on idle timeout and at shutdown. Idempotent once empty."""
        try:
            events = self._parser.drain()
            return self._route(events)
        except Exception:                # noqa: BLE001 - drain must never raise
            return b''

    # -- the Router + interleaving emitter ----------------------------------
    def _route(self, events) -> bytes:
        """Walk events in stream order. GRID events mutate the Screen; a CONTROL
        event first flushes the diff for everything painted so far (so the prior
        visible state is on the terminal), then appends its raw bytes verbatim,
        then rendering continues. A final flush closes the batch. This is what
        puts a forwarded query at its CORRECT stream position."""
        out = bytearray()
        for ev in events:
            if self._alt:
                # Stepped aside: forward EVERYTHING verbatim until alt-exit.
                out += ev.raw
                if self._is_alt_exit(ev):
                    self._alt = False
                continue
            if self._is_alt_enter(ev):
                # Flush intent painted so far, THEN forward the alt-enter and
                # switch to passthrough for the alt buffer.
                out += self._flush_diff()
                out += ev.raw
                self._alt = True
                continue
            if self._is_grid(ev):
                self._apply_grid(ev)
            else:
                # CONTROL: forward verbatim AT its stream position. Paint prior
                # visible state first so the control lands between the cells
                # before and after it (ordering), then append the raw bytes.
                out += self._flush_diff()
                out += ev.raw
        out += self._flush_diff()
        return bytes(out)

    @staticmethod
    def _is_grid(ev) -> bool:
        """Classify one event: True = GRID (mutate Screen), False = CONTROL
        (forward raw). The single source of truth for the Router."""
        if isinstance(ev, Print):
            return True
        if isinstance(ev, Execute):
            return ev.byte in (0x0d, 0x0a, 0x08, 0x09)   # CR LF BS HT
        if isinstance(ev, EscDispatch):
            # CURSOR/SCROLL positioning ESC dispatches (DECSC/DECRC ESC 7/8,
            # RI ESC M, IND ESC D, NEL ESC E) are GRID: the emitter's absolute-
            # CUP repaint OWNS positioning, so these are consumed as no-ops in
            # the Screen and NOT forwarded — forwarding a bare RI at the top
            # margin would scroll the real terminal and shift the whole repaint
            # down by a row (the spurious blank top row bug). Charset designators
            # (intermediates present), keypad-mode ESC =/>, title ESC k, and ST
            # ESC \ are CONTROL (forwarded verbatim) and return False below.
            return (not ev.intermediates) and ev.final in (0x37, 0x38, 0x4d,
                                                            0x44, 0x45)
        if isinstance(ev, CsiDispatch):
            if ev.final < 0:
                return False                              # malformed CSI: forward inert raw
            if ev.private:
                return False                              # ?/</=/> private: CONTROL
            final = ev.final
            if final in _INSU_QUERY_FINALS:               # DA / DSR: CONTROL
                return False
            return final in _INSU_GRID_FINALS
        # Osc / Dcs / Sos / Pm / Apc: CONTROL
        return False

    def _apply_grid(self, ev) -> None:
        if isinstance(ev, Print):
            self._screen.print(ev.text)
        elif isinstance(ev, Execute):
            self._screen.execute(ev.byte)
        elif isinstance(ev, CsiDispatch):
            self._screen.csi(ev.private, ev.params, ev.final)
        elif isinstance(ev, EscDispatch):
            # Positioning ESC dispatches the Router routes to GRID. DECSC/DECRC
            # (ESC 7/8) are no-ops here (the emitter owns positioning and the
            # frozen intent oracle ignores them); RI/IND/NEL move the cursor.
            if ev.final == 0x4d:                         # RI — reverse index (up)
                self._screen.ri()
            elif ev.final == 0x44:                       # IND — index (down)
                self._screen.ind()
            elif ev.final == 0x45:                       # NEL — next line
                self._screen.nel()

    @staticmethod
    def _is_alt_enter(ev) -> bool:
        return (isinstance(ev, CsiDispatch) and ev.final in (ord('h'),)
                and (ev.private + ev.params) in _INSU_ALT_ENTER)

    @staticmethod
    def _is_alt_exit(ev) -> bool:
        return (isinstance(ev, CsiDispatch) and ev.final in (ord('l'),)
                and (ev.private + ev.params) in _INSU_ALT_EXIT)

    # -- emission (diff render, reused logic) -------------------------------
    def _flush_diff(self) -> bytes:
        """Emit absolute-positioned updates for the Screen since the last flush:
        first push any scrolled-off lines into real scrollback (bottom row +
        CRLF), then repaint rows whose chars OR style changed. Returns b'' when
        nothing changed, so an interleaved control event that follows an
        already-painted state appends NO redundant repaint."""
        scrolloff, scrolloff_sty = self._screen.take_scrolloff()
        out = bytearray()
        g = self._screen._g
        sty_plane = self._screen._sty
        if scrolloff:
            # A scroll happened: push each scrolled-off line into REAL scrollback
            # (write it at the bottom row, then CRLF — the CRLF is a real scroll
            # on the clamping terminal, so the line enters tmux history exactly as
            # claude intended). The CRLF scrolls shift every visible row on the
            # real terminal in ways a per-row diff against the pre-scroll snapshot
            # cannot track, so after the scroll we do a FULL absolute repaint of
            # the viewport (like ScreenRepair's scroll path) to re-sync the
            # clamping terminal to intent deterministically — this is what keeps
            # the result chunk-invariant (whole == 1-byte == random).
            for line, sty in zip(scrolloff, scrolloff_sty):
                out += b'\x1b[%d;1H' % self.H
                out += b'\x1b[2K'
                out += self._render_row(list(line) + [' '] * self.W, sty)
                out += b'\r\n'
            for r in range(self.H):
                out += b'\x1b[%d;1H' % (r + 1)
                out += b'\x1b[2K'
                out += self._render_row(g[r], sty_plane[r])
                self._prev[r] = list(g[r])
                self._prev_sty[r] = list(sty_plane[r])
            return bytes(out)
        # No scroll: cheap diff — repaint only rows whose chars OR style changed.
        for r in range(self.H):
            row = g[r]
            if row != self._prev[r] or sty_plane[r] != self._prev_sty[r]:
                out += b'\x1b[%d;1H' % (r + 1)
                out += b'\x1b[2K'
                out += self._render_row(row, sty_plane[r])
                self._prev[r] = list(row)
                self._prev_sty[r] = list(sty_plane[r])
        return bytes(out)

    def _render_row(self, row, sty) -> bytes:
        """Render one row to bytes, re-emitting claude's SGR per styled run so
        colors/attributes match intent EXACTLY and downstream apply_subs needles
        round-trip. Identical faithful-SGR strategy as ScreenRepair: a leading
        \x1b[0m opens the row from a clean baseline before the first styled run;
        precise per-attribute off-tokens (\x1b[22m/\x1b[39m/...) close styled
        runs so \x1b[1mBash\x1b[22m and \x1b[38;5;153m stay paired."""
        last = -1
        for c in range(len(row) - 1, -1, -1):
            if row[c] != ' ':
                last = c
                break
        if last < 0:
            return b''
        out = bytearray()
        cur = _SGR()
        opened = False
        for c in range(last + 1):
            key = sty[c] if c < len(sty) else self._default_key
            if key != cur.copy_key():
                want = _sgr_from_key(key)
                if not want.is_default() and not opened:
                    out += b'\x1b[0m'
                    opened = True
                want.replay_from(cur, out)
                cur = want
            ch = row[c]
            out += ch.encode('utf-8', 'replace') if ch != ' ' else b' '
        if not cur.is_default():
            cur.replay_to_default(out)
        return bytes(out)


# Env flag that disables the cursor-repair stage entirely (instant rollback to
# the pre-ScreenRepair wrapper, no code change). Default ON. Only these explicit
# off-values disable it; anything else (including unset) leaves repair enabled.
_REPAIR_OFF_VALUES = frozenset({"0", "off", "false", "no"})
# Repair is OPT-IN (default OFF): it is a young, high-blast-radius transform that
# rewrites the whole TUI byte stream, and a missed sequence silently mis-renders
# (the barricade only catches exceptions, not bad output). Enable explicitly with
# CLAUDE_WRAP_REPAIR=1 once you've confirmed it's clean for your usage.
_REPAIR_ON_VALUES = frozenset({"1", "on", "true", "yes"})
# Where the safety barricade logs the ONE time repair trips an exception and
# degrades to passthrough. Best-effort; a logging failure never breaks the loop.
REPAIR_DEBUG_LOG = "/tmp/claude-theme-wrap-repair.log"


def repair_enabled() -> bool:
    """True unless CLAUDE_WRAP_REPAIR is set to an explicit off-value. Read once
    at startup so a mid-session env change can't flip the pipeline shape."""
    val = os.environ.get("CLAUDE_WRAP_REPAIR", "").strip().lower()
    return val in _REPAIR_ON_VALUES


class RepairState:
    """Session-scoped holder for the output-correction pipeline so main()'s loop,
    its SIGWINCH closure, and the idle/shutdown drains all share ONE object
    instead of several free variables (containment over a sprawling loop, per
    cc-routine-and-class-design). Groups the two pure transforms (ScreenRepair +
    FrameMux) and the two sticky booleans that gate them.

    enabled  — the env flag's decision, fixed for the session.
    disabled — the safety barricade tripped (a ScreenRepair exception). Once set,
               repair is bypassed for the REST of the session: bytes flow through
               FrameMux+apply_subs exactly as the pre-repair wrapper did, so the
               session never breaks or freezes.
    """

    __slots__ = ("sr", "mux", "enabled", "disabled", "_logged")

    def __init__(self, rows: int, cols: int) -> None:
        self.enabled = repair_enabled()
        # Only build the (stateful) ScreenRepair when repair is on; when off, the
        # output path is byte-identical to today's mux-only wrapper.
        self.sr = ScreenRepair(rows, cols) if self.enabled else None
        self.mux = FrameMux()
        self.disabled = False
        self._logged = False

    def active(self) -> bool:
        """True when the repair stage should run for the next chunk."""
        return self.enabled and not self.disabled and self.sr is not None

    def _trip(self, where: str, exc: BaseException) -> None:
        """Barricade: disable repair for the rest of the session and log ONCE.
        Logging is best-effort — a failure to write the debug file must never
        propagate into the live I/O loop."""
        self.disabled = True
        if self._logged:
            return
        self._logged = True
        try:
            with open(REPAIR_DEBUG_LOG, "a") as f:
                f.write(f"[claude-theme-wrap] repair disabled at {where}: "
                        f"{type(exc).__name__}: {exc}\n")
        except OSError:
            pass

    def correct(self, data: bytes) -> bytes:
        """Run the cursor-repair stage on a chunk, guarded. Returns the corrected
        bytes (claude's intended grid, with faithful original SGR) when repair is
        active; the raw bytes unchanged when repair is off/disabled. ANY exception
        from ScreenRepair.feed trips the barricade and returns the raw bytes, so
        downstream FrameMux+apply_subs still themes them — degraded, never broken."""
        if not self.active():
            return data
        try:
            return self.sr.feed(data)
        except Exception as exc:                 # noqa: BLE001 - barricade: never raise
            self._trip("feed", exc)
            return data

    def correct_drain(self) -> bytes:
        """Flush the repair stage's held tail (idle/shutdown), guarded the same
        way as correct(). Returns b'' when repair is off/disabled or nothing is
        held."""
        if not self.active():
            return b''
        try:
            return self.sr.drain()
        except Exception as exc:                 # noqa: BLE001 - barricade: never raise
            self._trip("drain", exc)
            return b''

    def repair_pending(self) -> bool:
        """True while the repair stage holds an incomplete token (drives the idle
        backstop). False when repair is off/disabled."""
        return self.active() and self.sr.has_pending()

    def on_resize(self, rows: int, cols: int) -> None:
        """SIGWINCH: track the new geometry in the virtual grid so post-resize
        content lands on the right rows. reset() clears any held tail, so a resize
        mid-stream can't strand a half-parsed token. Guarded — a reset failure
        trips the barricade rather than killing the resize path."""
        if self.sr is None:
            return
        try:
            self.sr.reset(rows, cols)
        except Exception as exc:                 # noqa: BLE001 - barricade
            self._trip("reset", exc)


def process_output(data: bytes, state: "RepairState") -> bytes:
    """The master_fd -> stdout pipeline for one chunk:

        claude bytes -> ScreenRepair (cursor-desync repair, faithful SGR)
                     -> FrameMux.feed (apply_subs theming, frame-bracketing)
                     -> bytes to write

    With repair OFF/disabled, `state.correct` returns `data` unchanged, so this is
    byte-identical to the pre-repair wrapper's `mux.feed(data)`. ScreenRepair never
    emits a BSU/ESU, so FrameMux only ever sees out-of-frame bytes here and its
    dormant in-frame path stays untouched; if a genuine 2026 frame were present it
    would still be FrameMux — the sole frame handler — that brackets it downstream."""
    return state.mux.feed(state.correct(data))


def drain_output(state: "RepairState") -> bytes:
    """Idle/shutdown flush of BOTH pipeline stages, in pipeline order: drain the
    repair stage first so its bytes reach FrameMux, then drain FrameMux. Returns
    everything still buffered (so the final frame and any held tail aren't lost)."""
    out = bytearray()
    tail = state.correct_drain()
    if tail:
        out += state.mux.feed(tail)
    out += state.mux.drain()
    return bytes(out)


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

    # Output-correction pipeline state (ScreenRepair + FrameMux + the flag/
    # barricade booleans), shared by the loop, the SIGWINCH closure, and the
    # drains. Sized to the current geometry; SIGWINCH re-sizes the virtual grid.
    state = RepairState(rows, cols)

    def on_resize(*_):
        r, c = get_term_size()
        set_winsize(master_fd, r, c)
        # Track the new size in the virtual grid so post-resize content lands on
        # the right rows (after set_winsize, like FrameMux's clockless contract).
        state.on_resize(r, c)
    signal.signal(signal.SIGWINCH, on_resize)

    try:
        while True:
            r, _, _ = select.select([stdin_fd, master_fd], [], [], IDLE_FLUSH_SECS)
            if not r:
                # Time backstop: a frame whose ESU hasn't arrived, a held partial
                # marker, OR a held partial repair token would otherwise freeze
                # the screen. Both transforms are clockless, so the loop owns this
                # flush — drain the repair stage into the mux, then the mux.
                if state.mux.has_open_frame() or state.repair_pending():
                    write_all(stdout_fd, drain_output(state))
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
                write_all(stdout_fd, process_output(data, state))
    finally:
        # Drain whatever the pipeline still holds so the final frame isn't lost.
        try:
            write_all(stdout_fd, drain_output(state))
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
