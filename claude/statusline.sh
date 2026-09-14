#!/usr/bin/env bash
# Claude Code statusLine — renders one line beneath the input box:
#
#      12:34  ·   Opus  ·   high  ·   12%
#     time        model      effort     context used
#
# NOTE: the clock only refreshes on conversation activity (keystroke / tool call /
# response) — Claude Code re-runs this on message updates, not on a timer. So the
# time is current whenever you're working, and can lag while the session is idle.
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
CLOCK=$(printf '\xef\x80\x97')     # U+F017 clock (time)
CHIP=$(printf '\xef\x8b\x9b')      # U+F2DB microchip (model)
BOLT=$(printf '\xef\x83\xa7')      # U+F0E7 bolt (effort)
GAUGE=$(printf '\xef\x83\xa4')     # U+F0E4 tachometer (context)
COIN=$(printf '\xef\x85\x95')      # U+F155 dollar-sign (session cost)
sep=$(printf "$SEP")

# One field per line + `IFS= read` — preserves empty fields and spaces in
# values. (Tab-delimited @tsv fails: bash collapses consecutive whitespace-IFS
# delimiters, so empty middle fields vanish and later values shift left.)
{ IFS= read -r model; IFS= read -r effort; IFS= read -r pct; IFS= read -r cost; } < <(printf '%s' "$input" | jq -r '
  (.model.display_name // ""),
  (.effort.level // ""),
  (.context_window.used_percentage // ""),
  (.cost.total_cost_usd // "")')

parts=()
parts+=("${GREEN}${CLOCK}${R} $(date '+%H:%M')")
[ -n "$model" ]  && parts+=("${BLUE}${CHIP}${R} ${FG}${model}${R}")
[ -n "$effort" ] && parts+=("${PEACH}${BOLT}${R} ${FG}${effort}${R}")
if [ -n "$pct" ]; then
  p=${pct%.*}; [ -z "$p" ] && p=0
  col=$GREEN; [ "$p" -ge 50 ] && col=$PEACH; [ "$p" -ge 80 ] && col=$RED
  parts+=("${col}${GAUGE}${R} ${col}${p}%${R}")
fi
# Session cost — client-side estimate, resets to $0 on /clear.
if [ -n "$cost" ]; then
  parts+=("$(printf '%s%s%s %s$%.2f%s' "$GREEN" "$COIN" "$R" "$FG" "$cost" "$R")")
fi

out=""
for i in "${!parts[@]}"; do
  [ "$i" -gt 0 ] && out+="$sep"
  out+="${parts[$i]}"
done
printf '%s' "$out"
