import re, sys

class _Style:
    """Independent SGR-attribute tracker for the oracle (NOT shared with the
    production _SGR — a separate implementation so a shared bug can't hide a
    failure). Models sticky SGR accumulation over the codes claude emits and
    canonicalizes each active attribute to a stable key, so styled_grid() can
    compare claude's INTENDED per-cell color against the repaired stream's.
    Char/cursor behavior is untouched; this is a parallel plane only."""
    # flag code -> off code (22 cancels bold AND dim).
    _FLAG_OFF = {1: 22, 2: 22, 3: 23, 4: 24, 5: 25, 7: 27, 8: 28, 9: 29}
    _OFF_CODES = {22: (1, 2), 23: (3,), 24: (4,), 25: (5,),
                  27: (7,), 28: (8,), 29: (9,)}

    def __init__(self):
        self.flags = set()   # active flag codes (canonical: 1,3,4,...)
        self.fg = None       # canonical fg key, e.g. ('256', 153) or ('idx', 32)
        self.bg = None

    def apply(self, nums):
        # nums: list of int sub-params (already parsed). Empty -> reset.
        if not nums:
            nums = [0]
        i = 0
        while i < len(nums):
            code = nums[i]
            if code == 0:
                self.flags.clear(); self.fg = None; self.bg = None
            elif code in self._FLAG_OFF:
                # dim(2) is modeled as bold(1) for keying? No — keep distinct.
                self.flags.add(code)
            elif code in self._OFF_CODES:
                for f in self._OFF_CODES[code]:
                    self.flags.discard(f)
            elif code in (38, 48):
                key, consumed = self._ext(nums, i)
                if key is not None:
                    if code == 38: self.fg = key
                    else: self.bg = key
                i += consumed; continue
            elif code == 39:
                self.fg = None
            elif code == 49:
                self.bg = None
            elif 30 <= code <= 37 or 90 <= code <= 97:
                self.fg = ('idx', code)
            elif 40 <= code <= 47 or 100 <= code <= 107:
                self.bg = ('idx', code)
            i += 1

    @staticmethod
    def _ext(nums, i):
        if i + 1 >= len(nums): return None, 1
        mode = nums[i + 1]
        if mode == 5 and i + 2 < len(nums):
            return ('256', nums[i + 2]), 3
        if mode == 2 and i + 4 < len(nums):
            return ('rgb', nums[i + 2], nums[i + 3], nums[i + 4]), 5
        return None, 1

    def key(self):
        return (tuple(sorted(self.flags)), self.fg, self.bg)


class VT:
    def __init__(self, rows, cols, clamp=True):
        self.rows, self.cols, self.clamp = rows, cols, clamp
        self.g = [[' ']*cols for _ in range(rows)]
        # Parallel style plane: per-cell active-SGR key at write time. Default
        # key for blank/erased cells. Independent of the char grid — adding it
        # does NOT change cursor/char behavior (clamp=ON stays byte-identical to
        # a real tmux capture-pane).
        self.sgr = _Style()
        self._dk = _Style().key()
        self.sty = [[self._dk]*cols for _ in range(rows)]
        self.r=0; self.c=0; self.pending=False  # pending = magic-margin wrap (am+xenl)
        self.events=[]
    def _cl_r(self,r): return max(0,min(self.rows-1,r)) if self.clamp else r
    def _cl_c(self,c): return max(0,min(self.cols-1,c)) if self.clamp else c
    def scroll(self):
        self.g.pop(0); self.g.append([' ']*self.cols)
        self.sty.pop(0); self.sty.append([self._dk]*self.cols)
    def lf(self):
        self.pending=False
        if self.r==self.rows-1: self.scroll()
        else: self.r+=1
    def cr(self): self.pending=False; self.c=0
    def putch(self,ch):
        if self.pending:
            self.cr(); self.lf()
        if 0<=self.r<self.rows and 0<=self.c<self.cols:
            self.g[self.r][self.c]=ch
            self.sty[self.r][self.c]=self.sgr.key()  # record color at this cell
        if self.c==self.cols-1:
            self.pending=True   # magic margin: stay, set pending
        else:
            self.c+=1
    def feed(self,data):
        i=0; n=len(data)
        while i<n:
            b=data[i]
            if b==0x1b:
                # CSI
                m=re.match(rb'\x1b\[([0-9;?]*)([A-Za-z@])', data[i:])
                if m:
                    params=m.group(1); fin=m.group(2)
                    if params.startswith(b'?'):
                        i+=m.end(); continue   # private modes (?25h etc) - ignore for grid
                    nums=[int(x) if x else 0 for x in params.split(b';')] if params else []
                    f=fin
                    def p(k,d=1): 
                        return nums[k] if k<len(nums) and nums[k]!=0 else d
                    if f==b'A':  # CUU
                        before=self.r; self.r=self._cl_r(self.r-p(0))
                        if self.clamp and (self.r-(before-p(0)))!=0: pass
                    elif f==b'B': self.r=self._cl_r(self.r+p(0))
                    elif f==b'C': self.c=self._cl_c(self.c+p(0)); self.pending=False
                    elif f==b'D': self.c=self._cl_c(self.c-p(0)); self.pending=False
                    elif f==b'G': self.c=self._cl_c(p(0)-1); self.pending=False
                    elif f==b'H' or f==b'f':
                        self.r=self._cl_r(p(0)-1); self.c=self._cl_c(p(1)-1); self.pending=False
                    elif f==b'd': self.r=self._cl_r(p(0)-1)
                    elif f==b'K':
                        mode=nums[0] if nums else 0
                        if 0<=self.r<self.rows:
                            if mode==0:
                                for c in range(max(0,self.c),self.cols):
                                    self.g[self.r][c]=' '; self.sty[self.r][c]=self._dk
                            elif mode==1:
                                for c in range(0,min(self.cols,self.c+1)):
                                    self.g[self.r][c]=' '; self.sty[self.r][c]=self._dk
                            else:
                                for c in range(self.cols):
                                    self.g[self.r][c]=' '; self.sty[self.r][c]=self._dk
                    elif f==b'J':
                        mode=nums[0] if nums else 0
                        if mode==2:
                            self.g=[[' ']*self.cols for _ in range(self.rows)]
                            self.sty=[[self._dk]*self.cols for _ in range(self.rows)]
                    elif f==b'm':
                        # SGR: mutate the parallel style state. No char/cursor
                        # effect, so clamp=ON char positioning is unchanged.
                        self.sgr.apply(nums)
                    i+=m.end(); continue
                # OSC
                m=re.match(rb'\x1b\][^\x07]*(\x07|\x1b\\)', data[i:])
                if m: i+=m.end(); continue
                m=re.match(rb'\x1b.', data[i:])
                if m: i+=m.end(); continue
                i+=1; continue
            if b==0x0d: self.cr(); i+=1; continue
            if b==0x0a: self.lf(); i+=1; continue
            if b==0x08: self.c=max(0,self.c-1); i+=1; continue
            if b<0x20: i+=1; continue
            # UTF-8 decode one char (treat width 1 for this content)
            if b<0x80: ch=chr(b); i+=1
            else:
                L=2 if b<0xe0 else 3 if b<0xf0 else 4
                try: ch=data[i:i+L].decode('utf-8')
                except: ch='?'
                i+=L
            self.putch(ch)
    def grid(self):
        return '\n'.join(''.join(row).rstrip() for row in self.g)

    def styled_grid(self):
        """Color-aware grid: a tuple of per-row tuples of (char, style_key) up to
        each row's last non-blank cell (trailing blanks trimmed, mirroring grid()'s
        rstrip). Two streams with equal styled_grid() render IDENTICAL glyphs AND
        IDENTICAL per-cell colors — so clamp(repair).styled_grid() ==
        noclamp(raw).styled_grid() catches color loss that grid() (char-only)
        cannot. Default-style cells carry the default key, so an uncolored stream
        still compares equal to itself."""
        out = []
        for r in range(self.rows):
            row, sty = self.g[r], self.sty[r]
            last = -1
            for c in range(self.cols - 1, -1, -1):
                if row[c] != ' ':
                    last = c; break
            out.append(tuple((row[c], sty[c]) for c in range(last + 1)))
        return tuple(out)

if __name__=='__main__':
    data=open(sys.argv[1],'rb').read()
    rows,cols=int(sys.argv[2]),int(sys.argv[3])
    clamp = sys.argv[4]!='noclamp' if len(sys.argv)>4 else True
    vt=VT(rows,cols,clamp); vt.feed(data)
    print(vt.grid())
