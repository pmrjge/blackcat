---
name: code-standards
description: Load before writing or changing code or infra config — workflow, minimal diffs, tests, escalation.
---
# Engineering standards
Verification, review triggers, parallel dispatch, consent and reporting follow the global rules; this skill adds the coding workflow.

## Workflow
1. Understand before editing: the relevant code, conventions, tests and the build/lint/test commands (package.json, pyproject.toml, Cargo.toml, Makefile, project CLAUDE.md). Use LSP when a code-intelligence plugin is installed and `grep`/`find` through Bash (Claude Code's shell runs fast embedded versions); for wide searches spawn explore.
2. Reproduce bugs first (a failing test or command). Fix the cause, not the symptom.
3. Smallest correct diff in the existing style. No drive-by refactors, no new dependencies without a reason.
4. Verify: the relevant tests, typecheck, lint and the program itself; quote only the decisive output lines. Never report done with failing tests: report partial and why.

## Quality bar
Clear names; small functions; explicit error handling (no silent catches); no secrets, dead code or commented-out code; comments explain "why". New behavior and fixed bugs get tests.

## Tool defaults
- Python: `uv` (`uv run`, `uv add`), ruff, pytest, pyright/mypy when configured. JS/TS: the repo's package manager, tsc, eslint, vitest/jest. Rust: cargo check / clippy / test. Go: go vet / test.
- Local ML on Apple Silicon: prefer MLX-native implementations for inference, quantization and fine-tuning; CUDA work runs only on an NVIDIA host the user or project docs name.
- Library/API usage: confirm against current docs with mcp__libdocs when unsure (`get_library_docs(library, topic)`); for a library the project leans on heavily, run `index_library_docs` once so later lookups are free.

## Offloading and escalation
- Offload mechanical, well-specified work (boilerplate, tests, call-site updates, docs) to coder with an exact brief: files, interfaces, done-when.
- Escalation chain: coder → main-coder (ml-/dl-/llm-engineer for model work, mlx-/cuda-engineer for accelerator work) after two failed attempts or when architecture or numerics is needed. main-coder hands an algorithmic or mathematical core (novel algorithm, proof, numerical stability, performance-critical kernel) to ninja-coder, and escalates to it after two serious, evidence-based attempts failed; mlx-, cuda-, dl- and llm-engineer use ninja-coder for such cores. ninja-coder is the top tier: after it failed twice, STATUS: partial with the dossier.
- Every escalation carries a dossier: goal, constraints, what failed and why, logs, minimal repro, current hypothesis. An agent that cannot spawn the next tier returns STATUS: partial with NEXT naming it and the dossier.
- TaskStop ends a runaway subagent.

Related skills: `python-engineering`, `rust-engineering`, `typescript-engineering` (language practice); `secure-coding` (input, secrets, auth, network); `git-workflows` (branches, worktrees, history edits); `cpu-performance` or `gpu-kernel-dev` before optimizing.
