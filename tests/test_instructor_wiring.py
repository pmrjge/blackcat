"""The deterministic instructor (tools/instructor/) as the stack wires it: the settings.json permission
rules (exactly one allow rule per public recipe, the exact menu rule, an absolute Edit deny on the
directory), the installer's `just` formula, and the recipes run through a real `just` (skipped
without one).

Why one rule per recipe: `just` options before the recipe name (`--command`, `--shell`, `--shell-arg`,
`--set`, `--justfile`) choose what runs, so `Bash(just -f tools/instructor/justfile *)` would approve
any command; after the recipe name every token is a recipe argument, passed as "$@" to the recipe's
script, whose argparse allowlist refuses anything else (exit 2).

Run: uv run --no-project --python 3.13 --with pytest pytest -q tests/test_instructor_wiring.py
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / "dot-claude" / "settings.json"
JUSTFILE = ROOT / "tools" / "instructor" / "justfile"
DEVTOOLS = ROOT / "lib" / "devtools.sh"
PREFIX = "just -f tools/instructor/justfile"
RECIPES = ["check-suite", "ff-merge", "worktree-audit"]
MENU_RULE = f"Bash({PREFIX} --list)"
INSTR_DENY = "Edit(//**/tools/instructor/**)"       # absolute: every tools/instructor on the machine
# the only other Bash allow rule settings.json has: toolsmith's executor (tests/test_toolsmith.py pins it)
OTHER_BASH = ["Bash(__CLAUDE_DIR__/bin/stack-install *)"]
JUST = shutil.which("just")
STATUS_RE = re.compile(r"^(OK|FAIL|NOOP) ([a-z-]+)((?: [a-z_]+=\S+)*) log=(\S+)$")


def perms():
    return json.loads(SETTINGS.read_text(encoding="utf-8"))["permissions"]


def justfile_recipes():
    """Recipe names from the justfile's header lines (`name:` or `name *args:`)."""
    return re.findall(r"^([a-z_][a-z-]*)(?: \*args)?:[ \t]*$", JUSTFILE.read_text(encoding="utf-8"), re.MULTILINE)


# ---------------------------------------------------------------- settings.json
def test_the_public_recipes_are_the_decided_three():
    """A new recipe fails here until its allow rule (or the decision to leave it prompting) is made."""
    names = justfile_recipes()
    assert [n for n in names if not n.startswith("_")] == RECIPES
    assert [n for n in names if n.startswith("_")] == ["_menu"]


def test_one_allow_rule_per_recipe_plus_the_exact_menu_rule():
    allow = perms()["allow"]
    bash = [r for r in allow if r.startswith("Bash(")]
    assert len(bash) == len(set(bash)), bash
    assert sorted(bash) == sorted([f"Bash({PREFIX} {r} *)" for r in RECIPES] + [MENU_RULE] + OTHER_BASH)


def test_no_wildcard_before_the_recipe_name():
    """The only `*` in an instructor rule is the trailing argument wildcard after the recipe name."""
    for rule in perms()["allow"]:
        if not rule.startswith("Bash(") or rule in OTHER_BASH:
            continue
        head = rule[len("Bash("):-1]
        if rule == MENU_RULE:
            assert "*" not in head
            continue
        assert head.endswith(" *") and "*" not in head[:-2], rule
        prefix, recipe = head[:-2].rsplit(" ", 1)
        assert prefix == PREFIX and recipe in RECIPES, rule


def test_no_other_rule_names_just():
    """No broader allow or ask rule elsewhere (`Bash(just *)`, `Bash(just:*)`) reaches the instructor."""
    p = perms()
    other = [r for k in ("allow", "ask") for r in p.get(k, [])
             if re.search(r"\bjust\b", r) and not r.startswith(f"Bash({PREFIX} ")]
    assert not other, other


def test_the_instructor_directory_is_edit_denied_machine_wide():
    """One deny rule, anchored at the filesystem root (`//`, as in the permissions docs' `Read(//**/.env)`):
    the relative `Edit(**/tools/instructor/**)` covered only the session's own tree, so a worktree session
    with the main checkout as an additional directory could Write `<main>/tools/instructor/justfile`, which
    the allow rules run. Edit rules cover every built-in file-editing tool (Write, NotebookEdit); a
    `Write(...)` path rule is never consulted, so none may stand in for it."""
    p = perms()
    instr = [r for r in p["deny"] if "tools/instructor" in r]
    assert instr == [INSTR_DENY], instr
    assert "Edit(**/tools/instructor/**)" not in p["deny"]
    assert not [r for k in ("allow", "ask") for r in p.get(k, []) if "tools/instructor" in r and
                not r.startswith(f"Bash({PREFIX} ")]


# ---------------------------------------------------------------- installer
def test_installer_offers_just_in_the_deps_batch():
    items = re.search(r'^BREW_ITEMS="(.*?)"', DEVTOOLS.read_text(encoding="utf-8"), re.MULTILINE | re.DOTALL).group(1)
    assert "DEPS formula just cmd:just" in items.splitlines()


# ---------------------------------------------------------------- the recipes through a real just
needs_just = pytest.mark.skipif(JUST is None, reason="just is not installed")


def env():
    return {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "JUST_"))}


def just(*args, cwd, timeout=180):
    return subprocess.run([JUST, "-f", str(JUSTFILE), *args], cwd=cwd, env=env(), text=True,
                          capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL, check=False)


def git(*args, cwd):
    return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
                           "-c", "init.defaultBranch=main", "-c", "user.name=t",
                           "-c", "user.email=t@example.invalid", *args],
                          cwd=cwd, env=env(), text=True, capture_output=True, check=True,
                          stdin=subprocess.DEVNULL).stdout.strip()


@pytest.fixture
def scratch(tmp_path):
    """A repository `m` on main and a worktree `wt` on branch feat, one commit ahead."""
    m, wt = tmp_path / "m", tmp_path / "wt"
    m.mkdir()
    git("init", "-q", cwd=m)
    (m / "a.txt").write_text("a\n")
    git("add", "a.txt", cwd=m)
    git("commit", "-q", "-m", "a", cwd=m)
    git("worktree", "add", "-q", "-b", "feat", str(wt), cwd=m)
    (wt / "b.txt").write_text("b\n")
    git("add", "b.txt", cwd=wt)
    git("commit", "-q", "-m", "b", cwd=wt)
    return m, wt


def status(cp):
    lines = cp.stdout.splitlines()
    assert len(lines) == 1, (cp.stdout, cp.stderr)
    m = STATUS_RE.match(lines[0])
    assert m, lines[0]
    return m.group(1), m.group(2), dict(f.split("=", 1) for f in m.group(3).split())


@needs_just
def test_menu_lists_the_public_recipes(tmp_path):
    for args in (["--list"], []):                       # the default recipe is the menu
        cp = just(*args, cwd=tmp_path)
        assert cp.returncode == 0, cp.stderr
        listed = re.findall(r"^\s+([a-z_][a-z-]*)", cp.stdout, re.MULTILINE)
        assert [n for n in listed if n != "_menu"] == sorted(RECIPES), cp.stdout
        assert "_menu" not in listed


@needs_just
def test_worktree_audit_runs_through_just(scratch):
    _, wt = scratch
    cp = just("worktree-audit", cwd=wt)                 # [no-cd]: the caller's checkout
    st, verb, kv = status(cp)
    assert (cp.returncode, st, verb) == (0, "OK", "worktree-audit"), cp.stderr
    assert kv["worktrees"] == "2" and kv["unmerged"] == "1"
    assert list((wt / ".claude-work" / "instr").glob("worktree-audit-*.log"))


@needs_just
def test_check_suite_dry_run_runs_nothing(scratch):
    m, _ = scratch
    cp = just("check-suite", "--dry-run", "--only", "lint-agents", cwd=m)
    st, verb, kv = status(cp)
    assert (cp.returncode, st, verb, kv.get("dry_run")) == (0, "OK", "check-suite", "1"), cp.stderr


@needs_just
def test_ff_merge_through_just_moves_main_and_its_checkout(scratch):
    m, wt = scratch
    new = git("rev-parse", "feat", cwd=m)
    cp = just("ff-merge", "--branch", "feat", "--suite", "none", cwd=wt)
    st, verb, kv = status(cp)
    assert (cp.returncode, st, verb, kv.get("merged")) == (0, "OK", "ff-merge", "1"), cp.stderr
    assert git("rev-parse", "main", cwd=m) == new and (m / "b.txt").read_text() == "b\n"
    again = just("ff-merge", "--branch", "feat", "--suite", "none", cwd=wt)
    assert (again.returncode, status(again)[0]) == (3, "NOOP")


@needs_just
@pytest.mark.parametrize("planted", [".python-version", "tools/.python-version", "uv.toml"])
@pytest.mark.parametrize("recipe", RECIPES)
def test_recipes_ignore_planted_uv_config(tmp_path, planted, recipe):
    """uv looks for .python-version (and uv.toml, pyproject.toml) in the ancestors of the script's
    directory, files outside tools/instructor/ that an agent can write; a planted interpreter path
    there must never run (`uv run --no-config`)."""
    proj = tmp_path / "proj"
    shutil.copytree(JUSTFILE.parent, proj / "tools" / "instructor",
                    ignore=shutil.ignore_patterns("__pycache__", ".claude-work"))
    marker, fake = tmp_path / "ran", tmp_path / "fakepy"
    fake.write_text(f'#!/bin/sh\ntouch {marker}\nexec /usr/bin/python3 "$@"\n')
    fake.chmod(0o755)
    text = f'python = "{fake}"\n' if planted == "uv.toml" else f"{fake}\n"
    (proj / planted).write_text(text)
    cp = subprocess.run([JUST, "-f", "tools/instructor/justfile", recipe, "--help"], cwd=proj, env=env(),
                        text=True, capture_output=True, timeout=180, stdin=subprocess.DEVNULL, check=False)
    assert cp.returncode == 0, cp.stderr
    assert not marker.exists(), cp.stderr


@needs_just
@pytest.mark.parametrize("recipe,args", [
    ("ff-merge", ["--branch", "feat; touch {p}"]),
    ("ff-merge", ["--branch", "$(touch {p})"]),
    ("check-suite", ["--repo", "`touch {p}`"]),
    ("worktree-audit", ["--repo", "/tmp/x'; touch {p}; '"]),
    # just's own options after the recipe name are recipe arguments, refused by the script
    ("worktree-audit", ["--shell", "/bin/sh"]),
    ("worktree-audit", ["--command", "touch {p}"]),
    ("check-suite", ["--set", "x", "y"]),
])
def test_arguments_are_never_shell_text_or_just_options(scratch, tmp_path, recipe, args):
    m, wt = scratch
    pwned = tmp_path / "pwned"
    cp = just(recipe, *[a.format(p=pwned) for a in args], cwd=wt)
    assert cp.returncode == 2, (cp.stdout, cp.stderr)
    assert status(cp)[0] == "FAIL" and "reason=bad-arg" in cp.stdout
    assert not pwned.exists()
    assert git("rev-parse", "main", cwd=m) != git("rev-parse", "feat", cwd=m)
