#!/bin/bash
# Save this as cycle_displays.sh

# Get the current and total number of displays
current=$(yabai -m query --displays --display | jq '.index')
total=$(yabai -m query --displays | jq length)

# Determine the next display index with wrapping
if [[ $1 == "next" ]]; then
    next=$(( (current % total) + 1 ))
elif [[ $1 == "prev" ]]; then
    next=$(( current - 1 ))
    if [[ $next -lt 1 ]]; then
        next=$total
    fi
fi

# Focus the next display
yabai -m display --focus $next
