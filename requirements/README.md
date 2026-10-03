# requirements/

Hash-locked inputs for the shared venvs (`~/.claude/venvs/sci`, `~/.claude/venvs/ml`, Python 3.14, macOS arm64 only).
`*.in` are the unpinned lists; `*.txt` are compiled lockfiles with sha256 for every wheel/sdist (`--require-hashes` at install).
Why: pins and hashes stop a swapped or freshly hijacked PyPI release from being installed (CWE-494/829); the
`--exclude-newer` cutoff (7 days before compilation) is a cooldown, since malicious releases are usually pulled within days.
Regenerate (bump the date to today minus 7 days, RFC 3339); the exact command is in each `.txt` header:

    uv pip compile requirements/sci.in -o requirements/sci.txt --generate-hashes --python-version 3.14 --python-platform aarch64-apple-darwin --only-binary :all: --exclude-newer 2026-09-22T00:00:00Z
    uv pip compile requirements/ml.in  -o requirements/ml.txt  --generate-hashes --python-version 3.14 --universal --exclude-newer 2026-09-22T00:00:00Z

Install: `uv venv --python 3.14 V && uv pip install --python V/bin/python --require-hashes -r requirements/<sci|ml>.txt`.
`sci.txt` is locked for macOS arm64 only (`--python-platform aarch64-apple-darwin`, all wheels). `ml.txt` stays `--universal` (mlx/mlx-lm carry a macOS arm64 marker, so it still resolves on Linux), but torch 2.14 and mlx wheels need macOS 14 or later. ml.txt contains sdist-only
packages (`rouge-score`, `sqlitedict`, `word2number`; pure Python, hashed), so do not pass `--only-binary :all:` for ml.
