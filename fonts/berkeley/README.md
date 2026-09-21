# Berkeley Mono Nerd Font, repaired for kitty

`dist/` holds the four Berkeley Mono Nerd Font faces after `patch.py` fixed them for
kitty on macOS: recentered obliques, overhanging Latin glyphs pulled inside the cell,
and correct monospace/bold/italic metadata so kitty stops falling back to Menlo.

- `bin/install-fonts` (or `make fonts`) installs `dist/` into `~/Library/Fonts`.
- `bin/install-fonts --rebuild` regenerates `dist/` from the untouched originals in
  `src/` (git-ignored; drop the stock Nerd Font `.otf` files there).

Berkeley Mono is a commercial font from Berkeley Graphics. Only keep `dist/` in a
repository you are licensed to distribute it in.
