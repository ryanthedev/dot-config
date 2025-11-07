#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Building move-window binary..."
swiftc -O move-window.swift -o move-window

echo "Build complete!"
echo "Created: move-window (binary)"
