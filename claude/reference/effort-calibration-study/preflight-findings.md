# Pre-flight ceiling test: result + interpretation (FOR PROBING)

## The project (one paragraph)
Build a calibration model + skill so an LLM (Claude Code) can estimate, BEFORE starting, how long a
coding task will take IT to complete — fighting the bias where LLMs anchor time estimates on human-calendar
durations from training data. Prior art confirms: LLMs overshoot task duration 4-7x by anchoring on task
text, not their own speed. We have ~200 genuine interactive Claude Code session transcripts (sifted from
12,916) on one power user's ~30 repos.

## Why we ran a cheap pre-flight FIRST
A Fable what-if probe found the planned cost model (size -> time) is partly an accounting identity
(tautology): it fits time from latencies measured off the same timestamps that define time. The REAL,
non-tautological question is finding #3/#5 from that probe: can an LLM predict the size proxy (tool_calls,
files_touched, minutes) from a task DESCRIPTION at all? If not, the skill relocates the bias rather than
fixing it, no matter how good the cost model. So we tested that ceiling directly and cheaply before
building the full pipeline.

## The pre-flight design
- 30 sessions, stratified across active-time (0.6 -> 136 active-min), from the clean cli set (n=219).
- For each: extracted the OPENING human request (what the estimator sees) separately from ACTUALS
  (tool_calls, files_touched, active_min, tshirt) computed deterministically from the transcript.
- 5 blind estimator agents (sonnet), each saw ONLY opening requests, predicted the four metrics.
  Neutral framing — NOT told this was a bias experiment. t-shirt bands: S<5min, M 5-20, L 20-60, XL>60.

## The result (n=30)
| metric | blind-estimate vs actual | null baseline | verdict |
|---|---|---|---|
| tool_calls | Spearman 0.04 | - | no signal |
| files_touched | Spearman 0.20 | - | faint |
| active_min | Spearman 0.15 | - | no signal |
| active_min MAPE | 84% | 67% (always guess median) | WORSE than guessing |
| t-shirt exact | 30% | 33% (always guess "L") | WORSE than guessing |
| t-shirt within-1 band | 60% | - | modest |

Biggest misses are all HIGH-TURN sessions (the estimator massively UNDER-predicts):
- 59e8857d: 36 human turns, 136 min actual -> predicted 15 min
- d03bba19: 7 turns, 258 tool calls -> predicted 1 min
- 16edcb97: 17 turns, 99 min -> predicted 6 min
Single-task subset (<=3 human turns): Spearman -0.02, but n=7 (too small).

## MY INTERPRETATION (this is what I want probed)
Claim A: The negative is NOT fatal to the project; it's dominated by the session-not-task confound.
  The opening request cannot predict a 36-turn session because that measures "how long the human keeps
  going," not "how big is this task." We already decided to fix this via task-grain segmentation.
Claim B: The decisive next step is a TASK-GRAIN ceiling test — segment each session into tasks, take each
  task's triggering request, predict that task's effort bounded to that task's own turns, re-score. If
  that is ALSO flat, we abandon the pipeline.
Claim C: This pre-flight was worth running even though negative — it cost ~1 agent batch and reshaped the
  gate.

## Honest caveats already noted
- n=30, one model (sonnet proxy for the real skill host), a minimal estimator prompt.
- Result contradicts the literature's overshoot direction (here the estimator UNDER-shot) — possibly
  framing/model dependent.

## Data files (same scratchpad dir)
- ceiling_full.json (requests + actuals), predictions_0..4.json, ceiling_score.py output above.
