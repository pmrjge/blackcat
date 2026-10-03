"""tests/derive_wave_sim.py: the held-out check of the replay's barrier simulation, on synthetic transcripts.

Run: uv run --python 3.13 --with pytest --with pandas --with numpy pytest -q tests/test_derive_wave_sim.py
"""
import json
import os
import sys

import pytest

pytest.importorskip("pandas")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import derive_wave_sim as D  # noqa: E402

PROJ = "-tmp-proj"


def iso(s):
    return "2026-10-02T%s.000Z" % s


def hms(sec):
    return "%02d:%02d:%02d" % (sec // 3600, sec % 3600 // 60, sec % 60)


def write_jsonl(path, recs):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.writelines(json.dumps(r) + "\n" for r in recs)


def call(mid, sec, blocks=None):
    return {"type": "assistant", "timestamp": iso(hms(sec)), "requestId": "r" + mid,
            "message": {"id": mid, "model": "claude-x", "content": blocks or [{"type": "text", "text": "ok"}],
                        "usage": {"input_tokens": 10, "output_tokens": 10, "cache_creation_input_tokens": 100,
                                  "cache_read_input_tokens": 100}}}


def user(sec, text):
    return {"type": "user", "timestamp": iso(hms(sec)), "message": {"content": text}}


def session(root, state, sid, orch, kids, lat, durs):
    """main thread -> orchestrator `orch`; the orchestrator's first message spawns kids[0], kids[1] (7 s apart), its next
    message, `lat` s after both returned, spawns kids[2]. Times from 10:00:00 UTC, ledger in UTC+1."""
    t0 = 36000
    base = os.path.join(root, PROJ)
    write_jsonl(os.path.join(base, sid + ".jsonl"), [user(t0 - 5, "do it"), call("m0" + sid[:4], t0 - 2)])
    sub = os.path.join(base, sid, "subagents")
    a, b, c = kids
    disp = {a: t0 + 5, b: t0 + 12}
    end = {a: disp[a] + 2 + durs[0], b: disp[b] + 2 + durs[1]}
    disp[c] = max(end.values()) + lat
    end[c] = disp[c] + 2 + durs[2]
    res = lambda tu, k: {"type": "tool_result", "tool_use_id": tu, "content": [{"type": "text", "text": "done\nagentId: %s (use SendMessage)" % k}]}
    spawn = lambda tu, k: {"type": "tool_use", "id": tu, "name": "Agent", "input": {"description": k, "subagent_type": "coder"}}
    m1, m2 = "m1" + sid[:4], "m2" + sid[:4]
    write_jsonl(os.path.join(sub, "agent-%s.jsonl" % orch), [
        user(t0, "plan"), call(m1, disp[a], [spawn("tu1", a)]), call(m1, disp[b], [spawn("tu2", b)]),
        {"type": "user", "timestamp": iso(hms(max(end[a], end[b]))), "message": {"content": [res("tu1", a), res("tu2", b)]}},
        call(m2, disp[c], [spawn("tu3", c)]),
        {"type": "user", "timestamp": iso(hms(end[c])), "message": {"content": [res("tu3", c)]}},
        call("m3" + sid[:4], end[c] + 5)])
    json.dump({"agentType": "orchestrator", "description": "O", "spawnDepth": 1}, open(os.path.join(sub, "agent-%s.meta.json" % orch), "w"))
    for k in kids:
        write_jsonl(os.path.join(sub, "agent-%s.jsonl" % k), [user(disp[k] + 1, "brief"), call("a" + k, disp[k] + 2),
                                                              call("b" + k, end[k])])
        json.dump({"agentType": "coder", "description": k, "spawnDepth": 2}, open(os.path.join(sub, "agent-%s.meta.json" % k), "w"))
    led = ["# Delegations, session %s" % sid, "Updated 12:00:00. x", "",
           '- orchestrator · "O" · finished · %s · id %s' % (hms(t0 - 1 + 3600), orch)]
    led += ['  - coder · "%s" · finished · %s · id %s' % (k, hms(int(disp[k]) + 3600), k) for k in kids]
    os.makedirs(os.path.join(state, sid), exist_ok=True)
    open(os.path.join(state, sid, "delegations.md"), "w").write("\n".join(led) + "\n")
    return max(end.values()) - (disp[a] + 2)


def test_held_out_report(tmp_path):
    root, state, out = str(tmp_path / "projects"), str(tmp_path / "state"), str(tmp_path / "wave-sim.md")
    s1, s2 = "11111111-aaaa-0000-0000-000000000000", "22222222-bbbb-0000-0000-000000000000"
    mk1 = session(root, state, s1, "a0000000000000001", ["a0000000000000002", "a0000000000000003", "a0000000000000004"],
                  lat=30, durs=(190, 280, 270))
    session(root, state, s2, "b0000000000000001", ["b0000000000000002", "b0000000000000003", "b0000000000000004"],
            lat=20, durs=(300, 120, 400))
    sids, rows = D.load(root, state, [])
    assert sids == [s1, s2]
    g = [r for r in rows if r["sid"] == s1 and r["disp"] == "a0000000000000001"][0]
    assert g["mk"] == pytest.approx(mk1)
    # the message waves come from the orchestrator's own messages, and the rule recovers them
    assert g["truth"] == [["a0000000000000002#0", "a0000000000000003#0"], ["a0000000000000004#0"]]
    assert D.rule_waves(g, 60.0) == g["truth"] and D.f1(D.barrier(rows), 60.0) == 1.0
    # held out: session 1 simulated with session 2's latency (20 s) and stagger (7 s), not with its own 30 s
    p = D.fit([r for r in rows if r["sid"] != s1])
    assert p["lat"] == pytest.approx(20.0) and p["stagger"] == pytest.approx(7.0)
    assert D.err_new(g, p) == pytest.approx((mk1 - 10.0) / mk1 - 1, abs=1e-6)
    sys.argv = ["derive_wave_sim.py", "--root", root, "--state", state, "--out", out]
    D.main()
    md = open(out).read()
    assert "## Leave one session out" in md and "| 11111111 |" in md and "| 22222222 |" in md
    assert "- after, rule waves: n=2 in 2 clusters;" in md and "Minimax over lat" in md
    # the headline is the groups that exercise the barrier (more than one message wave): here both
    head = md.split("Headline, groups with more than one message wave")[1].split("All groups")[0]
    assert "- after, rule waves: n=2 in 2 clusters; within 2%: 2 " in head and "crude 95% CI" in head
    assert "All groups (0 of 2 have one message wave" in md


def test_cluster_ci_resamples_dispatchers_not_groups():
    # 9 groups of one dispatcher within 2%, 1 group of another far off: as 10 independent groups the share's 95% CI
    # excludes 50%; with 2 clusters, resampling draws {B, B} a quarter of the time and the interval spans 0-100%
    errs, cl = [0.0] * 9 + [0.5], [("s", "A")] * 9 + [("s", "B")]
    assert D.wilson(9, 10)[0] > 0.5
    assert D.cluster_share_ci(errs, cl) == (0.0, 1.0)
    assert D.cluster_median_ci(errs, cl) == (0.0, 0.5)
    assert D.summary(errs, cl).startswith("n=10 in 2 clusters; within 2%: 9 (90%, crude 95% CI 0-100%)")


def test_release_is_measured_from_the_groups_first_dispatch(tmp_path):
    pd = pytest.importorskip("pandas")
    # orchestrator O: P runs from window 0 into window 1; in window 1 O spawns Y at 10:09:40 (started 20 s later) and
    # resumes P when P#0 ends at 10:13:00. The simulated timeline starts at Y's dispatch: P#0 ends 200 s into it
    sid, O, P, Y = "33333333-0000-0000-0000-000000000000", "c0000000000000001", "c0000000000000002", "c0000000000000003"
    seg = pd.DataFrame([dict(session=sid, id=P, seg=0, first_ts=iso("10:05:20"), last_ts=iso("10:13:00")),
                        dict(session=sid, id=Y, seg=0, first_ts=iso("10:10:00"), last_ts=iso("10:10:10")),
                        dict(session=sid, id=P, seg=1, first_ts=iso("10:13:20"), last_ts=iso("10:18:20"))])
    ev = [("user", {"tr": False, "meta": False, "text": t, "ts": iso(ts)}) for t, ts in (("go", "10:00:00"), ("next", "10:09:30"))]
    led = tmp_path / "delegations.md"
    led.write_text("# Delegations, session %s\n\n- orchestrator · (no description) · finished · 10:59:00 · id %s\n"
                   "  - verifier · (no description) · finished · 11:05:20 · id %s\n"
                   "  - coder · (no description) · finished · 11:09:40 · id %s\n" % (sid, O, P, Y))
    g = [r for r in D.session_groups(sid, seg, ev, [], str(led)) if r["wi"] == 1][0]
    y, p1 = g["units"][Y + "#0"], g["units"][P + "#1"]
    assert g["disp"] == O and len(g["units"]) == 2 and y["dispatch"] == y["start"] - 20 and g["mk"] == pytest.approx(500.0)
    assert p1["rel"] == pytest.approx(200.0)                                    # 180 s from Y's start
    # Y 20 + 10 s; P#1 released at 200 + 20 s, 300 s long: 520 - 20 = 500 s, the recorded makespan (-4% from the start)
    assert D.err_new(g, {"gap": 60.0, "lat": 20.0, "stagger": 0.0}) == pytest.approx(0.0)


def test_replay_section_on_the_committed_fixture(tmp_path):
    root, state, out = str(tmp_path / "projects"), str(tmp_path / "state"), str(tmp_path / "wave-sim.md")
    session(root, state, "11111111-aaaa-0000-0000-000000000000", "a0000000000000001",
            ["a0000000000000002", "a0000000000000003", "a0000000000000004"], lat=30, durs=(190, 280, 270))
    fx = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "sched", "4e2da3ce")
    sys.argv = ["derive_wave_sim.py", "--root", root, "--state", state, "--out", out, "--replay-usage", fx,
                "--replay-ledger", os.path.join(fx, "delegations.md")]
    D.main()
    md = open(out).read()
    assert "## Replay windows, session 4e2da3ce" in md and "unreachable" not in md
    # the windows with a barrier are named and scored apart; the minimax states the stagger 2% in every window needs
    assert "Windows with more than one wave in a timeline (the only ones that exercise the barrier): 1, 3, 21, 36;" in md
    mm = float(md.split("on these windows' rule waves: worst |error| at best ")[1].split("%")[0])
    assert ("2% in every window needs a stagger of at least" in md) == (mm <= 2.0)
