#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["claude-agent-sdk==0.2.163"]
# [tool.uv]
# exclude-newer = "2026-10-02T00:00:00Z"
# ///
"""claude-agent-stack for Agent SDK apps (optional; nothing loads it). Hash-locked by stack_sdk.py.lock
beside it (`uv run --locked --script`; install.sh stages both, doctor.sh checks the lock offline).
Session: the supported path (ClaudeSDKClient). It connects, checks that the stack loaded before any prompt
(StackNotLoaded: the agents, the SessionStart hooks, agent_guard's session-start marker), answers permission
requests through one host (none: unattended, deny by default, stops at the plan; tty; an app callable),
bounds the run and returns one dict per prompt. run(): the legacy one-shot (query()), no load check.
parse_stream(lines): the same dict from `claude -p --output-format stream-json --verbose`. options() and
parse_report() as in v1. Import: sys.path.insert(0, "<config>/bin"). CLI: stack_sdk.py --help.
Docs: skills/claude-code-extensions/references/agent-sdk.md"""
import argparse
import asyncio
import contextlib
import dataclasses
import glob
import inspect
import json
import os
import queue
import re
import secrets
import select
import shutil
import signal
import sys
import threading
import time
from collections import Counter

CLEAN = re.compile(r"[*`_ ]*(?P<input>.+?) · (?P<timestamp>\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2})?)"
                   r" · (?P<agent>[A-Za-z0-9_-]+)[*`_ ]*")
FIELD = re.compile(r"(STATUS|RESULT|EVIDENCE|FILES|NEXT):\s*(.*)")
SEP, NONE = re.compile(r"\s(?:—|–|--?)\s"), re.compile(r"(?i)\(?(none|nothing|no files)(\)|\s|$)")
TASK_MSGS = ("TaskStartedMessage", "TaskProgressMessage", "TaskNotificationMessage", "TaskUpdatedMessage")
SUBTYPE = dict(zip(TASK_MSGS, ("task_started", "task_progress", "task_notification", "task_updated")))
TYPE = re.compile(r"([\w-]+): |([\w-]+)\Z")     # label "<type>: <task>", or a bare type
TERMINAL = frozenset({"completed", "failed", "stopped", "killed"})
AGENT_TASKS = frozenset({"local_agent", "local_workflow"})      # the SDK's DEFERRING_TASK_TYPES
EXTRA_OK = ("debug", "debug-file", "verbose", "model", "fallback-model", "effort", "betas", "name")  # SDK-2r2:
#   an allowlist (D5): the CLI's flag namespace, hidden flags included, is too large to deny by name
REFUSED_KW = ("hooks", "agents", "can_use_tool", "permission_prompt_tool_name", "sandbox",  # D4: files are the truth
              "max_budget_usd", "setting_sources")                        # budget_usd= and sources= own these
POLICY_KEYS = ("hooks", "disableAllHooks", "permissions", "defaultMode", "sandbox")
CEILING_ENV, STATE_ENV = "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS", "CLAUDE_CODE_EMIT_SESSION_STATE_EVENTS"
HOST_WAIT_S, LOAD_WAIT_S, INTERRUPT_S, GRACE_S, DEADLINE_NONE_S, GAP_S = 300.0, 20.0, 10.0, 2.0, 3600.0, 0.5
RESULT_KEYS = ("subtype", "is_error", "num_turns", "duration_ms", "duration_api_ms", "session_id",
               "total_cost_usd", "usage", "result", "permission_denials", "errors", "api_error_status",
               "terminal_reason", "stop_reason", "origin")
ROW_KEYS = ("outcome", "gate", "gate_waived", "needs_user", "ended_by", "session_id", "host", "entrypoint",
            "agent", "cost_usd", "num_turns", "duration_ms", "duration_api_ms", "permission_mode", "cli_version",
            "sdk_version", "first_message_s")
IDENT, SID = re.compile(r"[\w.:@+-]{1,128}"), re.compile(r"[\w-]{1,128}")
BIDI = "\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069\u2028\u2029"
CTRL = re.compile(f"[\x00-\x08\x0b-\x1f\x7f-\x9f{BIDI}]")   # C0 but \t \n, DEL, C1 (ESC/CSI/OSC), bidi


class StackNotLoaded(RuntimeError):
    """The installed stack did not load (agents, SessionStart hooks, guard marker): no prompt was sent."""


class CliNotFound(RuntimeError):
    """No `claude` on PATH and no explicit cli; "bundled" opts into the SDK's own CLI (D11)."""


class UsageError(ValueError):
    """A run that may not start: host none without a budget, host tty without a terminal."""


def files_of(block):    # `path — purpose` or `- path` per line, or the older `a, b`; as hooks/stack_report.py
    out = []
    for ln in block.split("\n"):
        ln = re.sub(r"^(?:[-*+•]|\d{1,3}[.)])\s+", "", ln.strip())
        for p in [SEP.split(ln)[0]] if SEP.search(ln) else ln.split(","):
            p = re.sub(r":\d+(?:-\d+)?$", "", re.sub(r"^(\S.*?)(?<!\s)\s+\([^()]*\)$", r"\1", p.strip()).strip("`'\" "))
            out += [] if p.lower() in ("", "-", "—", "n/a") or NONE.match(p) else [p]
    return out


def parse_report(text):
    """Final reply -> {format, input, timestamp, agent, status, eflag, result, evidence, files, next}.
    format: json (STACK_REPORT_FORMAT=json; the last JSON line wins), clean (the clean-finish line;
    status done), status (the STATUS block) or text (neither: status None, the reply as result)."""
    r = dict.fromkeys(("input", "timestamp", "agent", "status", "eflag", "evidence", "next"))
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
    e = re.search(r"(?i)\bE\s*:\s*(look|drop)\b", got["status"].split("\n")[0])
    r["eflag"], r["files"] = e and e.group(1).lower(), files_of(got.get("files", ""))
    return r


def options(agent="blackcat", max_turns=None, budget_usd=None, allowed_tools=(), disallowed_tools=(),
            permission_mode=None, resume=None, fork=False, cwd=None, json_reports=False,
            sources=("user", "project", "local"), **more):
    """ClaudeAgentOptions for the installed stack, every field visible and adjustable
    (dataclasses.replace); `more` is any other ClaudeAgentOptions field (model, effort, hooks...)."""
    from claude_agent_sdk import ClaudeAgentOptions
    kw = dict(setting_sources=list(sources),  # noqa: C408 - agents, skills, rules, hooks, permissions: the files
              system_prompt={"type": "preset", "preset": "claude_code", "exclude_dynamic_sections": True},
              max_turns=max_turns, max_budget_usd=budget_usd, allowed_tools=list(allowed_tools),
              disallowed_tools=list(disallowed_tools), permission_mode=permission_mode, resume=resume,
              fork_session=fork, cwd=cwd)
    kw["extra_args"] = dict(more.pop("extra_args", None) or {}, **({"agent": agent} if agent else {}))
    kw["env"] = dict(more.pop("env", None) or {}, **({"STACK_REPORT_FORMAT": "json"} if json_reports else {}))
    return ClaudeAgentOptions(**dict(kw, **more))


def agent_of(task):     # "<type>: <task>" label, or a bare type for an agent task; else None
    m = TYPE.match(task.get("description") or "")
    return m and (m.group(1) or (m.group(2) if task.get("task_type") == "local_agent" else None))


# ---------------------------------------------------------------- one reducer, two adapters (D14)
def wire(m):
    """An SDK message -> the stream-json dict the CLI sent, as far as the reducer reads it."""
    if isinstance(m, dict):
        return m
    k, data = type(m).__name__, getattr(m, "data", None)

    def g(a):
        return getattr(m, a, None)
    if k == "ResultMessage":
        return dict({a: g(a) for a in RESULT_KEYS}, type="result", modelUsage=g("model_usage"))
    if isinstance(data, dict) and data.get("type"):
        return data                                  # system, task and hook frames: the CLI's own dict
    if k in SUBTYPE or k in ("SystemMessage", "HookEventMessage"):
        d = {a: g(a) for a in ("task_id", "tool_use_id", "description", "task_type", "status", "usage", "patch",
                               "session_id") if g(a) is not None}
        return dict(data or {}, **d, type="system", subtype=g("subtype") or SUBTYPE.get(k),
                    **({"hook_event": g("hook_event_name")} if k == "HookEventMessage" else {}))
    if k == "AssistantMessage":
        return {"type": "assistant", "parent_tool_use_id": g("parent_tool_use_id"), "message": {"content": [
            {"type": "tool_use", "id": b.id, "name": b.name} for b in g("content") or []
            if type(b).__name__ == "ToolUseBlock"]}}
    if k == "RateLimitEvent":
        i = g("rate_limit_info")
        return {"type": "rate_limit_event", "rate_limit_info": getattr(i, "raw", None) or {
            "status": getattr(i, "status", None), "rateLimitType": getattr(i, "rate_limit_type", None)}}
    return {"type": {"UserMessage": "user", "StreamEvent": "stream_event"}.get(k, k)}


def state_root(env=None):
    return (env or {}).get("XDG_STATE_HOME") or os.environ.get("XDG_STATE_HOME") or \
        os.path.expanduser("~/.local/state")


def config_root(env=None):
    return (env or {}).get("CLAUDE_CONFIG_DIR") or os.environ.get("CLAUDE_CONFIG_DIR") or \
        os.path.expanduser("~/.claude")


class Reducer:
    """One run's wire dicts -> the result dict (D6, D8, D10); Session.ask, run() and parse_stream share it."""

    def __init__(self):
        self.t0, self.first, self.results, self.init, self.state, self.sid = time.monotonic(), None, [], {}, None, None
        self.tasks, self.keys, self.tree, self.parent = {}, {}, {}, {}
        self.rate, self.subtypes, self.hooks = {}, Counter(), Counter()

    def feed(self, d):
        self.first = self.first if self.first is not None else round(time.monotonic() - self.t0, 3)
        t, sub = d.get("type"), d.get("subtype")
        if t in ("result", "system") and isinstance(d.get("session_id"), str):
            self.sid = d["session_id"]
        if t == "result":
            self.results.append(d)
        elif t == "system":
            self.subtypes[str(sub)] += 1
            if sub == "init":
                self.init = d
            elif sub == "session_state_changed":
                self.state = d.get("state")
            elif sub in ("hook_started", "hook_response"):
                name = d.get("hook_event") or d.get("hook_name") or d.get("hook_event_name") or ""
                self.hooks[f"{name}:{sub}"] += 1
            elif sub in SUBTYPE.values():
                self._task(d)
        elif t == "assistant":
            for b in (d.get("message") or {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in ("Agent", "Task"):
                    self.parent[b.get("id")] = d.get("parent_tool_use_id")
        elif t == "rate_limit_event":
            i = d.get("rate_limit_info") or {}
            by = self.rate.setdefault(str(i.get("status")), {})
            by[str(i.get("rateLimitType"))] = by.get(str(i.get("rateLimitType")), 0) + 1

    def _task(self, d):
        tid, patch = d.get("task_id"), d.get("patch") if isinstance(d.get("patch"), dict) else {}
        if not tid:
            return
        k = self.keys.setdefault(tid, d.get("tool_use_id") or tid)
        t = self.tasks.setdefault(k, {"task_id": tid})       # v1's per-subagent view (`agents`)
        t.update({a: v for a in ("description", "status", "usage", "task_type") if (v := d.get(a) or patch.get(a))})
        n = self.tree.setdefault(tid, {"task_id": tid, "tool_use_id": None, "task_type": None, "status": "running",
                                       "ended": False})
        n["tool_use_id"] = d.get("tool_use_id") or n["tool_use_id"]
        n["task_type"] = d.get("task_type") or n["task_type"]
        n["label"] = n.get("label") or d.get("description")
        st = d.get("status") or patch.get("status")
        n["status"] = st or n["status"]
        n["ended"] = n["ended"] or d.get("subtype") == "task_notification" or st in TERMINAL
        n["usage"] = d.get("usage") or patch.get("usage") or n.get("usage")

    def inflight(self):
        return [{"task_id": n["task_id"], "task_type": n["task_type"],
                 "agent": agent_of({"description": n.get("label"), "task_type": n["task_type"]})}
                for n in self.tree.values() if not n["ended"] and n["task_type"] in AGENT_TASKS]

    def summary(self, host=None, ended_by=None, env=None):
        res = self.results[-1] if self.results else {}
        text = res.get("result")
        report = dict(parse_report(text if isinstance(text, str) else ""))
        report["source"] = report["format"]
        sub, why = str(res.get("subtype") or ""), str(res.get("terminal_reason") or "")
        bounded = ended_by in ("bg_wait_ceiling", "deadline")       # our own interrupt: partial (D7)
        if res.get("is_error") and sub != "error_max_budget_usd" and not why.startswith("aborted") or (
                not res and ended_by == "eof"):
            outcome = "error"
        elif why.startswith("aborted") and not bounded or ended_by in ("signal", "cancelled"):
            outcome = "interrupted"
        elif bounded or sub == "error_max_budget_usd":
            outcome = "partial"
        else:
            outcome = {"done": "done", "partial": "partial", "blocked": "blocked", "failed": "failed"}.get(
                report["status"], "unknown")
        ask = bool(re.search(r"\bASK USER\b", report.get("next") or ""))
        needs_user = True if ask else (None if host == "none" and report["format"] == "text" else False)
        mode = self.init.get("permissionMode")
        gate = "ask" if ask else ("plan" if host == "none" and mode == "plan" and report["status"] in (
            "blocked", None) else None)
        denials = {}
        for r in self.results:
            for x in r.get("permission_denials") or []:
                if isinstance(x, dict):
                    denials.setdefault(x.get("tool_use_id"), {"tool_name": x.get("tool_name"),
                                                              "tool_use_id": x.get("tool_use_id")})
        sid, state, config = res.get("session_id") or self.sid, state_root(env), config_root(env)
        origin = lambda o: o if isinstance(o, dict) and isinstance(o.get("kind"), str) else None
        out = {"outcome": outcome, "needs_user": needs_user, "gate": gate, "gate_waived": False,
               "ended_by": ended_by, "report": report, "session_id": sid,
               "results": [dict({k: r.get(k) for k in RESULT_KEYS if k not in ("result", "usage", "errors",
                                 "permission_denials", "origin")}, origin=origin(r.get("origin"))) for r in self.results],
               "permission_denials": list(denials.values()), "errors": res.get("errors"),
               "cost_usd": res.get("total_cost_usd"), "permission_mode": mode,
               "cli_version": self.init.get("claude_code_version"), "first_message_s": self.first,
               "model_usage": res.get("modelUsage"), "agents": [dict(t, tool_use_id=k, agent=agent_of(t))
                                                                for k, t in self.tasks.items()],
               "tasks": [{"task_id": n["task_id"], "tool_use_id": n["tool_use_id"], "task_type": n["task_type"],
                          "parent_tool_use_id": self.parent.get(n["tool_use_id"]), "status": n["status"],
                          "agent": agent_of({"description": n.get("label"), "task_type": n["task_type"]}),
                          "usage": n.get("usage")} for n in self.tree.values()],
               "inflight_at_end": self.inflight(), "rate_limits": self.rate,
               "system_subtypes": dict(self.subtypes), "hook_events": dict(self.hooks),
               "ledger": sid and os.path.join(state, "claude-agent-stack", sid, "delegations.md"),
               "transcript": next(iter(sorted(glob.glob(os.path.join(glob.escape(config), "projects", "*",
                                                                      glob.escape(sid) + ".jsonl")))), None)
               if sid and SID.fullmatch(sid) else None}
        for k in ("subtype", "is_error", "num_turns", "duration_ms", "duration_api_ms", "terminal_reason",
                  "stop_reason", "api_error_status", "usage", "total_cost_usd"):
            out[k] = res.get(k)
        if not self.results:
            out["error"] = "no ResultMessage"
        return out


def parse_stream(lines, host=None):
    """`claude -p --output-format stream-json --verbose` lines (str, bytes or dicts) -> Session.ask's dict."""
    r = Reducer()
    for ln in lines:
        try:
            d = ln if isinstance(ln, dict) else json.loads(ln) if ln.strip() else None
        except ValueError:
            continue
        if isinstance(d, dict):
            r.feed(d)
    return r.summary(host=host, ended_by="result" if r.results else "eof")


def write_row(out, env=None):
    """One numbers-and-identifiers row per run: <state>/claude-agent-stack/usage/sdk-runs.jsonl, 0600 (D10)."""
    row = {"v": 1, "ts": round(time.time(), 3)}
    for k in ROW_KEYS:
        v = out.get(k)
        ok = v is None or isinstance(v, (bool, int, float)) or isinstance(v, str) and IDENT.fullmatch(v)
        row[k] = v if ok else None
    tok, mu = Counter(), out.get("model_usage")
    for u in (mu.values() if isinstance(mu, dict) else ()):
        for k in ("inputTokens", "cacheCreationInputTokens", "cacheReadInputTokens", "outputTokens"):
            v = u.get(k) if isinstance(u, dict) else None
            tok[k] += int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0
    rate = out.get("rate_limits") or {}
    row.update(results=len(out.get("results") or []), tasks=len(out.get("tasks") or []), tokens=dict(tok),
               denials=len(out.get("permission_denials") or []), inflight_at_end=len(out.get("inflight_at_end") or []),
               rate_limit_events=sum(sum(v.values()) for v in rate.values()),
               rate_limited=sum(sum(v.values()) for s, v in rate.items() if s not in ("allowed", "allowed_warning")))
    path = os.path.join(state_root(env), "claude-agent-stack", "usage", "sdk-runs.jsonl")
    try:
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            os.fchmod(fd, 0o600)
            os.write(fd, (json.dumps(row, separators=(",", ":")) + "\n").encode())
        finally:
            os.close(fd)
        return path
    except OSError:
        return None


# ---------------------------------------------------------------- the stack's files (D2, D3)
def stack_agents(config):
    """{name: frontmatter permissionMode or None} of <config>/agents/*.md; any file without a parsable
    name fails closed (R5)."""
    out, bad = {}, []
    for p in sorted(glob.glob(os.path.join(glob.escape(config), "agents", "*.md"))):
        try:
            with open(p, encoding="utf-8") as fh:
                m = re.match(r"---\r?\n(.*?)\r?\n---", fh.read(), re.DOTALL)
        except (OSError, UnicodeDecodeError):
            m = None
        fm = {}
        for k, v in re.findall(r"(?m)^['\"]?(name|permissionMode)['\"]?[ \t]*:(.*)$", m.group(1)) if m else []:
            v = re.sub(r"\s+#.*$", "", v).strip().strip("'\"").strip()
            fm[k] = v or ("?" if k == "permissionMode" else "")      # a mode we cannot read is denied (S7)
        if fm.get("name"):
            out[fm["name"]] = fm.get("permissionMode") or None
        else:
            bad.append(os.path.basename(p))
    if bad or not out:
        names = ", ".join(bad) or "none found"
        raise StackNotLoaded(f"agent files without a parsable name in {config}/agents: {names}")
    return out


def project_agent_files(cwd, config, extra=()):
    """Every .claude/agents directory the CLI may read project agents from (2.1.287: recursively, dotfiles too):
    cwd up to the repository root (or /), a linked worktree's main checkout, and `extra` (add_dirs). Any one,
    whatever it holds, fails the D3 plan gate: no deny rule can cover what it shadows (SDK-2r S1, R1). Unverified against
    the real CLI: a .claude/agents above the repository root's .git, and agents in subdirectories of an add_dir."""
    def text(p):
        with open(p, encoding="utf-8") as fh:
            return fh.read().strip()
    d, user = os.path.realpath(cwd or os.getcwd()), os.path.realpath(os.path.join(config, "agents"))
    roots = [os.path.join(d, str(x)) for x in extra]    # N1: the CLI resolves --add-dir against its own cwd
    while True:
        roots.append(d)
        g = os.path.join(d, ".git")
        if os.path.isfile(g):                            # gitdir: <main>/.git/worktrees/<n>; commondir ../..
            with contextlib.suppress(OSError, IndexError):
                gd = os.path.join(d, text(g).split("gitdir:", 1)[1].strip())
                roots.append(os.path.dirname(os.path.realpath(os.path.join(gd, text(os.path.join(gd, "commondir"))))))
        if os.path.lexists(g) or os.path.dirname(d) == d:
            return [a for r in roots for a in [os.path.join(str(r), ".claude", "agents")]
                    if os.path.lexists(a) and os.path.realpath(a) != user]
        d = os.path.dirname(d)


def session_start_hooks(config, source):
    """How many SessionStart hooks <config>/settings.json configures for `source` (plugins may add more)."""
    try:
        with open(os.path.join(config, "settings.json"), encoding="utf-8") as fh:
            groups = (json.load(fh).get("hooks") or {}).get("SessionStart") or []
        return sum(len(g.get("hooks") or []) for g in groups if isinstance(g, dict) and (
            g.get("matcher") in (None, "", "*") or re.fullmatch(str(g["matcher"]), source)))
    except (OSError, ValueError, AttributeError, TypeError, re.error):
        return 0


def policy_overlay(settings):
    """True if a `settings` overlay (JSON text or a file) touches hooks, permissions or the mode."""
    try:
        if isinstance(settings, str) and not settings.lstrip().startswith("{"):
            with open(settings, encoding="utf-8") as fh:
                settings = fh.read()
        obj = json.loads(settings) if isinstance(settings, str) else settings
    except (OSError, ValueError):
        return True
    return not isinstance(obj, dict) or any(k in obj for k in POLICY_KEYS)


def read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def resolve_cli(cli):
    """D11: None -> the `claude` on PATH (CliNotFound if none, never the bundled one); "bundled" -> None."""
    if cli == "bundled":
        return None
    p = shutil.which("claude") if cli is None else cli
    if not p or not os.path.isfile(p) or not os.access(p, os.X_OK):
        raise CliNotFound("no claude CLI at %r: install Claude Code or pass --cli PATH (or --cli bundled)" % (p or "PATH"))
    return p


# ---------------------------------------------------------------- permission hosts (D3)
def clean_text(s, cap):
    """Sanitised and capped for the terminal: no control, escape or bidi character survives."""
    s = CTRL.sub("?", str(s))
    return s if len(s) <= cap else f"{s[:cap]} [... {len(s) - cap} more chars]"


def one_line(s, cap):
    """clean_text on one line: for what is shown outside the '  | ' quote (options, tool, agent id)."""
    return clean_text(re.sub(r"[\n\t]", " ", str(s)), cap)


def keep_rules(updates, tool):
    """D3 callable: only session addRules (allow, deny, ask) whose rules name `tool`; nothing else."""
    from claude_agent_sdk.types import PermissionRuleValue, PermissionUpdate
    out = []
    for u in updates or []:
        def g(a, u=u):
            return u.get(a) if isinstance(u, dict) else getattr(u, a, None)
        if g("type") != "addRules" or g("destination") != "session" or g("behavior") not in ("allow", "deny", "ask"):
            continue
        rules = [PermissionRuleValue(tool_name=tool, rule_content=c if isinstance(c, str) else None)
                 for x in g("rules") or [] for n, c in [(x.get("toolName"), x.get("ruleContent")) if isinstance(x, dict)
                                                        else (getattr(x, "tool_name", None), getattr(x, "rule_content", None))]
                 if n == tool]
        if rules:
            out.append(PermissionUpdate(type="addRules", destination="session", behavior=g("behavior"), rules=rules))
    return out


async def ask_callable(host, tool, inp, ctx, timeout_s=HOST_WAIT_S):
    """The app's can_use_tool behind the D3 rules: deny on an exception, a timeout or an invalid return;
    AskUserQuestion needs the user's answers; updated_permissions filtered by keep_rules."""
    import anyio
    from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny
    if tool == "AskUserQuestion" and isinstance(inp, dict):     # answers come from the host's user only (S4)
        inp = {k: v for k, v in inp.items() if k not in ("answers", "annotations")}     # R5: the notes too
    try:
        with anyio.fail_after(timeout_s):
            r = host(tool, inp, ctx)
            r = await r if inspect.isawaitable(r) else r
    except Exception:  # noqa: BLE001 - the host failed: deny
        r = None
    if isinstance(r, PermissionResultDeny):
        return PermissionResultDeny(message=str(r.message)[:2000], interrupt=bool(r.interrupt))
    ui = r.updated_input if isinstance(r, PermissionResultAllow) else None
    if not isinstance(r, PermissionResultAllow) or ui is not None and not isinstance(ui, dict) or (
            tool == "AskUserQuestion" and not (isinstance(ui, dict) and ui.get("answers"))):
        return PermissionResultDeny(message="denied: the host gave no valid answer")
    return PermissionResultAllow(updated_input=ui, updated_permissions=keep_rules(r.updated_permissions, tool) or None)


class TtyHost:
    """The controlling terminal (D3 tty). One reader thread tags each line with the prompt it was typed
    for (older lines are discarded); TCIFLUSH before each prompt; prompts serialised; plan approval needs a
    4-digit nonce; timeout or EOF denies; every rendered string sanitised and capped; never returns
    updated_permissions. fds=(read, write) replaces /dev/tty (tests)."""

    def __init__(self, path="/dev/tty", timeout_s=HOST_WAIT_S, fds=None):
        if fds is None:
            try:
                fd = os.open(path, os.O_RDWR | os.O_NOCTTY)
            except OSError as e:
                raise UsageError(f"--host tty needs a terminal: {path}: {e.strerror}") from None
            fds = (fd, fd)
        self.rfd, self.wfd = fds
        self.timeout_s, self.seq, self.eof, self.q, self._lock = timeout_s, 0, False, queue.Queue(), None
        self.closed, self.thread = False, threading.Thread(target=self._reader, name="stack_sdk-tty", daemon=True)
        self.thread.start()

    def _reader(self):
        buf = b""
        while not self.closed:
            try:
                if not select.select([self.rfd], [], [], 0.2)[0]:
                    continue
                chunk = os.read(self.rfd, 4096)
            except (OSError, ValueError):
                chunk = b""
            if not chunk:
                self.eof = True
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                self.q.put((self.seq, line.decode("utf-8", "replace").strip()))

    def say(self, text):
        with contextlib.suppress(OSError):
            os.write(self.wfd, (text + "\n").encode("utf-8", "replace"))

    def quote(self, text, cap):
        """Every row shown starts with '  | ': lines are cut at half the terminal width, tabs expanded, since a
        longer line would wrap to column 0 by itself (SDK-2r R3)."""
        try:
            w = max(16, (os.get_terminal_size(self.wfd).columns - 4) // 2)
        except OSError:
            w = 38
        return "\n".join("  | " + ln[i:i + w] for ln in clean_text(text, cap).expandtabs(4).splitlines() or [""]
                         for i in range(0, len(ln) or 1, w))

    async def line(self, prompt):
        """One answer typed after `prompt` is shown; None on timeout or EOF."""
        import termios

        import anyio
        self.seq += 1                                    # a gap: a late line for the previous prompt lands here
        await anyio.sleep(GAP_S)                         # and is discarded, also when this prompt was queued (S6)
        self.seq += 1
        seq, end = self.seq, time.monotonic() + self.timeout_s
        with contextlib.suppress(OSError, termios.error):
            termios.tcflush(self.rfd, termios.TCIFLUSH)
        self.say(prompt)
        while time.monotonic() < end:
            try:
                s, ln = self.q.get_nowait()
            except queue.Empty:
                if self.eof:
                    return None
                await anyio.sleep(0.05)
                continue
            if s >= seq:
                return ln
        self.say(f"stack_sdk: no answer in {self.timeout_s:g} s: denied")
        return None

    async def __call__(self, tool, inp, ctx):
        import anyio
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny
        self._lock = self._lock or anyio.Lock()
        deny = PermissionResultDeny(message="denied at the terminal")
        who = one_line(getattr(ctx, "agent_id", None) or "main thread", 24)
        async with self._lock:
            if tool == "AskUserQuestion":
                answers = {}
                for q in [q for q in (inp or {}).get("questions") or [] if isinstance(q, dict)]:
                    opts = [str((o or {}).get("label", "")) for o in q.get("options") or [] if isinstance(o, dict)]
                    menu = self.quote("\n".join(f"{i + 1}) {one_line(o, 200)}" for i, o in enumerate(opts[:20])), 6000)
                    text = self.quote(q.get("question", ""), 1000)
                    ln = await self.line(f"\nstack_sdk: question ({who}):\n{text}\n{menu}\n"
                                         "answer (number or text, empty denies):")
                    if not ln:
                        return deny
                    picks = [opts[int(x) - 1] for x in ln.split(",") if x.strip().isdigit() and 0 < int(x) <= len(opts)]
                    answers[str(q.get("question", ""))] = ", ".join(picks) if picks else ln
                kept = {k: v for k, v in inp.items() if k != "annotations"}  # R5: user notes come from the user
                return PermissionResultAllow(updated_input=dict(kept, answers=answers)) if answers else deny
            if tool == "ExitPlanMode":
                nonce, plan = f"{secrets.randbelow(10000):04d}", self.quote((inp or {}).get("plan", ""), 8000)
                ln = await self.line(f"\nstack_sdk: plan ({who}):\n{plan}\ntype {nonce} to approve; anything else denies:")
                return PermissionResultAllow() if ln == nonce else deny
            shown = self.quote(json.dumps(inp, ensure_ascii=False, default=str), 2000)
            name, rows = one_line(tool, 40), shown.count("\n") + 1      # N4: what is approved, next to the answer
            ln = await self.line(f"\nstack_sdk: {who} wants {name}:\n{shown}\nstack_sdk: ^ {who} wants {name} "
                                 f"({rows} rows above)\nallow once? [y/N]:")
            return PermissionResultAllow() if (ln or "").lower() in ("y", "yes") else deny

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.thread.join(1.0)                            # the reader stops before its fd number can be reused
        for fd in {self.rfd, self.wfd}:
            with contextlib.suppress(OSError):
                os.close(fd)


# ---------------------------------------------------------------- Session (D1-D3, D5-D10)
class Session:
    """A stack session on ClaudeSDKClient: `async with Session(...) as s: out = await s.ask(prompt)`.
    host: "none" (default; unattended: --permission-prompts none, ExitPlanMode denied and, under plan,
    every builder agent and Workflow; budget_usd required; deadline_s 3600), "tty", or a callable
    can_use_tool(tool, input, context). cli: None (the `claude` on PATH), "bundled" or a path. The rest
    goes to options(). `client` is the raw ClaudeSDKClient, an escape hatch: its stop_task fires no hook;
    agent_guard releases the child at the next Agent/SendMessage from meta.json stoppedByUser (reap_host_stopped)."""

    def __init__(self, agent="blackcat", *, host="none", budget_usd=None, permission_mode=None, bg_wait_s=600.0,
                 deadline_s=None, cli=None, config_dir=None, forward_subagent_text=False, transport=None,
                 on_message=None, tty=None, load_timeout_s=LOAD_WAIT_S, row=True, **kw):
        bad = [k for k in REFUSED_KW if k in kw] + [k for k, v in (kw.get("extra_args") or {}).items() if k not in EXTRA_OK
                                                    or v is not None and (k == "verbose" or str(v).startswith("-"))]  # N3
        if bad or permission_mode == "bypassPermissions":
            raise ValueError("refused: %s (the host and the stack's files decide; bypassPermissions never)"
                             % (", ".join(map(str, bad)) or "bypassPermissions"))
        if kw.get("output_format") and agent:
            raise ValueError("output_format with an agent main thread: the report is parsed from the text (D6)")
        if "user" not in kw.get("sources", ("user",)) or kw.get("settings") is not None and policy_overlay(kw["settings"]):
            raise ValueError(f"setting_sources must include user, and no settings overlay may touch {POLICY_KEYS}")
        if not (host in ("none", "tty") or callable(host)):
            raise ValueError("host: none, tty or a callable")
        self.env = dict(kw.pop("env", None) or {})
        ceiling = self.env.get(CEILING_ENV, os.environ.get(CEILING_ENV))
        if ceiling is not None and not (str(ceiling).strip().isdigit() and int(ceiling) > 0):
            raise ValueError(f"{CEILING_ENV} must be a positive number of ms (0 = never stop waiting)")
        self.env.setdefault(CEILING_ENV, "3000")      # the CLI exits inside the SDK's 5 s close window
        self.env[STATE_ENV] = "1"
        self.agent, self.host, self.budget_usd, self.permission_mode = agent, host, budget_usd, permission_mode
        self.bg_wait_s, self.cli_path, self.transport, self.on_message = bg_wait_s, resolve_cli(cli), transport, on_message
        ok = isinstance(deadline_s, (int, float)) and deadline_s > 0     # S8: <= 0 never unbounds host none
        self.deadline_s = deadline_s if ok or host != "none" else DEADLINE_NONE_S
        self.config = config_dir or config_root(self.env)
        if config_dir and self.env.setdefault("CLAUDE_CONFIG_DIR", config_dir) != config_dir:    # R6: one config
            raise ValueError("config_dir and env CLAUDE_CONFIG_DIR differ: the CLI would load another config")
        self.extra, self.kw = dict(kw.pop("extra_args", None) or {}), kw
        self.forward_subagent_text, self.load_timeout_s, self.row = forward_subagent_text, load_timeout_s, row
        self.tty, self._own_tty = tty or (TtyHost() if host == "tty" else None), tty is None
        self._client = self._it = self._scope = self._stop = None
        self.loaded = self.asking = self._eof = self.asked = False
        self.early, self.t0, self.agents, self.failure = [], None, {}, None

    @property
    def client(self):
        return self._client

    @property
    def gate_waived(self):
        return self.host == "none" and self.permission_mode not in (None, "plan")

    def check(self):
        """Raise UsageError if this run may not start (D3 none: an unattended run needs a budget)."""
        if self.host == "none" and not (isinstance(self.budget_usd, (int, float)) and self.budget_usd > 0):
            raise UsageError("host none needs budget_usd > 0: an unattended run is bounded")

    def build(self, plan):
        """The options for this session: options() plus the host's keys, set last (D3, D5, D7, D12)."""
        kw = dict(self.kw)
        deny = list(kw.pop("disallowed_tools", ()) or ())
        if self.host == "none":
            deny += ["ExitPlanMode"] + ([*(f"Agent({n})" for n, m in sorted(self.agents.items())
                                           if m not in (None, "plan", "default")), "Workflow"] if plan else [])
        extra = dict(self.extra, **({"permission-prompts": "none"} if self.host == "none" else {}))
        mode = self.permission_mode or ("plan" if self.host == "none" else None)   # the flag outranks repo settings
        return options(self.agent, **dict(kw, budget_usd=self.budget_usd, permission_mode=mode,
                                          disallowed_tools=deny, extra_args=extra, env=self.env, cli_path=self.cli_path,
                                          include_hook_events=True, forward_subagent_text=self.forward_subagent_text,
                                          can_use_tool=None if self.host == "none" else self._can_use_tool))

    def preview(self):
        self.agents = stack_agents(self.config)
        return self.build((self.permission_mode or "plan") == "plan")

    async def _can_use_tool(self, tool, inp, ctx):
        from claude_agent_sdk import PermissionResultDeny
        if not self.loaded:                          # D2: nothing is answered before the load check passed
            return PermissionResultDeny(message="denied: the stack's load check has not passed")
        if self.tty is not None:
            return await self.tty(tool, inp, ctx)
        return await ask_callable(self.host, tool, inp, ctx)

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *exc):
        await self.disconnect()
        self.close()

    async def connect(self):
        """Connect and run the load check (D2) before any prompt; StackNotLoaded leaves nothing connected."""
        from claude_agent_sdk import ClaudeSDKClient
        self.check()
        self.agents = stack_agents(self.config)
        plan, self.asked, self.failure = (self.permission_mode or "plan") == "plan", False, None
        try:
            self.opts = self.build(plan)
            self._client = ClaudeSDKClient(self.opts, transport=self.transport and self.transport(self.opts))
            self.t0 = time.time()                        # immediately before connect(): the marker is newer
            await self._client.connect()
            info = await self._client.get_server_info() or {}
            items = info.get("agents") if isinstance(info, dict) else None
            have = {i.get("name") if isinstance(i, dict) else i for i in items or []
                    if isinstance(i, (dict, str))} if isinstance(items, list) else set()
            have = {h for h in have if isinstance(h, str)}
            missing = sorted(set(self.agents) - have)
            if missing:
                raise StackNotLoaded(f"agents missing from server_info: {', '.join(missing[:20])}")
            actual = info.get("current_permission_mode")
            if actual == "bypassPermissions":            # D5, whichever route set it (SDK-2r S2)
                raise StackNotLoaded("the session runs in bypassPermissions: refused")
            if self.host == "none" and plan:
                if actual != "plan":                     # S3, C1: the gate fails closed, never reconnects without it
                    raise StackNotLoaded(f"the permission mode drifted off plan: {actual!r} (pass permission_mode "
                                         "explicitly to waive the plan gate: logged gate_waived)")
                odd = sorted(h for h in have - set(self.agents) if ":" not in h)   # plugin agents keep no mode
                odd += project_agent_files(self.kw.get("cwd"), self.config, self.kw.get("add_dirs") or ())
                if odd:                                  # S1: no deny rule can cover agents from elsewhere
                    raise StackNotLoaded("agents outside <config>/agents under the unattended plan gate: "
                                         + ", ".join(map(str, odd[:10])))
            await self._load_check()
            self.loaded = True
        except BaseException:
            await self.disconnect()
            raise

    async def _load_check(self):
        """D2(b1) every SessionStart hook_started has a success hook_response (hook_id), at least as many
        as settings.json configures; then (b2) the guard's marker: fresh (ts >= t0), right source, policy on."""
        resume, fork = self.kw.get("resume"), self.kw.get("fork")
        sources = (("resume", "fork") if fork else ("resume",)) if resume or self.kw.get("continue_conversation") \
            else ("startup",)
        need = max(1, session_start_hooks(self.config, sources[0]))
        started, done, sid, end = set(), set(), None, time.monotonic() + self.load_timeout_s
        while not (len(done) >= need and started <= done):
            m = await self._recv(end - time.monotonic())
            if m is None:
                raise StackNotLoaded(f"SessionStart hooks: {len(done)} of {need} answered in "
                                     f"{self.load_timeout_s:g} s (include_hook_events)" +
                                     (f"; {self.failure}" if self.failure else ""))
            self.early.append(m)
            d = wire(m)
            if d.get("type") != "system" or d.get("subtype") not in ("hook_started", "hook_response") or \
                    (d.get("hook_event") or d.get("hook_name") or "").split(":")[0] != "SessionStart":
                continue
            sid, hid = d.get("session_id") or sid, d.get("hook_id") or f"?{len(self.early)}"
            if d["subtype"] == "hook_started":
                started.add(hid)
                continue
            if d.get("outcome") != "success":
                raise StackNotLoaded(f"a SessionStart hook did not succeed (outcome {d.get('outcome')!r})")
            done.add(hid)
        if not isinstance(sid, str) or not SID.fullmatch(sid):
            raise StackNotLoaded("no session id in the SessionStart events")
        path = os.path.join(state_root(self.env), "claude-agent-stack", sid, "session-start.json")
        mark = read_json(path)
        ts = mark.get("ts") if isinstance(mark, dict) else None
        if not isinstance(ts, (int, float)) or isinstance(ts, bool) or ts < self.t0:
            raise StackNotLoaded(f"agent_guard's session-start marker is missing or stale ({path}): an installed "
                                 "guard older than this helper? reinstall with ./install.sh")
        if mark.get("source") not in sources:
            raise StackNotLoaded(f"session-start marker source {mark.get('source')!r}, expected {'/'.join(sources)}")
        if mark.get("policy") is not True:
            raise StackNotLoaded("policy off: STACK_POLICY=off")

    async def _recv(self, timeout):
        """The next message, or None on timeout (`timeout` None: no limit) or end of stream (_eof)."""
        import anyio
        if timeout is not None and timeout <= 0:
            return None
        if self._it is None:
            self._it = self._client.receive_messages().__aiter__()
        m, ok = None, False
        try:
            with anyio.move_on_after(timeout):
                m, ok = await self._it.__anext__(), True
        except StopAsyncIteration:
            self._eof = True
        except Exception as e:  # noqa: BLE001 - the CLI exited non-zero or the stream broke: end of stream (C3)
            self._eof, self.failure = True, f"{type(e).__name__}: {e}"[:300]
        finally:
            if not ok:
                self._it = None                          # a cancelled generator is finished
        if ok and self.on_message:
            self.on_message(m)
        return m

    def stop(self, why="signal"):
        """End the current ask (SIGTERM/SIGHUP in the CLI): interrupt, then the caller disconnects."""
        self._stop = "signal" if why == "signal" else "cancelled"   # both interrupt and give interrupted (C6)
        if self._scope is not None:
            self._scope.cancel()

    async def ask(self, prompt):
        """Send `prompt` and read until the run ends (D7); one result dict (D6, D10)."""
        import anyio
        if not self.loaded:
            raise StackNotLoaded("not connected, or the load check did not pass")
        if self.host == "none" and (self.permission_mode or "plan") == "plan" and (     # N2: before every prompt
                odd := project_agent_files(self.kw.get("cwd"), self.config, self.kw.get("add_dirs") or ())):
            raise StackNotLoaded("agents outside <config>/agents under the unattended plan gate: " + ", ".join(odd[:10]))
        r = Reducer()
        for m in self.early:
            r.feed(wire(m))
        self.early, r.state, ended_by, self.asking = [], None, "cancelled", True
        try:
            with anyio.CancelScope() as self._scope:
                if self.asked:
                    await self._settle()                 # C4: a turn the CLI woke for since the last ask
                self.asked, r.t0, r.first, self.failure = True, time.monotonic(), None, None  # C5; R4: per ask
                await self._client.query(prompt)
                ended_by = await self._read(r)
            ended_by = self._stop or ended_by if self._scope.cancel_called else ended_by
        finally:
            self._scope, self.asking = None, False
        inflight, host = r.inflight(), self.host if isinstance(self.host, str) else "callable"
        if ended_by in ("bg_wait_ceiling", "deadline", "signal", "cancelled"):
            await self._interrupt(r)
        out = r.summary(host=host, ended_by=ended_by, env=self.env)
        import claude_agent_sdk as sdk
        out.update(gate_waived=self.gate_waived, host=host, agent=self.agent, entrypoint="sdk-py",
                   cli_path=self.cli_path, sdk_version=getattr(sdk, "__version__", None))
        if ended_by in ("bg_wait_ceiling", "deadline"):
            out["inflight_at_end"] = inflight           # what the ceiling or the deadline cut
        if self.failure:
            out["error"] = self.failure
            if not (r.results and r.results[-1].get("is_error")):   # R4: a crash is error; the CLI's own
                out["outcome"] = "error"                            # error result keeps its class (budget: partial)
        if self.row:
            out["row"] = write_row(out, self.env)
        return out

    async def _settle(self):
        """Read frames that arrived after the previous ask returned up to idle (bounded by bg_wait_s), so
        they never answer the next prompt."""
        stale, end = Reducer(), time.monotonic() + self.bg_wait_s
        while (m := await self._recv(0.05 if stale.state in (None, "idle") else end - time.monotonic())) is not None:
            stale.feed(wire(m))

    async def _read(self, r):
        deadline = time.monotonic() + self.deadline_s if self.deadline_s else None
        t_res, paused, p0, n = None, 0.0, None, 0
        while True:
            now = time.monotonic()
            if r.results and r.state == "idle":
                return "result"                          # result and idle, in either order
            limits = [(deadline - now, "deadline")] if deadline is not None else []
            if r.results:
                if r.state == "requires_action":         # a host is answering: the bg clock stops
                    p0 = now if p0 is None else p0
                elif p0 is not None:
                    paused, p0 = paused + now - p0, None
                if p0 is None:
                    limits.append((self.bg_wait_s - (now - t_res - paused), "bg_wait_ceiling"))
                if r.state is None and not r.inflight():
                    limits.append((GRACE_S, "result"))   # no state frames: result, no agent in flight, grace
            wait, why = min(limits) if limits else (None, None)
            if wait is not None and wait <= 0:
                return why
            m = await self._recv(wait)
            if m is None:
                if self._eof:
                    return "result" if r.results else "eof"
                if why:
                    return why
                continue
            r.feed(wire(m))
            if len(r.results) > n:
                n, t_res, paused, p0 = len(r.results), time.monotonic(), 0.0, None

    async def _interrupt(self, r):
        """interrupt() and read to its result, bounded at INTERRUPT_S; disconnect() follows (D7, D9)."""
        import anyio
        n = len(r.results)
        if self._eof or self._client is None:
            return
        with anyio.move_on_after(INTERRUPT_S), contextlib.suppress(Exception):
            await self._client.interrupt()
            while len(r.results) == n and not self._eof:
                m = await self._recv(None)
                if m is not None:
                    r.feed(wire(m))

    async def disconnect(self):
        import anyio
        c, self._client, self._it, self.loaded, self._eof = self._client, None, None, False, False
        if c is not None:
            with anyio.CancelScope(shield=True):
                await c.disconnect()

    def close(self):
        if self.tty is not None and self._own_tty:
            self.tty.close()


async def run(prompt, opts, on_message=None, deadline_s=None):
    """Legacy one-shot (query(), single-message mode): no load check, no host; Session.ask's dict.
    The CLI's background wait stays 600000 ms unless the caller set it; deadline_s bounds the run."""
    import claude_agent_sdk as sdk
    if opts is not None and CEILING_ENV not in (opts.env or {}) and CEILING_ENV not in os.environ:
        opts = dataclasses.replace(opts, env=dict(opts.env or {}, **{CEILING_ENV: "600000"}))
    r, ended_by = Reducer(), None

    async def consume():
        async for m in sdk.query(prompt=prompt, options=opts):
            if on_message:
                on_message(m)
            r.feed(wire(m))
    try:
        await (consume() if deadline_s is None else asyncio.wait_for(consume(), deadline_s))
    except asyncio.TimeoutError:
        ended_by = "deadline"
    env = getattr(opts, "env", None)
    out = r.summary(ended_by=ended_by or ("result" if r.results else "eof"), env=env)
    out.update(entrypoint="sdk-py", cli_path=getattr(opts, "cli_path", None), sdk_version=getattr(sdk, "__version__", None))
    out["row"] = write_row(out, env)
    return out


# ---------------------------------------------------------------- CLI (D15)
def exit_code(out):
    """0 done; 5 blocked or unknown with needs_user or a gate (waiting on the user); 1 anything else."""
    if out.get("outcome") == "done":
        return 0
    return 5 if out.get("outcome") in ("blocked", "unknown") and (out.get("needs_user") or out.get("gate")) else 1


async def _amain(s, prompt):
    loop, task = asyncio.get_running_loop(), asyncio.current_task()
    stop = lambda: s.stop("signal") if s.asking else task.cancel()
    sigs = [x for x in (signal.SIGTERM, getattr(signal, "SIGHUP", None)) if x is not None]
    for x in sigs:
        loop.add_signal_handler(x, stop)
    try:
        async with s:
            return await s.ask(prompt)
    finally:
        for x in sigs:
            loop.remove_signal_handler(x)
        s.close()


def main(argv=None, transport=None):
    p = argparse.ArgumentParser(description="Run one prompt on the installed stack in a Session. Exit: 0 done, "
                                "1 partial/failed/interrupted/unknown, 2 usage, 3 stack not loaded, 4 no claude "
                                "CLI, 5 waiting on the user (a question or the plan gate).")
    on = {"action": "store_true"}
    for flag, kw in (("prompt", {"nargs": "?"}), ("--agent", {"default": "blackcat"}), ("--max-turns", {"type": int}),
                     ("--budget-usd", {"type": float}), ("--allowed-tools", {"default": ""}),
                     ("--disallowed-tools", {"default": ""}), ("--permission-mode", {}), ("--resume", {}),
                     ("--json-reports", on), ("--print-options", on), ("--stream", on),
                     ("--host", {"choices": ("none", "tty"), "default": "none"}),
                     ("--bg-wait-s", {"type": float, "default": 600.0}), ("--deadline-s", {"type": float}),
                     ("--cli", {"help": "PATH or bundled (default: claude on PATH)"}), ("--subagent-text", on),
                     ("--continue", dict(on, dest="cont"))):
        p.add_argument(flag, **kw)
    a = p.parse_args(argv)
    split = lambda s: [x.strip() for x in s.split(",") if x.strip()]
    kw = dict(max_turns=a.max_turns, allowed_tools=split(a.allowed_tools), disallowed_tools=split(a.disallowed_tools),
              resume=a.resume, json_reports=a.json_reports, **({"continue_conversation": True} if a.cont else {}))
    s = None
    try:
        s = Session(a.agent, host=a.host, budget_usd=a.budget_usd, permission_mode=a.permission_mode,
                    bg_wait_s=a.bg_wait_s, deadline_s=a.deadline_s, cli=a.cli, forward_subagent_text=a.subagent_text,
                    transport=transport, on_message=(lambda m: print(repr(m), file=sys.stderr)) if a.stream else None,
                    **kw)
        if a.print_options:
            o = s.preview()
            print(json.dumps({f.name: getattr(o, f.name) for f in dataclasses.fields(o)}, default=repr))
            return 0
        s.check()
        if a.prompt is None:
            raise UsageError("a prompt is required")
        out = asyncio.run(_amain(s, a.prompt))
    except ValueError as e:                              # UsageError, refused modes and keys
        print(f"stack_sdk: {e}", file=sys.stderr)
        return 2
    except StackNotLoaded as e:
        out = {"outcome": "not_loaded", "host": a.host, "agent": a.agent, "entrypoint": "sdk-py"}
        if s is not None and not a.print_options:
            write_row(out, s.env)
        print(json.dumps(dict(out, error=str(e))))
        return 3
    except CliNotFound as e:
        print(f"stack_sdk: {e}", file=sys.stderr)
        return 4
    except (asyncio.CancelledError, KeyboardInterrupt):
        print(json.dumps({"outcome": "interrupted", "ended_by": "signal"}))
        return 1
    except Exception as e:  # noqa: BLE001 - the SDK or the CLI failed (a crash, a bad --resume): one JSON line (C3)
        out = {"outcome": "error", "host": a.host, "agent": a.agent, "entrypoint": "sdk-py"}
        if s is not None:
            write_row(out, s.env)
        print(json.dumps(dict(out, error=f"{type(e).__name__}: {e}"[:300])))
        return 1
    print(json.dumps(out, default=str))
    return exit_code(out)


if __name__ == "__main__":
    sys.exit(main())
