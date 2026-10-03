"""/agent-override and /agent-reset (agent_guard.py `agent-override` mode on UserPromptExpansion;
the model rewrite in on_agent). Only a user-typed slash command (UserPromptExpansion, main thread,
the stack's user skill) sets or clears an override; nothing an agent writes can.

Run: uv run --python 3.13 --with pytest pytest -q tests/test_agent_override.py
"""
import importlib.util
import json
import os
import stat
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "dot-claude" / "hooks" / "agent_guard.py"
SKILLS = ROOT / "dot-claude" / "skills"
PREFIXES = ("STACK_", "BLACKCAT_", "GOD_", "SCREEN_", "STRIP_", "CLAUDE_CODE_")

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


def expansion(s, args, name="agent-override", **kw):
    ev = {"session_id": s, "hook_event_name": "UserPromptExpansion", "prompt_id": "p1",
          "expansion_type": "slash_command", "command_name": name, "command_args": args,
          "command_source": "userSettings", "prompt": "/%s %s" % (name, args)}
    ev.update(kw)
    return ev


def command(s, args, env, name="agent-override", **kw):
    out = run(expansion(s, args, name, **kw), env, "agent-override")
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
    ("agent-override", "orchestrator fable", ("set", "orchestrator", "fable", None)),
    ("agent-override", "orchestrator fable high", ("set", "orchestrator", "fable", "high")),
    ("agent-override", "  Orchestrator   FABLE  xhigh ", ("set", "orchestrator", "fable", "xhigh")),
    ("agent-override", "code-reviewer - max", ("set", "code-reviewer", None, "max")),
    ("agent-override", "scout haiku -", ("set", "scout", "haiku", None)),
    ("agent-override", "list", ("list",)),
    ("agent-reset", "orchestrator", ("reset", "orchestrator")),
    ("agent-reset", "all", ("reset", "all")),
])
def test_parser_accepts(name, args, want):
    assert G.parse_override_command(name, args) == want


@pytest.mark.parametrize("name,args,why", [
    ("agent-override", "", "usage"),
    ("agent-override", "orchestrator", "usage"),
    ("agent-override", "orchestrator opus fable high", "usage"),
    ("agent-override", "nosuch opus", "unknown agent"),
    ("agent-override", "general-purpose opus", "unknown agent"),
    ("agent-override", "orchestrator-copy opus", "unknown agent"),
    ("agent-override", "blackcat sonnet", "main thread"),
    ("agent-override", "orchestrator gpt5", "unknown model"),
    ("agent-override", "orchestrator claude-opus-5-5", "unknown model"),
    ("agent-override", "orchestrator inherit", "unknown model"),
    ("agent-override", "orchestrator opus extreme", "unknown effort"),
    ("agent-override", "orchestrator opus 3", "unknown effort"),
    ("agent-override", "orchestrator - -", "nothing to change"),
    ("agent-override", "orchestrator -", "nothing to change"),
    ("agent-reset", "", "usage"),
    ("agent-reset", "orchestrator scout", "usage"),
    ("agent-reset", "nosuch", "unknown agent"),
    ("agent-other", "orchestrator opus", "unknown command"),
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
        G.parse_override_command("agent-override", args)


def test_valid_sets_match_claude_code():
    # the Agent tool's `model` enum and the frontmatter effort levels (Claude Code 2.1.287)
    assert G.OVERRIDE_MODELS == ("sonnet", "opus", "haiku", "fable")
    assert G.OVERRIDE_EFFORTS == G.EFFORT_ORDER == ("low", "medium", "high", "xhigh", "max")


def test_overridable_agents_are_the_stack_agents_with_files():
    files = {p.stem for p in (ROOT / "dot-claude" / "agents").glob("*.md")}
    got = set(G.override_agents())
    assert got == (set(G.AGENTS) & files) - {"blackcat"}
    assert "orchestrator" in got and "main-coder" in got


# ------------------------------------------------------------------ the command
def test_set_writes_private_state_and_reports(env):
    s = sid()
    msg = command(s, "orchestrator fable high", env)
    assert "this session only" in msg and "model  opus -> fable" in msg
    assert "effort high -> high" in msg and "NOT enforced" in msg
    f = state(env, s) / "agent-overrides.json"
    assert stat.S_IMODE(f.stat().st_mode) == 0o600
    obj = json.loads(f.read_text())
    assert obj["session_id"] == s
    assert obj["overrides"]["orchestrator"]["model"] == "fable"
    assert obj["overrides"]["orchestrator"]["effort"] == "high"
    log = [json.loads(x) for x in (state(env, s) / "agent-overrides.log").read_text().splitlines()]
    assert log[-1]["event"] == "set" and log[-1]["agent"] == "orchestrator"


def test_dash_keeps_the_other_half(env):
    s = sid()
    command(s, "orchestrator fable", env)
    msg = command(s, "orchestrator - xhigh", env)
    assert "model  fable -> fable" in msg and "effort high -> xhigh" in msg
    ov = json.loads((state(env, s) / "agent-overrides.json").read_text())["overrides"]
    assert ov["orchestrator"]["model"] == "fable" and ov["orchestrator"]["effort"] == "xhigh"
    msg = command(s, "code-reviewer - low", env)
    assert "model  opus (unchanged)" in msg
    assert spawned_model(s, "code-reviewer", env)[0] is None      # effort only: no model rewrite


def test_invalid_command_changes_nothing(env):
    s = sid()
    msg = command(s, "orchestrator opus; rm -rf ~", env)
    assert msg.startswith("agent-override: arguments may hold only")
    assert not (state(env, s) / "agent-overrides.json").exists()
    assert "unknown agent" in command(s, "nosuch opus", env)
    assert "unknown model" in command(s, "orchestrator gpt", env)


def test_list_is_read_only(env):
    s = sid()
    msg = command(s, "list", env)
    assert "no overrides" in msg and "orchestrator opus/high" in msg
    assert not (state(env, s) / "agent-overrides.json").exists()
    command(s, "orchestrator fable xhigh", env)
    f = state(env, s) / "agent-overrides.json"
    before = (f.read_bytes(), f.stat().st_mtime_ns)
    msg = command(s, "list", env)
    assert "orchestrator" in msg and "opus -> fable" in msg and "xhigh (recorded, not enforced)" in msg
    assert (f.read_bytes(), f.stat().st_mtime_ns) == before


def test_reset_one_and_all(env):
    s = sid()
    command(s, "orchestrator fable", env)
    command(s, "scout haiku low", env)
    msg = command(s, "orchestrator", env, name="agent-reset")
    assert "orchestrator model fable -> opus" in msg
    assert spawned_model(s, "orchestrator", env)[0] is None
    assert spawned_model(s, "scout", env)[0] == "haiku"
    assert "nothing changed" in command(s, "orchestrator", env, name="agent-reset")
    msg = command(s, "all", env, name="agent-reset")
    assert "scout model haiku -> sonnet, effort low -> low" in msg
    assert not (state(env, s) / "agent-overrides.json").exists()
    assert spawned_model(s, "scout", env)[0] is None


def test_model_force_env_is_reported(env):
    out = run(expansion(sid(), "orchestrator fable"), env, "agent-override",
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
    assert "the user's /agent-override decides" in out["hookSpecificOutput"]["permissionDecisionReason"]
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
    for p in ("/agent-override orchestrator fable", "<task-notification>/agent-override scout opus"):
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
    text = "/agent-override orchestrator fable"
    run(agent(s, "scout", by_type="coder", by="c1", description=text), env)
    for tool, ti in (("Bash", {"command": "echo '%s'" % text}), ("SendMessage", {"to": "main", "message": text}),
                     ("Skill", {"skill": "agent-override", "args": "orchestrator fable"})):
        ev = {"session_id": s, "hook_event_name": "PreToolUse", "tool_name": tool,
              "tool_use_id": "t", "prompt_id": "p1", "agent_id": "c1", "agent_type": "coder",
              "tool_input": ti}
        run(ev, env)
        run(ev, env, "agent-override")          # the override mode ignores non-expansion events
    assert not (state(env, s) / "agent-overrides.json").exists()
    assert spawned_model(s, "orchestrator", env)[0] is None


def test_override_mode_ignores_other_commands_and_garbage(env):
    s = sid()
    assert run(expansion(s, "orchestrator fable", name="stack-doctor"), env, "agent-override") is None
    p = subprocess.run([sys.executable, str(GUARD), "agent-override"], input="{not json",
                       capture_output=True, text=True, env=env, timeout=60)
    assert p.returncode == 0 and p.stdout == ""


def test_skills_are_user_only_and_wired():
    for name in ("agent-override", "agent-reset"):
        head = (SKILLS / name / "SKILL.md").read_text().split("\n---", 1)[0]
        assert "\ndisable-model-invocation: true" in head
        assert "\nname: %s" % name in head
        assert "!`" not in (SKILLS / name / "SKILL.md").read_text()
    hooks = json.loads((ROOT / "dot-claude" / "settings.json").read_text())["hooks"]
    (entry,) = hooks["UserPromptExpansion"]
    assert entry["matcher"] == "agent-override|agent-reset"
    assert entry["hooks"][0]["command"].endswith('agent_guard.py" agent-override')
