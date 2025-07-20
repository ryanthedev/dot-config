#!/usr/bin/env python3
import sys
import json
import subprocess

if len(sys.argv) < 2:
    sys.exit(0)

fzf_line = sys.argv[1].strip()
if fzf_line.startswith("'") and fzf_line.endswith("'"):
    fzf_line = fzf_line[1:-1].strip()
ws_name = fzf_line.split(':', 1)[0].strip()

try:
    result = subprocess.run([
        "aerospace", "list-windows", "--workspace", ws_name, "--json"
    ], capture_output=True, text=True, check=True)
    windows_json = json.loads(result.stdout)
    if not windows_json:
        print("(empty)")
    else:
        for win in windows_json:
            print(f"[{win.get('app-name','?')}] {win.get('window-title','')}")
except Exception:
    print("(empty)")
