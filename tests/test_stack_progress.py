"""Brief budgets and the early-stop rule (S4 L5): dot-config/dot-claude/hooks/stack_progress.py and its replay,
tests/derive_early_stop.py.

Run: uv run --python 3.12 --with pytest pytest -q -p no:cacheprovider tests/test_stack_progress.py
Synthetic transcripts only; every state lives under tmp_path (XDG_STATE_HOME); STACK_ variables are
stripped. The CLI runs on /usr/bin/python3 (the hooks' interpreter).

Mutation seam (how the tests are proven on seeded bugs): L5_DOT names a copy of dot-config/dot-claude/ with one seeded
bug; unset, the real tree is used. Nothing else reads it.
"""
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
DOT = Path(os.environ.get("L5_DOT") or ROOT / "dot-config" / "dot-claude")
HOOKS = DOT / "hooks"
PY = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable
RUN = 1790000000.5                      # a registry `started` stamp
SINCE_TS = "2026-09-21T14:13:20.500Z"   # iso_stamp(RUN)
AFTER = "2026-09-21T14:14:00.000Z"
BEFORE = "2026-09-21T14:10:00.000Z"


def load(path, name):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    loader.exec_module(mod)
    return mod


sp = load(HOOKS / "stack_progress.py", "l5_stack_progress")


@pytest.fixture
def env(tmp_path, monkeypatch):
    for k in [k for k in os.environ if k.startswith("STACK_")]:
        monkeypatch.delenv(k)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    d = tmp_path / "st" / "claude-agent-stack" / "sess-1"
    d.mkdir(parents=True)
    return d


# ---------------------------------------------------------------- transcript records
def call(k, name="Bash", tool_input=None, ts=AFTER, tokens=1000, extra_uses=()):
    """An API call's assistant record with one tool_use (plus extra_uses: (name, input) pairs)."""
    uses = [{"type": "tool_use", "id": "t%d" % k, "name": name,
             "input": tool_input if tool_input is not None else {"command": "make test"}}]
    uses += [{"type": "tool_use", "id": "t%d.%d" % (k, j), "name": n, "input": i}
             for j, (n, i) in enumerate(extra_uses)]
    return {"type": "assistant", "timestamp": ts, "requestId": "r%d" % k,
            "message": {"id": "m%d" % k, "usage": {"input_tokens": tokens, "cache_read_input_tokens": 0},
                        "content": uses}}


def result(k, error=False, sub=None):
    tid = "t%d" % k if sub is None else "t%d.%d" % (k, sub)
    return {"type": "user", "timestamp": AFTER,
            "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "is_error": error}]}}


def text(k, body, ts=AFTER):
    return {"type": "assistant", "timestamp": ts, "requestId": "r%d" % k,
            "message": {"id": "m%d" % k, "usage": {"input_tokens": 10}, "content": [{"type": "text", "text": body}]}}


def brief(body, ts=AFTER):
    return {"type": "user", "timestamp": ts, "message": {"role": "user", "content": body}}


def rounds(st, seq, start=0):
    """Feed one round per entry: (name, input, error)."""
    for j, (name, inp, err) in enumerate(seq):
        sp.feed(st, call(start + j, name, inp))
        sp.feed(st, result(start + j, err))
    return start + len(seq)


def failing(n, start=0):
    return [("Bash", {"command": "make test %d" % (start + i)}, True) for i in range(n)]


def test_iso_stamp_matches_the_transcripts():
    assert sp.iso_stamp(RUN) == SINCE_TS


# ---------------------------------------------------------------- brief budget
@pytest.mark.parametrize("line,want", [
    ("budget: ~300 K tokens, ≤ 3 children", {"tokens": 300000, "calls": None}),     # delegation.md's form
    ("Budget: 2.5M tokens; 40 calls", {"tokens": 2500000, "calls": 40}),
    ("- **Budget**: 1,500,000 context tokens", {"tokens": 1500000, "calls": None}),
    ("  budget: 25 tool calls and 4M tok", {"tokens": 4000000, "calls": 25}),
    ("BUDGET: 60 turns", {"tokens": None, "calls": 60}),
    ("budget: 2B tokens", {"tokens": 2000000000, "calls": None}),
])
def test_parse_budget_forms(line, want):
    assert sp.parse_budget("Goal: fix it\n%s\nDone when: green\n" % line) == want


@pytest.mark.parametrize("body", [
    "Stay within the token budget: be brief.",          # not at the start of a line
    "budget: at most 6 searches/fetches",                # not this run's tokens or calls
    "budget: ~12 tokens",                                # below the sane range
    "budget: 99999 calls",                               # above it
    "Budgets are tracked elsewhere.",
    "",
])
def test_parse_budget_rejects(body):
    assert sp.parse_budget(body) is None


def test_parse_budget_first_usable_line_and_scan_window():
    assert sp.parse_budget("budget: 3 searches\nbudget: 900K tokens\n") == {"tokens": 900000, "calls": None}
    assert sp.parse_budget("x" * sp.BRIEF_SCAN + "\nbudget: 900K tokens\n") is None


# the brief and the run's own text are model-written: each parse must stay linear (security review: three
# patterns backtracked quadratically, 17-39 s per line, past the 15 s hook timeout, which lets the call through)
@pytest.mark.parametrize("body", ["budget: 1" + " " * 60000 + "x", "budget: " + "1" * 16000,
                                  "budget: " + "1" * 16000 + " calls", "budget: " + "1,000" * 12000,
                                  "budget: 1" + " " * 30000 + "k" + " " * 30000 + "x"])
def test_parse_budget_is_linear(body):
    t0 = time.perf_counter()
    sp.parse_budget("Goal: x\n" + body + "\n")
    assert time.perf_counter() - t0 < 0.5


@pytest.mark.parametrize("body", ["budget: " + "1" * 5000 + " calls", "budget: " + "9" * 400 + " tokens",
                                  "budget: 1,000,000,000,000,000 tokens", "budget: 1" + "0" * 16 + " tokens"])
def test_parse_budget_huge_numbers_are_no_budget(body):
    """Past int()'s 4300-digit limit or float's range: no budget, never an exception (the run's state would
    stop advancing at that line)."""
    assert sp.parse_budget(body + "\n") is None


# ---------------------------------------------------------------- classes
@pytest.mark.parametrize("cmd", [
    "git -C /repo commit -m 'x'", "cd r && git merge --ff-only b", "mkdir -p out", "echo x > notes.md",
    "cat a >> log.txt", "sed -i '' 's/a/b/' f", "uv add requests", "cp a b", "printf x | tee f",
])
def test_shell_writes(cmd):
    assert sp.classify("Bash", {"command": cmd}) == "write"


@pytest.mark.parametrize("cmd", [
    "pytest -q 2>&1 | tail -5", "ls > /dev/null", "git status --short", "git log --oneline -3",
    "grep -rn foo src", "python3 -c 'print(1)' 2>/dev/null", "cat a | head", "rg x &>/dev/null",
])
def test_shell_reads(cmd):
    assert sp.classify("Bash", {"command": cmd}) == "read"


@pytest.mark.parametrize("name,want", [("Edit", "write"), ("Write", "write"), ("NotebookEdit", "write"),
                                       ("Agent", "delegate"), ("SendMessage", "delegate"),
                                       ("SubagentHandback", "report"), ("Read", "read"), ("Grep", "read"),
                                       ("mcp__x__y", "read")])
def test_tool_classes(name, want):
    assert sp.classify(name, {}) == want


# ---------------------------------------------------------------- rounds
def test_round_closes_at_the_next_api_call_not_before():
    st = sp.new_state()
    sp.feed(st, call(0))
    sp.feed(st, result(0, True))
    assert st["win"] == [] and st["cur"] is not None
    thinking = {"type": "assistant", "timestamp": AFTER, "requestId": "r1",
                "message": {"id": "m1", "content": [{"type": "thinking", "thinking": ""}]}}
    assert sp.feed(st, thinking) is True
    assert st["win"] == [[0, 1]]
    sp.feed(st, call(1))                       # same message id: the same round, no second close
    assert len(st["win"]) == 1


def test_parallel_calls_are_one_round():
    st = sp.new_state()
    sp.feed(st, call(0, "Read", {"file_path": "a"}, extra_uses=[("Edit", {"file_path": "a"})]))
    sp.feed(st, result(0))
    sp.feed(st, result(0, sub=0))
    sp.feed(st, call(1))
    assert st["win"] == [[1, 0]] and st["nround"] == 1 and st["nwork"] == 1


def test_failing_and_progress_flags():
    st = sp.new_state()
    n = rounds(st, [("Edit", {"file_path": "a"}, True),            # a failed edit: failing, no progress
                    ("Edit", {"file_path": "b"}, False),           # progress
                    ("Read", {"file_path": "a"}, False),           # neither
                    ("Read", {"file_path": "a"}, False),           # a pure repeat: failing
                    ("SubagentHandback", {"message": "x"}, False)])  # report: progress, not work
    sp.feed(st, call(n))
    assert st["win"] == [[0, 1], [1, 0], [0, 0], [0, 1], [1, 0]]
    assert st["nwork"] == 1


def test_partial_repeat_is_not_failing():
    st = sp.new_state()
    sp.feed(st, call(0, "Read", {"file_path": "a"}))
    sp.feed(st, result(0))
    sp.feed(st, call(1, "Read", {"file_path": "a"}, extra_uses=[("Read", {"file_path": "b"})]))
    sp.feed(st, result(1))
    sp.feed(st, result(1, sub=0))
    sp.feed(st, call(2))
    assert st["win"][-1] == [0, 0]


def test_usage_dedup_and_earlier_run_records():
    st = sp.new_state(RUN)
    rec = call(0, ts=BEFORE)
    sp.feed(st, rec, SINCE_TS)                 # an earlier run's call: not counted, no round
    assert (st["calls"], st["ctx"], st["cur"]) == (0, 0, None)
    sp.feed(st, call(1, tokens=500), SINCE_TS)
    sp.feed(st, call(1, tokens=500), SINCE_TS)  # the same call's next content line
    assert (st["calls"], st["ctx"]) == (1, 500)


def test_budget_is_fixed_by_the_first_call():
    st = sp.new_state()
    sp.feed(st, brief("Goal: x\nbudget: 400K tokens\n"))
    sp.feed(st, call(0))
    sp.feed(st, brief("<task-notification>\nbudget: 9 calls"))  # mid-run text: no new budget
    sp.feed(st, call(1))
    assert st["budget"] == {"tokens": 400000, "calls": None}
    early = sp.new_state(RUN)
    sp.feed(early, brief("budget: 20 calls", ts=BEFORE), SINCE_TS)   # a resume message stamped early
    sp.feed(early, call(0), SINCE_TS)
    assert early["budget"] == {"tokens": None, "calls": 20}


def test_final_status_is_tracked():
    st = sp.new_state()
    sp.feed(st, text(0, "work"))
    assert st["status"] == "clean" and st["ended"] is True
    sp.feed(st, text(1, "STATUS: partial\nRESULT: x"))
    assert st["status"] == "partial"


@pytest.mark.parametrize("body,want", [("**STATUS:** done", "done"), ("STATUS: **partial**", "partial"),
                                       ("> STATUS:  `blocked`", "blocked"), ("STATUS: *_ failed", "failed"),
                                       ("STATUS: ** ** done", "clean"), ("STATUSES: done", "clean")])
def test_status_forms(body, want):
    st = sp.new_state()
    sp.feed(st, text(0, body))
    assert st["status"] == want


@pytest.mark.parametrize("body", ["STATUS:" + " " * 60000 + "x", "STATUS:" + " " * 30000 + "*" + " " * 30000 + "x"])
def test_status_scan_is_linear(body):
    st = sp.new_state()
    t0 = time.perf_counter()
    sp.feed(st, text(0, body))
    assert time.perf_counter() - t0 < 0.5 and st["status"] == "clean"


# ---------------------------------------------------------------- the rule
def stalled_state(n_fail=8, budget=None):
    st = sp.new_state()
    if budget:
        sp.feed(st, brief("budget: %s" % budget))
    k = rounds(st, failing(n_fail))
    sp.feed(st, call(k))
    return st


def test_stall_needs_a_full_window_and_enough_failures():
    assert sp.stalled(stalled_state(7), 8, 4) == (False, 7)
    assert sp.stalled(stalled_state(8), 8, 4) == (True, 8)
    st = sp.new_state()
    k = rounds(st, failing(3) + [("Read", {"file_path": str(i)}, False) for i in range(5)])
    sp.feed(st, call(k))
    assert sp.stalled(st, 8, 4) == (False, 3)
    assert sp.stalled(st, 8, 3) == (True, 3)
    assert sp.stalled(st, 8, 0) == (True, 3)


def test_progress_in_the_window_blocks_the_stall():
    st = sp.new_state()
    k = rounds(st, failing(4) + [("Write", {"file_path": "x"}, False)] + failing(3, 10))
    sp.feed(st, call(k))
    assert sp.stalled(st, 8, 4)[0] is False


def test_stop_needs_the_budget_and_fires_once():
    st = stalled_state()
    assert [s for s, _b, _n in sp.evaluate(st, 10, 9, 1000)] == ["stall"]        # under the soft gate
    assert [s for s, _b, _n in sp.evaluate(st, 1000, 9, 1000)] == ["stop"]       # at it
    assert sp.evaluate(st, 10 ** 6, 10, 1000) == []


def test_no_gate_no_stop():
    st = stalled_state()                    # an orchestrator: no brief budget, no soft limit
    assert [s for s, _b, _n in sp.evaluate(st, 10 ** 12, 999, None)] == ["stall"]


def test_brief_budget_signal_and_gate():
    st = stalled_state(budget="30 calls")
    out = sp.evaluate(st, 1, 30, 10 ** 12)    # the brief's calls budget wins over the soft default
    assert [s for s, _b, _n in out] == ["budget", "stall", "stop"]
    assert out[0][1]["src"] == "brief" and out[0][1]["calls"] == 30
    st = stalled_state(budget="5M tokens")
    assert [s for s, _b, _n in sp.evaluate(st, 4999999, 2, 1)] == ["stall"]
    assert [s for s, _b, _n in sp.evaluate(st, 5000000, 3, 1)] == ["budget", "stop"]


def test_recovered_counts_work_not_the_report():
    st = stalled_state()
    sp.evaluate(st, 0, 9, None)
    k = rounds(st, [("SubagentHandback", {"message": "STATUS: partial"}, False)], 100)
    sp.feed(st, call(k))
    assert sp.evaluate(st, 0, 10, None) == []
    k = rounds(st, [("Edit", {"file_path": "fix"}, False)], 200)
    sp.feed(st, call(k))
    assert [s for s, _b, _n in sp.evaluate(st, 0, 11, None)] == ["recovered", "first_write"]


# ---------------------------------------------------------------- B3 (S4 L7): calls before the first write
def signals(st, calls=1):
    return [s for s, _b, _n in sp.evaluate(st, 0, calls, None)]


def test_first_write_is_the_index_of_the_api_call_that_first_writes():
    st = sp.new_state()
    k = rounds(st, [("Read", {"file_path": "a"}, False), ("Grep", {"pattern": "x"}, False),
                    ("Bash", {"command": "git -C /r commit -m x"}, False),       # a shell write: not counted
                    ("Bash", {"command": "mkdir -p .claude-work/x"}, False),
                    ("SubagentHandback", {"message": "STATUS: partial"}, False),  # a report: not counted
                    ("TaskStop", {"task_id": "t"}, False)])
    assert st["first_write"] is None and signals(st, k) == []
    k = rounds(st, [("Edit", {"file_path": "a"}, True)], k)                     # an attempt counts, failed or not
    assert st["first_write"] == 7 and st["calls"] == 7
    assert signals(st, k) == ["first_write"] and signals(st, k) == []          # once per run
    rounds(st, [("Write", {"file_path": "b"}, False), ("Agent", {"prompt": "p"}, False)], k)
    assert st["first_write"] == 7 and signals(st, k + 2) == []


@pytest.mark.parametrize("name", ["Edit", "Write", "NotebookEdit", "MultiEdit", "Agent", "Task", "SendMessage"])
def test_first_write_tools(name):
    st = sp.new_state()
    rounds(st, [("Read", {"file_path": "a"}, False), (name, {"x": 1}, False)])
    assert st["first_write"] == 2


def test_first_write_in_a_parallel_round_and_a_split_record():
    st = sp.new_state()
    sp.feed(st, call(0, "Read", {"file_path": "a"}, extra_uses=[("Edit", {"file_path": "a"})]))
    assert st["first_write"] == 1
    st = sp.new_state()                                     # one API call written as two records (text, tool_use)
    sp.feed(st, text(0, "looking"))
    sp.feed(st, text(1, "planning"))
    rec = call(1, "Write", {"file_path": "b"})
    sp.feed(st, rec)
    assert st["calls"] == 2 and st["first_write"] == 2


def test_first_write_ignores_an_earlier_run():
    st = sp.new_state(RUN)
    sp.feed(st, call(0, "Edit", {"file_path": "old"}, ts=BEFORE), SINCE_TS)
    assert st["first_write"] is None and st["calls"] == 0
    sp.feed(st, call(1, "Read", {"file_path": "a"}), SINCE_TS)
    sp.feed(st, call(2, "Edit", {"file_path": "a"}), SINCE_TS)
    assert st["first_write"] == 2


def test_params_knobs(monkeypatch):
    for k in ("STACK_EARLY_STOP_ROUNDS", "STACK_EARLY_STOP_FAILS"):
        monkeypatch.delenv(k, raising=False)
    assert sp.params() == (sp.ROUNDS, sp.FAILS)
    monkeypatch.setenv("STACK_EARLY_STOP_ROUNDS", "5")
    monkeypatch.setenv("STACK_EARLY_STOP_FAILS", "9")       # above rounds: the default, capped at rounds
    assert sp.params() == (5, min(sp.FAILS, 5))
    monkeypatch.setenv("STACK_EARLY_STOP_ROUNDS", "2")      # below the range
    monkeypatch.setenv("STACK_EARLY_STOP_FAILS", "x")
    assert sp.params() == (sp.ROUNDS, sp.FAILS)


@pytest.mark.parametrize("val,want", [("", "observe"), ("warn", "warn"), ("OFF", "off"), ("enforce", "observe")])
def test_mode(monkeypatch, val, want):
    monkeypatch.setenv("STACK_EARLY_STOP", val)
    assert sp.mode() == want


def test_policy_off_is_off(monkeypatch):
    monkeypatch.setenv("STACK_EARLY_STOP", "warn")
    monkeypatch.setenv("STACK_POLICY", "off")
    assert sp.mode() == "off"


# ---------------------------------------------------------------- check(): the hook side
def write_lines(path, recs, mode="a"):
    with open(path, mode) as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")


def stall_transcript(path, n=9, budget=None):
    recs = [brief("Goal: x\n" + ("budget: %s\n" % budget if budget else ""))]
    for k in range(n):
        recs += [call(k, "Bash", {"command": "make t%d" % k}), result(k, True)]
    recs.append(call(n))
    write_lines(path, recs, "w")


def log_rows(d):
    p = d / sp.LOG
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def test_check_observe_logs_and_says_nothing(env, tmp_path):
    t = tmp_path / "agent-a1.jsonl"
    stall_transcript(t)
    assert sp.check(str(env), "a1", "coder", str(t), RUN, 5000, 10, default_tokens=4000) is None
    rows = log_rows(env)
    assert [r["signal"] for r in rows] == ["stall", "stop"]
    allowed = {"v", "ts", "agent_id", "type", "run", "signal", "mode", "calls", "ctx", "budget_tokens",
               "budget_calls", "src", "rounds", "fails"}
    assert all(set(r) == allowed for r in rows)                 # numbers and ids only
    assert rows[1]["src"] == "soft" and rows[1]["budget_tokens"] == 4000 and rows[1]["mode"] == "observe"
    assert stat.S_IMODE(os.stat(env / sp.LOG).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(env / sp.STATE_DIR / "a1.json").st_mode) == 0o600
    assert sp.check(str(env), "a1", "coder", str(t), RUN, 6000, 11, default_tokens=4000) is None
    assert len(log_rows(env)) == 2                              # once per run


def test_check_warn_returns_the_notes(env, tmp_path, monkeypatch):
    monkeypatch.setenv("STACK_EARLY_STOP", "warn")
    t = tmp_path / "agent-a2.jsonl"
    stall_transcript(t, budget="9 calls")
    note = sp.check(str(env), "a2", "coder", str(t), RUN, 50, 10, default_tokens=None)
    assert note.startswith("Brief budget reached") and "Early-stop check" in note
    assert "9 API calls" in note and "blocks no tool" in note


def test_check_off_touches_nothing(env, tmp_path, monkeypatch):
    monkeypatch.setenv("STACK_EARLY_STOP", "off")
    t = tmp_path / "agent-a3.jsonl"
    stall_transcript(t)
    assert sp.check(str(env), "a3", "coder", str(t), RUN, 5000, 10, default_tokens=1) is None
    assert not (env / sp.STATE_DIR).exists() and not (env / sp.LOG).exists()


def test_check_rejects_bad_ids(env, tmp_path):
    t = tmp_path / "x.jsonl"
    stall_transcript(t)
    for aid in ("../evil", "", None, "a/b"):
        assert sp.check(str(env), aid, "coder", str(t), RUN, 5000, 10, default_tokens=1) is None
    assert not (env / sp.STATE_DIR).exists()


def test_check_is_incremental_and_waits_for_whole_lines(env, tmp_path):
    t = tmp_path / "agent-a4.jsonl"
    stall_transcript(t, n=4)
    sp.check(str(env), "a4", "coder", str(t), RUN, 5000, 5, default_tokens=1)
    st = json.loads((env / sp.STATE_DIR / "a4.json").read_text())
    assert st["off"] == t.stat().st_size and len(st["win"]) == 4
    with open(t, "a") as f:
        f.write(json.dumps(result(4, True)) + "\n" + json.dumps(call(5))[:-5])      # a half-written line
    sp.check(str(env), "a4", "coder", str(t), RUN, 5000, 6, default_tokens=1)
    st = json.loads((env / sp.STATE_DIR / "a4.json").read_text())
    assert st["off"] < t.stat().st_size and len(st["win"]) == 4                  # round 4 still open
    with open(t, "a") as f:
        f.write(json.dumps(call(5))[-5:] + "\n")
    sp.check(str(env), "a4", "coder", str(t), RUN, 5000, 6, default_tokens=1)
    st = json.loads((env / sp.STATE_DIR / "a4.json").read_text())
    assert st["off"] == t.stat().st_size and len(st["win"]) == 5


def test_a_new_run_starts_a_new_window(env, tmp_path):
    t = tmp_path / "agent-a5.jsonl"
    stall_transcript(t)
    sp.check(str(env), "a5", "coder", str(t), RUN, 5000, 10, default_tokens=1)
    write_lines(t, [brief("follow-up"), call(50, ts="2026-09-21T14:30:00.000Z")])
    sp.check(str(env), "a5", "coder", str(t), RUN + 600, 10, 1, default_tokens=1)
    st = json.loads((env / sp.STATE_DIR / "a5.json").read_text())
    assert st["run"] == RUN + 600 and st["win"] == [] and st["fired"] == {}
    assert len(log_rows(env)) == 2


def test_a_replaced_transcript_resumes_at_its_end(env, tmp_path):
    t = tmp_path / "agent-a6.jsonl"
    stall_transcript(t, n=3)
    sp.check(str(env), "a6", "coder", str(t), RUN, 1, 1, default_tokens=None)
    t.unlink()
    stall_transcript(t, n=9)                                  # a new inode, longer
    sp.check(str(env), "a6", "coder", str(t), RUN, 1, 1, default_tokens=None)
    st = json.loads((env / sp.STATE_DIR / "a6.json").read_text())
    assert st["off"] == t.stat().st_size and len(st["win"]) == 3


def test_a_busy_lock_skips_the_call(env, tmp_path):
    import fcntl
    t = tmp_path / "agent-a7.jsonl"
    stall_transcript(t)
    (env / sp.STATE_DIR).mkdir()
    fd = os.open(str(env / sp.STATE_DIR / "a7.lock"), os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        assert sp.check(str(env), "a7", "coder", str(t), RUN, 5000, 10, default_tokens=1, how="warn") is None
        assert not (env / sp.STATE_DIR / "a7.json").exists()
    finally:
        os.close(fd)
    assert sp.check(str(env), "a7", "coder", str(t), RUN, 5000, 10, default_tokens=1, how="warn")


def test_a_damaged_state_is_rebuilt(env, tmp_path):
    t = tmp_path / "agent-a8.jsonl"
    stall_transcript(t)
    (env / sp.STATE_DIR).mkdir()
    (env / sp.STATE_DIR / "a8.json").write_text("{not json")
    sp.check(str(env), "a8", "coder", str(t), RUN, 5000, 10, default_tokens=1)
    assert [r["signal"] for r in log_rows(env)] == ["stall", "stop"]


def test_the_log_stops_at_its_cap(env, tmp_path, monkeypatch):
    monkeypatch.setattr(sp, "LOG_MAX", 10)
    (env / sp.LOG).write_text("x" * 11)
    t = tmp_path / "agent-a9.jsonl"
    stall_transcript(t)
    sp.check(str(env), "a9", "coder", str(t), RUN, 5000, 10, default_tokens=1)
    assert (env / sp.LOG).read_text() == "x" * 11


def write_transcript(path, n_reads):
    recs = [brief("Goal: x")]
    for k in range(n_reads):
        recs += [call(k, "Read", {"file_path": "f%d" % k}), result(k)]
    recs += [call(n_reads, "Edit", {"file_path": "f"}), result(n_reads), call(n_reads + 1)]
    write_lines(path, recs, "w")


@pytest.mark.parametrize("how", ["observe", "warn"])
def test_check_logs_the_first_write_once_and_says_nothing(env, tmp_path, monkeypatch, how):
    monkeypatch.setenv("STACK_EARLY_STOP", how)
    t = tmp_path / "agent-w1.jsonl"
    write_transcript(t, 5)
    assert sp.check(str(env), "w1", "coder", str(t), RUN, 50, 7, default_tokens=None) is None
    (row,) = log_rows(env)
    assert row["signal"] == "first_write" and row["at_call"] == 6 and row["calls"] == 7
    assert row["mode"] == how and row["type"] == "coder" and row["run"] == RUN
    assert set(row) == {"v", "ts", "agent_id", "type", "run", "signal", "mode", "calls", "ctx", "budget_tokens",
                        "budget_calls", "src", "rounds", "fails", "at_call"}
    write_lines(t, [call(9, "Write", {"file_path": "g"})])
    assert sp.check(str(env), "w1", "coder", str(t), RUN, 60, 8, default_tokens=None) is None
    assert len(log_rows(env)) == 1                                              # once per run
    write_lines(t, [brief("follow-up"), call(20, "Read", ts="2026-09-21T14:30:00.000Z"),
                    call(21, "Edit", {"file_path": "h"}, ts="2026-09-21T14:30:01.000Z")])
    sp.check(str(env), "w1", "coder", str(t), RUN + 600, 70, 2, default_tokens=None)
    rows = log_rows(env)                                                        # a resume is a new run
    assert len(rows) == 2 and rows[1]["at_call"] == 2 and rows[1]["run"] == RUN + 600


# ---------------------------------------------------------------- report and CLI
def test_report_joins_the_hand_back_status(env, tmp_path):
    t = tmp_path / "agent-b1.jsonl"
    stall_transcript(t)
    sp.check(str(env), "b1", "coder", str(t), RUN, 5000, 10, default_tokens=1)
    usage = env.parent / "usage"
    usage.mkdir()
    write_lines(usage / "reports.jsonl", [{"session": "sess-1", "agent_id": "b1", "run": str(RUN),
                                           "status": "partial"}], "w")
    r = sp.report()
    assert r["sessions"] == 1 and r["signals"] == {"stall": {"partial": 1}, "stop": {"partial": 1}}
    assert r["types"] == {"coder": {"stall": 1, "stop": 1}}
    assert sp.report("other")["signals"] == {}


def test_report_sums_up_the_first_write_by_outcome(env, tmp_path):
    reps = []
    for j, (n, status) in enumerate([(1, "done"), (3, "done"), (9, "done"), (4, "partial")]):
        t = tmp_path / ("agent-f%d.jsonl" % j)
        write_transcript(t, n)
        sp.check(str(env), "f%d" % j, "coder", str(t), RUN, 10, n + 2, default_tokens=None)
        reps.append({"session": "sess-1", "agent_id": "f%d" % j, "run": str(RUN), "status": status})
    (env.parent / "usage").mkdir()
    write_lines(env.parent / "usage" / "reports.jsonl", reps, "w")
    r = sp.report()
    assert r["signals"] == {"first_write": {"done": 3, "partial": 1}}
    assert r["first_write"] == {"done": {"n": 3, "median": 4, "p90": 10},
                                "partial": {"n": 1, "median": 5, "p90": 5}}


def test_cli_self_test_and_report(env):
    e = dict(os.environ, XDG_STATE_HOME=str(env.parent.parent))
    p = subprocess.run([PY, "-B", str(HOOKS / "stack_progress.py"), "--self-test"], capture_output=True,
                       text=True, env=e)
    assert p.returncode == 0 and p.stdout.strip() == "stack_progress self-test: ok", p.stderr
    p = subprocess.run([PY, "-B", str(HOOKS / "stack_progress.py"), "report", "--json"], capture_output=True,
                       text=True, env=e)
    assert p.returncode == 0 and json.loads(p.stdout)["sessions"] == 0
    p = subprocess.run([PY, "-B", str(HOOKS / "stack_progress.py")], capture_output=True, text=True, env=e)
    assert p.returncode == 2


# ---------------------------------------------------------------- the replay (calibration script)
def test_replay_routes_agree_on_a_synthetic_root(tmp_path):
    sub = tmp_path / "root" / "-proj" / "s-1" / "subagents"
    sub.mkdir(parents=True)
    stall_transcript(sub / "agent-c1.jsonl", n=12)
    write_lines(sub / "agent-c1.jsonl", [result(12, True), text(13, "STATUS: partial\nRESULT: stuck")])
    (sub / "agent-c1.meta.json").write_text(json.dumps({"agentType": "coder"}))
    recs = [brief("Goal: y")]
    for k in range(10):
        recs += [call(k, "Edit", {"file_path": "f%d" % k}), result(k)]
    recs.append(text(10, "done, all green"))
    write_lines(sub / "agent-c2.jsonl", recs, "w")
    (sub / "agent-c2.meta.json").write_text(json.dumps({"agentType": "coder"}))
    out = tmp_path / "out"
    p = subprocess.run([PY, "-B", str(ROOT / "tests" / "derive_early_stop.py"), "--root", str(tmp_path / "root"),
                        "--out", str(out)], capture_output=True, text=True,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    assert p.returncode == 0, p.stderr
    s = json.loads((out / "summary.json").read_text())
    assert s["runs"] == 2 and s["outcomes"] == {"partial": 1, "clean": 1} and s["routes_agree"] is True
    assert s["shipped"]["stall"] == {"fired": 1, "success": 0, "other": 1}
    assert s["shipped"]["first_write"] == {"fired": 1, "success": 1, "other": 0}     # c2's Edit, c1 never writes
    grid = (out / "grid.csv").read_text().splitlines()
    assert grid[0].startswith("rounds,fails,gate,progress,runs,fired")


# ---------------------------------------------------------------- through agent_guard (the budget gate)
GUARD = HOOKS / "agent_guard.py"


def test_the_budget_gate_calls_the_check():
    """The guard tests below must not pass vacuously: budget_gate calls progress_check."""
    src = GUARD.read_text()
    body = re.search(r"(?ms)^def budget_gate\(.*?(?=^def )", src)
    assert "def progress_check(" in src and body and "progress_check(" in body.group(0)


def guard_session(tmp_path, how, extra=None, hooks=HOOKS, agent="A1", budget="5 calls", n=9,
                  strip_ids=False):
    """SessionStart, SubagentStart of a coder, its transcript (a brief with `budget`, n failing Bash
    rounds and an open one), then the `budget` PreToolUse hook of its next call (of the main thread
    when agent is None). (output, early-stop rows, session state dir, stderr)."""
    sid = "s-" + uuid.uuid4().hex[:12]
    proj = tmp_path / "projects" / "p"
    subs = proj / sid / "subagents"
    subs.mkdir(parents=True)
    main = proj / (sid + ".jsonl")
    main.write_text(json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("STACK_", "BLACKCAT_", "CLAUDE_"))}
    env.update(XDG_STATE_HOME=str(tmp_path / "xdg"), STACK_USAGE_COLLECT="0",
               CLAUDE_CONFIG_DIR=str(tmp_path / "cfg"), STACK_EARLY_STOP=how, **(extra or {}))

    def hook(ev, *args):
        base = {"session_id": sid, "transcript_path": str(main), "cwd": str(tmp_path)}
        p = subprocess.run([PY, "-B", str(hooks / "agent_guard.py"), *args],
                           input=json.dumps(dict(base, **ev)), capture_output=True, text=True, env=env,
                           timeout=60)
        assert p.returncode == 0, p.stderr
        return (json.loads(p.stdout) if p.stdout.strip() else {}), p.stderr

    hook({"hook_event_name": "SessionStart", "source": "startup"})
    ev = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_use_id": "tu-1", "prompt_id": "p1",
          "tool_input": {"command": "make t%d" % n}}
    if agent:
        hook({"hook_event_name": "SubagentStart", "agent_id": agent, "agent_type": "coder"})
        time.sleep(0.01)
        now = time.strftime("%Y-%m-%dT%H:%M:%S.999Z", time.gmtime(time.time() + 1))
        recs = [brief("Goal: x\n" + ("budget: %s\n" % budget if budget else ""), ts=now)]
        for k in range(n):
            recs += [call(k, "Bash", {"command": "make t%d" % k}, ts=now), result(k, True)]
        recs.append(call(n, ts=now))
        if strip_ids:   # the gate then keys calls by uuid (scan_transcript), stack_progress's own count by id
            for j, r in enumerate(recs):
                if r["type"] == "assistant":
                    r.pop("requestId")
                    r["message"].pop("id")
                    r["uuid"] = "u%d" % j
        write_lines(subs / ("agent-%s.jsonl" % agent), recs, "w")
        ev.update(agent_id=agent, agent_type="coder")
    o, err = hook(ev, "budget")
    d = tmp_path / "xdg" / "claude-agent-stack" / sid
    return o, log_rows(d), d, err


def decision(o):
    return (o.get("hookSpecificOutput") or {}).get("permissionDecision")


@pytest.mark.parametrize("how", ["observe", "warn", "off", "enforce"])
def test_budget_gate_runs_the_check(tmp_path, how):
    o, rows, d, _err = guard_session(tmp_path, how)
    ctx = (o.get("hookSpecificOutput") or {}).get("additionalContext") or ""
    assert decision(o) is None                       # never a refusal, in any mode
    if how == "warn":
        assert "Brief budget reached" in ctx and "Early-stop check" in ctx
    else:                                            # observe (and an unknown value) and off: no output
        assert o == {}
    if how == "off":
        assert rows == [] and not (d / sp.STATE_DIR).exists()
    else:
        assert [r["signal"] for r in rows] == ["budget", "stall", "stop"]
        assert rows[0]["calls"] == 10 and rows[0]["src"] == "brief" and rows[0]["type"] == "coder"
        assert rows[0]["ctx"] == 10000 and rows[0]["mode"] == ("warn" if how == "warn" else "observe")


@pytest.mark.parametrize("softctx,scale,want,gate", [("2000", None, ["stall", "stop"], 2000),
                                                     ("0", None, ["stall"], None),
                                                     ("20000", "0.1", ["stall", "stop"], 2000),
                                                     ("2000", "0", ["stall"], None)])
def test_the_soft_limit_is_the_default_gate(tmp_path, softctx, scale, want, gate):
    """No brief budget: the gate is the type's soft limit in force (soft.agent.<type> of the session snapshot
    x STACK_SOFT_LIMIT_SCALE); none, no stop."""
    extra = dict({"STACK_SOFTCTX_CODER": softctx}, **({"STACK_SOFT_LIMIT_SCALE": scale} if scale else {}))
    o, rows, _d, _err = guard_session(tmp_path, "observe", extra, budget=None)
    assert decision(o) is None and [r["signal"] for r in rows] == want
    if gate:
        assert rows[-1]["src"] == "soft" and rows[-1]["budget_tokens"] == gate


def test_the_gate_passes_its_own_count_and_run_stamp(tmp_path):
    """The usage and run logged are run_segment's: without message ids the gate counts 10 calls by uuid, the
    module's own count only 1, so a check() that falls back to its own count logs no `budget`."""
    _o, rows, d, _err = guard_session(tmp_path, "observe", strip_ids=True)
    assert [r["signal"] for r in rows] == ["budget", "stall", "stop"]
    assert rows[0]["calls"] == 10 and rows[0]["ctx"] == 10000
    assert rows[0]["run"] == json.loads((d / "agents" / "A1.json").read_text())["started"]


def test_a_hard_refusal_is_not_checked(tmp_path):
    o, rows, d, _err = guard_session(tmp_path, "warn", {"STACK_MAXTURNS_CODER": "3"})
    hso = o.get("hookSpecificOutput") or {}
    assert hso.get("permissionDecision") == "deny" and "Turn budget reached" in hso["permissionDecisionReason"]
    assert "Early-stop" not in hso["permissionDecisionReason"]
    assert rows == [] and not (d / sp.STATE_DIR).exists()


@pytest.mark.parametrize("extra,agent", [({}, None), ({"STACK_POLICY": "off"}, "A1")])
def test_the_main_thread_and_policy_off_are_not_checked(tmp_path, extra, agent):
    o, rows, d, _err = guard_session(tmp_path, "warn", extra, agent=agent)
    assert o == {} and rows == [] and not (d / sp.STATE_DIR).exists()


def test_a_broken_module_fails_open(tmp_path):
    hooks = tmp_path / "hooks"
    shutil.copytree(HOOKS, hooks, ignore=shutil.ignore_patterns("__pycache__"))
    (hooks / "stack_progress.py").write_text("raise RuntimeError('seeded')\n")
    o, rows, _d, err = guard_session(tmp_path, "warn", hooks=hooks)
    assert decision(o) is None and "Early-stop" not in json.dumps(o) and rows == []
    assert "early stop: not checked (RuntimeError)" in err


# ---------------------------------------------------------------- the installer ships it
def test_the_installer_stages_tracks_and_compiles_the_module():
    text = (ROOT / "install.sh").read_text()
    sd = load(ROOT / "lib" / "stack_diff.py", "l5_stack_diff")
    assert sd.staged_files(text).get("hooks/stack_progress.py") == "dot-config/dot-claude/hooks/stack_progress.py"
    assert '"hooks/stack_progress.py"' in re.search(r"(?s)STACK_SCRIPTS = \[(.*?)\]", text).group(1)
    mods = re.search(r'(?m)^\s*for m in ([^;\n]+); do\n\s*if \[ -f "\$C/hooks/\$m\.py" \]', text)
    assert mods and "stack_progress" in mods.group(1).split()
    assert '"stack_progress"' in (DOT / "bin" / "doctor.sh").read_text()
    allow = json.loads((ROOT / "tests" / "redundancy_allowlist.json").read_text())
    assert not [e for e in allow["hooks"] if e.get("file") == "stack_progress.py"]
