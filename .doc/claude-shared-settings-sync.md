# Agent brief: sync this machine to the shared Claude settings

Paste this file into a Claude Code session on any machine that pulls `~/.config`
after commit `e727301` (2026-10-05). It is written for the agent doing the work.

## What changed upstream

- `claude/settings.json` is gone. It was a full snapshot of one machine's
  settings, and copying it between machines kept breaking things (usernames,
  work-only MCP servers, herdr-only hooks).
- `claude/settings.shared.json` replaces it. It holds only the settings that
  should be the same everywhere. It is **layered** on top of each machine's own
  `~/.claude/settings.json` at launch through `claude --settings <file>`:
  - single values in the shared file win (UI prefs, statusLine,
    outputStyle, editorMode, ...);
  - lists merge (permissions allow/deny/ask, plugins, marketplaces).
- Nothing in the repo writes `~/.claude/settings.json` any more. That file is
  per-machine and stays where machine-specific things live (work MCP servers,
  local hooks, model choice, plugin paths).
- `zsh/.zshrc` defines `claude` and `claudew` aliases that pass `--settings`.
- `make claude` symlinks `~/.claude/output-styles` to `claude/output-styles`
  (needed because the shared file sets `outputStyle: "Skimmable"`).
- Permission changes in the shared file: the no-op `Bash(rsync * *:*)` deny rule
  is gone (it printed a startup warning and never matched), and `Bash(pkill *)`
  plus `Bash(launchctl bootout*)` are **ask** rules, so they prompt.

## Steps

1. `cd ~/.config && git status` — stop and report if there are uncommitted
   changes; do not stash or discard them without asking the user.
2. `git pull`. If it conflicts, keep this machine's machine-specific values
   (paths, work servers) and the upstream shared-settings layout; ask the user
   about anything else.
3. Run `make claude`. If it reports it moved an existing
   `~/.claude/output-styles` aside, tell the user which styles were in the backup.
4. Open a **new** shell (aliases load at shell startup) and confirm
   `alias claude` prints `command claude --settings ~/.config/claude/settings.shared.json`.
   If `~/.zshrc.local` redefines `claude`, it must extend the base alias with
   `"$aliases[claude] ..."`, not replace it.
5. Compare `~/.claude/settings.json` against `claude/settings.shared.json`:
   - Remove from the local file any value the shared file now owns **only if it
     is identical**; leave differing values and tell the user which ones the
     shared file will override.
   - Check the `env` block on both. It is unverified whether `--settings`
     merges `env` per key or replaces the whole object; if the local file has
     env vars the shared file lacks, start `claude` and confirm they are still
     set (e.g. ask it to run `env | grep <NAME>`).
   - Leave `Bash(pkill *)` / `Bash(launchctl bootout*)` out of the local
     **deny** list; a deny rule would override the shared ask rule.
6. Verify: `cd ~ && claude -p "say ok" </dev/null 2>&1` prints `ok` with no
   "Permission … rule" warnings, and the statusline script path
   `~/.config/claude/statusline.sh` exists.
7. Report to the user in a short table: what changed, what was overridden,
   anything left for them to decide. Do not commit or push unless asked.
