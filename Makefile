# dabootstrap Makefile - Frontend for dotfiles bootstrap
# Usage: make [target]

SHELL := /bin/bash
BOOTSTRAP := $(HOME)/.config/bin/dabootstrap

.PHONY: all check symlinks services cleanup thegrid terminfo claude status help
.PHONY: cleanup-aerospace cleanup-yabai cleanup-skhd

# Default target
all:
	@$(BOOTSTRAP) all

# Check prerequisites (homebrew, mss, etc.)
check:
	@$(BOOTSTRAP) check

# Symlink scripts to ~/.local/bin
symlinks:
	@$(BOOTSTRAP) symlinks

# Generate and install launchd services
services:
	@$(BOOTSTRAP) services

# Remove all legacy window managers
cleanup: cleanup-aerospace cleanup-yabai cleanup-skhd

cleanup-aerospace:
	@$(BOOTSTRAP) cleanup-aerospace

cleanup-yabai:
	@$(BOOTSTRAP) cleanup-yabai

cleanup-skhd:
	@$(BOOTSTRAP) cleanup-skhd

# Setup theGrid (dev or brew based on .damachine)
thegrid:
	@$(BOOTSTRAP) thegrid

# Install Ghostty terminfo on remote hosts
terminfo:
	@$(BOOTSTRAP) terminfo

# Setup Claude Code skills
claude:
	@$(BOOTSTRAP) claude

# Show service status
status:
	@$(BOOTSTRAP) status

# Help
help:
	@echo "dabootstrap - macOS dotfiles bootstrap"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@echo "  all       Run full bootstrap (default)"
	@echo "  check     Check prerequisites"
	@echo "  symlinks  Symlink bin scripts to ~/.local/bin"
	@echo "  services  Generate and install launchd services"
	@echo "  cleanup   Remove all legacy window managers"
	@echo "  thegrid   Setup theGrid"
	@echo "  terminfo  Install Ghostty terminfo on remote hosts"
	@echo "  claude    Setup Claude Code skills"
	@echo "  status    Show service status"
	@echo ""
	@echo "Cleanup targets:"
	@echo "  cleanup-aerospace  Remove AeroSpace"
	@echo "  cleanup-yabai      Remove yabai"
	@echo "  cleanup-skhd       Remove skhd"
