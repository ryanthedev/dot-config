# SSH Key Management: Per-Host Keys with Automated Setup

## Summary

SSH keys are organized per remote host (`~/.ssh/{host}`) with automated setup via `ssh-setup` and terminal configuration via `dabootstrap`. This provides clean key isolation and one-command provisioning for new machines.

## Problem

Managing SSH across multiple machines and servers has several pain points:

1. **Key sprawl** - Generic key names like `id_ed25519` make it unclear which servers use which keys
2. **Manual setup** - Each new machine requires: generate key, copy key, update config, configure terminal
3. **Terminal issues** - Ghostty's terminfo isn't installed on remote servers, causing broken colors/keys
4. **No automation** - Repeating manual steps is error-prone and tedious

## Solution

### Key Naming Convention

Keys are named after their remote host:
```
~/.ssh/linode          # Private key for linode
~/.ssh/linode.pub      # Public key for linode
~/.ssh/aws-east-vm1    # Private key for AWS VM
```

### Key Comment Format

Keys include the local machine name for identification when auditing `authorized_keys`:
```
r@Ryans-Mac-Studio→linode
```

This makes it easy to revoke access from a specific local machine.

### SSH Config Structure

Each host has a dedicated config block:
```
Host linode
    HostName 139.144.44.123
    User r
    IdentityFile ~/.ssh/linode

Host aws-east-vm1
    HostName ec2-12-34-56-78.compute-1.amazonaws.com
    User ubuntu
    IdentityFile ~/.ssh/aws-east-vm1
```

## Tools

### `ssh-setup` - Initial Key Setup (Interactive)

For first-time setup of a new remote host. Requires password authentication.

```bash
# Generate key + copy to server + verify
ssh-setup linode --generate

# With Ghostty terminfo
ssh-setup linode --generate --terminfo

# Existing key (just copy)
ssh-setup linode --terminfo
```

**What it does:**
1. Generates ed25519 key at `~/.ssh/{host}` (if `--generate`)
2. Updates `~/.ssh/config` with host block
3. Copies public key via `ssh-copy-id` (prompts for password)
4. Verifies passwordless connection works
5. Installs Ghostty terminfo (if `--terminfo`)

### `dabootstrap` - Ongoing Maintenance (Automated)

For subsequent runs on machines with keys already authorized. Runs without interaction.

```bash
dabootstrap
```

**SSH-related actions:**
- Installs Ghostty terminfo on all hosts in `SSH_HOSTS`
- Skips unreachable hosts gracefully
- No password prompts (requires keys already set up)

### Configuration

In `~/.config/.damachine`:
```bash
# Space-separated list of SSH hosts for terminfo setup
SSH_HOSTS="linode aws-east-vm1 raspberry-pi"
```

## Workflow

### New Remote Server

```bash
# 1. Add to SSH config (or let ssh-setup create it)
vim ~/.ssh/config

# 2. Generate and copy key
ssh-setup myserver --generate --terminfo

# 3. Add to dabootstrap for future maintenance
echo 'SSH_HOSTS="linode myserver"' >> ~/.config/.damachine
```

### New Local Machine

```bash
# 1. Clone dotfiles
git clone ... ~/.config

# 2. For each server, copy existing key or generate new one
ssh-setup linode --generate --terminfo

# 3. Run bootstrap for everything else
dabootstrap
```

### Adding Machine to Existing Server

If you have a new laptop and want to add it to a server that already has keys from other machines:

```bash
ssh-setup linode --generate --terminfo
```

The server's `authorized_keys` will have multiple entries:
```
ssh-ed25519 AAAA... r@macstudio→linode
ssh-ed25519 AAAA... r@macbook→linode
```

## Security Considerations

### Why Per-Host Keys?

1. **Revocation granularity** - Compromised key only affects one server
2. **Audit trail** - `authorized_keys` shows which machines have access
3. **Rotation** - Can rotate keys for one server without touching others

### Key Algorithm

Using ed25519:
- Smaller keys (256 bits vs 2048+ for RSA)
- Faster operations
- Modern and secure
- Widely supported (OpenSSH 6.5+)

## Troubleshooting

### "Permission denied (publickey)"

Key not copied or wrong IdentityFile in config:
```bash
# Verify key exists
ls -la ~/.ssh/linode*

# Check config points to right key
grep -A3 "Host linode" ~/.ssh/config

# Re-copy key
ssh-setup linode
```

### Terminal colors broken over SSH

Ghostty terminfo not installed:
```bash
# Install manually
infocmp -x xterm-ghostty | ssh linode tic -x -

# Or via ssh-setup
ssh-setup linode --terminfo

# Or run dabootstrap (if key already works)
dabootstrap
```

### "Host not found in ~/.ssh/config"

Add the host block manually:
```
Host myserver
    HostName 1.2.3.4
    User myuser
    IdentityFile ~/.ssh/myserver
```

---

*Document created: 2025-12-24*
*Based on ssh-setup and dabootstrap implementation*
