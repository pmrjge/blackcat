# Project brief templates
Read from `prompt-and-brief-design` (core rules in its SKILL.md).

```markdown
# <Project> — <one-line purpose>
<2–3 sentences: users, what the system does, current stage.>

## Commands
- Setup: `uv sync`
- Test all / one: `uv run pytest -q` / `uv run pytest -q tests/test_x.py::test_y`
- Lint, format, types: `uv run ruff check --fix . && uv run ruff format . && uv run mypy src`
- Run: `uv run python -m <app>`

## Architecture
- `src/<app>/core/`: pure domain logic, no I/O. `src/<app>/io/`: adapters. Dependency direction: io → core.
- Invariants: <what must always hold>.

## Conventions
- <specific, checkable rules: naming, error handling, logging, typing>

## Non-goals
- <what not to build or optimize>

## Workflow
- Read the module and its tests before editing; add or update tests with each change.
- After each change run the package's tests; before reporting, the full suite and linters.
- Do not add dependencies, change public APIs or touch `<paths>` without asking.

## Gotchas
- <things that already went wrong, with the fix>
```
**Initial task prompt** — one milestone per session:
```
Goal: <one-sentence outcome>.
Context: <why; spec paths; relevant files and prior decisions>.
This session: milestone <N> — <scope>. Out of scope: <…>.
Requirements:
1. <behavioral requirement>
Acceptance criteria (all must hold):
- `uv run pytest -q tests/test_<feature>.py` passes; new tests cover <cases, incl. edge cases>.
- `<command>` prints <expected output>.
Constraints: <no new deps / keep API / don't edit X>.
Verification loop: after each change run <cmd>; fix failures before moving on; never weaken, skip or delete tests
to get green — if a test is wrong, say so.
Report: summary (≤10 lines); files changed; commands run with results; deviations and why; open questions.
Stop and ask if requirements conflict, a destructive action is needed, or <3> attempts at the same failure fail.
```
