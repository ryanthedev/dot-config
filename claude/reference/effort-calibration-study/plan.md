# Plan v2 — cheap, decisive, ships something regardless

## What changed since v1 (from the Fable critiques)
- The pre-flight proved nothing conclusively (underpowered n=30; confound story unsupported; my "negative" overstated).
- KEY INSIGHT: the estimator was REPO-BLIND, but the deployed skill estimates from INSIDE the repo. The worst
  misses were bounded questions whose effort lived in hidden repo state that no request text carries
  (584ca043: "any read/write adapters?" -> 128 tool calls / 30 min via exploration). So text-only tests
  measure the wrong construct.
- Point-estimating minutes is hard and maybe not the product anyway. The ORIGINAL problem was anchoring on
  human-calendar time when weighing tasks — that can be fought with reference-class data, no per-task predictor.

## Objective
Two cheap outputs:
  (1) A SHIPPABLE anti-anchoring artifact from the ~200 real sessions (needs no feasibility win).
  (2) A directional feasibility signal on whether a REPO-AWARE estimator beats a blind one — the right construct.

## Experiment 1 — Repo-aware recon feasibility probe (the right construct, cheap)
- Sample: from the 30 (extend toward the clean 219 if needed), select sessions whose `cwd` STILL EXISTS on disk
  AND whose opening request is informative (drop the 5-6 content-free openers: "l", bare /plugin, /effort).
  Target n=12-15 spanning the size range. If <8 have a live cwd -> Experiment 1 is INFEASIBLE (see gates).
- Procedure: one estimator agent per session (sonnet). Input = opening request + the repo path. It may do BOUNDED
  recon (ls/read/grep/git, hard cap ~12 tool calls) to understand scope, then predict tool_calls / active_min /
  tshirt for how the ORIGINAL task would have gone. It does NOT read the session transcript.
- Compare: recon-aware estimates vs the existing blind Round-1 estimates vs actuals.
- Metrics: pairwise ranking accuracy on active_min + tool_calls (with bootstrap 95% CI); Spearman with CI.

### PRE-DECLARED decision rule (fixes the "no threshold" critique)
- FEASIBLE / worth building the fuller predictor IF: recon-aware active_min pairwise-rank >= 65% AND its
  bootstrap CI lower bound > 50% AND it beats blind Round-1 by >= 8 points on the SAME sessions.
- Otherwise INCONCLUSIVE-or-NEGATIVE: report as such; the calibration artifact (Exp 2) becomes the deliverable.
- Declared BEFORE running. n is small so CIs will be wide — that itself is a reportable outcome, not massaged away.

### Known confounds to report honestly (not hide)
- Repo DRIFT: the repo today may already CONTAIN the session's finished work -> recon could reverse-infer effort
  (optimism leak). Deployment repos do NOT contain the result. Note as a caveat; it biases toward FEASIBLE, so a
  NEGATIVE result is trustworthy, a POSITIVE is soft.
- Recon tool-calls are separate from the predicted task tool-calls (instruct explicitly).

## Experiment 2 — Calibration / reference-class table (ships regardless, cheap)
- Over the full clean cli set (~200; entrypoint==cli, assistant_msgs>0, user_turns>=2, drop probes):
  compute p10/p50/p90 of active_min and tool_calls, OVERALL and split by a cheap a-priori task-type inferred
  from the OPENING REQUEST ONLY (one sharded LLM pass over ~200 short opening requests — fits context easily,
  no giant-transcript reads). Types e.g.: research/Q&A, debug, feature-build, refactor, config, plugin/agent-work.
- Deliverable = a table the skill can cite: "tasks of type T empirically run ~p50 (p10-p90) active-min / tool-calls."
  This directly counters human-calendar anchoring with the user's OWN history.
- Ship condition: types must actually SEPARATE (their median active-min must differ materially); if all types
  collapse to the global median, the table adds nothing -> say so.

## Free fixes folded into the report
- Corrected rescore: mean-APE AND median-APE, the +0.16 multi-turn slice, cleaned-sample Spearman, always-L
  within-1 baseline (87%). Present the honest, non-selective numbers.

## Validation (cheap, self-run)
- Leakage check on task-type labels: types derived from opening request only, never from outcome/length.
- Sanity: recon agents did NOT read the transcript (check their tool logs don't touch ~/.claude/projects).
- Report all CIs; do not declare a null the power can't support.

## Feasibility gates (PING the user only for these)
- Exp 1: fewer than 8 sampled sessions have a live cwd on disk -> repo-aware construct can't be tested cheaply.
- Exp 2: the ~200-session opening-request labeling can't be done (data missing) — unlikely.
- Any hard tooling failure that blocks both experiments.

## Cost budget (go cheap)
- Deterministic scripts: free. Task-type labeling: ~5 sonnet agents. Recon estimator: ~12-15 sonnet agents.
  Total <= ~20 sonnet agents. No opus, no worktrees.

## Deliverable to the user
One consolidated report: corrected numbers, Exp-1 feasibility verdict (with CIs + caveats), Exp-2 calibration
table, and a clear recommendation (build the predictor / ship calibration-only / stop).
