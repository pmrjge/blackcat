"""Credential scrub, observe only (agent_guard.py scrub_observe, STACK_SCRUB): an Agent prompt or a
SendMessage message matching bin/stack-tree's credential patterns is logged (class, tool, agent id;
never the text) and noted once per run to the sender; nothing is rewritten or denied.
Run: uv run --with pytest pytest -q tests/test_scrub_observe.py
GUARD=/path/to/agent_guard.py points them at another copy of the hook (its ../bin/stack-tree is read)."""
import json
import os
import shutil
import stat
import subprocess
import sys
import time

from guard_harness import GUARD, Env

# built at run time, so no token-shaped literal sits in the repository
FAKE_GH = "gh" + "p_" + "Q7w" * 12
FAKE_PW = "pass" + "word=" + "Hu" * 6 + "42"


def log_path(e):
    return os.path.join(e.sdir(), "scrub-observe.jsonl")


def log_rows(e):
    p = log_path(e)
    return [json.loads(x) for x in open(p).read().splitlines()] if os.path.exists(p) else []


def context(r):
    return json.loads(r.stdout)["hookSpecificOutput"].get("additionalContext", "") if r.stdout.strip() else ""


def dispatch(e, prompt, **extra):
    ev = e.pre_agent("coder", agent_type="blackcat")
    ev["tool_input"]["prompt"] = prompt
    return ev, e.run(ev, extra=extra or None)


def child(e, cid="C1"):
    ev, r = dispatch(e, "fix the parser")
    e.run(e.start(cid, "coder"))
    e.run(e.post_agent(ev, cid))
    return cid


def send(e, text, aid="C1", to="main"):
    ev = e.send(to, agent_id=aid, agent_type="coder")
    ev["tool_input"]["message"] = text
    return e.run(ev)


def test_secret_in_a_brief_is_logged_and_noted_never_rewritten():
    e = Env()
    prompt = "Deploy with this token: " + FAKE_GH + " then report."
    ev, r = dispatch(e, prompt)
    assert r.decision != "deny", r
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out.get("updatedInput", {}).get("prompt", prompt) == prompt      # not rewritten
    assert "Credential check (observe only" in out["additionalContext"]
    assert "known-token-format" in out["additionalContext"]
    rows = log_rows(e)
    assert len(rows) == 1 and rows[0]["tool"] == "Agent" and rows[0]["agent_id"] == "main"
    assert "known-token-format" in rows[0]["counts"] and set(rows[0]) == {"ts", "tool", "agent_id", "counts"}
    assert stat.S_IMODE(os.stat(log_path(e)).st_mode) == 0o600


def test_the_log_never_holds_the_secret_or_the_text():
    e = Env()
    child(e)
    send(e, "use " + FAKE_PW + " and " + FAKE_GH)
    raw = open(log_path(e)).read()
    for secret in (FAKE_GH, FAKE_PW, FAKE_GH[4:16], "Hu" * 6, "use "):
        assert secret not in raw, secret
    assert {"secret-assignment", "known-token-format"} <= set(log_rows(e)[-1]["counts"])


def test_the_full_text_is_scanned_and_matches_counted():
    e = Env()
    child(e)
    send(e, "a" * 70000 + "\n" + FAKE_GH + " and " + FAKE_GH)      # past RAW_CAP and any 64K cut
    assert log_rows(e)[-1]["counts"]["known-token-format"] == 2


def test_note_once_per_run_log_every_match():
    e = Env()
    child(e)
    first = send(e, "token " + FAKE_GH)
    second = send(e, "again " + FAKE_PW)
    assert "Credential check" in context(first) and "Credential check" not in context(second)
    assert len(log_rows(e)) == 2 and log_rows(e)[1]["agent_id"] == "C1"
    # a resume is a new run (SubagentStart rewrites `started`): one more note
    e.run(e.stop("C1", "coder"))
    e.age_reg("C1", 5)
    e.run(e.start("C1", "coder"))
    assert "Credential check" in context(send(e, "third " + FAKE_GH))


def test_clean_text_and_off_write_nothing():
    e = Env()
    child(e)
    r = send(e, "Plan: run the suite, then report the token counts per agent.")
    assert "Credential check" not in context(r) and log_rows(e) == []
    e2 = Env(STACK_SCRUB="off")
    ev, r = dispatch(e2, "secret " + FAKE_GH)
    assert "Credential check" not in context(r) and not os.path.exists(log_path(e2))
    assert not os.path.exists(os.path.join(e2.sdir(), "scrub"))


def test_log_is_capped_at_one_megabyte():
    e = Env()
    child(e)
    with open(log_path(e), "w") as f:
        f.write("x" * ((1 << 20) - 10))
    os.chmod(log_path(e), 0o600)
    send(e, FAKE_GH)
    assert os.path.getsize(log_path(e)) == (1 << 20) - 10


def test_fails_open_without_the_pattern_table(tmp_path):
    hooks = tmp_path / "hooks"
    shutil.copytree(os.path.dirname(GUARD), hooks)            # no ../bin/stack-tree beside it
    e = Env()
    e_guard = str(hooks / os.path.basename(GUARD))
    ev = e.pre_agent("coder", agent_type="blackcat")
    ev["tool_input"]["prompt"] = "secret " + FAKE_GH
    p = subprocess.run([sys.executable, e_guard], input=json.dumps(ev), capture_output=True, text=True,
                       env=e.env, timeout=60)
    assert p.returncode == 0 and '"deny"' not in p.stdout, (p.stdout, p.stderr)
    assert "scrub: FileNotFoundError" in p.stderr and not os.path.exists(log_path(e))


# ---------------------------------------------------------------- guard-land: bounded scan
def test_a_crafted_word_is_scanned_in_bounded_time_and_logged_partial():
    """review a788868 / audit aee5316 HIGH: stack-tree's patterns backtrack quadratically on one long
    word ("pass"*60000: ~15 s uncapped), past the hook's 15 s timeout. The scan runs in windows to a
    deadline: an allowed call keeps its output (the stamp) and the log row says partial."""
    e = Env()
    child(e)
    t = time.monotonic()
    r = send(e, "pass" * 60000)
    took = time.monotonic() - t
    assert took < 5 and r.decision != "deny", (took, r)
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["updatedInput"]["message"].startswith("[from coder C1: ")       # held, then written
    assert log_rows(e)[-1].get("partial") is True, log_rows(e)


def test_matches_across_window_edges_count_once():
    e = Env()
    child(e)
    # windows of 4096 that overlap by 512: [0,4096) [3584,7680) [7168,11264) [10752,14848) ...
    # tokens at a window's start, inside an overlap (seen by two windows) and across a window's end
    text = [" "] * 16000
    for at in (3584, 3700, 4076, 7168, 7670, 11000, 11240, 14830):
        text[at:at + len(FAKE_GH)] = FAKE_GH
    send(e, "".join(text))
    row = log_rows(e)[-1]
    assert row["counts"]["known-token-format"] == 8 and "partial" not in row, row


def test_a_refused_call_is_refused_before_any_scan():
    """The scrub runs after the decision: a refusal never waits for it (and logs nothing)."""
    e = Env()
    child(e)
    ev = e.send("nobody", agent_id="C1", agent_type="coder")
    ev["tool_input"]["message"] = "token " + FAKE_GH
    r = e.run(ev)
    assert r.decision == "deny" and log_rows(e) == [], (r, log_rows(e))


def test_loading_stack_tree_writes_no_bytecode_into_bin(tmp_path):
    """review a788868 / audit aee5316 LOW: hooks run outside the sandbox, and without
    PYTHONDONTWRITEBYTECODE the guard's load of bin/stack-tree wrote bin/__pycache__ (stack-tree's own
    sys.dont_write_bytecode runs after get_code has written the pyc)."""
    for sub in ("hooks", "bin"):
        shutil.copytree(os.path.join(os.path.dirname(os.path.dirname(GUARD)), sub), tmp_path / sub,
                        ignore=shutil.ignore_patterns("__pycache__"))
    e = Env()
    env = {k: v for k, v in e.env.items() if k != "PYTHONDONTWRITEBYTECODE"}
    guard = str(tmp_path / "hooks" / os.path.basename(GUARD))
    ev = e.pre_agent("coder", agent_type="blackcat")
    ev["tool_input"]["prompt"] = "secret " + FAKE_GH
    p = subprocess.run([sys.executable, guard], input=json.dumps(ev), capture_output=True, text=True,
                       env=env, timeout=60)
    assert p.returncode == 0 and "known-token-format" in p.stdout, (p.stdout, p.stderr)
    assert not (tmp_path / "bin" / "__pycache__").exists(), os.listdir(tmp_path / "bin" / "__pycache__")
