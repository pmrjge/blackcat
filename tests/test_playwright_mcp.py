"""Static checks of the Playwright MCP launch args: auto-named output (screenshots, snapshots,
logs) goes to a fixed directory under the sandbox-writable cache, never `<cwd>/.playwright-mcp/`
(0.0.82's default when no --output-dir is given). CONFIG.md changelog 2026-10-03.

Run: uv run --with pytest pytest -q tests/test_playwright_mcp.py
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOT = ROOT / "dot-claude"
SANDBOX_CACHE = "~/.cache/claude-sandbox"           # settings.json sandbox.filesystem.allowWrite
OUTPUT_DIR = "__HOME__/.cache/claude-sandbox/playwright-mcp"


def inline_playwright_args():
    """{agent file: args list} for every agent whose frontmatter declares an inline playwright."""
    out = {}
    for p in sorted((DOT / "agents").glob("*.md")):
        fm = p.read_text().split("\n---", 1)[0]
        m = re.search(r"(?m)^  - playwright:\n((?:      .*\n)+)", fm + "\n")
        if not m:
            continue
        a = re.search(r"(?m)^      args:\s*(\[.*\])\s*$", m.group(1))
        assert a, "%s: playwright entry without a one-line args list" % p.name
        out[p.name] = json.loads(a.group(1))
    return out


def all_playwright_args():
    found = inline_playwright_args()
    magg = json.loads((DOT / "magg" / "config.json").read_text())
    found["magg/config.json"] = magg["servers"]["playwright"]["args"]
    return found


def opt(args, name):
    """Value of `name <v>` or `name=<v>` in args (None when absent)."""
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


def test_every_playwright_entry_is_found():
    found = all_playwright_args()
    assert {"browser-operator.md", "frontend-engineer.md", "verifier.md", "magg/config.json"} <= set(found)


def test_output_dir_is_set_and_under_the_sandbox_cache():
    for where, args in all_playwright_args().items():
        out = opt(args, "--output-dir")
        assert out, "%s: playwright args lack --output-dir (output lands in <cwd>/.playwright-mcp)" % where
        assert out == OUTPUT_DIR, "%s: --output-dir %r, expected %r" % (where, out, OUTPUT_DIR)
        # absolute after rendering: the server does path.resolve() with no ~ expansion
        assert out.startswith("__HOME__/") and "~" not in out, where
        rendered = out.replace("__HOME__", "~", 1)
        assert rendered.startswith(SANDBOX_CACHE + "/"), (where, rendered)


def test_sandbox_cache_is_writable_in_settings():
    settings = json.loads((DOT / "settings.json").read_text())
    assert SANDBOX_CACHE in settings["sandbox"]["filesystem"]["allowWrite"]
    assert not any(SANDBOX_CACHE.startswith(d.rstrip("/")) or d.startswith(SANDBOX_CACHE)
                   for d in settings["sandbox"]["filesystem"].get("denyWrite", []))


def test_existing_flags_kept_and_paths_absolute():
    for where, args in all_playwright_args().items():
        assert "--headless" in args and "--isolated" in args, where
        assert opt(args, "--file-paths") == "absolute", where


def test_one_pinned_version_everywhere():
    pins = {where: next(a for a in args if a.startswith("@playwright/mcp@"))
            for where, args in all_playwright_args().items()}
    assert len(set(pins.values())) == 1, pins
    assert "@latest" not in next(iter(pins.values()))


def test_gitignore_has_the_old_folder():
    assert ".playwright-mcp/" in (ROOT / ".gitignore").read_text().splitlines()


def test_installer_creates_the_output_dir():
    """install.sh creates the rendered --output-dir, 0700 (doctor.sh FAILs while it is missing; the
    behaviour, --dry-run included, is checked by tests/install_smoke.sh §8): the path it builds is
    OUTPUT_DIR with __HOME__ as $HOME, and it only does so when an installed entry names it."""
    text = (ROOT / "install.sh").read_text()
    want = 'pw_out="${HOME%%/}%s"' % OUTPUT_DIR[len("__HOME__"):]
    assert want in text, "install.sh does not build %s" % OUTPUT_DIR
    block = text[text.index(want):][:600]
    assert 'grep -qsF -e "\\"$pw_out\\""' in block
    assert '(umask 077 && mkdir -p "$pw_out") && chmod 700 "$pw_out"' in block
