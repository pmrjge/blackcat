# L7 paid A/B: "minimum first" + anti-overthinking wording (proposal, not run)

Status: NOT RUN. Needs the user's consent (paid runs, and `install.sh` into two throwaway config dirs is the user's step).
Date: 2026-10-05. Arms: A = main `7d12c58`; B = branch `s4-l7-l10` (rules line "Minimum first…", main-coder step 1,
two duplicate lines removed). Nothing else differs (models, effort, tools, skills, hooks identical: `git diff 7d12c58
s4-l7-l10 --stat` touches only dot-claude/rules/claude-agent-stack.md and three agent bodies).

## Question
Does B cut cost per subagent run (turns, output + thinking tokens, list $) without lowering task quality?
Primary quality: non-inferiority, margin −5 pp pass rate. Primary cost: paired ratio of list $ per run.

## Why paid
The change is behavioural; no frozen transcript can show it. Docs (platform.claude.com, prompting-claude-sonnet 5.5,
"Steer initiative and scope"): a stop-and-report instruction "cut session cost by about a third, with no change in
quality" at `max` on Sonnet 5.5; prompting-claude-opus 5.5 "Calibrate effort": lowering effort reduces thinking
"more reliably than prompt instructions do". So the expected effect is on actions (extra reads, rounds, additions),
not on thinking per turn; both are measured.

## Setup (identical for both arms)
1. User step: install each arm into its own config dir from a clean checkout of the arm's commit:
   `CLAUDE_CONFIG_DIR=$TMPDIR/ab-A ./install.sh` (at 7d12c58) and `CLAUDE_CONFIG_DIR=$TMPDIR/ab-B ./install.sh`
   (at s4-l7-l10), same stack.env, same Claude Code version (record `claude --version`; abort if it changes mid-run).
2. Fixture repos: one git repo per task at a pinned commit, copied fresh per run (`git worktree add` from the pinned
   commit into `$TMPDIR/ab/<arm>/<task>/<rep>`); hidden graders live outside the copy.
3. Driver (one run = one fresh session, persistence on so h4 scripts can read the transcript):
   ```sh
   CLAUDE_CONFIG_DIR=$TMPDIR/ab-$ARM claude -p --agent blackcat --output-format stream-json --verbose \
     --max-budget-usd $CAP --max-turns 60 "@$TYPE $(cat tasks/$TASK.md)"
   ```
   BlackCat rule 1 dispatches the prompt verbatim to `$TYPE`, so the target runs as a real subagent with the rules
   loaded (the case L7 targets). `$CAP` = 3 × that type's measured median run $ (below).
4. Order: all 2 × 20 × 3 runs in one randomized interleaved schedule (seed 20261005), one run at a time, same day;
   never two runs on one GPU/Mac job. Each run starts with a cold prompt cache per arm only by chance; cache reads
   are recorded and $ is reported both as billed (list) and cache-normalized.

## Task suite (20 tasks, weighted by measured spend, MEASURE.md h4_effort_by_type)
| Type | n | Task kind | Grader (deterministic first) |
|---|---|---|---|
| claude-code-engineer | 4 | add/fix a hook, agent field, settings key, skill description | lint_agents + pytest subset + a planted-typo check |
| main-coder | 4 | multi-file bug fix / small feature in an unfamiliar repo | hidden acceptance tests |
| code-reviewer | 3 | review a diff with 2–3 seeded defects | recall of seeded defects; false-positive count |
| coder | 3 | script or one-file fix | hidden tests |
| data-scientist | 2 | analysis with a known answer (simulated data) | numeric answer within tolerance |
| planner | 2 | plan for a task with a known pitfall | rubric: pitfall named, owners valid (LLM judge on Sonnet, calibrated on 6 human-graded plans) |
| verifier | 2 | verify a build with one hidden regression | regression found (binary) |
Each task also records "unrequested additions": files changed outside the expected set (deterministic).

## Metrics (per run, from the transcript with `h4_extract.py` + `h4_tokens.py`, out_lb correction as MEASURE §1.3)
Primary: pass (0/1 or recall); list $ of the run tree (target + its children). Secondary: turns, tool calls, output and
thinking tokens, spawns, wall time, STATUS clean/partial share, unrequested additions, hand-back chars.

## Analysis (pre-registered)
- Pair by task; per task average the 3 replicates per arm.
- Cost: mean paired log2(B/A) over tasks, percentile bootstrap over tasks (B = 10,000, seed 20261005), 95% CI.
- Quality: paired difference in pass rate, bootstrap CI; B is non-inferior iff the lower 95% bound > −5 pp.
- Decision: adopt B iff non-inferior AND cost CI upper bound < 0; keep A if the quality bound fails; otherwise
  (non-inferior, no cost effect) drop the L7 wording and keep only the behaviour-neutral L10 trims (the L7 line
  costs ~+170 chars on every spawn that loads the rules).
- Power (assumption, unverified: SD of log cost within a task ≈ 0.8, from the spread of per-type medians): 20 tasks ×
  3 reps detects a cost change of about ±35% at 80% power. A pilot estimates the real SD; if the MDE exceeds 35%,
  extend to 40 tasks (option 2) before the main run.

## Budget (list prices, MEASURE.md §1.2; list price is not the bill, unverified)
Per-run medians (h4_effort_by_type.csv): claude-code-engineer $5.68, main-coder $4.26, code-reviewer $1.70, coder $0.25,
data-scientist $5.34, planner $3.44, verifier $1.15; BlackCat relay ≈ $0.10/run (assumption).
- One arm × one replicate of the suite: 4·5.68 + 4·4.26 + 3·1.70 + 3·0.25 + 2·5.34 + 2·3.44 + 2·1.15 + 20·0.10
  = $67.47; × 1.3 for children spawned by the targets = **$87.7**.
- Pilot: 5 tasks (one each of cce, main-coder, code-reviewer, data-scientist, coder) × 1 rep × 2 arms ≈ **$45**.
- Main run (option 1): 20 tasks × 3 reps × 2 arms = 6 × $87.7 ≈ **$526**. Total with pilot ≈ **$571**
  (range 0.5×–1.5× for benchmark tasks being smaller or larger than organic ones: **$285–$855**).
- Option 2 (40 tasks × 3 reps): ≈ **$1,100** (+ pilot).
- Hard stops: `--max-budget-usd` per run (3 × type median); abort the whole study at **$650** (option 1) spent,
  reporting what ran.

## What the user must decide (ASK USER)
Run option 1 (≈ $571 list), option 2 (≈ $1,100), or not at all; and run `install.sh` into the two config dirs
(or authorize it). No run happens before that answer.
