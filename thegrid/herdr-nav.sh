#!/bin/zsh
# cmd-h / cmd-l inside Herdr: move between Herdr panes, and only when there is
# no pane further that way, fall through to theGrid's window focus (what
# cmd-h / cmd-l do everywhere else). Like vim-tmux-navigator.
# Wired up in bfd.yaml under apps: Herdr.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
dir=$1                                   # left | right
case $dir in
  left)  grid=prev ;;
  right) grid=next ;;
  *) echo "usage: herdr-nav.sh left|right" >&2; exit 2 ;;
esac

pane() { herdr-app status 2>/dev/null | sed -n 's/.*"focused_pane": "\(.*\)".*/\1/p'; }

before=$(pane)
herdr-app do pane.go "{\"direction\":\"$dir\"}" >/dev/null 2>&1
if [[ -z $before || $(pane) == $before ]]; then
  thegrid focus $grid --mouse >/dev/null 2>&1
fi
