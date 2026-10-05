"""tests/cache_monitor.py: request extraction, the miss rule, every cause label, the CLI (aggregates
only, exit codes) on synthetic transcripts."""
import importlib.util
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent / "cache_monitor.py"
spec = importlib.util.spec_from_file_location("cache_monitor_under_test", SCRIPT)
cm = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = cm          # dataclasses resolve the module by name
spec.loader.exec_module(cm)

T0 = 1_790_000_000.0
SECRET = "do-not-leak-7f3a"
OPUS, SONNET = "opus-test", "sonnet-test"      # the tier comes from the family name


def iso(t):
    return datetime.fromtimestamp(T0 + t, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def asst(mid, t, ctx, cr, model=OPUS, cc1h=0, inp=3, out=10):
    cc = ctx - cr - inp
    return {"type": "assistant", "timestamp": iso(t),
            "message": {"id": mid, "model": model, "content": [{"type": "text", "text": SECRET}],
                        "usage": {"input_tokens": inp, "cache_creation_input_tokens": cc,
                                  "cache_read_input_tokens": cr, "output_tokens": out,
                                  "cache_creation": {"ephemeral_1h_input_tokens": cc1h,
                                                     "ephemeral_5m_input_tokens": cc - cc1h}}}}


def user(t):
    return {"type": "user", "timestamp": iso(t), "message": {"role": "user", "content": SECRET}}


def hook_start():
    return {"type": "attachment", "attachment": {"type": "hook_success", "hookEvent": "SubagentStart",
                                                 "stdout": "Started " + SECRET}}


def drop(kinds="none", baseline="none"):
    return {"type": "attachment", "attachment": {"type": "thinking_drop", "clientChange": {
        "kinds": kinds, "baseline": baseline, "callNumber": 1}, "newlyDropped": {"reason": "prefix_mismatch"}}}


def compact():
    return {"type": "system", "subtype": "compact_boundary", "compactMetadata": {"trigger": "auto"}}


def write(path, recs):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(r if isinstance(r, str) else json.dumps(r) + "\n" for r in recs))


def m1_with(u=None, **message):
    """A further streamed record of m1 (same numbers) with some usage or message fields replaced."""
    r = asst("m1", 51, 21000, 20000)
    r["message"]["usage"].update(u or {})
    r["message"].update(message)
    return r


def no_id(t):
    r = asst("x", t, 30000, 0)
    del r["message"]["id"]
    return r


# Malformed records: each is skipped or read as empty, and none aborts the report.
MALFORMED = {
    "message-str": [{"type": "assistant", "message": "x"}],
    "id-list": [asst(["m9"], 52, 30000, 0)],
    "tokens-str": [m1_with({"input_tokens": "5", "output_tokens": "99"})],
    "tokens-bool-float": [m1_with({"output_tokens": 99.0, "cache_creation": {"ephemeral_1h_input_tokens": True}})],
    "usage-list": [m1_with(usage=[1])],
    "cache-creation-str": [m1_with({"cache_creation": "x"})],
    "attachment-str": [{"type": "attachment", "attachment": "x"}],
    "client-change-str": [{"type": "attachment", "attachment": {"type": "thinking_drop", "clientChange": "x"}}],
    "kinds-int": [{"type": "attachment", "attachment": {"type": "thinking_drop", "clientChange": {"kinds": 7}}}],
    "no-id-pair": [no_id(52), no_id(53)],             # must not merge under None into a request
}
MAIN_HEAD = [user(0), asst("m0", 0, 20000, 0, cc1h=19997),
             user(40), asst("m1", 50, 15000, 14000),      # streamed: a partial record first
             asst("m1", 51, 21000, 20000),                # the max over the records counts
             {"type": "assistant", "message": {"id": "x", "model": "<synthetic>", "usage": {}}},
             "not json\n"]
MAIN = [*MAIN_HEAD, *(r for recs in MALFORMED.values() for r in recs),
        user(4000), asst("m2", 4001, 22000, 0),           # idle 3950 > 3600 (1h writer)
        compact(), user(4090), asst("m3", 4100, 5000, 0),
        user(4105), asst("m4", 4110, 6000, 1000)]         # nothing explains it
SUB = [hook_start(), user(0), asst("s0", 0, 6000, 0),     # the first start is no resume
       asst("s1", 10, 8000, 6000),                         # hit
       hook_start(), drop(), user(100), asst("s2", 101, 9000, 6000),
       asst("s3", 110, 9500, 0, model=SONNET),
       asst("s4", 120, 9800, 2000, model=SONNET),          # the request after a switch
       drop("systemPromptChanged"), asst("s5", 130, 9900, 3000, model=SONNET),
       hook_start(), asst("s6", 140, 10000, 4000, model=SONNET),
       drop("messagesHistoryChanged", "memory"), asst("s7", 150, 10100, 5000, model=SONNET),
       drop(), asst("s8", 160, 10200, 6000, model=SONNET),
       user(700), asst("s9", 701, 10300, 0, model=SONNET)]  # idle 600 > 300
WANT = {("main", 2): "ttl-expiry", ("main", 3): "compaction", ("main", 4): "unexplained",
        ("coder", 2): "resume-thinking-drop", ("coder", 3): "model-change", ("coder", 4): "model-change",
        ("coder", 5): "system-prompt", ("coder", 6): "resume", ("coder", 7): "history-rewrite",
        ("coder", 8): "thinking-drop", ("coder", 9): "ttl-expiry"}


@pytest.fixture
def root(tmp_path):
    proj = tmp_path / "projects" / "-repo"
    write(proj / "sess-1.jsonl", MAIN)
    write(proj / "sess-1" / "subagents" / "agent-aaa.jsonl", SUB)
    (proj / "sess-1" / "subagents" / "agent-aaa.meta.json").write_text(json.dumps({"agentType": "coder"}))
    return tmp_path / "projects"


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                          check=False)


def test_request_extraction_dedupes_streams_and_skips_synthetic(root):
    th = cm.parse_thread(root / "-repo" / "sess-1.jsonl", "sess-1", "main", "main")
    assert [q.k for q in th.reqs] == [0, 1, 2, 3, 4]
    assert (th.reqs[1].ctx, th.reqs[1].cr) == (21000, 20000)
    assert th.reqs[3].marks == {"compact": True}


def _summary(path):
    th = cm.parse_thread(path, "s", "main", "main")
    return [(q.k, q.model, q.inp, q.cc, q.cc1h, q.cr, q.out, q.ts_first, q.ts_last) for q in th.reqs]


@pytest.mark.parametrize("name", sorted(MALFORMED))
def test_malformed_record_is_skipped_or_read_as_empty(tmp_path, name):
    """One record with wrong field types next to well-formed ones: same requests, same numbers."""
    bad = MALFORMED[name]
    tail = MAIN[len(MAIN_HEAD) + sum(map(len, MALFORMED.values())):]
    write(tmp_path / "good.jsonl", [*MAIN_HEAD, *tail])
    write(tmp_path / "bad.jsonl", [*MAIN_HEAD, *bad, *tail])
    want = _summary(tmp_path / "good.jsonl")
    assert len(want) == 5
    assert _summary(tmp_path / "bad.jsonl") == want


def test_non_string_model_reads_as_none(tmp_path):
    write(tmp_path / "t.jsonl", [asst("a", 0, 5000, 0, model=5), asst("b", 10, 9000, 0, model=["x"])])
    th = cm.parse_thread(tmp_path / "t.jsonl", "s", "main", "main")
    assert [q.model for q in th.reqs] == [None, None]
    res = cm.analyse([th])                      # the price tier of a None model is opus
    assert res["totals"]["all"]["miss_n"] == 1


def test_token_counts_are_ints_only():
    assert [cm.tokens(x) for x in (7, 0, True, False, "5", 5.0, None, [1])] == [7, 0, 0, 0, 0, 0, 0, 0]


def test_every_cause_label(root):
    res = cm.analyse([cm.parse_thread(*f) for f in cm.discover(root, None, 0)])
    got = {(m["type"], m["k"]): m["cause"] for m in res["misses"]}
    assert got == WANT
    assert sum(v["n"] for v in res["by_cause"].values()) == len(WANT)


def test_totals_split_gap_and_no_gap(root):
    res = cm.analyse([cm.parse_thread(*f) for f in cm.discover(root, None, 0)])
    t = res["totals"]
    assert t["main"]["requests"] == 5 and t["sub"]["requests"] == 10
    assert t["main"]["nogap_n"] == 1 and t["main"]["miss_n"] == 3
    assert t["sub"]["nogap_n"] == 7 and t["sub"]["miss_n"] == 8
    assert t["main"]["nogap_tok"] == 4000 and t["main"]["miss_tok"] == 21000 + 5000 + 4000
    reads = 20000 + 1000
    ctx = 20000 + 21000 + 22000 + 5000 + 6000
    assert t["main"]["read_share"] == pytest.approx(reads / ctx)
    # the main no-gap miss: 4000 tokens x (Opus 5m write 5.00 - read 0.20) $/MTok
    assert t["main"]["nogap_usd"] == pytest.approx(4000 * 4.8 / 1e6)
    assert 0 < t["all"]["nogap_usd_share"] < 1


def test_min_miss_threshold(root):
    res = cm.analyse([cm.parse_thread(*f) for f in cm.discover(root, None, 0)], min_miss=6000)
    assert {(m["type"], m["k"]) for m in res["misses"]} == {
        ("main", 2), ("coder", 3), ("coder", 4), ("coder", 5), ("coder", 9)}


def test_discover_filters_sessions_and_age(root, tmp_path):
    write(root / "-other" / "sess-2.jsonl", MAIN)
    assert {f[1] for f in cm.discover(root, ["sess-2"], 0)} == {"sess-2"}
    assert len(cm.discover(root, None, 0)) == 3
    old = time.time() - 2 * 86400
    for f in root.rglob("*.jsonl"):
        os.utime(f, (old, old))
    assert cm.discover(root, None, 1) == [] and len(cm.discover(root, None, 3)) == 3
    assert cm.discover(tmp_path / "missing", None, 0) == []


def test_cli_prints_aggregates_only(root):
    for args in (["--list"], ["--json", "--list"], ["--json"]):
        r = run("--root", root, "--days", "0", *args)
        assert r.returncode == 0, r.stderr
        assert SECRET not in r.stdout
    data = json.loads(run("--root", root, "--days", "0", "--json").stdout)
    assert data["misses"] == [] and data["totals"]["all"]["nogap_n"] == 8
    text = run("--root", root, "--days", "0", "--list").stdout
    assert "resume-thinking-drop" in text and "no-gap" in text


def test_cli_exit_codes(root, tmp_path):
    assert run("--root", root, "--days", "0", "--fail-over", 0).returncode == 1
    assert run("--root", root, "--days", "0", "--fail-over", 100).returncode == 0
    assert run("--root", tmp_path / "empty", "--days", "0").returncode == 2
