<!-- markdownlint-disable MD013 MD060 -->
# Instructor: fixed `just` recipes

`tools/instructor/` is a closed menu of fixed procedures that agents may run without a prompt in a checkout of
this repository: the C10 check suite, a locked fast-forward of local `main`, and a read-only worktree report. The
point is that an agent runs a reviewed procedure, not a command line it composed.

## The recipes

| Recipe | Does |
|---|---|
| `check-suite` | the [C10 suite](Testing-and-C10.md) in one checkout: `bash -n` on every tracked `*.sh`, `agent_guard.py --self-test`, `tests/lint_agents.py`, `tests/prompt_budget.py --check`, pytest on `tests/` and on `tools/instructor/tests/` (one run each), `tests/install_smoke.sh`. Options `--only`/`--skip <step>`, `--fail-fast`, `--timeout` |
| `ff-merge --branch <name>` | fast-forwards local `main` to a local branch, one merge at a time per repository (a `flock` on `<git-common-dir>/instr-ff-merge.lock`), by compare-and-swap (`git update-ref refs/heads/main <new> <old>`), moves `main`'s checkout with `git read-tree -m -u` after a dry run, then runs `check-suite` there (`--suite none` skips it) |
| `worktree-audit` | report only: every worktree (main, bare, prunable, busy, dirty, merged-clean, unmerged, detached) and every branch without a worktree; removal stays your step |

`ff-merge` refuses a non-fast-forward, a dirty, busy or missing `main` checkout and an untracked file it would
overwrite; an already merged branch is a NOOP. It never stashes, resets, discards, removes a worktree or deletes a
branch, and runs git with `core.hooksPath=/dev/null`, `core.fsmonitor=false`, `protocol.allow=never` and no
`GIT_*` variables from the caller.

## Running it

From the root of a checkout:

```bash
just -f tools/instructor/justfile --list                  # the menu (also the default recipe)
just -f tools/instructor/justfile check-suite --dry-run   # the plan, nothing run
just -f tools/instructor/justfile check-suite
just -f tools/instructor/justfile ff-merge --branch my-branch
just -f tools/instructor/justfile worktree-audit
just -f tools/instructor/justfile <recipe> --help
```

Without `just`: `uv run --no-config --script tools/instructor/bin/<script>.py …` does the same (`check_suite.py`,
`ff_merge.py`, `worktree_audit.py`). `install.sh` step 2 adds `just` to the Homebrew batch when it is missing.

**Output contract.** stdout is one line, `OK|FAIL|NOOP <verb> key=value... log=<path>`; exit 0 OK, 1 FAIL, 2 bad
argument, 3 NOOP. Details go to a fresh log under `<checkout>/.claude-work/instr/`.

## Why it is safe to pre-approve

- **The justfile is a dispatcher only.** Each recipe runs `uv run --quiet --no-config --script
  tools/instructor/bin/<script>.py "$@"` with `set positional-arguments`: arguments reach the script verbatim,
  never as shell text. No backticks, variables, `{{arg}}` interpolation or recipe dependencies
  (`tools/instructor/tests/test_instr_safety.py` pins this). `--no-config` keeps an agent-writable
  `.python-version`, `uv.toml` or `pyproject.toml` from choosing the interpreter.
- **One allow rule per recipe, plus the menu:**

  ```text
  Bash(just -f tools/instructor/justfile check-suite *)
  Bash(just -f tools/instructor/justfile ff-merge *)
  Bash(just -f tools/instructor/justfile worktree-audit *)
  Bash(just -f tools/instructor/justfile --list)
  ```

  There is no `Bash(just *)`: `just`'s own options before the recipe name (`--command`, `--shell`, `--set`,
  `--justfile`) choose what runs. After the recipe name every token is a recipe argument, and each script checks
  its arguments against its own allowlist (exit 2 otherwise). `tests/test_instructor_wiring.py` pins the rule set
  against the justfile's recipes.
- **Not agent-writable.** `Edit(//**/tools/instructor/**)` denies the directory to Edit, Write and the other
  file-editing tools everywhere on the machine, and the guard's protected-path spec `tools/instructor` refuses
  Bash writes that name it, in every checkout. Changes to the instructor are yours, by commit.
- **The commands still run in the Bash sandbox.**

## Residual risks

From `CONFIG.md` §5 "Instructor":

- The rules' `-f tools/instructor/justfile` is relative to the session's directory, so in another repository that
  ships its own `tools/instructor/justfile` those three recipe names run its recipes unprompted, sandboxed.
- `check-suite` runs the target checkout's own code (tests, the guard's self-test, the smoke test) with the tools
  venv: sandboxed for agents, unsandboxed when you run it from a terminal.
- Bash writes that do not name `tools/instructor` pass the guard (`rsync -a <dir>/ tools/`, archive extracts,
  `git checkout <rev> -- tools/instructor/…`, `rm -rf tools`, script files).
- Repo-local git filter and merge drivers run during `read-tree -u`; agents cannot set them, but one you set runs.
- The absolute deny rule has a machine-wide side effect on macOS: see
  [Operations](Operations.md#side-effect-of-the-instructor-deny-rule).

Tests: `uv run --no-project --python 3.13 --with pytest pytest -q tools/instructor/tests tests/test_instructor_wiring.py`
(77 tests in `tools/instructor/tests` on 2026-10-06; the wiring tests run the recipes through a real `just` and are
skipped without one). Lint: `cd tools/instructor && uv run --no-project --with ruff ruff check .`.

Sources: `tools/instructor/justfile`, `tools/instructor/bin/check_suite.py`, `dot-claude/settings.json`
(`permissions.allow`, `permissions.deny`), `README.md` ("Commands and CLIs", "Safety and guardrails"),
`CONFIG.md` §5 "Instructor: `just` recipes" and §9 (2026-10-05).
