"""Hand-back protocol, Phase 1 (observe by default): hooks/stack_report.py and its use in agent_guard.py
(SubagentStop check, PreToolUse(Agent) brief measures, PostToolUse(Agent) totals), the parsers that read the
same final reply (stack_sdk.parse_report, stack-tree, stack_usage) and stack-tree's registry-report and
--pending logic.

Run: ~/.claude/venvs/tools/bin/python -m pytest -q -p no:cacheprovider tests/test_stack_report.py
Hook processes run under /usr/bin/python3 (the hooks' interpreter, 3.9 on macOS); every state lives under
tmp_path (XDG_STATE_HOME, HOME, cwd), STACK_/BLACKCAT_/CLAUDE_ variables are stripped, no sleeps, no
network. Fixtures: tests/fixtures/reports/*.txt (raw final replies) and expected.json (what each parser must
read from them).

Mutation seam (how the tests are proven on seeded bugs): S4_DOT names a copy of dot-claude/ with one seeded
bug (hooks/, bin/); unset, the real tree is used. Nothing else reads it.
"""
import importlib.machinery
import importlib.util
import json
import math
import os
import stat
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import pytest

sys.dont_write_bytecode = True          # no __pycache__ beside the code under test

ROOT = Path(__file__).resolve().parents[1]
DOT = Path(os.environ.get("S4_DOT") or ROOT / "dot-claude")
HOOKS = DOT / "hooks"
GUARD = HOOKS / "agent_guard.py"
TREE = DOT / "bin" / "stack-tree"
SDK = DOT / "bin" / "stack_sdk.py"
FIX = ROOT / "tests" / "fixtures" / "reports"
PY = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable
STRIP = ("STACK_", "BLACKCAT_", "SCREEN_", "STRIP_", "CLAUDE_")
STARTED = 1790000000.5


def load(path, name):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    loader.exec_module(mod)
    return mod


sr = load(HOOKS / "stack_report.py", "s4_stack_report")
sdk = load(SDK, "s4_stack_sdk")
tree = load(TREE, "s4_stack_tree")
U = load(HOOKS / "stack_usage.py", "s4_stack_usage")
EXPECT = json.loads((FIX / "expected.json").read_text())


def fixture_text(name):
    return (FIX / (name + ".txt")).read_text()


# ---------------------------------------------------------------- the hook rig
class Result(object):
    def __init__(self, rc, out, err, secs):
        self.rc, self.stdout, self.stderr, self.secs = rc, out, err, secs

    @property
    def json(self):
        return json.loads(self.stdout) if self.stdout.strip() else None


class Rig(object):
    """One session's state under tmp_path; events piped into agent_guard.py as Claude Code does (no tty)."""

    def __init__(self, tmp, sid="s-s4test", **knobs):
        self.tmp, self.sid = Path(tmp), sid
        self.home, self.cwd = self.tmp / "home", self.tmp / "proj"
        self.home.mkdir(exist_ok=True)
        self.cwd.mkdir(exist_ok=True)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(STRIP)}
        self.env.update(XDG_STATE_HOME=str(self.tmp / "state"), HOME=str(self.home), PYTHONDONTWRITEBYTECODE="1")
        self.env.update({k: str(v) for k, v in knobs.items()})
        self.state = self.tmp / "state" / "claude-agent-stack" / sid
        (self.state / "agents").mkdir(parents=True, exist_ok=True)
        self.main_transcript = self.tmp / (sid + ".jsonl")
        self.main_transcript.write_text("{}\n")

    # -- state
    def seed(self, aid, atype="coder", started=STARTED, spawned=True, **kw):
        rec = {"id": aid, "type": atype, "started": started, "parent": "main", "depth": 1}
        if spawned:
            rec.update(spawned=started + 1, tool_use_id="toolu_" + aid)
        rec.update(kw)
        (self.state / "agents" / (aid + ".json")).write_text(json.dumps(rec))

    def reg(self, aid):
        p = self.state / "agents" / (aid + ".json")
        return json.loads(p.read_text()) if p.exists() else None

    def ledger(self, tid, **rec):
        (self.state / "spawns").mkdir(exist_ok=True)
        (self.state / "spawns" / (tid + ".json")).write_text(json.dumps(dict({"tid": tid}, **rec)))

    def ledger_rec(self, tid):
        return json.loads((self.state / "spawns" / (tid + ".json")).read_text())

    def copies(self):
        d = self.state / "reports"
        return sorted(p.name for p in d.iterdir()) if d.is_dir() else []

    def rows(self):
        p = self.tmp / "state" / "claude-agent-stack" / "usage" / "reports.jsonl"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    # -- events
    def base(self, event, **kw):
        ev = {"session_id": self.sid, "hook_event_name": event, "transcript_path": str(self.main_transcript),
              "cwd": str(self.cwd)}
        ev.update(kw)
        return ev

    def stop(self, aid, atype, text, active=False, transcript=None, cwd=None):
        return self.base("SubagentStop", agent_id=aid, agent_type=atype, stop_hook_active=active,
                         agent_transcript_path=transcript, last_assistant_message=text,
                         **({"cwd": str(cwd)} if cwd else {}))

    def start(self, aid, atype):
        return self.base("SubagentStart", agent_id=aid, agent_type=atype)

    def pre_agent(self, tid, prompt, child="coder"):
        return self.base("PreToolUse", tool_name="Agent", prompt_id="p1", tool_use_id=tid, agent_type="blackcat",
                         tool_input={"subagent_type": child, "prompt": prompt, "description": "do it"})

    # -- running
    def popen(self, ev, **extra):
        p = subprocess.Popen([PY, "-B", str(GUARD)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, env=dict(self.env, **extra), start_new_session=True)
        p.stdin.write(json.dumps(ev))
        p.stdin.close()
        return p

    def run(self, ev, **extra):
        t0 = time.monotonic()
        p = self.popen(ev, **extra)
        out, err = p.stdout.read(), p.stderr.read()
        p.wait(timeout=60)
        return Result(p.returncode, out, err, time.monotonic() - t0)


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path, STACK_REPORT_FORMAT="compact")


def blocked(res):
    j = res.json
    return bool(j) and j.get("decision") == "block"


BAD = "ok"                 # a hard violation (no STATUS line) for any class
GOOD = "STATUS: done\nRESULT: fine\nFILES: none\nEVIDENCE: pytest -q → 3 passed"


# ================================================================ 1. cross-parser agreement
@pytest.mark.parametrize("name", sorted(EXPECT))
def test_cross_parser_agreement(name):
    exp, text = EXPECT[name], fixture_text(name)
    p, q = sr.parse(text), sdk.parse_report(text)
    hits = list(tree.STATUS_RE.finditer(text))
    mu = U.STATUS_RE.search(text)
    # stack_report: the absolute expectations
    assert (p["format"], p["status"], p["eflag"], p["wrapped"]) == (exp["format"], exp["status"], exp["eflag"],
                                                                    exp["wrapped"])
    assert [f["path"] for f in p["files"]] == exp["files"]
    assert [f["deleted"] for f in p["files"]] == exp["deleted"]
    for k in ("verdict", "counts", "evidence_ref"):
        if k in exp:
            assert p[k] == exp[k], k
    # stack_sdk.parse_report: status, E flag and the FILES paths as stack_report reads them
    assert (q["format"], q["status"]) == (exp["sdk_format"], exp["sdk_status"])
    assert q["files"] == exp["files"]
    # stack-tree: the last STATUS line (+ its E flag); no line is a clean finish = done
    tstatus, teflag = (hits[-1].group(1).lower(), (hits[-1].group(2) or "").lower() or None) if hits \
        else ("done", None)
    assert [tstatus, teflag] == exp["tree"]
    # stack_usage: the first `STATUS:` line at a line start; no match = no status code (a clean 0 in the collector)
    assert (mu.group(1) if mu else None) == exp["usage"]
    if mu:
        assert U.STATUS_CODE[mu.group(1)] == {"done": 0, "partial": 1, "failed": 1, "blocked": 2}[exp["usage"]]
    # where every parser reads a status they agree, and the E flag agrees wherever one is read
    if p["status"]:
        assert {p["status"], q["status"], tstatus, mu.group(1)} == {p["status"]}
        assert p["eflag"] == q["eflag"] == teflag


def test_no_status_conventions_are_pinned():
    """The conventions for a reply without a STATUS line, per parser (the clean-finish line and plain text)."""
    clean, plain = fixture_text("clean_finish"), fixture_text("plain_text")
    assert (sr.parse(clean)["format"], sr.parse(clean)["status"], sr.parse(clean)["header"]) == ("clean", None, True)
    assert (sr.parse(plain)["format"], sr.parse(plain)["status"]) == ("text", None)
    assert (sdk.parse_report(clean)["format"], sdk.parse_report(clean)["status"]) == ("clean", "done")
    assert (sdk.parse_report(plain)["format"], sdk.parse_report(plain)["status"]) == ("text", None)
    assert not tree.STATUS_RE.search(clean) and not tree.STATUS_RE.search(plain)      # tree: no match -> "done"
    assert not U.STATUS_RE.search(clean) and not U.STATUS_RE.search(plain)            # usage: no match -> clean 0
    assert sr.parse("")["format"] == "empty"


def test_stack_tree_scan_defaults_a_clean_finish_to_done_and_reads_the_last_status(tmp_path):
    f = TreeFix(tmp_path)
    f.spawn("t1", "main", "coder", "a", child="A1", ts=f.t0)
    f.spawn("t2", "main", "coder", "b", child="A2", ts=f.t0 + 1)
    f.agent("A1", "coder")
    f.agent("A2", "coder", start=f.t0 + 1)
    f.transcript([say("a1", fixture_text("clean_finish"), f.t0 + 5)], "A1")
    f.transcript([say("a2", "first\nSTATUS: partial\nthen\nSTATUS: failed · E:drop", f.t0 + 6)], "A2")
    d = {n["id"]: n for n in flatten(json.loads(f.run("--session", f.sid, "--json").stdout)["root"])}
    assert (d["A1"]["status"], d["A1"]["eflag"]) == ("done", None)
    assert (d["A2"]["status"], d["A2"]["eflag"]) == ("failed", "drop")


# ================================================================ 2. restate once (compact)
@pytest.mark.parametrize("active_on_second", [False, True])
def test_restate_once_lifecycle(rig, active_on_second):
    rig.seed("aa1", "coder")
    r1 = rig.run(rig.stop("aa1", "coder", BAD))
    j = r1.json
    assert r1.rc == 0 and set(j) == {"decision", "reason"} and j["decision"] == "block"
    assert 0 < len(j["reason"]) <= 400 and "no STATUS line" in j["reason"]
    rec = rig.reg("aa1")
    assert "stopped" not in rec                                   # the agent keeps running to restate
    assert rec["report"]["blocked"] is True and rec["report"]["restate_key"] == str(STARTED)
    r2 = rig.run(rig.stop("aa1", "coder", BAD, active=active_on_second))
    assert r2.rc == 0 and r2.stdout == ""                         # never a second block for this run
    rec = rig.reg("aa1")
    assert rec.get("stopped")                                     # the second stop records the stop
    assert rec["report"]["restated"] is True and rec["report"]["blocked"] is False and rec["report"]["stops"] == 2
    names = rig.copies()
    assert names == ["aa1.%d.1.md" % int(STARTED), "aa1.%d.2.md" % int(STARTED)]
    for n in names:
        assert stat.S_IMODE((rig.state / "reports" / n).stat().st_mode) == 0o600
    # a resumed run is a new run (SubagentStart stamps a new `started`): it may be restated once more
    rig.run(rig.start("aa1", "coder"))
    new = rig.reg("aa1")
    assert new["started"] != STARTED and "stopped" not in new
    r3 = rig.run(rig.stop("aa1", "coder", BAD))
    assert blocked(r3)
    assert rig.run(rig.stop("aa1", "coder", BAD)).stdout == ""
    assert any(n.startswith("aa1.%d." % int(new["started"])) for n in rig.copies())


def test_a_resumed_run_drops_the_previous_report(tmp_path):
    """SubagentStart clears the earlier run's report: a resume that ends without a reply shows none."""
    rig = Rig(tmp_path, STACK_REPORT_FORMAT="observe")
    rig.seed("ag1", "coder")
    rig.run(rig.stop("ag1", "coder", "STATUS: failed\nRESULT: x\nEVIDENCE: e\nNEXT: n"))
    assert rig.reg("ag1")["report"]["status"] == "failed"
    rig.run(rig.start("ag1", "coder"))
    rig.run(rig.stop("ag1", "coder", ""))
    assert "report" not in rig.reg("ag1")


def test_rows_of_a_restate_share_the_run_stamp_and_carry_wrapped(rig):
    """21. `run` is the registry `started` stamp as a string, so both rows of a restate join; `wrapped` too."""
    rig.seed("rr1", "coder")
    rig.run(rig.stop("rr1", "coder", BAD))
    rig.run(rig.stop("rr1", "coder", BAD))
    rows = rig.rows()
    assert len(rows) == 2
    assert {(r["session"], r["agent_id"], r["run"]) for r in rows} == {("s-s4test", "rr1", str(STARTED))}
    assert all(isinstance(r["run"], str) and r["wrapped"] is False for r in rows)
    assert [(r["n"], r["blocked"], r["restated"]) for r in rows] == [(1, True, False), (2, False, True)]
    rig.seed("rr2", "coder")
    rig.run(rig.stop("rr2", "coder", fixture_text("fenced_whole")))
    wrapped = [r for r in rig.rows() if r["agent_id"] == "rr2"]
    assert wrapped[0]["wrapped"] is True and wrapped[0]["run"] == str(STARTED)


# ================================================================ 3. concurrent stops
def test_two_concurrent_stops_block_exactly_once(rig):
    rig.seed("cc1", "coder")
    outs = []

    def go(p, t0):
        out, err = p.stdout.read(), p.stderr.read()
        p.wait(timeout=60)
        outs.append((out, err, time.monotonic() - t0, p.returncode))

    ths = []
    t0 = time.monotonic()
    procs = [rig.popen(rig.stop("cc1", "coder", BAD)) for _ in range(2)]
    for p in procs:
        th = threading.Thread(target=go, args=(p, t0))
        th.start()
        ths.append(th)
    for th in ths:
        th.join(60)
    assert len(outs) == 2
    assert sorted(bool(o[0].strip()) for o in outs) == [False, True]
    assert sum(1 for o in outs if json.loads(o[0] or "{}").get("decision") == "block") == 1
    assert all(o[3] == 0 and o[2] < 2.0 for o in outs), outs
    assert rig.copies() == ["cc1.%d.1.md" % int(STARTED), "cc1.%d.2.md" % int(STARTED)]
    rep = rig.reg("cc1")["report"]
    assert rep["stops"] == 2 and rep["restated"] is True


def test_an_earlier_finish_never_overwrites_a_later_stop(guard, tmp_path):
    """The interleaving forced in-process: stop 1 decides, then stop 2 runs whole before stop 1 copies its
    reply and finishes; the registry keeps stop 2's report and copy (the `stops == n` guard in finish)."""
    d = seed_inproc(guard, tmp_path)
    real, calls = guard.report_copy, []

    def copy(*a):
        calls.append(a[3])
        if len(calls) == 1:
            guard.report_stop(stop_event("ff1", "coder", GOOD, tmp_path), d, "ff1", "coder")
        return real(*a)
    guard.report_copy = copy
    assert guard.report_stop(stop_event("ff1", "coder", GOOD, tmp_path), d, "ff1", "coder") is None
    assert calls == [1, 2]
    rep = guard.reg_get(d, "ff1")["report"]
    assert rep["stops"] == 2 and rep["path"].endswith(".2.md")
    assert sorted(os.listdir(os.path.join(d, "reports"))) == ["ff1.%d.1.md" % int(STARTED),
                                                              "ff1.%d.2.md" % int(STARTED)]


# ================================================================ 4. stop_hook_active on the first stop
def test_stop_hook_active_on_the_first_stop_never_blocks_and_is_recorded(rig):
    rig.seed("hh1", "coder")
    r = rig.run(rig.stop("hh1", "coder", BAD, active=True))
    assert r.rc == 0 and r.stdout == ""
    rec = rig.reg("hh1")
    assert rec.get("stopped") and rec["report"]["blocked"] is False and rec["report"]["hard"] == ["no_status"]
    (row,) = rig.rows()
    assert row["stop_hook_active"] is True and row["blocked"] is False and row["hard"] == ["no_status"]
    # a string "true" counts too (the event may carry either)
    rig.seed("hh2", "coder")
    assert rig.run(rig.stop("hh2", "coder", BAD, active="True")).stdout == ""


# ================================================================ 5. fail open
@pytest.fixture
def guard(tmp_path, monkeypatch):
    for k in [k for k in os.environ if k.startswith(STRIP)]:
        monkeypatch.delenv(k)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("STACK_REPORT_FORMAT", "compact")
    monkeypatch.setitem(sys.modules, "stack_report", sr)
    g = load(GUARD, "s4_agent_guard")
    monkeypatch.setattr(g, "_REPORT_MOD", [])
    return g


def seed_inproc(g, tmp_path, aid="ff1", atype="coder"):
    d = g.sdir("s-inproc")
    os.makedirs(os.path.join(d, "agents"), exist_ok=True)
    with open(os.path.join(d, "agents", aid + ".json"), "w") as fh:
        json.dump({"id": aid, "type": atype, "started": STARTED, "spawned": STARTED + 1}, fh)
    return d


def stop_event(aid, atype, text, cwd):
    return {"session_id": "s-inproc", "hook_event_name": "SubagentStop", "agent_id": aid, "agent_type": atype,
            "stop_hook_active": False, "last_assistant_message": text, "cwd": str(cwd)}


def call_stop(g, ev, d):
    try:
        g.on_subagent_stop(ev, d)
    except SystemExit:
        pass


def test_fail_open_with_a_raising_parser(guard, tmp_path, capsys):
    d = seed_inproc(guard, tmp_path)

    def boom(_text):
        raise ValueError("parser exploded")
    fake = types.SimpleNamespace(**{n: getattr(sr, n) for n in dir(sr) if not n.startswith("__")})
    fake.parse = boom
    guard.report_module = lambda: fake
    call_stop(guard, stop_event("ff1", "coder", BAD, tmp_path), d)
    cap = capsys.readouterr()
    assert cap.out == ""                                           # no decision
    assert "hand-back check: ValueError: parser exploded" in cap.err
    assert guard.reg_get(d, "ff1").get("stopped")                  # and the stop is recorded


@pytest.mark.parametrize("exc", ["MutexTimeout", "OSError", "KeyError"])
def test_fail_open_with_a_raising_registry_update(guard, tmp_path, capsys, exc):
    d = seed_inproc(guard, tmp_path)
    err = {"MutexTimeout": guard.MutexTimeout("timed out waiting for registry.mutex"), "OSError": OSError("disk"),
           "KeyError": KeyError("k")}[exc]

    def boom(*a, **k):
        raise err
    guard.reg_update = boom
    call_stop(guard, stop_event("ff1", "coder", BAD, tmp_path), d)
    cap = capsys.readouterr()
    assert cap.out == "" and "hand-back check" in cap.err
    assert guard.reg_get(d, "ff1").get("stopped")


def test_fail_open_when_the_module_cannot_be_imported(guard, tmp_path, capsys):
    d = seed_inproc(guard, tmp_path)

    def nomod():
        raise ImportError("no stack_report")
    guard.report_module = nomod
    call_stop(guard, stop_event("ff1", "coder", BAD, tmp_path), d)
    cap = capsys.readouterr()
    assert cap.out == "" and "hand-back check: ImportError" in cap.err
    assert guard.reg_get(d, "ff1").get("stopped")


def test_a_failing_record_never_undoes_the_decision(guard, tmp_path, capsys):
    """compact: the block was decided under the registry lock; a copy or log that cannot be written only warns."""
    d = seed_inproc(guard, tmp_path)

    def boom(*a, **k):
        raise OSError("read-only")
    guard.report_copy = boom
    guard.report_log = boom
    call_stop(guard, stop_event("ff1", "coder", BAD, tmp_path), d)
    cap = capsys.readouterr()
    assert json.loads(cap.out)["decision"] == "block"
    assert "hand-back record: OSError" in cap.err
    assert not guard.reg_get(d, "ff1").get("stopped")


# ================================================================ 6. who is checked
def test_only_spawned_stack_subagents_are_checked(rig, tmp_path):
    # the session's own agent (what prompt suggestions and /btw run as), with and without a registry entry
    assert rig.run(rig.stop("bb1", "blackcat", "ok")).stdout == ""
    rig.seed("bb2", "blackcat")
    assert rig.run(rig.stop("bb2", "blackcat", "ok")).stdout == ""
    # a stack type no allowed Agent call spawned: no registry entry / an entry without `spawned`, no ledger link
    assert rig.run(rig.stop("nn1", "coder", "ok")).stdout == ""
    rig.seed("nn2", "coder", spawned=False)
    assert rig.run(rig.stop("nn2", "coder", "ok")).stdout == ""
    # a foreign type with an entry
    rig.seed("nn3", "mystery-agent")
    assert rig.run(rig.stop("nn3", "mystery-agent", "ok")).stdout == ""
    assert rig.copies() == [] and rig.rows() == []
    assert not (rig.state / "reports").exists()
    # the foreground path: no `spawned`, but meta.json names a ledger record of the same type
    sub = tmp_path / "projects" / "p" / "subagents"
    sub.mkdir(parents=True)
    rig.seed("fg1", "coder", spawned=False)
    rig.ledger("toolu_fg", type="coder", by="main")
    (sub / "agent-fg1.meta.json").write_text(json.dumps({"agentType": "coder", "toolUseId": "toolu_fg"}))
    assert blocked(rig.run(rig.stop("fg1", "coder", "ok", transcript=str(sub / "agent-fg1.jsonl"))))
    assert rig.copies() == ["fg1.%d.1.md" % int(STARTED)]
    # a ledger record of ANOTHER type does not vouch for it
    rig.seed("fg2", "coder", spawned=False)
    rig.ledger("toolu_fg2", type="scout", by="main")
    (sub / "agent-fg2.meta.json").write_text(json.dumps({"toolUseId": "toolu_fg2"}))
    assert rig.run(rig.stop("fg2", "coder", "ok", transcript=str(sub / "agent-fg2.jsonl"))).stdout == ""
    assert not any(n.startswith("fg2.") for n in rig.copies())
    assert [r["agent_id"] for r in rig.rows()] == ["fg1"]
    # control: a spawned one is checked and recorded
    rig.seed("ok1", "coder")
    assert blocked(rig.run(rig.stop("ok1", "coder", "ok")))


def test_blank_or_missing_reply_is_not_checked(rig):
    rig.seed("em1", "coder")
    assert rig.run(rig.stop("em1", "coder", "  \n ")).stdout == ""
    ev = rig.stop("em1", "coder", None)
    assert rig.run(ev).stdout == ""
    assert rig.rows() == [] and rig.reg("em1").get("stopped") and "report" not in rig.reg("em1")


# ================================================================ 7. the planner's plan
def test_planner_plan_is_not_blocked(rig):
    text = fixture_text("planner_plan")
    assert len(text) > 12000
    rig.seed("pl1", "planner")
    r = rig.run(rig.stop("pl1", "planner", text))
    assert r.rc == 0 and r.stdout == ""
    rep = rig.reg("pl1")["report"]
    assert rep["class"] == "plan" and rep["hard"] == [] and rep["blocked"] is False
    assert "size" in rep["soft"] and "blob" in rep["soft"]       # only soft violations, logged
    assert rig.reg("pl1").get("stopped")
    # the same text from a builder IS a hard violation (the class decides)
    rig.seed("pl2", "coder")
    assert blocked(rig.run(rig.stop("pl2", "coder", text)))


# ================================================================ 8. missing and deleted files
def report_with_files(*lines):
    return "STATUS: done\nRESULT: ok\nFILES:\n%s\nEVIDENCE: pytest -q → 1 passed\nNEXT: none" % "\n".join(lines)


def test_deleted_path_that_does_not_exist_is_not_missing(rig):
    rig.seed("df1", "coder")
    r = rig.run(rig.stop("df1", "coder", report_with_files("- gone/old.py — deleted", "- also_gone.py — (deleted)")))
    assert r.stdout == ""
    rep = rig.reg("df1")["report"]
    assert rep["files"] == [{"path": "gone/old.py", "state": "deleted"}, {"path": "also_gone.py", "state": "deleted"}]
    assert rep["missing"] == [] and rep["blocked"] is False
    assert rig.rows()[0]["missing"] == 0 and rig.rows()[0]["files"] == 2


def test_missing_non_deleted_path_is_logged_never_blocked(rig):
    (rig.cwd / "real.py").write_text("x = 1\n")
    rig.seed("df2", "coder")
    r = rig.run(rig.stop("df2", "coder", report_with_files("- nope/new.py — new module", "- real.py — edited")))
    assert r.stdout == ""
    rep = rig.reg("df2")["report"]
    assert rep["missing"] == ["nope/new.py"]
    states = {f["path"]: f for f in rep["files"]}
    assert states["nope/new.py"] == {"path": "nope/new.py", "state": "missing"}
    assert states["real.py"]["state"] == "ok" and states["real.py"]["size"] == 6 and len(states["real.py"]["sha8"]) == 8
    assert rig.rows()[0]["missing"] == 1 and rep["hard"] == [] and rep["blocked"] is False


# ================================================================ 9. credential and outside paths
OUTSIDE = lambda p: {"path": p, "state": "outside"}          # noqa: E731 - exactly this, no size/mtime/sha8


def test_credential_path_is_outside_with_nothing_recorded(tmp_path, monkeypatch):
    home, proj = tmp_path / "home", tmp_path / "proj"
    (home / ".ssh").mkdir(parents=True)
    (home / ".ssh" / "id_ed25519").write_text("PRIVATE KEY")
    proj.mkdir()
    monkeypatch.setenv("HOME", str(home))
    got = sr.file_meta([{"path": "~/.ssh/id_ed25519"}], str(proj))
    assert got == [OUTSIDE("~/.ssh/id_ed25519")]
    # inside the cwd, a credential-named path is still never looked at
    (proj / ".ssh").mkdir()
    (proj / ".ssh" / "id_rsa").write_text("K")
    (proj / ".env").write_text("TOKEN=1")
    (proj / "sub").mkdir()
    (proj / "sub" / ".env.local").write_text("TOKEN=2")
    got = sr.file_meta([{"path": ".ssh/id_rsa"}, {"path": ".env"}, {"path": "sub/.env.local"}], str(proj))
    assert got == [OUTSIDE(".ssh/id_rsa"), OUTSIDE(".env"), OUTSIDE("sub/.env.local")]


def test_home_as_cwd_opens_nothing(tmp_path, monkeypatch):
    """HOME is also the event cwd: a cwd that is the home folder is no root, so ~/.ssh stays unread."""
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    (home / ".ssh" / "id_ed25519").write_text("PRIVATE KEY")
    (home / "notes.txt").write_text("n")
    monkeypatch.setenv("HOME", str(home))
    files = [{"path": "~/.ssh/id_ed25519"}, {"path": ".ssh/id_ed25519"}, {"path": "notes.txt"}]
    assert sr.file_meta(files, str(home)) == [OUTSIDE("~/.ssh/id_ed25519"), OUTSIDE(".ssh/id_ed25519"),
                                                OUTSIDE("notes.txt")]
    assert sr.allowed_roots(str(home)) == [] and sr.allowed_roots("/") == []
    assert sr.allowed_roots(str(tmp_path)) == []                   # an ancestor of home neither
    assert sr.allowed_roots(str(home / ".ssh"), str(home)) != []   # a folder below home is one


def test_credential_path_through_the_hook_is_recorded_as_outside(tmp_path):
    rig = Rig(tmp_path, STACK_REPORT_FORMAT="observe")
    (rig.home / ".ssh").mkdir()
    (rig.home / ".ssh" / "id_ed25519").write_text("PRIVATE KEY")
    rig.seed("ss1", "coder")
    rig.run(rig.stop("ss1", "coder", report_with_files("- ~/.ssh/id_ed25519 — read")))
    assert rig.reg("ss1")["report"]["files"] == [OUTSIDE("~/.ssh/id_ed25519")]
    # HOME is the event cwd (the hook's own environment): the same
    (tmp_path / "two").mkdir()
    rig2 = Rig(tmp_path / "two", STACK_REPORT_FORMAT="observe")
    rig2.cwd = rig2.home
    (rig2.home / ".ssh").mkdir()
    (rig2.home / ".ssh" / "id_ed25519").write_text("PRIVATE KEY")
    rig2.seed("ss2", "coder")
    rig2.run(rig2.stop("ss2", "coder", report_with_files("- ~/.ssh/id_ed25519 — read", "- .ssh/id_ed25519 — read")))
    assert rig2.reg("ss2")["report"]["files"] == [OUTSIDE("~/.ssh/id_ed25519"), OUTSIDE(".ssh/id_ed25519")]


def test_a_symlinked_claude_work_never_widens_the_roots(tmp_path, monkeypatch):
    """.claude-work is agent-writable: a symlink there to ~/.config must not make ~/.config a root."""
    home, proj = tmp_path / "home", tmp_path / "proj"
    (home / ".config" / "git").mkdir(parents=True)
    cred = home / ".config" / "git" / "credentials"
    cred.write_text("https://u:token@example.com\n")
    (proj / ".git").mkdir(parents=True)
    (proj / ".claude-work").symlink_to(home / ".config")
    monkeypatch.setenv("HOME", str(home))
    assert str(home / ".config") not in sr.allowed_roots(str(proj))
    assert sr.file_meta([{"path": str(cred)}], str(proj)) == [OUTSIDE(str(cred))]
    assert sr.file_meta([{"path": ".claude-work/git/credentials"}], str(proj)) == \
        [OUTSIDE(".claude-work/git/credentials")]


@pytest.mark.parametrize("path", ["/p/.config/git/credentials", "/p/.cache/huggingface/token",
                                  "/p/.claude/ide/1234.lock", "/p/.claude/backup-20261003/settings.json",
                                  "/p/.local/state/claude-agent-stack-backups/a.json", "/p/.SSH/id_rsa",
                                  "/p/.Env.Local", "/p/sub/.ENV", "/p/.Config/GH/hosts.yml"])
def test_more_credential_paths_are_never_looked_at(path):
    """The sandbox-denied reads, matched case-insensitively (APFS is case-insensitive by default)."""
    assert sr._credential(path)


def test_ordinary_paths_are_no_credential():
    for p in ("/p/src/env.py", "/p/.environment", "/p/.config/app.toml", "/p/.claude/agents/x.md",
              "/p/.cache/pip/x"):
        assert not sr._credential(p), p


# ================================================================ 10. swaps after resolution
def bounded(fn, secs=5.0):
    """Run fn in a daemon thread: (result, finished). A hang is a failed assertion, not a stuck suite."""
    box = []
    th = threading.Thread(target=lambda: box.append(fn()), daemon=True)
    th.start()
    th.join(secs)
    return (box[0] if box else None), bool(box)


def test_fifo_swapped_in_after_resolution_is_not_regular_and_never_hangs(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    proj.mkdir()
    target = proj / "report.md"
    target.write_text("data")
    real = sr._resolve

    def swap(path, cwd):
        got = real(path, cwd)
        os.unlink(got)
        os.mkfifo(got)
        return got
    monkeypatch.setattr(sr, "_resolve", swap)
    got, done = bounded(lambda: sr.file_meta([{"path": "report.md"}], str(proj)))
    try:
        fd = os.open(str(target), os.O_WRONLY | os.O_NONBLOCK)      # release a reader stuck in open()
        os.close(fd)
    except OSError:
        pass
    assert done, "file_meta hung on a FIFO"
    assert got == [{"path": "report.md", "state": "not_regular"}]


def test_final_component_swapped_to_a_symlink_is_refused(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "other.txt").write_text("other")
    (proj / "f.txt").write_text("orig")
    real = sr._resolve

    def swap(path, cwd):
        got = real(path, cwd)
        os.unlink(got)
        os.symlink(str(proj / "other.txt"), got)
        return got
    monkeypatch.setattr(sr, "_resolve", swap)
    assert sr.file_meta([{"path": "f.txt"}], str(proj)) == [{"path": "f.txt", "state": "symlink"}]


def test_symlink_inside_cwd_pointing_outside_is_outside(tmp_path):
    proj, away = tmp_path / "proj", tmp_path / "away"
    proj.mkdir()
    away.mkdir()
    (away / "secret.txt").write_text("s")
    os.symlink(str(away / "secret.txt"), str(proj / "link.txt"))
    os.symlink(str(away), str(proj / "dir"))
    got = sr.file_meta([{"path": "link.txt"}, {"path": "dir/secret.txt"}], str(proj))
    assert got == [OUTSIDE("link.txt"), OUTSIDE("dir/secret.txt")]
    # a symlink to a file inside the roots resolves (realpath) to a regular file: looked at, state ok
    (proj / "real.txt").write_text("r")
    os.symlink(str(proj / "real.txt"), str(proj / "ok_link.txt"))
    assert sr.file_meta([{"path": "ok_link.txt"}], str(proj))[0]["state"] == "ok"


def test_path_swapped_to_a_file_outside_after_resolution_is_outside(tmp_path, monkeypatch):
    """The kernel's own path for the open descriptor is checked again (F_GETPATH, /proc/self/fd)."""
    proj, away = tmp_path / "proj", tmp_path / "away"
    proj.mkdir()
    away.mkdir()
    (away / "s.txt").write_text("s")
    (proj / "a" / "b").mkdir(parents=True)
    (proj / "a" / "b" / "f.txt").write_text("f")
    real = sr._resolve

    def swap(path, cwd):
        got = real(path, cwd)
        (proj / "a" / "b").rename(proj / "a" / "b_old")             # a directory component becomes a link
        os.symlink(str(away), str(proj / "a" / "b"))
        (away / "f.txt").write_text("outside")
        return got
    monkeypatch.setattr(sr, "_resolve", swap)
    got = sr.file_meta([{"path": "a/b/f.txt"}], str(proj))
    assert got == [OUTSIDE("a/b/f.txt")]


# ================================================================ 11. huge files and a stuck hash
def test_huge_sparse_file_is_stat_only(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    big = proj / "big.bin"
    with open(big, "wb") as fh:
        fh.truncate(sr.HASH_MAX + 1)
    (proj / "edge.bin").write_bytes(b"\0" * 1000)
    with open(proj / "edge_max.bin", "wb") as fh:
        fh.truncate(sr.HASH_MAX)
    got = sr.file_meta([{"path": "big.bin"}, {"path": "edge.bin"}, {"path": "edge_max.bin"}], str(proj))
    assert got[0]["state"] == "ok" and got[0]["size"] == sr.HASH_MAX + 1
    assert "sha8" not in got[0] and "hash" not in got[0]
    assert len(got[1]["sha8"]) == 8 and len(got[2]["sha8"]) == 8    # HASH_MAX itself is still hashed


def test_hash_that_cannot_finish_times_out_within_the_budget(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "a.txt").write_text("a")
    release = threading.Event()

    def stuck(jobs, out):
        release.wait(10)
        for _key, fd in jobs:
            os.close(fd)
    monkeypatch.setattr(sr, "_hash_jobs", stuck)
    t0 = time.monotonic()
    try:
        got = sr.file_meta([{"path": "a.txt"}], str(proj), budget=0.3)
    finally:
        release.set()
    assert time.monotonic() - t0 < 1.5
    assert got[0]["state"] == "ok" and got[0]["size"] == 1 and got[0]["hash"] == "timeout" and "sha8" not in got[0]


def test_at_most_files_max_paths_are_looked_at(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    files = [{"path": "f%d.txt" % i} for i in range(sr.FILES_MAX + 3)]
    got = sr.file_meta(files, str(proj))
    assert [g["state"] for g in got[:sr.FILES_MAX]] == ["missing"] * sr.FILES_MAX
    assert [g["state"] for g in got[sr.FILES_MAX:]] == ["skipped"] * 3


# ================================================================ 12. hostile text
def hostile():
    return ("STATUS: done\nRESULT: " + "A" * 1_000_000 + "\x00NUL\x01\x02\x1b[31m\x7f\nFILES: none\n"
            "EVIDENCE: x\x00\nNEXT: none")


def test_hostile_text_in_process():
    text = hostile()
    p = sr.parse(text)
    score, hits = sr.blob_score(text)
    assert p["status"] == "done" and p["format"] == "status" and p["chars"] == len(text)
    assert {"control", "long_line", "base64_or_hex"} <= set(hits) and score == len(hits)
    chk = sr.check(p, "coder", text)
    assert "blob" in chk["hard"] and chk["blob"] == hits
    # only control characters: the one blob hit, the one hard violation
    small = "STATUS: done\nRESULT: ok\x00 \x1b[0m\nFILES: none\nEVIDENCE: x"
    chk = sr.check(sr.parse(small), "coder", small)
    assert chk["blob"] == ["control"] and chk["hard"] == ["blob"]
    assert sr.blob_score("STATUS: done\nRESULT: a\x00b")[1] == ["control"]          # a NUL alone is binary
    assert sr.blob_score("STATUS: done\r\nRESULT: tab\there\n")[1] == []             # CR, TAB, LF are text
    # a 1 MB line of NULs/controls does not crash anything else either
    sr.brief_stats("\x00" * 50000 + "\n" + "B" * 3_000_000)
    assert sr.parse("\x00\x00\x00")["format"] == "text"


def test_hostile_text_observe_never_outputs_and_copy_is_written(tmp_path):
    rig = Rig(tmp_path, STACK_REPORT_FORMAT="observe")
    rig.seed("hs1", "coder")
    text = hostile()
    r = rig.run(rig.stop("hs1", "coder", text))
    assert r.rc == 0 and r.stdout == "" and r.secs < 5
    (name,) = rig.copies()
    assert (rig.state / "reports" / name).stat().st_size >= 1_000_000
    (row,) = rig.rows()
    assert {"control", "long_line"} <= set(row["blob"]) and "blob" in row["hard"] and row["blocked"] is False
    assert row["report_chars"] == len(text) and row["report_tokens_est"] == math.ceil(len(text) / 3)
    assert rig.reg("hs1").get("stopped")


def test_hostile_text_in_compact_is_blocked_once_for_a_builder(rig):
    rig.seed("hs2", "coder")
    r = rig.run(rig.stop("hs2", "coder", hostile()))
    assert r.secs < 5 and blocked(r) and "pasted content" in r.json["reason"]
    assert "blob" in rig.reg("hs2")["report"]["hard"]
    r2 = rig.run(rig.stop("hs2", "coder", hostile()))
    assert r2.stdout == "" and rig.reg("hs2").get("stopped")


WS = " " * 200_000
BACKTRACK = {"purpose_sep": "STATUS: done\nRESULT: ok\nFILES:\n- a" + WS + "b\n",
             "paren": "STATUS: done\nRESULT: ok\nFILES:\n- a" + WS + "b)\n",
             "clean_line": "*" + WS + "x\nSTATUS: done\nRESULT: ok\n"}


@pytest.mark.parametrize("name", sorted(BACKTRACK))
def test_long_whitespace_runs_never_backtrack_past_the_hook_timeout(tmp_path, name):
    """A 200k-space run in a FILES line or the first line: the stop finishes in 10 s (the hook's own
    timeout is 15 s, and a killed hook never marks the agent stopped)."""
    rig = Rig(tmp_path, STACK_REPORT_FORMAT="observe")
    rig.seed("rx1", "coder")
    p = rig.popen(rig.stop("rx1", "coder", BACKTRACK[name]))
    try:
        rc = p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
        pytest.fail("SubagentStop still running after 10 s")
    finally:
        p.stdout.close()
        p.stderr.close()
    assert rc == 0 and rig.reg("rx1").get("stopped")


# ================================================================ 13. the brief
PROSE = ("lorem ipsum dolor sit amet, consectetur adipiscing elit sed do\n" * 100)[:5000]


def brief_run(tmp_path, mode, label=None, tid="toolu_b1", prompt=PROSE):
    knobs = {"STACK_REPORT_FORMAT": mode}
    if label:
        knobs["STACK_AGENT_LABEL"] = label
    rig = Rig(tmp_path, **knobs)
    return rig, rig.run(rig.pre_agent(tid, prompt))


def test_observe_brief_is_recorded_and_never_output(tmp_path):
    assert len(PROSE) == 5000
    rig, r = brief_run(tmp_path, "observe", label="off")
    assert r.rc == 0 and r.stdout == "", r.stderr
    rec = rig.ledger_rec("toolu_b1")
    assert rec["brief_chars"] == 5000 and rec["brief_user_chars"] == 0
    assert rec["brief_blob"] == [] and rec["brief_pasted"] is False
    # the default label rewrites the input but carries no brief warning
    (tmp_path / "two").mkdir()
    rig2, r2 = brief_run(tmp_path / "two", "observe")
    assert r2.rc == 0
    assert "additionalContext" not in (r2.json or {}).get("hookSpecificOutput", {})
    assert rig2.ledger_rec("toolu_b1")["brief_chars"] == 5000
    # unset STACK_REPORT_FORMAT is observe
    (tmp_path / "three").mkdir()
    rig3 = Rig(tmp_path / "three", STACK_AGENT_LABEL="off")
    assert rig3.run(rig3.pre_agent("toolu_b3", PROSE)).stdout == ""
    assert rig3.ledger_rec("toolu_b3")["brief_chars"] == 5000


def test_compact_brief_warning_reaches_the_caller(tmp_path):
    rig, r = brief_run(tmp_path, "compact", label="off")
    ctx = r.json["hookSpecificOutput"]["additionalContext"]
    assert "Brief check" in ctx and "5000 agent-written chars (cap 2000)" in ctx
    assert rig.ledger_rec("toolu_b1")["brief_chars"] == 5000
    # with the default label the warning rides on the rewritten input
    (tmp_path / "two").mkdir()
    rig2, r2 = brief_run(tmp_path / "two", "compact")
    assert "Brief check" in r2.json["hookSpecificOutput"]["additionalContext"]
    # a short brief: no warning even in compact; a USER: block is exempt from the size
    (tmp_path / "three").mkdir()
    _, r3 = brief_run(tmp_path / "three", "compact", label="off", prompt="GOAL: x\nUSER:\n" + PROSE)
    assert r3.stdout == ""


def test_mode_off_records_no_brief(tmp_path):
    rig, r = brief_run(tmp_path, "off", label="off")
    assert r.stdout == ""
    rec = rig.ledger_rec("toolu_b1")
    assert not [k for k in rec if k.startswith("brief_")]


def test_brief_stats_measures():
    s = sr.brief_stats("GOAL: x\n" + "y" * 100 + "\nUSER:\n" + "z" * 7000)
    assert s["brief_chars"] == len("GOAL: x\n" + "y" * 100 + "\n") and s["brief_user_chars"] == len("USER:\n" + "z" * 7000)
    assert s["brief_warn"] is None
    p = sr.brief_stats("see the report:\nSTATUS: done\nRESULT: x")
    assert p["brief_pasted"] is True and "a pasted report" in p["brief_warn"]
    b = sr.brief_stats("x\n```\n" + "line\n" * 20 + "```\n")
    assert b["brief_blob"] == ["fence"] and "pasted content (fence)" in b["brief_warn"]
    assert sr.brief_stats(None)["brief_chars"] == 0


# ================================================================ 14. observe: silent, recorded, no text in the row
SHAPES = ["compact_done", "failed_look", "partial", "blocked_ask", "old_comma", "fenced_whole", "done_drop_ref",
          "review_verdict", "clean_finish", "plain_text"]
SENTINEL = "ZEBRA-7f3a9c"


@pytest.mark.parametrize("name", SHAPES + ["empty_status", "bad_status"])
def test_observe_is_silent_and_records_without_report_text(tmp_path, name):
    rig = Rig(tmp_path, STACK_REPORT_FORMAT="observe")
    if name == "empty_status":
        text = "STATUS:\nRESULT: %s" % SENTINEL
    elif name == "bad_status":
        text = "STATUS: wat\nRESULT: %s" % SENTINEL
    else:
        text = fixture_text(name)
        text = text.replace("RESULT: ", "RESULT: %s " % SENTINEL, 1) if "RESULT: " in text else text + SENTINEL + "\n"
    rig.seed("ob1", "coder")
    r = rig.run(rig.stop("ob1", "coder", text))
    assert r.rc == 0 and r.stdout == "", r.stderr
    rec = rig.reg("ob1")
    assert rec.get("stopped")
    rep = rec["report"]
    (row,) = rig.rows()
    (copy,) = rig.copies()
    assert (rig.state / "reports" / copy).read_text() == text and rep["path"] == str(rig.state / "reports" / copy)
    assert copy == "ob1.%d.1.md" % int(STARTED)
    parsed = sr.parse(text)
    assert rep["status"] == parsed["status"] and rep["format"] == parsed["format"] and rep["mode"] == "observe"
    assert rep["blocked"] is False and rep["restated"] is False and rep["stops"] == 1
    # the usage row
    n = len(text)
    assert row["report_chars"] == n and row["report_tokens_est"] == math.ceil(n / 3)
    assert row["class"] == "builder" and row["mode"] == "observe" and row["status"] == parsed["status"]
    assert row["eflag"] == rep["eflag"] and row["restated"] is False and row["blocked"] is False
    assert row["blob"] == rep["blob"] and row["format"] == parsed["format"] and row["v"] == 1
    assert row["session"] == "s-s4test" and row["agent_id"] == "ob1" and row["run"] == str(STARTED)
    assert isinstance(row["missing"], int) and row["files"] == len(parsed["files"])
    if name in EXPECT:
        assert row["status"] == EXPECT[name]["status"]
        assert row["missing"] == sum(1 for d in EXPECT[name]["deleted"] if not d)
    # no report text anywhere in the row: not the sentinel, not any line of the reply
    raw = json.dumps(row, ensure_ascii=False)
    assert SENTINEL not in raw
    for line in text.splitlines():
        assert len(line.strip()) < 12 or line.strip() not in raw
    assert all(len(str(v)) < 300 for v in row.values())


def test_implied_eflag_and_class_in_the_row(tmp_path):
    rig = Rig(tmp_path, STACK_REPORT_FORMAT="observe")
    rig.seed("ob2", "scout")
    rig.run(rig.stop("ob2", "scout", "STATUS: partial\nRESULT: x\nEVIDENCE: y\nNEXT: z"))
    (row,) = rig.rows()
    assert row["class"] == "lookup" and row["status"] == "partial" and row["eflag"] == "look"
    assert row["soft"] == ["eflag_implied"] and row["hard"] == []


# ================================================================ 15. SubagentHandback
def transcript_with_last_tool(path, name):
    lines = [{"type": "user", "message": {"content": "go"}},
             {"type": "assistant", "message": {"content": [{"type": "text", "text": "t"},
                                                           {"type": "tool_use", "id": "tu1", "name": "Bash",
                                                            "input": {"command": "ls"}}]}},
             {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "tu2", "name": name,
                                                            "input": {"report": "STATUS: done"}}]}}]
    path.write_text("".join(json.dumps(x) + "\n" for x in lines))
    return str(path)


def test_subagent_handback_is_logged_not_blocked(rig, tmp_path):
    """A SubagentHandback whose input has no readable `message` keeps the common row (format handback)."""
    t = transcript_with_last_tool(tmp_path / "agent-hb1.jsonl", "SubagentHandback")
    rig.seed("hb1", "coder")
    r = rig.run(rig.stop("hb1", "coder", BAD, transcript=t))
    assert r.rc == 0 and r.stdout == ""
    (row,) = rig.rows()
    assert row["format"] == "handback" and row["via"] == "handback" and "blocked" not in row
    assert row["report_chars"] == len(BAD)
    assert rig.copies() == [] and "report" not in rig.reg("hb1") and rig.reg("hb1").get("stopped")
    # control: another last tool is checked as usual
    t2 = transcript_with_last_tool(tmp_path / "agent-hb2.jsonl", "Bash")
    rig.seed("hb2", "coder")
    assert blocked(rig.run(rig.stop("hb2", "coder", BAD, transcript=t2)))
    assert rig.rows()[-1]["via"] == "text"


# B1 (S4 L7): the hand-back message is the report: parsed, checked and recorded like a text reply, never blocked
HB_MSG = ("STATUS: partial · E:look\nRESULT: half of it\nFILES:\n- a.py — parser\n"
          "EVIDENCE: pytest -q → 1 failed\nNEXT: main-coder: finish b.py")


def handback_transcript(path, message, before=(), after=(), key="message"):
    """A subagent transcript: `before` records, an API call with text + a SubagentHandback tool_use (input
    {key: message}), its tool_result, then `after` records."""
    lines = list(before) + [
        {"type": "user", "message": {"content": "go"}},
        {"type": "assistant", "message": {"id": "m1", "content": [
            {"type": "tool_use", "id": "tu1", "name": "Bash", "input": {"command": "ls"}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "tu1"}]}},
        {"type": "assistant", "message": {"id": "m2", "content": [
            {"type": "text", "text": "Reporting."},
            {"type": "tool_use", "id": "tu2", "name": "SubagentHandback", "input": {key: message}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "tu2"}]}},
    ] + list(after)
    path.write_text("".join(json.dumps(x) + "\n" for x in lines))
    return str(path)


def test_handback_message_is_checked_and_recorded(tmp_path):
    rig = Rig(tmp_path, STACK_REPORT_FORMAT="observe")
    (rig.cwd / "a.py").write_text("x = 1\n")
    t = handback_transcript(tmp_path / "agent-hm1.jsonl", HB_MSG)
    rig.seed("hm1", "coder")
    r = rig.run(rig.stop("hm1", "coder", "Reporting.", transcript=t))
    assert r.rc == 0 and r.stdout == ""
    (row,) = rig.rows()
    parsed = sr.parse(HB_MSG)
    assert row["via"] == "handback" and row["format"] == "status" and row["status"] == "partial"
    assert row["eflag"] == "look" and row["class"] == "builder" and row["blocked"] is False
    assert row["report_chars"] == len(HB_MSG) and row["report_tokens_est"] == math.ceil(len(HB_MSG) / 3)
    assert row["counted_chars"] == sr.check(parsed, "coder", HB_MSG)["counted"]
    assert row["files"] == 1 and row["missing"] == 0 and row["hard"] == []
    raw = json.dumps(row, ensure_ascii=False)
    assert "half of it" not in raw and "finish b.py" not in raw            # no report text in the row
    rep = rig.reg("hm1")["report"]
    assert rep["via"] == "handback" and rep["status"] == "partial" and rep["blocked"] is False
    assert rep["files"][0]["state"] == "ok" and rig.reg("hm1").get("stopped")
    (name,) = rig.copies()
    assert (rig.state / "reports" / name).read_text() == HB_MSG
    assert stat.S_IMODE((rig.state / "reports" / name).stat().st_mode) == 0o600


def test_handback_is_never_blocked_even_in_compact(rig, tmp_path):
    t = handback_transcript(tmp_path / "agent-hm2.jsonl", BAD)
    rig.seed("hm2", "coder")
    for _ in range(2):
        r = rig.run(rig.stop("hm2", "coder", BAD, transcript=t))
        assert r.rc == 0 and r.stdout == ""
    rows = rig.rows()
    assert [x["hard"] for x in rows] == [["no_status"], ["no_status"]]
    assert all(x["via"] == "handback" and x["blocked"] is False and x["restated"] is False for x in rows)
    rep = rig.reg("hm2")["report"]
    assert rep["blocked"] is False and "restate_key" not in rep and rig.reg("hm2").get("stopped")


def test_handback_with_an_empty_reply_is_still_checked(rig, tmp_path):
    t = handback_transcript(tmp_path / "agent-hm3.jsonl", HB_MSG)
    rig.seed("hm3", "coder")
    r = rig.run(rig.stop("hm3", "coder", "", transcript=t))
    assert r.rc == 0 and r.stdout == ""
    (row,) = rig.rows()
    assert row["via"] == "handback" and row["status"] == "partial" and row["report_chars"] == len(HB_MSG)
    # no message and no reply: the common row only
    t2 = handback_transcript(tmp_path / "agent-hm4.jsonl", HB_MSG, key="report")
    rig.seed("hm4", "coder")
    assert rig.run(rig.stop("hm4", "coder", "", transcript=t2)).stdout == ""
    row = rig.rows()[-1]
    assert row["format"] == "handback" and row["report_chars"] == 0 and "status" not in row


def test_a_resumed_run_ending_in_text_is_no_handback(rig, tmp_path):
    """The newest assistant record decides: a resume that answers in plain text after an earlier run's
    SubagentHandback is checked as text (compact restates it), never as the old message."""
    after = [{"type": "user", "message": {"content": "one more thing"}},
             {"type": "assistant", "message": {"id": "m3", "content": [{"type": "text", "text": BAD}]}}]
    t = handback_transcript(tmp_path / "agent-hm5.jsonl", HB_MSG, after=after)
    rig.seed("hm5", "coder")
    assert blocked(rig.run(rig.stop("hm5", "coder", BAD, transcript=t)))
    (row,) = rig.rows()
    assert row["via"] == "text" and row["hard"] == ["no_status"] and row["report_chars"] == len(BAD)


def test_a_long_handback_is_still_a_handback(rig, tmp_path):
    """Review fix (security-auditor, code-reviewer): Claude Code stores a tool input twice per record
    (message.content and wireToolInputs), so a ~145k-char message makes a ~290 KiB record, past a 256 KiB
    tail; the hand-back reader's own tail (HANDBACK_TAIL_MAX) still sees it."""
    msg = "STATUS: done\nRESULT: ok\n" + "- row 0123456789\n" * 8500
    rec = {"type": "assistant", "message": {"id": "m2", "content": [
        {"type": "text", "text": "Reporting."},
        {"type": "tool_use", "id": "tu2", "name": "SubagentHandback", "input": {"message": msg}}]},
        "wireToolInputs": {"tu2": {"message": msg}}}
    t = tmp_path / "agent-hm7.jsonl"
    t.write_text(json.dumps(rec) + "\n" + json.dumps({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "tu2"}]}}) + "\n")
    assert t.stat().st_size > 256 << 10
    rig.seed("hm7", "coder")
    r = rig.run(rig.stop("hm7", "coder", "Reporting.", transcript=str(t)))
    assert r.rc == 0 and not blocked(r)
    row = rig.rows()[-1]
    assert row["via"] == "handback" and row["status"] == "done" and row["report_chars"] == len(msg)


@pytest.mark.parametrize("value", [None, 7, ["STATUS: done"], {"m": 1}])
def test_a_non_string_message_is_no_report(rig, tmp_path, value):
    t = handback_transcript(tmp_path / "agent-hm6.jsonl", value)
    rig.seed("hm6", "coder")
    assert rig.run(rig.stop("hm6", "coder", BAD, transcript=t)).stdout == ""
    (row,) = rig.rows()
    assert row["format"] == "handback" and "status" not in row and rig.copies() == []


def test_transcript_handback_reads_the_newest_assistant_record_only(tmp_path):
    p = tmp_path / "t.jsonl"
    assert sr.transcript_handback(handback_transcript(p, HB_MSG)) == HB_MSG
    assert sr.transcript_handback(handback_transcript(p, HB_MSG, key="report")) == ""
    assert sr.transcript_handback(handback_transcript(p, 5)) == ""
    after = [{"type": "assistant", "message": {"id": "m3", "content": [{"type": "text", "text": "later"}]}},
             {"type": "user", "message": {"content": "a user line naming \"assistant\" and SubagentHandback"}}]
    assert sr.transcript_handback(handback_transcript(p, HB_MSG, after=after)) is None
    # the hand-back after another tool_use in the same API call; a later system record is skipped
    rec = {"type": "assistant", "message": {"id": "m9", "content": [
        {"type": "tool_use", "id": "a", "name": "Read", "input": {}},
        {"type": "tool_use", "id": "b", "name": "SubagentHandback", "input": {"message": "STATUS: done"}}]}}
    p.write_text(json.dumps(rec) + "\n" + json.dumps({"type": "system", "content": "x"}) + "\n")
    assert sr.transcript_handback(str(p)) == "STATUS: done"
    big = handback_transcript(p, "STATUS: done\nRESULT: " + "y" * 600)
    assert sr.transcript_handback(big, cap=300) is None                     # the tail is all that is read
    assert sr.transcript_handback(str(tmp_path / "missing.jsonl")) is None
    assert sr.transcript_handback("relative.jsonl") is None and sr.transcript_handback(None) is None
    link = tmp_path / "link.jsonl"
    link.symlink_to(p)
    assert sr.transcript_handback(str(link)) is None                         # O_NOFOLLOW
    fifo = tmp_path / "fifo"
    os.mkfifo(str(fifo))
    got, done = bounded(lambda: sr.transcript_handback(str(fifo)))          # a FIFO with no writer: no hang
    assert done and got is None
    fd = os.open(str(fifo), os.O_RDWR | os.O_NONBLOCK)                       # a FIFO holding a hand-back: not read
    try:
        os.write(fd, (json.dumps(rec) + "\n").encode())
        got, done = bounded(lambda: sr.transcript_handback(str(fifo)))
        assert done and got is None
    finally:
        os.close(fd)


def test_transcript_tail_never_reads_a_device(monkeypatch):
    """A character device is opened but never read (S_ISREG first): /dev/zero would hand back 256 KiB."""
    reads, real = [], os.read
    monkeypatch.setattr(os, "read", lambda fd, n: reads.append(n) or real(fd, n))
    assert sr.transcript_handback("/dev/zero") is None
    assert reads == []


def test_no_dead_transcript_reader():
    """T15 review F4: report_stop reads transcript_handback only (S4 L7 B1); the older last-tool reader and its
    256 KiB tail had no caller left."""
    assert not hasattr(sr, "transcript_last_tool") and not hasattr(sr, "TAIL_MAX")


# ================================================================ 16. modes off and json
def test_mode_off_records_nothing_but_the_stop(tmp_path):
    rig = Rig(tmp_path, STACK_REPORT_FORMAT="off")
    rig.seed("of1", "coder")
    r = rig.run(rig.stop("of1", "coder", BAD))
    assert r.rc == 0 and r.stdout == ""
    assert "report" not in rig.reg("of1") and rig.reg("of1").get("stopped")
    assert rig.copies() == [] and rig.rows() == [] and not (rig.state / "reports").exists()


JSON_OK = json.dumps({"input": "do x", "timestamp": "2026-10-03 20:25", "agent": "coder", "status": "done",
                      "eflag": "", "result": "fine", "evidence": "pytest -q → 3 passed", "files": ["a.py"],
                      "next": ""})


def test_mode_json_checks_the_shape_and_never_blocks(tmp_path):
    rig = Rig(tmp_path, STACK_REPORT_FORMAT="json")
    rig.seed("js1", "coder")
    r = rig.run(rig.stop("js1", "coder", "text before\n" + JSON_OK))
    assert r.stdout == ""
    rep = rig.reg("js1")["report"]
    assert rep["format"] == "json" and rep["status"] == "done" and "json_shape" not in rep["soft"]
    assert rep["hard"] == [] and rep["mode"] == "json"
    assert [f["path"] for f in rig.reg("js1")["report"]["files"]] == ["a.py"]
    rig.seed("js2", "coder")
    r = rig.run(rig.stop("js2", "coder", BAD))
    assert r.rc == 0 and r.stdout == ""                           # a hard violation, but json never blocks
    rep = rig.reg("js2")["report"]
    assert "json_shape" in rep["soft"] and rep["hard"] == ["no_status"] and rep["blocked"] is False
    assert rig.reg("js2").get("stopped")
    rig.seed("js3", "coder")                                       # a STATUS block is not the JSON line
    rig.run(rig.stop("js3", "coder", GOOD))
    assert rig.reg("js3")["report"]["soft"] == ["json_shape"]
    rows = {r["agent_id"]: r for r in rig.rows()}
    assert rows["js1"]["format"] == "json" and "json_shape" in rows["js2"]["soft"]


def test_parse_json_shape_rules():
    assert sr.parse_json("no json here") is None
    assert sr.parse_json('{"status": "done"}') is None            # needs status and result
    p = sr.parse_json('{"status": "Failed", "result": "r", "eflag": "drop", "files": "a.py"}')
    assert (p["format"], p["status"], p["eflag"], [f["path"] for f in p["files"]]) == ("json", "failed", "drop",
                                                                                        ["a.py"])
    p = sr.parse_json('{"status": "maybe", "result": "r"}')
    assert p["status"] is None and p["status_raw"] == "maybe"
    assert sr.parse_json("{" * 100000) is None                   # deep nesting: no crash


# ================================================================ 17. PostToolUse(Agent) totals
def post_event(rig, tid, response):
    ev = rig.pre_agent(tid, "p")
    ev["hook_event_name"] = "PostToolUse"
    ev["tool_response"] = response
    return ev


def test_foreground_totals_land_in_the_ledger(tmp_path):
    rig = Rig(tmp_path, STACK_REPORT_FORMAT="observe")
    r = rig.run(post_event(rig, "toolu_fgd", {"status": "completed", "agentId": "fgd1", "totalDurationMs": 4210,
                                              "totalToolUseCount": 7, "totalTokens": 51234,
                                              "content": [{"type": "text", "text": "done"}]}))
    assert r.rc == 0, r.stderr
    rec = rig.ledger_rec("toolu_fgd")
    assert (rec["duration_ms"], rec["tool_uses"], rec["total_tokens"]) == (4210, 7, 51234)
    assert rec["status"] == "completed" and rec["child"] == "fgd1"
    r = rig.run(post_event(rig, "toolu_bgd", {"status": "async_launched", "agentId": "bgd1", "description": "x",
                                              "prompt": "x", "outputFile": "/x"}))
    rec = rig.ledger_rec("toolu_bgd")
    assert rec["status"] == "async_launched"
    assert not {"duration_ms", "tool_uses", "total_tokens"} & set(rec)


@pytest.fixture
def g_plain(monkeypatch):
    monkeypatch.setitem(sys.modules, "stack_report", sr)
    return load(GUARD, "s4_agent_guard_totals")


def test_agent_totals_accepts_only_sane_numbers(g_plain):
    t = g_plain.agent_totals
    full = {"totalDurationMs": 5, "totalToolUseCount": 2, "totalTokens": 9}
    want = {"duration_ms": 5, "tool_uses": 2, "total_tokens": 9}
    assert t({"tool_response": full}) == want
    assert t({"tool_response": json.dumps(full)}) == want
    assert t({"tool_response": [{"x": 1}, full]}) == want
    assert t({"tool_response": {"totalDurationMs": 5.9}}) == {"duration_ms": 5}
    assert t({"tool_response": {"status": "async_launched", "agentId": "a"}}) == {}
    assert t({"tool_response": {"totalDurationMs": True, "totalToolUseCount": -1, "totalTokens": 1e16}}) == {}
    assert t({"tool_response": {"totalDurationMs": "5"}}) == {} and t({"tool_response": "not json"}) == {}
    assert t({}) == {}


# ================================================================ 18. stack-tree
SID = "11111111-2222-3333-4444-555555555555"


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))


def say(mid, txt, t):
    return {"type": "assistant", "isSidechain": False, "timestamp": iso(t),
            "message": {"id": mid, "content": [{"type": "text", "text": txt}],
                        "usage": {"input_tokens": 1, "cache_creation_input_tokens": 1,
                                  "cache_read_input_tokens": 1, "output_tokens": 1}}}


class TreeFix(object):
    def __init__(self, tmp, sid=SID):
        self.tmp, self.sid = Path(tmp), sid
        self.state = self.tmp / "state" / "claude-agent-stack" / sid
        self.proj = self.tmp / "cfg" / "projects" / "-proj"
        (self.state / "spawns").mkdir(parents=True)
        (self.state / "agents").mkdir()
        self.proj.mkdir(parents=True)
        (self.tmp / "home").mkdir(exist_ok=True)
        self.t0 = time.time() - 3600

    def spawn(self, tid, by, typ, task, child=None, status="async_launched", ts=None):
        rec = {"tid": tid, "by": by, "by_type": None, "type": typ, "task": task, "name": None, "isolation": None,
               "ts": ts or self.t0, "status": status}
        if child:
            rec["child"] = child
        (self.state / "spawns" / (tid + ".json")).write_text(json.dumps(rec))

    def agent(self, aid, typ, parent="main", stopped=True, start=None, **kw):
        start = start or self.t0
        rec = dict({"id": aid, "type": typ, "parent": parent, "spawned": start, "started": start}, **kw)
        if stopped:
            rec["stopped"] = start + 60
        (self.state / "agents" / (aid + ".json")).write_text(json.dumps(rec))

    def transcript(self, lines, aid):
        p = self.proj / self.sid / "subagents" / ("agent-%s.jsonl" % aid)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join(json.dumps(x) + "\n" for x in lines))
        reg = self.state / "agents" / (aid + ".json")
        rec = json.loads(reg.read_text())
        rec["transcript"] = str(p)
        reg.write_text(json.dumps(rec))

    def run(self, *args, timeout=60):
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.tmp / "home"), "XDG_STATE_HOME": str(self.tmp / "state"),
               "CLAUDE_CONFIG_DIR": str(self.tmp / "cfg"), "COLUMNS": "400", "LANG": "en_US.UTF-8"}
        return subprocess.run([PY, "-B", str(TREE)] + list(args), capture_output=True, text=True, timeout=timeout,
                              env=env)


def flatten(n):
    yield n
    for c in n["children"]:
        for x in flatten(c):
            yield x


def test_registry_report_status_wins_over_the_transcript_scan(tmp_path):
    f = TreeFix(tmp_path)
    t = f.t0
    for i, (aid, rep) in enumerate((("W1", {"status": "failed", "eflag": "look"}),
                                    ("W2", {"status": "done", "eflag": "drop"}),
                                    ("W3", {"status": "wat"}), ("W4", None), ("W5", {"status": "partial"}))):
        f.spawn("t%d" % i, "main", "coder", aid, child=aid, ts=t + i)
        f.agent(aid, "coder", start=t + i, **({"report": rep} if rep else {}))
    # every transcript says something else
    f.transcript([say("m1", "STATUS: done\nRESULT: x", t + 5)], "W1")
    f.transcript([say("m2", "STATUS: failed · E:look\nRESULT: x", t + 5)], "W2")
    f.transcript([say("m3", "STATUS: blocked · E:drop", t + 5)], "W3")
    f.transcript([say("m4", "STATUS: partial · E:drop", t + 5)], "W4")
    f.transcript([say("m5", "STATUS: done · E:drop", t + 5)], "W5")
    nodes = {n["task"]: n for n in flatten(json.loads(f.run("--session", SID, "--json").stdout)["root"])}
    assert (nodes["W1"]["status"], nodes["W1"]["eflag"]) == ("failed", "look")          # the report wins
    assert (nodes["W2"]["status"], nodes["W2"]["eflag"]) == ("done", "drop")
    assert (nodes["W3"]["status"], nodes["W3"]["eflag"]) == ("blocked", "drop")         # unusable report: the scan, with its own flag
    assert (nodes["W4"]["status"], nodes["W4"]["eflag"]) == ("partial", "drop")          # no report: the scan
    assert (nodes["W5"]["status"], nodes["W5"]["eflag"]) == ("partial", None)            # the report's missing flag stays None
    # and in the text tree
    body = f.run("--session", SID).stdout
    assert 'coder · "W1" · failed' in body


def test_a_report_of_a_running_agent_does_not_change_its_state(tmp_path):
    f = TreeFix(tmp_path)
    f.spawn("t1", "main", "coder", "R1", child="R1")
    f.agent("R1", "coder", stopped=False, report={"status": "done"})
    n = {x["task"]: x for x in flatten(json.loads(f.run("--session", SID, "--json").stdout)["root"])}["R1"]
    assert n["status"] == "running"


def pending_session(tmp_path):
    f = TreeFix(tmp_path)
    t = f.t0
    plan = [  # task, ledger status, registry kwargs, stopped
        ("RUN", "async_launched", {}, False), ("FAIL", "failed", {}, False),
        ("BLOCKED", "async_launched", {"report": {"status": "blocked"}}, True),
        ("UNHANDLED", "async_launched", {"report": {"status": "done"}}, True),
        ("BLOCKED_HANDLED", "completed", {"report": {"status": "blocked"}}, True),
        ("FAILED_HANDLED", "completed", {"report": {"status": "failed", "handled": True}}, True),
        ("DONE_LEDGER", "completed", {}, True), ("DONE_REG", "async_launched", {"handled": True}, True),
        ("DONE_REP", "async_launched", {"report": {"status": "done", "handled": True}}, True),
        ("CANCELLED", "cancelled", {}, True), ("PARENT", "completed", {}, True)]
    for i, (task, led, kw, stopped) in enumerate(plan):
        f.spawn("t%d" % i, "main", "coder", task, child=task, status=led, ts=t + i)
        f.agent(task, "coder", stopped=stopped, start=t + i, **kw)
    f.spawn("tc", "PARENT", "coder", "KID", child="KID", ts=t + 20)
    f.agent("KID", "coder", parent="PARENT", stopped=False, start=t + 20)
    return f


def test_pending_keeps_agents_that_still_need_their_parent(tmp_path):
    f = pending_session(tmp_path)
    full = [n["task"] for n in flatten(json.loads(f.run("--session", SID, "--json").stdout)["root"])][1:]
    assert len(full) == 12
    out = f.run("--session", SID, "--json", "--pending")
    doc = json.loads(out.stdout)
    kept = [n["task"] for n in flatten(doc["root"])][1:]
    assert sorted(kept) == sorted(["RUN", "FAIL", "BLOCKED", "UNHANDLED", "BLOCKED_HANDLED", "FAILED_HANDLED", "PARENT",
                                  "KID"])                                         # PARENT: an ancestor
    paths = {n["task"]: n["path"] for n in flatten(doc["root"])}
    full_paths = {n["task"]: n["path"] for n in flatten(json.loads(f.run("--session", SID, "--json").stdout)["root"])}
    assert all(paths[k] == full_paths[k] for k in kept)                  # tree paths stay as they were
    text = f.run("--session", SID, "--pending").stdout
    assert " · --pending: 7 pending" in text.splitlines()[0]    # all kept but the ancestor PARENT
    for dropped in ("DONE_LEDGER", "DONE_REG", "DONE_REP", "CANCELLED"):
        assert dropped not in text
    for shown in ("RUN", "FAIL", "BLOCKED", "UNHANDLED", "BLOCKED_HANDLED", "FAILED_HANDLED", "PARENT", "KID"):
        assert '"%s"' % shown in text


def test_pending_with_nothing_pending(tmp_path):
    f = TreeFix(tmp_path)
    f.spawn("t1", "main", "coder", "ONLY", child="ONLY", status="completed")
    f.agent("ONLY", "coder")
    out = f.run("--session", SID, "--pending")
    assert out.returncode == 0 and "(no pending agent)" in out.stdout and "0 pending" in out.stdout


def test_pending_static_is_a_usage_error(tmp_path):
    f = TreeFix(tmp_path)
    p = f.run("--pending", "--static")
    assert p.returncode != 0
    assert "--pending needs a live session" in (p.stdout + p.stderr)
    assert "Traceback" not in p.stderr


# ================================================================ 19. stack_usage STATUS: failed
def u_call(mid, k, text):
    return {"type": "assistant", "requestId": "req_" + mid, "timestamp": time.strftime(
        "%Y-%m-%dT%H:%M:%S", time.gmtime(1790000000.0 + k)) + ".250Z", "uuid": "u" + mid,
        "message": {"id": "msg_" + mid, "model": "claude-test", "content": [{"type": "text", "text": text}],
                    "usage": {"input_tokens": 3, "output_tokens": 5, "cache_creation_input_tokens": 100,
                              "cache_read_input_tokens": 1000}}}


def u_user(text, k):
    return {"type": "user", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(1790000000.0 + k)) + ".250Z",
            "message": {"role": "user", "content": text}}


def test_stack_usage_maps_status_failed_to_code_1(tmp_path, monkeypatch):
    for k in [k for k in os.environ if k.startswith("STACK_")]:
        monkeypatch.delenv(k)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    sub = tmp_path / "projects" / "p" / SID / "subagents"
    sub.mkdir(parents=True)
    cases = {"fdone": "STATUS: done\nRESULT: x", "ffail": "STATUS: failed · E:look\nRESULT: x\nEVIDENCE: y\nNEXT: z",
             "fblock": "STATUS: blocked\nNEXT: ASK USER: q", "fpart": "STATUS: partial · E:look",
             "fwrap": fixture_text("fenced_whole")}
    for aid, txt in cases.items():
        (sub / ("agent-%s.jsonl" % aid)).write_text(
            "".join(json.dumps(x) + "\n" for x in (u_user("go", 0), u_call(aid, 1, txt))))
        (sub / ("agent-%s.meta.json" % aid)).write_text(json.dumps({"agentType": "coder", "description": "d"}))
    U.scan_once(SID, str(sub), final=True)
    rows = U.read_rows()
    got = {aid: rows[(SID, aid, 0)]["status_code"] for aid in cases}
    assert got == {"fdone": "0", "ffail": "1", "fblock": "2", "fpart": "1", "fwrap": "0"}
    assert U.STATUS_CODE == {"done": 0, "partial": 1, "failed": 1, "blocked": 2}
    assert U.STATUS_RE.search("STATUS: failed").group(1) == "failed"


# ================================================================ 20. whole-reply fence
def unwrapped(text):
    lines = text.rstrip("\n").split("\n")
    assert lines[0].startswith("```") and lines[-1].strip() == "```"
    return "\n".join(lines[1:-1]) + "\n"


def test_whole_reply_fence_parses_like_the_unwrapped_text():
    wrapped = fixture_text("fenced_whole")
    plain = unwrapped(wrapped)
    assert len(wrapped.split("\n")) - 2 > 15
    pw, pp = sr.parse(wrapped), sr.parse(plain)
    assert pw["wrapped"] is True and pp["wrapped"] is False
    for k in ("format", "status", "eflag", "files", "evidence", "next", "result"):
        assert pw[k] == pp[k], k
    assert pw["status"] == "done" and [f["path"] for f in pw["files"]] == ["src/alpha.py", "src/beta.py"]
    # a ~~~ fence, and text before the fence line's own indent
    tilde = wrapped.replace("```", "~~~")
    assert sr.parse(tilde)["wrapped"] is True and sr.parse(tilde)["status"] == "done"
    assert sr.parse("  " + wrapped.lstrip())["wrapped"] is True
    # blob_score on the wrapped text DOES see a fence over 15 lines; check() looks at the unwrapped text
    assert "fence" in sr.blob_score(wrapped)[1]
    chk = sr.check(pw, "coder", wrapped)
    assert "fence" not in chk["blob"] and chk["hard"] == []


def test_whole_reply_fence_is_not_blocked_in_compact_for_a_builder(rig):
    rig.seed("wf1", "coder")
    r = rig.run(rig.stop("wf1", "coder", fixture_text("fenced_whole")))
    assert r.stdout == ""
    rep = rig.reg("wf1")["report"]
    assert rep["hard"] == [] and "fence" not in rep["blob"] and rep["blocked"] is False and rep["status"] == "done"


def long_fence(n=20):
    return "```\n" + "".join("line %d\n" % i for i in range(n)) + "```\n"


def test_a_fence_over_15_lines_elsewhere_is_still_a_blob(rig):
    mid = "STATUS: done\nRESULT: see the output\n%sEVIDENCE: ran it\n" % long_fence()
    p = sr.parse(mid)
    assert p["wrapped"] is False
    chk = sr.check(p, "coder", mid)
    assert chk["blob"] == ["fence"] and "blob" in chk["hard"]
    # first line a fence, but no STATUS inside it: not a wrapped report
    first = long_fence() + "STATUS: done\nRESULT: x\nEVIDENCE: y\n"
    assert sr.parse(first)["wrapped"] is False and "fence" in sr.check(sr.parse(first), "coder", first)["blob"]
    # a short fence is no blob
    short = "STATUS: done\nRESULT: x\n```\na\nb\n```\nEVIDENCE: y\n"
    assert sr.check(sr.parse(short), "coder", short)["blob"] == []
    # an unclosed long fence counts too
    unclosed = "STATUS: done\nRESULT: x\n```\n" + "z\n" * 30
    assert sr.blob_score(unclosed)[1] == ["fence"]
    rig.seed("wf2", "coder")
    assert blocked(rig.run(rig.stop("wf2", "coder", mid)))
    assert rig.reg("wf2")["report"]["blob"] == ["fence"]


def test_fenced_example_status_does_not_become_the_report():
    text = "Here is the format:\n```\nSTATUS: failed\n```\nSTATUS: done\nRESULT: real\nEVIDENCE: x"
    p = sr.parse(text)
    assert p["status"] == "done" and p["result"] == "real"           # the first STATUS outside a fence counts
    only_fenced = sr.parse("Format:\n```\nSTATUS: partial\nRESULT: x\n```\nand more prose after")
    assert only_fenced["status"] == "partial"              # no STATUS outside a fence: the one inside is used


# ================================================================ guard self-test and defaults
def test_default_mode_is_observe_and_unknown_values_fall_back(g_plain, monkeypatch):
    monkeypatch.delenv("STACK_REPORT_FORMAT", raising=False)
    assert g_plain.report_mode() == "observe"
    for v, want in (("compact", "compact"), (" JSON ", "json"), ("off", "off"), ("bogus", "observe"), ("", "observe")):
        monkeypatch.setenv("STACK_REPORT_FORMAT", v)
        assert g_plain.report_mode() == want
