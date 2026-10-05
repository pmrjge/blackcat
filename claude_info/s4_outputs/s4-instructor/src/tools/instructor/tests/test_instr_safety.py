"""The instructor's own guard rails, checked on the recipe and script text.

A Bash PreToolUse hook sees `just -f tools/instructor/justfile <recipe> ...` only, never the commands
a recipe runs, so the rules the hook enforces elsewhere are enforced here on the files themselves:
no remote write (push, forge CLIs, network git), no install.sh, no shell strings, a dispatcher-only
justfile, small PEP 723 scripts.

Run: uv run --with pytest pytest -q tools/instructor/tests/"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JUSTFILE = ROOT / "justfile"
SCRIPTS = sorted((ROOT / "bin").glob("*.py"))
ALL = [JUSTFILE, *SCRIPTS]

FORBIDDEN = [
    r"\bpush\b", r"send-pack", r"receive-pack", r"upload-pack", r"\bgh\b", r"\btea\b", r"\bfj\b",
    r"\bfetch\b", r"\bpull\b", r"\bclone\b", r"\bremote\b", r"\bsubmodule\b", r"ls-remote",
    r"install\.sh", r"\bbrew\b", r"\bcurl\b", r"\bwget\b", r"api\.github", r"https?://", r"ssh\b",
    r"shell\s*=\s*True", r"os\.(system|popen|exec\w*|spawn\w*)", r"\bgetoutput\b", r"\bgetstatusoutput\b",
    r"(?<![\w.])eval\s*\(", r"(?<![\w.])exec\s*\(", r"\bpty\b", r"--force\b", r"\breset\b", r"\bstash\b",
    r"worktree\s+(remove|prune)", r"branch\s+-[dD]\b", r"update-ref\s+-d\b", r"\bclaude\b\s+-p",
]


@pytest.mark.parametrize("path", ALL, ids=lambda p: p.name)
def test_no_remote_write_install_or_shell_string(path):
    text = path.read_text(encoding="utf-8")
    hits = [(n, pat) for n, line in enumerate(text.splitlines(), 1) for pat in FORBIDDEN
            if re.search(pat, line, re.I)]
    assert not hits, f"{path.name}: forbidden text at {hits}"


def test_the_grep_catches_what_it_should():
    bad = ["git push origin main", "subprocess.run(['git', 'push'])", "gh pr create", "tea pr merge 1",
           "fj release create v1", "./install.sh --yes", "subprocess.run(cmd, shell=True)", "os.system('x')",
           "git -C x fetch", "git worktree remove x", "git branch -D x", "git reset --hard", "brew install just"]
    for line in bad:
        assert any(re.search(p, line, re.I) for p in FORBIDDEN), line


SUBPROCESS_CALLS = {"run", "Popen", "call", "check_call", "check_output"}


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.name)
def test_subprocess_calls_are_list_form(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr in SUBPROCESS_CALLS and getattr(f.value, "id", "") == "subprocess":
            first = node.args[0] if node.args else None
            assert isinstance(first, (ast.List, ast.Name)), f"{path.name}:{node.lineno}: argv must be a list"
            assert not any(k.arg in ("shell", "executable") for k in node.keywords), f"{path.name}:{node.lineno}"


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.name)
def test_scripts_are_small_pep723(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[:4] == ["# /// script", '# requires-python = ">=3.11"', "# dependencies = []", "# ///"]
    assert len(lines) <= 150, f"{path.name}: {len(lines)} lines"


def _code_lines() -> list[str]:
    lines = JUSTFILE.read_text(encoding="utf-8").splitlines()
    return [ln for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]


def test_justfile_is_a_dispatcher_only():
    code = _code_lines()
    assert "set positional-arguments" in code and "set dotenv-load := false" in code
    assert not [ln for ln in code if "`" in ln], "no backticks (evaluated at parse time outside --dry-run)"
    for ln in code:
        for expr in re.findall(r"\{\{(.*?)\}\}", ln):
            assert re.fullmatch(r"quote\((justfile\(\)|justfile_directory\(\) / \"bin\" / \"[a-z_]+\.py\")\)", expr), ln
    assert not [ln for ln in code if ":=" in ln and not ln.startswith("set ")], "no variables (just --set)"
    headers = [ln for ln in code if not ln.startswith((" ", "\t", "set ", "["))]
    bodies = [ln for ln in code if ln.startswith((" ", "\t"))]
    assert len(headers) == len(bodies) <= 10, "one line per recipe, at most 10 recipes"
    for h in headers:
        assert re.fullmatch(r"[a-z_][a-z-]*( \*args)?:", h), f"no dependencies, no named parameters: {h!r}"
    menu = "    @just --justfile {{quote(justfile())}} --list"
    body_re = r'    @uv run --quiet --script \{\{quote\(justfile_directory\(\) / "bin" / "([a-z_]+\.py)"\)\}\} "\$@"'
    for b in bodies:
        m = re.fullmatch(body_re, b)
        assert b == menu or (m and (ROOT / "bin" / m.group(1)).is_file()), b
    attrs = [ln for ln in code if ln.startswith("[")]
    assert attrs == ["[no-cd]"] * len(headers)


def test_every_script_but_the_library_has_a_recipe():
    used = set(re.findall(r'"bin" / "([a-z_]+\.py)"', JUSTFILE.read_text(encoding="utf-8")))
    assert used == {p.name for p in SCRIPTS} - {"instr_common.py"}
