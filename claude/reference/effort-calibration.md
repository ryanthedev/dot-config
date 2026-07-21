# Claude Code task-effort calibration — your own history (n=219 real interactive sessions)

Use this to fight human-calendar anchoring. When you catch yourself thinking "this is a 2-day refactor,"
that's the wrong unit. Here is what your real tasks actually cost in agent active-time.

## The one rule that matters most
**Session length ≈ how many turns you take, NOT the task type.**
A single, well-scoped ask runs **~5–9 active-minutes** and **~5–15 tool calls** — for *every* task type
(research, debug, feature, config alike). Sessions only balloon when the work turns into back-and-forth.

| If you expect… | Active-time | Tool calls |
|---|---|---|
| A single exchange (one ask, little back-and-forth) | ~5–9 min | ~5–15 |
| A typical multi-turn session | ~30 min (median) | ~50–70 |
| A long collaborative session (p90) | ~100–115 min | ~180+ |

## Condition on REPO, not task-type
Task-type from your phrasing does **not** predict effort (≈chance). The repo does (weak but real):

| Repo | Median active-min | p10–p90 |
|---|---|---|
| upublish-website | 68 | 34–124 |
| design-for-ai | 47 | 8–148 |
| code-foundations | 45 | 7–201 |
| sdd | 37 | 3–109 |
| engram | 33 | 4–135 |
| .config | 17 | 7–31 |
| upublish | 10 | 2–107 |

## Sprawl flag (cheap, a-priori)
Openers that are **pointers/resumes** ("pick back up on…", "necro the previous session", "get up to speed")
or **bare slash-commands** reliably become **large** sessions (median ~40 min). Opener *shape* predicts
sprawl better than opener *content*.

## What this card is NOT
Per-task point estimation does not work from a-priori info (no feature beat the global-median baseline).
This is a reference class, not a predictor: it narrows the range and kills the human-calendar anchor —
it does not tell you a specific task's minutes.

_Source: 219 clean `entrypoint==cli` sessions, deterministic actuals, leave-one-out + session-clustered
bootstrap. Session-level (not task-level) numbers; the tail is inflated by multi-turn persistence._
