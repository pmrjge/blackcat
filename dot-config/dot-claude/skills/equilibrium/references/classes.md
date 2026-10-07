# Equilibrium classes, predictions, refusals, fallbacks, labels

## Classes
| class | problem | answer kind | reducer | member tools | workdir |
|---|---|---|---|---|---|
| PF | proof in Lean (statement + lake project) | checkable | verify-then-select: first passer of the checker in seeded order; repair round if none | Read Write Edit Bash | `.claude-work/eq/<run>/m<i>/` |
| CP | code patch with a public test command | checkable | as PF | + Glob Grep | git worktree per member |
| CR | code review | finding set | cluster (file, line +-3), accept support >= 2, singles verified | Read Glob Grep Bash | git worktree per member |
| RS | research question | discrete | plurality on labelled answers | Read Grep Glob | none or `m<i>/` |
| ES | numeric estimate | numeric | median of ln | Read | none or `m<i>/` |
| DS | design | long-form | `plan-reviewer` ranks twice, Borda, select never fuse | none | none or `m<i>/` |
| OE | open-ended writing/analysis | long-form | as DS | none | none or `m<i>/` |

Members never get Agent, SendMessage, web or MCP tools.

## Predictions (stated, not measured here)
Expected to beat one expert at equal cost on proofs (selection by checker), code review (recall), checkable code and estimation (small effect); neutral or worse on research and design. RS, DS and OE: the leader refuses `eq-mode: auto` and warns on a manual run ("predicted neutral or worse").

## Refusals
Uncommitted change under the problem paths (CP, CR); check program not found; segment or check path outside the project root or in a protected path; PF without a lake project; ES without a numeric ask; `STACK_EQ=0`; a second live run; `auto` for a class without `validated` status; a missing consent record.

## Fallbacks for unvalidated (manual) runs
N 5 (capped by `STACK_EQ_MAX_N`); rounds 1; LOO view `rotation`; the class's pre-registered view scheme; reducer R0; the a-priori member type; the type's turn and token caps; certainty null; W3 level `auto` (container when installed and probed, else sandbox). All seven classes are allowed manually after the cost consent.

## Labels in every result
`unvalidated` (no validated entry), `agreement, not probability`, `w1_bash: heuristic` for PF, CP and CR (members have Bash), `n/a` for RS, ES, DS, OE; `model_drift` when a member ran on another model than the calibrated id; `override` when `STACK_EQ_N` or `STACK_EQ_ROUNDS` is set (manual only).
