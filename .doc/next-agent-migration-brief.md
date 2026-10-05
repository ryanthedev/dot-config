# Brief for the agent on the NEW machine

You are picking up a machine migration. Ryan moved from a Mac where everything below was verified on 2026-09-11. Read this before touching anything. The companion file `machine-migration-backup.md` (same dir) is the full inventory with evidence; this file is the order of operations.

## Two decisions Ryan made on 2026-09-11 (do not silently reverse)

1. **The primary grug brain has no git remote, deliberately, for now.** He chose tarball-only for the move. That means **`migration-secrets-2026-09-11.tgz` is the sole off-machine copy** of `~/.grug-brain/memories` (122 md files + full git history, both verified in the archive). Treat it as precious until it's restored and verified on the new machine. Offer to create the remote *after* the move succeeds; don't create one unasked.

   The two archives are `migration-secrets-2026-09-11.tgz` (79MB, has `.ssh` — **never** put this on Google Drive or any cloud share) and `migration-config-2026-09-11.tgz` (18MB, has `zsh/.env` and `aerospace/.env` — also secret-bearing).
2. **`ryan-voice/references/voice-profile.md` is intentionally excluded from the Google Drive bundle.** It contains verbatim personal/medical Slack samples and Drive is Carvana-managed. It rides in the offline tarball only. If you're restoring ryan-voice and the profile is missing, get it from the tarball or USB — do not re-upload it to Drive, and do not reconstruct it from memory.

## Ground truth you should not re-derive

- Dotfiles repo: `git@github.com-dotconfig:ryanthedev/dot-config.git` → `~/.config`. It uses a **whitelist-style `.gitignore`** (`/*` then `!dir/`), so a lot of real config is deliberately untracked. Don't assume "not in git" means "not needed."
- Bootstrap is `make` in `~/.config` fronting `~/.config/bin/dabootstrap`. Targets: `all, check, symlinks, services, cleanup, thegrid, terminfo, claude, status`.
- Memory system is **grug-brain** (MCP plugin `grug-brain@rtd`). Layout lives in `~/.grug-brain/brains.json`. Auto memory is off by design.
- grug's `grug.db` is a **derived index** — it re-syncs incrementally from markdown file mtimes on startup. Never restore it from backup; restore the markdown and let it rebuild.

## Order of operations

1. **SSH first.** Nothing clones without `~/.ssh` — specifically the `github.com-dotconfig` Host alias and its key. Restore from the offline tarball/USB, `chmod 600` the keys, then `ssh -T git@github.com-dotconfig` to verify.
2. **Homebrew.** Install brew, then `brew bundle --file=~/.config/Brewfile`. That file **was generated 2026-09-11** (11 taps, 26 formulae, 5 casks) and is in `migration-config-2026-09-11.tgz`; it may also be committed to the repo. `make check` fails until brew is sane. If the Brewfile is somehow missing, the custom taps to re-add by hand are `ryanthedev/mss`, `felixkratz/formulae`, `atlassian/acli`, `fluxcd/tap`, `controlplaneio-fluxcd/tap`, `hashicorp/tap`, `jackielii/tap`, `mike-engel/jwt-cli`, `ngrok/ngrok`, `powershell/tap`.
3. **Clone `~/.config`**, then restore the untracked-but-needed dirs from `migration-config-2026-09-11.tgz`: `app-launchers/`, `stele/`, `scripts/`, `containers/`, `raycast/`, `git/`, `packer/`, `uv/`, `ado/`, `NuGet/`, `sudo`, `aerospace/aerospace.toml`, `thegrid/*.local.yaml`, `nvim/lazy-lock.json`, and the two `.env` files (`zsh/.env`, `aerospace/.env`).
4. **Do NOT restore auth caches.** Re-authenticate instead: `gcloud`, `gh`, `acli`, `github-copilot`, `configstore`, and `~/.claude/.credentials.json`. Copying these forward causes confusing half-broken auth.
5. **grug-brain.** Restore `~/.grug-brain/brains.json` and `~/.grug-brain/memories/` from the tarball (or clone the remote, if step 6 of the *old* machine's checklist got done). Then `com.grug-brain.server.plist` → `~/Library/LaunchAgents/` and `launchctl bootstrap`. Let the index rebuild itself.
6. **Claude config — READ THIS, there is a known trap.** See next section.
7. `make all`, then `make status` to confirm services.

## The Claude config trap

On the old machine, `~/.claude/CLAUDE.md` and `~/.claude/settings.json` were **regular files, not symlinks**. `dabootstrap` (line ~421) is supposed to `ln -sf` `CLAUDE.md` from `~/.config/claude/`, but that never took effect, so the two copies **drifted in both directions**:

| | Live `~/.claude` (was in effect) | Repo `~/.config/claude` |
|---|---|---|
| `CLAUDE.md` | Correct grug-brain memory section | **Stale Engram** section, but **has** the newer "Effort & Time Estimates" block that live lacks |
| `settings.json` | jjira/herderp perms, `model: opus[1m]` | engram/thegrid/craft perms, `model: claude-opus-4-8[1m]`, extra `ask` block |

**The merged, correct version is what you want.** If the repo copy was reconciled before the move, just `make claude` and verify `~/.claude/CLAUDE.md` is now a symlink. If it wasn't, merge by hand — take the grug-brain memory section from the live copy and the Effort & Time Estimates block from the repo copy — write the result to `~/.config/claude/CLAUDE.md`, then `make claude`.

Verify with `ls -la ~/.claude/CLAUDE.md` — it must show `->`. If it's a regular file, the drift will silently start over.

## Things that are NOT backed up by any repo

- `~/.claude/skills/ryan-voice` — voice skill built from real Slack messages. **Irreplaceable.** Not in git, not symlinked to anything (`dabootstrap` links skills from an installed *skill repo's* `skills/` dir, not from `~/.config/claude/`, which has no `skills/` dir). Restore from tarball.
- `~/.claude/skills/siren` — 4.2MB, mostly workspace artifacts; the skill itself is also available as `siren.skill`. Lower priority.
- `~/.grug-brain/memories/recall.md` and `local/` — excluded by that dir's own `.gitignore`, so they never ride along even when the brain is in git.
- `~/grug-brain.mcp/memories/` — 21 md files (`azure/`, `carvana-migration/`, `github-actions/`), untracked, last touched March 2026, not referenced by `brains.json`. Probably superseded; skim before discarding.

## Known-broken things to prune, not restore

- `settings.json` → `enabledPlugins` has `svelte-foundations@/Users/r/repos/svelte-foundations.skill`. That's a **local path under `/Users/r/`, not `/Users/RHayden/`**, and the directory exists nowhere on the old machine. It's a dead reference — delete the entry rather than trying to satisfy it.
- `~/grug-memories` (old machine) — has a git remote but is a **stale, unrelated** memory set (last commit 2026-03-28, different categories than the live brain). Do not mistake it for the real brain, and do not merge it in without asking Ryan.
- `~/.grug-brain/docs` was 1 commit **ahead** of its remote, meaning the `syncInterval: 60` auto-sync was not keeping up. Check `git log @{u}..HEAD` on each synced brain (`docs`, `hive`) after restore and push anything stranded.

## Plugins / marketplaces

All three marketplaces are GitHub-sourced and re-install cleanly: `obra/superpowers-marketplace`, `anthropics/claude-plugins-official`, `ryanthedev/rtd-claude-inn` (the `rtd` marketplace, `autoUpdate: true`, which supplies grug-brain, claude-mux, oberskills, penman, code-foundations, design-for-ai, judge-fable, herderp, what).

## Check `whoami` before restoring

Several files hardcode the absolute path `/Users/RHayden/`: `~/.grug-brain/brains.json` (every brain `dir`), `com.grug-brain.server.plist`, and `settings.json` → `statusLine.command` (`/Users/RHayden/.config/claude/statusline.sh`). If the new machine's short username differs, grug won't start and the statusline will silently fail. Run `whoami` first; if it isn't `RHayden`, plan a `sed` pass over those three before step 5.

## Ask Ryan before you do these

- Creating the GitHub remote for `~/.grug-brain/memories` if it still doesn't have one (it had **none** as of the sweep — 122 files, 105 commits, local only). It must be a **new** repo; the existing `grug-memories.git` has unrelated history and will collide.
- Merging `~/grug-memories` content into the live brain.
- Anything that deletes from the old machine.
