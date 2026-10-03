"""hooks/read_gate.py: the token gate on reads of generated, vendored, data, media and binary files.

Run: uv run --python 3.12 --with pytest pytest -q tests/test_read_gate.py
"""
import ast
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "dot-claude" / "hooks" / "read_gate.py"
PY = "/usr/bin/python3"   # the hooks' own interpreter, as in settings.json


@pytest.fixture
def env(tmp_path):
    """Environment for the hook: its own state dir and stack.env."""
    (tmp_path / "state").mkdir()
    stack_env = tmp_path / "stack.env"
    stack_env.write_text("")
    return {"XDG_STATE_HOME": str(tmp_path / "state"), "STACK_ENV_FILE": str(stack_env),
            "PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}


def run(env, tool, inp, cwd, agent_type=None, agent_id="a1", session="s1"):
    ev = {"hook_event_name": "PreToolUse", "session_id": session, "cwd": str(cwd), "tool_name": tool,
          "tool_input": inp}
    if agent_id:
        ev["agent_id"] = agent_id
    if agent_type:
        ev["agent_type"] = agent_type
    out = subprocess.run([PY, str(HOOK)], input=json.dumps(ev), capture_output=True, text=True, env=env,
                         timeout=20, check=False)
    assert out.returncode == 0, out.stderr
    if not out.stdout.strip():
        return None
    hso = json.loads(out.stdout)["hookSpecificOutput"]
    assert hso["permissionDecision"] == "deny"
    return hso["permissionDecisionReason"]


def mk(root, rel, data="x"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(data)
    return p


@pytest.fixture
def hugo(tmp_path):
    site = tmp_path / "site"
    mk(site, "hugo.toml", 'title = "t"\n')
    mk(site, "content/post.md")
    mk(site, "public/index.html", "<html></html>")
    return site


@pytest.fixture
def repo(tmp_path):
    """A git repository: dist/ and target/ ignored, build/ and public/ (Vite's source folder) not."""
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    mk(r, ".gitignore", "dist/\n/target\nvendor/\n")
    for rel in ("dist/app.js", "target/debug/x.d", "build/notes.md", "public/favicon.svg", "src/main.ts",
                "vendor/lib/a.php", "node_modules/pkg/index.js", "data/small.csv"):
        mk(r, rel)
    mk(r, "data/big.csv", "a,b\n" * 70000)
    mk(r, ".claude-work/job/big.csv", "a,b\n" * 70000)
    return r


def test_self_test():
    out = subprocess.run([PY, str(HOOK), "--self-test"], capture_output=True, text=True, timeout=30, check=False)
    assert out.returncode == 0 and "ok" in out.stdout, out.stdout + out.stderr


def test_hugo_public_refused_then_identical_retry_passes(env, hugo):
    page = str(hugo / "public" / "index.html")
    why = run(env, "Read", {"file_path": page}, hugo)
    assert why and "generated build output" in why and "repeat this exact call" in why
    assert run(env, "Read", {"file_path": page}, hugo) is None              # the retry
    assert run(env, "Read", {"file_path": page}, hugo) is None              # and after it
    assert run(env, "Read", {"file_path": page, "offset": 10}, hugo)        # a different call
    assert run(env, "Read", {"file_path": page}, hugo, agent_id="a2")       # another agent
    assert run(env, "Read", {"file_path": page}, hugo, session="s2")        # another session
    assert run(env, "Read", {"file_path": str(hugo / "content" / "post.md")}, hugo) is None


def test_read_with_small_limit_passes(env, hugo):
    page = str(hugo / "public" / "index.html")
    assert run(env, "Read", {"file_path": page, "limit": 200}, hugo) is None
    assert run(env, "Read", {"file_path": page, "limit": 500}, hugo)


def test_exempt_agents_and_overrides(env, hugo, repo, tmp_path):
    page = str(hugo / "public" / "index.html")
    assert run(env, "Read", {"file_path": page}, hugo, "verifier") is None
    assert run(env, "Read", {"file_path": page}, hugo, "frontend-engineer-copy", agent_id="c") is None
    assert run(env, "Read", {"file_path": page}, hugo, "coder", agent_id="d")
    big = str(repo / "data" / "big.csv")
    assert run(env, "Read", {"file_path": big}, repo, "data-scientist") is None
    assert run(env, "Read", {"file_path": big}, repo, "verifier", agent_id="v")
    clip = mk(tmp_path, "art/clip.mov")
    assert run(env, "Read", {"file_path": str(clip)}, tmp_path, "motion-designer") is None
    assert run(env, "Read", {"file_path": str(clip)}, tmp_path, "designer") is None
    assert run(env, "Read", {"file_path": str(clip)}, tmp_path, "coder", agent_id="e")
    Path(env["STACK_ENV_FILE"]).write_text("READ_GATE_EXEMPT_BUILD=coder  # mine\n")
    assert run(env, "Read", {"file_path": page}, hugo, "coder", agent_id="f") is None
    assert run(env, "Read", {"file_path": page}, hugo, "verifier", agent_id="g")


def test_git_ignore_decides_ambiguous_dirs(env, repo):
    def read(rel, aid):
        return run(env, "Read", {"file_path": str(repo / rel)}, repo, agent_id=aid)
    assert read("dist/app.js", "1")                  # ignored dist/
    assert read("target/debug/x.d", "2")             # ignored target/
    assert read("vendor/lib/a.php", "3")             # ignored vendor/
    assert read("build/notes.md", "4") is None       # build/ tracked: source
    assert read("public/favicon.svg", "5") is None   # Vite public/: source
    assert read("node_modules/pkg/index.js", "6")    # always gated, ignored or not
    assert read("src/main.ts", "7") is None


def test_data_size_and_claude_work(env, repo):
    assert run(env, "Read", {"file_path": str(repo / "data" / "big.csv")}, repo)
    assert run(env, "Read", {"file_path": str(repo / "data" / "small.csv")}, repo) is None
    assert run(env, "Read", {"file_path": str(repo / ".claude-work" / "job" / "big.csv")}, repo) is None
    assert run(env, "Bash", {"command": "cat .claude-work/job/big.csv"}, repo) is None


@pytest.mark.parametrize("cmd", [
    "grep -rn useState node_modules/",
    "rg useState node_modules",
    "cd data && cat big.csv",
    "find node_modules -name '*.d.ts'",
    "sed 's/a/b/' data/big.csv",
    "awk -F, '{print $1}' data/big.csv",
    "FOO=1 cat dist/app.js",
    "ls -R node_modules",
    "tree node_modules",
    "grep -r foo",                                   # recursive search of a cwd inside node_modules
])
def test_bash_readers_refused(env, repo, cmd):
    cwd = repo / "node_modules" if cmd == "grep -r foo" else repo
    assert run(env, "Bash", {"command": cmd, "description": "x"}, cwd)
    assert run(env, "Bash", {"command": cmd, "description": "other words"}, cwd) is None   # retry


@pytest.mark.parametrize("cmd", [
    "head -n 20 data/big.csv",
    "wc -l data/big.csv",
    "grep -rl useState node_modules/",
    "rg -c useState node_modules",
    "rg useState node_modules | head -20",
    "find node_modules -maxdepth 1",
    "cat data/big.csv > /tmp/x",
    "sed -n '1,20p' data/big.csv",
    "ls node_modules",
    "git status && rg foo src",
    "grep -rn foo src",
    "cat src/main.ts",
    'echo "cat dist/app.js"',
])
def test_bash_cheap_or_ungated_passes(env, repo, cmd):
    assert run(env, "Bash", {"command": cmd}, repo) is None


def test_grep_and_glob_tools(env, repo):
    nm = str(repo / "node_modules")
    assert run(env, "Grep", {"pattern": "x", "path": nm, "output_mode": "content"}, repo)
    assert run(env, "Grep", {"pattern": "x", "path": nm, "output_mode": "count"}, repo) is None
    assert run(env, "Grep", {"pattern": "x", "path": nm, "head_limit": 50}, repo, agent_id="b") is None
    assert run(env, "Grep", {"pattern": "x", "path": str(repo / "src")}, repo) is None
    assert run(env, "Glob", {"pattern": "**/node_modules/**/*.js"}, repo)
    assert run(env, "Glob", {"pattern": "dist/**"}, repo)
    assert run(env, "Glob", {"pattern": "src/**/*.ts"}, repo) is None


def test_read_gate_off(env, hugo):
    page = str(hugo / "public" / "index.html")
    assert run(dict(env, READ_GATE="0"), "Read", {"file_path": page}, hugo) is None
    Path(env["STACK_ENV_FILE"]).write_text("READ_GATE=0\n")
    assert run(env, "Read", {"file_path": page}, hugo) is None


def test_retry_state_is_bounded(env, repo):
    Path(env["STACK_ENV_FILE"]).write_text("READ_GATE_MAX_KEYS=3\n")
    for i in range(6):
        assert run(env, "Read", {"file_path": str(repo / "dist" / "app.js"), "offset": i}, repo)
    state = json.loads((Path(env["XDG_STATE_HOME"]) / "claude-agent-stack" / "s1" / "read-gate.json").read_text())
    assert len(state) == 3


def test_fails_open(env, hugo, tmp_path):
    page = str(hugo / "public" / "index.html")
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")
    assert run(dict(env, XDG_STATE_HOME=str(blocker)), "Read", {"file_path": page}, hugo) is None
    out = subprocess.run([PY, str(HOOK)], input="not json", capture_output=True, text=True, env=env, timeout=20,
                         check=False)
    assert out.returncode == 0 and out.stdout == ""
    assert run(env, "Bash", {"command": "cat 'unbalanced"}, hugo) is None
    assert run(env, "Edit", {"file_path": page}, hugo) is None


def test_example_documents_every_knob():
    """stack.env.example lists each knob with the hook's default (the hook's table is the source)."""
    tree = ast.parse(HOOK.read_text())
    knobs = next(ast.literal_eval(n.value) for n in tree.body
                 if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "KNOBS")
    example = (ROOT / "stack.env.example").read_text()
    for name, (default, _) in knobs.items():
        m = re.search(rf"^#{name}=(.*)$", example, re.MULTILINE)
        assert m, name + " missing from stack.env.example"
        assert m.group(1).strip() == str(default), name


def test_settings_and_installer_wire_the_hook():
    s = json.loads((ROOT / "dot-claude" / "settings.json").read_text())
    groups = [g for g in s["hooks"]["PreToolUse"] if "read_gate.py" in json.dumps(g)]
    assert len(groups) == 1 and groups[0]["matcher"] == "Read|Grep|Glob|Bash"
    assert groups[0]["hooks"][0]["command"] == '"__PYTHON3__" "__CLAUDE_DIR__/hooks/read_gate.py"'
    inst = (ROOT / "install.sh").read_text()
    assert "stage_script 755 hooks/read_gate.py" in inst
    assert '"hooks/read_gate.py"' in inst.split("STACK_SCRIPTS = [", 1)[1].split("]", 1)[0]
    m = re.search(r'^STACK_HOOK_RE = re\.compile\(r"([^"]+)"\)$', inst, re.MULTILINE)
    assert m and re.search(m.group(1), groups[0]["hooks"][0]["command"])
