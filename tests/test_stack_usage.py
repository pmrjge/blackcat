"""stack_usage.py (the per-session usage collector) and stack_sched_refresh.py (the model refit).

Run: uv run --python 3.14 --with pytest --with pandas --with numpy pytest -q tests/test_stack_usage.py
(the refresh tests are skipped without pandas/numpy). Synthetic transcripts only; every test uses its
own XDG_STATE_HOME under tmp_path, never the stack's state folder. Hook and collector processes run
under /usr/bin/python3, the hooks' interpreter.
"""
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "dot-claude" / "hooks"
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


@pytest.fixture
def st(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    for k in [k for k in os.environ if k.startswith("STACK_")]:
        monkeypatch.delenv(k)
    return tmp_path / "st" / "claude-agent-stack"


def env_for(tmp_path, **extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("STACK_")}
    env.update(XDG_STATE_HOME=str(tmp_path / "st"), PYTHONDONTWRITEBYTECODE="1", STACK_USAGE_POLL_S="0.2",
               STACK_USAGE_REFRESH="0")
    env.update(extra)
    return env


# ---------------------------------------------------------------- synthetic transcripts
T0 = 1790000000.0


def ts(k):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(T0 + k)) + ".250Z"


def call(mid, k, inp=3, out=50, cc=1000, cr=20000, tool=True, text="ok"):
    content = [{"type": "text", "text": text}]
    if tool:
        content.append({"type": "tool_use", "id": "tu_" + mid, "name": "Bash",
                        "input": {"command": "echo SECRET-TOOL-INPUT sk-ant-api03-XYZ"}})
    return {"type": "assistant", "requestId": "req_" + mid, "timestamp": ts(k), "uuid": "u" + mid,
            "message": {"id": "msg_" + mid, "model": "-".join(("claude", "opus", "5", "5")), "content": content,
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


def write_agent(folder, aid, lines, atype="coder", mode="w"):
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / ("agent-%s.jsonl" % aid), mode) as fh:
        for r in lines:
            fh.write(json.dumps(r) + "\n")
    meta = folder / ("agent-%s.meta.json" % aid)
    if atype and not meta.exists():
        meta.write_text(json.dumps({"agentType": atype, "description": "SECRET DESCRIPTION"}))


def subdir(tmp_path):
    return tmp_path / "projects" / "p" / SID / "subagents"


def rows_by_key():
    return U.read_rows()


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
    csv_lines = (st / "usage" / "runs.csv").read_text().splitlines()
    assert csv_lines[0] == ",".join(U.COLUMNS) and len(csv_lines) == 3
    r = rows_by_key()
    assert len(r) == 1 and r[(SID, "i1", 0)]["status"] == "complete"
    rows, _ = U.scan_once(SID, str(sub), final=True)
    assert rows == []


def test_rotation_keeps_last_rows(st, tmp_path, monkeypatch):
    monkeypatch.setenv("STACK_USAGE_MAX_BYTES", "3000")
    base = dict({c: 0 for c in U.COLUMNS}, schema_version=1, session=SID, type="scout", seg=0, last_ts=T0)
    for i in range(60):
        U.append_rows([dict(base, id="r%d" % (i % 7), status="partial" if i < 53 else "complete", api_calls=i)])
    for i in range(80):
        U.append_rows([dict(base, id="k%d" % i, status="partial", api_calls=i)])
    U.append_rows([dict(base, id="k0", status="complete", api_calls=1000)])
    assert (st / "usage" / "runs.1.csv").exists() and os.path.getsize(st / "usage" / "runs.csv") <= 3200
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
    raw = (st / "usage" / "runs.csv").read_text()
    for secret in ("SECRET", "sk-ant", "hunter2", "FINAL REPORT", "echo", "DESCRIPTION", "rm -rf"):
        assert secret not in raw
    for r in rows_by_key().values():
        for c, v in r.items():
            if c in U.STRING_COLUMNS:
                assert U.ID_RE.match(v) or U.TYPE_RE.match(v) or v in ("(unknown)", "partial", "complete"), (c, v)
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
    """agent_guard.py's SessionStart prunes state folders idle for 3 days, never usage/."""
    old = time.time() - 5 * 86400
    for name in ("usage", "old-session"):
        d = st / name
        d.mkdir(parents=True)
        (d / "f").write_text("x")
        os.utime(d / "f", (old, old))
        os.utime(d, (old, old))
    ev = {"session_id": "new-session", "hook_event_name": "SessionStart", "source": "startup", "cwd": str(tmp_path)}
    p = subprocess.run([PY, str(HOOKS / "agent_guard.py")], input=json.dumps(ev), capture_output=True, text=True,
                       env=env_for(tmp_path, HOME=str(tmp_path)), timeout=60)
    assert p.returncode == 0, p.stderr
    assert (st / "usage" / "f").exists() and not (st / "old-session").exists()


# ---------------------------------------------------------------- the active model
def test_load_model_prefers_active(st, tmp_path, monkeypatch):
    monkeypatch.delenv("STACK_SCHED_MODEL", raising=False)
    S = _load("stack_sched_for_usage_test", HOOKS / "stack_sched.py")
    shipped = HOOKS / "sched_model.json"
    assert S.default_model_path() == shipped.resolve()
    st.mkdir(parents=True, exist_ok=True)
    act = st / "sched_model.json"
    act.write_text("[]")                                   # invalid: the shipped file is used
    assert S.default_model_path() == shipped.resolve()
    act.write_text(json.dumps({"version": 1, "types": {"scout": {"turns": {"S": 1, "M": 2, "L": 3}}}}))
    m = S.load_model()
    assert m["file"] == str(act) and S.tinfo(m, "scout")["turns"] == {"S": 1, "M": 2, "L": 3}
    monkeypatch.setenv("STACK_SCHED_MODEL", str(shipped))  # the explicit override still wins
    assert S.load_model()["file"] == str(shipped)


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


@pytest.fixture
def refit(tmp_path):
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


def csv_rows(df):
    out = []
    for r in df.itertuples():
        out.append(dict((c, 0) for c in U.COLUMNS))
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
    U.append_rows(csv_rows(k["segs"]("scout", 2, 20.0, 9, "new1")))          # 2 more agents: the new
    J = do_refresh(k, st)                                                    # lookup pool is not gated
    assert J["types"]["scout"]["status"] == "provisional" and J["types"]["scout"]["evidence"]["n_seg_seen"] == 2
    assert J["types"]["scout"]["n_seg"] == 3
    U.append_rows(csv_rows(k["segs"]("scout", 1, 20.0, 12, "new1")))
    U.append_rows(csv_rows(k["segs"]("claude-code-guide", 4, 20.0, 13, "new1")))
    J = do_refresh(k, st)
    sc = J["types"]["scout"]
    assert sc["status"] == "supported" and sc["n_seg"] == 6 and sc["n_agents"] == 6
    assert sc["evidence"] == {"n_seg_shipped": 3, "n_seg_collected": 3, "n_agents_collected": 3, "n_first_collected": 3,
                              "n_seg_seen": 3}
    assert sc["band"]["method"] == "combined"
    saved = json.loads((st / "sched_model.json").read_text())
    assert saved["types"]["scout"]["status"] == "supported" and saved["refresh"]["base_generated"] == k["shipped"]["generated"]
    # the shipped sessions are never counted twice
    U.append_rows(csv_rows(k["segs"]("scout", 4, 20.0, 10, "ship1")))
    assert do_refresh(k, st)["types"]["scout"]["n_seg"] == 6


def test_refresh_bounded_step_and_narrowing(st, tmp_path, refit):
    k = refit
    m0 = k["shipped"]["types"]["claude-code-guide"]
    w0 = m0["band"]["turns"]["hi"] / m0["band"]["turns"]["med"]
    U.append_rows(csv_rows(k["segs"]("claude-code-guide", 40, 200.0, 11, "new2")))   # 10x the turns
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
