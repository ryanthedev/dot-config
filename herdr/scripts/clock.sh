#!/usr/bin/env bash
# Live ticking clock for a herdr throwaway pane (keys.command type="pane").
# Zero-dependency: pure bash + tput — no tty-clock/figlet/watch needed. Draws a
# big block-digit HH:MM:SS centered in the pane, green to match the herdr accent
# (#9ece6a), with the date beneath. Re-renders every second and re-centers on
# resize. Quit with q or Ctrl-C; herdr closes the throwaway pane on exit.
# Mirrors the house style of scrollback-nvim.sh (POSIX-ish, well-commented).
set -u

GREEN=$'\033[38;2;158;206;106m'
DIM=$'\033[38;2;86;95;137m'
RST=$'\033[0m'

# grow <char> <row 0..4> -> the block pattern for that glyph row.
# Each glyph is a fixed width across all 5 rows (digits 3 cols, colon 1 col),
# so horizontal concatenation with a constant gap stays vertically aligned.
grow() {
  local ch="$1" row="$2" r0 r1 r2 r3 r4
  case "$ch" in
    0) r0='███' r1='█ █' r2='█ █' r3='█ █' r4='███';;
    1) r0='  █' r1='  █' r2='  █' r3='  █' r4='  █';;
    2) r0='███' r1='  █' r2='███' r3='█  ' r4='███';;
    3) r0='███' r1='  █' r2='███' r3='  █' r4='███';;
    4) r0='█ █' r1='█ █' r2='███' r3='  █' r4='  █';;
    5) r0='███' r1='█  ' r2='███' r3='  █' r4='███';;
    6) r0='███' r1='█  ' r2='███' r3='█ █' r4='███';;
    7) r0='███' r1='  █' r2='  █' r3='  █' r4='  █';;
    8) r0='███' r1='█ █' r2='███' r3='█ █' r4='███';;
    9) r0='███' r1='█ █' r2='███' r3='  █' r4='███';;
    :) r0=' '  r1='█'  r2=' '  r3='█'  r4=' ' ;;
    *) r0=' '  r1=' '  r2=' '  r3=' '  r4=' ' ;;
  esac
  eval "printf '%s' \"\$r$row\""
}

# build_rows <HH:MM:SS> -> populate globals R0..R4 with the assembled art rows.
build_rows() {
  local t="$1" i ch
  R0='' R1='' R2='' R3='' R4=''
  for (( i=0; i<${#t}; i++ )); do
    ch="${t:i:1}"
    R0+="$(grow "$ch" 0) "; R1+="$(grow "$ch" 1) "; R2+="$(grow "$ch" 2) "
    R3+="$(grow "$ch" 3) "; R4+="$(grow "$ch" 4) "
  done
}

# Self-test: render one static frame with no tty/tput, for verification.
if [ "${1:-}" = "--test" ]; then
  build_rows "12:34:56"
  printf '%s\n%s\n%s\n%s\n%s\n' "$R0" "$R1" "$R2" "$R3" "$R4"
  exit 0
fi

cleanup() { tput cnorm 2>/dev/null; tput sgr0 2>/dev/null; clear; exit 0; }
trap cleanup INT TERM

pad() { local n=$1 s; printf -v s '%*s' "$n" ''; printf '%s' "$s"; }

render() {
  local t d cols lines w top dpad i
  t=$(date '+%H:%M:%S'); d=$(date '+%A, %d %B %Y')
  build_rows "$t"
  cols=$(tput cols 2>/dev/null || echo 80)
  lines=$(tput lines 2>/dev/null || echo 24)
  w=${#R0}
  top=$(( (lines - 8) / 2 )); (( top < 0 )) && top=0
  local sp; sp=$(pad $(( (cols - w) / 2 < 0 ? 0 : (cols - w) / 2 )))
  dpad=$(( (cols - ${#d}) / 2 )); (( dpad < 0 )) && dpad=0
  clear
  for (( i=0; i<top; i++ )); do printf '\n'; done
  printf '%s%s%s%s\n' "$sp" "$GREEN" "$R0" "$RST"
  printf '%s%s%s%s\n' "$sp" "$GREEN" "$R1" "$RST"
  printf '%s%s%s%s\n' "$sp" "$GREEN" "$R2" "$RST"
  printf '%s%s%s%s\n' "$sp" "$GREEN" "$R3" "$RST"
  printf '%s%s%s%s\n' "$sp" "$GREEN" "$R4" "$RST"
  printf '\n%s%s%s%s\n' "$(pad "$dpad")" "$DIM" "$d" "$RST"
}

tput civis 2>/dev/null
while :; do
  render
  # read doubles as the 1-second tick AND the quit handler.
  if read -rsn1 -t 1 key; then
    case "$key" in q|Q) cleanup;; esac
  fi
done
