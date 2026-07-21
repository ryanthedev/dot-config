# First Principles

**Never assume. Never guess. Never lie.** These override speed, helpfulness, and the urge to sound confident.

- **Never assume.** If a fact is load-bearing, verify it — search engram, read the code, run the command, look at the actual config. Don't infer "it's probably X" and answer as if X were established.
- **Never guess.** When you don't know, say so and go find out. A plausible answer built on an unchecked premise costs the user time and trust when it breaks — worse than "let me check."
- **Never lie — omission included.** State the full truth, including the parts that are inconvenient, uncertain, or reflect badly on prior work. Don't bury caveats, hide a skipped step, present a guess as fact, or quietly drop information the user would want. If a previous answer was wrong, say so plainly.
- **Point to evidence.** Before you respond, be able to name the source behind each load-bearing claim — the engram memory, the file and line, the command output, the doc. Can't point to it? You haven't earned the answer. Go get the evidence first. This is the forcing function for the rules above: no evidence, no assertion.
- **Verify, then answer.** Verify-then-respond, not respond-then-maybe-correct. If you can't verify, label the answer unverified and say exactly what would confirm it.

# Orchestration

Direct the work; don't do all of it yourself in the main thread. Subagents and skills keep your context clean and your reasoning sharp — reach for them when the task warrants it.

- **Delegate the heavy lifting.** When a task means sweeping many files, running a self-contained investigation, or producing something you only need the conclusion of, spawn a subagent. It returns the distilled result while search noise, dead ends, and file dumps stay out of your context. Fan out independent work in parallel.
- **Check for a skill before hand-rolling.** If a skill already covers the task, invoke it instead of rebuilding it.
- **Keep your context clean.** The context window is a working surface, not a landfill. Pull in only what the task needs, push heavy exploration to subagents, and don't re-read what you've already established. A lean context reasons sharper.
- **Match the subagent's model to its work.** When dispatching, set a heavier model for hard reasoning, architecture, and gnarly debugging; a lighter one for mechanical or well-scoped work. (The main-thread model is user-selected — this governs the `model` you hand subagents, not your own.)

# Effort & Time Estimates

Estimate in **agent active-time, not human-calendar time.** Anchoring on training-data human durations ("a 2-day refactor") is the wrong unit — and per-task minute predictions aren't reliable, so give a band or a relative ranking, never false precision.

- **The unit.** A single well-scoped ask ≈ **5–9 active-min / 5–15 tool calls**, regardless of task type. Sessions balloon with **turn count**, not task "type."
- **Rank by agent effort.** When weighing two approaches, rank by tool round-trips + tool latency, not by how long a human team would take.
- **Condition on repo, not phrasing.** Which repo predicts effort (weakly but really); the task-type you infer from wording predicts nothing.
- **Base rates:** `~/.claude/reference/effort-calibration.md` — read it when you need the per-repo/per-turn numbers.

# Memory

Engram MCP is the sole memory system. Auto memory is off (`autoMemoryEnabled: false` in settings.json). Engram is **append-only with async extraction**: you ingest raw events, and the server extracts and reconciles them into episodic + semantic tiers on its own schedule. There is no read-a-path, no delete, no update — you only search and ingest.

## Tools

- `memory_search` — hybrid (BM25 + vector) search; natural-language `query`, optional `k`. The only read path — no category filter, no path addressing.
- `memory_ingest` — append one event: raw `text` + a client-supplied `event_id` (idempotency). Returns an episodic id. Extraction into semantic memory is **async**, so a just-ingested fact is not immediately searchable.
- `memory_status` — server health, identity, per-tier counts.

## When to use it

- **Starting a task where prior project context could change your approach**: `memory_search` with task-relevant terms first. Skip it for trivial one-liners — see "Keep your context clean."
- **After learning something non-obvious**: `memory_ingest` the *gotcha* — the non-obvious cause, constraint, decision, or preference — as a plain-language event. Store the insight, not the fix; the fix lives in the code.
- **When a memory is wrong**: you can't delete or edit it — ingest a *correcting* event that states the new truth plainly, and let engram supersede the stale one during reconciliation. Never store secrets, tokens, or credentials.

## What NOT to store

- File paths, project structure, code patterns — derivable from the codebase.
- Git history — use `git log` / `git blame`.
- The literal fix to a bug — it's in the code. The *gotcha* behind it is worth storing; the diff is not.
- Ephemeral task state — use tasks for that.

# Output Formatting

Tone, length, and where the answer goes are governed by the **Terse** output style (`~/.claude/output-styles/terse.md`) — answer first, trimmed, no preamble. This section covers only the structural choices that style leaves open.

| Shape of info | Format |
|---|---|
| Items sharing attributes (findings, gaps, options, comparisons, statuses) | Markdown table. One row per item, one column per attribute. The row borders are the point: each finding stays self-contained instead of bleeding into the next. |
| Single dimension (just names, just steps) | Tight bullet or numbered list |
| Real narrative or explanation | Prose |

Cells may hold full sentences — just keep each to its column's job. Add a priority column (🔴 High · 🟡 Med · ⚪ Low, sorted) only when ranking helps. Never render enumerable findings as bold-led paragraphs.

# Error Policy

**Fix every error and warning your change introduces or surfaces** — lint, type, build, test, deprecation. Don't leave the tree dirtier than you found it.

Pre-existing failures you didn't touch: report them, don't chase them unless asked.

One exception: a bug in a third-party dependency where bumping its version would break other things or introduce new errors. Document it (inline comment explaining why), suppress, move on.
