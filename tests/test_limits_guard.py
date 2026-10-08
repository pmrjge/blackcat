"""agent_guard.py and the S6 learned limits (W2): the per-session immutable snapshot in the guard.

Run: uv run --python 3.12 --with pytest pytest -q tests/test_limits_guard.py
Tests T8-T11 and T18 of the S6 design (s6-design-v2 section 4) plus the guard-side pieces of plan
step 2: the turn gate, hard.agent and soft.session, limit-hits.jsonl and prompt-windows.jsonl, the
MCP cap from the snapshot's turns, the limits/ prune skip, the lean reader's cost. The hook runs
under the hook interpreter (/usr/bin/python3) in its own XDG_STATE_HOME; nothing here touches the
stack's state folder.
"""
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "dot-config" / "dot-claude" / "hooks"
GUARD = HOOKS / "agent_guard.py"
PY = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable
HEX16 = re.compile(r"^[0-9a-f]{16}$")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


L = _load("stack_limits", HOOKS / "stack_limits.py")
SEED = json.loads((HOOKS / "stack_limits_seed.json").read_text())["vars"]


def frontmatter_turns(atype):
    text = (ROOT / "dot-config" / "dot-claude" / "agents" / (atype + ".md")).read_text()
    return int(re.search(r"^maxTurns:\s*(\d+)\s*$", text, re.MULTILINE).group(1))


# ---------------------------------------------------------------- harness
class Sess:
    """One session: its transcripts laid out like ~/.claude/projects/<project>/, a state folder
    of its own, and the hook run under the hook interpreter."""

    def __init__(self, tmp, monkeypatch):
        self.tmp = tmp
        self.state = tmp / "xdg"
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("STACK_", "BLACKCAT_", "SCREEN_", "CLAUDE_CODE_MAX"))}
        self.env.update(XDG_STATE_HOME=str(self.state), STACK_USAGE_COLLECT="0",
                        CLAUDE_CONFIG_DIR=str(tmp / "cfg"))
        for k in [k for k in os.environ if k.startswith("STACK_")]:
            monkeypatch.delenv(k)
        monkeypatch.setenv("XDG_STATE_HOME", str(self.state))      # for the in-process stack_limits
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp / "cfg"))
        monkeypatch.setenv("STACK_USAGE_COLLECT", "0")
        L._ENV_WARNED.clear()
        self.new()

    def new(self):
        self.sid = "s-" + uuid.uuid4().hex[:12]
        proj = self.tmp / "projects" / "p"
        (proj / self.sid / "subagents").mkdir(parents=True)
        self.main = proj / (self.sid + ".jsonl")
        self.main.write_text(json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n")
        self.subs = proj / self.sid / "subagents"
        return self

    # paths
    @property
    def root(self):
        return self.state / "claude-agent-stack"

    @property
    def sdir(self):
        return self.root / self.sid

    @property
    def snap(self):
        return self.root / "limits" / "snapshots" / (self.sid + ".json")

    def snapdoc(self):
        return json.loads(self.snap.read_text())

    def hits(self):
        p = self.sdir / "limit-hits.jsonl"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    # events
    def base(self, event, **kw):
        ev = {"session_id": self.sid, "hook_event_name": event, "transcript_path": str(self.main),
              "cwd": str(self.tmp)}
        ev.update(kw)
        return ev

    def start(self, source="startup", **extra):
        return self.run(self.base("SessionStart", source=source), **extra)

    def prompt(self, pid, **extra):
        return self.run(self.base("UserPromptSubmit", prompt_id=pid, prompt="go"), **extra)

    def sub_start(self, aid, atype, **extra):
        return self.run(self.base("SubagentStart", agent_id=aid, agent_type=atype), **extra)

    def tool(self, tool, aid="A1", atype="coder", prompt="p1", **ti):
        ev = self.base("PreToolUse", tool_name=tool, tool_use_id="tu-" + uuid.uuid4().hex[:8],
                       prompt_id=prompt, tool_input=ti or {"file_path": "x"})
        if aid:
            ev.update(agent_id=aid, agent_type=atype)
        return ev

    def run(self, ev, args=("budget",), **extra):
        if ev.get("hook_event_name") != "PreToolUse":
            args = ()
        e = dict(self.env, **{k: str(v) for k, v in extra.items()})
        return subprocess.run([PY, str(GUARD), *args], input=json.dumps(ev), capture_output=True,
                              text=True, env=e, timeout=60, check=False)

    def calls(self, aid, n, tokens=10):
        """n API calls (no timestamp: they count toward the current run) in a subagent's file."""
        with open(self.subs / f"agent-{aid}.jsonl", "a") as f:
            for _ in range(n):
                mid = uuid.uuid4().hex[:10]
                f.write(json.dumps({"type": "assistant", "requestId": "r" + mid, "message": {
                    "id": mid, "usage": {"input_tokens": tokens}}}) + "\n")

    def main_calls(self, tokens):
        mid = uuid.uuid4().hex[:10]
        with open(self.main, "a") as f:
            f.write(json.dumps({"type": "assistant", "requestId": "r" + mid, "message": {
                "id": mid, "usage": {"input_tokens": tokens}}}) + "\n")


def out(p):
    """(decision, reason or additionalContext, systemMessage) of a hook run."""
    assert p.returncode == 0, p.stderr
    if not p.stdout.strip():
        return "allow", None, None
    o = json.loads(p.stdout)
    h = o.get("hookSpecificOutput") or {}
    return (h.get("permissionDecision", "allow"),
            h.get("permissionDecisionReason") or h.get("additionalContext"), o.get("systemMessage"))


@pytest.fixture
def S(tmp_path, monkeypatch):
    return Sess(tmp_path, monkeypatch)


# ---------------------------------------------------------------- T8
def test_T8_snapshot_is_excl_0444_and_kept_on_resume_compact_clear(S):
    p = S.start("startup")
    assert p.returncode == 0, p.stderr
    assert stat.S_IMODE(S.snap.stat().st_mode) == 0o444
    doc = S.snapdoc()
    assert doc["session_id"] == S.sid and doc["source_event"] == "startup"
    assert doc["hash"] == L.snap_hash(doc) and HEX16.match(doc["regime"])
    raw, ino = S.snap.read_bytes(), S.snap.stat().st_ino
    for source in ("resume", "compact", "clear"):
        assert S.start(source, STACK_MAXTURNS_CODER="9").returncode == 0
        assert S.snap.read_bytes() == raw and S.snap.stat().st_ino == ino, source
    assert S.snapdoc()["values"]["turns.coder"] == frontmatter_turns("coder")   # not 9
    # O_EXCL: a file already there (here an altered one) is never replaced at SessionStart
    other = S.new()
    other.snap.parent.mkdir(parents=True, exist_ok=True)
    other.snap.write_text(json.dumps({"schema_version": 1, "session_id": other.sid}))
    before = other.snap.read_bytes()
    assert other.start("startup").returncode == 0
    assert other.snap.read_bytes() == before


def test_T8_session_start_notice_and_collector_skip(S):
    """No notice without a change or fallback; a fallback (unusable live.json) is shown once, as a
    systemMessage of <= 300 chars naming stack_limits.py."""
    assert out(S.start("startup"))[2] is None
    lim = S.root / "limits"
    (lim / "live.json").write_text("{not json")
    S.new()
    msg = out(S.start("startup"))[2]
    assert msg and len(msg) <= 300 and "stack_limits.py" in msg


# ---------------------------------------------------------------- T9
def test_T9_live_json_changed_mid_session_changes_nothing(S):
    turns = frontmatter_turns("coder")
    floor = SEED["turns.coder"]["floor"]
    L.seed()                                               # live.json from the seed
    assert S.start("startup").returncode == 0
    snap = S.snap.read_bytes()
    assert S.snapdoc()["values"]["turns.coder"] == turns
    S.sub_start("A1", "coder")
    S.calls("A1", floor + 1)
    # mid-session: the user freezes turns.coder at its floor (a valid live.json change) ...
    L.cmd_freeze("turns.coder", value=floor)
    assert json.loads((S.root / "limits" / "live.json").read_text())["vars"]["turns.coder"]["frozen"] == floor
    assert out(S.run(S.tool("Read")))[0] == "allow"
    # ... and then live.json is replaced by anything at all
    (S.root / "limits" / "live.json").write_text('{"schema_version": 1, "vars": {"turns.coder": {"value": 1}}}')
    assert out(S.run(S.tool("Read")))[0] == "allow"
    assert out(S.run(S.tool("mcp__exa__web_search_exa", query="x")))[0] == "allow"
    # a resume, compact or clear of this session keeps its snapshot
    S.start("resume")
    assert out(S.run(S.tool("Read")))[0] == "allow" and S.snap.read_bytes() == snap
    # env overrides set mid-session wait for the next session too
    assert out(S.run(S.tool("Read"), STACK_MAXTURNS_CODER=str(floor),
                     STACK_PROMPT_CTX_BUDGET="1"))[0] == "allow"
    # the next session sees the frozen value (live.json repaired by the user's command)
    (S.root / "limits" / "live.json").unlink()
    L.seed()
    L.cmd_freeze("turns.coder", value=floor)
    S.new()
    S.start("startup")
    assert S.snapdoc()["values"]["turns.coder"] == floor and S.snapdoc()["origin"]["turns.coder"] == "frozen"
    S.sub_start("A1", "coder")
    S.calls("A1", floor)
    assert out(S.run(S.tool("Read")))[0] == "allow"          # the last turn of the budget runs
    S.calls("A1", 1)
    d, why, _ = out(S.run(S.tool("Read")))
    assert d == "deny" and "origin frozen" in why


# ---------------------------------------------------------------- T10
def test_T10_altered_snapshot_gives_seed_values_one_line_one_marker(S):
    """An altered snapshot gives the seed values: a turns env override at the call is ignored (only a
    hard.* one below the seed applies, T10b), one stderr line, one marker."""
    S.start("startup", STACK_MAXTURNS_CODER="3")
    doc = S.snapdoc()
    assert doc["values"]["turns.coder"] == 3 and doc["origin"]["turns.coder"] == "env"
    os.chmod(S.snap, 0o644)
    S.snap.write_text(S.snap.read_text().replace('"turns.coder":3', '"turns.coder":4'))
    S.sub_start("A1", "coder")
    S.calls("A1", 5)                                       # past 3 and 4, far below the seed
    p = S.run(S.tool("Read"), STACK_MAXTURNS_CODER="3")
    assert out(p)[0] == "allow"                            # seed values: frontmatter maxTurns
    lines = p.stderr.splitlines()
    assert len(lines) == 1 and "snapshot" in lines[0] and "tamper" in lines[0], p.stderr
    marker = S.sdir / "limits-tamper"
    assert marker.exists()
    mtime = marker.stat().st_mtime_ns
    p = S.run(S.tool("Read"))
    assert out(p)[0] == "allow" and p.stderr == "" and marker.stat().st_mtime_ns == mtime
    S.calls("A1", frontmatter_turns("coder"))
    d, why, _ = out(S.run(S.tool("Read")))
    assert d == "deny" and "seed value" in why and "tamper" in why


def test_T10b_without_a_usable_snapshot_env_only_lowers_the_prompt_cap(S):
    """A tampered snapshot, then a missing one that cannot be written: hard.prompt is the seed (300M)
    unless STACK_PROMPT_CTX_BUDGET at the call is below it; a value above the seed does not raise it
    (the user, 2026-10-08: on a fallback an env value only lowers a hard cap)."""
    S.start("startup")
    os.chmod(S.snap, 0o644)
    S.snap.write_text(S.snap.read_text().replace('"hard.prompt":300000000', '"hard.prompt":300000001'))
    snaps = S.snap.parent
    try:
        for state in ("tamper", "missing"):
            S.prompt("p1")
            S.main_calls(1200)
            d, why, _ = out(S.run(S.tool("Read"), STACK_PROMPT_CTX_BUDGET="1000"))
            assert d == "deny" and why.startswith("Prompt token budget reached"), (state, why)
            assert "STACK_PROMPT_CTX_BUDGET=1000, below the seed" in why and state in why, why
            assert out(S.run(S.tool("Read"), STACK_PROMPT_CTX_BUDGET="400000000"))[0] == "allow"  # 1,200 < 300M
            S.main_calls(300000000)
            d, why, _ = out(S.run(S.tool("Read"), STACK_PROMPT_CTX_BUDGET="400000000"))
            assert d == "deny" and "hard.prompt=300000000, seed value" in why and state in why, why
            S.new()                                        # next: no snapshot, and none can be written
            os.chmod(snaps, 0o500)
    finally:
        os.chmod(snaps, 0o700)
    assert not S.snap.exists()


def test_guard_fallbacks_env_only_lowers_hard_caps(S, monkeypatch):
    """The guard's own fallbacks follow the same rule: the built-in constants (stack_limits.py
    unusable) and the seed of an event without a session id."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("agent_guard_fallbacks", GUARD)
    G = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(G)
    monkeypatch.setenv("STACK_PROMPT_CTX_BUDGET", "1000")
    monkeypatch.setenv("STACK_SESSION_CTX_BUDGET", "0")                 # off would raise it: ignored
    b = G.builtin_limits()
    assert (b.get("hard.prompt"), b.get("hard.session")) == (1000, 1920000000)
    lim = G.session_limits({"session_id": None})
    assert lim.state == "nosession" and (lim.get("hard.prompt"), lim.origin["hard.prompt"]) == (1000, "env")
    assert lim.get("hard.session") == 1920000000 and "below the seed" in lim.where("hard.prompt")
    monkeypatch.setenv("STACK_PROMPT_CTX_BUDGET", "400000000")
    G._LIMITS.clear()
    assert G.builtin_limits().get("hard.prompt") == 300000000
    lim = G.session_limits({"session_id": None})
    assert (lim.get("hard.prompt"), lim.origin["hard.prompt"]) == (300000000, "seed")


# ---------------------------------------------------------------- T11
def test_T11_subagent_reads_parent_snapshot_turn_gate_and_exempt_calls(S):
    S.start("startup", STACK_MAXTURNS_CODER="3")
    snap = S.snapdoc()["hash"][7:23]
    S.prompt("p1")
    S.sub_start("A1", "coder")
    S.calls("A1", 3)
    # the T-th call keeps its tools (Claude Code's maxTurns lets the last turn run too); the
    # subagent's own hook process has another value in its env: the snapshot wins
    assert out(S.run(S.tool("Read"), STACK_MAXTURNS_CODER="50"))[0] == "allow"
    S.calls("A1", 1)
    d, why, msg = out(S.run(S.tool("Bash", command="ls"), STACK_MAXTURNS_CODER="50"))
    assert d == "deny" and why.startswith("Turn budget reached") and "4 API calls" in why
    assert "STATUS: partial" in why and "stack_limits.py show" in why
    assert "turns.coder=3" in why and "STACK_MAXTURNS_CODER=3" in why
    assert "stack_limits.py show" in msg and "install.sh" not in msg
    # reporting always passes
    for tool, ti in (("SubagentHandback", {"message": "done"}), ("TaskStop", {"task_id": "x"}),
                     ("ToolSearch", {"query": "select:SubagentHandback"}),
                     ("Write", {"file_path": str(S.tmp / ".claude-work" / "j" / "report.md")})):
        assert out(S.run(S.tool(tool, **ti)))[0] == "allow", tool
    # the main hook's own tools (Agent here) are gated too
    ev = S.tool("Agent", subagent_type="scout", prompt="x", description="x")
    assert out(S.run(ev, args=()))[0] == "deny"
    # another agent, and the main thread, are not this run's turns
    S.sub_start("A2", "coder")
    assert out(S.run(S.tool("Read", aid="A2")))[0] == "allow"
    assert out(S.run(S.tool("Read", aid=None)))[0] == "allow"
    # a resume is a new run with a new allowance
    time.sleep(0.01)
    S.sub_start("A1", "coder")
    assert out(S.run(S.tool("Read")))[0] == "allow"
    hit = [h for h in S.hits() if h["kind"] == "turn"]               # one line per firing: Bash, Agent
    assert len(hit) == 2 and {h["agent_id"] for h in hit} == {"A1"} and hit[0]["agent_type"] == "coder"
    assert (hit[0]["value"], hit[0]["limit"], hit[0]["snap"]) == (4, 3, snap)
    assert isinstance(hit[0]["run"], float) and isinstance(hit[0]["ts"], float)


def test_T11_mcp_cap_takes_the_snapshot_turns(S):
    S.start("startup", STACK_MAXTURNS_CODER="4")
    folder = S.sdir / "mcp-calls"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "C1.json").write_text(json.dumps({"calls": 3}))       # no SubagentStart: run None
    ev = S.tool("mcp__exa__web_search_exa", aid="C1", atype="coder", query="x")
    assert out(S.run(ev))[0] == "allow"
    d, why, _ = out(S.run(ev))
    assert d == "deny" and "4 MCP tool calls" in why and "turns.coder=4" in why
    assert [h["kind"] for h in S.hits()] == ["mcp"]
    # STACK_MAX_MCP_CALLS stays a fixed env knob: it is read per call, min with the turns
    (folder / "C2.json").write_text(json.dumps({"calls": 2}))
    ev2 = S.tool("mcp__exa__web_search_exa", aid="C2", atype="coder", query="x")
    assert out(S.run(ev2, STACK_MAX_MCP_CALLS="2"))[0] == "deny"
    S.calls("C1", 4)
    assert out(S.run(S.tool("Read", aid="C1", atype="coder")))[0] == "allow"
    S.calls("C1", 1)
    assert out(S.run(S.tool("Read", aid="C1", atype="coder")))[0] == "deny"


def test_hard_agent_and_soft_session_from_the_snapshot(S):
    S.start("startup", STACK_HARDCTX_SCOUT="1000", STACK_SOFT_SESSION_CTX="1500")
    S.prompt("p1")
    S.sub_start("A1", "scout")
    S.calls("A1", 1, tokens=900)
    assert out(S.run(S.tool("Read", atype="scout")))[0] == "allow"
    S.calls("A1", 1, tokens=200)
    d, why, _ = out(S.run(S.tool("Read", atype="scout")))
    assert d == "deny" and why.startswith("Per-agent token cap reached") and "1,100" in why
    assert "hard.agent.scout=1000" in why and "STATUS: partial" in why and "stack_limits.py show" in why
    S.main_calls(500)                                       # session total 1,600
    d, ctx, _ = out(S.run(S.tool("Read", aid=None)))
    assert d == "allow" and "Soft token limit reached for this session" in ctx
    assert out(S.run(S.tool("Read", aid=None)))[1] is None                 # once
    kinds = [h["kind"] for h in S.hits()]
    assert kinds == ["hard_agent", "soft_session"]
    assert [h["agent_id"] for h in S.hits()] == ["A1", None]


def test_hard_prompt_and_session_deny_texts_name_the_snapshot(S):
    S.start("startup", STACK_PROMPT_CTX_BUDGET="1000")
    S.prompt("p1")
    S.main_calls(1200)
    d, why, msg = out(S.run(S.tool("Read")))
    assert d == "deny" and why.startswith("Prompt token budget reached")
    assert "hard.prompt=1000" in why and "STACK_PROMPT_CTX_BUDGET=1000" in why
    assert "stack_limits.py show" in why and "STATUS: partial" in why
    assert "stack_limits.py show" in msg and "install.sh" not in msg
    S.new()
    S.start("startup")                     # live.json (seeded by the first start): 300M / 1.92B
    assert S.snapdoc()["origin"]["hard.session"] == "live"
    S.prompt("p1")
    S.main_calls(10)
    assert out(S.run(S.tool("Read")))[0] == "allow"
    assert [h["kind"] for h in S.hits()] == []


def test_shipped_prompt_cap_is_300m(S):
    """hard.prompt as shipped (2026-10-08, was 100M): a prompt may use 299,999,999 context tokens;
    the call after 300,000,000 is refused, naming hard.prompt and its live origin."""
    S.start("startup")
    assert S.snapdoc()["values"]["hard.prompt"] == 300000000 and S.snapdoc()["origin"]["hard.prompt"] == "live"
    S.prompt("p1")
    S.main_calls(299999999)
    assert out(S.run(S.tool("Read")))[0] == "allow"
    S.main_calls(1)
    d, why, _ = out(S.run(S.tool("Read")))
    assert d == "deny" and why.startswith("Prompt token budget reached") and "300,000,000" in why
    assert [h["kind"] for h in S.hits()] == ["soft_prompt", "hard_prompt"]     # the 33M warning came first


def test_prompt_windows_one_line_per_human_prompt(S):
    S.start("startup")
    S.prompt("p1")
    S.main_calls(700)
    assert out(S.run(S.tool("Read", aid=None)))[0] == "allow"
    S.prompt("p2")
    S.run(S.base("UserPromptSubmit", prompt_id="n1", prompt="<task-notification>x"))
    lines = [json.loads(x) for x in (S.sdir / "prompt-windows.jsonl").read_text().splitlines()]
    assert [(w["v"], w["prompt_id"], w["base"]) for w in lines] == [(1, "p1", 0), (1, "p2", 700)]
    assert all(isinstance(w["ts"], float) for w in lines)
    assert stat.S_IMODE((S.sdir / "prompt-windows.jsonl").stat().st_mode) == 0o600
    # the collector's reader takes them as they are
    U = _load("stack_usage_for_limits_guard", HOOKS / "stack_usage.py")
    assert [w["base"] for w in U.load_windows(str(S.sdir))] == [0, 700]


def test_limit_hits_meet_the_collector_schema(S):
    S.start("startup", STACK_MAXTURNS_CODER="1")
    S.sub_start("A1", "coder")
    S.calls("A1", 2)
    assert out(S.run(S.tool("Read")))[0] == "deny"
    U = _load("stack_usage_for_limits_guard2", HOOKS / "stack_usage.py")
    got = U.load_hits(str(S.sdir))
    assert len(got) == 1 and got[0][:2] == ("hit_turn", "A1")
    assert U.snapshot_cells(S.sid)["snap"] == S.hits()[0]["snap"]


# ---------------------------------------------------------------- T18
def test_T18_auto_off_snapshot_is_seed_plus_env_overrides(S):
    L.seed()
    L.cmd_freeze("turns.coder", value=SEED["turns.coder"]["floor"])
    p = S.start("startup", STACK_LIMITS_AUTO="0", STACK_MAXTURNS_SCOUT="6", STACK_SESSION_CTX_BUDGET="0")
    assert p.returncode == 0, p.stderr
    doc = S.snapdoc()
    assert doc["auto"] is False
    for v, spec in SEED.items():
        if v == "turns.scout":
            assert (doc["values"][v], doc["origin"][v]) == (6, "env")
        elif v == "hard.session":
            assert (doc["values"][v], doc["origin"][v]) == (None, "env")
        else:
            assert (doc["values"][v], doc["origin"][v]) == (spec["seed"], "seed"), v
    S.sub_start("A1", "scout")
    S.calls("A1", 6)
    assert out(S.run(S.tool("Read", atype="scout")))[0] == "allow"
    S.calls("A1", 1)
    d, why, _ = out(S.run(S.tool("Read", atype="scout")))
    assert d == "deny" and "STACK_MAXTURNS_SCOUT=6" in why


# ---------------------------------------------------------------- lifecycle and cost
def test_prune_keeps_limits_and_missing_snapshot_is_ensured(S):
    old = time.time() - 5 * 86400
    lim = S.root / "limits"
    lim.mkdir(parents=True)
    (lim / "f").write_text("x")
    os.utime(lim / "f", (old, old))
    os.utime(lim, (old, old))
    S.start("startup")
    assert (lim / "f").exists() and S.snap.exists()
    # no SessionStart seen (a hook added mid-session): the first event writes it, without applying
    S.new()
    assert out(S.run(S.tool("Read")))[0] == "allow"
    assert S.snapdoc()["source_event"] == "ensure"


def test_lean_reader_matches_stack_limits_and_costs_under_3ms(S):
    S.start("startup")
    probe = (
        "import importlib.util, json, sys, time\n"
        "spec = importlib.util.spec_from_file_location('g', sys.argv[1])\n"
        "g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)\n"
        "t = time.perf_counter(); lim = g.session_limits({'session_id': sys.argv[2]}, None)\n"
        "dt = time.perf_counter() - t\n"
        "print(json.dumps({'ms': dt * 1e3, 'state': lim.state, 'values': lim.values, 'snap': lim.snap}))\n")
    runs = []
    for _ in range(5):
        p = subprocess.run([PY, "-c", probe, str(GUARD), S.sid], capture_output=True, text=True,
                           env=S.env, timeout=60, check=False)
        assert p.returncode == 0, p.stderr
        runs.append(json.loads(p.stdout))
    ref = L.read_snapshot(S.sid)[0]
    assert all(r["state"] == "ok" and r["values"] == ref["values"] and r["snap"] == ref["hash"][7:23]
               for r in runs)
    best = min(r["ms"] for r in runs)
    print(f"lean snapshot read, fresh process: min {best:.2f} ms over 5")
    assert best <= 3.0, runs


# ---------------------------------------------------------------- STACK_LIMITS_SNAPSHOT in the session
def test_session_env_exports_the_snapshot_path_and_stack_sched_resolves_it(S):
    """session-env writes STACK_LIMITS_SNAPSHOT (stack_limits.snapshot_path of the sid, before any
    snapshot exists) into CLAUDE_ENV_FILE once; a later session id gets its own line, which wins;
    stack_sched.py, run with that file sourced, resolves the session from it."""
    envf = S.tmp / "envfile.sh"
    ev = json.dumps({"session_id": S.sid, "hook_event_name": "SessionStart", "source": "startup"})

    def session_env(ev_json):
        return subprocess.run([PY, str(GUARD), "session-env"], input=ev_json, capture_output=True,
                              text=True, env=dict(S.env, CLAUDE_ENV_FILE=str(envf), HOME=str(S.tmp)),
                              timeout=60, check=False)
    assert not S.snap.exists()
    for _ in range(2):
        assert session_env(ev).returncode == 0
    text = envf.read_text()
    want = f"export STACK_LIMITS_SNAPSHOT={L.snapshot_path(S.sid)}"
    assert text.count(want) == 1 and text.count("claude-agent-stack: sandboxed Bash caches") == 1
    first = S.sid
    S.new()
    assert session_env(ev.replace(first, S.sid)).returncode == 0
    lines = [x for x in envf.read_text().splitlines() if x.startswith("export STACK_LIMITS_SNAPSHOT=")]
    assert lines == [want, f"export STACK_LIMITS_SNAPSHOT={L.snapshot_path(S.sid)}"]
    # no usable id: no line, the rest still written
    assert session_env(json.dumps({"session_id": "../x", "hook_event_name": "SessionStart"})).returncode == 0
    assert len([x for x in envf.read_text().splitlines() if "STACK_LIMITS_SNAPSHOT" in x]) == 2
    probe = ("import importlib.util, sys; spec = importlib.util.spec_from_file_location('s', sys.argv[1]); "
             "m = importlib.util.module_from_spec(spec); sys.modules['s'] = m; spec.loader.exec_module(m); "
             "print(m.session_id())")
    env = {k: v for k, v in S.env.items() if k != "CLAUDE_SESSION_ID"}
    p = subprocess.run(["/bin/sh", "-c", '. "$1" && exec "$2" -c "$3" "$4"', "sh", str(envf), PY, probe,
                        str(HOOKS / "stack_sched.py")], capture_output=True, text=True, env=env, timeout=60,
                       check=False)
    assert p.returncode == 0 and p.stdout.strip() == S.sid, p.stderr
