"""bin/stack-who: who is running in the session (id, type, name, state, layer, parent, start, task) built from
the guard's registry and delegation records through bin/stack-tree's reader. Read-only, redacted, bounded,
fail-open. Runs use /usr/bin/python3 like the script's shebang. STACK_WHO_UNDER_TEST points the suite at another
copy of the script (mutation proofs: a copy with stack-tree beside it)."""
import json
import os
from pathlib import Path

import pytest

import test_stack_tree as tt

ROOT = Path(__file__).resolve().parents[1]
WHO = Path(os.environ.get("STACK_WHO_UNDER_TEST") or ROOT / "dot-config" / "dot-claude" / "bin" / "stack-who")
SID = tt.SID
SNAP = "/x/limits/snapshots/%s.json" % SID


@pytest.fixture
def fx(tmp_path):
    f = tt.Fixture(tmp_path)
    f.spawn("t1", "main", "orchestrator", "Port attention kernel to MLX", child="aorch000001", ts=f.t0)
    f.agent("aorch000001", "orchestrator", stopped=False, depth=1)
    f.spawn("t2", "aorch000001", "mlx-engineer", "Kernels in src/kernels", child="amlx0000002", ts=f.t0 + 1,
            name="mlxport-kernels")
    f.agent("amlx0000002", "mlx-engineer", parent="aorch000001", stopped=False, depth=2, name="mlxport-kernels")
    f.spawn("t3", "aorch000001", "test-engineer", "Tests for the kernel port", child="atest000003", ts=f.t0 + 2,
            status="completed")
    f.agent("atest000003", "test-engineer", parent="aorch000001", depth=2,
            report={"status": "partial"})
    f.spawn("t4", "amlx0000002", "mathematician", "fp16 error bound token=%s" % tt.SECRET, child="amath000004",
            ts=f.t0 + 3, status="completed")
    f.agent("amath000004", "mathematician", parent="amlx0000002", depth=3)
    f.spawn("t6", "aorch000001", "scout", "Look up the MLX version", child="ascout00006", ts=f.t0 + 4,
            status="failed")
    f.agent("ascout00006", "scout", parent="aorch000001", depth=2)
    return f


def who(f, *args, **env):
    env.setdefault("STACK_LIMITS_SNAPSHOT", SNAP)
    return f.run(*args, script=WHO, **env)


def body(p):
    assert p.returncode == 0, p.stderr
    lines = p.stdout.splitlines()
    return lines[0], lines[1:]


def test_table_lines_carry_id_type_state_layer_parent_task(fx):
    head, rows = body(who(fx))
    assert "session %s (this shell's)" % SID in head and "5 agents, 2 running" in head
    assert len(rows) == 5
    k = [r for r in rows if r.startswith("amlx0000002 ")][0]
    assert " · mlx-engineer name mlxport-kernels · running · L2 · parent aorch000001 · started " in k
    assert k.endswith('"Kernels in src/kernels"')
    t = [r for r in rows if r.startswith("atest000003 ")][0]
    assert " · finished/partial · L2 · parent aorch000001 " in t
    m = [r for r in rows if r.startswith("amath000004 ")][0]
    assert " · L3 · parent amlx0000002 " in m


def test_filters_keyword_type_state_and_id_prefix(fx):
    # every word must match the task, type or name (amlx: "port" and "kernel" are in its name)
    assert [r.split(" ")[0] for r in body(who(fx, "kernel", "port"))[1]] == [
        "aorch000001", "amlx0000002", "atest000003"]
    assert [r.split(" ")[0] for r in body(who(fx, "kernel", "tests"))[1]] == ["atest000003"]
    assert [r.split(" ")[0] for r in body(who(fx, "--type", "mathematician"))[1]] == ["amath000004"]
    assert {r.split(" ")[0] for r in body(who(fx, "--running"))[1]} == {"aorch000001", "amlx0000002"}
    assert {r.split(" ")[0] for r in body(who(fx, "--finished"))[1]} == {"atest000003", "amath000004", "ascout00006"}
    assert " · failed · L2 · " in body(who(fx, "--type", "scout"))[1][0]
    assert [r.split(" ")[0] for r in body(who(fx, "--id", "atest0"))[1]] == ["atest000003"]
    assert body(who(fx, "--id", "atest"))[1] == []                    # a prefix under 6 characters matches nothing
    assert [r.split(" ")[0] for r in body(who(fx, "--name", "mlxport-kernels"))[1]] == ["amlx0000002"]


def test_task_text_is_redacted_and_cleaned(fx):
    fx.spawn("t5", "main", "coder", tt.HOSTILE, child="acoder00005", ts=fx.t0 + 9)
    fx.agent("acoder00005", "coder", stopped=False, depth=1)
    out = who(fx).stdout
    assert tt.SECRET not in out and "token=***" in out
    assert "\x1b" not in out and "\r" not in out and "\x07" not in out


def test_bounded_output(fx):
    for i in range(12):
        fx.spawn("x%d" % i, "main", "scout", "lookup %d" % i, child="ascout%05d" % i, ts=fx.t0 + 20 + i)
    head, rows = body(who(fx, "--max", "5"))
    assert len(rows) == 6 and rows[-1].startswith("… 12 more")
    j = json.loads(who(fx, "--max", "3", "--json").stdout)
    assert len(j["matches"]) == 3 and j["cut"] == 14 and j["agents"] == 17


def test_session_sources(fx):
    p = who(fx, STACK_LIMITS_SNAPSHOT="")          # no session named: no table, never the newest one
    assert p.returncode == 0 and p.stdout.startswith("stack-who: no agent table (this shell names no session")
    assert SID not in p.stdout
    head, _ = body(who(fx, "--session", SID, STACK_LIMITS_SNAPSHOT=""))
    assert "(given)" in head


def test_fail_open_and_usage_errors(fx, tmp_path):
    p = who(fx, XDG_STATE_HOME=str(tmp_path / "nothing"), STACK_LIMITS_SNAPSHOT="")
    assert p.returncode == 0 and p.stdout.startswith("stack-who: no agent table (this shell names no session")
    p = who(fx, "--session", "other-session")
    assert p.returncode == 0 and "no agent table" in p.stdout
    lone = tmp_path / "lone"
    lone.mkdir()
    (lone / "stack-who").write_bytes(WHO.read_bytes())      # no stack-tree beside it: the reader cannot load
    p = fx.run(script=lone / "stack-who", STACK_LIMITS_SNAPSHOT=SNAP)
    assert p.returncode == 0 and p.stdout.startswith("stack-who: no agent table (FileNotFoundError)")
    assert who(fx, "--max", "0").returncode == 2
    assert who(fx, "--session", "../etc").returncode == 2
    assert who(fx, "--running", "--finished").returncode == 2


def test_read_only(fx):
    def snap():
        return sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in fx.state.rglob("*"))
    before = snap()
    body(who(fx))
    body(who(fx, "--json"))
    assert snap() == before


def test_installed_by_install_sh():
    text = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert '\nstage_script 755 "bin/stack-who"\n' in text and '"bin/stack-who",' in text
    assert os.access(ROOT / "dot-config" / "dot-claude" / "bin" / "stack-who", os.X_OK)


def test_resumed_after_failure_is_running(fx):
    # the first run's Agent call failed; a SendMessage resumed it later (resumed > stopped): running again,
    # in stack-who and in stack-tree (one reader, bin/stack-tree ledger_state)
    fx.spawn("t7", "aorch000001", "coder", "Retry the flaky fixture", child="acoder00007", ts=fx.t0 + 5,
             status="failed")
    fx.agent("acoder00007", "coder", parent="aorch000001", depth=2, resumed=fx.t0 + 400)
    row = body(who(fx, "--type", "coder"))[1][0]
    assert " · coder · running · L2 · " in row
    assert [r.split(" ")[0] for r in body(who(fx, "--running"))[1]].count("acoder00007") == 1
    assert "acoder00007" not in who(fx, "--finished").stdout
    # an older resume (before the last stop) leaves the failure in place
    fx.agent("acoder00007", "coder", parent="aorch000001", depth=2, resumed=fx.t0 + 10)
    assert " · coder · failed · L2 · " in body(who(fx, "--type", "coder"))[1][0]


def test_caps_hold(fx):
    long_task = "Q" * 89 + "XYZ" + "w" * 30                 # 122 characters, no spaces to fold
    fx.spawn("tl", "main", "scout", long_task, child="along00000", ts=fx.t0 + 6)
    for i in range(205):
        fx.spawn("c%d" % i, "main", "scout", "lookup %d" % i, child="acap%06d" % i, ts=fx.t0 + 30 + i)
    head, rows = body(who(fx, "--max", "500"))                 # asks for 500, MAX_CAP 200 holds
    assert len(rows) == 201 and rows[-1].startswith("… 11 more")
    row = [r for r in body(who(fx, "--id", "along0"))[1]][0]
    task = row.split(' · "', 1)[1][:-1]
    assert task == "Q" * 89 + "…"                              # TASK_CAP 90: 89 characters and the ellipsis
    assert len(json.loads(who(fx, "--max", "500", "--json").stdout)["matches"]) == 200


def test_layer_from_registry_when_a_spawn_is_lost(fx):
    # alost's spawn record is lost and so is its parent's; the registry still knows its depth and parent
    fx.agent("alost00008", "coder", parent="aghost00009", stopped=False, depth=3)
    rows = body(who(fx))[1]
    row = [r for r in rows if r.startswith("alost00008 ")][0]
    assert " · coder · running · L3 · parent aghost00009 · " in row
    assert not [r for r in rows if r.startswith("aghost00009 ")]       # an unknown parent is no agent
    # once the registry knows the parent it is an agent like any other
    fx.agent("aghost00009", "main-coder", parent="main", stopped=False, depth=1)
    rows = body(who(fx))[1]
    assert [r for r in rows if r.startswith("aghost00009 ")]
    assert "aghost00009" not in who(fx, "--finished").stdout
    # a spawn record naming the wrong caller moves the node in the tree; the registry's parent and depth win
    fx.spawn("t9", "main", "verifier", "Re-run the suite", child="adrift00010", ts=fx.t0 + 7)
    fx.agent("adrift00010", "verifier", parent="aorch000001", stopped=False, depth=2)
    row = body(who(fx, "--type", "verifier"))[1][0]
    assert " · verifier · running · L2 · parent aorch000001 · " in row


def test_no_bytecode_written_without_dash_b(fx, tmp_path):
    import shutil
    import subprocess
    b = tmp_path / "bin"
    b.mkdir()
    shutil.copy(WHO, b / "stack-who")
    shutil.copy(WHO.parent / "stack-tree", b / "stack-tree")
    p = subprocess.run([tt.PY, str(b / "stack-who")], capture_output=True, text=True, timeout=60,
                       env=fx.env(STACK_LIMITS_SNAPSHOT=SNAP))
    assert p.returncode == 0 and p.stdout.startswith("stack-who · session"), p.stdout + p.stderr
    # Apple's python keeps stdlib bytecode under $HOME/Library/Caches (sys.pycache_prefix): not ours. The
    # check is bin/ itself and any cache entry for the two scripts, wherever the prefix puts it.
    assert not list(b.rglob("__pycache__")) and not list(b.rglob("*.pyc"))
    assert not [x for x in tmp_path.rglob("*.pyc") if "stack" in x.name or "/bin/" in str(x)]
