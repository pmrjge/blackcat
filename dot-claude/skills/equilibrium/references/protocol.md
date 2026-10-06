# Equilibrium protocol (header, lifecycle, output contract, member contract)

## Header grammar
The brief to the `equilibrium` agent begins with lines, then `---`, then the problem verbatim:

| line | meaning |
|---|---|
| `eq-run: R` | injected by the guard (8 hex, `sha256(session|tool_use_id)[:8]`); never written by a caller |
| `eq-class: K` | one of PF CP CR RS ES DS OE (`classes.md`) |
| `eq-mode: auto\|manual` | `auto` = routed by BlackCat or the orchestrator (validated classes only); `manual` = the user asked |
| `eq-type: <type>` | optional member type; the plan's calibrated type wins unless manual |
| `eq-check: <argv>` | checkable classes: the public check, shell-quoted argv |
| `eq-segments: <path>\|<path>...` | optional inputs, inside the project root |

An unparsable header, `STACK_EQ=0`, a second live run, or `auto` on a class not validated: the spawn is refused by the guard.

## Lifecycle (store phases)
`planned` (plan) -> `started` (start, after consent) -> `checks` (prepare-check) -> `reduced` (reduce) -> `viewed` (view, rounds >= 1) -> `result` -> `cleaned` (cleanup). Tokens: member spawn `eq R m<i>/<N>`; reconcile message `eq R r<r> m<i>`; consent `Run eq:R`, removal `Remove eq:R`. Members are 1-based, rounds 0-based (r0 is blind). The guard substitutes the stored brief or view for every token, so the leader never holds them.

## Commands
`<config>/bin/stack-eq <sub> --run R [--round r]` with sub in `plan start prepare-check check-container reduce view result cleanup status help`; `<config>/bin/stack-eq-check --run R --cand i` (one candidate, sandboxed). `stack-eq help` prints the grammar. Consent is recorded only from a main-thread AskUserQuestion answer containing `Run eq:R`; a relay without that record is refused.

## Output contract (`stack-eq result`)
A JSON block and one prose line: `answer` (or `partial`; workdir classes: the `selected.patch` path), `class`, `validated`, `status_reason` (`no_calibration`, `class_not_validated`, `model_drift`, `n_or_rounds_capped`, `override`, `manual`), `validated_on`, `agreement` (kappa 0 and final, "agreement, not probability"), `loo`, `checks`, `facts`, `dissent`, `certainty` (null unless calibrated; null for CR and long-form), `wall` (`w3`, `w1_file_tools`, `w1_bash: heuristic` while members run Bash unsandboxed-by-container), `cost`, `run`, `params_sha256`, `patches`, `next`. The leader's final reply equals it; the guard asks for one restate otherwise.

## Member contract (rendered into every brief)
- One JSON object as the whole final reply: `answer`, `evidence[]`, `confidence`; the class schema is printed in the brief.
- No spawns, messages, web or memory; work only in the named working directory.
- Integrator: the equilibrium leader. Do not commit, merge, stash, rebase or touch other branches or worktrees; leave your edits uncommitted in your working directory.
- Git is read-only (`status`, `diff`, `log` and `show` at HEAD, `ls-files`). Siblings' directories, transcripts and the store are off limits (enforced by a hook for file tools).
