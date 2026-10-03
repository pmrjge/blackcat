"""/override-agent and /reset-agent (agent_guard.py `override-agent` mode on UserPromptExpansion;
the model rewrite in on_agent). Only a user-typed slash command (UserPromptExpansion, main thread,
the stack's user skill) sets or clears an override; nothing an agent writes can.

Run: uv run --python 3.13 --with pytest pytest -q tests/test_override_agent.py
"""
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "dot-claude" / "hooks" / "agent_guard.py"
SKILLS = ROOT / "dot-claude" / "skills"
PREFIXES = ("STACK_", "BLACKCAT_", "GOD_", "SCREEN_", "STRIP_", "CLAUDE_CODE_", "ANTHROPIC_DEFAULT_")

_spec = importlib.util.spec_from_file_location("agent_guard_override", GUARD)
G = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G)


@pytest.fixture
def env(tmp_path):
    e = {k: v for k, v in os.environ.items() if not k.startswith(PREFIXES)}
    e["XDG_STATE_HOME"] = str(tmp_path / "state")
    return e


def run(ev, env, *args, **knobs):
    p = subprocess.run([sys.executable, str(GUARD), *args], input=json.dumps(ev),
                       capture_output=True, text=True, env=dict(env, **knobs), timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout) if p.stdout.strip() else None


def sid():
    return "s-" + uuid.uuid4().hex[:8]


def state(env, s):
    return Path(env["XDG_STATE_HOME"]) / "claude-agent-stack" / s


def expansion(s, args, name="override-agent", **kw):
    ev = {"session_id": s, "hook_event_name": "UserPromptExpansion", "prompt_id": "p1",
          "expansion_type": "slash_command", "command_name": name, "command_args": args,
          "command_source": "userSettings", "prompt": "/%s %s" % (name, args)}
    ev.update(kw)
    return ev


def command(s, args, env, name="override-agent", knobs=None, **kw):
    out = run(expansion(s, args, name, **kw), env, "override-agent", **(knobs or {}))
    assert out["decision"] == "block"
    assert out["hookSpecificOutput"] == {"hookEventName": "UserPromptExpansion",
                                         "suppressOriginalPrompt": True}
    return out["reason"]


def agent(s, child, by_type="blackcat", by=None, **ti):
    ev = {"session_id": s, "hook_event_name": "PreToolUse", "tool_name": "Agent",
          "prompt_id": "p1", "tool_use_id": "tu-" + uuid.uuid4().hex[:8], "agent_type": by_type,
          "tool_input": dict({"subagent_type": child, "prompt": "do it"}, **ti)}
    if by:
        ev["agent_id"] = by
    return ev


def spawned_model(s, child, env, **kw):
    out = run(agent(s, child, **kw), env)
    hso = (out or {}).get("hookSpecificOutput") or {}
    assert hso.get("permissionDecision") != "deny", hso
    return (hso.get("updatedInput") or {}).get("model"), out


# ------------------------------------------------------------------ parser
@pytest.mark.parametrize("name,args,want", [
    ("override-agent", "orchestrator fable", ("set", "orchestrator", "fable")),
    ("override-agent", "  Orchestrator   FABLE ", ("set", "orchestrator", "fable")),
    ("override-agent", "scout haiku", ("set", "scout", "haiku")),
    ("override-agent", "list", ("list",)),
    ("reset-agent", "orchestrator", ("reset", "orchestrator")),
    ("reset-agent", "all", ("reset", "all")),
])
def test_parser_accepts(name, args, want):
    assert G.parse_override_command(name, args) == want


@pytest.mark.parametrize("name,args,why", [
    ("override-agent", "", "usage"),
    ("override-agent", "orchestrator", "usage"),
    ("override-agent", "orchestrator fable high", "two arguments, no effort"),
    ("override-agent", "orchestrator opus fable", "two arguments, no effort"),
    ("override-agent", "orchestrator - high", "two arguments, no effort"),
    ("override-agent", "orchestrator -", "unknown model"),
    ("override-agent", "nosuch opus", "unknown agent"),
    ("override-agent", "general-purpose opus", "unknown agent"),
    ("override-agent", "orchestrator-copy opus", "unknown agent"),
    ("override-agent", "blackcat sonnet", "main thread"),
    ("override-agent", "orchestrator gpt5", "unknown model"),
    ("override-agent", "orchestrator claude-opus-5-5", "unknown model"),
    ("override-agent", "orchestrator inherit", "unknown model"),
    ("reset-agent", "", "usage"),
    ("reset-agent", "orchestrator scout", "usage"),
    ("reset-agent", "nosuch", "unknown agent"),
    ("agent-override", "orchestrator opus", "unknown command"),     # the old names are gone
    ("agent-reset", "orchestrator", "unknown command"),
])
def test_parser_rejects(name, args, why):
    with pytest.raises(G.OverrideError) as exc:
        G.parse_override_command(name, args)
    assert why in str(exc.value)


@pytest.mark.parametrize("args", [
    "orchestrator opus\n", "orchestrator\nopus", "orchestrator opus; rm -rf ~",
    "orchestrator $(id) opus", "orchestrator `id`", "orchestrator opus && echo",
    "orchestrator opus | cat", "orchestrator\topus", "orchestrator opus > /tmp/x",
    "../agents/orchestrator opus", "orchestrator opus high", "orchestrator оpus",
    "orchestrator opus #", "x" * 121, None, 7,
])
def test_parser_rejects_injection(args):
    with pytest.raises(G.OverrideError):
        G.parse_override_command("override-agent", args)


def test_valid_sets_match_claude_code():
    # the Agent tool's `model` enum and the frontmatter effort levels (Claude Code 2.1.287)
    assert G.OVERRIDE_MODELS == ("sonnet", "opus", "haiku", "fable")
    assert G.OVERRIDE_EFFORTS == G.EFFORT_ORDER == ("low", "medium", "high", "xhigh", "max")


def test_overridable_agents_are_the_stack_agents_with_files():
    files = {p.stem for p in (ROOT / "dot-claude" / "agents").glob("*.md")}
    got = set(G.override_agents())
    assert got == (set(G.AGENTS) & files) - {"blackcat"}
    assert "orchestrator" in got and "main-coder" in got


# ------------------------------------------------------------------ the effort table
TABLE = json.loads((ROOT / "dot-claude" / "hooks" / "agent_effort.json").read_text())
ENV_IDS = dict(re.findall(r"(?m)^ANTHROPIC_DEFAULT_([A-Z]+)_MODEL=(\S+)",
                          (ROOT / "stack.env.example").read_text()))


def test_table_covers_every_agent_and_model_with_supported_levels():
    agents = TABLE["agents"]
    assert set(agents) == set(G.override_agents())
    ids = dict(fable=TABLE["models"]["alias_defaults"]["fable"], **{k.lower(): v for k, v in ENV_IDS.items()})
    for a, row in agents.items():
        assert set(row) == set(G.OVERRIDE_MODELS), a
        for m, level in row.items():
            assert level in G.OVERRIDE_EFFORTS, (a, m)
            # the stack's own model IDs take every level, so the shipped values stand unclamped
            assert level in G.model_effort_levels(ids[m], TABLE), (a, m, ids[m])
    assert "initial" in TABLE["_about"].lower() and TABLE["version"] == 1


def test_table_follows_rule_v1():
    order = G.OVERRIDE_EFFORTS
    tier = {"haiku": 1, "sonnet": 2, "opus": 3, "fable": 4}
    for a, row in TABLE["agents"].items():
        dm, de = G.agent_defaults(a)
        i = order.index(de)
        want = {m: order[i] for m in row}
        want["haiku"] = order[max(0, i - 1)]
        for m in ("sonnet", "opus", "fable"):
            if tier[m] < tier[dm] and de != "max":
                want[m] = order[min(order.index("xhigh"), i + 1)]
        assert row == want, a
    # the classes the user named: planners/heads higher, lookups lower
    assert TABLE["agents"]["ninja-coder"]["opus"] in ("xhigh", "max")
    assert TABLE["agents"]["scout"]["opus"] == "low" and TABLE["agents"]["oracle"]["opus"] == "low"


@pytest.mark.parametrize("mid,levels", [
    ("claude-opus-5-5", ["low", "medium", "high", "xhigh", "max"]),
    ("claude-fable-5-1", ["low", "medium", "high", "xhigh", "max"]),
    ("claude-opus-4-6", ["low", "medium", "high", "max"]),
    ("claude-sonnet-4-6", ["low", "medium", "high", "max"]),
    ("claude-opus-4-5-20251101", ["low", "medium", "high"]),
    ("claude-haiku-4-5-20251001", []),
    ("claude-3-7-sonnet-latest", []),
])
def test_model_levels(mid, levels):
    assert G.model_effort_levels(mid, TABLE) == levels


@pytest.mark.parametrize("level,levels,want", [
    ("xhigh", ["low", "medium", "high", "max"], "high"),
    ("max", ["low", "medium", "high"], "high"),
    ("low", ["medium", "high"], "medium"),
    ("high", [], None),
    ("medium", list(G.OVERRIDE_EFFORTS), "medium"),
])
def test_clamp(level, levels, want):
    assert G.clamp_effort(level, levels) == want


# ------------------------------------------------------------------ the command
def test_set_uses_the_table_and_writes_private_state(env):
    s = sid()
    msg = command(s, "orchestrator sonnet", env,
                  knobs={"ANTHROPIC_DEFAULT_SONNET_MODEL": ENV_IDS["SONNET"]})
    assert "this session only" in msg and "model   opus -> sonnet (%s)" % ENV_IDS["SONNET"] in msg
    assert "effort  high -> xhigh (table; recorded, not applied" in msg
    f = state(env, s) / "agent-overrides.json"
    assert stat.S_IMODE(f.stat().st_mode) == 0o600
    obj = json.loads(f.read_text())
    assert obj["session_id"] == s
    e = obj["overrides"]["orchestrator"]
    assert (e["model"], e["effort"], e["effort_source"], e["model_id"]) == (
        "sonnet", "xhigh", "table", ENV_IDS["SONNET"])
    # unset: the alias itself, taken as a current model
    assert "model   opus -> opus (opus)" in command(sid(), "code-reviewer opus", env)
    log = [json.loads(x) for x in (state(env, s) / "agent-overrides.log").read_text().splitlines()]
    assert log[-1]["event"] == "set" and log[-1]["effort"] == "xhigh"


def test_effort_is_clamped_to_the_resolved_model(env):
    s = sid()
    msg = command(s, "orchestrator sonnet", env, knobs={"ANTHROPIC_DEFAULT_SONNET_MODEL": "claude-sonnet-4-6"})
    assert "effort  high -> high (table, xhigh clamped to high for claude-sonnet-4-6" in msg
    msg = command(s, "scout haiku", env, knobs={"ANTHROPIC_DEFAULT_HAIKU_MODEL": "claude-haiku-4-5-20251001"})
    assert "-> none (table; claude-haiku-4-5-20251001 takes no effort" in msg
    ov = json.loads((state(env, s) / "agent-overrides.json").read_text())["overrides"]
    assert ov["orchestrator"]["effort"] == "high" and ov["scout"]["effort"] is None
    assert spawned_model(s, "scout", env)[0] == "haiku"


def test_a_stored_effort_survives_a_table_change(env, tmp_path):
    s = sid()
    d = state(env, s)
    ev = expansion(s, "orchestrator fable")
    table = dict(TABLE, agents=dict(TABLE["agents"], orchestrator=dict(TABLE["agents"]["orchestrator"], fable="max")))
    path = tmp_path / "t.json"
    path.write_text(json.dumps(table))
    os.environ["XDG_STATE_HOME"] = env["XDG_STATE_HOME"]
    try:
        G.override_command(ev, table_path=str(path))
        assert G.read_overrides(str(d), s)["orchestrator"]["effort"] == "max"
        path.write_text(json.dumps(TABLE))               # a later install ships another value
        assert G.read_overrides(str(d), s)["orchestrator"]["effort"] == "max"
        assert "max (table" in G.override_command(expansion(s, "list"))
    finally:
        os.environ.pop("XDG_STATE_HOME", None)


def test_missing_table_still_sets_the_model(env, tmp_path):
    os.environ["XDG_STATE_HOME"] = env["XDG_STATE_HOME"]
    try:
        s = sid()
        msg = G.override_command(expansion(s, "coder opus"), table_path=str(tmp_path / "none.json"))
        assert "table missing (rerun install.sh)" in msg
        assert G.read_overrides(G.sdir(s), s)["coder"]["model"] == "opus"
    finally:
        os.environ.pop("XDG_STATE_HOME", None)


def test_invalid_command_changes_nothing(env):
    s = sid()
    msg = command(s, "orchestrator opus; rm -rf ~", env)
    assert msg.startswith("override-agent: arguments may hold only")
    assert "two arguments, no effort" in command(s, "orchestrator opus high", env)
    assert not (state(env, s) / "agent-overrides.json").exists()
    assert "unknown agent" in command(s, "nosuch opus", env)
    assert "unknown model" in command(s, "orchestrator gpt", env)


def test_list_is_read_only_and_shows_the_source(env):
    s = sid()
    msg = command(s, "list", env)
    assert "no overrides" in msg and "orchestrator opus/high" in msg
    assert not (state(env, s) / "agent-overrides.json").exists()
    command(s, "orchestrator fable", env)
    f = state(env, s) / "agent-overrides.json"
    before = (f.read_bytes(), f.stat().st_mtime_ns)
    msg = command(s, "list", env)
    assert "orchestrator         fable (default opus), effort high (table; recorded, not applied" in msg
    assert (f.read_bytes(), f.stat().st_mtime_ns) == before


def test_reset_one_and_all(env):
    s = sid()
    command(s, "orchestrator fable", env)
    command(s, "scout haiku", env)
    msg = command(s, "orchestrator", env, name="reset-agent")
    assert "orchestrator model fable -> opus, effort high -> high" in msg
    assert spawned_model(s, "orchestrator", env)[0] is None
    assert spawned_model(s, "scout", env)[0] == "haiku"
    assert "nothing changed" in command(s, "orchestrator", env, name="reset-agent")
    msg = command(s, "all", env, name="reset-agent")
    assert "scout model haiku -> sonnet, effort low -> low" in msg
    assert not (state(env, s) / "agent-overrides.json").exists()
    assert spawned_model(s, "scout", env)[0] is None


def test_model_force_env_is_reported(env):
    out = run(expansion(sid(), "orchestrator fable"), env, "override-agent",
              CLAUDE_CODE_SUBAGENT_MODEL_FORCE="1")
    assert "CLAUDE_CODE_SUBAGENT_MODEL_FORCE is set" in out["reason"]


# ------------------------------------------------------------------ the rewrite
def test_rewrite_sets_model_only_for_the_named_type(env):
    s = sid()
    assert spawned_model(s, "orchestrator", env)[0] is None
    command(s, "orchestrator fable", env)
    model, out = spawned_model(s, "orchestrator", env, description="plan it")
    assert model == "fable"
    assert out["hookSpecificOutput"]["updatedInput"]["description"] == "orchestrator: plan it"
    assert "permissionDecision" not in out["hookSpecificOutput"]     # nothing loosened
    assert "orchestrator runs on fable" in out["systemMessage"]
    assert spawned_model(s, "scout", env)[0] is None
    log = (state(env, s) / "agent-overrides.log").read_text().splitlines()
    assert json.loads(log[-1])["event"] == "apply"


def test_rewrite_replaces_a_model_the_caller_passed(env):
    s = sid()
    command(s, "scout opus", env)
    model, out = spawned_model(s, "scout", env, model="haiku")
    assert model == "opus"
    assert "the user's /override-agent decides" in out["hookSpecificOutput"]["permissionDecisionReason"]
    # without an override the caller's model is still stripped, as before
    model, out = spawned_model(s, "coder", env, model="haiku")
    assert model is None


def test_rewrite_applies_to_nested_spawns_and_copies(env):
    s = sid()
    command(s, "main-coder sonnet", env)
    command(s, "coder haiku", env)
    assert spawned_model(s, "main-coder", env, by_type="orchestrator", by="orch1")[0] == "sonnet"
    assert spawned_model(s, "coder-copy", env, by_type="coder", by="cod1")[0] == "haiku"


def test_gates_still_refuse_with_an_override(env):
    s = sid()
    command(s, "god-coder sonnet", env)
    out = run(agent(s, "god-coder", by_type="blackcat"), env)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "model" not in json.dumps(out["hookSpecificOutput"].get("updatedInput") or {})


def test_session_isolation(env):
    a, b = sid(), sid()
    command(a, "orchestrator fable", env)
    assert spawned_model(a, "orchestrator", env)[0] == "fable"
    assert spawned_model(b, "orchestrator", env)[0] is None
    # a copy of session a's file in session b's dir names a, so b ignores it
    (state(env, b)).mkdir(parents=True, exist_ok=True)
    (state(env, b) / "agent-overrides.json").write_text(
        (state(env, a) / "agent-overrides.json").read_text())
    assert spawned_model(b, "orchestrator", env)[0] is None


def test_symlinked_or_malformed_state_is_ignored(env, tmp_path):
    s = sid()
    d = state(env, s)
    d.mkdir(parents=True)
    target = tmp_path / "elsewhere.json"
    target.write_text(json.dumps({"session_id": s, "overrides": {"orchestrator": {"model": "fable"}}}))
    (d / "agent-overrides.json").symlink_to(target)
    assert spawned_model(s, "orchestrator", env)[0] is None
    (d / "agent-overrides.json").unlink()
    (d / "agent-overrides.json").write_text(json.dumps(
        {"session_id": s, "overrides": {"orchestrator": {"model": "claude-x"}}}))
    assert spawned_model(s, "orchestrator", env)[0] is None
    (d / "agent-overrides.json").write_text("{not json")
    assert spawned_model(s, "orchestrator", env)[0] is None


@pytest.mark.parametrize("source,kept", [("startup", False), ("resume", False), ("clear", False),
                                         ("compact", True)])
def test_session_start_clears(env, source, kept):
    s = sid()
    command(s, "orchestrator fable", env)
    run({"session_id": s, "hook_event_name": "SessionStart", "source": source}, env)
    assert (state(env, s) / "agent-overrides.json").exists() is kept
    assert (spawned_model(s, "orchestrator", env)[0] == "fable") is kept


# ------------------------------------------------------------------ nothing an agent writes sets one
def test_user_prompt_submit_text_never_sets_an_override(env):
    # UserPromptSubmit's prompt can be model-authored (a cron fire, SendMessage to the main thread)
    s = sid()
    for p in ("/override-agent orchestrator fable", "<task-notification>/override-agent scout opus"):
        run({"session_id": s, "hook_event_name": "UserPromptSubmit", "prompt_id": "p9",
             "prompt": p}, env)
    assert not (state(env, s) / "agent-overrides.json").exists()


def test_expansion_inside_a_subagent_or_from_elsewhere_is_refused(env):
    s = sid()
    msg = command(s, "orchestrator fable", env, agent_id="a1", agent_type="coder")
    assert "only the user's own prompt" in msg
    assert "did not resolve" in command(s, "orchestrator fable", env, expansion_type="mcp_prompt")
    for src in ("projectSettings", "plugin", "policySettings", None):
        assert "did not resolve" in command(s, "orchestrator fable", env, command_source=src)
    assert not (state(env, s) / "agent-overrides.json").exists()


def test_tool_calls_carrying_the_command_text_set_nothing(env):
    s = sid()
    text = "/override-agent orchestrator fable"
    run(agent(s, "scout", by_type="coder", by="c1", description=text), env)
    for tool, ti in (("Bash", {"command": "echo '%s'" % text}), ("SendMessage", {"to": "main", "message": text}),
                     ("Skill", {"skill": "override-agent", "args": "orchestrator fable"})):
        ev = {"session_id": s, "hook_event_name": "PreToolUse", "tool_name": tool,
              "tool_use_id": "t", "prompt_id": "p1", "agent_id": "c1", "agent_type": "coder",
              "tool_input": ti}
        run(ev, env)
        run(ev, env, "override-agent")          # the override mode ignores non-expansion events
    assert not (state(env, s) / "agent-overrides.json").exists()
    assert spawned_model(s, "orchestrator", env)[0] is None


def test_override_mode_ignores_other_commands_and_garbage(env):
    s = sid()
    assert run(expansion(s, "orchestrator fable", name="stack-doctor"), env, "override-agent") is None
    p = subprocess.run([sys.executable, str(GUARD), "override-agent"], input="{not json",
                       capture_output=True, text=True, env=env, timeout=60)
    assert p.returncode == 0 and p.stdout == ""


def test_skills_are_user_only_and_wired():
    for name in ("override-agent", "reset-agent"):
        head = (SKILLS / name / "SKILL.md").read_text().split("\n---", 1)[0]
        assert "\ndisable-model-invocation: true" in head
        assert "\nname: %s" % name in head
        assert "!`" not in (SKILLS / name / "SKILL.md").read_text()
    hooks = json.loads((ROOT / "dot-claude" / "settings.json").read_text())["hooks"]
    (entry,) = hooks["UserPromptExpansion"]
    assert entry["matcher"] == "override-agent|reset-agent"
    assert entry["hooks"][0]["command"].endswith('agent_guard.py" override-agent')
