"""Round-3 security checks of agent_guard.py.

R3-T3-RELAY: web content reaches an agent through what others hand it (a descendant's report, a
SendMessage either way, a spawn prompt from a tainted agent); such an agent can't write the shared
memory either.

Run: uv run --with pytest pytest -q tests/test_guard_round3.py
"""
import json
import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from guard_harness import Env  # noqa: E402

REMEMBER = "mcp__neural-memory__nmem_remember"


def tool_ev(env, tool, agent_id, agent_type, **ti):
    return env.base("PreToolUse", tool_name=tool, tool_use_id="toolu_" + uuid.uuid4().hex[:12],
                    agent_id=agent_id, agent_type=agent_type, tool_input=ti)


def remember(env, agent_id, agent_type):
    return env.run(tool_ev(env, REMEMBER, agent_id, agent_type, content="x", tags=["p"]))


def web_fetch(env, agent_id, agent_type):
    env.run(tool_ev(env, "WebFetch", agent_id, agent_type, url="https://example.org"),
            args=("budget",))


def spawn(env, parent_id, parent_type, child, child_id, status="async_launched", start=True):
    """`parent_id` spawns `child_id`; returns the PreToolUse event (its tool_use_id)."""
    pre = env.pre_agent(child, agent_id=parent_id, agent_type=parent_type)
    assert env.run(pre).decision != "deny"
    if start:
        env.run(env.start(child_id, child))
    if status is not None:
        env.run(env.post_agent(pre, child_id, status=status))
    return pre


def denied_from(r, source):
    return r.decision == "deny" and "web content can have reached this agent" in r.reason \
        and source in r.reason


@pytest.mark.parametrize("web_child", ["scout", "researcher", "browser-operator"])
def test_parent_of_a_web_reading_child_cannot_remember(web_child):
    env = Env()
    spawn(env, "O1", "orchestrator", web_child, "W1")
    assert denied_from(remember(env, "O1", "orchestrator"), "W1")


def test_report_of_a_tainted_child_taints_every_ancestor():
    env = Env()
    spawn(env, "O1", "orchestrator", "main-coder", "M1")
    spawn(env, "M1", "main-coder", "coder", "C1", status="completed")
    assert remember(env, "O1", "orchestrator").decision == "allow(no-output)"
    web_fetch(env, "C1", "coder")                       # the grandchild reads a page
    assert denied_from(remember(env, "M1", "main-coder"), "C1")
    assert denied_from(remember(env, "O1", "orchestrator"), "C1")
    r = remember(env, "C1", "coder")
    assert r.decision == "deny" and "read web content" in r.reason


def test_siblings_and_the_main_thread_do_not_join():
    """A clean agent keeps memory writes: a sibling's taint (both spawned by the untracked main
    thread, or by one parent before it was tainted) doesn't reach it."""
    env = Env()
    spawn(env, None, "blackcat", "researcher", "R1")
    spawn(env, None, "blackcat", "coder", "C1")
    assert remember(env, "C1", "coder").decision == "allow(no-output)"
    spawn(env, "O1", "orchestrator", "coder", "C2")      # spawned before any web input
    spawn(env, "O1", "orchestrator", "scout", "S1")
    assert remember(env, "C2", "coder").decision == "allow(no-output)"


def test_spawn_prompt_from_a_tainted_agent_taints_the_child():
    env = Env()
    web_fetch(env, "M1", "main-coder")
    pre = spawn(env, "M1", "main-coder", "coder", "C1")                   # background child
    assert denied_from(remember(env, "C1", "coder"), "the prompt that spawned coder C1")
    assert os.path.exists(os.path.join(env.sdir(), "web-spawned", pre["tool_use_id"]))
    # a foreground child still running: matched through its meta.json (no registry parent yet)
    pre = spawn(env, "M1", "main-coder", "coder", "C2", status=None)
    meta = os.path.join(env.proj, env.sid, "subagents", "agent-C2.meta.json")
    with open(meta, "w") as f:
        json.dump({"agentType": "coder", "spawnDepth": 2, "toolUseId": pre["tool_use_id"],
                   "parentAgentId": "M1"}, f)
    assert denied_from(remember(env, "C2", "coder"), "the prompt that spawned coder C2")
    # a child the same clean agent spawns is not marked
    spawn(env, "X1", "main-coder", "coder", "C3")
    assert remember(env, "C3", "coder").decision == "allow(no-output)"


def test_send_message_relays_both_ways():
    env = Env()
    spawn(env, "O1", "orchestrator", "researcher", "R1")
    spawn(env, "O2", "orchestrator", "main-coder", "M1")
    spawn(env, "O2", "orchestrator", "coder", "C1")
    assert remember(env, "M1", "main-coder").decision == "allow(no-output)"
    # M1 asks R1 (not its child): R1's reply reaches M1
    assert env.run(env.send("R1", agent_id="M1", agent_type="main-coder")).decision != "deny"
    assert denied_from(remember(env, "M1", "main-coder"), "R1")
    # C1 is messaged by the now tainted M1: M1's message reaches C1
    assert env.run(env.send("C1", agent_id="M1", agent_type="main-coder")).decision != "deny"
    assert denied_from(remember(env, "C1", "coder"), "R1")
    for a, b in (("M1", "R1"), ("R1", "M1"), ("M1", "C1"), ("C1", "M1")):
        assert os.path.exists(os.path.join(env.sdir(), "web-relay", a, b))


def test_send_to_an_unregistered_web_reader_taints_the_caller():
    env = Env()
    names = os.path.join(env.sdir(), "names")
    os.makedirs(names, exist_ok=True)
    with open(os.path.join(names, "digger.json"), "w") as f:     # named, id not yet known
        json.dump({"type": "researcher", "id": None, "by": "main", "ts": 0}, f)
    assert env.run(env.send("digger", agent_id="M1", agent_type="main-coder")).decision != "deny"
    r = remember(env, "M1", "main-coder")
    assert r.decision == "deny" and "read web content" in r.reason


def test_relay_needs_the_policy_and_leaves_clean_agents_alone():
    env = Env()
    spawn(env, "O1", "orchestrator", "coder", "C1", status="completed")
    spawn(env, "O1", "orchestrator", "code-reviewer", "V1", status="completed")
    assert remember(env, "O1", "orchestrator").decision == "allow(no-output)"
    off = Env(STACK_POLICY="off")
    spawn(off, "O1", "orchestrator", "scout", "S1")
    assert remember(off, "O1", "orchestrator").decision == "allow(no-output)"


def test_web_source_fails_closed_past_the_node_cap(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "dot-claude" / "hooks"))
    import agent_guard as G
    d = tmp_path / "s"
    (d / "agents").mkdir(parents=True)
    chain = ["A0", "A1", "A2", "A3", "A4"]
    for parent, child in zip(chain, chain[1:]):
        (d / "agents" / (child + ".json")).write_text(
            json.dumps({"id": child, "type": "coder", "parent": parent}))
    assert G.web_source(str(d), "A0", {}) is None
    monkeypatch.setattr(G, "WEB_SOURCE_MAX_NODES", 2)
    assert "more than 2 linked agents" in G.web_source(str(d), "A0", {})


# ---------------------------------------------------------------- R3-CACHES, R3-GITENV: session-env
GUARD = str(ROOT / "dot-claude" / "hooks" / "agent_guard.py")


def session_env(home, env_file, stdin='{"hook_event_name": "SessionStart", "source": "startup"}'):
    import subprocess
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_ENV_FILE",)}
    env["HOME"] = str(home)
    if env_file is not None:
        env["CLAUDE_ENV_FILE"] = str(env_file)
    return subprocess.run([sys.executable, GUARD, "session-env"], input=stdin, env=env,
                          capture_output=True, text=True, timeout=30)


def sourced(env_file, *names, **pre):
    import subprocess
    script = '. "$1"; for n in %s; do eval "printf \'%%s\\n\' \\"\\${$n-UNSET}\\""; done' % " ".join(names)
    env = {"PATH": os.environ["PATH"], **pre}
    out = subprocess.run(["bash", "-c", script, "_", str(env_file)], env=env, capture_output=True,
                         text=True, timeout=30, check=True).stdout
    return out.splitlines()


def test_session_env_writes_every_cache_under_the_sandbox_root_once(tmp_path):
    sys.path.insert(0, str(ROOT / "dot-claude" / "hooks"))
    import agent_guard as G
    home, env_file = tmp_path / "home", tmp_path / "sessionstart-hook-0.sh"
    home.mkdir()
    env_file.write_text("export OTHER=1")                 # another hook's line, no newline
    for _ in range(3):
        r = session_env(home, env_file)
        assert r.returncode == 0 and not r.stdout, r
    text = env_file.read_text()
    assert text.startswith("export OTHER=1\n") and text.count(G.SANDBOX_ENV_MARK) == 1
    root = str(home / ".cache" / "claude-sandbox")
    assert os.path.isdir(root) and oct(os.stat(root).st_mode & 0o777) == "0o700"
    names = [k for k, _ in G.SANDBOX_ENV]
    values = sourced(env_file, "OTHER", *names)
    assert values[0] == "1"
    for (key, sub), value in zip(G.SANDBOX_ENV, values[1:]):
        assert value == os.path.join(root, sub), key
    assert {"UV_CACHE_DIR", "npm_config_cache", "PRE_COMMIT_HOME", "XDG_CACHE_HOME", "CARGO_HOME",
            "GOMODCACHE", "GRADLE_USER_HOME", "COURSIER_CACHE", "HF_HOME"} <= set(names)
    maven, git = sourced(env_file, "MAVEN_OPTS", "GIT_CONFIG_PARAMETERS", MAVEN_OPTS="-Xmx2g",
                         GIT_CONFIG_PARAMETERS="'core.pager=cat'")
    assert maven == "-Xmx2g -Dmaven.repo.local=%s/m2" % root
    assert git == "'core.pager=cat' 'credential.helper='"
    maven, git = sourced(env_file, "MAVEN_OPTS", "GIT_CONFIG_PARAMETERS")
    assert maven == "-Dmaven.repo.local=%s/m2" % root and git == "'credential.helper='"


def test_session_env_quotes_an_odd_home_and_never_blocks(tmp_path):
    home, env_file = tmp_path / "my home $x", tmp_path / "env.sh"
    home.mkdir()
    assert session_env(home, env_file).returncode == 0
    uv, maven = sourced(env_file, "UV_CACHE_DIR", "MAVEN_OPTS")
    assert uv == str(home / ".cache" / "claude-sandbox" / "uv")
    assert maven == "UNSET"                      # MAVEN_OPTS is split on spaces: not set at all
    r = session_env(home, None)                  # no CLAUDE_ENV_FILE: a warning, rc 0
    assert r.returncode == 0 and "sandbox env not written" in r.stderr
    r = session_env(home, tmp_path / "missing-dir" / "env.sh", stdin="not json")
    assert r.returncode == 0 and "sandbox env not written" in r.stderr
