# requirements/

Hash-locked inputs for the shared venvs (`~/.claude/venvs/sci`, `~/.claude/venvs/ml`, `~/.claude/venvs/tools`, Python 3.13, macOS arm64 only).
`*.in` are the unpinned lists; `*.txt` are compiled lockfiles with sha256 for every wheel/sdist (`--require-hashes` at install).
Why: pins and hashes stop a swapped or freshly hijacked PyPI release from being installed (CWE-494/829); the
`--exclude-newer` cutoff (7 days before compilation) is a cooldown, since malicious releases are usually pulled within days.
Regenerate (bump the date to today minus 7 days, RFC 3339); the exact command is in each `.txt` header:

    uv pip compile requirements/sci.in -o requirements/sci.txt --generate-hashes --python-version 3.13 --python-platform aarch64-apple-darwin --only-binary :all: --exclude-newer 2026-09-22T00:00:00Z
    uv pip compile requirements/ml.in  -o requirements/ml.txt  --generate-hashes --python-version 3.13 --universal --exclude-newer 2026-09-22T00:00:00Z
    uv pip compile requirements/tools.in -o requirements/tools.txt --generate-hashes --python-version 3.13 --python-platform aarch64-apple-darwin --only-binary :all: --exclude-newer 2026-09-22T00:00:00Z

Install: `uv venv --python 3.13 V && uv pip install --python V/bin/python --require-hashes -r requirements/<sci|ml|tools>.txt`.
`sci.txt` is locked for macOS arm64 only (`--python-platform aarch64-apple-darwin`, all wheels). `ml.txt` stays `--universal` (mlx/mlx-lm carry a macOS arm64 marker, so it still resolves on Linux), but torch 2.14 and mlx wheels need macOS 14 or later. ml.txt contains sdist-only
packages (`rouge-score`, `sqlitedict`, `word2number`; pure Python, hashed), so do not pass `--only-binary :all:` for ml.

## tools (`~/.claude/venvs/tools`)
What the stack's own Python imports outside the stdlib: `bin/`, `mcp/` (libdocs, image_studio, neural_memory),
`hooks/stack_sched_refresh.py`, `tests/` (derive_sched_model, derive_thresholds, test_*.py). Each line of
`tools.in` names its importers; `tests/test_install_state.py` fails when a new third-party import appears that
`tools.in` does not cover. Hooks run on `/usr/bin/python3` with the stdlib only and never use this venv.
Full suite: `~/.claude/venvs/tools/bin/python -m pytest -q tests/`.
Left out: `claude-agent-sdk==0.2.163` (bin/stack_sdk.py, tests/sdk_smoke.py, one importorskip test in
test_sdk_integration.py), published 2026-09-30, inside the cooldown; add it at the next re-lock.

Extras (e.g. a future Bayesian stack, PyMC or NumPyro): a separate lock, never extra lines in `tools.in`.
Write `requirements/tools-<extra>.in` starting with `-r tools.in`, compile it with the tools command above
(`-o requirements/tools-<extra>.txt`; drop `--only-binary :all:` only if a dependency is sdist-only), and
point `TOOLS_REQS` in install.sh at that `.txt` behind an opt-in flag (as `--with-ml` does); the base
`tools.txt` stays the default.
