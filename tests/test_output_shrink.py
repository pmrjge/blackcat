"""hooks/output_shrink.py: the PostToolUse output shrink (Stage 4 lever L2).

Run: uv run --no-project --python 3.13 --with pytest pytest -q tests/test_output_shrink.py
Every test works on a copy of dot-claude/hooks/output_shrink.py and dot-claude/bin/stack-tree under
tmp_path, with its own HOME, CLAUDE_PROJECT_DIR and CLAUDE_CONFIG_DIR; nothing in the repository or ~
is written. OUTPUT_SHRINK_ROOT=<checkout> tests another checkout (the mutation check uses it).
"""
import copy
import importlib.util
import itertools
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(os.environ.get("OUTPUT_SHRINK_ROOT") or Path(__file__).resolve().parents[1])
HOOKS_SRC = ROOT / "dot-claude" / "hooks"
BIN_SRC = ROOT / "dot-claude" / "bin"
PY = sys.executable
_N = itertools.count()

pytestmark = pytest.mark.skipif(sys.version_info < (3, 13), reason="the hook floor is Python 3.13")

GHP = "ghp" + "_" + "Q7wX" * 9                     # fake credentials, assembled so no scanner flags the file
AKIA = "AKIA" + "Z" * 16
PEM = ["-----BEGIN RSA PRIVATE" + " KEY-----", "MIIEowIBAAKCAQEA" + "x" * 48, "-----END RSA PRIVATE" + " KEY-----"]


# ---------------------------------------------------------------- fixtures and helpers
def install(c, stack_tree=True):
    (c / "hooks").mkdir(parents=True)
    (c / "bin").mkdir()
    shutil.copy2(HOOKS_SRC / "output_shrink.py", c / "hooks" / "output_shrink.py")
    if stack_tree:
        shutil.copy2(BIN_SRC / "stack-tree", c / "bin" / "stack-tree")
    return c


def load(c):
    name = "output_shrink_t%d" % next(_N)
    spec = importlib.util.spec_from_file_location(name, c / "hooks" / "output_shrink.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def hk(tmp_path, monkeypatch):
    tmp = tmp_path.resolve()
    home, proj = tmp / "home", tmp / "proj"
    home.mkdir()
    proj.mkdir()
    for k in list(os.environ):
        if k.startswith("STACK_OUTPUT_SHRINK") or k in ("CLAUDE_PROJECT_DIR", "CLAUDE_CONFIG_DIR"):
            monkeypatch.delenv(k)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp / "cfgdir"))
    c = install(tmp / "C")
    return SimpleNamespace(tmp=tmp, home=home, proj=proj, c=c, mod=load(c), mp=monkeypatch)


def setmode(hk, m):
    hk.mp.setenv("STACK_OUTPUT_SHRINK", m)


def wdir(hk):
    return hk.proj / ".claude-work" / "output-shrink"


def rows(hk):
    p = wdir(hk) / "log.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def spills(hk):
    d = wdir(hk) / "spill"
    return sorted(d.iterdir()) if d.exists() else []


def bash_ev(hk, cmd, stdout, stderr="", sid="s1", aid="a1", tuid="toolu_01ABC", **resp):
    r = {"stdout": stdout, "stderr": stderr, "interrupted": False, "isImage": False}
    r.update(resp)
    return {"hook_event_name": "PostToolUse", "session_id": sid, "agent_id": aid, "agent_type": "coder",
            "cwd": str(hk.proj), "tool_name": "Bash", "tool_use_id": tuid,
            "tool_input": {"command": cmd, "description": "run"}, "tool_response": r}


def read_ev(hk, path, content, sid="s1", aid="a1", start=1, **inp):
    n = content.count("\n") + 1
    i = {"file_path": str(path)}
    i.update(inp)
    return {"hook_event_name": "PostToolUse", "session_id": sid, "agent_id": aid, "agent_type": "coder",
            "cwd": str(hk.proj), "tool_name": "Read", "tool_use_id": "toolu_02XYZ", "tool_input": i,
            "tool_response": {"type": "text", "file": {"filePath": str(path), "content": content, "numLines": n,
                                                       "startLine": start, "totalLines": n}}}


def sized(n, unit="." * 99):
    """Exactly n characters, lines of len(unit)."""
    s = (unit + "\n") * (n // (len(unit) + 1) + 1)
    return s[:n]


def build_log(n=3000, errs=(), summary=None):
    lines = ["step %05d ok" % i for i in range(n)]
    for i, s in errs:
        lines[i] = s
    if summary:
        lines[-2] = summary
    return "\n".join(lines)


def updated(out):
    assert out is not None
    return out["hookSpecificOutput"]["updatedToolOutput"]


# ---------------------------------------------------------------- shadow mode: logs only
def test_shadow_never_changes_output_and_writes_no_spill(hk):
    setmode(hk, "shadow")
    text = build_log(errs=[(1500, "Error: boom")], summary="1 failed, 9 passed")
    ev = bash_ev(hk, "make test", text)
    before = copy.deepcopy(ev)
    assert hk.mod.handle(ev) is None
    big = "\n".join("def f%d():\n    return %d" % (i, i) for i in range(2000))
    assert hk.mod.handle(read_ev(hk, hk.proj / "big.py", big)) is None
    assert ev == before
    r = rows(hk)
    assert [x["tool"] for x in r] == ["Bash", "Read"]
    assert all(x["mode"] == "shadow" and x["cut"] is True for x in r)
    assert all(0 < x["kept_chars"] < x["chars"] for x in r)
    assert spills(hk) == [] and not (wdir(hk) / "spill").exists()


@pytest.mark.parametrize("value", [None, "", "yes", "enforce", "ON?"])
def test_mode_defaults_to_shadow(hk, value):
    if value is not None:
        setmode(hk, value)
    assert hk.mod.mode() == "shadow"
    assert hk.mod.handle(bash_ev(hk, "make", sized(30000))) is None
    assert rows(hk)[0]["mode"] == "shadow" and spills(hk) == []


def test_off_writes_nothing(hk):
    setmode(hk, "off")
    assert hk.mod.handle(bash_ev(hk, "make", sized(30000))) is None
    assert not (hk.proj / ".claude-work").exists()


def test_mode_value_is_case_and_space_tolerant(hk):
    setmode(hk, " On ")
    assert hk.mod.mode() == "on"


# ---------------------------------------------------------------- on mode: the first chunk holds what matters
def test_on_keeps_errors_summary_head_tail_in_order(hk):
    setmode(hk, "on")
    errs = [(10, "error: first failure here"), (1500, "Traceback (most recent call last):"),
            (1501, '  File "x.py", line 3, in <module>'), (2990, "ValueError: the decisive line")]
    text = build_log(errs=errs, summary="=== 1 failed, 99 passed in 3.21s ===")
    out = updated(hk.mod.handle(bash_ev(hk, "uv run pytest", text)))
    s = out["stdout"]
    assert out["stderr"] == ""
    for _, line in errs:
        assert line in s
    assert "=== 1 failed, 99 passed in 3.21s ===" in s
    assert "step 00000 ok" in s and "step 02999 ok" in s          # head and tail
    body = s.split("\n")
    assert body[0].startswith("[output-shrink:") and str(hk.proj) in body[0]
    pos = [s.index(line) for _, line in errs]
    assert pos == sorted(pos)                                      # original order
    assert len(s) < 6000 < len(text)


def test_last_error_lines_win_when_errors_exceed_budget(hk):
    setmode(hk, "on")
    errs = [(i, "ERROR: case %04d failed with a long explanation of what went wrong" % i) for i in range(5, 2700, 7)]
    errs.append((2750, "FATAL: the run stopped here"))
    lines = build_log(errs=errs).split("\n")
    lines[2751:] = ["teardown %04d " % i + "." * 90 for i in range(2751, 3000)]   # a long tail the tail budget can't reach past
    text = "\n".join(lines)
    s = updated(hk.mod.handle(bash_ev(hk, "make check", text)))["stdout"]
    assert "FATAL: the run stopped here" in s                      # the last error line
    assert errs[0][1] in s                                         # and the first one
    r = rows(hk)[-1]
    assert r["err_total"] == len(errs) and 2 <= r["err_kept"] < r["err_total"]


def test_npm_err_lines_count_as_errors(hk):
    lines = ["npm ERR! code ELIFECYCLE", "npm ERR! errno 2"]
    assert all(hk.mod.ERR_RE.search(x) for x in lines)


def test_stderr_is_merged_into_the_digest_and_other_fields_kept(hk):
    setmode(hk, "on")
    out = updated(hk.mod.handle(bash_ev(hk, "make", build_log(), stderr="warning: x\nfatal: stderr line",
                                        returnCodeInterpretation="ok")))
    assert "fatal: stderr line" in out["stdout"] and out["stderr"] == ""
    assert out["interrupted"] is False and out["isImage"] is False and out["returnCodeInterpretation"] == "ok"


def test_render_marks_omitted_ranges_exactly(hk):
    lines = ["l%d" % i for i in range(1, 11)]                     # l1..l10, 1-based line numbers
    s = hk.mod.render(lines, [0, 4, 5], "H")
    assert s.split("\n") == ["H", "l1", "… [lines 2-4 omitted] …", "l5", "l6", "… [lines 7-10 omitted] …"]


def test_long_lines_are_cut_in_the_digest(hk):
    setmode(hk, "on")
    text = build_log(errs=[(2998, "Error: " + "z" * 5000)])
    s = updated(hk.mod.handle(bash_ev(hk, "make", text)))["stdout"]
    assert "Error: " in s and "z" * 400 not in s and "[+4707 chars]" in s


SHAPES = {
    "err-ok": "\n".join(("error %04d" % i) if i % 2 else "ok" for i in range(1400)),
    "err-gap": "\n".join(("error %04d" % i) if i % 2 == 0 else "f" * 20 for i in range(520)),
    "all-err": "\n".join("error: case %d broke" % i for i in range(900)),
    "one-line": "x" * 29000,
    "blank": "\n" * 9000,
}


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_digest_is_bounded_and_saves_a_quarter(hk, shape):
    """Error lines in separate gaps cost a marker each: the digest stays bounded and well under the output."""
    setmode(hk, "on")
    text = SHAPES[shape]
    assert len(text) > 8000
    s = updated(hk.mod.handle(bash_ev(hk, "make", text)))["stdout"]
    assert len(s) * 4 <= len(text) * 3 and len(s) <= 9000


def test_logged_kept_chars_is_the_real_digest_size(hk):
    setmode(hk, "on")
    s = updated(hk.mod.handle(bash_ev(hk, "make", build_log(errs=[(50, "error: x")]))))["stdout"]
    assert rows(hk)[-1]["kept_chars"] == len(s)
    big = "\n".join("def f%d():\n    return %d" % (i, i) for i in range(2000))
    o = hk.mod.handle(read_ev(hk, hk.proj / "big.py", big))
    hso = o["hookSpecificOutput"]
    assert rows(hk)[-1]["kept_chars"] == len(hso["updatedToolOutput"]["file"]["content"]) + len(hso["additionalContext"])


def test_shadow_logs_the_same_decision_as_on(hk):
    text = build_log(errs=[(7, "error: a"), (2500, "Error: b")])
    setmode(hk, "shadow")
    hk.mod.handle(bash_ev(hk, "make", text, sid="s-shadow"))
    setmode(hk, "on")
    hk.mod.handle(bash_ev(hk, "make", text, sid="s-on"))
    a, b = rows(hk)
    for k in ("cut", "kept", "kept_lines", "kept_chars", "err_total", "err_kept", "cls", "thr", "chars"):
        assert a[k] == b[k], k


# ---------------------------------------------------------------- Read
def test_read_keeps_a_contiguous_head_and_pages_the_rest(hk):
    setmode(hk, "on")
    big = "\n".join("def f%d():\n    return %d" % (i, i) for i in range(2000))
    ev = read_ev(hk, hk.proj / "src" / "big.py", big, start=1)
    hso = hk.mod.handle(ev)["hookSpecificOutput"]
    f = hso["updatedToolOutput"]["file"]
    assert big.startswith(f["content"]) and len(f["content"]) <= hk.mod.READ_HEAD
    k = f["content"].count("\n") + 1
    assert f["numLines"] == k and f["startLine"] == 1 and f["totalLines"] == 4000
    assert f["filePath"] == str(hk.proj / "src" / "big.py") and hso["updatedToolOutput"]["type"] == "text"
    note = hso["additionalContext"]
    assert "offset=%d" % (k + 1) in note and "lines 1-%d" % k in note
    m = re.search(r"^L(\d+): def f\d+\(\):$", note, re.MULTILINE)
    assert m and int(m.group(1)) in (k + 1, k + 2)                 # the outline starts at the hidden part
    assert spills(hk) == []                                        # the file itself is the full output


def test_read_first_line_too_long_is_cut_and_said(hk):
    setmode(hk, "on")
    big = "x" * 30000 + "\nsecond"
    hso = hk.mod.handle(read_ev(hk, hk.proj / "min.js", big))["hookSpecificOutput"]
    assert hso["updatedToolOutput"]["file"]["numLines"] == 1 and "(line 1 cut)" in hso["additionalContext"]


@pytest.mark.parametrize("rel", ["SKILL.md", "CLAUDE.md", "x/skills/a/references/r.md", "x/rules/r.md",
                                 "x/agents/coder.md", "AGENTS.md"])
def test_prompt_files_never_shrunk(hk, rel):
    setmode(hk, "on")
    assert hk.mod.handle(read_ev(hk, hk.proj / rel, sized(50000))) is None
    assert rows(hk)[-1]["skip"] == "prompt-file"


@pytest.mark.parametrize("inp", [{"offset": 1}, {"limit": 500}, {"offset": 10, "limit": 100}])
def test_ranged_read_never_shrunk(hk, inp):
    setmode(hk, "on")
    assert hk.mod.handle(read_ev(hk, hk.proj / "a.py", sized(50000), **inp)) is None
    assert rows(hk)[-1]["skip"] == "ranged"


@pytest.mark.parametrize("resp", [{"type": "image", "file": {"base64": "A" * 50000, "type": "image/png"}},
                                  {"type": "notebook", "file": {"filePath": "n.ipynb", "content": "x" * 50000}}])
def test_non_text_read_untouched(hk, resp):
    setmode(hk, "on")
    ev = read_ev(hk, hk.proj / "a.png", "x")
    ev["tool_response"] = resp
    assert hk.mod.handle(ev) is None and rows(hk)[-1]["skip"] == "shape"


# ---------------------------------------------------------------- thresholds per tool
@pytest.mark.parametrize("cmd,thr", [("make test", 8000), ("cd x && FOO=1 make", 8000), ("sed -n 1,400p f", 20000),
                                     ("cat a b", 20000), ("cd /r && git diff HEAD~1", 20000),
                                     ("git -C /r show HEAD", 20000), ("git -C /r log -p", 20000),
                                     ("FOO=1 tail -n 900 f", 20000), ("git status", 8000)])
def test_bash_threshold_boundary(hk, cmd, thr):
    setmode(hk, "shadow")
    hk.mod.handle(bash_ev(hk, cmd, sized(thr), sid="at"))
    hk.mod.handle(bash_ev(hk, cmd, sized(thr + 1), sid="over"))
    at, over = rows(hk)
    assert at["thr"] == thr and at["cut"] is False and "skip" not in at
    assert over["cut"] is True


def test_read_threshold_boundary(hk):
    setmode(hk, "shadow")
    hk.mod.handle(read_ev(hk, hk.proj / "a.py", sized(20000), sid="at"))
    hk.mod.handle(read_ev(hk, hk.proj / "a.py", sized(20001), sid="over"))
    at, over = rows(hk)
    assert (at["cls"], at["thr"], at["cut"], over["cut"]) == ("read", 20000, False, True)


@pytest.mark.parametrize("value,want", [("5000", 5000), ("100", 4000), (str(10 ** 9), 200000), ("abc", 8000),
                                        ("", 8000)])
def test_threshold_env_override_clamped(hk, value, want):
    hk.mp.setenv("STACK_OUTPUT_SHRINK_BASH", value)
    assert hk.mod.thresholds()["bash"] == want


def test_small_outputs_are_logged_without_a_digest(hk):
    setmode(hk, "on")
    assert hk.mod.handle(bash_ev(hk, "ls", "a\nb\n")) is None
    r = rows(hk)[-1]
    assert r["cut"] is False and "kept" not in r and r["chars"] == 4


# ---------------------------------------------------------------- full output reachable
def test_same_call_again_returns_full_output(hk):
    setmode(hk, "on")
    text = build_log()
    assert hk.mod.handle(bash_ev(hk, "make", text)) is not None
    assert hk.mod.handle(bash_ev(hk, "make", text)) is None             # asked twice: unshrunk
    assert rows(hk)[-1]["skip"] == "repeat"
    assert hk.mod.handle(bash_ev(hk, "make", text, aid="other")) is not None   # another agent: its own first call
    assert hk.mod.handle(bash_ev(hk, "make", text, sid="s2")) is not None      # another session


def test_reading_a_spill_is_never_shrunk(hk):
    setmode(hk, "on")
    hk.mod.handle(bash_ev(hk, "make", build_log()))
    sp = spills(hk)[0]
    assert hk.mod.handle(bash_ev(hk, "cat %s" % sp, sized(30000))) is None
    assert rows(hk)[-1]["skip"] == "reread" and rows(hk)[-1]["refs"] == [sp.name]
    assert hk.mod.handle(read_ev(hk, sp, sized(30000))) is None
    assert rows(hk)[-1]["skip"] == "reread"


def test_grep_over_the_spill_directory_is_never_shrunk(hk):
    setmode(hk, "on")
    out = hk.mod.handle(bash_ev(hk, "rg -n Error .claude-work/output-shrink/spill/", sized(30000)))
    assert out is None and rows(hk)[-1]["skip"] == "reread"


@pytest.mark.parametrize("extra", [{"interrupted": True}, {"isImage": True}, {"backgroundTaskId": "b1"}])
def test_special_bash_results_untouched(hk, extra):
    setmode(hk, "on")
    assert hk.mod.handle(bash_ev(hk, "make", sized(30000), **extra)) is None
    assert rows(hk)[-1]["skip"] == "special"


# ---------------------------------------------------------------- spill file: 0600, safe paths
def test_spill_is_0600_in_0700_dirs_under_the_project(hk):
    setmode(hk, "on")
    text = build_log()
    out = updated(hk.mod.handle(bash_ev(hk, "make", text)))
    [sp] = spills(hk)
    assert stat.S_IMODE(sp.stat().st_mode) == 0o600
    assert stat.S_IMODE((wdir(hk) / "spill").stat().st_mode) == 0o700
    assert stat.S_IMODE(wdir(hk).stat().st_mode) == 0o700
    assert stat.S_IMODE((wdir(hk) / "log.jsonl").stat().st_mode) == 0o600
    assert (wdir(hk) / ".gitignore").read_text() == "*\n"
    assert sp.parent == hk.proj / ".claude-work" / "output-shrink" / "spill"
    assert hk.mod.SPILL_NAME_RE.match(sp.name)
    assert str(sp) in out["stdout"].split("\n")[0]
    assert sp.read_text() == text                                  # no credentials here: byte-identical
    assert rows(hk)[-1]["spill"] == sp.name


def test_existing_wide_dirs_are_tightened(hk):
    setmode(hk, "on")
    (wdir(hk) / "spill").mkdir(parents=True, mode=0o755)
    os.chmod(wdir(hk), 0o755)
    os.chmod(wdir(hk) / "spill", 0o755)
    hk.mod.handle(bash_ev(hk, "make", build_log()))
    assert stat.S_IMODE(wdir(hk).stat().st_mode) == 0o700
    assert stat.S_IMODE((wdir(hk) / "spill").stat().st_mode) == 0o700


@pytest.mark.parametrize("tuid", ["../../../etc/x;rm -rf ~/" + "A" * 80, "toolu_01/../../../../escape", "toolu\x00x/..",
                                  "", None])
def test_hostile_tool_use_id_cannot_steer_the_spill_path(hk, tuid):
    setmode(hk, "on")
    hk.mod.handle(bash_ev(hk, "make", build_log(), tuid=tuid))
    [sp] = spills(hk)
    assert sp.parent == wdir(hk) / "spill" and hk.mod.SPILL_NAME_RE.match(sp.name)
    assert [p.name for p in (hk.proj / ".claude-work").iterdir()] == ["output-shrink"]


@pytest.mark.parametrize("link", [".claude-work", ".claude-work/output-shrink", ".claude-work/output-shrink/spill"])
def test_symlink_below_the_project_disables_writes(hk, link):
    setmode(hk, "on")
    target = hk.tmp / "elsewhere"
    target.mkdir()
    lp = hk.proj / link
    lp.parent.mkdir(parents=True, exist_ok=True)
    if link.endswith("spill"):
        os.chmod(lp.parent, 0o700)
    lp.symlink_to(target)
    assert hk.mod.handle(bash_ev(hk, "make", build_log())) is None
    assert list(target.iterdir()) == []


def test_symlinked_log_is_not_followed(hk):
    setmode(hk, "on")
    wdir(hk).mkdir(parents=True)
    victim = hk.tmp / "victim.txt"
    victim.write_text("keep")
    (wdir(hk) / "log.jsonl").symlink_to(victim)
    hk.mod.handle(bash_ev(hk, "make", build_log()))
    assert victim.read_text() == "keep"


def test_fifo_log_does_not_hang(hk):
    wdir(hk).mkdir(parents=True)
    os.mkfifo(wdir(hk) / "log.jsonl")
    env = dict(os.environ, STACK_OUTPUT_SHRINK="on")
    p = subprocess.run([PY, str(hk.c / "hooks" / "output_shrink.py")], input=json.dumps(bash_ev(hk, "make", build_log())),
                       capture_output=True, text=True, env=env, timeout=15, check=False)
    assert p.returncode == 0


@pytest.mark.parametrize("where", ["home", "root", "relative", "missing", "config", "hookdir"])
def test_refused_project_roots_write_nothing(hk, where):
    setmode(hk, "on")
    proj = {"home": str(hk.home), "root": "/", "relative": "proj", "missing": str(hk.tmp / "nope"),
            "config": str(hk.tmp / "cfgdir" / "p"), "hookdir": str(hk.c / "x")}[where]
    if where in ("config", "hookdir"):
        os.makedirs(proj)
    hk.mp.setenv("CLAUDE_PROJECT_DIR", proj)
    ev = bash_ev(hk, "make", build_log())
    ev["cwd"] = proj
    assert hk.mod.handle(ev) is None
    assert not list(hk.tmp.glob("**/.claude-work"))


def test_unwritable_spill_dir_means_no_shrink(hk):
    setmode(hk, "on")
    (wdir(hk) / "spill").mkdir(parents=True)
    os.chmod(wdir(hk) / "spill", 0o500)
    try:
        assert hk.mod.handle(bash_ev(hk, "make", build_log())) is None
        r = rows(hk)[-1]
        assert r["cut"] is False and r["skip"].startswith("spill-failed")
    finally:
        os.chmod(wdir(hk) / "spill", 0o700)


def test_prune_removes_only_own_old_files(hk):
    setmode(hk, "on")
    sd = wdir(hk) / "spill"
    sd.mkdir(parents=True)
    old = sd / "20260101T000000Z-bash-toolu_old-0123abcd.txt"
    old.write_text("x")
    mine = sd / "notes.txt"
    mine.write_text("y")
    t = time.time() - 8 * 86400
    os.utime(old, (t, t))
    os.utime(mine, (t, t))
    hk.mod.handle(bash_ev(hk, "make", build_log()))
    assert not old.exists() and mine.exists()


def test_git_status_stays_clean(hk):
    if not shutil.which("git"):
        pytest.skip("git missing")
    subprocess.run(["git", "init", "-q", str(hk.proj)], check=True)
    setmode(hk, "on")
    hk.mod.handle(bash_ev(hk, "make", build_log()))
    st = subprocess.run(["git", "-C", str(hk.proj), "status", "--porcelain", "--untracked-files=all"],
                        capture_output=True, text=True, check=True)
    assert spills(hk) and st.stdout == ""


# ---------------------------------------------------------------- no secret leakage beyond the original
SECRET_LINES = ["export API_KEY=sk-live-Abc123Def456Ghi789", "Authorization: Bearer abcdefghijklmnop123456",
                "token " + GHP, "aws " + AKIA, "clone https://bob:hunter2pw@git.example.com/r.git"] + PEM


def test_spill_masks_credentials_and_keeps_line_numbers(hk):
    setmode(hk, "on")
    lines = build_log().split("\n")
    lines[100:100 + len(SECRET_LINES)] = SECRET_LINES
    text = "\n".join(lines)
    hk.mod.handle(bash_ev(hk, "make", text))
    data = spills(hk)[0].read_text()
    for needle in ("sk-live-Abc123Def456Ghi789", "abcdefghijklmnop123456", GHP, AKIA, "hunter2pw", PEM[1]):
        assert needle not in data, needle
    assert data.count("\n") == text.count("\n")                     # same lines: the digest's ranges hold
    assert data.split("\n")[0] == lines[0] and data.split("\n")[-1] == lines[-1]


def test_digest_only_holds_lines_of_the_original(hk):
    setmode(hk, "on")
    lines = build_log(errs=[(5, "error: " + GHP)]).split("\n")
    s = updated(hk.mod.handle(bash_ev(hk, "make", "\n".join(lines))))["stdout"]
    orig = set(lines)
    for x in s.split("\n")[1:]:
        assert x in orig or re.fullmatch(r"… \[lines \d+-\d+ omitted\] …", x), x


def test_log_holds_no_output_command_or_path(hk):
    setmode(hk, "on")
    cmd = 'git -c http.extraheader="AUTHORIZATION: basic %s" -c user.password=%s fetch origin' % (GHP, AKIA)
    hk.mod.handle(bash_ev(hk, cmd, build_log(errs=[(3, "error: SECRETOUTPUT")])))
    hk.mod.handle(bash_ev(hk, GHP + " --flag", sized(30000)))
    hk.mod.handle(read_ev(hk, hk.proj / "private-name-xyz.py", sized(30000)))
    raw = (wdir(hk) / "log.jsonl").read_text()
    for needle in (GHP[:12], AKIA[:10], "SECRETOUTPUT", "private-name-xyz", "extraheader", "AUTHORIZATION", "step 0"):
        assert needle not in raw, needle
    fams = [r["fam"] for r in rows(hk)]
    assert fams[:2] == ["git fetch", "other"]


@pytest.mark.parametrize("cmd,fam", [("git -C /r diff", "git diff"), ("cd a && sed -n 1p f", "sed"),
                                     ("A=1 B=2 cat f", "cat"), ("uv run pytest", "uv run"),
                                     ("/usr/bin/head -5 f", "head"), ("$(cat tok) x", "other"), ("", "other")])
def test_family(hk, cmd, fam):
    assert hk.mod.family(cmd) == fam


def test_no_credential_tables_means_no_spill_and_no_shrink(hk):
    c = install(hk.tmp / "C2", stack_tree=False)
    mod = load(c)
    setmode(hk, "on")
    assert mod.handle(bash_ev(hk, "make", build_log())) is None
    assert spills(hk) == [] and rows(hk)[-1]["skip"].startswith("spill-failed")


def test_scrub_masks_a_whole_pem_block(hk):
    s = hk.mod.scrub("\n".join(["a"] + PEM + ["b"]))
    assert s.split("\n") == ["a", "***", "***", "***", "b"]


# ---------------------------------------------------------------- never rewrites the command
def test_output_never_touches_the_input(hk):
    setmode(hk, "on")
    big = "\n".join("def f%d():\n    return %d" % (i, i) for i in range(2000))
    for ev in (bash_ev(hk, "make test", build_log()), read_ev(hk, hk.proj / "big.py", big)):
        before = copy.deepcopy(ev)
        out = hk.mod.handle(ev)
        assert ev == before                                        # the event is not mutated
        assert set(out) == {"hookSpecificOutput"}
        hso = out["hookSpecificOutput"]
        assert hso["hookEventName"] == "PostToolUse"
        assert set(hso) <= {"hookEventName", "updatedToolOutput", "additionalContext"}
        assert "updatedInput" not in json.dumps(out) and "permissionDecision" not in json.dumps(out)
        assert set(hso["updatedToolOutput"]) == set(ev["tool_response"])


@pytest.mark.parametrize("event,tool", [("PreToolUse", "Bash"), ("PostToolUseFailure", "Bash"), ("PostToolUse", "Edit"),
                                        ("PostToolUse", "Grep")])
def test_other_events_and_tools_ignored(hk, event, tool):
    setmode(hk, "on")
    ev = bash_ev(hk, "make", sized(30000))
    ev["hook_event_name"], ev["tool_name"] = event, tool
    assert hk.mod.handle(ev) is None and not (hk.proj / ".claude-work").exists()


def test_settings_registers_posttooluse_bash_read_only():
    s = json.loads((ROOT / "dot-claude" / "settings.json").read_text())
    hooks = s["hooks"]
    found = []
    for ev, entries in hooks.items():
        for e in entries:
            for h in e.get("hooks", []):
                if "output_shrink" in h.get("command", ""):
                    found.append((ev, e.get("matcher"), h["command"], h.get("timeout")))
    assert found == [("PostToolUse", "Bash|Read", '/bin/sh "__CLAUDE_DIR__/bin/stack-hook" output_shrink', 10)]
    # Phase 0 security review: these two stay pinned (legacy ~/.claude.json fallback; remote flag default)
    assert s["autoCompactEnabled"] is True and s["env"]["MAX_MCP_OUTPUT_TOKENS"] == "25000"
    assert "STACK_OUTPUT_SHRINK" not in s.get("env", {})          # shipped in shadow mode (the default)


def test_installer_and_doctor_wire_the_hook():
    """install.sh stages, tracks and precompiles the module; the doctor checks its bytecode; the
    installer's STACK_HOOK_RE claims its settings.json entry as the stack's."""
    inst = (ROOT / "install.sh").read_text()
    assert re.search(r"^stage_script 755 hooks/output_shrink\.py$", inst, re.MULTILINE)
    assert '"hooks/output_shrink.py"' in inst.split("STACK_SCRIPTS = [", 1)[1].split("]", 1)[0]
    loop = re.search(r"^\s*for m in ([a-z_ ]+); do\n\s*if \[ -f \"\$C/hooks/\$m\.py\" \]", inst, re.MULTILINE)
    assert loop and "output_shrink" in loop.group(1).split()
    m = re.search(r'^STACK_HOOK_RE = re\.compile\(r"([^"]+)"\)$', inst, re.MULTILINE)
    assert m and re.search(m.group(1), '/bin/sh "__CLAUDE_DIR__/bin/stack-hook" output_shrink')
    doc = (ROOT / "dot-claude" / "bin" / "doctor.sh").read_text()
    fresh = re.search(r'^for m in \(([^)]*)\):\n    src = os\.path\.join\(h, m \+ "\.py"\)', doc, re.MULTILINE)
    assert fresh and '"output_shrink"' in fresh.group(1)


# ---------------------------------------------------------------- entry points
def stub_tree(tmp):
    c = tmp / "S"
    shutil.copytree(HOOKS_SRC, c / "hooks", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (c / "bin").mkdir()
    shutil.copy2(BIN_SRC / "stack-tree", c / "bin" / "stack-tree")
    return c


@pytest.mark.parametrize("md", ["shadow", "on"])
def test_through_the_stack_hook_stub(hk, md):
    c = stub_tree(hk.tmp)
    env = dict(os.environ, STACK_OUTPUT_SHRINK=md)
    p = subprocess.run([PY, str(c / "hooks" / "stack_hook.py"), "output_shrink"],
                       input=json.dumps(bash_ev(hk, "make", build_log())), capture_output=True, text=True, env=env,
                       timeout=30, check=False)
    assert p.returncode == 0, p.stderr
    if md == "shadow":
        assert p.stdout == "" and rows(hk)[-1]["cut"] is True
    else:
        assert json.loads(p.stdout)["hookSpecificOutput"]["updatedToolOutput"]["stdout"].startswith("[output-shrink:")


@pytest.mark.parametrize("stdin", ["", "not json", "[]", ('{"hook_event_name": "PostToolUse", "tool_name": "Bash", '
                                                            '"tool_response": "a string", "tool_input": {"command": "x"}}')])
def test_garbage_input_fails_open(hk, stdin):
    env = dict(os.environ, STACK_OUTPUT_SHRINK="on")
    p = subprocess.run([PY, str(hk.c / "hooks" / "output_shrink.py")], input=stdin, capture_output=True, text=True,
                       env=env, timeout=15, check=False)
    assert p.returncode == 0 and p.stdout == ""


def test_self_test_passes(hk):
    p = subprocess.run([PY, str(hk.c / "hooks" / "output_shrink.py"), "--self-test"], capture_output=True, text=True,
                       env=dict(os.environ), timeout=30, check=False)
    assert p.returncode == 0 and "self-test: ok" in p.stdout, p.stdout + p.stderr


def test_report_reads_the_log(hk):
    setmode(hk, "shadow")
    hk.mod.handle(bash_ev(hk, "make", build_log(errs=[(9, "error: q")])))
    hk.mod.handle(bash_ev(hk, "make", build_log(errs=[(9, "error: q")])))
    hk.mod.handle(bash_ev(hk, "ls", "a\n"))
    rep = hk.mod.report(hk.mod.load_rows([str(hk.proj)]))
    assert rep["rows"] == 3 and rep["cut_events"] == 1 and rep["by_class"]["bash"]["calls"] == 3
    assert rep["repeat_rate_after_cut"] == 1.0 and rep["error_lines_kept"] == 1.0
    assert set(rep["sweep"]) == {"4000", "8000", "12000", "20000", "30000"}
    p = subprocess.run([PY, str(hk.c / "hooks" / "output_shrink.py"), "report", str(hk.proj), "--json"],
                       capture_output=True, text=True, env=dict(os.environ), timeout=30, check=False)
    assert p.returncode == 0 and json.loads(p.stdout)["cut_events"] == 1
