#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Fold the user's paid A4 probe into COMPARE_eq A4 item 4.

Reads the stream-json output of the probe (and its .err), strips credentials, tokens, session ids and emails,
and prints a Markdown block to paste under A4 item 4 plus one verdict per open question (confirmed, refuted,
consistent, or unknown when the output does not show it). Read-only; writes nothing unless --out is given.

  uv run --script hand_off/a4_fold.py PROBE.json [--err PROBE.err] [--agent-file dot-claude/agents/writer.md]
        [--tools-flag Read,Skill,StructuredOutput] [--date YYYY-MM-DD] [--out FILE]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

HOME_RE = re.compile(r"/Users/[^/\s\"']+")
SECRET_RES = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\b(?:ghp|gho|ghs|ghu|github_pat|glpat|xox[abprs]|hf|npm|AKIA|AIza|hvs|dckr_pat)[_\-]?[A-Za-z0-9_\-\.]{12,}"),
    re.compile(r"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]*"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=\-]{8,}"),
    re.compile(r"(?i)\b([A-Za-z0-9_\-]*(?:key|token|secret|passw(?:or)?d|cookie|auth|credential)[A-Za-z0-9_\-]*)(\s*[=:]\s*)\S+"),
]
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")


def scrub(text: object) -> str:
    s = str(text)
    s = HOME_RE.sub("~", s)
    s = UUID_RE.sub("<uuid>", s)
    s = EMAIL_RE.sub("<email>", s)
    for rx in SECRET_RES:
        if rx.groups:
            s = rx.sub(lambda m: f"{m.group(1)}{m.group(2)}<redacted>", s)
        else:
            s = rx.sub("<redacted>", s)
    return s


def parse_stream(path: Path) -> tuple[list[dict], int]:
    events, bad = [], 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            bad += 1
            continue
        if isinstance(obj, dict):
            events.append(obj)
        else:
            bad += 1
    return events, bad


def csv_names(value: str) -> list[str]:
    return [x.strip() for x in re.split(r"[,\s]+", value) if x.strip()]


def frontmatter_tools(path: Path) -> list[str] | None:
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.match(r"---\n(.*?)\n---", text, re.S)
    if not m:
        return None
    for line in m.group(1).splitlines():
        if line.startswith("tools:"):
            return csv_names(line[len("tools:"):])
    return None


def extract(events: list[dict]) -> dict:
    info: dict = {"init": None, "result": None, "tool_uses": [], "tool_errors": [], "skill_ok": False}
    skill_ids: set[str] = set()
    for ev in events:
        t = ev.get("type")
        if t == "system" and ev.get("subtype") == "init" and info["init"] is None:
            servers = ev.get("mcp_servers") or []
            info["init"] = {
                "tools": [str(x) for x in (ev.get("tools") or [])],
                "model": ev.get("model"),
                "permissionMode": ev.get("permissionMode"),
                "version": ev.get("claude_code_version"),
                "mcp_servers": [
                    f"{s.get('name')}:{s.get('status')}" if isinstance(s, dict) else str(s) for s in servers
                ],
                "n_skills": len(ev.get("skills") or []),
                "n_slash": len(ev.get("slash_commands") or []),
                "agents": [str(a) for a in (ev.get("agents") or [])],
            }
        elif t == "assistant":
            content = (ev.get("message") or {}).get("content")
            for b in content if isinstance(content, list) else []:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    info["tool_uses"].append(str(b.get("name")))
                    if b.get("name") == "Skill":
                        skill_ids.add(str(b.get("id")))
        elif t == "user":
            content = (ev.get("message") or {}).get("content")
            for b in content if isinstance(content, list) else []:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    if b.get("is_error"):
                        info["tool_errors"].append(str(b.get("content"))[:200])
                    elif str(b.get("tool_use_id")) in skill_ids:
                        info["skill_ok"] = True
        elif t == "result":
            info["result"] = {
                "subtype": ev.get("subtype"),
                "is_error": ev.get("is_error"),
                "num_turns": ev.get("num_turns"),
                "cost": ev.get("total_cost_usd", ev.get("cost_usd")),
                "duration_ms": ev.get("duration_ms"),
                "structured_output": ev.get("structured_output"),
                "result_text": ev.get("result"),
                "denials": [
                    str(d.get("tool_name")) if isinstance(d, dict) else str(d)
                    for d in (ev.get("permission_denials") or [])
                ],
            }
    return info


def verdicts(info: dict, tools_flag: list[str], fm: list[str] | None) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    init, res = info["init"], info["result"]
    # Q1
    if res is None:
        q1 = ("unknown", "no result event in the output")
    else:
        so = res["structured_output"]
        ok = isinstance(so, dict) and isinstance(so.get("tools"), list)
        if ok:
            q1 = ("confirmed", "the result event carries structured_output with a tools array")
            if "StructuredOutput" in tools_flag:
                q1 = (q1[0], q1[1] + "; StructuredOutput was named in --tools, so whether it NEEDS naming stays unknown")
            else:
                q1 = (q1[0], q1[1] + "; StructuredOutput was NOT named in --tools, so it does not need naming")
        else:
            q1 = ("refuted", "result event without a valid structured_output (is_error=%s, subtype=%s)" % (res["is_error"], res["subtype"]))
    out.append(("`--json-schema` answer arrives under `--tools`; `StructuredOutput` naming", *q1))
    # Q2
    observed = set(init["tools"]) if init else None
    builtin_flag = {t for t in tools_flag if not t.startswith("mcp__")}
    if observed is None:
        q2 = ("unknown", "no init event")
    elif fm is None:
        q2 = ("unknown", "no --agent-file given; frontmatter tools unknown")
    else:
        fset = set(fm)
        widened = sorted(t for t in observed if t in fset and t not in builtin_flag and t != "StructuredOutput")
        expected = (fset & builtin_flag)
        missing = sorted(expected - observed)
        extra = sorted(observed - builtin_flag - {"StructuredOutput"})
        if widened or extra:
            q2 = ("refuted", f"tools outside --tools are present: {sorted(set(widened) | set(extra))}")
        elif missing:
            q2 = ("refuted", f"names in both frontmatter and --tools are absent: {missing} (not a plain intersection)")
        elif builtin_flag - fset - {"StructuredOutput"}:
            gone = sorted(builtin_flag - fset - {"StructuredOutput"} - observed)
            if gone:
                q2 = ("confirmed", f"intersection: {gone} is in --tools but not in the frontmatter, and is absent from the init tools")
            else:
                q2 = ("refuted", "a --tools name outside the frontmatter is present: --tools wins over the frontmatter")
        else:
            q2 = ("consistent", "frontmatter tools include every --tools built-in, so intersection and 'only --tools' give the same set: not distinguishable by this probe")
    out.append(("`--agent` frontmatter tools combine with `--tools` as an intersection under `-p`", *q2))
    # Q3
    out.append(("`--settings` cannot widen the list", "unknown", "the probe passes no --settings"))
    # Q4
    if observed is None:
        q4 = ("unknown", "no init event")
    elif info["skill_ok"]:
        q4 = ("confirmed", "a Skill tool_use returned a non-error result under --strict-mcp-config")
    elif "Skill" in observed:
        q4 = ("unknown", "Skill is in the init tool list (mcp_servers: %s) but the probe never invoked it: loading is not exercised" % (", ".join(init["mcp_servers"]) or "none"))
    else:
        q4 = ("refuted", "Skill is absent from the init tool list")
    out.append(("`Skill` loads under `--strict-mcp-config`", *q4))
    return out


def render(info: dict, vs: list, err_lines: list[str], bad: int, date: str, tools_flag: list[str]) -> str:
    init, res = info["init"], info["result"]
    L = [f"- **A4 item 4 outcome, {date}: paid probe (one `claude -p` call, cap $0.25; folded by `hand_off/a4_fold.py`; credentials, session ids and emails stripped).**"]
    L.append(f"  - Flags under test: `--tools {','.join(tools_flag)}`.")
    if init:
        L.append(f"  - init event: model `{scrub(init['model'])}`, permissionMode `{scrub(init['permissionMode'])}`, Claude Code `{scrub(init['version'])}`, "
                 f"MCP servers: {scrub(', '.join(init['mcp_servers']) or 'none')}; {init['n_skills']} skills, {init['n_slash']} slash commands listed.")
        L.append(f"  - Tool list in the init event ({len(init['tools'])}): `{scrub(', '.join(init['tools']))}`.")
    else:
        L.append("  - No init event found in the output.")
    if res:
        so = json.dumps(res["structured_output"], sort_keys=True) if res["structured_output"] is not None else "none"
        L.append(f"  - result event: subtype `{scrub(res['subtype'])}`, is_error `{res['is_error']}`, turns {res['num_turns']}, "
                 f"cost ${res['cost']}, duration {res['duration_ms']} ms; structured_output `{scrub(so)}`.")
        if res["denials"]:
            L.append(f"  - permission denials: `{scrub(', '.join(res['denials']))}`.")
        if res["cost"] is not None and isinstance(res["cost"], (int, float)) and res["cost"] > 0.25:
            L.append(f"  - WARNING: cost {res['cost']} exceeds the $0.25 cap.")
    else:
        L.append("  - No result event found in the output (the call may have failed; see the .err lines below).")
    uses = ", ".join(sorted(set(info["tool_uses"]))) or "none"
    L.append(f"  - Tools the model called: `{scrub(uses)}`.")
    if bad:
        L.append(f"  - {bad} non-JSON line(s) in the stream were ignored.")
    if err_lines:
        L.append("  - stderr (scrubbed, last %d lines): `%s`" % (len(err_lines), scrub(" | ".join(err_lines))))
    L.append("  - Verdicts on the four open questions:")
    for q, v, why in vs:
        L.append(f"    - {q}: **{v}**. {scrub(why)}")
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("probe", type=Path)
    ap.add_argument("--err", type=Path)
    ap.add_argument("--agent-file", type=Path, help="agent .md whose frontmatter tools: line is compared (writer.md)")
    ap.add_argument("--tools-flag", default="Read,Skill,StructuredOutput")
    ap.add_argument("--date", default=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"))
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    if not a.probe.is_file():
        print(f"a4_fold: no such file: {a.probe}", file=sys.stderr)
        return 2
    events, bad = parse_stream(a.probe)
    info = extract(events)
    fm = frontmatter_tools(a.agent_file) if a.agent_file and a.agent_file.is_file() else None
    tools_flag = csv_names(a.tools_flag)
    err_lines: list[str] = []
    if a.err and a.err.is_file():
        err_lines = [ln for ln in a.err.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()][-8:]
    text = render(info, verdicts(info, tools_flag, fm), err_lines, bad, a.date, tools_flag)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
