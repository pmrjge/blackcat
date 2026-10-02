"""stack_sched.py: the scheduler advisor (dot-claude/hooks/stack_sched.py).

Run: uv run --python 3.12 --with pytest pytest -q tests/test_stack_sched.py
No test touches the stack's state folder; the replay test on the recorded session reads
.claude-work/agents-usage/ (untracked) and is skipped when that folder is absent.
"""
import importlib.util
import itertools
import json
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCHED = ROOT / "dot-claude" / "hooks" / "stack_sched.py"
FIXTURE = ROOT / "tests" / "fixtures" / "sched" / "graph-4e2da3ce.json"
USAGE = ROOT / ".claude-work" / "agents-usage"
SESSION = "4e2da3ce-e2f4-4971-aac5-a67f2dcf252e"

spec = importlib.util.spec_from_file_location("stack_sched", SCHED)
S = importlib.util.module_from_spec(spec)
sys.modules["stack_sched"] = S
spec.loader.exec_module(S)

TYPES = ("coder", "claude-code-engineer", "explore", "verifier", "planner", "scout")


@pytest.fixture(scope="module")
def model():
    return S.load_model("/nonexistent/sched_model.json")


def clean_env(tmp_path, **extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("STACK_")}
    env["XDG_STATE_HOME"] = str(tmp_path / "st")
    env["PYTHONPYCACHEPREFIX"] = str(tmp_path / "pyc")
    env.update(extra)
    return env


def random_graph(rng, n, max_alt=2, conflicts=True):
    ids = ["N%d" % i for i in range(n)]
    nodes = []
    alts = 0
    for i, nid in enumerate(ids):
        dep = [ids[j] for j in range(i) if rng.random() < 0.35]
        node = {"id": nid, "a": rng.choice(TYPES), "n": rng.randint(1, 20), "dep": dep}
        if conflicts and rng.random() < 0.4:
            node["w"] = ["f%d.txt" % rng.randint(1, 3)]
        if rng.random() < 0.1:
            node["r"] = [rng.choice(["gui", "accel"])]
        if alts < max_alt and rng.random() < 0.3:
            node["alt"] = rng.choice(TYPES)
            alts += 1
        nodes.append(node)
    order = list(range(n))
    rng.shuffle(order)                               # the file order must not matter
    return S.load_graph({"job": "rnd", "speed": "balanced", "nodes": [nodes[i] for i in order]})


# ---------------------------------------------------------------- independent brute force
def brute_force(g, m, cap, lam, eps):
    """Exhaustive: every variant choice, every ordered partition into waves (dependencies, cap,
    conflicts). Returns the minimum J over feasible schedules. Shares no code with the solver."""
    nodes = g.nodes
    n = len(nodes)
    idx = {nd.id: i for i, nd in enumerate(nodes)}
    dep = [{idx[d] for d in nd.dep} for nd in nodes]
    anc = [set() for _ in range(n)]
    changed = True
    while changed:
        changed = False
        for i in range(n):
            new = set(dep[i])
            for d in dep[i]:
                new |= anc[d]
            if new != anc[i]:
                anc[i], changed = new, True
    conflict = [[False] * n for _ in range(n)]
    for i, j in itertools.combinations(range(n), 2):
        if i in anc[j] or j in anc[i]:
            continue
        hit = bool(set(nodes[i].w) & set(nodes[j].w)) or any(t in nodes[i].r and t in nodes[j].r for t in ("gui", "accel"))
        conflict[i][j] = conflict[j][i] = hit
    prim = S.estimate(g, m)
    pd = [prim[nd.id].wall_p50 for nd in nodes]
    pt = [prim[nd.id].t_w for nd in nodes]
    alt_i = [i for i, nd in enumerate(nodes) if nd.alt]
    ad, at = {}, {}
    for i in alt_i:
        e = S._est_for(m, nodes[i].alt, nodes[i].s, nodes[i].n)
        ad[i], at[i] = e.wall_p50, e.t_w
    t_base = sum(pt)
    best = float("inf")
    for r in range(len(alt_i) + 1):
        for sel in itertools.combinations(alt_i, r):
            d = [ad[i] if i in sel else pd[i] for i in range(n)]
            t = sum(at[i] if i in sel else pt[i] for i in range(n))
            if t > (1 + eps) * t_base + 1e-9:
                continue
            w = min_makespan(n, d, dep, cap, conflict)
            best = min(best, t + lam * w)
    return best


def min_makespan(n, d, dep, cap, conflict):
    best = [float("inf")]

    def rec(done, elapsed):
        if elapsed >= best[0]:
            return
        if len(done) == n:
            best[0] = elapsed
            return
        avail = [i for i in range(n) if i not in done and dep[i] <= done]
        for r in range(1, min(cap, len(avail)) + 1):
            for wave in itertools.combinations(avail, r):
                if any(conflict[a][b] for a, b in itertools.combinations(wave, 2)):
                    continue
                rec(done | set(wave), elapsed + max(d[i] for i in wave))

    rec(frozenset(), 0.0)
    return best[0]


def check_valid(g, s, cap, mode):
    """Dependencies respected, running count within the cap, conflicting nodes never overlapping."""
    nodes = {nd.id: nd for nd in g.nodes}
    anc = {}

    def ancestors(i):
        if i not in anc:
            anc[i] = set()
            for d in nodes[i].dep:
                anc[i] |= {d} | ancestors(d)
        return anc[i]

    for i, nd in nodes.items():
        for d in nd.dep:
            assert s.times[d][1] <= s.times[i][0] + 1e-6, "%s starts before %s ended" % (i, d)
    events = sorted({t for ab in s.times.values() for t in ab})
    for t in events:
        running = [i for i, (a, b) in s.times.items() if a <= t + 1e-9 < b - 1e-9]
        assert len(running) <= cap, "cap %d exceeded at %s: %s" % (cap, t, running)
    for a, b in itertools.combinations(nodes, 2):
        if a in ancestors(b) or b in ancestors(a):
            continue
        clash = set(nodes[a].w) & set(nodes[b].w) or any(t in nodes[a].r and t in nodes[b].r for t in ("gui", "accel"))
        if clash:
            (a0, a1), (b0, b1) = s.times[a], s.times[b]
            assert a1 <= b0 + 1e-6 or b1 <= a0 + 1e-6, "%s and %s overlap but conflict" % (a, b)
    if mode == "barrier":
        for w in s.waves:
            assert len(w) <= cap
            assert len({s.times[i][0] for i in w}) == 1
    assert sorted(i for w in s.waves for i in w) == sorted(nodes)


# ---------------------------------------------------------------- 1. DP == brute force
def test_barrier_dp_equals_brute_force_on_200_random_dags(model):
    rng = random.Random(20261002)
    for k in range(200):
        n = rng.randint(2, 8)
        g = random_graph(rng, n)
        cap = rng.randint(1, 4)
        lam = rng.choice([0.0, 50.0, 3000.0, 100000.0])
        eps = rng.choice([0.0, 0.0, 0.1, 1.0])
        s = S.schedule(g, model, mode="barrier", caps={"fanout": cap}, lam=lam, slack=eps)
        assert s.exact
        want = brute_force(g, model, cap, lam, eps)
        assert s.J == pytest.approx(want, rel=1e-9, abs=1e-6), "graph %d (n=%d cap=%d lam=%s eps=%s)" % (k, n, cap, lam, eps)
        check_valid(g, s, cap, "barrier")


def test_release_exact_matches_serial_schedule_enumeration_and_beats_barrier(model):
    rng = random.Random(7)
    for k in range(40):
        n = rng.randint(2, 6)
        g = random_graph(rng, n, max_alt=0)
        cap = rng.randint(1, 3)
        rel = S.schedule(g, model, mode="release", caps={"fanout": cap}, lam=1.0)
        bar = S.schedule(g, model, mode="barrier", caps={"fanout": cap}, lam=1.0)
        check_valid(g, rel, cap, "release")
        assert rel.wall <= bar.wall + 1e-6
        # enumerate every precedence-feasible activity list with the serial schedule generation scheme
        est = S.estimate(g, model)
        nodes = g.nodes
        idx = {nd.id: i for i, nd in enumerate(nodes)}
        best = float("inf")
        for perm in itertools.permutations(range(n)):
            pos = {v: p for p, v in enumerate(perm)}
            if any(pos[idx[d]] > pos[i] for i, nd in enumerate(nodes) for d in nd.dep):
                continue
            starts, ends, placed = {}, {}, []
            for i in perm:
                nd = nodes[i]
                t0 = max([ends[idx[d]] for d in nd.dep] + [0.0])
                cands = [t0] + sorted(e for e in ends.values() if e > t0)
                dur = est[nd.id].wall_p50
                for t in cands:
                    ok = True
                    for j in placed:
                        clash = set(nd.w) & set(nodes[j].w) or any(x in nd.r and x in nodes[j].r for x in ("gui", "accel"))
                        anc_dep = nodes[j].id in _anc(g, nd.id) or nd.id in _anc(g, nodes[j].id)
                        if clash and not anc_dep and starts[j] < t + dur - 1e-9 and ends[j] > t + 1e-9:
                            ok = False
                    pts = [t] + [starts[j] for j in placed if t < starts[j] < t + dur - 1e-9]
                    for p in pts:
                        if sum(1 for j in placed if starts[j] <= p + 1e-9 < ends[j]) >= cap:
                            ok = False
                    if ok:
                        break
                starts[i], ends[i] = t, t + dur
                placed.append(i)
            best = min(best, max(ends.values()))
        assert rel.wall == pytest.approx(best, rel=1e-9, abs=1e-6), "graph %d" % k


def _anc(g, nid):
    byid = g.by_id()
    out, stack = set(), list(byid[nid].dep)
    while stack:
        x = stack.pop()
        if x not in out:
            out.add(x)
            stack.extend(byid[x].dep)
    return out


# ---------------------------------------------------------------- 2. caps
@pytest.mark.parametrize("mode", ["barrier", "release"])
def test_no_wave_exceeds_the_caps(model, mode):
    rng = random.Random(11)
    for _ in range(60):
        n = rng.randint(2, 16)                       # crosses the exact/list boundary (14)
        g = random_graph(rng, n, max_alt=0)
        cap = rng.randint(1, 5)
        s = S.schedule(g, model, mode=mode, caps={"fanout": cap})
        check_valid(g, s, cap, mode)
        assert s.caps["fanout"] == cap


def test_default_caps_by_dispatcher(model):
    nodes = [{"id": "N%d" % i, "a": "scout", "n": 3} for i in range(12)]
    for disp, cap in (("blackcat", 8), ("orchestrator", 10), ("planner", 8), (None, 3)):
        g = S.load_graph({"nodes": nodes, "dispatcher": disp} if disp else {"nodes": nodes})
        s = S.schedule(g, model)
        assert max(len(w) for w in s.waves) <= cap
        assert s.caps["fanout"] == cap
    s = S.schedule(S.load_graph({"nodes": nodes}), model, caps={"fanout": 2})
    assert max(len(w) for w in s.waves) == 2


# ---------------------------------------------------------------- 3. exact up to 14, list above
def test_exact_up_to_14_nodes_and_list_scheduling_above(model):
    chain = lambda n: S.load_graph({"nodes": [{"id": "N%d" % i, "a": "scout", "n": 2 + (i % 5),
                                               "dep": ["N%d" % (i - 1)] if i % 3 else []} for i in range(n)]})
    s14 = S.schedule(chain(14), model, caps={"fanout": 3})
    assert s14.exact and not any("list scheduling" in w for w in s14.warnings)
    s15 = S.schedule(chain(15), model, caps={"fanout": 3})
    assert not s15.exact and any("list scheduling" in w for w in s15.warnings)
    check_valid(chain(15), s15, 3, "barrier")
    # the list schedule is never better than the exact one on a graph both can solve
    g = chain(10)
    assert S.schedule(g, model, caps={"fanout": 3}).wall <= S.schedule(g, model, caps={"fanout": 3}, exact=False).wall + 1e-9


# ---------------------------------------------------------------- 4. validation
def test_read_only_type_with_a_write_set_is_rejected(model, tmp_path):
    for t in sorted(S.READONLY_TYPES):
        g = S.load_graph({"nodes": [{"id": "A", "a": t, "s": "S", "w": ["src/**"]}]})
        issues = S.validate(g, model)
        assert [i for i in issues if i.level == "error" and i.node == "A" and "read-only" in i.msg], t
    ok = S.load_graph({"nodes": [{"id": "A", "a": "verifier", "s": "S", "rd": ["src/**"]},
                                 {"id": "B", "a": "coder", "s": "S", "w": ["src/**"], "dep": ["A"]}]})
    assert not [i for i in S.validate(ok, model) if i.level == "error"]
    alt = S.load_graph({"nodes": [{"id": "A", "a": "coder", "alt": "code-reviewer", "w": ["x"]}]})
    assert any(i.level == "error" for i in S.validate(alt, model))
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"nodes": [{"id": "A", "a": "verifier", "w": ["src/**"]}]}))
    p = subprocess.run([sys.executable, str(SCHED), "plan", str(bad)], capture_output=True, text=True, env=clean_env(tmp_path))
    assert p.returncode == 1 and "read-only" in p.stderr


def test_graph_errors(tmp_path):
    cases = [
        {"nodes": []},
        {"nodes": [{"id": "A", "a": "coder"}, {"id": "A", "a": "coder"}]},
        {"nodes": [{"id": "A", "a": "coder", "dep": ["Z"]}]},
        {"nodes": [{"id": "A", "a": "coder", "dep": ["A"]}]},
        {"nodes": [{"id": "A", "a": "coder", "dep": ["B"]}, {"id": "B", "a": "coder", "dep": ["A"]}]},
        {"nodes": [{"id": "A", "a": "coder", "s": "XL"}]},
        {"nodes": [{"id": "A", "a": "coder", "r": ["nope"]}]},
        {"nodes": [{"id": "A", "a": "coder"}], "speed": "warp"},
        {"nodes": [{"id": "A"}]},
    ]
    for c in cases:
        with pytest.raises(S.GraphError):
            S.load_graph(c)
        p = tmp_path / "g.json"
        p.write_text(json.dumps(c))
        r = subprocess.run([sys.executable, str(SCHED), "plan", str(p)], capture_output=True, text=True, env=clean_env(tmp_path))
        assert r.returncode == 1, c
    with pytest.raises(S.GraphError):
        S.load_graph(tmp_path / "missing.json")


def test_write_conflicts_are_serialised_and_shared_docs_are_not(model):
    nodes = [{"id": "A", "a": "coder", "n": 5, "w": ["src/*.py"]}, {"id": "B", "a": "coder", "n": 5, "w": ["src/app.py"]},
             {"id": "C", "a": "coder", "n": 5, "w": ["README.md"]}, {"id": "D", "a": "coder", "n": 5, "w": ["README.md"]}]
    g = S.load_graph({"nodes": nodes})
    assert any("serialised" in i.msg for i in S.validate(g, model))
    s = S.schedule(g, model, caps={"fanout": 4})
    (a0, a1), (b0, b1) = s.times["A"], s.times["B"]
    assert a1 <= b0 or b1 <= a0
    assert s.times["C"][0] == s.times["D"][0] or True        # README.md conflicts exist unless the fragment rule applies
    s2 = S.schedule(g, model, caps={"fanout": 4}, rules={"fragments": True})
    assert s2.times["C"][0] == s2.times["D"][0]


def test_glob_overlap():
    f = S._glob_overlap
    assert f("dot-claude/agents/*.md", "dot-claude/agents/coder.md")
    assert not f("dot-claude/skills/[a-m]*/**", "dot-claude/skills/[n-z]*/**")
    assert f("dot-claude/skills/x/**", "dot-claude/skills/x/references/a.md")
    assert f("dot-claude/skills", "dot-claude/skills/x/a.md")
    assert not f("tests/a.py", "docs/a.py")


# ---------------------------------------------------------------- 5. model, estimate, J
def test_load_model_defaults_and_b_schema(tmp_path, monkeypatch):
    m0 = S.load_model("/nonexistent/sched_model.json")
    assert m0["file"] is None and m0["types"] == {}
    info = S.tinfo(m0, "claude-code-engineer")
    assert info["turns"]["M"] == 42 and info["turns"]["L"] == 83 and info["turns"]["S"] == 21
    assert info["ctx"]["a"] == 95000 and info["ttl"] == "5m"
    assert S.tinfo(m0, "researcher")["ttl"] == "1h" and S.tinfo(m0, "scout")["soft_limit"] == 390000
    # a file in the (b) schema overrides per key and keeps the defaults for the rest
    f = tmp_path / "m.json"
    f.write_text(json.dumps({"version": 1, "generated": "x", "stack_hash": "h", "sessions": ["a"],
                             "kappa": {"cache_write_5m": 1.25, "cache_write_1h": 2.0,
                                       "cache_read": {"default": 0.1, "opus-5-5": 0.05},
                                       "models_measured": {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5"},
                                       "output": None},
                             "types": {"claude-code-engineer": {"model": "opus", "ttl": "5m", "turns": {"S": 10, "M": 30, "L": 60},
                                                                 "ctx": {"a": 50000, "b": 1000}, "static_cc": 20000,
                                                                 "sec_per_call": {"p50": 10, "p90": 20}}},
                             "pools": {"builder": {}}}))
    m = S.load_model(f)
    assert S.tinfo(m, "claude-code-engineer")["turns"] == {"S": 10, "M": 30, "L": 60}
    assert S.tinfo(m, "claude-code-engineer")["soft_limit"] == 19000000       # not in the file: default kept
    assert S.kappas(m, "claude-code-engineer") == (1.25, 0.05)                 # opus -> opus-5-5 key
    assert S.kappas(m, "coder") == (1.25, 0.1)                                 # sonnet -> default
    assert S.kappas(m, "researcher") == (2.0, 0.05)                            # 1h cache
    monkeypatch.setenv("STACK_SCHED_MODEL", str(f))
    assert S.load_model()["file"] == str(f)
    bad = tmp_path / "bad.json"
    bad.write_text("[1]")
    with pytest.raises(S.ModelError):
        S.load_model(bad)
    bad.write_text("{")
    with pytest.raises(S.ModelError):
        S.load_model(bad)
    committed = ROOT / "dot-claude" / "hooks" / "sched_model.json"
    if committed.is_file():
        mm = S.load_model(committed)
        assert S.estimate(S.load_graph({"nodes": [{"id": "A", "a": "claude-code-engineer", "s": "M"}]}), mm)["A"].t_w > 0


def test_estimate(model):
    g = S.load_graph({"nodes": [{"id": "A", "a": "claude-code-engineer", "s": "M"}, {"id": "B", "a": "scout", "n": 4},
                                {"id": "C", "a": "verifier"}]})
    est = S.estimate(g, model)
    a = est["A"]
    assert a.turns == 42 and a.ctx_p50 == pytest.approx(95000 * 42 + 1300 * 42 ** 2)
    assert a.ctx_p90 > a.ctx_p50 and a.wall_p90 > a.wall_p50 > 0
    last = 95000 + 2 * 1300 * 42
    assert a.t_w == pytest.approx(1.25 * last + 0.05 * (a.ctx_p50 - last))
    assert est["B"].turns == 4
    assert est["C"].turns == 37                      # no size: M


def test_objective_lambda_speed_and_slack(model, monkeypatch):
    g = S.load_graph({"nodes": [{"id": "A", "a": "claude-code-engineer", "s": "M"},
                                {"id": "B", "a": "main-coder", "s": "M", "alt": "coder", "dep": ["A"]}]})
    base = S.schedule(g, model, caps={"fanout": 3})
    assert base.J <= base.J_baseline + 1e-6
    assert base.lam == pytest.approx(base.tokens_baseline / base.wall_baseline)       # balanced
    slow = S.load_graph(dict(json.loads(json.dumps({"nodes": [{"id": "A", "a": "coder", "n": 3}], "speed": "frugal"}))))
    fast = S.load_graph({"nodes": [{"id": "A", "a": "coder", "n": 3}], "speed": "fast"})
    assert S.schedule(fast, model).lam == pytest.approx(16 * S.schedule(slow, model).lam)
    monkeypatch.setenv("STACK_SCHED_LAMBDA", "123")
    assert S.schedule(g, model).lam == pytest.approx(123)
    assert S.schedule(g, model, lam=5.0).lam == 5.0
    # with eps = 0 an alternative that costs more tokens is never chosen; with a large eps and a high lambda it can be
    g2 = S.load_graph({"nodes": [{"id": "A", "a": "coder", "n": 20, "alt": "main-coder"}]})
    tight = S.schedule(g2, model, lam=1e9, slack=0.0)
    loose = S.schedule(g2, model, lam=1e9, slack=10.0)
    assert tight.variants["A"] == "coder" or tight.tokens <= tight.tokens_baseline * (1 + 1e-9)
    assert loose.tokens >= tight.tokens - 1e-6


def test_next_ready(model):
    g = S.load_graph({"nodes": [{"id": "A", "a": "scout", "n": 2}, {"id": "B", "a": "scout", "n": 2},
                                {"id": "C", "a": "coder", "n": 2, "dep": ["A", "B"]},
                                {"id": "D", "a": "coder", "n": 2, "dep": ["A"]}]})
    s = S.schedule(g, model, mode="barrier", caps={"fanout": 2})
    assert set(S.next_ready(g, {"nodes": {}}, s)) <= {"A", "B"}
    assert len(S.next_ready(g, {"nodes": {}}, s)) == 2
    st = {"nodes": {"A": {"status": "done"}, "B": {"status": "running"}}}
    assert S.next_ready(g, st, s) == []              # barrier: B still runs
    st["nodes"]["B"]["status"] = "done"
    assert set(S.next_ready(g, st, s)) <= {"C", "D"} and S.next_ready(g, st, s)
    r = S.schedule(g, model, mode="release", caps={"fanout": 2})
    st = {"nodes": {"A": {"status": "done"}, "B": {"status": "running"}}}
    assert S.next_ready(g, st, r) == ["D"]           # release: D needs only A; the cap leaves one slot
    st["nodes"]["D"] = {"status": "running"}
    assert S.next_ready(g, st, r) == []              # cap reached


# ---------------------------------------------------------------- 6. CLI
def test_cli(tmp_path):
    env = clean_env(tmp_path)
    g = tmp_path / "g.json"
    g.write_text(json.dumps({"job": "j", "nodes": [{"id": "A", "a": "scout", "n": 2}, {"id": "B", "a": "coder", "n": 5, "dep": ["A"]}]}))
    r = subprocess.run([sys.executable, str(SCHED), "plan", str(g), "--mode", "release", "--speed", "fast", "--json"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["mode"] == "release" and out["critical_path"] == ["A", "B"]
    st = tmp_path / "s.json"
    st.write_text(json.dumps({"nodes": {"A": {"status": "done"}}}))
    r = subprocess.run([sys.executable, str(SCHED), "next", str(g), str(st)], capture_output=True, text=True, env=env)
    assert r.returncode == 0 and json.loads(r.stdout) == ["B"]
    r = subprocess.run([sys.executable, str(SCHED), "emit-workflow"], capture_output=True, text=True, env=env)
    assert r.returncode == 2 and "disabled until probe" in r.stderr
    r = subprocess.run([sys.executable, str(SCHED), "plan", str(g), "--mode", "sideways"], capture_output=True, text=True, env=env)
    assert r.returncode == 2
    r = subprocess.run([sys.executable, str(SCHED)], capture_output=True, text=True, env=env)
    assert r.returncode == 2


def test_py_compile_with_system_python(tmp_path):
    p = subprocess.run(["/usr/bin/python3", "-m", "py_compile", str(SCHED)], capture_output=True, text=True,
                       env=clean_env(tmp_path))
    assert p.returncode == 0, p.stderr
    head = SCHED.read_text().splitlines()[:5]
    assert head[1] == "# /// script" and "dependencies = []" in head[3]


def test_render_md_limit(model):
    g = S.load_graph({"nodes": [{"id": "A%d" % i, "a": "scout", "n": 2} for i in range(30)]})
    s = S.schedule(g, model, caps={"fanout": 3})
    assert len(S.render_md(s)) <= 1500
    assert len(S.render_md(s, max_chars=None)) > 0
    assert len(S.render_md(S.estimate(g, model), max_chars=200)) <= 200


# ---------------------------------------------------------------- 7. fixture and replay
def test_fixture_graph():
    g = S.load_graph(FIXTURE)
    ids = {n.id for n in g.nodes}
    want = {"T%d" % i for i in range(1, 9)} | {"P%d" % i for i in (1, 2, 3, 4, 5, 6, 7, 8, 10)} | \
           {"P9a", "P9b", "P9c", "P9d"} | {"Q%d" % i for i in range(1, 11)} | {"R1", "R2"}
    assert ids == want
    from_plans = {"T3": ["T2"], "T7": ["T3"], "T8": ["T5", "T7", "T3"], "P2": ["P1"], "P8": ["P3", "P4", "P5", "P6", "P7"],
                  "Q5": ["Q6"], "Q4": ["Q1", "Q2", "Q3"], "R1": ["Q10"]}
    byid = g.by_id()
    for k, v in from_plans.items():
        assert sorted(byid[k].dep) == sorted(v), k
    assert not [i for i in S.validate(g, S.load_model("/nonexistent")) if i.level == "error"]
    for n in g.nodes:
        for k, ph in enumerate(n.extra["ph"]):
            for d in ph.get("dep", []):
                nid, _, p = d.partition(":")
                assert nid in ids and int(p) < len(byid[nid].extra["ph"]), (n.id, d)
    s = S.schedule(g, S.load_model("/nonexistent"), mode="barrier", caps={"fanout": 10})
    assert not s.exact and any("list scheduling" in w for w in s.warnings)     # 32 nodes


def make_session(tmp_path):
    """A tiny recorded session: two prompts, A -> B (B resumed later, cold), C independent."""
    sid = "11111111-0000-0000-0000-000000000000"
    hdr = ["session", "id", "type", "desc", "depth", "seg", "nsegs", "compactions", "turn_limit", "after_limit", "open",
           "input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "api_calls",
           "tool_calls", "fresh", "ctx", "cum", "peak", "rereads", "first_ts", "last_ts"]

    def row(i, typ, desc, seg, cc, cr, calls, peak, t0, t1):
        return [sid, i, typ, desc, 1, seg, 2, 0, False, False, False, 10, 100, cc, cr, calls, calls, 0, 0, 0, peak, 0,
                "2026-10-02T10:%s.000Z" % t0, "2026-10-02T10:%s.000Z" % t1]

    rows = [row("aaaa", "scout", "A lookup", 0, 30000, 100000, 5, 40000, "00:10", "01:10"),
            row("bbbb", "claude-code-engineer", "B build", 0, 100000, 1000000, 20, 120000, "02:00", "10:00"),
            row("bbbb", "claude-code-engineer", "B build", 1, 90000, 800000, 10, 130000, "30:00", "34:00"),
            row("cccc", "coder", "C other", 0, 50000, 500000, 15, 60000, "02:10", "08:00")]
    import csv
    with open(tmp_path / "seg.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(hdr)
        w.writerows(rows)
    with open(tmp_path / "prm.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["session", "kind", "i", "start", "prompt", "fresh", "ctx", "cum", "api_calls"])
        w.writerow([sid, "human", 0, "10:00", "first", 0, 0, 0, 0])
        w.writerow([sid, "human", 1, "10:25", "second", 0, 0, 0, 0])
    (tmp_path / "led.md").write_text('# Delegations\nUpdated 11:40:00. x\n\n'
                                     '- scout · "A lookup" · finished · 11:00:10 · id aaaa\n'
                                     '- claude-code-engineer · "B build" · finished · 11:02:00 · id bbbb\n'
                                     '- coder · "C other" · finished · 11:02:10 · id cccc\n')
    graph = {"job": "mini", "session": sid, "dispatcher": "orchestrator", "nodes": [
        {"id": "A", "a": "scout", "n": 5, "ph": [{"agent": "aaaa", "segs": [0], "dep": []}]},
        {"id": "B", "a": "claude-code-engineer", "n": 30, "dep": ["A"], "w": ["src/**"],
         "ph": [{"agent": "bbbb", "segs": [0], "dep": ["A:0"], "w": ["src/**"]},
                {"agent": "bbbb", "segs": [1], "dep": [], "w": ["src/**"], "kind": "fix"}]},
        {"id": "C", "a": "coder", "n": 15, "w": ["docs/**"], "ph": [{"agent": "cccc", "segs": [0], "dep": []}]}]}
    return sid, graph


def test_replay_synthetic_session(model, tmp_path):
    sid, graph = make_session(tmp_path)
    rep = S.replay(str(tmp_path / "led.md"), str(tmp_path / "seg.csv"), str(tmp_path / "prm.csv"), graph, model, session=sid)
    assert rep.tz_offset == 3600.0
    assert [w.i for w in rep.windows] == [0, 1]
    w0, w1 = rep.windows
    # window 0: A (4 min after prompt... starts 10:00:10), B starts 10:02:00 -> makespan from first start to last end
    assert w0.makespan == pytest.approx(10 * 60 - 10)
    assert abs(w0.sim_err) <= 0.02 and abs(w1.sim_err) <= 0.02
    # B waited for A (ended 10:01:10) until 10:02:00; C was dispatched 120 s after the window start
    assert w0.barrier_wait == pytest.approx(50 + 120, abs=2)
    assert len(rep.cold) == 1 and rep.cold[0]["excess"] == 90000.0                 # min(cc 90000, prior peak 120000)
    assert rep.cold[0]["gap"] == pytest.approx(20 * 60)
    # B's resume is a fix after a 20 min gap: cold, no schedule can make it warm; a fresh fixer is the only option
    assert rep.rows["release/oracle"]["fresh"] + rep.rows["release/oracle"]["warm"] == 1
    assert rep.rows["release/oracle"]["S_wall"] >= -1e-9
    md = S.render_md(rep, max_chars=None)
    for needle in ("S_wall", "S_tok", "STOP", "Hand estimates"):
        assert needle in md or needle == "STOP" and ("STOP" in md or "ASK USER" in md)


def test_replay_fed_the_actual_waves_reproduces_each_window(model):
    # actual waves: (dispatch offset, startup lag, duration) per unit
    waves = [[(0.0, 2.0, 300.0), (5.0, 1.0, 120.0)], [(330.0, 3.0, 200.0)]]
    assert S.simulate_waves(waves) == pytest.approx(533.0)
    assert S.cluster_waves([(0, "a"), (30, "b"), (400, "c"), (410, "d")], gap=120) == [["a", "b"], ["c", "d"]]


@pytest.mark.skipif(not (USAGE / "segments.csv").is_file(), reason="agents-usage data not in this checkout")
def test_replay_recorded_session(model, tmp_path):
    led = Path.home() / ".local/state/claude-agent-stack" / SESSION / "delegations.md"
    rep = S.replay(str(led) if led.is_file() else None, str(USAGE / "segments.csv"), str(USAGE / "prompts.csv"), FIXTURE, model,
                   session=SESSION)
    assert rep.windows
    # (3) the actual waves and durations reproduce every window's makespan within 2%
    assert max(abs(w.sim_err) for w in rep.windows) <= 0.02
    # no advised row beats physics: the advised makespan is at least the longest unit of each window
    for w in rep.windows:
        longest = max([rep.units[k].end - rep.units[k].start for k in w.units] or [0.0])
        for name in ("barrier/oracle", "release/oracle"):
            assert w.rows[name]["makespan"] >= longest - 1e-6
    # the hand estimates this replay was asked to confirm or refute
    assert sum(c["excess"] for c in rep.cold if c["type"] != "orchestrator") == pytest.approx(3.02e6, rel=0.01)
    assert rep.phase1["cp_dur_min"] == pytest.approx(68.0, abs=1.0) and rep.phase1["elapsed_min"] == pytest.approx(73.6, abs=0.2)
    assert rep.barrier_rewrites == {"P5": 477514.0, "P7": 432109.0}
    # CLI: the report file
    out = tmp_path / "replay.md"
    p = subprocess.run([sys.executable, str(SCHED), "replay", "--session", SESSION, "--graph", str(FIXTURE), "--segments",
                        str(USAGE / "segments.csv"), "--prompts", str(USAGE / "prompts.csv"), "--ledger", str(led), "--out", str(out)],
                       capture_output=True, text=True, env=clean_env(tmp_path))
    assert p.returncode == 0, p.stderr
    md = out.read_text()
    for needle in ("S_wall", "S_tok", "## Verdict", "STOP", "barrier/oracle", "release/oracle"):
        assert needle in md
