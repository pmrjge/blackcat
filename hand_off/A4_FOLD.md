# A4 probe: run it, fold it into COMPARE_eq A4 item 4

One paid call (consent given, hard cap $0.25), user-run from a normal logged-in terminal (agent sandboxes have no
`claude` login). Nothing here was run by the author. Source of the probe: `HANDOFF_STATE.md` §5; the only change is
`P=`: the output goes to `dot-config/dot-equilibrium/runs/probes/` in the repository, which `.gitignore` keeps out of git
(`/equilibrium/**/runs/`), so the raw output (session ids, paths) is never tracked. Run it with the stack as installed now (it uses `~/.claude/agents/writer.md`),
not in the middle of the c0 arm (`RUNBOOK_c0.md`: no `claude` calls besides the arm session between A and C).

## 1. The probe (corrected `P=`)

```sh
P=/Users/pmrj/ZDone/claude-agent-stack/dot-config/dot-equilibrium/runs/probes; mkdir -p "$P"; TS=$(date -u +%Y%m%dT%H%M%SZ); cd "$(mktemp -d)" && printf 'List the exact names of every tool you can call, then return them.\n' | claude -p --agent writer --model sonnet --max-budget-usd 0.25 --json-schema '{"type":"object","properties":{"tools":{"type":"array","items":{"type":"string"}}},"required":["tools"],"additionalProperties":false}' --output-format stream-json --verbose --permission-mode acceptEdits --disallowedTools Agent WebSearch WebFetch --strict-mcp-config --tools Read,Skill,StructuredOutput --allowedTools Read Skill > "$P/a4-probe-$TS.json" 2> "$P/a4-probe-$TS.err"; echo "exit=$?" >> "$P/a4-probe-$TS.err"
```

Outputs: `$P/a4-probe-<TS>.json` (stream-json) and `$P/a4-probe-<TS>.err` (stderr plus `exit=`). Both can hold
session ids and paths; do not paste them anywhere raw.

## 2. Fold (read-only; prints a Markdown block, writes nothing)

`a4_fold.py` strips credentials, tokens, session ids, emails and home paths; extracts the init event (tools, model,
permission mode, version, MCP servers), the result event (structured output, cost, turns, denials), the tools the
model called and the errors they returned (a Skill call that only errored gives `unknown`, not "never invoked");
prints a block for A4 item 4 and one verdict per open question (`confirmed`, `refuted`, `consistent`, or `unknown`
when the output cannot show it). Tests: `uv run --with pytest pytest -q hand_off/tests/test_a4_fold.py`
(9 pass; synthetic fixtures only, the real output format is [unverified]: field names follow the stream-json init and
result events and the parser tolerates missing ones).

```sh
P=/Users/pmrj/ZDone/claude-agent-stack/dot-config/dot-equilibrium/runs/probes; F=$(ls -t "$P"/a4-probe-*.json | head -1); uv run --script /Users/pmrj/ZDone/claude-agent-stack/hand_off/a4_fold.py "$F" --err "${F%.json}.err" --agent-file ~/.claude/agents/writer.md --out "${F%.json}.fold.md"
```

The block is also saved as `a4-probe-<TS>.fold.md` next to the probe. Expected limits of this one probe, so no
surprise: (a) `--tools` names `StructuredOutput`, so "needs naming" cannot be answered; (b) `writer`'s frontmatter
contains `Read` and `Skill`, so intersection and "only `--tools`" give the same list (verdict `consistent`); the
probe shows only that the frontmatter does not widen it; (c) no `--settings` is passed (verdict `unknown`); (d) `Skill`
is listed but never invoked (verdict `unknown`). Closing (c) and (d) needs a second paid call, your decision.

## 3. Brief for a fresh python-engineer (apply the block to COMPARE_eq)

Hand the engineer the text below verbatim, with `<FOLD>` replaced by the path of `a4-probe-<TS>.fold.md`. EQ-T is
tracked in the repository as `dot-config/dot-equilibrium/` (eq-track), so the file to edit is `dot-config/dot-equilibrium/COMPARE_eq.md` on a branch,
and git replaces the old tarball archive.

```
Goal: replace the "Still unverified" list of A4 item 4 in dot-config/dot-equilibrium/COMPARE_eq.md with the probe outcome.
Inputs: <FOLD> (scrubbed Markdown block, already folded; do not read the raw a4-probe-*.json or .err);
dot-config/dot-equilibrium/COMPARE_eq.md in the repository M = /Users/pmrj/ZDone/claude-agent-stack (tracked on main; A4 item 4 is the
"Still unverified" list in section 12 A4, at about lines 457-464); the earlier A4 text in the same file.
Constraints: work on a new branch from M's main in your own worktree (where the session's rules put worktrees); git is
the archive. Edit only dot-config/dot-equilibrium/COMPARE_eq.md, only A4 item 4 (and, if a verdict contradicts item 2 or 5, add one
dated sentence there; change nothing else), plus the pin record below. A4 is a PRE-FREEZE amendment: if
dot-config/dot-equilibrium/COMPARE_eq.sha256 (the freeze sidecar) or a runs/ folder under dot-config/dot-equilibrium/ other than runs/probes/ (the
probe's output) and the tracked items/RS/fixtures/corpus/runs/ now exists, stop and report STATUS: blocked instead.
COMPARE_eq.md is digest-pinned (tests/equilibrium_paths.py): re-pin it with
`uv run --no-project python tests/equilibrium_paths.py amend --amendment A4 dot-config/dot-equilibrium/COMPARE_eq.md` (the amend
subcommand comes with eq-runtime; if it is missing, stop and report STATUS: blocked). Keep the file's style (no emojis;
item numbering 1-5 unchanged). Do not run claude, install.sh, or any paid call; do not push or merge; python only via uv.
Do: (1) paste the block from <FOLD> as the new content of item 4, keeping each verdict word exactly (confirmed, refuted,
consistent, unknown); for every "unknown" keep the sentence "settled only by a live call" with the reason from the block;
(2) if a verdict is "refuted", state the consequence for A4 items 2 and 5 in one sentence and list the harness code that
would change (dot-config/dot-equilibrium/harness/eq_harness.py build_argv, flags.json common_tools) WITHOUT editing it; (3) re-pin, then
run `uv run --no-project python tests/equilibrium_paths.py check`, `tests/test_equilibrium_paths.py`, and the harness
suite from a $TMPDIR copy as CONFIG.md section 5 ("Extra C10 step") gives it: 0 failed, the same counts as on main
before the edit; any pin test that fails: stop, STATUS: blocked with its output; (4) commit on your branch (the merge is
the integrator's) and report the branch, the commit, `git diff main --stat` and the test results.
Done when: item 4 holds the probe outcome with four verdicts, the pin check and the tests pass, the commit exists.
Output: STATUS block, at most 1500 chars.
```
