#!/bin/bash
# dot-config/dot-codex_config/tests/run.sh: the Codex installer's suite, then the Claude installer's own
# install tests (they must stay green: the Codex installer reuses lib/install_state.py by path).
# Usage: dot-config/dot-codex_config/tests/run.sh [extra pytest args for the codex suite]
# Python through uv (3.13, pytest only); scratch HOME/CODEX_HOME per test; the fake codex on PATH.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$repo"
py=(uv run --no-project --python 3.13 --with pytest python)
echo "== dot-config/dot-codex_config/tests"
"${py[@]}" -m pytest -q -p no:cacheprovider dot-config/dot-codex_config/tests "$@"
echo "== Claude installer tests"
env -u STACK_LIMITS_SNAPSHOT -u CLAUDE_SESSION_ID "${py[@]}" -m pytest -q -p no:cacheprovider \
  tests/test_install_*.py tests/test_installer_config_dir.py
