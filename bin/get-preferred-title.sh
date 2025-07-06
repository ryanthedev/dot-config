#!/usr/bin/env bash
# get-preferred-title.sh
# Usage: get-preferred-title.sh <workspace>
# Prints the preferred window title for the given workspace (Code > kitty > Chrome > any)

ws_name="$1"
windows_json=$(aerospace list-windows --workspace "$ws_name" --json 2>/dev/null)
preferred_title=$(printf '%s\n' "$windows_json" | jq -r '.[] | select(."app-name"=="Code") | "[Code] " + .["window-title"]' | head -n1)
[ -z "$preferred_title" ] && preferred_title=$(printf '%s\n' "$windows_json" | jq -r '.[] | select(."app-name"=="kitty") | "[kitty] " + .["window-title"]' | head -n1)
[ -z "$preferred_title" ] && preferred_title=$(printf '%s\n' "$windows_json" | jq -r '.[] | select(."app-name"=="Google Chrome") | "[Google Chrome] " + .["window-title"]' | head -n1)
[ -z "$preferred_title" ] && preferred_title=$(printf '%s\n' "$windows_json" | jq -r '.[] | "[" + .["app-name"] + "] " + .["window-title"]' | head -n1)
[ -z "$preferred_title" ] && preferred_title="(empty)"
echo "$preferred_title"
