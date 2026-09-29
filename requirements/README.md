# requirements/

Hash-locked inputs for the shared venvs (`~/.claude/venvs/sci`, `~/.claude/venvs/ml`, Python 3.12).
`*.in` are the unpinned lists; `*.txt` are compiled lockfiles with sha256 for every wheel/sdist (`--require-hashes` at install).
Why: pins and hashes stop a swapped or freshly hijacked PyPI release from being installed (CWE-494/829); the
`--exclude-newer` cutoff (7 days before compilation) is a cooldown, since malicious releases are usually pulled within days.
Regenerate (bump the date to today minus 7 days, RFC 3339); the exact command is in each `.txt` header:

    uv pip compile requirements/sci.in -o requirements/sci.txt --generate-hashes --python-version 3.12 --universal --exclude-newer 2026-09-22T00:00:00Z
    uv pip compile requirements/ml.in  -o requirements/ml.txt  --generate-hashes --python-version 3.12 --universal --exclude-newer 2026-09-22T00:00:00Z

Install: `uv venv --python 3.12 V && uv pip install --python V/bin/python --require-hashes -r requirements/<sci|ml>.txt`.
`mlx`/`mlx-lm` in ml.in carry a macOS arm64 marker, so the universal lock works on Linux too. ml.txt contains one sdist-only
package (`rouge-score`, pure Python, hashed), so do not pass `--only-binary :all:` for ml.
