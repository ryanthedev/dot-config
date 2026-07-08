#!/usr/bin/env bash
# Claude Code statusLine — renders one line beneath the input box:
#
#      Opus  ·   high  ·   12%
#     model      effort     context used
#
# (The live clock lives in a dedicated herdr pane — scripts/clock.sh — because
#  the statusLine only refreshes on conversation activity, not on a timer.)
#
# Reads the session JSON on stdin (schema: code.claude.com/docs/en/statusline).
# Fields Claude omits are skipped: effort.level is absent on non-reasoning models,
# context_window.used_percentage is null early in a session. Colors are truecolor
# SGR tuned to the herdr theme (green accent #9ece6a). macOS /bin/bash 3.2 safe —
# nerd-font glyphs are built from raw UTF-8 bytes (no $'\u' which 3.2 lacks).
#
# Referenced by ~/.claude/settings.json -> statusLine.command. Version-tracked in
# the dotfiles repo. Claude reads settings.json at launch, so edits here show on
# the next session start.
input=$(cat)

esc=$'\033'; R="${esc}[0m"
GREEN="${esc}[38;2;158;206;106m"   # accent green — time
BLUE="${esc}[38;2;122;162;247m"    # model
PEACH="${esc}[38;2;224;175;104m"   # effort
RED="${esc}[38;2;247;118;142m"     # context when high
FG="${esc}[38;2;192;202;245m"      # values
DIM="${esc}[38;2;86;95;137m"       # separators
SEP=" ${DIM}\xc2\xb7${R} "         # " · "

# Nerd-font glyphs as UTF-8 bytes (Font Awesome codepoints).
CHIP=$(printf '\xef\x8b\x9b')      # U+F2DB microchip (model)
BOLT=$(printf '\xef\x83\xa7')      # U+F0E7 bolt (effort)
GAUGE=$(printf '\xef\x83\xa4')     # U+F0E4 tachometer (context)
sep=$(printf "$SEP")

read -r model effort pct < <(printf '%s' "$input" | jq -r '
  [ (.model.display_name // ""),
    (.effort.level // ""),
    (.context_window.used_percentage // "") ] | @tsv')

parts=()
[ -n "$model" ]  && parts+=("${BLUE}${CHIP}${R} ${FG}${model}${R}")
[ -n "$effort" ] && parts+=("${PEACH}${BOLT}${R} ${FG}${effort}${R}")
if [ -n "$pct" ]; then
  p=${pct%.*}; [ -z "$p" ] && p=0
  col=$GREEN; [ "$p" -ge 50 ] && col=$PEACH; [ "$p" -ge 80 ] && col=$RED
  parts+=("${col}${GAUGE}${R} ${col}${p}%${R}")
fi

out=""
for i in "${!parts[@]}"; do
  [ "$i" -gt 0 ] && out+="$sep"
  out+="${parts[$i]}"
done
printf '%s' "$out"
