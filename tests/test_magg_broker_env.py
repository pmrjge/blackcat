"""mcp-broker's magg server environment: the settings magg 1.3.0 needs from the stack.

magg 1.3.0's server search opens its aiohttp session with trust_env=True, which reads ~/.netrc and
sends a `default` entry's login to every host it queries (MCP registry, glama, GitHub, npm); magg runs
outside the Bash sandbox, so the stack's Read(~/.netrc) deny does not cover it. NETRC=/dev/null in
the magg entry's env turns that lookup off. MAGG_BACKEND_INIT_TIMEOUT=300 replaces 1.3.0's 30 s
backend initialize limit, too short for a first uvx/npx download of a catalog server.

Run: uv run --with pytest pytest -q tests/test_magg_broker_env.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BROKER = ROOT / "dot-config" / "dot-claude" / "agents" / "mcp-broker.md"


def _front() -> str:
    return BROKER.read_text(encoding="utf-8").split("\n---", 1)[0]


def test_magg_env_disables_netrc():
    assert re.search(r'^\s+NETRC: "/dev/null"\s*$', _front(), re.M), "magg env lacks NETRC: \"/dev/null\""


def test_magg_env_raises_backend_init_timeout():
    assert re.search(r'^\s+MAGG_BACKEND_INIT_TIMEOUT: "300"\s*$', _front(), re.M)


def test_magg_env_keys_sit_in_the_magg_env_block():
    """Both keys are siblings of MAGG_PATH, i.e. in the magg server's env, not elsewhere."""
    lines = _front().splitlines()
    i = next(n for n, line in enumerate(lines) if line.strip().startswith("MAGG_PATH:"))
    indent = len(lines[i]) - len(lines[i].lstrip())
    block = []
    for line in lines[i:]:
        if len(line) - len(line.lstrip()) != indent:
            break
        block.append(line.strip().split(":", 1)[0])
    assert {"MAGG_PATH", "MAGG_BACKEND_INIT_TIMEOUT", "NETRC"} <= set(block), block
