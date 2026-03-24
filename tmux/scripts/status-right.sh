#!/usr/bin/env bash
pane_path=$(tmux display-message -p '#{pane_current_path}')
branch=$(git -C "$pane_path" branch --show-current 2>/dev/null)
[[ -n "$branch" ]] && printf "%s " "$branch"
