#!/bin/sh
# Scrollback in floating nvim (editable / yankable) — herdr clone of the tmux
# `prefix v` binding. Runs in a throwaway herdr pane (keys.command type="pane"),
# which herdr closes when nvim exits.
#
# herdr injects the SOURCE pane (the one focused when the keybind fired) as
# HERDR_ACTIVE_PANE_ID, distinct from HERDR_PANE_ID (this throwaway pane).
set -eu

src="${HERDR_ACTIVE_PANE_ID:-}"
out="${TMPDIR:-/tmp}/herdr-scroll"

# Self-diagnostic: if herdr didn't hand us the source pane, don't silently
# capture the wrong (empty) pane — show what we DID get so we can fix the var.
if [ -z "$src" ]; then
  {
    echo "HERDR_ACTIVE_PANE_ID was empty — herdr did not inject the source pane id."
    echo "Adjust scrollback-nvim.sh to use whichever of these points at the origin pane:"
    echo
    env | grep '^HERDR_' | sort
  } > "$out"
  exec nvim +'setlocal buftype=nofile' +'nnoremap <buffer> q :q!<CR>' "$out"
fi

# Fullscreen feel (tmux used a 99% popup); zoom this throwaway pane. Best-effort.
herdr pane zoom "${HERDR_PANE_ID:-}" --on >/dev/null 2>&1 || true

# Capture the source pane's recent scrollback WITH ansi colors (== capture-pane -e).
herdr pane read "$src" --source recent --lines 3000 --format ansi > "$out" 2>/dev/null \
  || herdr pane read "$src" --lines 3000 --format ansi > "$out"

# Filetype: prefer herdr's detected agent, else the foreground command name.
agent=$(herdr pane get "$src" 2>/dev/null \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["result"]["pane"].get("agent_session",{}).get("agent") or "")' 2>/dev/null || true)
cmd=$(herdr pane process-info --pane "$src" 2>/dev/null \
  | python3 -c 'import sys,json;fp=json.load(sys.stdin)["result"]["process_info"]["foreground_processes"];print(fp[-1].get("argv0","") if fp else "")' 2>/dev/null || true)

case "$agent" in
  claude*|codex*|gemini*|droid*|copilot*|cursor*|amp*|opencode*) ft=markdown ;;
  *)
    case "$cmd" in
      *[Pp]ython*)          ft=python ;;
      *node*|*deno*|*bun*)  ft=javascript ;;
      *ruby*|*irb*)         ft=ruby ;;
      *go)                  ft=go ;;
      *cargo*|*rustc*)      ft=rust ;;
      *)                    ft=bash ;;
    esac ;;
esac

# Open it: line numbers, scratch buffer, q to quit, baleia to render the ANSI,
# jump to the bottom (newest output) — same recipe as the tmux popup.
exec nvim --cmd 'let g:scrollback=1' \
  +"setlocal number buftype=nofile bufhidden=wipe noswapfile filetype=$ft" \
  +'nnoremap <buffer> q :q!<CR>' \
  +'BaleiaColorize' \
  +'normal! G' \
  "$out"
