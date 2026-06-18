"""Prototype cursor-repair transcoder.
Idea: track claude's INTENDED (no-clamp) visible grid, and re-emit it to a real
(clamping) terminal using absolute positioning, so edge-clamping can't desync it.
This file is a PROTOTYPE to validate the approach against the model oracle.
"""
import re, importlib.util
spec=importlib.util.spec_from_file_location("vt","/tmp/vtmodel.py"); vt=importlib.util.module_from_spec(spec); spec.loader.exec_module(vt)

csi=re.compile(rb'\x1b\[[0-9;?]*[A-Za-z@]'); osc=re.compile(rb'\x1b\][^\x07]*(?:\x07|\x1b\\)'); oth=re.compile(rb'\x1b.')

def transcode(data, H, W):
    """Re-render claude's intended visible grid via absolute positioning.
    Returns bytes that, on a clamping terminal, reproduce the no-clamp grid."""
    intent = vt.VT(H, W, clamp=False)   # claude's intended screen
    out = bytearray()
    prev = [[' ']*W for _ in range(H)]
    i=0; n=len(data)
    # process the whole stream into the intent model, snapshotting after each
    # write/erase by re-rendering the diff. For the oracle test we only need the
    # FINAL grid, so feed all then render once.
    intent.feed(data)
    # Emit absolute-positioned full render of intent.grid (visible H rows).
    out += b'\x1b[H'
    for r in range(H):
        out += b'\x1b[%d;1H' % (r+1)
        out += b'\x1b[2K'
        line=''.join(intent.g[r]).rstrip()
        out += line.encode('utf-8','replace')
    return bytes(out)

if __name__=='__main__':
    import sys
    for fn in ['cc-cap-raw.bin','cc-cap-xterm.bin']:
        data=open('/tmp/'+fn,'rb').read()
        # oracle = claude's intent (no-clamp grid)
        oracle=vt.VT(41,129,clamp=False); oracle.feed(data)
        ograte=oracle.grid()
        # apply repair, then run through a REAL (clamping) terminal model
        repaired=transcode(data,41,129)
        real=vt.VT(41,129,clamp=True); real.feed(repaired)
        match = real.grid()==ograte
        print(f"{fn:20} repair makes clamping-terminal == claude-intent : {match}")
        if not match:
            a=real.grid().splitlines(); b=ograte.splitlines()
            for k in range(max(len(a),len(b))):
                la=a[k] if k<len(a) else '<none>'; lb=b[k] if k<len(b) else '<none>'
                if la!=lb: print(f"   row {k}: real={la!r}\n          intent={lb!r}"); break
