#!/usr/bin/env python3
"""Repair the Berkeley Mono Nerd Font family for kitty on macOS.

kitty renders every cell into a canvas exactly one cell wide. Glyphs whose
outlines reach past their advance width are clipped (italic slots) or shrunk
(main font). The Nerd Font build of Berkeley Mono has three problems that
trigger this, plus mislabelled metadata that makes macOS treat the bold faces
as proportional so kitty never picks them:

  1. Oblique/BoldOblique lean up to 107 units past the 600-unit cell because
     the slant was applied about the baseline with no recentering.
  2. Regular/Bold have 129 Latin glyphs (r, k, K, E, [ ...) that overhang the
     cell on the right.
  3. Bold/BoldOblique: four ligature glyphs have non-600 advances and the CFF
     and post fixed-pitch flags are off, so CoreText drops the monospace trait.
     Style-name records and fsSelection/macStyle bits are also wrong.

Usage: patch.py SRC_DIR DST_DIR     (expects BerkeleyMonoNerdFont-{Regular,Bold,Oblique,BoldOblique}.otf in SRC_DIR)
Requires: python3 with fontTools (pip install fonttools).
"""
import os, sys
from fontTools.ttLib import TTFont
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.boundsPen import BoundsPen

FACES = {
    #  face          subfamily        bold   italic  uniform x shift
    'Regular':     ('Regular',       False, False,     0),
    'Bold':        ('Bold',          True,  False,     0),
    'Oblique':     ('Oblique',       False, True,   -130),
    'BoldOblique': ('Bold Oblique',  True,  True,   -130),
}
CELL = 600

def skip_fit(cp):
    """Glyphs that are meant to touch or exceed the cell: box drawing, blocks, arrows, icons."""
    return cp is None or cp >= 0xE000 or 0x2500 <= cp <= 0x259F or 0x2190 <= cp <= 0x21FF \
        or cp in (0x23FB, 0x23FC, 0x23FD, 0x23FE, 0x2B58)

def fix_metadata(f, sub, bold, italic):
    for n in f['name'].names:
        if n.nameID == 2:
            n.string = sub
    fs = f['OS/2'].fsSelection & ~(1 << 6)                    # clear REGULAR
    fs = (fs | (1 << 5)) if bold else (fs & ~(1 << 5))         # BOLD
    fs = (fs | 1) if italic else (fs & ~1)                     # ITALIC
    f['OS/2'].fsSelection = fs
    f['head'].macStyle = (1 if bold else 0) | (2 if italic else 0)

def fix_monospace(f):
    hm = f['hmtx'].metrics
    for g, (w, lsb) in list(hm.items()):
        if w != CELL:
            hm[g] = (CELL, lsb)
    f['post'].isFixedPitch = 1
    f['OS/2'].panose.bProportion = 9
    f['hhea'].advanceWidthMax = CELL
    f['OS/2'].xAvgCharWidth = CELL
    f['CFF '].cff.topDictIndex[0].isFixedPitch = 1

def reshape(f, uniform_dx):
    """Re-encode charstrings: uniform shift for obliques, then per-glyph left shift so
    Latin glyphs fit inside the cell wherever there is room on the left."""
    gs = f.getGlyphSet(); cff = f['CFF '].cff; td = cff.topDictIndex[0]; cs = td.CharStrings; pd = td.Private
    default = getattr(pd, 'defaultWidthX', 0); hm = f['hmtx'].metrics
    rev = {v: k for k, v in f.getBestCmap().items()}
    moved = 0
    for name in f.getGlyphOrder():
        bp = BoundsPen(gs); gs[name].draw(bp)
        if not bp.bounds:
            continue
        x0, _, x1, _ = bp.bounds
        dx = uniform_dx
        if not skip_fit(rev.get(name)):
            over = (x1 + dx) - CELL
            if over > 1:
                dx -= min(over, x0 + dx)   # never push the left edge below 0
        if dx == 0:
            continue
        adv = hm[name][0]
        pen = T2CharStringPen(adv if adv != default else None, gs, roundTolerance=0.5)
        gs[name].draw(TransformPen(pen, (1, 0, 0, 1, dx, 0)))
        cs[name] = pen.getCharString(private=pd, globalSubrs=cff.GlobalSubrs)
        moved += 1
    if hasattr(pd, 'Subrs'):
        del pd.Subrs
    # recompute sidebearings and bounding boxes from the new outlines
    gs2 = f.getGlyphSet(); xs = []; ys = []
    for name in f.getGlyphOrder():
        bp = BoundsPen(gs2); gs2[name].draw(bp)
        if bp.bounds:
            hm[name] = (hm[name][0], int(round(bp.bounds[0])))
            xs += [bp.bounds[0], bp.bounds[2]]; ys += [bp.bounds[1], bp.bounds[3]]
    box = [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]
    f['head'].xMin, f['head'].yMin, f['head'].xMax, f['head'].yMax = box
    td.FontBBox = box
    return moved

def main(src, dst):
    os.makedirs(dst, exist_ok=True)
    for face, (sub, bold, italic, dx) in FACES.items():
        fn = f'BerkeleyMonoNerdFont-{face}.otf'
        f = TTFont(os.path.join(src, fn))
        fix_metadata(f, sub, bold, italic)
        fix_monospace(f)
        moved = reshape(f, dx)
        f.save(os.path.join(dst, fn))
        print(f'{fn}: {moved} glyphs reshaped')

if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
