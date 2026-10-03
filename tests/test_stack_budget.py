"""stack-budget (dot-claude/bin/stack-budget): the read-only budget view.

Run: uv run --python 3.12 --with pytest pytest -q tests/test_stack_budget.py
Every test uses a temp XDG_STATE_HOME and synthetic rows / snapshots; the CLI runs on /usr/bin/python3.
"""
import csv
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "dot-claude" / "hooks"
CLI = ROOT / "dot-claude" / "bin" / "stack-budget"
PY = "/usr/bin/python3"
SID = "33333333-3333-4333-8333-333333333333"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, HOOKS / (name + ".py"))
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    for k in [k for k in os.environ if k.startswith("STACK_") or k == "CLAUDE_SESSION_ID"]:
        monkeypatch.delenv(k)
    (tmp_path / "st" / "claude-agent-stack").mkdir(parents=True)
    return tmp_path / "st" / "claude-agent-stack"


def run(*args, extra=None, py=PY):
    e = dict(os.environ, **(extra or {}))
    return subprocess.run([py, str(CLI)] + list(args), capture_output=True, text=True, env=e, check=False)


def js(*args, extra=None):
    p = run(*args, "--json", extra=extra)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def snapshot(**envs):
    L = sys.modules.get("stack_limits") or _load("stack_limits")
    for k, v in envs.items():
        os.environ[k] = v
    try:
        path, _ = L.apply_and_snapshot({"session_id": SID, "source": "startup"}, spawn=False)
    finally:
        for k in envs:
            os.environ.pop(k, None)
    return path


def write_rows(env, scout_ctx):
    U = sys.modules.get("stack_usage") or _load("stack_usage")
    d = env / "usage"
    d.mkdir(exist_ok=True)
    with open(d / "runs2.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=U.COLUMNS)
        w.writeheader()
        for i, c in enumerate(scout_ctx):
            w.writerow(dict(U.EMPTY_ROW, schema_version="2", session=SID, id="a%d" % i, type="scout", seg="0",
                            status="complete", api_calls=str(4 + i), ctx=str(c), first_ts=str(1000 + i),
                            last_ts=str(1100 + i), src="measured"))


def tree(env):
    out = {}
    for p in sorted(env.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(env))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def test_help_runs_on_the_system_python():
    for args in (["--help"], ["plan", "--help"], ["agent", "--help"]):
        assert run(*args).returncode == 0


def test_summary_shows_the_frozen_limits_with_origin(env):
    snapshot(STACK_SOFTCTX_SCOUT="300000")
    write_rows(env, [500000, 520000, 540000, 560000, 580000, 600000])
    d = js("--session", SID)
    assert d["session"]["values_from"] == "snapshot" and d["session"]["snapshot"] == "ok"
    row = next(r for r in d["types"] if r["type"] == "scout")
    assert row["soft"]["value"] == 300000 and row["soft"]["origin"] == "env"
    assert row["ctx"]["n"] == 6 and row["verdict_soft"] == "does not fit"        # the whole CI is over 300k
    assert row["turns"]["origin"] in ("seed", "live")
    txt = run("--session", SID).stdout
    assert "scout" in txt and "does not fit" in txt and "300k/e" in txt


def test_verdict_is_uncertain_when_the_interval_straddles_the_limit(env):
    snapshot(STACK_SOFTCTX_SCOUT="300000")
    write_rows(env, [100000, 150000, 250000, 320000, 400000, 450000])
    row = next(r for r in js("--session", SID)["types"] if r["type"] == "scout")
    lo, hi = row["ctx"]["ci"]
    assert lo <= 300000 < hi and row["verdict_soft"] == "uncertain"
    write_rows(env, [100000, 110000, 120000, 130000, 140000, 150000])
    assert next(r for r in js("--session", SID)["types"] if r["type"] == "scout")["verdict_soft"] == "fits"
    write_rows(env, [100000, 110000])                                           # n < 3: no interval, never "fits"
    r = next(r for r in js("--session", SID)["types"] if r["type"] == "scout")
    assert r["ctx"]["ci"] is None and r["verdict_soft"] == "uncertain"


def test_consumption_against_prompt_and_session_limits(env):
    snapshot(STACK_SOFT_PROMPT_CTX="5000000", STACK_SESSION_CTX_BUDGET="400000000")
    sdir = env / SID
    sdir.mkdir()
    (sdir / "budget.json").write_text(json.dumps({"total": 450000000, "prompt_base": 440000000}))
    d = js("--session", SID)
    by = {x["var"]: x for x in d["limits"]}
    assert d["consumption"] == {"session": 450000000.0, "prompt": 10000000.0}
    assert by["soft.prompt"]["verdict"] == "does not fit" and by["hard.session"]["verdict"] == "does not fit"
    assert by["hard.prompt"]["verdict"] == "fits"
    assert by["soft.prompt"]["origin"] == "env"


def test_sid_from_the_snapshot_env_and_the_newest_snapshot(env):
    snapshot(STACK_SOFTCTX_SCOUT="300000")
    p = js(extra={"STACK_LIMITS_SNAPSHOT": str(Path(env, "limits", "snapshots", SID + ".json"))})
    assert p["session"]["id"] == SID and p["session"]["found_by"] == "STACK_LIMITS_SNAPSHOT"
    q = js()
    assert q["session"]["id"] == SID and q["session"]["found_by"] == "newest snapshot"
    r = js("--session", "44444444-4444-4444-8444-444444444444")
    assert r["session"]["snapshot"] == "missing" and r["session"]["values_from"] == "seed"


def test_nothing_is_ever_written(env, tmp_path):
    snapshot()
    write_rows(env, [1000] * 4)
    g = tmp_path / "g.json"
    g.write_text(json.dumps({"job": "j", "nodes": [{"id": "A", "a": "scout", "n": 5}]}))
    before = tree(env)
    for args in (["--session", SID], ["--session", "44444444-4444-4444-8444-444444444444"], ["agent", "scout"],
                 ["plan", str(g), "--session", SID], ["--all"]):
        assert run(*args).returncode == 0, args
    assert tree(env) == before                                                  # no snapshot created, nothing changed


def test_agent_prints_seed_live_snapshot_interval_and_recent_rows(env):
    L = sys.modules.get("stack_limits") or _load("stack_limits")
    snapshot()
    write_rows(env, [200000, 210000, 220000, 230000, 240000, 250000])
    live = L.live_from_seed(L.load_seed())
    st = live["vars"]["soft.agent.scout"]
    st.update(status="provisional", n=4, ci=[350000, 420000])
    (env / "limits" / "live.json").write_text(json.dumps(live))
    d = js("agent", "scout", "--session", SID)
    assert d["soft"]["seed"] == 390000 and d["soft"]["status"] == "provisional" and d["soft"]["ci"] == [350000, 420000]
    assert d["soft"]["origin"] in ("seed", "live") and len(d["recent"]) == 5 and d["recent"][-1]["id"] == "a5"
    txt = run("agent", "scout", "--session", SID).stdout
    assert "[350k-420k]" in txt and "provisional" in txt
    assert run("agent", "no-such-type").returncode == 1
    assert js("agent", "scout-copy", "--session", SID)["type"] == "scout"


def test_plan_gives_intervals_and_a_verdict_per_node_and_for_the_plan(env, tmp_path):
    snapshot(STACK_SOFT_PROMPT_CTX="5000000")
    sdir = env / SID
    sdir.mkdir()
    (sdir / "budget.json").write_text(json.dumps({"total": 700000000, "prompt_base": 0}))
    g = tmp_path / "g.json"
    g.write_text(json.dumps({"job": "j", "dispatcher": "blackcat", "nodes": [
        {"id": "A", "a": "claude-code-engineer", "n": 80}, {"id": "B", "a": "scout", "n": 3, "dep": ["A"]}]}))
    d = js("plan", str(g), "--session", SID)
    nodes = {n["id"]: n for n in d["nodes"]}
    assert nodes["A"]["ctx"][1] >= nodes["A"]["ctx"][0] > 0 and nodes["A"]["verdict_soft"] in ("fits", "uncertain", "does not fit")
    assert nodes["B"]["verdict_turns"] == "fits" and nodes["B"]["limits"]["soft"] == 390000
    plan = {w["scope"]: w for w in d["plan"]}
    assert plan["prompt soft"]["limit"] == 5000000 and plan["prompt soft"]["verdict"] == "does not fit"
    assert plan["session hard"]["already_used"] == 700000000.0 and plan["session hard"]["verdict"] == "does not fit"
    assert d["verdict"] == "does not fit"
    txt = run("plan", str(g), "--session", SID).stdout
    assert "whole plan vs prompt soft" in txt and "verdict: does not fit" in txt
    (tmp_path / "bad.json").write_text("{")
    assert run("plan", str(tmp_path / "bad.json")).returncode == 1


def test_static_wraps_prompt_budget():
    p = run("static", "--json")
    assert p.returncode == 0 and "head" in json.loads(p.stdout)


def test_stdlib_only_and_python38_syntax():
    import ast
    tree_ = ast.parse(CLI.read_text())
    mods = {n.names[0].name.split(".")[0] for n in ast.walk(tree_) if isinstance(n, ast.Import)}
    assert mods <= {"argparse", "importlib", "json", "os", "subprocess", "sys"}


def test_install_stages_and_tracks_the_script():
    install = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert install.count("stack-budget") >= 2                 # staged (stage_script loop) and tracked in STACK_SCRIPTS
    assert os.access(CLI, os.X_OK)


def test_overridden_runs_are_left_out_and_counted(env):
    """Runs of a type on another model than its frontmatter's (/override-agent; scout is sonnet) are not
    in the sample, as the learner leaves them out, and the views say how many."""
    snapshot()
    U = sys.modules.get("stack_usage") or _load("stack_usage")
    d = env / "usage"
    d.mkdir(exist_ok=True)
    runs = [(500000, "claude-sonnet-5-5"), (510000, ""), (520000, "claude-sonnet-5-5"),
            (9000000, "claude-haiku-4-5-20251001"), (9100000, "claude-opus-5-5")]
    with open(d / "runs3.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=U.COLUMNS)
        w.writeheader()
        for i, (c, m) in enumerate(runs):
            w.writerow(dict(U.EMPTY_ROW, schema_version="3", session=SID, id=f"b{i}", type="scout", seg="0",
                            status="complete", api_calls=str(4 + i), ctx=str(c), first_ts=str(1000 + i),
                            last_ts=str(1100 + i), src="measured", model=m))
    d = js("--session", SID)
    row = next(r for r in d["types"] if r["type"] == "scout")
    assert row["ctx"]["n"] == 3 and row["ctx"]["max"] == 520000 and row["model_mismatch"] == 2
    assert d["model_mismatch"] == 2
    assert "leaves out 2 completed runs on another model than the frontmatter's (/override-agent): scout 2" in \
        run("--session", SID).stdout
    a = js("agent", "scout", "--session", SID)
    assert a["ctx"]["n"] == 3 and a["model_mismatch"] == 2
    assert "left out, run on another model than the frontmatter's (/override-agent): 2" in \
        run("agent", "scout", "--session", SID).stdout
