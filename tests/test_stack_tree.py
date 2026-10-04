"""bin/stack-tree: the session's agent tree (or table) from the guard's delegation records, its agent registry
and the transcripts, and /stack-tree = `stack-tree --hook` on UserPromptExpansion (matcher stack-tree), which
blocks the expansion (exit 2) with the output on stderr, so no model turn runs and BlackCat needs no Bash.
Every run here uses /usr/bin/python3 (3.9 on macOS), the interpreter the hook and the shebang name."""
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TREE = ROOT / "dot-claude" / "bin" / "stack-tree"
PY = "/usr/bin/python3"
SID = "11111111-2222-3333-4444-555555555555"
HOSTILE = "evil\x1b[31mRED\x1b[0m\rFORGED\nnext line\x07‮gnp.exe​|pipe`tick`<script>[x](y)\\"
SECRET = "sk-ant-abcdefghijklmnopqrstuvwxyz012345"


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))


def asst(mid, blocks, t, side=False):
    return {"type": "assistant", "isSidechain": side, "timestamp": iso(t),
            "message": {"id": mid, "content": blocks,
                        "usage": {"input_tokens": 10, "cache_creation_input_tokens": 100,
                                  "cache_read_input_tokens": 1000, "output_tokens": 5}}}


def use(tid, name, inp):
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


def result(tid, t, err=False, txt="ok"):
    return {"type": "user", "timestamp": iso(t),
            "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "is_error": err, "content": txt}]}}


def say(mid, txt, t):
    return asst(mid, [{"type": "text", "text": txt}], t)


class Fixture(object):
    def __init__(self, tmp, sid=SID):
        self.tmp, self.sid = tmp, sid
        self.state = tmp / "state" / "claude-agent-stack" / sid
        self.proj = tmp / "cfg" / "projects" / "-proj"
        (self.state / "spawns").mkdir(parents=True)
        (self.state / "agents").mkdir()
        self.proj.mkdir(parents=True, exist_ok=True)
        (tmp / "home").mkdir(exist_ok=True)
        self.main = self.proj / (sid + ".jsonl")
        self.t0 = time.time() - 3600

    def spawn(self, tid, by, typ, task, child=None, status="async_launched", ts=None, **kw):
        rec = dict({"tid": tid, "by": by, "by_type": None, "type": typ, "task": task, "name": None,
                    "isolation": None, "ts": ts or self.t0, "status": status}, **kw)
        if child:
            rec["child"] = child
        (self.state / "spawns" / (tid + ".json")).write_text(json.dumps(rec))

    def agent(self, aid, typ, parent="main", stopped=True, start=None, **kw):
        start = start or self.t0
        rec = dict({"id": aid, "type": typ, "parent": parent, "spawned": start, "started": start,
                    "transcript": str(self.proj / self.sid / "subagents" / ("agent-%s.jsonl" % aid))}, **kw)
        if stopped:
            rec["stopped"] = start + 125
        (self.state / "agents" / (aid + ".json")).write_text(json.dumps(rec))

    def transcript(self, lines, aid=None):
        p = self.main if aid is None else self.proj / self.sid / "subagents" / ("agent-%s.jsonl" % aid)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join(json.dumps(x) + "\n" for x in lines))
        return p

    def env(self, **kw):
        e = {"PATH": "/usr/bin:/bin", "HOME": str(self.tmp / "home"), "XDG_STATE_HOME": str(self.tmp / "state"),
             "CLAUDE_CONFIG_DIR": str(self.tmp / "cfg"), "COLUMNS": "400", "LANG": "en_US.UTF-8"}
        e.update(kw)
        return e

    def run(self, *args, stdin=None, timeout=60, script=TREE, direct=False, **envkw):
        # as the hook runs it ("__PYTHON3__" -B), or through the shebang (#!/usr/bin/python3 -B)
        cmd = [str(script)] if direct else [PY, "-B", str(script)]
        return subprocess.run(cmd + list(args), input=stdin, capture_output=True, text=True,
                              timeout=timeout, env=self.env(**envkw))

    def hook(self, args="", event=None, **kw):
        ev = {"session_id": self.sid, "hook_event_name": "UserPromptExpansion", "expansion_type": "slash_command",
              "command_name": "stack-tree", "command_args": args, "command_source": "userSettings",
              "prompt": "/stack-tree " + args}
        ev.update(event or {})
        return self.run("--hook", stdin=json.dumps(ev), **kw)


def nested(tmp):
    """main -> orchestrator (partial) -> main-coder (done) -> coder (blocked) -> explore (finished, no report);
    main -> scout (failed spawn); main -> verifier (running, one pending call)."""
    f = Fixture(tmp)
    t = f.t0
    f.transcript([
        asst("m1", [use("tu1", "Read", {"file_path": "/x/plan.md"})], t),
        result("tu1", t + 1),
        asst("m2", [use("tu2", "Agent", {"subagent_type": "orchestrator"})], t + 2),
        asst("m3", [use("tu3", "Bash", {"command": "git status"})], t + 3),
        result("tu3", t + 4),
        asst("m4", [use("tu4", "Bash", {"command": "git status"})], t + 5),
        result("tu4", t + 6, err=True, txt="Exit code 1\nfatal"),
        asst("side", [use("tu9", "Bash", {"command": "sidechain only"})], t + 7, side=True),
    ])
    f.spawn("t1", "main", "orchestrator", "plan the work", child="A1", ts=t + 2)
    f.spawn("t2", "A1", "main-coder", "build it", child="A2", ts=t + 10)
    f.spawn("t3", "A2", "coder", "small part", child="A3", ts=t + 20)
    f.spawn("t4", "A3", "explore", "find files", child="A4", ts=t + 30)
    f.spawn("t5", "main", "scout", "look it up", status="failed", ts=t + 40)
    f.spawn("t6", "main", "verifier", "check it", child="A6", ts=t + 50)
    for aid, typ, parent, st in (("A1", "orchestrator", "main", t + 2), ("A2", "main-coder", "A1", t + 10),
                                 ("A3", "coder", "A2", t + 20), ("A4", "explore", "A3", t + 30)):
        f.agent(aid, typ, parent, start=st)
    f.agent("A6", "verifier", "main", stopped=False, start=t + 50)
    f.transcript([asst("a1", [use("x1", "Skill", {"skill": "review-protocol"})], t + 3), result("x1", t + 4),
                  say("a1b", "work\nSTATUS: partial\nRESULT: half", t + 100)], "A1")
    f.transcript([asst("a2", [use("x2", "mcp__libdocs__get_docs", {"q": "z"})], t + 11), result("x2", t + 12),
                  say("a2b", "clean finish line", t + 30)], "A2")
    f.transcript([asst("a3", [use("x3", "Bash", {"command": "rm -rf /"})], t + 21),
                  result("x3", t + 22, err=True, txt="PreToolUse:Bash hook error: Blocked by the stack's guard"),
                  say("a3b", "STATUS: blocked\nNEXT: ASK USER", t + 40)], "A3")
    f.transcript([asst("a4", [use("x4", "Grep", {"pattern": "foo", "path": "/src"})], t + 31),
                  result("x4", t + 32)], "A4")
    f.transcript([asst("a6", [use("x6", "Bash", {"command": "sleep 100"})], t + 51)], "A6")
    return f


def lines_of(p):
    assert p.returncode == 0, p.stderr
    return p.stdout.splitlines()


# ---------------------------------------------------------------- live tree
def test_nested_tree_levels_statuses_and_leaves(tmp_path):
    f = nested(tmp_path)
    out = lines_of(f.run("--session", SID))
    assert out[0].startswith("stack-tree · session %s · 6 agents (1 running, 3 failed/blocked/partial/stopped)" % SID)
    assert out[1].startswith("blackcat (main thread) · ")
    body = "\n".join(out)
    assert "├── Read /x/plan.md\n" in body
    assert "├── $ git status ×2 [1 exit 1]\n" in body                      # collapsed, failure counted
    assert "sidechain only" not in body                                     # main transcript: main thread only
    assert '├── orchestrator · "plan the work" · partial · 2m05s · ' in body   # STATUS line of its last message
    assert '│   └── main-coder · "build it" · done · ' in body                # a clean finish is done
    assert '│       └── coder · "small part" · blocked · ' in body
    assert '│           └── explore · "find files" · finished · ' in body       # stopped, no final report
    assert '│               └── Grep foo in /src' in body
    assert '├── scout · "look it up" · failed' in body
    assert '└── verifier · "check it" · running · ' in body
    assert '    └── $ sleep 100 [pending]' in body
    assert "│   ├── review-protocol" in body and "libdocs.get_docs" in body and "rm -rf / [blocked]" in body
    assert "1.1k tok" in body and "1 calls" in body                         # 10+100+1000+5 per message


def test_depth_leaves_and_failed_filters(tmp_path):
    f = nested(tmp_path)
    d1 = "\n".join(lines_of(f.run("--session", SID, "--depth", "1")))
    assert "orchestrator" in d1 and "main-coder" not in d1 and "review-protocol" in d1
    d0 = "\n".join(lines_of(f.run("--session", SID, "--depth", "0", "--no-leaves")))
    assert d0.count("\n") == 1                                              # header + root
    nl = "\n".join(lines_of(f.run("--session", SID, "--no-leaves")))
    assert "git status" not in nl and "explore" in nl
    fl = "\n".join(lines_of(f.run("--session", SID, "--leaves-only-failed")))
    assert "$ git status [exit 1]" in fl and "Read /x/plan.md" not in fl and "rm -rf / [blocked]" in fl
    assert "sleep 100" not in fl and "review-protocol" not in fl
    asc = lines_of(f.run("--session", SID, "--ascii"))
    assert any(l.startswith("|-- ") for l in asc) and any("`-- " in l for l in asc)
    assert not any(c in "\n".join(asc) for c in "├└│")
    narrow = lines_of(f.run("--session", SID, "--width", "40"))
    assert all(len(l) <= 40 for l in narrow) and any(l.endswith("…") for l in narrow)
    ml = "\n".join(lines_of(f.run("--session", SID, "--max-leaves", "1")))
    assert "… 1 more (--max-leaves 0 shows all)" in ml


def test_json_tree(tmp_path):
    f = nested(tmp_path)
    doc = json.loads(f.run("--session", SID, "--json").stdout)
    assert doc["session"] == SID and doc["source"] == "spawns" and doc["main_transcript"]
    r = doc["root"]
    assert r["type"] == "blackcat" and r["level"] == "main" and len(r["calls"]) == 3
    o = r["children"][0]
    chain = [o, o["children"][0], o["children"][0]["children"][0], o["children"][0]["children"][0]["children"][0]]
    assert [(c["type"], c["level"], c["status"]) for c in chain] == [
        ("orchestrator", "L1", "partial"), ("main-coder", "L2", "done"), ("coder", "L3", "blocked"),
        ("explore", "L4", "finished")]
    assert o["tokens"] == 2 * 1115 and o["duration_s"] == pytest.approx(125, abs=1)


def test_newest_session_is_the_default_and_the_hook_prefers_its_own(tmp_path):
    f = nested(tmp_path)
    other = Fixture(tmp_path, sid="99999999-0000-0000-0000-000000000000")
    other.spawn("z1", "main", "writer", "newer session", child="Z1")
    os.utime(other.state / "spawns", (time.time() + 100, time.time() + 100))
    assert "newer session" in f.run().stdout
    p = f.hook("")
    assert p.returncode == 2 and p.stdout == "" and "session %s" % SID in p.stderr.splitlines()[0]


def test_hostile_strings_cannot_forge_lines_or_escape(tmp_path):
    f = Fixture(tmp_path)
    t = f.t0
    f.spawn("t1", "main", "coder" + HOSTILE, HOSTILE, child="A1", name=HOSTILE, isolation=HOSTILE)
    f.agent("A1", "coder")
    f.transcript([asst("m1", [use("u1", "Bash", {"command": HOSTILE + " && export API_KEY=%s" % SECRET}),
                              use("u2", "WebFetch", {"url": "https://user:pw@h.example/p?token=%s#f" % SECRET}),
                              use("u3", HOSTILE, {}), use("u4", "Read", {"file_path": HOSTILE})], t),
                  say("m2", HOSTILE + "\nSTATUS: done", t + 2)], "A1")
    f.transcript([])
    outs = [f.run("--session", SID), f.run("--session", SID, "--table", "--columns", "all", "--width", "0"),
            f.run("--session", SID, "--json"), f.run("--session", SID, "--table", "--csv"),
            f.run("--session", SID, "--table", "--json"), f.hook("")]
    for p in outs:
        s = p.stdout + p.stderr
        assert not re.search(r"[\x00-\x09\x0b-\x1f\x7f‮​]", s), repr(s[:300])
        assert "\\u001b" not in s and "\\r" not in s and "\\u202e" not in s     # nor as JSON escapes
        assert SECRET not in s and "user:pw" not in s
    tree = outs[0].stdout.splitlines()
    assert len(tree) == 2 + 1 + 4                    # header, root, the agent, its four calls: no forged line
    assert all("FORGED" not in l or "evil" in l for l in tree)


def test_markdown_table_cells_are_escaped_and_valid(tmp_path):
    f = Fixture(tmp_path)
    f.spawn("t1", "main", "coder", "|pipe`tick`<script>[x](y)\\ " + HOSTILE, child="A1")
    f.agent("A1", "coder")
    f.transcript([asst("m1", [use("u1", "Bash", {"command": "a | b `c` <x> [l](u) \\ " + HOSTILE})], f.t0),
                  result("u1", f.t0 + 1)], "A1")
    f.transcript([])
    for width in ("80", "0"):
        p = f.run("--session", SID, "--table", "--columns", "all", "--width", width)
        rows = lines_of(p)
        ncols = 15 + 9                     # LIVE_EXTRA gained eflag and report
        assert rows[1] == "|" + "|".join(" --- " for _ in range(ncols)) + "|"
        for r in rows:
            assert r.startswith("| ") and r.endswith(" |")
            pipes, i = 0, 0
            while i < len(r):                        # GFM: a backslash escapes the next character
                if r[i] == "\\":
                    i += 2
                    continue
                pipes += r[i] == "|"
                assert r[i] not in "`<>[]", r
                i += 1
            assert pipes == ncols + 1, r
        assert "\\<script\\>" in p.stdout and "\\|pipe\\`tick\\`" in p.stdout


def test_table_columns_rows_and_unrecorded(tmp_path):
    f = nested(tmp_path)
    rows = lines_of(f.run("--session", SID, "--table", "--columns", "path,agent,kind,command,result,tokens"))
    assert rows[0] == "| path | agent | kind | command | result | tokens |"
    body = rows[2:]
    assert "| 0 | blackcat | agent | — | — | 4460 |" in body
    assert "| 0#1 | blackcat | tool | Read /x/plan.md | ok | unrecorded |" in body   # no per-call tokens
    assert "| 0#3 | blackcat | bash | $ git status | exit 1 | unrecorded |" in body
    assert "| 1.1.1 | coder | agent | — | blocked | 2230 |" in body
    assert "| 2 | scout | agent | — | — | unrecorded |" in body                      # failed spawn: no transcript
    assert len(body) == 7 + 3 + 5                     # 7 agents, 3 main calls, 5 agent calls (Agent is a node)
    nl = lines_of(f.run("--session", SID, "--table", "--no-leaves", "--columns", "kind"))
    assert nl[2:] == ["| agent |"] * 7
    fl = lines_of(f.run("--session", SID, "--table", "--leaves-only-failed", "--columns", "kind,result"))
    assert "| bash | exit 1 |" in fl and "| skill | ok |" not in fl
    bad = f.run("--session", SID, "--table", "--columns", "agent,nope")
    assert bad.returncode == 2 and "unknown column(s) nope" in bad.stderr
    allc = lines_of(f.run("--session", SID, "--table", "--columns", "all"))
    assert allc[0].endswith("| id | tid | name | isolation | ended | output_tokens | transcript | eflag | report |")
    j = json.loads(f.run("--session", SID, "--table", "--json", "--columns", "path,status").stdout)
    assert j[0] == {"path": "0", "status": "session"}
    c = lines_of(f.run("--session", SID, "--table", "--csv", "--columns", "path,agent"))
    assert c[:2] == ["path,agent", "0,blackcat"]


def test_csv_cells_cannot_start_a_formula(tmp_path):
    f = Fixture(tmp_path)
    f.spawn("t1", "main", "coder", "=HYPERLINK(\"http://x\")", child="A1")
    f.agent("A1", "coder")
    f.transcript([])
    out = f.run("--session", SID, "--table", "--csv", "--columns", "task").stdout
    assert "'=HYPERLINK" in out and "\n=HYPERLINK" not in out


def test_missing_bad_and_empty_sessions(tmp_path):
    f = Fixture(tmp_path)
    p = f.run("--session", "00000000-dead-beef-0000-000000000000")
    assert p.returncode == 1 and "no session 00000000-dead-beef" in p.stdout
    for bad in ("../etc", "a/b", "", "-x"):
        p = f.run("--session=" + bad)
        assert p.returncode == 2 and "not a session id" in p.stderr, bad
    p = f.run("--session", SID)                       # an empty ledger: the root only
    assert p.returncode == 0 and "0 agents" in p.stdout and "(no Agent calls recorded yet)" in p.stdout
    assert "(main transcript not found" in p.stdout
    empty = Fixture(tmp_path / "e")
    shutil.rmtree(empty.state.parent)
    p = empty.run()
    assert p.returncode == 1 and "no session with a delegation ledger" in p.stdout
    h = empty.hook("", event={"session_id": "not/valid"})
    assert h.returncode == 2 and "no session with a delegation ledger" in h.stderr


def test_delegations_md_fallback(tmp_path):
    f = Fixture(tmp_path)
    shutil.rmtree(f.state / "spawns")
    (f.state / "delegations.md").write_text(
        "# Delegations, session x\nUpdated 1.\n\n"
        '- orchestrator · "plan \x1b[2J" · finished · 12:00:00 · id A1\n'
        '  - coder · "code" · running · 12:01:00 · id A2\n'
        '- scout · "s" · failed · 12:02:00\n')
    out = "\n".join(lines_of(f.run("--session", SID)))
    assert '├── orchestrator · "plan [2J" · finished' in out and "\x1b" not in out
    assert '│   └── coder · "code" · running' in out and '└── scout · "s" · failed' in out
    assert "(read from delegations.md" in out


def test_fifos_and_odd_records_do_not_hang_or_crash(tmp_path):
    f = nested(tmp_path)
    os.mkfifo(str(f.state / "spawns" / "fifo.json"))
    os.mkfifo(str(f.state / "agents" / "AF.json"))
    (f.state / "spawns" / "junk.json").write_text("[1, 2")
    (f.state / "spawns" / "list.json").write_text("[1, 2]")
    (f.state / "spawns" / "odd.json").write_text(json.dumps({"tid": "odd", "by": 5, "type": None, "ts": "x",
                                                             "child": "../../etc"}))
    (f.state / "agents" / "A9.json").write_text(json.dumps({"type": "writer", "parent": "GHOST", "spawned": 1e30}))
    sub = f.proj / SID / "subagents" / "agent-A4.jsonl"
    sub.unlink()
    os.mkfifo(str(sub))
    p = f.run("--session", SID, timeout=30)
    assert p.returncode == 0, p.stderr
    assert "explore" in p.stdout and "id GHOST · spawn not recorded" in p.stdout and "writer" in p.stdout


def test_huge_ledger_is_bounded(tmp_path):
    f = Fixture(tmp_path)
    t = f.t0
    for i in range(1500):
        f.spawn("t%05d" % i, "main", "scout", "task %d" % i, child="S%05d" % i, ts=t + i)
    f.agent("S00000", "scout")
    calls = []
    for i in range(20000):
        calls += [asst("m%d" % i, [use("u%d" % i, "Bash", {"command": "echo %d" % (i % 50)})], t + i),
                  result("u%d" % i, t + i)]
    f.transcript(calls, "S00000")
    f.transcript([])
    t1 = time.time()
    p = f.run("--session", SID, timeout=120)
    assert p.returncode == 0 and time.time() - t1 < 60
    lines = p.stdout.splitlines()
    assert len(lines) == 2 + 1500 + 11                # 10 distinct commands of 50, then "… 40 more"
    assert "$ echo 0 ×400" in p.stdout and "… 40 more" in p.stdout
    h = f.hook("")
    assert h.returncode == 2 and len(h.stderr) <= 16000 + 600
    assert h.stderr.splitlines()[-1].startswith("… cut at ") and "stack-tree" in h.stderr.splitlines()[-1]


# ---------------------------------------------------------------- hook
def test_hook_output_format_words_and_errors(tmp_path):
    f = nested(tmp_path)
    p = f.hook("--depth 1")
    assert p.returncode == 2 and p.stdout == ""
    err = p.stderr.splitlines()
    assert err[0].startswith("stack-tree · session %s" % SID) and err[1].startswith("blackcat (main thread)")
    assert "main-coder" not in p.stderr
    t = f.hook("table --no-leaves --columns path,agent")
    assert t.returncode == 2 and t.stderr.splitlines()[:3] == ["| path | agent |", "| --- | --- |", "| 0 | blackcat |"]
    s = f.hook("static --depth 1 --no-leaves")
    assert s.returncode == 2 and s.stderr.startswith("stack-tree --static")
    for args, msg in (("--bogus", "unrecognized arguments: --bogus"), ("--hook", "--hook is not an option"),
                      ('"open', "cannot parse the arguments"), ("--session ../x", "not a session id")):
        e = f.hook(args)
        assert e.returncode == 2 and e.stdout == "" and msg in e.stderr, (args, e.stderr)
    h = f.hook("--help")
    assert h.returncode == 2 and "usage: /stack-tree" in h.stderr
    # the event's transcript_path is used when the projects folder lacks it
    moved = tmp_path / "elsewhere" / (SID + ".jsonl")
    moved.parent.mkdir()
    shutil.move(str(f.main), str(moved))
    m = f.hook("", event={"transcript_path": str(moved)})
    assert "git status ×2" in m.stderr
    garbage = f.run("--hook", stdin="not json")
    assert garbage.returncode == 2 and garbage.stderr.startswith("stack-tree · session")


def test_settings_skill_and_installer_wiring():
    hooks = json.loads((ROOT / "dot-claude" / "settings.json").read_text())["hooks"]
    (g,) = [g for g in hooks["UserPromptExpansion"] if g["matcher"] == "stack-tree"]
    cmd = g["hooks"][0]["command"]
    assert cmd == '"__PYTHON3__" -B "__CLAUDE_DIR__/bin/stack-tree" --hook' and g["hooks"][0]["timeout"] <= 60
    src = (ROOT / "install.sh").read_text()
    stack_re = re.compile(re.search(r'^STACK_HOOK_RE = re\.compile\(r"([^"]+)"\)$', src, re.M).group(1))
    assert stack_re.search(cmd.replace("__PYTHON3__", "/usr/bin/python3").replace("__CLAUDE_DIR__", "/u/.claude"))
    assert "stack-budget stack-tree; do stage_script 755" in src and '"bin/stack-tree",' in src
    skill = (ROOT / "dot-claude" / "skills" / "stack-tree" / "SKILL.md").read_text()
    head = skill.split("\n---", 1)[0]
    assert "\nname: stack-tree\n" in head and "\ndisable-model-invocation: true" in head and "!`" not in skill
    assert os.access(str(TREE), os.X_OK) and TREE.read_text().startswith("#!/usr/bin/python3 -B\n")


# ---------------------------------------------------------------- static
def _guard():
    spec = importlib.util.spec_from_file_location("agent_guard_tree", ROOT / "dot-claude" / "hooks" / "agent_guard.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_static_hierarchy_matches_the_agent_files_and_policy(tmp_path):
    f = Fixture(tmp_path)
    rows = json.loads(f.run("--static", "--table", "--json", "--width", "0").stdout)
    names = sorted(p.stem for p in (ROOT / "dot-claude" / "agents").glob("*.md"))
    assert sorted(r["agent"] for r in rows) == names
    by = {r["agent"]: r for r in rows}
    policy = _guard().POLICY
    for name in names:
        want = sorted(policy.get(name, []))
        got = sorted(x for x in by[name]["may_spawn"].split(", ") if x != "—")
        assert got == want, name
    l1 = {a for a, r in by.items() if r["level"] == "L1"}
    assert l1 == set(policy["blackcat"]) and by["blackcat"]["level"] == "main"
    assert all(r["level"] in ["main"] + ["L%d" % d for d in range(1, 9)] for r in rows)
    assert by["python-engineer"]["skills"].startswith("python-engineering")
    assert "/stack-tree" in by["blackcat"]["skills"] and "/stack-doctor" in by["blackcat"]["skills"]
    tree = json.loads(f.run("--static", "--json").stdout)

    def walk(n, depth):
        assert n["level"] == ("main" if depth == 0 else "L%d" % depth)
        if n["children"]:
            assert depth < 8 and n["ref"] is None          # only a first occurrence below L8 expands
        for c in n["children"]:
            walk(c, depth + 1)
    walk(tree["root"], 0)
    assert tree["unreachable"] == []
    txt = f.run("--static", "--depth", "1", "--no-leaves").stdout.splitlines()
    assert txt[1] == "blackcat · main · sonnet" and len(txt) == 2 + len(policy["blackcat"])


# ---------------------------------------------------------------- read-only
def snapshot(*dirs):
    out = {}
    for d in dirs:
        for base, subdirs, files in os.walk(str(d)):
            for n in subdirs + files:
                p = os.path.join(base, n)
                st = os.lstat(p)
                out[p] = (st.st_mtime_ns, st.st_size, st.st_ino)
    return out


def test_every_mode_is_read_only(tmp_path):
    f = nested(tmp_path)
    cfg = tmp_path / "inst"
    (cfg / "bin").mkdir(parents=True)
    shutil.copy(str(TREE), str(cfg / "bin" / "stack-tree"))
    shutil.copytree(str(ROOT / "dot-claude" / "agents"), str(cfg / "agents"))
    shutil.copytree(str(ROOT / "dot-claude" / "skills" / "stack-tree"), str(cfg / "skills" / "stack-tree"))
    script = cfg / "bin" / "stack-tree"
    before = snapshot(tmp_path)
    repo_bin = sorted(os.listdir(str(TREE.parent)))
    runs = [(), ("--session", SID), ("--json",), ("--table",), ("--table", "--csv"), ("--table", "--json"),
            ("--static",), ("--static", "--table"), ("--static", "--json"), ("--session", "nope"), ("--bogus",)]
    for args in runs:
        for direct in (False, True):
            p = f.run(*args, script=script, direct=direct)
            assert p.returncode in (0, 1, 2), (args, p.stderr)
    h = f.hook("table", script=script)
    assert h.returncode == 2
    assert snapshot(tmp_path) == before                    # no file created, modified or replaced
    assert sorted(os.listdir(str(TREE.parent))) == repo_bin and not (cfg / "bin" / "__pycache__").exists()


# ---------------------------------------------------------------- review round 1 (code-reviewer on 845b6f4)
def test_resumed_foreground_agent_is_running(tmp_path):
    # F1: SubagentStart of a resume clears `stopped` and sets `resumed`; a foreground spawn record stays completed
    f = Fixture(tmp_path)
    f.spawn("t1", "main", "coder", "first run", child="A1", status="completed")
    f.agent("A1", "coder", stopped=False, resumed=f.t0 + 300)
    f.spawn("t2", "main", "writer", "resumed then stopped", child="A2", status="completed")
    f.agent("A2", "writer", resumed=f.t0 + 10)                      # stopped at t0 + 125, after the resume
    f.transcript([])
    p = f.run("--session", SID, "--table", "--no-leaves", "--columns", "agent,status")
    assert "| coder | running |" in p.stdout and "| writer | finished |" in p.stdout


def test_usage_of_a_message_split_over_lines_counts_its_final_output(tmp_path):
    # F2: one JSONL line per content block; earlier lines carry a partial output_tokens
    f = Fixture(tmp_path)
    a, b = asst("m1", [{"type": "text", "text": "x"}], f.t0), asst("m1", [use("u1", "Read", {"file_path": "/a"})], f.t0)
    b["message"]["usage"] = dict(a["message"]["usage"], output_tokens=300)
    f.transcript([a, b, asst("m2", [], f.t0 + 1)])
    rows = lines_of(f.run("--session", SID, "--table", "--no-leaves", "--columns", "tokens,output_tokens"))
    assert rows[2] == "| %d | 305 |" % (1110 + 300 + 1115)


LEAKS = [
    ('curl -H "X-Vault-Token: hvs.CAESIJabcdefghijklmnop" https://vault/v1/x', "hvs.CAES"),
    ('curl -H "PRIVATE-TOKEN: abcdEFGH12345678" https://gitlab/api', "abcdEFGH1234"),
    ("mysql -uroot -pS3cretPassw0rd db", "S3cretPass"),
    ("sshpass -p hunter2hunter2 ssh host", "hunter2"),
    ("""curl -d '{"api_key":"sk_live_51Habcdefghijkl","password":"hunter2"}' https://x""", "sk_live_51"),
    ("curl -d '{\"password\": \"hunter2\"}' https://x", "hunter2"),
    ("openssl rsa -in k.pem -passin pass:Sup3rSecret", "Sup3rSecret"),
    ("aws configure set aws_secret_access_key wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLEKEY", "wJalr"),
    ("npm config set //registry.npmjs.org/:_authToken npm_abcdefghijklmnopqrstuvwxyz0123456789", "npm_abcd"),
    ("echo sk_test_abcdefghijklmnop dckr_pat_abcdefghijklmnopqr", "sk_test_abc"),
    ("echo dckr_pat_abcdefghijklmnopqr", "dckr_pat_abc"),
]


@pytest.mark.parametrize("cmd,leak", LEAKS)
def test_more_secret_shapes_are_masked(tmp_path, cmd, leak):
    # F3
    f = Fixture(tmp_path)
    f.transcript([asst("m1", [use("u1", "Bash", {"command": cmd})], f.t0)])
    for args in ((), ("--table", "--width", "0"), ("--json",)):
        out = f.run("--session", SID, "--max-leaves", "0", *args).stdout
        assert leak not in out and "***" in out, (args, out[-400:])


def test_hook_json_is_cut_by_lines_not_dropped(tmp_path):
    # F4: a JSON document over the cap still shows its first lines
    f = Fixture(tmp_path)
    f.transcript([asst("m%d" % i, [use("u%d" % i, "Bash", {"command": "echo %d" % i})], f.t0) for i in range(300)])
    for args in ("json", "table json"):
        h = f.hook(args)
        ls = h.stderr.splitlines()
        assert h.returncode == 2 and len(ls) > 50 and any('"' in l for l in ls[:5]) and ls[-1].startswith("… cut at ")


def test_abbreviated_help_goes_to_the_reason(tmp_path):
    # F5: argparse accepts --hel and -hx and would print help to stdout
    f = Fixture(tmp_path)
    for args in ("--hel", "--h", "-h"):
        h = f.hook(args)
        assert h.returncode == 2 and h.stdout == "" and "show this help" in h.stderr, args
    x = f.hook("-hx")                                  # Python 3.9: a usage error, still nothing on stdout
    assert x.returncode == 2 and x.stdout == "" and "usage: /stack-tree" in x.stderr
    c = f.run("--hel")
    assert c.returncode == 0 and "show this help" in c.stdout and c.stderr == ""


def test_markdown_cells_escape_character_references(tmp_path):
    # F6: a renderer would turn &#x202E; into a real bidi override
    f = Fixture(tmp_path)
    f.spawn("t1", "main", "coder", "&#x202E;exe.doc &amp;", child="A1")
    f.agent("A1", "coder")
    f.transcript([])
    out = f.run("--session", SID, "--table", "--columns", "task").stdout
    assert "\\&#x202E;exe.doc \\&amp;" in out


def test_cut_line_names_the_shown_session(tmp_path):
    # F7: the terminal command must show the event's session, not the newest one
    f = Fixture(tmp_path)
    f.transcript([asst("m%d" % i, [use("u%d" % i, "Bash", {"command": "echo %d" % i})], f.t0) for i in range(300)])
    other = Fixture(tmp_path, sid="99999999-0000-0000-0000-000000000000")
    other.spawn("z1", "main", "writer", "newer", child="Z1")
    os.utime(other.state / "spawns", (time.time() + 100, time.time() + 100))
    h = f.hook("table")
    assert "--session %s" % SID in h.stderr.splitlines()[-1]


def test_adversarial_strings_stay_fast(tmp_path):
    # backtracking-heavy commands and a final message of blank lines: linear patterns, cut before redaction
    f = Fixture(tmp_path)
    nasty = ["x-key-" * 3000, "key" + " " * 9000 + ":", "a-" * 5000, "--token-" * 2000, "KEY=" * 3000]
    f.transcript([asst("m%d" % i, [use("u%d" % i, "Bash", {"command": nasty[i % 5] + str(i)})], f.t0)
                  for i in range(400)] + [say("z", "\n" * 50000 + " \t" * 20000, f.t0 + 1)])
    for args in ((), ("--table",), ("--json",)):
        t = time.time()
        p = f.run("--session", SID, "--max-leaves", "0", *args, timeout=120)
        assert p.returncode == 0 and time.time() - t < 20, (args, time.time() - t)
    t = time.time()
    assert f.hook("table").returncode == 2 and time.time() - t < 20


def test_past_the_deadline_text_is_withheld_and_transcripts_unscanned(tmp_path):
    code = ("import importlib.machinery as M, importlib.util as U, sys; l = M.SourceFileLoader('t', sys.argv[1]); "
            "m = U.module_from_spec(U.spec_from_loader('t', l)); l.exec_module(m); m.DEADLINE = 1.0; "
            "print(m.text('API_KEY=abc'), m.scan_transcript(sys.argv[1], False, m.Budget())['state'])")
    p = subprocess.run([PY, "-B", "-c", code, str(TREE)], capture_output=True, text=True, timeout=30)
    assert p.stdout.strip() == "(withheld: time budget) unscanned", p.stderr


def test_redaction_covers_more_token_shapes():
    """pypi, Google OAuth access, Slack app-level, SendGrid tokens and Slack/Discord webhook URLs are masked
    (security audit of stack-who, 2026-10-04: these reach the task text both tools print)."""
    loader = importlib.machinery.SourceFileLoader("stack_tree_redact", str(TREE))
    spec = importlib.util.spec_from_loader("stack_tree_redact", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    for raw in ("pypi-AgEIcHlwaS5vcmcCJGFiY2RlZmdo",
                "ya29.a0AfH6SMBx1234567890abcdefgh",
                "xapp-1-A0123456789-abcdef",
                "SG.abcdefghijklmnopqrstuv.ABCDEFGHIJKLMNOPQRSTUVWXYZ012345",
                "https://hooks.slack.com/services/T000/B000/XXXXXXXXXXXXXXXX",
                "https://discord.com/api/webhooks/123456/abcDEF_ghi-jkl",
                "https://discordapp.com/api/webhooks/123456/abcDEF"):
        out = mod.redact("deploy with %s now" % raw)
        assert raw not in out and "***" in out, (raw, out)
        tail = raw.split("/")[-1] if "/" in raw else raw[6:]
        assert tail not in out, (raw, out)
