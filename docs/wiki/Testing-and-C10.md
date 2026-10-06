<!-- markdownlint-disable MD013 MD060 -->
# Testing and the C10 gate

What the repository's tests prove is the machinery: the guard, the installer, the limits, the user commands and
the prompt sizes. The rules' effect on answer quality is not measured by them (README "Reliability and
verification"). Every merge into `main` is followed by C10 on `main`.

## C10: the check suite

C10 is the name the project uses for its full check suite; `tools/instructor/bin/check_suite.py` calls itself
"the stack's C10 check suite" and runs it as the `check-suite` recipe ([Instructor](Instructor.md)). Steps, in
order:

| Step | Command (run on `~/.claude/venvs/tools/bin/python`) | Passes when |
|---|---|---|
| `bash-n` | `/bin/bash -n` on every tracked `*.sh` | every file parses |
| `guard-self-test` | `dot-claude/hooks/agent_guard.py --self-test` | exit 0 |
| `lint-agents` | `tests/lint_agents.py` | exit 0 |
| `prompt-budget` | `tests/prompt_budget.py --check` | exit 0 |
| `pytest` | `pytest -q tests/`, then `pytest -q tools/instructor/tests/` (one run per directory: each has its own `conftest.py`) | exit 0 with a summary line |
| `smoke` | `/bin/bash tests/install_smoke.sh` | every FAIL line is one of the two known openpty cases |

The interpreter is fixed, never an argument, and the suite drops `STACK_LIMITS_SNAPSHOT` and `CLAUDE_SESSION_ID`
from the environment of each step. Run it with `just -f tools/instructor/justfile check-suite` (or `--only`,
`--skip`, `--fail-fast`, `--timeout`); `ff-merge` runs it on `main` after each fast-forward.

## Known environment failures

These fail for reasons of where the tests run, not because of the code. Run the suite from your own terminal to
see them pass.

| Case | Why it fails | Where it is recorded |
|---|---|---|
| `install_smoke.sh`: "supply-chain confirmation" and "controlling-terminal supply confirmation" | `os.openpty()` is denied in sandboxed Bash; they pass in a terminal. C10 tolerates exactly these two | `KNOWN_SMOKE` in `check_suite.py` |
| `test_four_tools_and_three_model_settings` in `tests/test_image_studio_mcp.py` | the sandbox denies reading `~/.claude/stack.env` | README "Known limits" |
| one `f4` case in `tests/test_protected_paths.py` | pytest's temp dir sits under `/tmp/claude-501` inside a session | README "Known limits" |
| two cases of `test_three_way_verdict_on_the_soft_limit` | fail when `STACK_LIMITS_SNAPSHOT` is set (C10 unsets it) | README "Known limits" |
| the collector upgrade tests in `tests/test_stack_usage.py` | read older commits; skipped with a note in a clone without them | README "Contributing and safety" |
| `install_smoke.sh` as a whole | the Claude Code sandbox refuses parts of it | README "Verify": run it from your own terminal |

`tests/prompt_budget.py --check` compares with its base revision through git; in a clone without that commit it
falls back to `tests/fixtures/prompt_budget_base.json`.

## What the suites cover

| Area | Tests |
|---|---|
| Spawn policy, depth, fan-out, BlackCat's tools, security rounds | `agent_guard.py --self-test`, `tests/test_agent_guard.py`, `test_guard_regressions.py`, `test_guard_round2.py`, `test_guard_round3.py`, `test_blackcat_tools.py` |
| No push, protected paths, read-only Bash, message routing | `tests/test_no_push.py`, `test_protected_paths.py`, `test_readonly_agents.py`, `test_send_routing.py` |
| Budgets, learned limits, collector, scheduler | `tests/test_limits_guard.py`, `test_stack_limits.py`, `test_stack_usage.py`, `test_sched_snapshot.py`, `test_stack_sched.py` |
| User commands | `tests/test_stack_budget.py`, `test_stack_tree.py`, `test_stack_doctor.py`, `test_override_agent.py`, `test_stack_who.py` |
| Gates and MCP servers | `tests/test_read_gate.py`, `test_web_caps.py`, `test_output_shrink.py`, `test_image_limit.py`, `test_libdocs_mcp.py`, `test_image_studio_mcp.py`, `test_mcp_headers.py`, `test_stack_progress.py` |
| Agent and skill files, prompt size | `tests/lint_agents.py`, `tests/prompt_budget.py --check`, `test_skill_modules.py`, `test_no_duplicates.py`, `test_moved_paths.py`, `test_cache_stability.py`, `test_redundancy.py` |
| Installer | `tests/install_smoke.sh`, `test_install_*.py`, `test_installer_config_dir.py`, `test_install_eq_container.py`, `test_eq_container.py` |
| toolsmith, instructor | `tests/test_toolsmith.py`, `test_instructor_wiring.py`, `tools/instructor/tests/` |
| This wiki | `tests/test_wiki_links.py`: every relative link and image in `docs/wiki/` resolves, anchors exist, images carry alt text, every page is in the sidebar |

Sizes on 2026-10-06 (`pytest --collect-only` on the tools venv): `tests/` holds 70 `test_*.py` files; the other
suites are `tools/instructor/tests` (77 tests, part of C10), `hand_off/tests` (40) and `lib/eq-wall/tests` (102),
the last two outside C10. Recorded runs, for history: 2,401 passed at the 2026-09-29 validation (CONFIG §8);
3,119 passed, 2 failed, 1 skipped on 2026-10-03, run by the author inside the sandbox (README "Known limits").

## Other checks

| Command | Checks |
|---|---|
| `uv run tests/redundancy_lint.py` | no long sentence repeated in 3+ agent or skill files, no dangling skill reference, no unwired hook file, beyond `tests/redundancy_allowlist.json` |
| `uv run tests/cache_stability_lint.py` | no dates, clock times, ids, commit hashes, versions, model IDs or shell injection in the prompt text the stack ships into the cached prefix (agents, rules, skill frontmatter, `CLAUDE*.md` templates) |
| `uv run tests/lint_agents.py` | also: no specific Claude model ID in any tracked file outside the allowed places |
| `bash ~/.claude/bin/doctor.sh` | the installed folder's health (= `/stack-doctor`) |

## Running the tests

```bash
~/.claude/venvs/tools/bin/python -m pytest -q tests/        # the full suite (the tools venv from install.sh)
uv run --with pytest pytest -q tests/test_wiki_links.py      # one file
just -f tools/instructor/justfile check-suite                # all of C10, one status line
bash tests/install_smoke.sh                                  # from your own terminal
```

Sources: `tools/instructor/bin/check_suite.py`, `README.md` ("Reliability and verification", "Known limits",
"Verify", "Contributing and safety"), `CONFIG.md` §5 "Instructor" and §8, `hand_off/HANDOFF_STATE.md` §6
(standing constraints), `pytest --collect-only` output.
