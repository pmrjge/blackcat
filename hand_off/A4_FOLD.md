# A4 probe: run it, fold it into COMPARE_eq A4 item 4

One paid call (consent given, hard cap $0.25), user-run from a normal logged-in terminal (agent sandboxes have no
`claude` login). Nothing here was run by the author. Source of the probe: `HANDOFF_STATE.md` §5; the only change is
`P=`, because EQ-T moved to `/Users/pmrj/ZDone/claude-agent-stack/.claude-work/worktrees/eq-t-1005/.claude-work/equilibrium`
[v: `COMPARE_eq.md` A4 is readable there]. Run it with the stack as installed now (it uses `~/.claude/agents/writer.md`),
not in the middle of the c0 arm (`RUNBOOK_c0.md`: no `claude` calls besides the arm session between A and C).

## 1. The probe (corrected `P=`)

```sh
P=/Users/pmrj/ZDone/claude-agent-stack/.claude-work/worktrees/eq-t-1005/.claude-work/equilibrium/probes; mkdir -p "$P"; TS=$(date -u +%Y%m%dT%H%M%SZ); cd "$(mktemp -d)" && printf 'List the exact names of every tool you can call, then return them.\n' | claude -p --agent writer --model sonnet --max-budget-usd 0.25 --json-schema '{"type":"object","properties":{"tools":{"type":"array","items":{"type":"string"}}},"required":["tools"],"additionalProperties":false}' --output-format stream-json --verbose --permission-mode acceptEdits --disallowedTools Agent WebSearch WebFetch --strict-mcp-config --tools Read,Skill,StructuredOutput --allowedTools Read Skill > "$P/a4-probe-$TS.json" 2> "$P/a4-probe-$TS.err"; echo "exit=$?" >> "$P/a4-probe-$TS.err"
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
P=/Users/pmrj/ZDone/claude-agent-stack/.claude-work/worktrees/eq-t-1005/.claude-work/equilibrium/probes; F=$(ls -t "$P"/a4-probe-*.json | head -1); uv run --script /Users/pmrj/ZDone/claude-agent-stack/hand_off/a4_fold.py "$F" --err "${F%.json}.err" --agent-file ~/.claude/agents/writer.md --out "${F%.json}.fold.md"
```

The block is also saved as `a4-probe-<TS>.fold.md` next to the probe. Expected limits of this one probe, so no
surprise: (a) `--tools` names `StructuredOutput`, so "needs naming" cannot be answered; (b) `writer`'s frontmatter
contains `Read` and `Skill`, so intersection and "only `--tools`" give the same list (verdict `consistent`); the
probe shows only that the frontmatter does not widen it; (c) no `--settings` is passed (verdict `unknown`); (d) `Skill`
is listed but never invoked (verdict `unknown`). Closing (c) and (d) needs a second paid call, your decision.

## 3. Brief for a fresh python-engineer (apply the block to COMPARE_eq)

Hand the engineer the text below verbatim, with `<FOLD>` replaced by the path of `a4-probe-<TS>.fold.md`.

```
Goal: replace the "Still unverified" list of A4 item 4 in COMPARE_eq.md with the probe outcome.
Inputs: <FOLD> (scrubbed Markdown block, already folded; do not read the raw a4-probe-*.json or .err);
COMPARE_eq.md at /Users/pmrj/ZDone/claude-agent-stack/.claude-work/worktrees/eq-t-1005/.claude-work/equilibrium/COMPARE_eq.md
(A4 item 4 is at about lines 457-464); the earlier A4 text in the same file.
Constraints: EQ-T is not in git. FIRST archive it: tar -czf <your worktree>/.claude-work/eq-t-before-a4-fold.tgz of
the whole equilibrium/ folder and record the path and `shasum -a 256` of the tarball; also copy COMPARE_eq.md to
COMPARE_eq.md.pre-a4-fold beside the tarball. Edit only COMPARE_eq.md, only A4 item 4 (and, if a verdict contradicts item
2 or 5, add one dated sentence there; change nothing else). A4 is a PRE-FREEZE amendment: if COMPARE_eq.sha256 or runs/
now exist, stop and report STATUS: blocked instead. Keep the file's style (no emojis; item numbering 1-5 unchanged).
Do not run claude, install.sh, or any paid call; do not push; python only via uv.
Do: (1) paste the block from <FOLD> as the new content of item 4, keeping each verdict word exactly (confirmed, refuted,
consistent, unknown); for every "unknown" keep the sentence "settled only by a live call" with the reason from the block;
(2) if a verdict is "refuted", state the consequence for A4 items 2 and 5 in one sentence and list the harness code that
would change (harness/eq_harness.py build_argv, flags.json common_tools) WITHOUT editing it; (3) run the harness tests from a /tmp
copy: uv run --no-project --with pytest --with duckdb --with-requirements harness/eq_harness.py pytest -q -p no:cacheprovider harness/tests
(expected 416 passed); (4) git is not involved (EQ-T has no repo): report the tarball path, the diff (diff -u pre-fold new),
and the test result.
Done when: item 4 holds the probe outcome with four verdicts, tests unchanged, archive recorded.
Output: STATUS block, at most 1500 chars, plus the diff path.
```
