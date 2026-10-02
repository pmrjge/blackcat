#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["claude-agent-sdk==0.2.163"]
# ///
"""claude-agent-stack for Agent SDK apps (optional; nothing loads it). options() builds
ClaudeAgentOptions that load the installed stack from its own files; run() runs one prompt and
returns one dict: the final report parsed without an LLM (parse_report), session id, cost, per-model
and per-subagent usage, the delegation ledger path. Import: sys.path.insert(0, "<config>/bin"); import
stack_sdk. CLI: stack_sdk.py "task" [--agent coder] [--max-turns N] [--budget-usd X] [--resume ID]
[--allowed-tools A,B] [--disallowed-tools A,B] [--permission-mode M] [--json-reports]
[--print-options] [--stream]. Docs: skills/claude-code-extensions/references/agent-sdk.md."""
import argparse, asyncio, dataclasses, json, os, re, sys, time

CLEAN = re.compile(r"[*`_ ]*(?P<input>.+?) · (?P<timestamp>\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2})?)"
                   r" · (?P<agent>[A-Za-z0-9_-]+)[*`_ ]*")
FIELD = re.compile(r"(STATUS|RESULT|EVIDENCE|FILES|NEXT):\s*(.*)")
TASK_MSGS = ("TaskStartedMessage", "TaskProgressMessage", "TaskNotificationMessage")


def parse_report(text):
    """Final reply -> {format, input, timestamp, agent, status, result, evidence, files, next}.
    format: json (STACK_REPORT_FORMAT=json; the last JSON line wins), clean (the clean-finish line;
    status done), status (the STATUS block) or text (neither: status None, the reply as result)."""
    r = dict.fromkeys(("input", "timestamp", "agent", "status", "evidence", "next"))
    r.update(format="text", result=(text or "").strip(), files=[])
    body = [ln.strip() for ln in r["result"].splitlines() if ln.strip() and not ln.strip().startswith("```")]
    for ln in reversed(body):
        try:
            obj = json.loads(ln) if ln.startswith("{") else None
        except ValueError:
            continue
        if isinstance(obj, dict) and {"status", "result"} <= obj.keys():
            files = obj.get("files") or []
            return dict(r, **{k: obj.get(k) for k in r if k not in ("format", "files")},
                        format="json", files=[str(f) for f in (files if isinstance(files, list) else [files])])
    m = CLEAN.fullmatch(body[0]) if body else None
    if m:
        r.update(m.groupdict(), format="clean", status="done", result="\n".join(body[1:]))
    starts = [i for i, ln in enumerate(body) if ln.startswith("STATUS:")]
    if not starts:
        return r
    got, key = {}, None
    for ln in body[starts[0]:]:
        f = FIELD.fullmatch(ln)
        key = f.group(1).lower() if f else key
        got[key] = (got.get(key, "") + "\n" + (f.group(2) if f else ln)).strip()
    r.update({k: v for k, v in got.items() if k not in ("files", "status")}, format="status")
    r["status"] = ((got["status"].split() or [""])[0].strip("|*`").lower()) or None
    r["files"] = [p.strip() for p in re.split(r"[,\n]", got.get("files", ""))
                  if p.strip().lower() not in ("", "-", "—", "none", "(none)")]
    return r


def options(agent="blackcat", max_turns=None, budget_usd=None, allowed_tools=(), disallowed_tools=(),
            permission_mode=None, resume=None, fork=False, cwd=None, json_reports=False,
            sources=("user", "project", "local"), **more):
    """ClaudeAgentOptions for the installed stack, every field visible and adjustable
    (dataclasses.replace); `more` is any other ClaudeAgentOptions field (model, effort, hooks...)."""
    from claude_agent_sdk import ClaudeAgentOptions
    return ClaudeAgentOptions(
        setting_sources=list(sources),       # agents, skills, rules, hooks, permissions: the files
        system_prompt={"type": "preset", "preset": "claude_code", "exclude_dynamic_sections": True},
        extra_args={"agent": agent} if agent else {},           # --agent: the main-thread agent
        max_turns=max_turns, max_budget_usd=budget_usd, allowed_tools=list(allowed_tools),
        disallowed_tools=list(disallowed_tools), permission_mode=permission_mode, resume=resume,
        fork_session=fork, cwd=cwd, env={"STACK_REPORT_FORMAT": "json"} if json_reports else {}, **more)


async def run(prompt, opts, on_message=None):
    """Run `prompt`; on_message(msg) sees every SDK message as it streams."""
    from claude_agent_sdk import query
    t0, first, tasks, res = time.monotonic(), None, {}, None
    async for m in query(prompt=prompt, options=opts):
        first = first if first is not None else round(time.monotonic() - t0, 3)
        if on_message:
            on_message(m)
        if type(m).__name__ in TASK_MSGS:                  # subagents and background tasks
            t = tasks.setdefault(m.tool_use_id or m.task_id, {"task_id": m.task_id})
            t.update({k: getattr(m, k) for k in ("description", "status", "usage") if getattr(m, k, None)})
        elif type(m).__name__ == "ResultMessage":
            res = m
    if res is None:
        return {"report": parse_report(""), "error": "no ResultMessage", "first_message_s": first}
    agents = [dict(t, tool_use_id=k, agent=(t.get("description") or "").partition(": ")[0] or None)
              for k, t in tasks.items()]               # label "<type>: <task>" (STACK_AGENT_LABEL)
    state = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return {"report": parse_report(res.result), "session_id": res.session_id, "subtype": res.subtype,
            "is_error": res.is_error, "num_turns": res.num_turns, "duration_ms": res.duration_ms,
            "first_message_s": first, "total_cost_usd": res.total_cost_usd, "usage": res.usage,
            "model_usage": res.model_usage, "agents": agents,
            "ledger": os.path.join(state, "claude-agent-stack", res.session_id, "delegations.md")}


def main(argv=None):
    p = argparse.ArgumentParser(description="Run one prompt on the installed stack (Agent SDK).")
    p.add_argument("prompt")
    for flag, kw in (("--agent", {"default": "blackcat"}), ("--max-turns", {"type": int}),
                     ("--budget-usd", {"type": float}), ("--allowed-tools", {"default": ""}),
                     ("--disallowed-tools", {"default": ""}), ("--permission-mode", {}), ("--resume", {})):
        p.add_argument(flag, **kw)
    for flag in ("--json-reports", "--print-options", "--stream"):
        p.add_argument(flag, action="store_true")
    a = p.parse_args(argv)
    split = lambda s: [x.strip() for x in s.split(",") if x.strip()]  # noqa: E731
    o = options(a.agent, a.max_turns, a.budget_usd, split(a.allowed_tools), split(a.disallowed_tools),
                a.permission_mode, a.resume, json_reports=a.json_reports)
    if a.print_options:
        print(json.dumps({f.name: getattr(o, f.name) for f in dataclasses.fields(o)}, default=repr))
        return 0
    out = asyncio.run(run(a.prompt, o, (lambda m: print(repr(m), file=sys.stderr)) if a.stream else None))
    print(json.dumps(out, default=str))
    bad = out.get("error") or out.get("is_error") or out["report"]["status"] in ("partial", "blocked")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
