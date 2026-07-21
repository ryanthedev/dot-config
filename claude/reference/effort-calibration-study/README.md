# Effort calibration study (2026-07-19)

How `claude/reference/effort-calibration.md` was derived. Kept so the numbers are
reproducible rather than folklore.

## The question

Can an LLM predict, a-priori, how much effort a coding task will cost *it* — before starting?
Motivation: Claude anchors estimates on human-calendar durations from training data
("a 2-day refactor"), which is the wrong unit for agent work.

## The answer

No — not as a point estimate. **Per-repo base rate is the only a-priori feature that beat
chance at ranking** (60% pairwise on tool calls), and *no* feature beat the global-median
baseline at predicting actual minutes. Task-type inferred from the request wording is
literally chance (49%).

The dominant effect is a confound, not a task property: **session length tracks human turn
count, not task type.** A single-exchange task of any type runs ~5–9 active-min.

So the deliverable is a reference class (the calibration card), not an estimator.

## Reproduce

Run in order from any scratch directory — they read `~/.claude/projects/**/*.jsonl` directly.

```sh
python3 mine_sessions.py    # 12,916 transcripts -> sessions.csv (deterministic actuals)
python3 enrich_clean.py     # -> enriched.json: 219 clean entrypoint==cli sessions
python3 freebaseline.py     # leave-one-out + session-clustered bootstrap over enriched.json
```

The intermediate data (`sessions.csv`, `enriched.json`) is deliberately **not** committed —
it carries local repo paths and is regenerable from the scripts above.

Definitions that matter: `active_sec` sums inter-message gaps with idle breaks excluded, so
it is agent active-time, not wall-clock session span. "Clean" = `entrypoint == cli`
(interactive), excluding sdk-cli/sidechain runs.

## Verbatim result (n=219)

```
### target=active_min  (ALL, n=219)   [ranking baseline = 50% chance]
predictor              pairwise          95% CI  spearman
per-repo median (LOO)       57%   [  52%,  61%]      0.20
per-type median (LOO)       49%   [  45%,  54%]     -0.01
request words               55%   [  51%,  60%]      0.15
lowinfo flag (0/1)          41%   [  33%,  49%]     -0.15

### target=tool_calls  (ALL, n=219)   [ranking baseline = 50% chance]
predictor              pairwise          95% CI  spearman
per-repo median (LOO)       60%   [  55%,  64%]      0.29
per-type median (LOO)       49%   [  44%,  54%]     -0.02
request words               54%   [  49%,  59%]      0.12
lowinfo flag (0/1)          39%   [  32%,  47%]     -0.19

### target=active_min  (low-turn <=3, n=55)   [ranking baseline = 50% chance]
predictor              pairwise          95% CI  spearman
per-repo median (LOO)       49%   [  39%,  59%]     -0.02
per-type median (LOO)       44%   [  35%,  54%]     -0.14
request words               64%   [  55%,  72%]      0.40
lowinfo flag (0/1)          47%   [  30%,  65%]     -0.05

### target=tool_calls  (low-turn <=3, n=55)   [ranking baseline = 50% chance]
predictor              pairwise          95% CI  spearman
per-repo median (LOO)       58%   [  48%,  67%]      0.20
per-type median (LOO)       34%   [  26%,  43%]     -0.42
request words               59%   [  49%,  69%]      0.25
lowinfo flag (0/1)          44%   [  25%,  62%]     -0.09

### point-error active_min (all)  MAPE median / mean
null global median :    67% /   224%
per-repo LOO median:    70% /   203%
per-type LOO median:    73% /   221%

### CALIBRATION: per-type session percentiles (types with n>=10)
type               n      active_min p10/50/90    tool_calls p10/50/90
resume-pointer    57     9.6/ 41.9/ 114.8        15/  79/  180
research-qa       53     6.2/ 29.6/  99.2         7/  51/  149
command           43     6.3/ 39.5/ 106.3         5/  69/  206
feature-build     25     2.5/ 26.6/ 201.1         5/  41/  274
other             20     3.3/ 17.2/ 158.9         2/  30/  231
debug             11     4.2/ 22.9/  99.0         7/  52/  145
type median active_min spread: 17.2 -> 41.9 min  (max/min = 2.4x; pre-declared 'separates' if >=2.0x)

### CALIBRATION: per-repo session percentiles (repos with n>=10)
repo                 n      active_min p10/50/90
engram              24     3.8/ 33.3/ 135.3
upublish-website    23    33.6/ 68.2/ 123.7
design-for-ai       21     7.8/ 46.7/ 148.2
.config             16     7.1/ 16.6/  30.8
sdd                 13     3.3/ 36.7/ 108.7
code-foundations    12     7.2/ 45.2/ 201.1
upublish            11     2.4/  9.6/ 106.6

### persistence effect: active_min median, all vs low-turn(<=3), by type(n>=10)
resume-pointer   all_med= 41.9  low-turn_med=  9.2  (low-turn n=9)
research-qa      all_med= 29.6  low-turn_med=  8.4  (low-turn n=19)
command          all_med= 39.5  low-turn_med=  5.9  (low-turn n=5)
feature-build    all_med= 26.6  low-turn_med=  6.7  (low-turn n=10)
other            all_med= 17.2  low-turn_med=  6.1  (low-turn n=7)
debug            all_med= 22.9  low-turn_med=  4.2  (low-turn n=3)
```

## Files

| File | What |
|---|---|
| `plan.md` | The plan actually executed, after a `what-if` probe killed the leaky v1 |
| `preflight-findings.md` | The cheap n=30 LLM-ceiling test run *before* the full pipeline. Negative, and worth it — it reshaped the gate |
| `mine_sessions.py` | Transcript miner → deterministic actuals |
| `enrich_clean.py` | Filter to clean interactive sessions + a-priori features |
| `freebaseline.py` | Leave-one-out ranking + bootstrap CIs + MAPE vs null |

## Two traps this study walked into (both caught before shipping)

1. **Accounting identity.** The original cost model fit time from latencies measured off the
   same timestamps that *define* time. A `what-if` probe caught it; the plan was rewritten.
2. **Leakage.** A planned "recon the repo to predict effort" experiment would have read repos
   containing the sessions' own committed work — any positive result would have been fake.
   Dropped before any agent ran.
