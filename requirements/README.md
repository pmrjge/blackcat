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

Extras: a separate lock, never extra lines in `tools.in`.
Write `requirements/tools-<extra>.in` starting with `-r tools.in`, compile it with the tools command above
plus `-c requirements/tools.txt` (every package the two locks share keeps the base pin, so a later plain
install, which syncs `tools.txt` into the same venv, changes none of them; `-o requirements/tools-<extra>.txt`;
drop `--only-binary :all:` only if a dependency is sdist-only), and point `TOOLS_REQS` in install.sh at that
`.txt` behind an opt-in flag; the base `tools.txt` stays the default. Re-lock an extra whenever `tools.txt`
changes. Before an extra's `.txt` ships, scan it (below) and record the result in the commit message.

### tools-bayes (`./install.sh --with-bayes`, docs/BAYES.md §2.9)
The detached Bayes fitter's dependencies (`hooks/stack_bayes.py`: pymc, pytensor, nutpie, arviz, scipy) on top
of the tools venv. Opt-in and shadow-only: nothing installs it by default, and installing it changes no limit
(`STACK_BAYES` defaults to `shadow`, `BAYES_LIVE` is empty). Lock (2026-10-09, cutoff 2026-10-02):

    uv pip compile requirements/tools-bayes.in -c requirements/tools.txt -o requirements/tools-bayes.txt --generate-hashes --python-version 3.13 --python-platform aarch64-apple-darwin --only-binary :all: --exclude-newer 2026-10-02T00:00:00Z

Pins equal the prototype's lock (`docs/bayes/b1v2/fit_prototype.py.lock`) except pytensor 3.3.2 for 3.3.3
(published 2026-10-02T14:13Z, inside the cooldown; `tools-bayes.in` says when to re-lock).
Scan (no install into the stack: uv's cache only; api.osv.dev is not reachable from the agents' sandbox, so
the PyPI advisory feed):

    uvx --exclude-newer 2026-10-02T00:00:00Z pip-audit -r requirements/tools-bayes.txt --require-hashes --disable-pip -s pypi

2026-10-09, pip-audit 2.10.1: 76 packages, none of the Bayes packages or their own dependencies flagged; 2
advisories in `pyjwt` 2.14.0 (PYSEC-2026-4141 / CVE-2026-101918, PYSEC-2026-4183 / CVE-2026-102275, fixed in
2.15.0), which comes from `tools.txt` (via `mcp`) and is flagged there too: fixed by re-locking `tools.txt`
(pyjwt 2.15.1, published 2026-09-28), then this file.
