# L8 effort per role: audit against measured data (report only, no change)

2026-10-05. Sources: dot-claude/agents/*.md frontmatter and dot-claude/hooks/agent_effort.json at main 7d12c58;
T/.claude-work/stage4-measure/csv/h4_effort_by_type.csv (5 frozen sessions, install a22c5b4); docs
platform.claude.com prompting-claude-opus 5.5 "Calibrate effort" and prompting-claude-sonnet 5.5 "Calibrate effort".

## Consistency (verified)
- All 42 measured types ran at exactly the model and effort their frontmatter sets today: no drift since a22c5b4.
- agent_effort.json (/override-agent table) equals the frontmatter effort for every (type, own model) pair of the 52
  subagent types (blackcat is the main thread and has no row, as designed).
- Unmeasured types (no runs in the 5 sessions): biochem-, dl-, embedded-, game-, hpc-, mlx-, mobile-, robotics-engineer,
  browser-operator, mcp-broker.

## Calibration (not identifiable)
Effort is fully confounded with agent type (no type ran at two levels), so no effect of effort on turns, cost or
quality can be estimated; MEASURE.md row 4 bounds the output side only: thinking = 7.8% of list $.
Thinking share of output by level (types, min–max): xhigh 0.36–0.69 (planner 0.69, security-auditor 0.62,
proof-checker 0.48, mathematician 0.39, main-coder 0.36); max 0.67 (ninja-coder, n = 2); high 0.10–0.60
(plan-reviewer 0.60, code-reviewer 0.50, devops 0.49, designer 0.46); medium 0.14–0.32; low 0.02–0.17.

## Against current vendor guidance (docs, 2026-10-05)
- Opus 5.5: default `medium`; "medium matches or exceeds Claude Opus 5 at high"; "Reserve xhigh and max for work where
  you've measured a quality gain"; lowering effort cuts thinking "more reliably than prompt instructions do".
  Stack: 26 Opus types at high, 5 at xhigh (main-coder, mathematician, planner, proof-checker, security-auditor),
  1 at max (ninja-coder). None has a measured quality gain on record.
- Sonnet 5.5: agentic work starts at medium, high for harder or longer tasks: verifier, data-engineer and
  devops-engineer at high, coder/test-engineer at medium are in line.

## Finding
The settings are internally consistent and match what ran, but none is calibrated: the levels above Opus 5.5's
default are unmeasured choices. The highest-leverage candidates for the effort A/B (already an open ASK USER in
STAGE4.md) are the high-thinking reviewers and planners (planner xhigh, security-auditor xhigh, plan-reviewer and
code-reviewer high) and claude-code-engineer high (13.9% of all $ alone in the o2s table). No recalibration made.
