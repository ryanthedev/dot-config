#!/bin/bash

# Get window title and app name
window_info=$(yabai -m query --windows --window)
app_name=$(echo $window_info | jq -r '.app')
window_title=$(echo $window_info | jq -r '.title')

# Show dialog and get response
response=$(osascript -e "display dialog \"Close window: $app_name${window_title:+ - $window_title}?\" buttons {\"Cancel\", \"Close\"} default button \"Close\"" 2>/dev/null)

# Check if user clicked "Close"
if [[ $response == *"Close"* ]]; then
    yabai -m window --close
fi
