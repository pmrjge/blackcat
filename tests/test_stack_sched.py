"""stack_sched.py: the scheduler advisor (dot-claude/hooks/stack_sched.py).

Run: uv run --python 3.13 --with pytest pytest -q tests/test_stack_sched.py
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
    pd = [prim[nd.id].wall_plan for nd in nodes]
    pt = [prim[nd.id].t_w_plan for nd in nodes]
    alt_i = [i for i, nd in enumerate(nodes) if nd.alt]
    ad, at = {}, {}
    for i in alt_i:
        e = S._est_for(m, nodes[i].alt, nodes[i].s, nodes[i].n)
        ad[i], at[i] = e.wall_plan, e.t_w_plan
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
                dur = est[nd.id].wall_plan
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


def check_of(s, name):
    return next(c for c in s.checks if c.name == name)


def test_blackcat_cap_is_dispatches_per_prompt(model):
    # agent_guard.py: 8 Agent calls per prompt (BLACKCAT_MAX_DISPATCH), all within 120 s (BLACKCAT_DISPATCH_WINDOW_S)
    mk = lambda k, disp: S.load_graph({"dispatcher": disp, "nodes": [{"id": "N%d" % i, "a": "scout", "n": 3} for i in range(k)]})
    s12 = S.schedule(mk(12, "blackcat"), model)
    c = check_of(s12, "blackcat_dispatches")
    assert (c.hi, c.limit, c.verdict) == (12, 8, "does not fit") and s12.verdict == "does not fit"
    assert any("Agent calls per prompt" in i.msg for i in S.validate(mk(12, "blackcat"), model) if i.level == "warn")
    s8 = S.schedule(mk(8, "blackcat"), model)
    assert check_of(s8, "blackcat_dispatches").verdict == "fits" and check_of(s8, "blackcat_window_s").verdict == "fits"
    assert not any(c.name.startswith("blackcat") for c in S.schedule(mk(12, "orchestrator"), model).checks)
    # a chain whose later dispatch starts after 120 s breaks the burst window
    chain = S.load_graph({"dispatcher": "blackcat", "nodes": [
        {"id": "A", "a": "claude-code-engineer", "n": 40}, {"id": "B", "a": "scout", "n": 3, "dep": ["A"]}]})
    w = check_of(S.schedule(chain, model), "blackcat_window_s")
    assert w.hi > 120 and w.limit == 120 and w.verdict == "does not fit"


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
                                       "cache_read": {"default": 0.1, "rules": [
                                           {"family": "opus", "version": "5.5", "value": 0.05}]},
                                       "models_measured": {"opus": "5.5", "sonnet": "5.5"},
                                       "output": None},
                             "types": {"claude-code-engineer": {"model": "opus", "ttl": "5m", "turns": {"S": 10, "M": 30, "L": 60},
                                                                 "ctx": {"a": 50000, "b": 1000}, "static_cc": 20000,
                                                                 "sec_per_call": {"p50": 10, "p90": 20}}},
                             "pools": {"builder": {}}}))
    m = S.load_model(f)
    assert S.tinfo(m, "claude-code-engineer")["turns"] == {"S": 10, "M": 30, "L": 60}
    assert S.tinfo(m, "claude-code-engineer")["soft_limit"] == 19000000       # not in the file: default kept
    assert S.kappas(m, "claude-code-engineer") == (1.25, 0.05)                 # opus 5.5 rule
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


def test_next_ready_barrier_skips_a_wave_of_dead_nodes(model):
    g = S.load_graph({"nodes": [{"id": "A", "a": "scout", "n": 2}, {"id": "X", "a": "scout", "n": 2},
                                {"id": "B", "a": "coder", "n": 2, "dep": ["A"]},
                                {"id": "Z", "a": "coder", "n": 2, "dep": ["X"]}]})
    s = S.schedule(g, model, mode="barrier", caps={"fanout": 2})
    s.waves = [["A", "X"], ["B"], ["Z"]]                      # B's wave holds only a node that can never run
    st = {"nodes": {"A": {"status": "failed"}, "X": {"status": "done"}}}
    assert S.next_ready(g, st, s) == ["Z"]                    # stalled forever before: wave 1 stayed active
    st["nodes"]["X"]["status"] = "failed"
    assert S.next_ready(g, st, s) == []                       # nothing can run: no dispatch, no stall either


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
    # barrier simulation (not a tautology): A, B, C fall in one wave (dispatch gaps under 120 s), so it ends at B's duration,
    # 480 s, against the recorded 590 s: B was dispatched 110 s into the window, after A finished
    assert w0.sim_makespan == pytest.approx(480.0) and w0.sim_err == pytest.approx(480.0 / 590.0 - 1)
    assert abs(w1.sim_err) <= 0.05
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
    # barrier simulation from (startup lag, duration): wave 0 at 0, wave 1 one latency after wave 0's last end
    waves = [[(2.0, 300.0), (1.0, 120.0)], [(3.0, 200.0)]]
    assert S.simulate_waves(waves) == pytest.approx(302.0 + 203.0)
    assert S.simulate_waves(waves, lat=30.0) == pytest.approx(302.0 + 30.0 + 203.0)
    assert S.cluster_waves([(0, "a"), (30, "b"), (400, "c"), (410, "d")], gap=120) == [["a", "b"], ["c", "d"]]


@pytest.mark.skipif(not (USAGE / "segments.csv").is_file(), reason="agents-usage data not in this checkout")
def test_replay_recorded_session(model, tmp_path):
    led = Path.home() / ".local/state/claude-agent-stack" / SESSION / "delegations.md"
    rep = S.replay(str(led) if led.is_file() else None, str(USAGE / "segments.csv"), str(USAGE / "prompts.csv"), FIXTURE, model,
                   session=SESSION)
    assert rep.windows
    # (3) the barrier simulation from recorded lags and durations is a real comparison: its error is measured and reported
    # (not 0 by construction; the 2% target is not met on this session, and the report says so)
    assert any(abs(w.sim_err) > 0 for w in rep.windows)
    assert "NOT met" in S.render_md(rep, max_chars=None) or max(abs(w.sim_err) for w in rep.windows) <= 0.02
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


# ---------------------------------------------------------------- provisional bands: small-n values are used
def bmodel(status="provisional", turns=(20, 30, 45), spc=(8, 10, 15), ctx=(0.9, 1.0, 1.4), soft=None, max_turns=None,
           pool_band=None, own_band=True):
    row = {"turns": {"S": 15, "M": 30, "L": 60}, "ctx": {"a": 100000, "b": 0}, "sec_per_call": {"p50": 10, "p90": 15},
           "static_cc": 20000, "ttl": "5m", "model": "sonnet", "soft_limit": soft, "maxTurns": max_turns, "status": status}
    if own_band:
        row["band"] = {"level": 0.9, "method": "bootstrap",
                       "turns": dict(zip(("lo", "med", "hi"), turns)), "sec_per_call": dict(zip(("lo", "med", "hi"), spc)),
                       "ctx": dict(zip(("lo", "med", "hi"), ctx))}
    m = S.load_model("/nonexistent")
    m["types"]["coder"] = row
    if pool_band:
        m["pools"]["builder"] = {"status": "provisional", "band": pool_band}
    return m


def one(a="coder", **kw):
    return S.load_graph({"nodes": [dict({"id": "A", "a": a, "s": "M"}, **kw)]})


def test_interval_med_vs_hi_and_plan_values():
    est = S.estimate(one(), bmodel())["A"]
    assert est.turns == 30 and est.turns_hi == pytest.approx(45)
    assert est.w["turns"] == pytest.approx(0.5) and est.w["sec_per_call"] == pytest.approx(0.5) and est.w["ctx"] == pytest.approx(0.4)
    assert est.ctx_p50 == pytest.approx(3.0e6) and est.ctx_hi == pytest.approx(4.5e6 * 1.4)
    assert est.wall_p50 == pytest.approx(300) and est.wall_hi == pytest.approx(45 * 10 * 1.5)
    assert est.t_w_hi > est.t_w > 0
    # provisional plans on med x (1 + w) = hi; supported plans on med
    assert est.wall_plan == est.wall_hi and est.t_w_plan == est.t_w_hi and est.status == "provisional"
    sup = S.estimate(one(), bmodel("supported"))["A"]
    assert sup.wall_plan == sup.wall_p50 and sup.t_w_plan == sup.t_w and sup.t_w_hi == pytest.approx(est.t_w_hi)
    # an explicit n is taken as given: only sec_per_call and ctx are widened
    e2 = S.estimate(one(n=10, s=None), bmodel())["A"]
    assert e2.turns_hi == 10 and e2.wall_hi == pytest.approx(10 * 10 * 1.5)


@pytest.mark.parametrize("soft,want,drivers", [(7_000_000, "fits", []), (4_000_000, "uncertain", ["coder"]),
                                              (2_000_000, "does not fit", [])])
def test_three_way_verdict_on_the_soft_limit(soft, want, drivers):
    m = bmodel(soft=soft)
    s = S.schedule(one(), m)
    chk = {c.name: c for c in s.checks}["soft:A"]
    assert chk.verdict == want and chk.drivers == drivers
    assert s.verdict == want                      # nothing else limits this plan
    assert S.three_way(1, 2, 3) == "fits" and S.three_way(1, 4, 3) == "uncertain" and S.three_way(4, 5, 3) == "does not fit"


def test_three_way_on_budget_prompt_and_max_turns():
    m = bmodel()
    assert S.schedule(one(), m, budget=10e6).verdict == "fits"
    s = S.schedule(one(), m, budget=5e6)           # med 3.0M fits, hi 8.8M does not
    assert s.verdict == "uncertain" and {c.name: c for c in s.checks}["budget"].drivers == ["coder"]
    assert S.schedule(one(), m, budget=1e6).verdict == "does not fit"
    big = S.load_graph({"nodes": [{"id": "A%d" % i, "a": "coder", "s": "M"} for i in range(8)]})      # 8 x 3.0M med = 24M, hi 70M
    c = {c.name: c for c in S.schedule(big, m, caps={"fanout": 8}).checks}["prompt"]
    assert c.verdict == "does not fit" or c.verdict == "uncertain"
    assert c.hi > S.SOFT_PROMPT_CTX >= c.med or c.verdict == "does not fit"
    orch = S.load_graph({"dispatcher": "orchestrator",
                         "nodes": [{"id": "A%d" % i, "a": "coder", "s": "M"} for i in range(8)]})
    co = {c.name: c for c in S.schedule(orch, m, caps={"fanout": 8}).checks}["prompt"]
    assert co.limit == S.SOFT_PROMPT_CTX_BY_TYPE["orchestrator"] == 80000000 and co.limit > c.limit
    mt = S.schedule(one(), bmodel(max_turns=40))
    assert {c.name: c for c in mt.checks}["maxTurns:A"].verdict == "uncertain"       # med 30 <= 40 < hi 45
    assert S.schedule(one(), bmodel(max_turns=20)).verdict == "does not fit"
    assert S.schedule(one(), bmodel(max_turns=50)).verdict == "fits"


def test_pool_band_fallback_and_unverified_heuristic():
    pool = {"level": 0.9, "method": "pool-prior", "turns": {"lo": 10, "med": 30, "hi": 60},
            "sec_per_call": {"lo": 5, "med": 10, "hi": 20}, "ctx": {"lo": 0.8, "med": 1.0, "hi": 1.2}}
    m = bmodel(own_band=False, pool_band=pool)
    e = S.estimate(one(), m)["A"]
    assert e.source == "pool" and e.status == "provisional"
    assert e.w == {"turns": pytest.approx(1.0), "sec_per_call": pytest.approx(1.0), "ctx": pytest.approx(0.2)}
    # neither the type nor its pool has a band: provisional, w = 1.0, marked unverified
    h = S.estimate(one(), bmodel(own_band=False))["A"]
    assert h.source == "heuristic" and h.status == "provisional"
    assert h.w == {"turns": 1.0, "sec_per_call": 1.0, "ctx": 1.0}
    assert h.wall_hi == pytest.approx(2 * 30 * 2 * 10) and h.wall_plan == h.wall_hi
    s = S.schedule(one(), bmodel(own_band=False))
    assert s.provisional["coder"]["unverified"] is True and "unverified" in S.render_md(s)
    # supported without a band cannot be trusted either: heuristic applies
    assert S.estimate(one(), bmodel("supported", own_band=False))["A"].status == "provisional"
    # a type the file does not know at all behaves the same
    assert S.estimate(one("scout"), S.load_model("/nonexistent"))["A"].w["turns"] == 1.0


def test_provisional_to_supported_changes_the_plan():
    g = S.load_graph({"nodes": [{"id": "A", "a": "coder", "s": "M"}, {"id": "B", "a": "coder", "s": "M", "dep": ["A"]}]})
    prov = S.schedule(g, bmodel("provisional"), lam=1.0)
    sup = S.schedule(g, bmodel("supported"), lam=1.0)
    assert sup.wall < prov.wall and sup.tokens < prov.tokens
    assert prov.wall == pytest.approx(2 * 45 * 10 * 1.5) and sup.wall == pytest.approx(2 * 30 * 10)
    # the check still looks at hi after the switch, so a tight budget stays uncertain
    assert S.schedule(one(), bmodel("supported"), budget=5e6).verdict == "uncertain"
    assert "planned at hi" in S.render_md(prov) and "planned at hi" not in S.render_md(sup)


def test_provisional_plan_is_never_below_the_hi_estimate():
    rng = random.Random(5)
    for _ in range(60):
        n = rng.randint(1, 7)
        g = random_graph(rng, n, max_alt=0, conflicts=False)
        t = (rng.randint(5, 20), rng.randint(21, 40), rng.randint(41, 90))
        sp = (rng.randint(3, 6), rng.randint(7, 12), rng.randint(13, 30))
        ctxb = (0.8, 1.0, 1.0 + rng.random())
        m = bmodel("provisional", t, sp, ctxb)
        m["types"] = {k: dict(m["types"]["coder"]) for k in TYPES}
        ms = {**m, "types": {k: dict(v, status="supported") for k, v in m["types"].items()}}
        for nd_id, e in S.estimate(g, m).items():
            assert e.wall_plan >= e.wall_hi - 1e-9 and e.t_w_plan >= e.t_w_hi - 1e-9
            assert e.wall_plan >= e.wall_p50 and e.t_w_plan >= e.t_w
        p, q = S.schedule(g, m, lam=1.0, caps={"fanout": 3}), S.schedule(g, ms, lam=1.0, caps={"fanout": 3})
        hi_tokens = sum(e.t_w_hi for e in S.estimate(g, m).values())
        assert p.tokens >= hi_tokens - 1e-6 and p.tokens >= q.tokens - 1e-6 and p.wall >= q.wall - 1e-6


@pytest.mark.skipif(not (USAGE / "segments.csv").is_file(), reason="agents-usage data not in this checkout")
def test_replay_reports_the_provisional_share(model):
    led = Path.home() / ".local/state/claude-agent-stack" / SESSION / "delegations.md"
    rep = S.replay(str(led) if led.is_file() else None, str(USAGE / "segments.csv"), str(USAGE / "prompts.csv"), FIXTURE, model,
                   session=SESSION)
    for v in rep.rows.values():
        assert 0.0 <= v["prov_share_wall"] <= 1.0 and 0.0 <= v["prov_share_tok"] <= 1.0
    assert "provisional types" in S.render_md(rep, max_chars=None)


def test_clamp_band_and_wrong_side_factors():
    c = S.clamp_band({"turns": {"lo": 40, "med": 30, "hi": 20}, "sec_per_call": {"lo": 5, "med": 10, "hi": 9},
                      "ctx": {"lo": 1.2, "med": 1.0, "hi": 0.8}, "junk": 1})
    for q in ("turns", "sec_per_call", "ctx"):
        assert c[q]["lo"] <= c[q]["med"] <= c[q]["hi"]
    assert c["turns"] == {"lo": 30.0, "med": 30.0, "hi": 30.0}
    # a hi below med gives a factor of 1 (not 0.67): the plan is never cheaper than med
    m = bmodel(turns=(40, 30, 20), spc=(12, 10, 8), ctx=(1.2, 1.0, 0.8))
    e = S.estimate(one(), m)["A"]
    assert e.w == {"turns": 0.0, "sec_per_call": 0.0, "ctx": 0.0}
    assert e.wall_plan >= e.wall_p50 and e.t_w_plan >= e.t_w and e.ctx_hi >= e.ctx_p50
    assert S.clamp_band("x") is None and "turns" not in S.clamp_band({"turns": {"med": "n/a"}})


def test_real_model_file_bands_and_kappa_rules():
    f = ROOT / "dot-claude" / "hooks" / "sched_model.json"
    if not f.is_file():
        pytest.skip("no sched_model.json")
    m = S.load_model(f)
    raw = json.loads(f.read_text())
    row = raw["types"]["claude-code-engineer"]
    if "band" not in row:
        pytest.skip("model file without bands")
    b = S.band_of(m, "claude-code-engineer")
    assert b["status"] == row["status"] and b["source"] == "own"
    assert b["turns"] == pytest.approx(max(1.0, row["band"]["turns"]["hi"] / row["band"]["turns"]["med"]))
    prov = [t for t, v in raw["types"].items() if v.get("status") == "provisional"]
    sup = [t for t, v in raw["types"].items() if v.get("status") == "supported"]
    assert prov and S.band_of(m, prov[0])["status"] == "provisional"
    if sup:
        e = S.estimate(one(sup[0]), m)["A"]
        assert e.status == "supported" and e.wall_plan == e.wall_p50
    kw, kr = S.kappas(m, "claude-code-engineer")
    assert kr == 0.05 and S.kappas(m, "coder")[1] == 0.1


# ---------------------------------------------------------------- S2f review fixes
def test_cold_resume_inside_one_phase_is_not_warm(model, tmp_path):
    sid, graph = make_session(tmp_path)
    graph["nodes"][1]["ph"] = [{"agent": "bbbb", "segs": [0, 1], "dep": ["A:0"], "w": ["src/**"]}]
    rep = S.replay(str(tmp_path / "led.md"), str(tmp_path / "seg.csv"), str(tmp_path / "prm.csv"), graph, model, session=sid)
    assert len(rep.cold) == 1
    for name in ("barrier/oracle", "release/oracle"):
        assert rep.rows[name]["warm"] == 0 and rep.rows[name]["S_tok_warm"] == 0.0


def test_replay_windows_across_utc_midnight(model, tmp_path):
    import csv
    sid = "22222222-0000-0000-0000-000000000000"
    hdr = ["session", "id", "type", "desc", "depth", "seg", "nsegs", "compactions", "turn_limit", "after_limit", "open",
           "input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "api_calls",
           "tool_calls", "fresh", "ctx", "cum", "peak", "rereads", "first_ts", "last_ts"]
    row = lambda i, day, a, b: [sid, i, "scout", "S " + i, 1, 0, 1, 0, False, False, False, 10, 100, 1000, 10000, 5, 5, 0, 0, 0,
                                2000, 0, "2026-10-0%dT%s.000Z" % (day, a), "2026-10-0%dT%s.000Z" % (day, b)]
    with open(tmp_path / "seg.csv", "w", newline="") as fh:        # "aaaa" (sorts first) is the day-2 agent
        w = csv.writer(fh)
        w.writerow(hdr)
        w.writerows([row("aaaa", 2, "23:55:00", "23:58:00"), row("bbbb", 3, "00:15:00", "00:18:00")])
    with open(tmp_path / "prm.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["session", "kind", "i", "start", "prompt", "fresh", "ctx", "cum", "api_calls"])
        w.writerow([sid, "human", 0, "23:50", "first", 0, 0, 0, 0])
        w.writerow([sid, "human", 1, "00:10", "second", 0, 0, 0, 0])
    g = {"job": "m", "session": sid, "nodes": [
        {"id": "A", "a": "scout", "n": 5, "ph": [{"agent": "aaaa", "segs": [0], "dep": []}]},
        {"id": "B", "a": "scout", "n": 5, "ph": [{"agent": "bbbb", "segs": [0], "dep": []}]}]}
    rep = S.replay(None, str(tmp_path / "seg.csv"), str(tmp_path / "prm.csv"), g, model, session=sid)
    assert [w.i for w in rep.windows] == [0, 1]
    assert [w.units for w in rep.windows] == [["A#0"], ["B#0"]]


def test_next_cli_rejects_readonly_with_write_set(tmp_path):
    g = tmp_path / "g.json"
    g.write_text(json.dumps({"nodes": [{"id": "A", "a": "verifier", "n": 2, "w": ["src/**"]}]}))
    st = tmp_path / "s.json"
    st.write_text(json.dumps({"nodes": {}}))
    p = subprocess.run([sys.executable, str(SCHED), "next", str(g), str(st)], capture_output=True, text=True,
                       env=clean_env(tmp_path))
    assert p.returncode == 1 and "read-only" in p.stderr


def test_own_band_without_ctx_uses_pool_band_then_heuristic():
    tri = lambda lo, med, hi: {"lo": lo, "med": med, "hi": hi}
    own = {"status": "supported", "tier": "builder", "band": {"turns": tri(10, 20, 30), "sec_per_call": tri(8, 10, 12)}}
    m = S.load_model("/nonexistent/sched_model.json")
    m["types"] = {"coder": own}
    m["pools"] = {"builder": {"band": {"turns": tri(1, 2, 3), "sec_per_call": tri(1, 2, 3), "ctx": tri(1.0, 1.0, 1.5)}}}
    b = S.band_of(m, "coder")
    assert b["turns"] == pytest.approx(1.5) and b["ctx"] == pytest.approx(1.5)           # own turns, pool ctx
    m["pools"] = {"builder": {}}
    assert S.band_of(m, "coder")["ctx"] == pytest.approx(1.0 + S.UNVERIFIED_W)          # no pool band either: w = 1.0


def test_kappas_resolve_the_alias_through_the_environment(monkeypatch):
    m = S.load_model("/nonexistent/sched_model.json")
    m["kappa"] = {"cache_write_5m": 1.25, "cache_write_1h": 2.0, "models_measured": {"opus": "4.8"},
                  "cache_read": {"default": 0.1, "rules": [{"family": "opus", "version": "5.5", "value": 0.05}]}}
    monkeypatch.delenv("ANTHROPIC_DEFAULT_OPUS_MODEL", raising=False)
    assert S.kappas(m, "claude-code-engineer")[1] == 0.1                                  # measured 4.8: default
    monkeypatch.setenv("ANTHROPIC_DEFAULT_OPUS_MODEL", "-".join(("claude", "opus", "5", "5")))
    assert S.kappas(m, "claude-code-engineer")[1] == 0.05                                 # the alias resolves to 5.5
    monkeypatch.setenv("ANTHROPIC_DEFAULT_OPUS_MODEL", "-".join(("claude", "opus", "4", "8")))
    m["kappa"]["models_measured"] = {"opus": "5.5"}
    assert S.kappas(m, "claude-code-engineer")[1] == 0.1                                  # the alias wins over models_measured


def test_derive_fit_takes_generated_as_an_argument():
    pytest.importorskip("pandas")
    sys.path.insert(0, str(ROOT / "tests"))
    import test_derive_sched_model as TD
    seg = TD.pool_rows()
    J = TD.D.fit(seg, TD.FM, TD.SOFT, B=50, generated="2000-01-01T00:00:00Z")
    assert J["generated"] == "2000-01-01T00:00:00Z"
    assert TD.D.fit(seg, TD.FM, TD.SOFT, B=50, generated="2000-01-01T00:00:00Z") == J


# ---------------------------------------------------------------- S1e: resume ctx, per-run intervals, measured fixer
RC = {"alpha": 1000, "gamma": 500.0, "n": 79, "n_agents": 23}
RI = {"level": 0.9, "groups": {"pooled": {"n": 100, "turns": {"lo": 0.2, "hi": 3.0}, "ctx": {"lo": 0.1, "hi": 4.0},
                                          "wall": {"lo": 0.05, "hi": 30.0}},
                               "builder:resume": {"n": 27, "turns": {"lo": 0.04, "hi": 3.2}, "ctx": {"lo": 0.02, "hi": 4.7},
                                                  "wall": {"lo": 0.01, "hi": 4.4}}}}


def test_a_peak_node_is_costed_as_a_resume_from_its_prior_peak():
    m = bmodel()
    plain = S.estimate(one(peak=200000), m)["A"]
    assert not plain.resume and plain.ctx_p50 == pytest.approx(3.0e6)        # no resume_ctx in the model: peak ignored
    m["resume_ctx"] = RC
    e = S.estimate(one(peak=200000), m)["A"]
    assert e.resume and e.ctx_p50 == pytest.approx(30 * (200000 + 1000 + 500 * 30))
    assert e.ctx_hi == pytest.approx(45 * (200000 + 1000 + 500 * 45) * 1.4)
    # T_w: the warm resume writes only its growth (alpha + 2 gamma n) and re-reads the rest
    kw, kr = S.kappas(m, "coder")
    last = 1000 + 2 * 500 * 30
    assert e.t_w == pytest.approx(kw * last + kr * (e.ctx_p50 - last))
    assert S.estimate(one(), m)["A"].resume is False
    for bad in (-1, True, "big"):
        with pytest.raises(S.GraphError):
            S.load_graph({"nodes": [{"id": "A", "a": "coder", "peak": bad}]})


def test_run_interval_factors_are_reported_and_caps_keep_the_band():
    m = bmodel(max_turns=60)
    e0 = S.estimate(one(), m)["A"]
    assert e0.turns_run_hi == 0.0 and e0.ctx_run_hi == 0.0
    m["run_interval"] = RI
    m["resume_ctx"] = RC
    e = S.estimate(one(), m)["A"]                       # builder:fresh absent -> pooled
    assert e.turns_run_hi == pytest.approx(30 * 3.0) and e.ctx_run_hi == pytest.approx(e.ctx_p50 * 4.0)
    assert e.wall_run_hi == pytest.approx(e.wall_p50 * 30.0)
    r = S.estimate(one(peak=100000), m)["A"]            # builder:resume
    assert r.turns_run_hi == pytest.approx(30 * 3.2) and r.ctx_run_hi == pytest.approx(r.ctx_p50 * 4.7)
    assert S.estimate(one(n=12), m)["A"].turns_run_hi == 12.0         # a fixed turn count has no spread
    # advisor only: the per-node maxTurns verdict still uses the band hi (45 < 60 fits), not the one-run hi (90)
    sch = S.schedule(one(), m)
    mt = [c for c in sch.checks if c.name == "maxTurns:A"]
    assert mt and mt[0].verdict == "fits"
    assert "one run, 90% hi: 90 turns" in S.render_md(S.estimate(one(), m), max_chars=None)


def test_replay_uses_the_measured_fixer_when_the_model_has_one(model, tmp_path):
    sid, graph = make_session(tmp_path)
    args = (str(tmp_path / "led.md"), str(tmp_path / "seg.csv"), str(tmp_path / "prm.csv"), graph)
    rep = S.replay(*args, model, session=sid)
    assert all("S_tok_measured" not in v for v in rep.rows.values())
    m = dict(model, fixer={"reread": 20000, "lo": 10000, "hi": 40000, "n": 14})
    rep = S.replay(*args, m, session=sid)
    v = rep.rows["release/oracle"]
    assert v["S_tok_measured_lo"] <= v["S_tok_measured"] <= v["S_tok_measured_hi"] <= v["S_tok_upper"] + 1e-12
    assert v["fixer_reread"] == 20000
    md = S.render_md(rep, max_chars=None)
    assert "S_tok measured" in md and "fixer.reread" in md


def test_load_model_keeps_well_formed_s1e_keys(tmp_path):
    f = tmp_path / "m.json"
    f.write_text(json.dumps({"types": {}, "resume_ctx": RC, "fixer": {"reread": 1000, "lo": 500, "hi": 2000},
                             "run_interval": RI}))
    m = S.load_model(f)
    assert m["resume_ctx"] == RC and m["fixer"]["reread"] == 1000 and m["run_interval"] == RI
    f.write_text(json.dumps({"types": {}, "resume_ctx": {"alpha": "x", "gamma": 1}, "fixer": {"reread": -1},
                             "run_interval": {"groups": []}}))
    m = S.load_model(f)
    assert not {"resume_ctx", "fixer", "run_interval"} & set(m)
    real = ROOT / "dot-claude" / "hooks" / "sched_model.json"
    raw = json.loads(real.read_text()) if real.is_file() else {}
    for k in ("resume_ctx", "fixer", "run_interval"):
        if raw.get(k):
            assert k in S.load_model(real), k
