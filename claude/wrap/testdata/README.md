# Repro fixtures — claude relative-cursor clamp-desync (2.1.181)

Captured raw claude output streams (post-wrapper, byte-transparent) that
deterministically reproduce the tmux-grid corruption.

- `cap-tmux256-agenttree.bin` — TERM=tmux-256color, 5 parallel subagents + full-width table.
  First clamp divergence @ byte 16900 (`[2K][1B]` clear-loop walks off bottom row).
- `cap-xterm256-agenttree.bin` — TERM=xterm-256color, same workload. Different clear
  strategy (no `[2K][1B]`) but STILL desyncs via oversized relative vertical moves.
- `vtmodel.py` — minimal VT model with cursor-edge `clamp` toggle. clamp=ON output is
  byte-identical to a real tmux `capture-pane`; clamp=OFF = claude's intended grid.
- `transcode_prototype.py` — proof that re-rendering the intended grid via absolute
  positioning makes a clamping terminal == claude's intent (validated on both caps).

Repro: `sh -c '/bin/cat cap-tmux256-agenttree.bin' ` into a 129x41 tmux pane.
