# Claude Code Instructions

## Scripting Preference

When you need to run multi-step shell operations, complex logic, or debugging scripts:

1. **Prefer Python over bash** - Write a Python script instead of complex bash one-liners or pipelines
2. **Use a session-specific script file:**
   - Generate a random 4-char ID at session start (e.g., `a7x3`)
   - Script path: `/Users/r/.config/bin/claude-debug-{id}.py`
   - Reuse the same ID throughout the session
3. **Clean up** - Delete the script file when done, or leave it if the user might want to inspect it

### When to use Python vs bash:
- **Python:** Multi-step operations, parsing output, error handling, conditionals/loops, JSON processing
- **Bash:** Simple single commands (ls, git status, grep, etc.)

### Example workflow:
```python
#!/usr/bin/env python3
import subprocess
import json

result = subprocess.run(['some', 'command'], capture_output=True, text=True)
print(result.stdout)
```

Run with: `python3 /Users/r/.config/bin/claude-debug-{id}.py`
