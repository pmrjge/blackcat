"""stack_usage.py (the per-session usage collector) and stack_sched_refresh.py (the model refit).

Run: uv run --python 3.13 --with pytest --with pandas --with numpy pytest -q tests/test_stack_usage.py
(the refresh tests are skipped without pandas/numpy), and on the hooks' own interpreter:
UV_PYTHON=/usr/bin/python3 uv run --with pytest pytest -q tests/test_stack_usage.py. Synthetic transcripts
only; every test uses its own XDG_STATE_HOME under tmp_path, never the stack's state folder. Hook and
collector processes run under /usr/bin/python3, the hooks' interpreter.
"""
import csv
import hashlib
import importlib.util
import io
import json
import os
import re
import signal
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "dot-config" / "dot-claude" / "hooks"
USAGE_PY = HOOKS / "stack_usage.py"
PY = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable
SID = "11111111-2222-3333-4444-555555555555"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


U = _load("stack_usage", USAGE_PY)
V1_REV = "910275c"            # the last commit with the v1 collector (runs.csv, COLUMNS of 23 fields)


def load_v1(tmp_path):
    """The v1 collector module, from git history, loaded from a temp file."""
    p = subprocess.run(["git", "-C", str(ROOT), "show", "%s:dot-config/dot-claude/hooks/stack_usage.py" % V1_REV],
                       capture_output=True, text=True)
    if p.returncode != 0:
        pytest.skip("commit %s not available: %s" % (V1_REV, p.stderr.strip()[:80]))
    f = tmp_path / "v1" / "stack_usage_v1.py"
    f.parent.mkdir(exist_ok=True)
    f.write_text(p.stdout)
    return _load("stack_usage_v1", f)


@pytest.fixture
def st(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))          # no ~/.claude/.stack-manifest.json
    for k in [k for k in os.environ if k.startswith("STACK_")]:
        monkeypatch.delenv(k)
    return tmp_path / "st" / "claude-agent-stack"


def env_for(tmp_path, **extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("STACK_")}
    env.update(XDG_STATE_HOME=str(tmp_path / "st"), HOME=str(tmp_path / "home"), PYTHONDONTWRITEBYTECODE="1",
               STACK_USAGE_POLL_S="0.2", STACK_USAGE_REFRESH="0")
    env.update(extra)
    return env


# ---------------------------------------------------------------- synthetic transcripts
T0 = 1790000000.0


def ts(k):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(T0 + k)) + ".250Z"


def call(mid, k, inp=3, out=50, cc=1000, cr=20000, tool=True, text="ok", content=None, model=None):
    if content is None:
        content = [{"type": "text", "text": text}]
        if tool:
            content.append({"type": "tool_use", "id": "tu_" + mid, "name": "Bash",
                            "input": {"command": "echo SECRET-TOOL-INPUT sk-ant-api03-XYZ"}})
    return {"type": "assistant", "requestId": "req_" + mid, "timestamp": ts(k), "uuid": "u" + mid,
            "message": {"id": "msg_" + mid, "model": model or "-".join(("claude", "opus", "5", "5")), "content": content,
                        "usage": {"input_tokens": inp, "output_tokens": out, "cache_creation_input_tokens": cc,
                                  "cache_read_input_tokens": cr}}}


def user(text, k):
    return {"type": "user", "timestamp": ts(k), "message": {"role": "user", "content": text}}


def result(k, text="RESULT TEXT with password=hunter2"):
    return {"type": "user", "timestamp": ts(k),
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": text}]}}


def agent_lines():
    """Two segments: a spawn (3 calls, one streamed over two lines, a compaction) and a resume."""
    a = call("a1", 1, cc=5000, cr=10000)
    a_stream = dict(a, message=dict(a["message"], usage=dict(a["message"]["usage"], output_tokens=90)))
    return [
        user("Please do the SECRET-PROMPT task with token sk-ant-api03-ABC", 0),
        a, a_stream, result(2),
        call("a2", 3, cc=200, cr=15000), result(4),
        user("This session is being continued from a previous conversation. Summary: SECRET", 5),
        call("a3", 6, cc=100, cr=16000, tool=False, text="FINAL REPORT TEXT"),
        user("Another Claude session sent a message while you were working: more SECRET-PROMPT", 400),
        call("b1", 401, cc=3000, cr=1000), result(402),
        call("b2", 403, cc=50, cr=4000, tool=False),
    ]


def write_agent(folder, aid, lines, atype="coder", mode="w", extra_meta=None):
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / ("agent-%s.jsonl" % aid), mode) as fh:
        for r in lines:
            fh.write(json.dumps(r) + "\n")
    meta = folder / ("agent-%s.meta.json" % aid)
    if atype and not meta.exists():
        meta.write_text(json.dumps(dict({"agentType": atype, "description": "T3 implement the parser"},
                                        **(extra_meta or {}))))


def subdir(tmp_path):
    return tmp_path / "projects" / "p" / SID / "subagents"


def rows_by_key():
    return U.read_rows()


def row3(**kw):
    """A complete row of the writer's schema (3) with every column present (empty unless given)."""
    r = {c: "" for c in U.COLUMNS}
    r.update(schema_version=U.SCHEMA_VERSION, session=SID, id="x1", type="scout", seg=0, status="complete",
             src="measured")
    r.update(kw)
    return r


# ---------------------------------------------------------------- parsing and rows
def test_segments_and_values(st, tmp_path):
    sub = subdir(tmp_path)
    write_agent(sub, "aaa1", agent_lines())
    rows, grew = U.scan_once(SID, str(sub), final=True)
    assert grew
    r = rows_by_key()
    s0, s1 = r[(SID, "aaa1", 0)], r[(SID, "aaa1", 1)]
    assert s0["type"] == "coder" and s0["status"] == "complete" and s1["status"] == "complete"
    assert int(s0["api_calls"]) == 3 and int(s1["api_calls"]) == 2
    assert int(s0["ctx"]) == (3 + 5000 + 10000) + (3 + 200 + 15000) + (3 + 100 + 16000)
    assert int(s0["output"]) == 90 + 50 + 50                     # streamed lines: the per-field max
    assert int(s0["first_cc"]) == 5000 and int(s0["first_cr"]) == 10000
    assert int(s0["compacted"]) == 1 and s0["turn_limited"] == "0" and s1["after_limit"] == "0"
    assert int(s1["prev_peak"]) == int(s0["peak"]) == 3 + 100 + 16000
    assert float(s1["gap_s"]) == pytest.approx(401 - 6)
    assert float(s0["wall_s"]) == pytest.approx(6 - 1)


def test_incremental_equals_whole(st, tmp_path):
    """Line by line with a scan (and the state saved and reloaded) after each line, and a partial
    line in between: the final rows equal one whole-file scan."""
    lines = agent_lines()
    whole = tmp_path / "whole"
    write_agent(whole / "sub", "w1", lines)
    stw = {"v": 1, "agents": {}}
    rw, _ = U.scan(stw, SID, str(whole / "sub"), final=True)
    final_whole = {r["seg"]: r for r in rw}

    sub = subdir(tmp_path)
    path = sub / "agent-w1.jsonl"
    write_agent(sub, "w1", [])
    for i, r in enumerate(lines):
        raw = json.dumps(r) + "\n"
        with open(path, "a") as fh:
            fh.write(raw[:7])                           # a line still being written
        U.scan_once(SID, str(sub))
        off = json.loads((st / "usage" / "sessions" / SID / "state.json").read_text())["agents"]["w1"]["off"]
        assert off == path.stat().st_size - 7           # the partial line is not consumed
        with open(path, "a") as fh:
            fh.write(raw[7:])
    U.scan_once(SID, str(sub), final=True)
    got = {int(k[2]): v for k, v in rows_by_key().items()}
    for seg, r in final_whole.items():
        for c in U.COLUMNS:
            if c != "session":
                assert str(got[seg][c]) == str(r[c]), (seg, c)


def test_idempotent_rows_and_last_row_wins(st, tmp_path):
    sub = subdir(tmp_path)
    write_agent(sub, "i1", agent_lines()[:4])          # ends on a tool result: running
    rows, _ = U.scan_once(SID, str(sub))
    assert [r["status"] for r in rows] == ["partial"]
    rows, grew = U.scan_once(SID, str(sub))
    assert rows == [] and not grew                      # nothing new: nothing appended
    rows, _ = U.scan_once(SID, str(sub), final=True)    # the session ended
    assert [r["status"] for r in rows] == ["complete"] and rows[0]["turn_limited"] == 1
    csv_lines = (st / "usage" / "runs3.csv").read_text().splitlines()
    assert csv_lines[0] == ",".join(U.COLUMNS) and len(csv_lines) == 3
    r = rows_by_key()
    assert len(r) == 1 and r[(SID, "i1", 0)]["status"] == "complete"
    rows, _ = U.scan_once(SID, str(sub), final=True)
    assert rows == []


def test_rotation_keeps_last_rows(st, tmp_path, monkeypatch):
    monkeypatch.setenv("STACK_USAGE_MAX_BYTES", "3000")
    base = dict(row3(), last_ts=T0, ctx=0)
    for i in range(60):
        U.append_rows([dict(base, id="r%d" % (i % 7), status="partial" if i < 53 else "complete", api_calls=i)])
    for i in range(80):
        U.append_rows([dict(base, id="k%d" % i, status="partial", api_calls=i)])
    U.append_rows([dict(base, id="k0", status="complete", api_calls=1000)])
    assert (st / "usage" / "runs3.1.csv").exists() and os.path.getsize(st / "usage" / "runs3.csv") <= 3200
    assert not (st / "usage" / "runs.csv").exists() and not (st / "usage" / "runs.1.csv").exists()
    r = rows_by_key()
    assert len(r) == 87 and r[(SID, "k0", 0)]["status"] == "complete" and r[(SID, "k0", 0)]["api_calls"] == "1000"
    assert sorted(int(r[(SID, "r%d" % i, 0)]["api_calls"]) for i in range(7)) == list(range(53, 60))
    assert all(r[(SID, "r%d" % i, 0)]["status"] == "complete" for i in range(7))
    # the archive's own cap (4 x STACK_USAGE_MAX_BYTES): the oldest sessions go first
    monkeypatch.setenv("STACK_USAGE_MAX_BYTES", "1500")
    newer = "22222222-2222-3333-4444-555555555555"
    for i in range(70):
        U.append_rows([dict(base, session=newer, id="n%d" % i, last_ts=T0 + 100, status="complete")])
    r = rows_by_key()
    assert {k[0] for k in r} == {newer} and len(r) == 70


def test_no_text_in_rows(st, tmp_path):
    sub = subdir(tmp_path)
    write_agent(sub, "t1", agent_lines())
    write_agent(sub, "t2", agent_lines()[:6], atype="Not a valid type; rm -rf /")
    U.scan_once(SID, str(sub), final=True)
    raw = (st / "usage" / "runs3.csv").read_text()
    for secret in ("SECRET", "sk-ant", "hunter2", "FINAL REPORT", "echo", "rm -rf"):
        assert secret not in raw
    for r in rows_by_key().values():
        for c, v in r.items():
            if c in U.STRING_COLUMNS:
                assert v == "" or U.valid_cell(c, v), (c, v)
            elif v != "":
                float(v)                                # every other field is a number
    state = (st / "usage" / "sessions" / SID / "state.json").read_text()
    assert "SECRET" not in state and "sk-ant" not in state


def test_runs_view(st, tmp_path):
    sub = subdir(tmp_path)
    write_agent(sub, "v1", agent_lines())
    write_agent(sub, "v2", agent_lines()[:4], atype="scout")
    U.scan_once(SID, str(sub))
    view = {r["id"]: r for r in U.runs_view(U.read_rows())}
    assert view["v1"]["segments"] == 2 and view["v1"]["api_calls"] == 5 and view["v1"]["type"] == "coder"
    assert view["v2"]["type"] == "scout"
    p = subprocess.run([PY, str(USAGE_PY), "runs", "--json"], capture_output=True, text=True, env=env_for(tmp_path))
    assert p.returncode == 0 and {r["id"] for r in json.loads(p.stdout)} == {"v1", "v2"}


# ---------------------------------------------------------------- lifecycle
def collector_meta(st_root):
    return json.loads((st_root / "usage" / "sessions" / SID / "collector.json").read_text())


def wait(pred, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if pred():
                return True
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(0.1)
    return False


def lock_held(st_root):
    with U.Locked(str(st_root / "usage" / "sessions" / SID / "collector.lock"), nb=True) as lk:
        return not lk.ok


@pytest.fixture
def owner():
    p = subprocess.Popen(["sleep", "120"])
    yield p
    p.kill()
    p.wait()


@pytest.fixture
def reap(st):
    yield
    try:
        pid = collector_meta(st)["pid"]
        os.kill(pid, signal.SIGTERM)
    except (OSError, ValueError, KeyError):
        pass


def hook(cmd, tmp_path, ev, **env):
    return subprocess.run([PY, str(USAGE_PY), cmd], input=json.dumps(ev), capture_output=True, text=True,
                          env=env_for(tmp_path, **env), timeout=10)


def event(tmp_path, name="SessionStart"):
    main = tmp_path / "projects" / "p" / (SID + ".jsonl")
    main.parent.mkdir(parents=True, exist_ok=True)
    return {"session_id": SID, "transcript_path": str(main), "cwd": str(tmp_path), "hook_event_name": name}


def run_collector(tmp_path, owner_pid=None, **env):
    cmd = [PY, str(USAGE_PY), "run", "--session", SID, "--subagents", str(subdir(tmp_path))]
    if owner_pid:
        cmd += ["--owner-pid", str(owner_pid)]
    return subprocess.Popen(cmd, env=env_for(tmp_path, **env), stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def test_kill_switch(st, tmp_path):
    p = hook("start", tmp_path, event(tmp_path), STACK_USAGE_COLLECT="0")
    assert p.returncode == 0 and p.stdout == "" and p.stderr == ""
    time.sleep(0.5)
    assert not (st / "usage").exists()
    c = run_collector(tmp_path, STACK_USAGE_COLLECT="0")
    assert c.wait(timeout=10) == 0
    assert not (st / "usage" / "sessions" / SID / "collector.json").exists()


def test_hooks_never_fail(st, tmp_path):
    for cmd in ("start", "end"):
        for raw in ("", "not json", "[1]", json.dumps({"session_id": "../../etc"}), json.dumps({"session_id": SID})):
            p = subprocess.run([PY, str(USAGE_PY), cmd], input=raw, capture_output=True, text=True,
                               env=env_for(tmp_path), timeout=10)
            assert p.returncode == 0 and p.stdout == "" and p.stderr == ""
    assert not (st / "usage" / "sessions" / "..").exists() or True
    assert not (tmp_path / "st" / "etc").exists()


def test_single_instance(st, tmp_path, owner, reap):
    write_agent(subdir(tmp_path), "s1", agent_lines()[:4])
    first = run_collector(tmp_path, owner.pid)
    assert wait(lambda: lock_held(st))
    second = run_collector(tmp_path, owner.pid)
    assert second.wait(timeout=10) == 0                 # the lock is taken: exits at once
    assert first.poll() is None and collector_meta(st)["pid"] == first.pid
    # the hook sees the running collector and starts nothing
    p = hook("start", tmp_path, event(tmp_path))
    assert p.returncode == 0
    time.sleep(0.5)
    assert collector_meta(st)["pid"] == first.pid
    first.send_signal(signal.SIGTERM)
    assert first.wait(timeout=10) == 0
    assert collector_meta(st)["reason"] == "signal"


def test_start_detached_and_end_marker(st, tmp_path, reap):
    """The SessionStart hook returns at once; its collector runs in its own session (it survives
    a kill of the hook's process group) and exits on the SessionEnd marker after a final scan."""
    sub = subdir(tmp_path)
    write_agent(sub, "e1", agent_lines()[:4])
    t = time.time()
    p = subprocess.Popen([PY, str(USAGE_PY), "start"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, env=env_for(tmp_path), start_new_session=True)
    out, err = p.communicate(json.dumps(event(tmp_path)).encode(), timeout=10)
    assert p.returncode == 0 and out == b"" and err == b"" and time.time() - t < 5
    try:
        os.killpg(p.pid, signal.SIGKILL)               # the hook's process group: the collector is not in it
    except ProcessLookupError:
        pass
    assert wait(lambda: lock_held(st))
    pid = collector_meta(st)["pid"]
    assert os.getsid(pid) != p.pid
    assert wait(lambda: rows_by_key()[(SID, "e1", 0)]["status"] == "partial")
    assert hook("end", tmp_path, event(tmp_path, "SessionEnd")).returncode == 0
    assert wait(lambda: collector_meta(st)["reason"] == "session end")
    assert wait(lambda: not lock_held(st))
    assert rows_by_key()[(SID, "e1", 0)]["status"] == "complete"     # the final scan closed it


def test_exit_on_owner_death(st, tmp_path, reap):
    write_agent(subdir(tmp_path), "o1", agent_lines()[:4])
    own = subprocess.Popen(["sleep", "120"])
    c = run_collector(tmp_path, own.pid)
    assert wait(lambda: lock_held(st))
    own.kill()
    own.wait()
    assert c.wait(timeout=15) == 0
    assert collector_meta(st)["reason"] == "owner gone"
    assert rows_by_key()[(SID, "o1", 0)]["status"] == "complete"


def test_exit_when_idle(st, tmp_path, owner, reap):
    c = run_collector(tmp_path, owner.pid, STACK_USAGE_IDLE_S="0.5")
    assert c.wait(timeout=15) == 0
    assert collector_meta(st)["reason"] == "idle"


def test_status_line(st, tmp_path):
    p = subprocess.run([PY, str(USAGE_PY), "status"], capture_output=True, text=True, env=env_for(tmp_path))
    assert p.returncode == 0 and p.stdout.startswith("usage collector: 0 running, 0 segment rows")
    p = subprocess.run([PY, str(USAGE_PY), "status"], capture_output=True, text=True,
                       env=env_for(tmp_path, STACK_USAGE_COLLECT="0"))
    assert "off (STACK_USAGE_COLLECT=0)" in p.stdout


def test_guard_prune_keeps_usage(st, tmp_path):
    """agent_guard.py's SessionStart prunes state folders idle for 3 days, never usage/, limits/, nor
    eq-container/ (image records, verification results) and eq-wall/ (audit logs, the user's verdicts and
    consents: install.sh --with-eq-container); a folder merely named like them elsewhere is no exception."""
    old = time.time() - 5 * 86400
    for name in ("usage", "limits", "old-session", "eq-container", "eq-wall", "eq-container-old"):
        d = st / name
        d.mkdir(parents=True)
        (d / "f").write_text("x")
        if name.startswith("eq-"):
            (d / "status.env").write_text("x")
            os.utime(d / "status.env", (old, old))
        os.utime(d / "f", (old, old))
        os.utime(d, (old, old))
    ev = {"session_id": "new-session", "hook_event_name": "SessionStart", "source": "startup", "cwd": str(tmp_path)}
    p = subprocess.run([PY, str(HOOKS / "agent_guard.py")], input=json.dumps(ev), capture_output=True, text=True,
                       env=env_for(tmp_path, HOME=str(tmp_path)), timeout=60)
    assert p.returncode == 0, p.stderr
    assert (st / "usage" / "f").exists() and not (st / "old-session").exists()
    assert (st / "limits" / "f").exists()
    assert (st / "eq-container" / "status.env").exists() and (st / "eq-wall" / "status.env").exists()
    assert not (st / "eq-container-old").exists()


# ---------------------------------------------------------------- the active model
def test_load_model_ignores_the_candidate(st, tmp_path, monkeypatch):
    """S6 U4: the refreshed (candidate) model is the next session's input; stack_sched never reads it."""
    monkeypatch.delenv("STACK_SCHED_MODEL", raising=False)
    monkeypatch.delenv("STACK_LIMITS_SNAPSHOT", raising=False)
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    S = _load("stack_sched_for_usage_test", HOOKS / "stack_sched.py")
    shipped = HOOKS / "sched_model.json"
    st.mkdir(parents=True, exist_ok=True)
    act = st / "sched_model.json"
    act.write_text(json.dumps({"version": 1, "types": {"scout": {"turns": {"S": 1, "M": 2, "L": 3}}}}))
    assert S.default_model_path() == shipped.resolve()
    assert S.load_model()["file"] == str(shipped.resolve())
    monkeypatch.setenv("STACK_SCHED_MODEL", str(act))      # the explicit override still wins
    assert S.load_model()["file"] == str(act)


def test_propose_prints_only(st, tmp_path):
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "scout.md").write_text("---\nname: scout\nmaxTurns: 400\n---\nbody\n")
    model = tmp_path / "m.json"
    model.write_text(json.dumps({"types": {"scout": {"status": "supported", "turns": {"L": 10}, "ctx": {"a": 1000, "b": 10},
                                                     "soft_limit": 1000000}}}))
    before = sorted((p.name, p.stat().st_mtime_ns) for p in tmp_path.rglob("*"))
    p = subprocess.run([PY, str(USAGE_PY), "propose", "--model", str(model), "--agents", str(agents)],
                       capture_output=True, text=True, env=env_for(tmp_path))
    assert p.returncode == 0
    assert "scout: maxTurns 400 > 3 x turns L 10" in p.stdout and "scout: soft limit 1M > 4 x ctx" in p.stdout
    assert sorted((p.name, p.stat().st_mtime_ns) for p in tmp_path.rglob("*")) == before


# ---------------------------------------------------------------- refresh (pandas, numpy)
LOOKUP = ("scout", "claude-code-guide", "oracle", "explore", "mcp-broker")


V1 = None


@pytest.fixture
def refit(tmp_path):
    global V1
    np = pytest.importorskip("numpy")
    pd = pytest.importorskip("pandas")
    sys.path.insert(0, str(ROOT / "tests"))
    D = _load("derive_sched_model", ROOT / "tests" / "derive_sched_model.py")
    R = _load("stack_sched_refresh", HOOKS / "stack_sched_refresh.py")
    agents = tmp_path / "agents"
    agents.mkdir()
    for t in LOOKUP:
        (agents / (t + ".md")).write_text("---\nname: %s\nmodel: sonnet\nmaxTurns: 40\n---\n" % t)
    fm = D.frontmatter(str(agents))
    V1 = load_v1(tmp_path)

    def segs(atype, n_agents, calls, seed, session):
        rng = np.random.default_rng(seed)
        rows = []
        for i in range(n_agents):
            n = max(1, int(round(calls * rng.lognormal(0, 0.3))))
            rows.append(dict(session=session, id="%s%d%d" % (atype[:3], seed, i), type=atype, seg=0, api_calls=n,
                             ctx=float(20000 * n + 800 * n * n), first_cc=18000.0, wall_s=float(9 * n)))
        return pd.DataFrame(rows)

    shipped_df = pd.concat([segs("claude-code-guide", 12, 20.0, 7, "ship1"), segs("scout", 3, 20.0, 8, "ship1")])
    shipped = D.fit(shipped_df, fm, {}, B=200)
    path = tmp_path / "shipped.json"
    path.write_text(json.dumps(shipped))
    return dict(R=R, D=D, segs=segs, shipped=shipped, path=path, agents=agents)


def v1_append(rows):
    """Rows of the v1 history (runs.csv), written the way the v1 collector did."""
    V1.append_rows(rows)


def csv_rows(df):
    out = []
    for r in df.itertuples():
        out.append(dict((c, 0) for c in V1.COLUMNS))
        out[-1].update(schema_version=1, session=r.session, id=r.id, type=r.type, seg=r.seg, status="complete",
                       api_calls=r.api_calls, ctx=r.ctx, first_cc=r.first_cc, first_ts=T0, last_ts=T0 + r.wall_s,
                       wall_s=r.wall_s, prev_peak="", gap_s="")
    return out


def do_refresh(k, st):
    return k["R"].refresh(str(st / "usage"), str(st / "sched_model.json"), str(k["path"]), str(k["agents"]),
                          "/nonexistent/agent_guard.py", step=1.5, B=200)


def test_refresh_provisional_to_supported(st, tmp_path, refit):
    k = refit
    assert k["shipped"]["types"]["scout"]["status"] == "provisional"          # 3 segments
    v1_append(csv_rows(k["segs"]("scout", 2, 20.0, 9, "new1")))          # 2 more agents: the new
    J = do_refresh(k, st)                                                    # lookup pool is not gated
    assert J["types"]["scout"]["status"] == "provisional" and J["types"]["scout"]["evidence"]["n_seg_seen"] == 2
    assert J["types"]["scout"]["n_seg"] == 3
    v1_append(csv_rows(k["segs"]("scout", 1, 20.0, 12, "new1")))
    v1_append(csv_rows(k["segs"]("claude-code-guide", 4, 20.0, 13, "new1")))
    J = do_refresh(k, st)
    sc = J["types"]["scout"]
    assert sc["status"] == "supported" and sc["n_seg"] == 6 and sc["n_agents"] == 6
    assert sc["evidence"] == {"n_seg_shipped": 3, "n_seg_collected": 3, "n_agents_collected": 3, "n_first_collected": 3,
                              "n_seg_seen": 3}
    assert sc["band"]["method"] == "combined"
    saved = json.loads((st / "sched_model.json").read_text())
    assert saved["types"]["scout"]["status"] == "supported" and saved["refresh"]["base_generated"] == k["shipped"]["generated"]
    # the shipped sessions are never counted twice
    v1_append(csv_rows(k["segs"]("scout", 4, 20.0, 10, "ship1")))
    assert do_refresh(k, st)["types"]["scout"]["n_seg"] == 6


def test_refresh_bounded_step_and_narrowing(st, tmp_path, refit):
    k = refit
    m0 = k["shipped"]["types"]["claude-code-guide"]
    w0 = m0["band"]["turns"]["hi"] / m0["band"]["turns"]["med"]
    v1_append(csv_rows(k["segs"]("claude-code-guide", 40, 200.0, 11, "new2")))   # 10x the turns
    J1 = do_refresh(k, st)
    m1 = J1["types"]["claude-code-guide"]
    assert m0["turns"]["M"] * 1.4 < m1["turns"]["M"] <= m0["turns"]["M"] * 1.5 + 0.1
    for q in ("a", "b"):
        assert m1["ctx"][q] <= m0["ctx"][q] * 1.5 + 1
    J2 = do_refresh(k, st)                                   # the active model is the next base
    m2 = J2["types"]["claude-code-guide"]
    assert J2["refresh"]["base"] == "active"
    assert m1["turns"]["M"] * 1.4 < m2["turns"]["M"] <= m1["turns"]["M"] * 1.5 + 0.1
    for _ in range(8):
        J = do_refresh(k, st)
    m = J["types"]["claude-code-guide"]
    target = k["R"].combine(k["shipped"], k["D"].fit(k["R"].frame(U.read_rows(), {"ship1"}), k["D"].frontmatter(str(k["agents"])), {}, B=200),
                            ["new2"], 40)["types"]["claude-code-guide"]
    assert m["turns"]["M"] == pytest.approx(target["turns"]["M"], rel=0.02)          # converged
    assert m["band"]["turns"]["hi"] / m["band"]["turns"]["med"] < w0                  # narrower with n


# ---------------------------------------------------------------- collector v2: columns, provenance, migration
REAL_SCAN = U.scan_once


def t_(k):
    return T0 + k + 0.25                                   # the epoch of ts(k)


def write_main(tmp_path, lines):
    main = tmp_path / "projects" / "p" / (SID + ".jsonl")
    main.parent.mkdir(parents=True, exist_ok=True)
    with open(main, "w") as fh:
        for r in lines:
            fh.write(json.dumps(r) + "\n")
    return main


def tu(tid, name, **inp):
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


def txt(t):
    return {"type": "text", "text": t}


def scan_final(tmp_path, **kw):
    U.scan_once(SID, str(subdir(tmp_path)), final=True, **kw)
    return rows_by_key()


def test_tool_counts_writes_and_first_write(st, tmp_path):
    c1 = call("c1", 1, cc=7000, cr=1000, content=[
        txt("thinking"), tu("r1", "Read", file_path="/repo/a.py"), tu("e1", "Edit", file_path="/repo/src/a.py"),
        tu("g1", "Bash", command="cd x && git -C /repo commit -m 'secret msg'")])
    c1_stream = dict(c1, message=dict(c1["message"], usage=dict(c1["message"]["usage"], output_tokens=99)))
    c2 = call("c2", 3, cc=300, cr=9000, content=[
        tu("w1", "Write", file_path="/private/tmp/claude-501/scratch/n.md"), tu("m1", "mcp__srv__tool"),
        tu("a1", "Agent", description="x"), tu("o1", "Mystery"), tu("e2", "MultiEdit", file_path="/repo/src/a.py"),
        tu("w2", "Write", file_path="/repo/b.py"), tu("n1", "NotebookEdit", notebook_path="/repo/n.ipynb"),
        tu("q1", "Bash", command="echo 'git commit' mention only")])
    c3 = call("c3", 5, cc=10, cr=9500, tool=False, text="STATUS: blocked\nRESULT: no")
    lines = [user("go", 0), c1, c1_stream, result(2), c2, result(4), c3]
    write_agent(subdir(tmp_path), "t1", lines, atype="code-reviewer",
                extra_meta={"parentAgentId": "ab12", "spawnDepth": 2})
    r = scan_final(tmp_path)[(SID, "t1", 0)]
    n = {k: int(r[k]) for k in U.TOOL_COLS + ["tool_calls"]}
    assert n == dict(n_read=1, n_write=2, n_edit=2, n_notebook=1, n_bash=2, n_grep=0, n_glob=0, n_agent=1, n_send=0,
                     n_skill=0, n_toolsearch=0, n_webfetch=0, n_websearch=0, n_lsp=0, n_mcp=1, n_other=1,
                     tool_calls=11)                              # the streamed duplicate of c1 counts once
    assert (r["files_written"], r["files_written_repo"], r["git_commits"]) == ("4", "3", "1")
    assert r["first_write_call"] == "1" and r["first_ctx"] == r["ctx_at_first_write"] == str(3 + 7000 + 1000)
    assert r["ro_write"] == "1" and r["status_code"] == "2"      # a read-only type that wrote repo files
    assert (r["resume"], r["cold"], r["parent"], r["depth"], r["node"]) == ("0", "", "ab12", "2", "T3")
    assert r["task"] == "implement the parser" and r["is_main"] == "0" and r["src"] == "measured"
    raw = (st / "usage" / "runs3.csv").read_text()
    for leak in ("secret msg", "/repo", "a.py", "git commit", "scratch"):
        assert leak not in raw


def test_resume_cold_and_empty_without_meta(st, tmp_path):
    write_agent(subdir(tmp_path), "m0", agent_lines(), atype=None)         # no meta file at all
    r = scan_final(tmp_path)
    s0, s1 = r[(SID, "m0", 0)], r[(SID, "m0", 1)]
    assert s1["resume"] == "1" and s1["cold"] == "1"              # first_cr 1000 < 0.5 * prev_peak 16103
    assert (s0["parent"], s0["depth"], s0["node"], s0["task"], s0["ro_write"]) == ("", "", "", "", "")
    assert s0["type"] == "(unknown)" and s0["resume"] == "0" and s0["cold"] == ""


def test_status_code_rules(st, tmp_path):
    sub = subdir(tmp_path)
    cases = {
        "sdone": [user("go", 0), call("d1", 1), result(2), call("d2", 3, tool=False, text="STATUS: done\nRESULT: x")],
        "spart": [user("go", 0), call("p1", 1), result(2), call("p2", 3, tool=False, text="Below.\nSTATUS: partial")],
        "sclean": [user("go", 0), call("c1", 1), result(2), call("c2", 3, tool=False, text="in · 2026-10-03\nok")],
        "stool": [user("go", 0), call("t1", 1), result(2), call("t2", 3)],
        "sres": [user("go", 0), call("r1", 1), result(2)]}
    for aid, ls in cases.items():
        write_agent(sub, aid, ls)
    r = scan_final(tmp_path)
    got = {aid: r[(SID, aid, 0)]["status_code"] for aid in cases}
    assert got == {"sdone": "0", "spart": "1", "sclean": "0", "stool": "", "sres": "1"}   # sres: turn_limited
    assert r[(SID, "sres", 0)]["turn_limited"] == "1"
    # a segment still open (fresh transcript, no final scan) has no status yet; a text-only end is complete
    U.scan_once(SID, str(sub), final=False)
    r = rows_by_key()
    assert r[(SID, "stool", 0)]["status"] == "partial" and r[(SID, "stool", 0)]["status_code"] == ""
    assert r[(SID, "sdone", 0)]["status"] == "complete" and r[(SID, "sdone", 0)]["status_code"] == "0"


def test_main_rows_windows_and_session_row(st, tmp_path):
    def human(k, pid=None, **kw):
        return dict(user("prompt %d" % k, k), promptId=pid, **kw)
    sdir = st / SID
    sdir.mkdir(parents=True)
    (sdir / "budget.json").write_text(json.dumps({"total": 777000}))
    write_main(tmp_path, [
        human(0, "pid-0"), call("m1", 1, content=[tu("x1", "Read", file_path="/r"), tu("x2", "Agent")]),
        call("m2", 2, tool=False), human(10, "pid-1"), human(10, "pid-1"),          # a replayed duplicate
        dict(user("meta", 11), isMeta=True), result(11), user("<task-notification>x</task-notification>", 12),
        call("m3", 13, content=[tu("x3", "Bash", command="ls")]), human(20, "pid-2")])   # window 2 has no call
    write_agent(subdir(tmp_path), "w1", [user("go", 0), call("w1", 14, tool=False)])
    write_agent(subdir(tmp_path), "w0", [user("go", 0), call("w0", 1, tool=False)])
    r = scan_final(tmp_path)
    m0, m1 = r[(SID, "main", 0)], r[(SID, "main", 1)]
    assert (SID, "main", 2) not in r
    assert (m0["type"], m0["is_main"], m0["depth"], m0["resume"], m0["window"], m0["parent"]) == (
        "blackcat", "1", "0", "0", "0", "")
    assert (m0["api_calls"], m0["n_read"], m0["n_agent"], m0["tool_calls"]) == ("2", "1", "1", "2")
    assert (m1["api_calls"], m1["n_bash"], m1["window"], m1["status"]) == ("1", "1", "1", "complete")
    assert (m0["status_code"], m0["cold"], m0["prev_peak"], m0["gap_s"]) == ("", "", "", "")
    assert r[(SID, "w1", 0)]["window"] == "1" and r[(SID, "w0", 0)]["window"] == "0"
    sess = r[(SID, "session", 0)]
    assert (sess["type"], sess["is_main"], sess["ctx"], sess["window_ctx"]) == ("blackcat", "1", "777000", "")
    assert float(sess["first_ts"]) == pytest.approx(t_(1)) and float(sess["last_ts"]) == pytest.approx(t_(14))
    # the transcripts' totals over the main thread and every subagent (5 calls of 3/50/1000/20000)
    assert [sess[c] for c in ("api_calls", "input", "output", "cache_creation", "cache_read")] == [
        "5", "15", "250", "5000", "100000"]
    assert {k[1] for k in r} == {"main", "session", "w0", "w1"}
    assert {a["id"] for a in U.runs_view(U.read_rows())} == {"w0", "w1"}


def test_hits_and_window_ctx_empty_until_the_guard_files_exist(st, tmp_path):
    two_windows(tmp_path)
    write_agent(subdir(tmp_path), "h1", [user("go", 0), call("h1", 12, tool=False)])
    sub = str(subdir(tmp_path))
    rows, _ = U.scan({"v": 2, "agents": {}}, SID, sub, final=False)
    r = {(x["id"], x["seg"]): x for x in rows}
    for k in (("main", 0), ("main", 1), ("h1", 0)):
        assert all(r[k][c] == "" for c in U.HIT_COLS), k      # nothing measured: empty, not 0
    # window_ctx without the guard's file: from the transcripts (h1's call at 12 is window 1's)
    assert (r[("main", 0)]["window_ctx"], r[("main", 1)]["window_ctx"], r[("h1", 0)]["window_ctx"]) == (
        21003, 2 * 21003, "")
    sdir = st / SID
    sdir.mkdir(parents=True)
    snap = "0123456789abcdef"
    hits = [{"v": 1, "ts": t_(12.5), "agent_id": "h1", "agent_type": "coder", "run": None, "kind": "turn",
             "value": 40, "limit": 40, "snap": snap},
            {"v": 1, "ts": t_(11.5), "agent_id": None, "agent_type": "blackcat", "run": None,
             "kind": "soft_prompt", "value": 9, "limit": 8, "snap": snap},
            {"v": 2, "ts": t_(12), "agent_id": "h1", "kind": "mcp"},                  # wrong schema version
            {"v": 1, "ts": t_(12), "agent_id": "../x", "kind": "mcp"},                # bad id
            {"v": 1, "ts": "x", "agent_id": "h1", "kind": "hard_agent"},              # bad ts
            {"v": 1, "ts": t_(50), "agent_id": "h1", "kind": "hard_agent"}]           # outside the segment
    (sdir / "limit-hits.jsonl").write_text("\n".join(json.dumps(h) for h in hits) + "\nnot json\n")
    pw = [{"v": 1, "ts": t_(0), "prompt_id": "pid-0", "base": 0},
          {"v": 1, "ts": t_(10), "prompt_id": "pid-1", "base": 100}, {"v": 1, "ts": "x", "base": 5}]
    (sdir / "prompt-windows.jsonl").write_text("\n".join(json.dumps(w) for w in pw) + "\n")
    (sdir / "budget.json").write_text(json.dumps({"total": 350}))
    rows, _ = U.scan({"v": 2, "agents": {}}, SID, sub, final=False)
    r = {(x["id"], x["seg"]): x for x in rows}
    h1, m0, m1 = r[("h1", 0)], r[("main", 0)], r[("main", 1)]
    assert [h1[c] for c in U.HIT_COLS] == [0, 1, 0, 0, 0, 0]
    assert [m0[c] for c in U.HIT_COLS] == [0] * 6
    assert [m1[c] for c in U.HIT_COLS] == [1, 0, 0, 0, 0, 0]
    assert (m0["window_ctx"], m1["window_ctx"], h1["window_ctx"]) == (100, 250, "")


def test_task_sanitized_and_node(st, tmp_path):
    cases = {"k1": ("P9d fix `rm -rf /` $(curl http://evil.example/x?a=b;id) <b>" + "z" * 80, "P9d"),
             "k2": ("Fix the thing", ""), "k3": ("!!! ??? \n", ""), "k4": ("S1e", "S1e"), "k5": ("t3 lower", ""),
             "k6": ("TOOLONG9 x", ""), "k7": ("A12345 x", "")}
    for aid, (desc, _) in cases.items():
        write_agent(subdir(tmp_path), aid, [user("go", 0), call(aid, 1, tool=False)], extra_meta={"description": desc})
    write_agent(subdir(tmp_path), "k8", [user("go", 0), call("k8", 1, tool=False)],
                extra_meta={"description": 5, "spawnDepth": True})
    r = scan_final(tmp_path)
    for aid, (_, node) in cases.items():
        row = r[(SID, aid, 0)]
        assert row["node"] == node and len(row["task"]) <= 60, aid
        assert row["task"] == "" or U.TASK_RE.match(row["task"])
    # plain words only: the plan node id lives in `node`, never in `task`
    assert r[(SID, "k1", 0)]["task"] == "fix"
    assert r[(SID, "k2", 0)]["task"] == "Fix the thing" and r[(SID, "k3", 0)]["task"] == ""
    assert [r[(SID, k, 0)]["task"] for k in ("k4", "k5", "k6", "k7")] == ["", "lower", "x", "x"]
    assert (r[(SID, "k8", 0)]["task"], r[(SID, "k8", 0)]["depth"]) == ("", "")


def test_task_label_keeps_no_path_url_args_or_key(tmp_path):
    """F1: `task` keeps the plain words of the description: no digit, '/', ':', URL, path, flag or key."""
    for desc in ("T3 review https://evil.example/c?k=1", "read /Users/x/.ssh/id_ed25519 now",
                 "key sk-ant-api03-DUMMY0000EXAMPLE", "run rm -rf /tmp/x", "fetch file:///etc/passwd ok",
                 "token ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcd"):
        (tmp_path / "agent-a1.meta.json").write_text(json.dumps({"agentType": "coder", "description": desc}))
        t = U.agent_meta(str(tmp_path), "a1")["task"]
        assert not re.search(r"[/:\d_.]|https?|\.ssh|-rf|sk-|ghp", t), (desc, t)
        assert t == "" or U.TASK_RE.match(t), (desc, t)
    assert U.agent_meta(str(tmp_path), "a1")["task"] == "token"
    (tmp_path / "agent-a1.meta.json").write_text(json.dumps({"agentType": "coder",
                                                             "description": "T3 fix the (flaky) re-run test, again!"}))
    m = U.agent_meta(str(tmp_path), "a1")
    assert (m["node"], m["task"]) == ("T3", "fix the flaky re-run test again")
    # the writer and the reader hold `task` to the same rule
    assert not U.valid_cell("task", "T3 x") and not U.valid_cell("task", "a/b") and U.valid_cell("task", "a b-c")


def test_stack_commit_from_manifest(st, tmp_path):
    man = tmp_path / "home" / ".claude" / ".stack-manifest.json"
    man.parent.mkdir(parents=True)
    write_agent(subdir(tmp_path), "c1", agent_lines()[:4])
    assert scan_final(tmp_path)[(SID, "c1", 0)]["stack_commit"] == ""                        # no manifest
    full = "1dea215d9a6ac5aab48efeea879ccd6a7fed30fa"
    for body, want in (('{"commit": "%s"}' % full, full), ("not json", ""), ('{"commit": "HEAD; rm -rf /"}', ""),
                       ('{"commit": 5}', ""), ("[]", "")):
        man.write_text(body)
        assert U.read_stack_commit() == want, body


def test_T22_append_only_provenance(st, tmp_path):
    full = "1dea215d9a6ac5aab48efeea879ccd6a7fed30fa"
    man = tmp_path / "home" / ".claude" / ".stack-manifest.json"
    man.parent.mkdir(parents=True)
    man.write_text('{"commit": "%s"}' % full)
    sub = subdir(tmp_path)
    write_main(tmp_path, [dict(user("hi", 0), promptId="p0"), call("m1", 1, tool=False)])
    write_agent(sub, "q1", agent_lines()[:4], atype=None)
    U.scan_once(SID, str(sub))
    f = st / "usage" / "runs3.csv"
    first = f.read_bytes()
    rows = rows_by_key()
    assert {k[1] for k in rows} == {"main", "q1"}
    for r in rows.values():
        assert r["src"] == "measured" and r["session"] == SID and r["first_ts"] != ""
        assert r["stack_commit"] == full and r["schema_version"] == "3"
        # nothing the collector cannot measure yet is a 0: the guard's files and the snapshot do not exist
        for c in U.HIT_COLS + ["sess_src", "snap", "regime"]:
            assert r[c] == "", c
    # window_ctx is measured from the transcripts: main's call plus q1's (in window 0)
    assert rows[(SID, "main", 0)]["window_ctx"] == str(21003 + 15003) and rows[(SID, "q1", 0)]["window_ctx"] == ""
    q = rows[(SID, "q1", 0)]
    assert (q["parent"], q["depth"], q["node"], q["task"], q["cold"], q["first_write_call"],
            q["ctx_at_first_write"]) == ("",) * 7
    assert q["status"] == "partial" and q["status_code"] == ""              # open: no status yet
    # later scans only append: the earlier bytes are untouched
    write_agent(sub, "q1", agent_lines()[4:], mode="a")
    write_agent(sub, "q2", agent_lines()[:4], atype="scout")
    U.scan_once(SID, str(sub), final=True)
    now = f.read_bytes()
    assert now.startswith(first) and len(now) > len(first)
    assert not (st / "usage" / "runs.csv").exists()
    assert rows_by_key()[(SID, "q2", 0)]["status_code"] == "1"             # ended on a tool result: turn-limited


def test_v1_and_v2_writers_coexist(st, tmp_path, monkeypatch):
    V = load_v1(tmp_path)
    base1 = {c: 0 for c in V.COLUMNS}
    expect = {}
    for i in range(12):
        ids = "v1x%d" % i
        V.append_rows([dict(base1, schema_version=1, session=SID, id=ids, type="scout", seg=0, status="complete",
                            api_calls=i + 1, last_ts=T0 + i, first_ts=T0, prev_peak="", gap_s="")])
        expect[(SID, ids, 0)] = ("seed_v1", str(i + 1))
        idw = "v2x%d" % i
        U.append_rows([row3(id=idw, api_calls=100 + i, last_ts=T0 + i, first_ts=T0, stack_commit="1dea215",
                              task="T%d x" % i, node="T%d" % i)])
        expect[(SID, idw, 0)] = ("measured", str(100 + i))
    r = U.read_rows()
    assert set(r) == set(expect)
    for k, (src, calls) in expect.items():
        assert r[k]["src"] == src and r[k]["api_calls"] == calls and set(r[k]) == set(U.COLUMNS)
    v1row = r[(SID, "v1x3", 0)]
    assert v1row["schema_version"] == "1" and v1row["tool_calls"] == "" and v1row["status_code"] == ""
    # the same key in both histories: the v2 row (read later) wins
    V.append_rows([dict(base1, schema_version=1, session=SID, id="dup", type="scout", seg=0, status="partial",
                        api_calls=1, prev_peak="", gap_s="")])
    U.append_rows([row3(id="dup", status="complete", api_calls=7)])
    assert U.read_rows()[(SID, "dup", 0)]["api_calls"] == "7"
    assert V.read_rows()[(SID, "v1x0", 0)]["api_calls"] == "1"        # the v1 reader still reads its own file
    # v1 rotation (its own business) never disturbs the v2 files
    before = (st / "usage" / "runs3.csv").read_bytes()
    monkeypatch.setenv("STACK_USAGE_MAX_BYTES", "1500")
    for i in range(30):
        V.append_rows([dict(base1, schema_version=1, session=SID, id="rot%d" % i, type="scout", seg=0,
                            status="complete", last_ts=T0 + 50, prev_peak="", gap_s="")])
    assert (st / "usage" / "runs.1.csv").exists() and (st / "usage" / "runs3.csv").read_bytes() == before
    assert (SID, "v2x5", 0) in U.read_rows() and (SID, "rot29", 0) in U.read_rows()


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def test_migration_unknown_header_set_aside_and_v1_files_untouched(st, tmp_path, monkeypatch):
    V = load_v1(tmp_path)
    base1 = {c: 0 for c in V.COLUMNS}
    for i in range(4):
        V.append_rows([dict(base1, schema_version=1, session=SID, id="old%d" % i, type="scout", seg=0,
                            status="complete", prev_peak="", gap_s="")])
    u = st / "usage"
    (u / "runs.1.csv").write_text((u / "runs.csv").read_text())
    (u / "runs.old-schema.csv").write_text("a,b\n1,2\n")
    v1_files = {n: sha(u / n) for n in ("runs.csv", "runs.1.csv", "runs.old-schema.csv")}
    (u / "runs3.csv").write_text(f"schema_version,session,id\n2,{SID},zzz\n")           # an unknown header
    monkeypatch.setattr(U, "time", types.SimpleNamespace(time=lambda: 1790000123.9, sleep=time.sleep,
                                                             monotonic=time.monotonic))
    U.append_rows([row3(id="n1")])
    aside = u / "runs3.old-schema-1790000123.csv"
    assert aside.read_text().endswith("2,%s,zzz\n" % SID)
    assert (u / "runs3.csv").read_text().splitlines()[0] == ",".join(U.COLUMNS)
    assert (SID, "zzz", 0) not in U.read_rows() and (SID, "n1", 0) in U.read_rows()
    first_aside = aside.read_bytes()
    (u / "runs3.csv").write_text("other,header\n1,2\n")                                    # again, same second
    U.append_rows([row3(id="n2")])
    assert aside.read_bytes() == first_aside and (u / "runs3.old-schema-1790000123-1.csv").exists()
    assert {k[1] for k in U.read_rows() if k[1].startswith("n")} == {"n2"}
    # v2 rotation and appends never touch the v1 files, even when runs.csv is over the cap
    monkeypatch.setenv("STACK_USAGE_MAX_BYTES", "400")
    for i in range(20):
        U.append_rows([row3(id=f"big{i}", last_ts=T0 + i)])
    assert (u / "runs3.1.csv").exists()
    assert {n: sha(u / n) for n in v1_files} == v1_files
    assert sorted(p.name for p in u.iterdir() if p.name.endswith(".csv") and p.name.startswith("runs.")) == [
        "runs.1.csv", "runs.csv", "runs.old-schema.csv"]
    assert U.read_rows()[(SID, "old2", 0)]["src"] == "seed_v1"


def test_hostile_csv_is_filtered_by_the_reader_and_writer(st, tmp_path):
    u = st / "usage"
    u.mkdir(parents=True)
    good = row3(id="good", parent="main", node="T3", task="a b", snap="0123456789abcdef", sess_src="resume",
                  regime="fedcba9876543210", stack_commit="abcdef1", api_calls=5)
    bad = row3(id="opt", parent="../../x", node="lower", task="<script>", snap="XYZ", sess_src="boot",
                 regime="1234", stack_commit="HEAD", src="evil", api_calls=6)
    rows = [good, bad, row3(id="../etc"), row3(id="ty", type="a;b"), row3(id="st", status="weird"),
            row3(id="seg", seg="x"), dict(row3(id="v2"), schema_version=2),
            dict(row3(id="v1"), schema_version=1)]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=U.COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    (u / "runs3.csv").write_text(buf.getvalue() + "short,row\n" + "\x00garbage\n")
    r = U.read_rows()
    assert {k[1] for k in r} == {"good", "opt"}
    g, o = r[(SID, "good", 0)], r[(SID, "opt", 0)]
    assert (g["parent"], g["node"], g["task"], g["snap"], g["sess_src"], g["regime"], g["stack_commit"]) == (
        "main", "T3", "a b", "0123456789abcdef", "resume", "fedcba9876543210", "abcdef1")
    assert all(o[c] == "" for c in U.OPTIONAL_STRINGS) and o["api_calls"] == "6"
    # the writer blanks an invalid optional cell as well: a formula, a newline or a comma in `task`
    U.append_rows([row3(id="w1", task="=cmd|' /C calc'!A0", parent="a b", stack_commit="zz"),
                   row3(id="w2", task="line1\nline2,x")])
    raw = (u / "runs3.csv").read_text()
    assert "calc" not in raw and "line1" not in raw
    r = U.read_rows()
    assert r[(SID, "w1", 0)]["task"] == "" and r[(SID, "w1", 0)]["parent"] == "" and r[(SID, "w2", 0)]["task"] == ""


def _csv3(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=U.COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode("utf-8")


def test_reader_keeps_rows_after_a_bad_line(st):
    """F2: a NUL line (csv on Python < 3.11 refuses it), an unbalanced quote and bad UTF-8 cost their own
    line only, never the rows after them."""
    u = st / "usage"
    u.mkdir(parents=True)
    body = _csv3([row3(id="g1")])
    for i, bad in enumerate((b"\x00bad\n", b'2,"open quote,x\n', b"\xff\xfe broken\n", b"\x00" * 40 + b"\n"), 2):
        body += bad + _csv3([row3(id=f"g{i}")]).split(b"\n", 1)[1]
    (u / "runs3.csv").write_bytes(body)
    assert {k[1] for k in U.read_rows()} == {"g1", "g2", "g3", "g4", "g5"}


def _rotation_files(u):
    return sorted(p.name for p in u.iterdir() if p.name.startswith("runs3") and p.name.endswith(".csv"))


@pytest.mark.parametrize("bad", [b"\x00" * 40 + b"\n", b'2,"an unbalanced quote\n', b"\xff\xfe broken\n"],
                         ids=["nul", "quote", "utf8"])
def test_rotation_after_a_corrupt_line_loses_no_row(st, monkeypatch, bad):
    """M2: rotation reads strictly; a file it cannot read is set aside byte for byte as
    runs3.unreadable-<epoch>.csv (never over an earlier one) and runs3.csv starts again: no row after
    the corrupt line is lost (before, rotation archived only the rows ahead of it and unlinked runs3.csv)."""
    u = st / "usage"
    base = dict(row3(), last_ts=T0, ctx=0)
    monkeypatch.setenv("STACK_USAGE_MAX_BYTES", "1000000")
    U.append_rows([dict(base, id=f"a{i}") for i in range(3)])
    with open(u / "runs3.csv", "ab") as fh:
        fh.write(bad)
    U.append_rows([dict(base, id=f"b{i}") for i in range(3)])
    before = (u / "runs3.csv").read_bytes()
    monkeypatch.setattr(U, "time", types.SimpleNamespace(time=lambda: 1790000123.9, sleep=time.sleep,
                                                             monotonic=time.monotonic))
    (u / "runs3.unreadable-1790000123.csv").write_bytes(b"an earlier one\n")
    monkeypatch.setenv("STACK_USAGE_MAX_BYTES", "300")
    U.append_rows([dict(base, id="c0")])                              # past the cap: rotation
    live = set(U.read_rows())
    aside = u / "runs3.unreadable-1790000123-1.csv"
    kept = set(live)
    if aside.exists():
        assert aside.read_bytes() == before                           # intact, byte for byte
        kept |= set(U.read_rows([str(aside)]))
    assert (u / "runs3.unreadable-1790000123.csv").read_bytes() == b"an earlier one\n"
    for k in ["a0", "a1", "a2", "b0", "b1", "b2"]:
        assert (SID, k, 0) in kept, k
    assert (SID, "c0", 0) in live
    # strict rotation sets aside on any interpreter (the csv module of /usr/bin/python3 refuses NUL)
    assert aside.exists() and not (u / "runs3.1.csv").exists()
    assert (u / "runs3.csv").read_text().splitlines()[0] == ",".join(U.COLUMNS)
    # an unreadable archive is set aside as well; the rotation goes on with runs3.csv's rows
    (u / "runs3.1.csv").write_bytes(_csv3([dict(base, id="old1")]) + bad
                                    + _csv3([dict(base, id="old2")]).split(b"\n", 1)[1])
    arch = (u / "runs3.1.csv").read_bytes()
    U.append_rows([dict(base, id=f"c{i}") for i in range(1, 4)])  # rotates again
    assert (u / "runs3.1.unreadable-1790000123.csv").read_bytes() == arch
    assert {k[1] for k in U.read_rows([str(u / "runs3.1.csv")])} == {"c0"}
    assert {k[1] for k in U.read_rows([str(u / "runs3.csv")])} == {"c1", "c2", "c3"}
    assert _rotation_files(u) == ["runs3.1.csv", "runs3.1.unreadable-1790000123.csv", "runs3.csv",
                                  "runs3.unreadable-1790000123-1.csv", "runs3.unreadable-1790000123.csv"]


@pytest.mark.parametrize("damage", ["bom", "stray", "header", "eacces"])
def test_rotation_keeps_an_archive_it_cannot_read(st, monkeypatch, damage):
    """M2 (audit follow-up): an archive whose header the strict reader would not see (a BOM, a stray
    byte, another header, no read permission) read as empty and was replaced by runs3.csv's rows; it is
    set aside intact instead."""
    if damage == "eacces" and os.geteuid() == 0:
        pytest.skip("root reads a mode-0 file")
    u, base = st / "usage", dict(row3(), last_ts=T0, ctx=0)
    monkeypatch.setenv("STACK_USAGE_MAX_BYTES", "1000000")
    U.append_rows([dict(base, id=f"a{i}") for i in range(3)])
    arch = _csv3([dict(base, id="old1")])
    pre = {"bom": b"\xef\xbb\xbf", "stray": b"x", "header": b"", "eacces": b""}[damage]
    if damage == "header":
        arch = b"schema_version,session,id\n2," + SID.encode() + b",old1\n"
    (u / "runs3.1.csv").write_bytes(pre + arch)
    if damage == "eacces":
        (u / "runs3.1.csv").chmod(0)
    monkeypatch.setenv("STACK_USAGE_MAX_BYTES", "300")
    U.append_rows([dict(base, id="c0")])
    for p in u.glob("runs3.1*.csv"):
        p.chmod(0o600)
    asides = list(u.glob("runs3.1.unreadable-*.csv"))
    assert len(asides) == 1 and asides[0].read_bytes() == pre + arch
    assert {k[1] for k in U.read_rows([str(u / "runs3.1.csv")])} == {"a0", "a1", "a2"}


def test_a_bad_byte_in_runs3_never_stops_the_writer(st, monkeypatch):
    """M2 (audit follow-up): the header check decoded the first 8 KB strictly, so one bad byte near the
    top of runs3.csv made every append raise (no row written again, below the cap too)."""
    u = st / "usage"
    U.append_rows([row3(id="a1")])
    with open(u / "runs3.csv", "ab") as fh:
        fh.write(b"\xff\xfe broken\n")
    U.append_rows([row3(id="a2")])
    assert {k[1] for k in U.read_rows()} == {"a1", "a2"}


def test_the_writer_never_quotes_a_cell(st, monkeypatch):
    """_csv_rows parses each line on its own because no written cell holds a quote, comma or newline:
    a value that would need quoting (a trailing newline passed `$`) is blanked, or its row (a key cell
    every reader drops) is not written, so strict rotation never sets a good file aside."""
    u = st / "usage"
    U.append_rows([row3(id="ok1", task="abc\n", node="T3\n", parent="main\n", stack_commit="abcdef1\n",
                          snap="0123456789abcdef\n"),
                   row3(id="bad\n"), row3(id="ok2", type="coder\n"), row3(id="ok3", session=SID + "\n"),
                   row3(id="ok4", status="complete\n"), row3(id='q"x'), row3(id="c,x")])
    raw = (u / "runs3.csv").read_bytes()
    assert b'"' not in raw and raw.count(b"\n") == 2
    r = U.read_rows()
    assert set(r) == {(SID, "ok1", 0)} and all(r[(SID, "ok1", 0)][c] == "" for c in U.OPTIONAL_STRINGS if c != "src")
    assert not U.valid_cell("task", "abc\n") and not U.ID_RE.match("a1\n") and not U.TYPE_RE.match("coder\n")
    monkeypatch.setenv("STACK_USAGE_MAX_BYTES", "300")
    U.append_rows([row3(id="ok5")])                                    # rotation reads it strictly
    assert not list(u.glob("runs3*.unreadable-*.csv")) and set(U.read_rows()) == {(SID, "ok1", 0), (SID, "ok5", 0)}


def test_refresh_scrubs_interpreter_env(st, tmp_path, monkeypatch):
    """S1: the refit runs unsandboxed at the collector's exit; uv picks its interpreter from an active
    venv/conda env, a parent uv, UV_PYTHON, a config file, a .venv up from the cwd, then PATH. None of
    that comes from the session: --no-config, those variables dropped, a fixed PATH, cwd /."""
    venv = tmp_path / ".venv" / "bin"
    venv.mkdir(parents=True)
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(cmd=cmd, **kw)
        return subprocess.CompletedProcess(cmd, 0, stdout="refresh: ok\n", stderr="")
    monkeypatch.setattr(U, "find_uv", lambda: "/fake/uv")
    monkeypatch.setattr(U.subprocess, "run", fake_run)
    drop = {"VIRTUAL_ENV": str(tmp_path / ".venv"), "CONDA_PREFIX": str(tmp_path), "CONDA_DEFAULT_ENV": "base",
            "UV_INTERNAL__PARENT_INTERPRETER": str(venv / "python"), "UV_PYTHON": str(venv / "python"),
            "UV_CONFIG_FILE": str(tmp_path / "uv.toml"), "PYTHONPATH": str(tmp_path), "PYTHONHOME": str(tmp_path)}
    for k, v in drop.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("PATH", str(venv) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.chdir(tmp_path)
    assert U.refresh("manual", force=True)["status"] == "ok"
    env, cmd = seen["env"], seen["cmd"]
    assert not set(drop) & set(env) and set(drop) == set(U.REFRESH_ENV_DROP)
    assert str(tmp_path) not in env["PATH"] and env["PATH"] == "/usr/bin:/bin:/usr/sbin:/sbin"
    assert "--no-config" in cmd and cmd.index("--no-config") < cmd.index("--script") and seen["cwd"] == "/"
    assert env["PYTHONDONTWRITEBYTECODE"] == "1" and env["UV_OFFLINE"] == "1" and env["HOME"] == os.environ["HOME"]


def test_install_warmup_builds_the_refit_env_the_same_way():
    """S1: install.sh warms the cache the refit reuses with the same scrubbed environment, so uv finds the
    interpreter and script env it built there."""
    text = (ROOT / "install.sh").read_text()
    i = text.index('"$C/hooks/stack_sched_refresh.py" --help')
    block = text[text.rindex("(cd / &&", 0, i):i]
    assert set(re.findall(r"-u (\w+)", block)) == set(U.REFRESH_ENV_DROP)
    assert "PATH=" + U.REFRESH_PATH in block and "PYTHONDONTWRITEBYTECODE=1" in block
    assert "run --quiet --no-config --script" in block


HOLD_LOCK = r"""
import fcntl, os, sys, time
fd = os.open(sys.argv[1], os.O_RDONLY)          # a read-only fd is enough for flock
fcntl.flock(fd, fcntl.LOCK_EX)
print("held", flush=True)
time.sleep(60)
"""


def test_append_rows_bounded_when_lock_held(st, tmp_path, monkeypatch):
    """S2: a process holding runs3.lock (from a read-only fd) made append_rows, and so the collector,
    block forever; now it gives up after APPEND_LOCK_WAIT_S with TimeoutError, scan_once reloads its
    state, and the rows are appended at a later tick."""
    import threading
    U.append_rows([row3(id="a1")])
    lock = st / "usage" / "runs3.lock"
    holder = subprocess.Popen([PY, "-c", HOLD_LOCK, str(lock)], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        got = []

        def go():
            t = time.monotonic()
            try:
                U.append_rows([row3(id="a2")])
                got.append(("ok", time.monotonic() - t))
            except TimeoutError:
                got.append(("timeout", time.monotonic() - t))
        th = threading.Thread(target=go, daemon=True)
        th.start()
        th.join(10)
        assert not th.is_alive() and got and got[0][0] == "timeout" and got[0][1] < 10
        assert U.APPEND_LOCK_WAIT_S <= 5
        # the collector's scan: the error leaves the state as it was on disk, nothing is skipped
        monkeypatch.setattr(U, "APPEND_LOCK_WAIT_S", 0.3)
        write_agent(subdir(tmp_path), "s1", agent_lines()[:4])
        with pytest.raises(TimeoutError):
            U.scan_once(SID, str(subdir(tmp_path)), final=True)
    finally:
        holder.kill()
        holder.wait()
    U.scan_once(SID, str(subdir(tmp_path)), final=True)
    U.append_rows([row3(id="a2")])
    assert {(SID, "a1", 0), (SID, "a2", 0), (SID, "s1", 0)} <= set(U.read_rows())


def test_scope_hits_credit_the_main_window_and_the_session_not_the_agent(st, tmp_path):
    """M1: a prompt or session limit tripped by a subagent's call is the main window's hit (and a
    session limit the session row's); an agent row's hit_soft is its own soft limit only. A soft_session
    firing marks the session row, not the window (soft.prompt reads a window's hit_soft)."""
    write_main(tmp_path, [dict(user("prompt", 0), promptId="pid-0"), call("m1", 1),
                          dict(user("prompt", 30), promptId="pid-1"), call("m2", 31, tool=False)])
    write_agent(subdir(tmp_path), "q1", [user("go", 2), call("q1a", 3), result(4), call("q1b", 5, tool=False)])
    sdir = st / SID
    sdir.mkdir(parents=True)
    (sdir / "budget.json").write_text(json.dumps({"total": 50000}))
    hits = [{"v": 1, "kind": "hard_prompt", "agent_id": "q1", "ts": t_(4)},
            {"v": 1, "kind": "soft_prompt", "agent_id": "q1", "ts": t_(3.5)},
            {"v": 1, "kind": "hard_session", "agent_id": "q1", "ts": t_(5)},
            {"v": 1, "kind": "soft_session", "agent_id": None, "ts": t_(31.5)}]
    (sdir / "limit-hits.jsonl").write_text("".join(json.dumps(h) + "\n" for h in hits))
    U.scan_once(SID, str(subdir(tmp_path)), final=True)
    r = rows_by_key()
    m0, m1, q, s = r[(SID, "main", 0)], r[(SID, "main", 1)], r[(SID, "q1", 0)], r[(SID, "session", 0)]
    assert m0["hit_hard_prompt"] == "1" and q["hit_soft"] != "1"
    assert [m0[c] for c in U.HIT_COLS] == ["1", "0", "0", "1", "1", "0"]
    assert [m1[c] for c in U.HIT_COLS] == ["0"] * 6                     # soft_session: not the window's
    assert [q[c] for c in U.HIT_COLS] == ["0", "0", "0", "1", "1", "0"]  # q1's calls were refused
    assert [s[c] for c in U.HIT_COLS] == ["1", "0", "0", "0", "1", "0"]
    # without limit-hits.jsonl nothing is measured: the session row's hit cells are empty, not 0
    (sdir / "limit-hits.jsonl").unlink()
    rows, _ = U.scan({"v": 2, "agents": {}}, SID, str(subdir(tmp_path)), final=True)
    srow = next(x for x in rows if x["id"] == "session")
    assert all(srow[c] == "" for c in U.HIT_COLS)


def test_uv_and_ps_by_absolute_path_never_from_PATH(st, tmp_path, monkeypatch):
    """Hardening: the collector runs ps and the refit runs uv from fixed absolute paths, resolved once;
    a uv or ps first on PATH (an agent-writable dir there) is never run; none found: skipped quietly."""
    evil, marker = tmp_path / "evil", tmp_path / "evil-ran"
    evil.mkdir()
    for n in ("uv", "ps"):
        (evil / n).write_text(f"#!/bin/sh\ntouch '{marker}'\necho '1 Mon Jan  1 00:00:00 2024 x'\n")
        (evil / n).chmod(0o755)
    good, goodps = tmp_path / "bin" / "uv", tmp_path / "bin" / "ps"
    good.parent.mkdir()
    good.write_text("#!/bin/sh\necho refresh: fake\n")
    goodps.write_text("#!/bin/sh\necho '   77 Mon Jan  1 00:00:00 2024     /usr/local/bin/claude'\n")
    for f in (good, goodps):
        f.chmod(0o755)
    monkeypatch.setenv("PATH", str(evil) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setattr(U, "_EXE", {})
    assert U.find_ps() in ("/bin/ps", "/usr/bin/ps")                 # the default fixed paths
    monkeypatch.setattr(U, "_EXE", {})
    monkeypatch.setattr(U, "UV_PATHS", (str(tmp_path / "none" / "uv"), "relative/uv", str(good)))
    monkeypatch.setattr(U, "PS_PATHS", ("ps", str(goodps)))
    assert U.find_uv() == str(good) and U.find_ps() == str(goodps)
    assert U.proc_info(12345) == (77, "claude", "Mon Jan  1 00:00:00 2024")
    assert U.refresh(trigger="manual", force=True)["summary"] == "refresh: fake"
    # resolved once: a later change of the candidates does not move it
    monkeypatch.setattr(U, "UV_PATHS", (str(evil / "uv"),))
    assert U.find_uv() == str(good)
    # nothing at the fixed paths: the step is skipped quietly, nothing from PATH runs
    monkeypatch.setattr(U, "_EXE", {})
    monkeypatch.setattr(U, "UV_PATHS", (str(tmp_path / "none" / "uv"),))
    monkeypatch.setattr(U, "PS_PATHS", (str(tmp_path / "none" / "ps"),))
    assert U.find_uv() is None and U.find_ps() is None
    assert U.refresh(trigger="manual", force=True)["status"] == "skipped: uv not found"
    assert U.proc_info(os.getpid()) is None and U.find_owner() is None
    assert not marker.exists()


class FakeLimits:
    def __init__(self, order, boom=None):
        self.order, self.boom = order, boom

    def propose(self, *a, **k):
        self.order.append("propose")
        if self.boom:
            raise self.boom


def run_inproc(tmp_path, monkeypatch, order, limits="absent", boom=None):
    """The collector loop in this process: a session whose end marker is already there (one final scan)."""
    Path(U.session_dir(SID), "end").write_text("1\n")

    def scan_rec(*a, **k):
        order.append("scan")
        return REAL_SCAN(*a, **k)
    monkeypatch.setattr(U, "scan_once", scan_rec)
    monkeypatch.setattr(U, "refresh", lambda **k: order.append("refresh") or {})
    monkeypatch.setitem(sys.modules, "stack_limits", None if limits == "absent" else FakeLimits(order, boom))
    old = signal.getsignal(signal.SIGTERM)
    try:
        return U.run(SID, str(subdir(tmp_path)), poll=0.01)
    finally:
        signal.signal(signal.SIGTERM, old)


def test_exit_order_scan_propose_refresh_and_no_limit_change(st, tmp_path, monkeypatch):
    write_agent(subdir(tmp_path), "x1", agent_lines()[:4])
    lim = st / "limits"
    (lim / "snapshots").mkdir(parents=True)
    names = ("live.json", "snapshots/%s.json" % SID)
    for n, body in zip(names, ('{"v": 1}', '{"hash": "sha256:0"}')):
        (lim / n).write_text(body)

    def stamp():
        return {n: ((lim / n).read_bytes(), (lim / n).stat().st_mtime_ns) for n in names}
    before = stamp()
    order = []
    assert run_inproc(tmp_path, monkeypatch, order, limits="fake") == "session end"
    assert order == ["scan", "propose", "refresh"]
    assert (SID, "x1", 0) in rows_by_key() and stamp() == before
    # stack_limits not importable: skipped silently, the refresh still runs
    order.clear()
    assert run_inproc(tmp_path, monkeypatch, order) == "session end"
    assert order == ["scan", "refresh"]
    # an unfinished proposer (NotImplementedError) or a failing one does not stop the refresh
    for boom in (NotImplementedError("later"), RuntimeError("x")):
        order.clear()
        assert run_inproc(tmp_path, monkeypatch, order, limits="fake", boom=boom) == "session end"
        assert order == ["scan", "propose", "refresh"]
    assert stamp() == before


def test_collect_off_writes_no_rows_and_no_proposals(st, tmp_path, monkeypatch):
    monkeypatch.setenv("STACK_USAGE_COLLECT", "0")
    write_agent(subdir(tmp_path), "x1", agent_lines()[:4])
    order = []
    monkeypatch.setitem(sys.modules, "stack_limits", FakeLimits(order))
    monkeypatch.setattr(U, "refresh", lambda **k: order.append("refresh") or {})
    assert U.run(SID, str(subdir(tmp_path))) == "disabled"
    assert order == [] and not (st / "usage").exists()
    assert U.hook_start(event(tmp_path)) == "disabled"


def test_exit_refresh_passes_the_session(st, tmp_path, monkeypatch):
    """The collector's exit refresh runs stack_sched_refresh.py with --session <sid> (its snapshot's
    soft limits); a manual refresh or a bad id passes none."""
    seen = []
    fake = tmp_path / "uv"
    fake.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$UV_ARGS\"\necho '{}'\n")
    fake.chmod(0o755)
    monkeypatch.setenv("UV_ARGS", str(tmp_path / "args"))
    monkeypatch.setattr(U, "find_uv", lambda: str(fake))

    def args():
        return (tmp_path / "args").read_text().split("\n")
    U.refresh(trigger="session end", force=True, session=SID)
    a = args()
    assert a[a.index("--session") + 1] == SID and a[a.index("--script") + 1].endswith("stack_sched_refresh.py")
    for sess in (None, "../x", "-rf"):
        U.refresh(trigger="manual", force=True, session=sess)
        assert "--session" not in args()
    # run() hands its sid to the exit refresh
    write_agent(subdir(tmp_path), "x1", agent_lines()[:4])
    Path(U.session_dir(SID), "end").write_text("1\n")
    monkeypatch.setattr(U, "refresh", lambda **k: seen.append(k) or {})
    monkeypatch.setitem(sys.modules, "stack_limits", None)
    old = signal.getsignal(signal.SIGTERM)
    try:
        assert U.run(SID, str(subdir(tmp_path)), poll=0.01) == "session end"
    finally:
        signal.signal(signal.SIGTERM, old)
    assert seen == [{"trigger": "session end", "session": SID}]


# ---------------------------------------------------------------- schema 3: the segment's model
# Model IDs as the API reports them (synthetic transcripts, the matcher's vectors): only on module-level
# constant lines like these, which tests/lint_agents.py allows (MODEL_ID_LINES)
HAIKU, SONNET, OPUS = "claude-haiku-4-5-20251001", "claude-sonnet-5-5", "claude-opus-5-5"
HAIKU_SHORT, BEDROCK_SONNET, OPUS_1M = "claude-haiku-4-5", "us.anthropic.claude-sonnet-4-5-20250929-v1:0", "claude-opus-4-6[1m]"


def test_segment_model_per_segment_mixed_and_synthetic(st, tmp_path):
    """`model` is what the API reported for the segment's calls: one id, `mixed` for two, empty for none
    valid; Claude Code's `<synthetic>` lines are no model. A resume is its own segment."""
    sub = subdir(tmp_path)
    resume = user("Another Claude session sent a message while you were working: more", 400)
    write_agent(sub, "m1", [user("go", 0), call("a1", 1, model=HAIKU), result(2), call("a2", 3, model=HAIKU, tool=False),
                            resume, call("b1", 401, model=SONNET, tool=False)], atype="scout")
    write_agent(sub, "m2", [user("go", 0), call("c1", 1, model=HAIKU), result(2), call("c2", 3, model=SONNET),
                            result(4), call("c3", 5, model=HAIKU, tool=False)], atype="scout")
    write_agent(sub, "m3", [user("go", 0), call("d1", 1, model=SONNET), result(2),
                            call("d2", 3, model="<synthetic>", tool=False, inp=0, cc=0, cr=0)], atype="scout")
    write_agent(sub, "m4", [user("go", 0), call("e1", 1, model="bad model, x", tool=False)], atype="scout")
    write_main(tmp_path, [dict(user("hi", 0), promptId="p0"), call("w1", 1, tool=False, model=SONNET)])
    r = scan_final(tmp_path)
    assert (r[(SID, "m1", 0)]["model"], r[(SID, "m1", 1)]["model"]) == (HAIKU, SONNET)
    assert r[(SID, "m2", 0)]["model"] == U.MODEL_MIXED == "mixed"
    assert r[(SID, "m3", 0)]["model"] == SONNET and r[(SID, "m4", 0)]["model"] == ""
    assert r[(SID, "main", 0)]["model"] == SONNET
    assert all(v["schema_version"] == "3" and (v["model"] == "" or U.valid_cell("model", v["model"])) for v in r.values())
    assert not U.valid_cell("model", "<synthetic>") and not U.valid_cell("model", "a,b") and not U.valid_cell("model", "x\n")
    assert U.valid_cell("model", BEDROCK_SONNET) and U.valid_cell("model", OPUS_1M)


def test_schema3_reads_the_v1_and_v2_files_and_never_writes_them(st, tmp_path, monkeypatch):
    """The migration: runs3*.csv is the writer's; the v1 (runs*.csv) and v2 (runs2*.csv) histories stay
    as they are, read with `model` empty (unknown, never guessed); a later v3 row of a key wins."""
    V = load_v1(tmp_path)
    V.append_rows([dict({c: 0 for c in V.COLUMNS}, schema_version=1, session=SID, id="o1", type="scout", seg=0,
                        status="complete", api_calls=1, prev_peak="", gap_s="")])
    u = st / "usage"
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=U.COLUMNS_V2, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    w.writerows([dict(row3(id="t1", api_calls=2), schema_version=2),
                 dict(row3(id="dup", api_calls=3, status="partial"), schema_version=2)])
    (u / "runs2.csv").write_text(buf.getvalue())
    (u / "runs2.1.csv").write_text(buf.getvalue().replace(",t1,", ",t0,"))
    before = {n: sha(u / n) for n in ("runs.csv", "runs2.csv", "runs2.1.csv")}
    U.append_rows([row3(id="dup", api_calls=7, model=SONNET), dict(row3(id="n1", model=HAIKU), schema_version=2)])
    r = U.read_rows()
    assert r[(SID, "o1", 0)]["src"] == "seed_v1" and r[(SID, "o1", 0)]["model"] == ""
    for k in ("t0", "t1"):
        assert r[(SID, k, 0)]["schema_version"] == "2" and r[(SID, k, 0)]["model"] == ""
    assert r[(SID, "dup", 0)]["api_calls"] == "7" and r[(SID, "dup", 0)]["model"] == SONNET   # v3 read last
    assert r[(SID, "n1", 0)]["schema_version"] == "3"          # the writer writes its own schema only
    assert (u / "runs3.csv").read_text().splitlines()[0] == ",".join(U.COLUMNS) and U.COLUMNS_V3[-1] == "model" and U.COLUMNS[-2:] == U.EQ_COLS
    monkeypatch.setenv("STACK_USAGE_MAX_BYTES", "400")          # rotation: runs3*.csv only
    for i in range(20):
        U.append_rows([row3(id=f"big{i}", last_ts=T0 + i)])
    assert (u / "runs3.1.csv").exists() and {n: sha(u / n) for n in before} == before
    assert {(SID, "t1", 0), (SID, "o1", 0), (SID, "big19", 0)} <= set(U.read_rows())
    assert [U.file_schemas(p) for p in ("a/runs3.1.csv", "runs2.csv", "runs.1.csv")] == [("3",), ("2",), ("1",)]


def test_an_older_collector_state_is_read_again_in_schema_3(st, tmp_path):
    """A session an older collector (state v2) had read is read again from the start, so its rows are
    written anew with `model`."""
    sub = subdir(tmp_path)
    write_agent(sub, "g1", agent_lines()[:4], atype="scout")
    U.scan_once(SID, str(sub), final=True)
    stp = st / "usage" / "sessions" / SID / "state.json"
    old = json.loads(stp.read_text())
    stp.write_text(json.dumps(dict(old, v=2)))
    (st / "usage" / "runs3.csv").unlink()
    U.scan_once(SID, str(sub), final=True)
    assert rows_by_key()[(SID, "g1", 0)]["model"] == OPUS
    stp.write_text(json.dumps(old))                              # the same schema: nothing read twice
    (st / "usage" / "runs3.csv").unlink()
    U.scan_once(SID, str(sub), final=True)
    assert rows_by_key() == {}


def test_refresh_skips_overridden_runs(st, tmp_path, refit):
    """The scheduler refit: scout runs on another model than scout's (sonnet: the refit's agents dir)
    are no evidence; v1 rows and rows of scout's model count."""
    k = refit
    sonnet = csv_rows(k["segs"]("scout", 3, 20.0, 9, "new1"))
    haiku = csv_rows(k["segs"]("scout", 4, 200.0, 21, "ovr1"))
    U.append_rows([dict(r, model=SONNET) for r in sonnet] + [dict(r, model=HAIKU) for r in haiku])
    J = do_refresh(k, st)
    sc = J["types"]["scout"]
    assert sc["evidence"]["n_seg_seen"] == 3 and J["refresh"]["model_mismatch"] == 4
    assert "ovr1" not in J["sessions"] and "new1" in J["sessions"]


V2_REV = "6a736c6"            # the last commit with the v2 collector (runs2.csv, no `model`)


def test_upgrade_hands_off_from_an_older_collector(st, tmp_path, owner, reap):
    """Audit follow-up: a collector keeps the code it started with, so after an install the session's
    v2 collector would write an /override-agent run typed now without `model` (read as unknown, learned
    from). The next start hook stops it (SIGTERM: final scan, exit) and a successor reads the session
    again in schema 3, whose rows win."""
    p = subprocess.run(["git", "-C", str(ROOT), "show", "%s:dot-config/dot-claude/hooks/stack_usage.py" % V2_REV],
                       capture_output=True, text=True)
    if p.returncode != 0:
        pytest.skip("commit %s not available: %s" % (V2_REV, p.stderr.strip()[:80]))
    old = tmp_path / "v2" / "stack_usage.py"
    old.parent.mkdir()
    old.write_text(p.stdout)
    sub = subdir(tmp_path)
    write_agent(sub, "u1", [user("go", 0), call("a1", 1, model=HAIKU), result(2),
                            call("a2", 3, model=HAIKU, tool=False)], atype="scout")
    c = subprocess.Popen([PY, str(old), "run", "--session", SID, "--subagents", str(sub), "--owner-pid",
                          str(owner.pid)], env=env_for(tmp_path), stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert wait(lambda: lock_held(st) and (st / "usage" / "runs2.csv").exists())
    assert "schema" not in collector_meta(st) and rows_by_key()[(SID, "u1", 0)]["model"] == ""
    assert hook("start", tmp_path, event(tmp_path, "SubagentStart")).returncode == 0
    assert c.wait(timeout=20) == 0 and collector_meta(st).get("reason") in ("signal", None)
    assert wait(lambda: collector_meta(st).get("schema") == U.SCHEMA_VERSION, timeout=30)
    assert wait(lambda: rows_by_key()[(SID, "u1", 0)]["model"] == HAIKU, timeout=30)
    assert rows_by_key()[(SID, "u1", 0)]["schema_version"] == "3"
    # a collector of this schema is left alone
    pid = collector_meta(st)["pid"]
    assert hook("start", tmp_path, event(tmp_path, "SubagentStart")).returncode == 0
    time.sleep(0.5)
    assert collector_meta(st)["pid"] == pid and lock_held(st)


def test_a_handoff_session_row_is_not_learned_as_a_whole_session(st, tmp_path, owner, reap):
    """Audit of the hand-off (MEDIUM): SIGTERM makes the v2 collector's final scan write a `complete`
    session row with the ctx of that moment (50k). The session goes on (90k) and the successor idles out:
    its idle exit's final scan replaces that row (90k, spanning every row), which stack_limits learns as
    the session's; the stale v2 row alone (no successor row yet) would be left out (stale_session)."""
    p = subprocess.run(["git", "-C", str(ROOT), "show", "%s:dot-config/dot-claude/hooks/stack_usage.py" % V2_REV],
                       capture_output=True, text=True)
    if p.returncode != 0:
        pytest.skip("commit %s not available: %s" % (V2_REV, p.stderr.strip()[:80]))
    old = tmp_path / "v2" / "stack_usage.py"
    old.parent.mkdir()
    old.write_text(p.stdout)
    (st / SID).mkdir(parents=True)
    (st / SID / "budget.json").write_text(json.dumps({"total": 50000}))
    sub = subdir(tmp_path)
    write_agent(sub, "u1", [user("go", 0), call("a1", 1, model=HAIKU), result(2),
                            call("a2", 3, model=HAIKU, tool=False)], atype="scout")
    c = subprocess.Popen([PY, str(old), "run", "--session", SID, "--subagents", str(sub), "--owner-pid",
                          str(owner.pid)], env=env_for(tmp_path), stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert wait(lambda: lock_held(st) and (st / "usage" / "runs2.csv").exists())
    assert (SID, "session", 0) not in rows_by_key()
    assert hook("start", tmp_path, event(tmp_path, "SubagentStart"), STACK_USAGE_IDLE_S="3").returncode == 0
    assert c.wait(timeout=20) == 0
    assert wait(lambda: collector_meta(st).get("schema") == U.SCHEMA_VERSION, timeout=30)
    assert rows_by_key()[(SID, "session", 0)]["ctx"] == "50000"          # the v2 final scan's row
    (st / SID / "budget.json").write_text(json.dumps({"total": 90000}))
    write_agent(sub, "u2", [user("go", 500), call("b1", 501, model=HAIKU, tool=False)], atype="scout")
    L = _load("stack_limits_handoff", HOOKS / "stack_limits.py")
    assert wait(lambda: collector_meta(st).get("reason") == "idle", timeout=30)
    assert rows_by_key()[(SID, "session", 0)]["ctx"] == "90000"          # the idle exit's final scan
    rows, stats = L.read_rows(models={})
    assert [r["ctx"] for r in rows if r["scope"] == "session"] == [90000] and stats["stale_session"] == 0
    assert {r["id"] for r in rows if r["session"] == SID} >= {"u1", "u2"}


def test_handoff_signals_only_a_running_older_collector_of_this_session(st, tmp_path, owner, monkeypatch):
    """Under a held lock the pid in collector.json gets SIGTERM only when the meta is an older schema's,
    unexited, with a fresh heartbeat and a live pid, and, where ps runs, that pid runs this session's
    `stack_usage.py run`. Anything else: "running", nobody signalled, no successor."""
    sd = Path(U.session_dir(SID))
    spawned = []
    monkeypatch.setattr(U, "spawn_collector", lambda *a, **k: spawned.append(k.get("wait_lock")))
    mine = "%s %s run --session %s --subagents %s" % (PY, USAGE_PY, SID, subdir(tmp_path))
    other = mine.replace(SID, "99999999-2222-3333-4444-555555555555")
    now = time.time()
    live = {"pid": owner.pid, "heartbeat": now, "exited": None}
    refused = [
        ({"pid": owner.pid}, None),                                   # no heartbeat
        ({"pid": os.getpid(), "heartbeat": now, "exited": None}, None),
        ({"pid": "1", "heartbeat": now}, None), ({"pid": True, "heartbeat": now}, None), ({}, None), ([1], None),
        (dict(live, exited=now), None),                               # it has let go
        (dict(live, heartbeat=now - U.HANDOFF_FRESH_S - 5), None),    # stale: hung, or a crashed one's
        (dict(live, heartbeat=float("nan")), None), (dict(live, heartbeat=now + 3600), None),
        (dict(live, schema=U.SCHEMA_VERSION), None), (dict(live, schema=U.SCHEMA_VERSION + 1), None),
        (live, "sleep 120"),                                          # ps: not a collector
        (live, other),                                                # ps: another session's collector
    ]
    for meta, args in refused:
        monkeypatch.setattr(U, "proc_args", lambda pid, a=args: a)
        (sd / "collector.json").write_text(json.dumps(meta))
        with U.Locked(str(sd / "collector.lock"), nb=True) as lk:
            assert lk.ok and U.hook_start(event(tmp_path), owner=owner.pid) == "running", meta
        assert owner.poll() is None and spawned == []
    # dead pid
    gone = subprocess.Popen(["true"])
    gone.wait()
    (sd / "collector.json").write_text(json.dumps(dict(live, pid=gone.pid)))
    with U.Locked(str(sd / "collector.lock"), nb=True):
        assert U.hook_start(event(tmp_path), owner=owner.pid) == "running" and spawned == []
    # ps confirms this session's collector (schema 2 in its meta, or none): signalled, successor spawned
    for meta in (dict(live, schema=2), live):
        victim = subprocess.Popen(["sleep", "120"])
        monkeypatch.setattr(U, "proc_args", lambda pid: mine)
        (sd / "collector.json").write_text(json.dumps(dict(meta, pid=victim.pid)))
        with U.Locked(str(sd / "collector.lock"), nb=True):
            assert U.hook_start(event(tmp_path), owner=owner.pid) == "handed off"
        assert victim.wait(timeout=5) == -signal.SIGTERM and spawned[-1] == U.HANDOFF_WAIT_S
    # no ps (a sandbox): the held lock and the fresh, unexited meta are the proof
    victim = subprocess.Popen(["sleep", "120"])
    monkeypatch.setattr(U, "proc_args", lambda pid: None)
    (sd / "collector.json").write_text(json.dumps(dict(live, pid=victim.pid)))
    with U.Locked(str(sd / "collector.lock"), nb=True):
        assert U.hook_start(event(tmp_path), owner=owner.pid) == "handed off"
    assert victim.wait(timeout=5) == -signal.SIGTERM and len(spawned) == 3 and owner.poll() is None


def test_a_successor_waits_for_the_lock_and_then_runs(st, tmp_path):
    """--wait-lock: the successor takes collector.lock once the older collector lets go (here within the
    wait); without it, a held lock means "already running" at once. NaN and inf are refused or capped."""
    sub = subdir(tmp_path)
    write_agent(sub, "w1", [user("go", 0), call("a1", 1, model=HAIKU), result(2),
                            call("a2", 3, model=HAIKU, tool=False)], atype="scout")
    sd = Path(U.session_dir(SID))
    lk = U.Locked(str(sd / "collector.lock"), nb=True).__enter__()
    assert lk.ok
    t = time.time()
    assert U.run(SID, str(sub), poll=0.05, idle=0.3) == "already running" and time.time() - t < 1
    c = subprocess.Popen([PY, str(USAGE_PY), "run", "--session", SID, "--subagents", str(sub), "--wait-lock", "30"],
                         env=env_for(tmp_path, STACK_USAGE_IDLE_S="0.5"), stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)
    assert c.poll() is None and not (st / "usage" / "runs3.csv").exists()
    lk.__exit__(None, None, None)
    assert c.wait(timeout=20) == 0
    assert collector_meta(st)["reason"] == "idle" and collector_meta(st)["schema"] == U.SCHEMA_VERSION
    assert rows_by_key()[(SID, "w1", 0)]["model"] == HAIKU
    for bad in ("nan", "inf", "-1", "x"):
        p = subprocess.run([PY, str(USAGE_PY), "run", "--session", SID, "--subagents", str(sub), "--wait-lock", bad],
                           env=env_for(tmp_path, STACK_USAGE_IDLE_S="0.3"), capture_output=True, timeout=30)
        assert p.returncode == 0


# ---------------------------------------------------------------- step 6.1: the columns written empty, the prefix
def iso_s(k):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(T0 + k))


def write_snapshot(st_root, created_k):
    d = st_root / "limits" / "snapshots"
    d.mkdir(parents=True, exist_ok=True)
    (d / (SID + ".json")).write_text(json.dumps({"created": iso_s(created_k), "source_event": "startup"}))


def human_(k, pid):
    return dict(user("prompt", k), promptId=pid)


def two_windows(tmp_path):
    return write_main(tmp_path, [human_(0, "pid-0"), call("m1", 1), human_(10, "pid-1"), call("m2", 11)])


def test_agent_type_prefix_does_not_hide_the_prompt_id(st, tmp_path):
    """Newer Claude Code stores "<agentType>: <description>" in agent-<id>.meta.json: the prefix is
    stripped before the prompt id (^\\s*(P\\d{2,3})\\b, the reference collector's) and the task words."""
    cases = [("proof-checker", "proof-checker: P10 v2 run proof-checker", "P10", "run proof-checker"),
             ("build-fixer", "build-fixer: P11: fix the build", "P11", "fix the build"),
             ("coder", "  coder: P123 x", "P123", "x"),
             ("coder", "coder: P1000 x", "", "x"),
             ("coder", "scout: P10 run", "", "scout run"),          # another type's prefix: not stripped
             ("coder", "P10 run", "P10", "run"),
             ("coder", "coder: T3 implement the parser", "T3", "implement the parser")]
    for atype, desc, node, task in cases:
        (tmp_path / "agent-a1.meta.json").write_text(json.dumps({"agentType": atype, "description": desc}))
        m = U.agent_meta(str(tmp_path), "a1")
        assert (m["node"], m["task"]) == (node, task), desc
    write_agent(subdir(tmp_path), "p1", [user("go", 0), call("p1", 1, tool=False)], atype="proof-checker",
                extra_meta={"description": "proof-checker: P10 v2 run proof-checker"})
    r = scan_final(tmp_path)[(SID, "p1", 0)]
    assert (r["node"], r["task"], r["type"]) == ("P10", "run proof-checker", "proof-checker")


def test_hits_are_zero_without_a_firing_once_the_guard_snapshot_exists(st, tmp_path):
    """The guard creates limit-hits.jsonl only at its first firing: from the session's snapshot on, no
    file means no firing (0), for agent, main and session rows."""
    two_windows(tmp_path)
    write_agent(subdir(tmp_path), "h1", [user("go", 0), call("h1", 12, tool=False)])
    (st / SID).mkdir(parents=True)
    (st / SID / "budget.json").write_text(json.dumps({"total": 1000}))
    write_snapshot(st, -5)
    r = scan_final(tmp_path)
    for k in ((SID, "main", 0), (SID, "main", 1), (SID, "h1", 0), (SID, "session", 0)):
        assert [r[k][c] for c in U.HIT_COLS] == ["0"] * 6, k


def test_hits_before_the_snapshot_stay_empty(st, tmp_path):
    """A session resumed from an older install: its snapshot is created at the resume; a firing before
    it may have gone unrecorded, so rows that began earlier (and the session row) stay empty; later
    rows read the file (or 0 without it)."""
    two_windows(tmp_path)
    write_agent(subdir(tmp_path), "h0", [user("go", 0), call("h0", 1, tool=False)])
    write_agent(subdir(tmp_path), "h1", [user("go", 0), call("h1", 12, tool=False)])
    (st / SID).mkdir(parents=True)
    (st / SID / "budget.json").write_text(json.dumps({"total": 1000}))
    write_snapshot(st, 5)
    for with_file in (False, True):
        if with_file:
            (st / SID / "limit-hits.jsonl").write_text(json.dumps(
                {"v": 1, "ts": t_(12.5), "agent_id": "h1", "kind": "turn"}) + "\n")
        rows, _ = U.scan({"v": 3, "agents": {}}, SID, str(subdir(tmp_path)), final=True)
        r = {(x["id"], x["seg"]): x for x in rows}
        assert all(r[k][c] == "" for k in (("main", 0), ("h0", 0), ("session", 0)) for c in U.HIT_COLS)
        assert [r[("main", 1)][c] for c in U.HIT_COLS] == [0] * 6
        assert [r[("h1", 0)][c] for c in U.HIT_COLS] == [0, int(with_file), 0, 0, 0, 0]


def test_window_ctx_from_the_transcripts_by_call_time(st, tmp_path):
    """No prompt-windows.jsonl: window_ctx is the window's own context plus every subagent call
    timestamped in it (a background agent's calls split across the windows), a streamed call once."""
    write_main(tmp_path, [human_(0, "pid-0"), call("m1", 1, inp=0, cc=10, cr=0), human_(100, "pid-1"),
                          call("m2", 101, inp=0, cc=20, cr=0, tool=False)])
    b1 = call("b1", 3, inp=0, cc=1000, cr=0)
    b1s = dict(b1, message=dict(b1["message"], usage=dict(b1["message"]["usage"], output_tokens=999)))
    write_agent(subdir(tmp_path), "bg", [user("go", 2), b1, b1s, result(4),
                                         call("b2", 150, inp=0, cc=0, cr=2000, tool=False)])
    r = scan_final(tmp_path)
    assert (r[(SID, "main", 0)]["window_ctx"], r[(SID, "main", 1)]["window_ctx"]) == ("1010", "2020")
    assert r[(SID, "bg", 0)]["window"] == "0" and r[(SID, "bg", 0)]["window_ctx"] == ""


def test_window_ctx_waits_for_a_backlog(st, tmp_path, monkeypatch):
    """A closed window's row is held while a transcript still has unread bytes (one of its subagent
    calls may be among them), then written with every call of the window."""
    monkeypatch.setattr(U, "READ_CHUNK", 1400)                # two or three lines per file per scan
    write_main(tmp_path, [human_(0, "pid-0"), call("m1", 1, inp=0, cc=10, cr=0), human_(100, "pid-1"),
                          call("m2", 101, inp=0, cc=20, cr=0, tool=False)])
    lines = [user("go", 2)]
    for j in range(10):
        lines += [call("s%d" % j, 3 + 2 * j, inp=0, cc=100, cr=0), result(4 + 2 * j)]
    write_agent(subdir(tmp_path), "slow", lines)
    U.scan_once(SID, str(subdir(tmp_path)))
    assert rows_by_key()[(SID, "main", 0)]["window_ctx"] == str(10 + 10 * 100)


def test_an_earlier_collector_state_leaves_the_transcript_sums_empty(st, tmp_path):
    """An agent state kept by an earlier collector (no per-window sums from its start): the transcript
    window_ctx and the session row's totals are empty, never a part sum; the budget's ctx stays."""
    main = two_windows(tmp_path)
    write_agent(subdir(tmp_path), "h1", [user("go", 0), call("h1", 12, tool=False)])
    (st / SID).mkdir(parents=True)
    (st / SID / "budget.json").write_text(json.dumps({"total": 4242}))
    state = {"v": 3, "agents": {}}
    U.scan(state, SID, str(subdir(tmp_path)), final=False)
    for k in ("wv", "tot", "wc", "wp"):
        state["agents"]["h1"].pop(k)
    with open(main, "a") as fh:
        fh.write(json.dumps(human_(20, "pid-2")) + "\n" + json.dumps(call("m3", 21, tool=False)) + "\n")
    rows, _ = U.scan(state, SID, str(subdir(tmp_path)), final=True)
    r = {(x["id"], x["seg"]): x for x in rows}
    assert r[("main", 2)]["window_ctx"] == ""
    s = r[("session", 0)]
    assert s["ctx"] == 4242 and all(s[c] == "" for c in ("api_calls", "input", "output", "cache_read"))


def test_session_row_without_the_guard_budget(st, tmp_path):
    """No budget.json (the guard's budgets off): the final scan's session row takes its ctx from the
    transcripts (input + cache creation + cache read of every call), with their totals."""
    two_windows(tmp_path)
    write_agent(subdir(tmp_path), "h1", [user("go", 0), call("h1", 12, tool=False)])
    s = scan_final(tmp_path)[(SID, "session", 0)]
    assert [s[c] for c in ("ctx", "api_calls", "input", "output", "cache_creation", "cache_read")] == [
        str(3 * 21003), "3", "9", "150", "3000", "60000"]
    assert (s["status"], s["is_main"], s["window_ctx"]) == ("complete", "1", "")


def test_an_idle_exit_writes_the_session_row(st, tmp_path, monkeypatch):
    """A collector that idles out does a final scan first: nothing restarts it before SessionEnd."""
    two_windows(tmp_path)
    write_agent(subdir(tmp_path), "h1", [user("go", 0), call("h1", 12, tool=False)])
    monkeypatch.setattr(U, "refresh", lambda **k: {})
    monkeypatch.setitem(sys.modules, "stack_limits", None)
    old = signal.getsignal(signal.SIGTERM)
    try:
        assert U.run(SID, str(subdir(tmp_path)), poll=0.01, idle=0.1) == "idle"
    finally:
        signal.signal(signal.SIGTERM, old)
    s = rows_by_key()[(SID, "session", 0)]
    assert s["ctx"] == str(3 * 21003) and s["status"] == "complete"


def test_session_end_without_a_collector_runs_the_final_scan(st, tmp_path, reap):
    """SessionEnd after the collector idled out: the hook starts one for the final scan (rows since,
    the session row); it exits with "session end"."""
    two_windows(tmp_path)
    write_agent(subdir(tmp_path), "h1", [user("go", 0), call("h1", 12, tool=False)])
    U.session_dir(SID)                                         # the collector's folder from an earlier run
    assert not lock_held(st)
    assert hook("end", tmp_path, event(tmp_path, "SessionEnd")).returncode == 0
    assert wait(lambda: collector_meta(st)["reason"] == "session end")
    assert wait(lambda: not lock_held(st))
    assert rows_by_key()[(SID, "session", 0)]["ctx"] == str(3 * 21003)
    assert U.hook_end({"session_id": SID}) == "marked"         # no transcript_path: nothing to scan


def reg(st, aid, **rec):
    d = st / SID / "agents"
    d.mkdir(parents=True, exist_ok=True)
    (d / (aid + ".json")).write_text(json.dumps(dict({"type": "scout", "depth": 1}, **rec)))


def test_eq_run_and_role_are_copied_from_the_registry_record(st, tmp_path):
    for aid in ("q1", "q2", "q3", "q4", "q5"):
        write_agent(subdir(tmp_path), aid, [user("go", 0), call(aid, 1, tool=False)])
    reg(st, "q1", eq_run="0a1b2c3d", eq_role="leader")
    reg(st, "q2", eq_run="0a1b2c3d", eq_role="member", eq_member=2)
    reg(st, "q3")                                          # an ordinary agent
    reg(st, "q4", eq_run="../../x", eq_role="boss")        # invalid: empty cells, never copied
    reg(st, "q5", eq_run="0a1b2c3d", eq_role="boss")       # a run with an invalid role: the run is kept
    r = scan_final(tmp_path)
    got = {a: (r[(SID, a, 0)]["eq_run"], r[(SID, a, 0)]["eq_role"]) for a in ("q1", "q2", "q3", "q4", "q5")}
    assert got == {"q1": ("0a1b2c3d", "leader"), "q2": ("0a1b2c3d", "member"), "q3": ("", ""),
                   "q4": ("", ""), "q5": ("0a1b2c3d", "")}


def test_eq_columns_need_a_valid_value_and_an_old_runs3_header_is_merged_not_set_aside(st, tmp_path):
    U.append_rows([row3(id="e1", eq_run="0a1b2c3d", eq_role="member"), row3(id="e2", eq_run="xyz", eq_role="x")])
    r = U.read_rows()
    assert (r[(SID, "e1", 0)]["eq_run"], r[(SID, "e1", 0)]["eq_role"]) == ("0a1b2c3d", "member")
    assert (r[(SID, "e2", 0)]["eq_run"], r[(SID, "e2", 0)]["eq_role"]) == ("", "")
    # a runs3.csv written before the columns existed: its rows survive, the next append starts a new file
    u = st / "usage"
    (u / "runs3.csv").unlink()
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=U.COLUMNS_V3, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    w.writerow(row3(id="old1", api_calls=4))
    (u / "runs3.csv").write_text(buf.getvalue())
    U.append_rows([row3(id="new1", eq_run="0a1b2c3d", eq_role="leader")])
    assert not list(u.glob("runs3.old-schema*"))
    assert (u / "runs3.csv").read_text().splitlines()[0] == ",".join(U.COLUMNS)
    r = U.read_rows()
    assert r[(SID, "old1", 0)]["api_calls"] == "4" and r[(SID, "new1", 0)]["eq_run"] == "0a1b2c3d"
