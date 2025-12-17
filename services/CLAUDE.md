# Services Directory - AI Context

This directory manages launchd services for the dotfiles. Use this information to help debug and manage services.

## Quick Commands

```bash
# Check all services
services list

# Check specific service status
services status sync-ueli-launchers

# View logs (real-time)
services logs sync-ueli-launchers

# Restart a service
services restart sync-ueli-launchers

# Install/uninstall all services
services install
services uninstall
```

## Directory Structure

```
~/.config/services/
├── CLAUDE.md           # This file - AI context
├── plists/             # LaunchAgent plist files (symlinked to ~/Library/LaunchAgents/)
│   └── com.r.*.plist
└── logs/               # Service log files
    └── *.log
```

**Helper script:** `~/.config/bin/services`

## How Services Work

1. Plist files define launchd jobs in `~/.config/services/plists/`
2. `services install` symlinks them to `~/Library/LaunchAgents/`
3. launchd loads and runs them based on their schedule
4. Logs go to `~/.config/services/logs/`

## Debugging Steps

### 1. Check if service is running
```bash
services status <name>
# or directly:
launchctl list | grep com.r
```

### 2. Check logs
```bash
services logs <name>
# or read the file:
cat ~/.config/services/logs/<name>.log
# or last 50 lines:
tail -50 ~/.config/services/logs/<name>.log
```

### 3. Check plist syntax
```bash
plutil -lint ~/.config/services/plists/com.r.<name>.plist
```

### 4. Check if symlink exists
```bash
ls -la ~/Library/LaunchAgents/com.r.*.plist
```

### 5. Manual load/unload
```bash
launchctl load ~/Library/LaunchAgents/com.r.<name>.plist
launchctl unload ~/Library/LaunchAgents/com.r.<name>.plist
```

### 6. Check launchd errors
```bash
# Get detailed info about a job
launchctl list com.r.<name>
# The second column shows exit code (0 = success)
```

## Current Services

| Service | Description | Schedule | Script |
|---------|-------------|----------|--------|
| sync-ueli-launchers | Syncs Chrome profiles to Ueli app launchers | Every 60s | `~/.config/bin/sync-ueli-launchers` |

## Adding New Services

1. Create plist in `~/.config/services/plists/com.r.<name>.plist`
2. Create the script it runs (usually in `~/.config/bin/`)
3. Run `services install` to symlink and load
4. Update the table above

### Plist Template

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.r.SERVICE_NAME</string>

    <key>ProgramArguments</key>
    <array>
        <string>/Users/r/.config/bin/SCRIPT_NAME</string>
    </array>

    <!-- Run every N seconds -->
    <key>StartInterval</key>
    <integer>60</integer>

    <!-- Or run at specific times (like cron) -->
    <!-- <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>9</integer>
        <key>Minute</key><integer>0</integer>
    </dict> -->

    <key>RunAtLoad</key>
    <true/>

    <key>StandardOutPath</key>
    <string>/Users/r/.config/services/logs/SERVICE_NAME.log</string>

    <key>StandardErrorPath</key>
    <string>/Users/r/.config/services/logs/SERVICE_NAME.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
    </dict>
</dict>
</plist>
```

## Common Issues

| Problem | Solution |
|---------|----------|
| Service not starting | Check `plutil -lint` on the plist for syntax errors |
| Service crashing | Check logs in `~/.config/services/logs/` |
| Script not found | Verify path in plist, check script is executable |
| PATH issues | Ensure PATH is set in plist EnvironmentVariables |
| Permission denied | Check script has execute permission (`chmod +x`) |
| Service runs but nothing happens | Check if script works when run manually |

## launchd vs cron

We use launchd instead of cron because:
- Apple recommends it (cron is "legacy" in macOS Sequoia)
- launchd catches up on missed jobs after sleep/wake
- Better integration with macOS

## Related Files

- `~/.config/bin/services` - Service management script
- `~/Library/LaunchAgents/` - Where symlinks are installed
- Existing non-managed LaunchAgents: skhd, yabai, AeroSpace
