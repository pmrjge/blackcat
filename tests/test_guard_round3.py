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


def running_named(env, parent_id, parent_type, child, child_id, name):
    """A foreground child spawned with a name, still running: its names/ record has no id yet;
    Claude Code's meta.json ties its agent id to the Agent call."""
    pre = env.pre_agent(child, agent_id=parent_id, agent_type=parent_type, name=name)
    assert env.run(pre).decision != "deny"
    env.run(env.start(child_id, child))
    with open(os.path.join(env.proj, env.sid, "subagents", "agent-%s.meta.json" % child_id), "w") as f:
        json.dump({"agentType": child, "spawnDepth": 2, "toolUseId": pre["tool_use_id"],
                   "parentAgentId": parent_id}, f)
    return pre


def test_send_by_name_to_a_running_agent_links_both_ways():
    """Review: a SendMessage to a name whose agent id isn't known yet (a foreground child) was not
    linked. It is now, through the Agent call that spawned it, in both directions."""
    env = Env()
    running_named(env, "O1", "orchestrator", "coder", "H1", "helper")
    web_fetch(env, "A1", "main-coder")
    assert remember(env, "H1", "coder").decision == "allow(no-output)"
    assert env.run(env.send("helper", agent_id="A1", agent_type="main-coder")).decision != "deny"
    assert denied_from(remember(env, "H1", "coder"), "A1")
    # the other way: a clean agent messages a running named agent that has read the web
    running_named(env, "O1", "orchestrator", "coder", "D2", "digger")
    web_fetch(env, "D2", "coder")
    assert env.run(env.send("digger", agent_id="B1", agent_type="main-coder")).decision != "deny"
    assert denied_from(remember(env, "B1", "main-coder"), "D2")
    # once it has returned, the registry carries the same link (names/ now has its id)
    pre = running_named(env, "O1", "orchestrator", "coder", "E3", "later")
    assert env.run(env.send("later", agent_id="A1", agent_type="main-coder")).decision != "deny"
    os.remove(os.path.join(env.proj, env.sid, "subagents", "agent-E3.meta.json"))
    env.run(env.post_agent(pre, "E3", status="completed"))
    assert denied_from(remember(env, "E3", "coder"), "A1")


def test_a_spawn_whose_taint_cannot_be_recorded_is_refused():
    """Review: a failed web-spawned marker let the child start unmarked; the spawn is refused
    now, holding nothing (a retry once the state dir is writable goes through, and is marked)."""
    env = Env()
    web_fetch(env, "M1", "main-coder")
    blocker = os.path.join(env.sdir(), "web-spawned")
    open(blocker, "w").close()                          # a file where the marker dir goes
    pre = env.pre_agent("coder", agent_id="M1", agent_type="main-coder")
    r = env.run(pre)
    assert r.decision == "deny" and "could not record whether web content reached" in r.reason
    os.remove(blocker)
    pre = spawn(env, "M1", "main-coder", "coder", "C1")
    assert denied_from(remember(env, "C1", "coder"), "the prompt that spawned coder C1")


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
    env["XDG_STATE_HOME"] = str(Path(str(home)).parent / "state")
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
    r = session_env(home, None)                  # no CLAUDE_ENV_FILE: shown to the user (rc 2)
    assert r.returncode == 2 and "NOT set for this session (no CLAUDE_ENV_FILE" in r.stderr
    r = session_env(home, tmp_path / "missing-dir" / "env.sh", stdin="not json")
    assert r.returncode == 2 and "NOT set for this session (FileNotFoundError" in r.stderr


def statusline(sid, state_home, now_offset=0):
    import subprocess
    env = dict(os.environ, XDG_STATE_HOME=str(state_home), NO_COLOR="1")
    data = json.dumps({"session_id": sid, "model": {"display_name": "M"}})
    return subprocess.run([sys.executable, str(ROOT / "dot-claude" / "bin" / "statusline.py")],
                          input=data, env=env, capture_output=True, text=True, timeout=30).stdout


def test_a_failed_session_env_is_recorded_shown_and_on_the_status_line(tmp_path):
    """R4: a session-env failure reaches the user: exit 2 (Claude Code shows a SessionStart
    hook's exit-2 stderr as a hook error notice, the session goes on), a record in the session's
    state dir, and a warning at the front of the status line until a new session succeeds."""
    home, state = tmp_path / "home", tmp_path / "state"
    home.mkdir()
    ok = session_env(home, tmp_path / "env.sh", stdin='{"session_id": "s-ok", "source": "startup"}')
    assert ok.returncode == 0
    rec = json.loads((state / "claude-agent-stack" / "s-ok" / "session-env.json").read_text())
    assert rec["state"] == "ok"
    assert "Bash sandbox env missing" not in statusline("s-ok", state)
    bad = session_env(home, None, stdin='{"session_id": "s-bad", "source": "resume"}')
    assert bad.returncode == 2 and "doctor.sh" in bad.stderr
    rec = json.loads((state / "claude-agent-stack" / "s-bad" / "session-env.json").read_text())
    assert rec["state"] == "failed" and "CLAUDE_ENV_FILE" in rec["reason"]
    assert statusline("s-bad", state).startswith("! Bash sandbox env missing: doctor.sh")
    # a hook that died midway: "running" for longer than the status line waits
    stale = state / "claude-agent-stack" / "s-dead"
    stale.mkdir(parents=True)
    (stale / "session-env.json").write_text(json.dumps({"state": "running", "ts": 1.0}))
    assert "Bash sandbox env missing" in statusline("s-dead", state)
    (stale / "session-env.json").write_text(json.dumps({"state": "running", "ts": __import__("time").time()}))
    assert "Bash sandbox env missing" not in statusline("s-dead", state)
    assert "Bash sandbox env missing" not in statusline("s-none", state)   # never ran: doctor's job


# ---------------------------------------------------------------- R3-SUPPLY: what the diff covers
def test_supply_diff_covers_everything_the_install_ships():
    """The pre-apply diff covers every repo path install.sh reads to build the config dir; the
    question is never asked under --dry-run or --yes, goes to the controlling terminal when stdin
    or stderr isn't one, and with no terminal at all the run stops (R4: never proceeds unasked)."""
    import re
    import subprocess
    text = (ROOT / "install.sh").read_text()
    paths = re.search(r'^SUPPLY_PATHS="([^"]+)"$', text, re.M).group(1).split()
    assert set(paths) == {"dot-claude", "install.sh", "lib", "requirements", "stack.env.example"}
    shipped = set(re.findall(r'"\$HERE/([A-Za-z0-9_.-]+)', text)) | {"dot-claude"}
    shipped -= {"tests", ".git", "legacy"}          # never installed: legacy is a migration source
    tracked = set(subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True,
                                 check=True).stdout.split())
    top = {p.split("/", 1)[0] for p in tracked}
    assert {p for p in shipped if p in top} <= set(paths), shipped - set(paths)
    ask = re.search(r'^if \[ "\$SUPPLY_CHANGED" = 1 \] (.+); then$', text, re.M).group(1)
    for cond in ('[ "$DRY_RUN" = 0 ]', '[ "$ASSUME_YES" = 0 ]'):
        assert cond in ask, cond
    block = text[text.index(ask):text.index('say "2/11')]
    assert "[ -t 0 ] && [ -t 2 ]" in block and "read -r ans </dev/tty" in block
    assert re.search(r"no terminal to ask: rerun with --yes.*\n\s+exit 1", block)


# ---------------------------------------------------------------- R3-INFO: a project under /tmp
def test_a_project_under_a_temp_dir_is_the_projects_not_scratch(tmp_path):
    """Read-only agents: the temp dirs are scratch, but a project checked out there is still the
    project: its tests run like any project's (no scratch content check), its files can't be
    written, and its .claude-work and the rest of the temp dirs stay scratch."""
    sys.path.insert(0, str(ROOT / "dot-claude" / "hooks"))
    import agent_guard as G
    proj = tmp_path / "checkout"
    (proj / "tests").mkdir(parents=True)
    (proj / "src").mkdir()
    (proj / "tests" / "harness.py").write_text("open('out.txt', 'w').write('x')\n")
    (proj / "tests" / "test_a.py").write_text("import harness\n")
    ev = {"cwd": str(proj)}
    assert G.readonly_violation("uv run --with pytest pytest -q tests/", ev) is None
    assert G.readonly_violation("python3 tests/harness.py", ev) is None
    for cmd in ("echo x > src/a.py", "cp tests/harness.py src/b.py", "rm tests/test_a.py",
                "sed -i '' s/x/y/ tests/harness.py"):
        assert G.readonly_violation(cmd, ev), cmd
    other = tmp_path / "elsewhere.txt"
    assert G.readonly_violation("echo x > .claude-work/j/n.txt", ev) is None
    assert G.readonly_violation("echo x > %s" % other, ev) is None
    # a scratch script in the project's .claude-work is still read before it runs
    (proj / ".claude-work").mkdir()
    (proj / ".claude-work" / "w.py").write_text("open('src/a.py', 'w').write('x')\n")
    assert G.readonly_violation("python3 .claude-work/w.py", ev)
    # a cwd that is a temp dir itself (not a project in one) keeps all of it scratch
    import tempfile
    assert G.readonly_violation("echo x > %s" % (proj / "src" / "c.py"),
                                {"cwd": tempfile.gettempdir()}) is None
    # and a project elsewhere doesn't make a temp-dir checkout its own
    assert G.readonly_violation("echo x > %s" % (proj / "src" / "c.py"), {"cwd": str(ROOT)}) is None


def test_the_project_is_claude_project_dir_when_set(tmp_path, monkeypatch):
    """Review: with CLAUDE_PROJECT_DIR set (as for every hook), only that dir is the project: a
    cwd that moved into another temp subdir stays scratch; the project's files stay protected."""
    sys.path.insert(0, str(ROOT / "dot-claude" / "hooks"))
    import agent_guard as G
    proj, moved = tmp_path / "checkout", tmp_path / "moved"
    (proj / "src").mkdir(parents=True)
    moved.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    ev = {"cwd": str(moved)}
    assert G.readonly_violation("echo x > %s" % (moved / "n.txt"), ev) is None
    assert G.readonly_violation("echo x > %s" % (proj / "src" / "a.py"), ev)
    assert G.readonly_violation("echo x > src/a.py", {"cwd": str(proj)})


# ---------------------------------------------------------------- T4: sandbox env, domains, self-test
def test_session_env_redirects_cabal_and_puts_a_julia_depot_first(tmp_path):
    sys.path.insert(0, str(ROOT / "dot-claude" / "hooks"))
    import agent_guard as G
    home, env_file = tmp_path / "home", tmp_path / "env.sh"
    home.mkdir()
    assert session_env(home, env_file).returncode == 0
    cabal, julia, rustup = sourced(env_file, "CABAL_DIR", "JULIA_DEPOT_PATH", "RUSTUP_HOME")
    root = str(home / ".cache" / "claude-sandbox")
    assert cabal == root + "/cabal"
    assert julia == root + "/julia:"          # the trailing ':' keeps Julia's default depots
    assert rustup == "UNSET"                  # ~/.rustup stays the user's (installs stay blocked)
    assert not any(k.startswith(("RUSTUP", "UV_TOOL")) for k, _ in G.SANDBOX_ENV)


def test_network_allowlist_gains_the_package_and_docs_hosts_and_stays_strict():
    s = json.loads((ROOT / "dot-claude" / "settings.json").read_text())
    net = s["sandbox"]["network"]
    assert net["strictAllowlist"] is True
    assert {"code.claude.com", "repo1.maven.org", "repo.maven.apache.org", "hackage.haskell.org",
            "storage.julialang.net"} <= set(net["allowedDomains"])
    assert not any("*" == d or d.startswith("*.") and d.count(".") < 2
                   for d in net["allowedDomains"])


def _self_test_with_probe_error(monkeypatch, err):
    import errno as _errno
    import io
    import tempfile
    sys.path.insert(0, str(ROOT / "dot-claude" / "hooks"))
    import agent_guard as G
    real = tempfile.mkdtemp

    def mkdtemp(*a, **kw):
        if str(kw.get("prefix", "")).startswith(".self-test-"):
            raise OSError(getattr(_errno, err), os.strerror(getattr(_errno, err)))
        return real(*a, **kw)
    monkeypatch.setattr(tempfile, "mkdtemp", mkdtemp)
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    rc = G.self_test()
    return rc, out.getvalue()


def test_self_test_reports_a_sandboxed_state_dir_as_a_warning(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    rc, out = _self_test_with_probe_error(monkeypatch, "EPERM")
    assert rc == 0 and "WARN state dir" in out and "self-test: ok" in out, out
    rc, out = _self_test_with_probe_error(monkeypatch, "EACCES")      # a real permission problem
    assert rc == 1 and "FAIL state dir" in out, out


def test_self_test_probes_xdg_state_home(tmp_path):
    import subprocess
    env = dict(os.environ, XDG_STATE_HOME=str(tmp_path))
    p = subprocess.run(["/usr/bin/python3", str(ROOT / "dot-claude" / "hooks" / "agent_guard.py"),
                        "--self-test"], capture_output=True, text=True, env=env, timeout=120, check=False)
    assert p.returncode == 0 and "WARN" not in p.stdout, p.stdout + p.stderr
    assert (tmp_path / "claude-agent-stack").is_dir()
