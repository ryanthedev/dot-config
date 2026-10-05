#!/usr/bin/env bash
# Claude Code statusLine — renders one line beneath the input box:
#
#      Opus  ·   high  ·   12%  ·   main  ·   db16221
#     model      effort     context    branch     commit
#
# NOTE: this re-runs on conversation activity, not on a timer, so the git segments
# refresh on activity, not on `git checkout`. The clock lives in a Claude Code mod
# instead (dev-mods/…/clock), which ticks on a real timer.
#
# Reads the session JSON on stdin (schema: code.claude.com/docs/en/statusline).
# Fields Claude omits are skipped: effort.level is absent on non-reasoning models,
# context_window.used_percentage is null early in a session. Git segments are
# skipped outside a repo, and the branch is skipped on a detached HEAD. Colors are
# truecolor SGR tuned to the herdr theme (green accent #9ece6a). macOS /bin/bash
# 3.2 safe — nerd-font glyphs are built from raw UTF-8 bytes (no $'\u' which 3.2
# lacks), and no associative arrays.
#
# WIDTH: the payload carries no terminal width, but Claude Code exports COLUMNS
# into this process (verified: COLUMNS and `tput cols` both report the live pane
# width). Segments are dropped, lowest priority first, until the line fits — see
# DROP_ORDER below. Widths are computed from a per-segment cell count rather than
# by measuring the rendered string, since the string carries SGR escapes and
# multi-byte glyphs that ${#...} would miscount.
#
# Referenced by ~/.claude/settings.json -> statusLine.command. Version-tracked in
# the dotfiles repo. Claude reads settings.json at launch, so edits here show on
# the next session start.
input=$(cat)

esc=$'\033'; R="${esc}[0m"
GREEN="${esc}[38;2;158;206;106m"   # accent green — context when low
BLUE="${esc}[38;2;122;162;247m"    # model
PEACH="${esc}[38;2;224;175;104m"   # effort
RED="${esc}[38;2;247;118;142m"     # context when high
PURPLE="${esc}[38;2;187;154;247m"  # branch
CYAN="${esc}[38;2;125;207;255m"    # commit
FG="${esc}[38;2;192;202;245m"      # values
DIM="${esc}[38;2;86;95;137m"       # separators
SEP=" ${DIM}\xc2\xb7${R} "         # " · "

# Nerd-font glyphs as UTF-8 bytes (Font Awesome codepoints).
CHIP=$(printf '\xef\x8b\x9b')      # U+F2DB microchip (model)
BOLT=$(printf '\xef\x83\xa7')      # U+F0E7 bolt (effort)
GAUGE=$(printf '\xef\x83\xa4')     # U+F0E4 tachometer (context)
FORK=$(printf '\xef\x84\xa6')      # U+F126 code-fork (branch)
GIT=$(printf '\xef\x87\x93')       # U+F1D3 git (commit)
sep=$(printf "$SEP")

SEP_W=3        # rendered cells of " · "
GLYPH_W=2      # assume double-width glyphs; over-counting only hides sooner
PAD=2          # right-edge breathing room
MAX_BRANCH=24  # longer branch names are elided, not dropped

# Lowest priority first. Anything not named here is never dropped (context %).
DROP_ORDER="commit branch effort model"

# IFS must be tab-only: display_name contains spaces ("Opus 5 (1M context)"), and
# default IFS would shred it across the other three variables.
IFS=$'\t' read -r model effort pct dir < <(printf '%s' "$input" | jq -r '
  [ (.model.display_name // ""),
    (.effort.level // ""),
    (.context_window.used_percentage // ""),
    (.workspace.current_dir // .cwd // "") ] | @tsv')

# name / rendered text / cell width, in display order.
names=(); texts=(); widths=()
addseg() { names+=("$1"); texts+=("$2"); widths+=("$3"); }

[ -n "$model" ]  && addseg model  "${BLUE}${CHIP}${R} ${FG}${model}${R}"   $((GLYPH_W + 1 + ${#model}))
[ -n "$effort" ] && addseg effort "${PEACH}${BOLT}${R} ${FG}${effort}${R}" $((GLYPH_W + 1 + ${#effort}))
if [ -n "$pct" ]; then
  p=${pct%.*}; [ -z "$p" ] && p=0
  col=$GREEN; [ "$p" -ge 50 ] && col=$PEACH; [ "$p" -ge 80 ] && col=$RED
  addseg context "${col}${GAUGE}${R} ${col}${p}%${R}" $((GLYPH_W + 1 + ${#p} + 1))
fi

# Two cheap plumbing calls — no index read, so they stay fast in large repos.
# symbolic-ref fails on a detached HEAD; rev-parse fails before the first commit.
if [ -n "$dir" ] && command -v git >/dev/null 2>&1; then
  branch=$(git -C "$dir" symbolic-ref --quiet --short HEAD 2>/dev/null)
  sha=$(git -C "$dir" rev-parse --short HEAD 2>/dev/null)
  if [ ${#branch} -gt $MAX_BRANCH ]; then
    branch="${branch:0:$((MAX_BRANCH - 1))}$(printf '\xe2\x80\xa6')"  # …
    bw=$MAX_BRANCH
  else
    bw=${#branch}
  fi
  [ -n "$branch" ] && addseg branch "${PURPLE}${FORK}${R} ${FG}${branch}${R}" $((GLYPH_W + 1 + bw))
  [ -n "$sha" ]    && addseg commit "${CYAN}${GIT}${R} ${FG}${sha}${R}"       $((GLYPH_W + 1 + ${#sha}))
fi

alive=(); for i in "${!names[@]}"; do alive[$i]=1; done

line_width() {
  local t=0 n=0 i
  for i in "${!names[@]}"; do
    [ "${alive[$i]}" = 1 ] || continue
    t=$((t + ${widths[$i]})); n=$((n + 1))
  done
  [ "$n" -gt 1 ] && t=$((t + SEP_W * (n - 1)))
  printf '%s' "$t"
}

budget=$(( ${COLUMNS:-80} - PAD ))
for name in $DROP_ORDER; do
  [ "$(line_width)" -le "$budget" ] && break
  for i in "${!names[@]}"; do
    [ "${names[$i]}" = "$name" ] && alive[$i]=0
  done
done

out=""; first=1
for i in "${!names[@]}"; do
  [ "${alive[$i]}" = 1 ] || continue
  [ "$first" = 1 ] || out+="$sep"
  out+="${texts[$i]}"; first=0
done
printf '%s' "$out"
