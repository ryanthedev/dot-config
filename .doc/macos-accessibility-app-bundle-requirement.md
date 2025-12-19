# macOS Accessibility Permissions: App Bundle Requirement

## Summary

The `grid-server` binary must be distributed as a `.app` bundle (not a standalone CLI binary) for macOS Accessibility permissions to work reliably on macOS Sonoma/Sequoia.

## Problem

When `grid-server` is distributed as a standalone Homebrew binary at `/opt/homebrew/Cellar/thegrid/x.x.x/bin/grid-server`:

1. **System Settings UI refuses to add CLI binaries** - The Accessibility pane in System Settings shows "Item from unidentified developer" and silently fails to add unsigned CLI tools to the Accessibility list.

2. **TCC database csreq mismatch** - Even when entries exist in the TCC database with `auth_value=2` (allowed), the code signing requirement (`csreq`) stored at permission grant time may not match the binary's current signature, causing `-25211` (kAXErrorAPIDisabled) errors.

3. **Ad-hoc signatures are insufficient** - Linker-signed or ad-hoc signed binaries lack a designated requirement that macOS can reliably verify.

## Evidence

### Error Logs
```json
{"err":-25211,"ev":"ax.fail","notif":"AXFocusedWindowChanged","op":"register_notif"}
{"ev":"ax.permission.denied","msg":"add grid-server to System Settings > Privacy & Security > Accessibility"}
```

### TCC Database State
```
/opt/homebrew/Cellar/thegrid/0.1.2/bin/grid-server|2|4|0
```
- `auth_value=2` means "allowed" but still fails due to csreq mismatch

### Code Signing Status
```
Signature=adhoc
TeamIdentifier=not set
```

## Solution

Distribute `grid-server` as a proper `.app` bundle:

### Required Structure
```
GridServer.app/
├── Contents/
│   ├── Info.plist
│   └── MacOS/
│       └── grid-server    # The actual binary
```

### Info.plist Requirements
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>grid-server</string>
    <key>CFBundleIdentifier</key>
    <string>com.thegrid.server</string>
    <key>CFBundleName</key>
    <string>GridServer</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleVersion</key>
    <string>0.1.2</string>
    <key>LSBackgroundOnly</key>
    <true/>
    <key>LSUIElement</key>
    <true/>
</dict>
</plist>
```

### Key Properties
- `LSBackgroundOnly: true` - Runs as background process (no dock icon)
- `LSUIElement: true` - No menu bar presence
- `CFBundleIdentifier` - Consistent identifier for TCC tracking

### Code Signing
Sign the app bundle with ad-hoc signature:
```bash
codesign -fs - --deep GridServer.app
```

Or with a Developer ID for distribution:
```bash
codesign -fs "Developer ID Application: Your Name" --deep GridServer.app
```

## Homebrew Formula Changes

Update the formula to:
1. Build/copy the binary into an app bundle structure
2. Install to `/Applications/GridServer.app` or user Applications folder
3. Create a symlink for CLI access: `ln -s /Applications/GridServer.app/Contents/MacOS/grid-server /opt/homebrew/bin/grid-server`

### LaunchAgent Plist
Update to launch the app bundle binary:
```xml
<key>ProgramArguments</key>
<array>
    <string>/Applications/GridServer.app/Contents/MacOS/grid-server</string>
</array>
```

## Why This Works

1. **App bundles have bundle identifiers** - macOS tracks permissions by bundle ID (`com.thegrid.server`) rather than file path, which is more stable across updates.

2. **System Settings recognizes .app files** - The UI properly displays and allows toggling permissions for app bundles.

3. **Consistent code signing** - The bundle's signature is verified against the embedded binary, and the csreq stored in TCC matches the bundle identifier.

## References

- Error `-25211`: `kAXErrorAPIDisabled` - Accessibility API access denied
- TCC: Transparency, Consent, and Control framework
- TCC Database: `/Library/Application Support/com.apple.TCC/TCC.db`

---

*Document created: 2025-12-19*
*Based on debugging session with Claude Code*
