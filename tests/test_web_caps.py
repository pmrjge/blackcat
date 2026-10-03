"""hooks/web_caps.py: per-call caps for exa/jina/spider and Spider's anti-bot defaults.

Run: uv run --python 3.14 --with pytest pytest -q tests/test_web_caps.py
"""
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "dot-claude" / "hooks" / "web_caps.py"
PY = "/usr/bin/python3"   # the hooks' own interpreter, as in settings.json


def run(event, env_file):
    out = subprocess.run([PY, str(HOOK)], input=json.dumps(event), capture_output=True, text=True,
                         env={"STACK_ENV_FILE": str(env_file), "PATH": "/usr/bin:/bin"}, timeout=20)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout) if out.stdout.strip() else None


def ev(tool, inp):
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": inp}


def test_self_test():
    out = subprocess.run([PY, str(HOOK), "--self-test"], capture_output=True, text=True, timeout=20)
    assert out.returncode == 0 and "ok" in out.stdout, out.stdout + out.stderr


def test_stack_env_overrides(tmp_path):
    env = tmp_path / "stack.env"
    env.write_text("EXA_MAX_RESULTS=5  # mine\nSPIDER_PROXY_ENABLED=1\nSPIDER_PROXY='isp'\n"
                   "EXA_API_KEY=secret\nJINA_MAX_RESULTS=oops\n")
    out = run(ev("mcp__exa__web_search_exa", {"query": "q", "numResults": 9}), env)
    assert out["hookSpecificOutput"]["updatedInput"]["numResults"] == 5
    assert "permissionDecision" not in out["hookSpecificOutput"]
    out = run(ev("mcp__spider__spider_scrape", {"url": "https://a.example"}), env)
    u = out["hookSpecificOutput"]["updatedInput"]
    assert u["proxy_enabled"] is True and u["proxy"] == "isp"
    out = run(ev("mcp__jina__search_web", {"query": "q"}), env)   # malformed value keeps the default
    assert out["hookSpecificOutput"]["updatedInput"]["num"] == 10


def test_missing_env_and_bad_input(tmp_path):
    assert run(ev("mcp__jina__read_url", {"url": "u", "topk": 3}), tmp_path / "none") is None
    out = subprocess.run([PY, str(HOOK)], input="not json", capture_output=True, text=True, timeout=20)
    assert out.returncode == 0 and out.stdout == ""


def test_refuses_recurring_spider(tmp_path):
    out = run(ev("mcp__spider__spider_crawl", {"url": "https://a.example", "webhooks": {"on_find": "x"}}),
              tmp_path / "none")
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_example_documents_every_knob():
    """stack.env.example lists each knob with the hook's default (the hook's table is the source)."""
    ns = {}
    src = HOOK.read_text()
    exec(compile(src.split("\nKEY_RE")[0], str(HOOK), "exec"), ns)   # KNOBS only
    example = (ROOT / "stack.env.example").read_text()
    for name, (default, _) in ns["KNOBS"].items():
        m = re.search(r"^#%s=(.*)$" % name, example, re.M)
        assert m, name + " missing from stack.env.example"
        assert m.group(1).strip() == str(default), name


def test_settings_wire_the_hook():
    s = json.loads((ROOT / "dot-claude" / "settings.json").read_text())
    groups = [g for g in s["hooks"]["PreToolUse"] if "web_caps.py" in json.dumps(g)]
    assert len(groups) == 1
    pat = re.compile(groups[0]["matcher"])
    for tool in ("mcp__exa__web_fetch_exa", "mcp__jina__read_url", "mcp__spider__spider_crawl"):
        assert pat.search(tool)
    assert not pat.search("mcp__context-mode__ctx_fetch_and_index")
