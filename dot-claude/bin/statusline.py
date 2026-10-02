#!/usr/bin/env python3
"""Status line for the claude-agent-stack (Claude Code `statusLine`; session JSON arrives on stdin).

    blackcat · Sonnet 5.5 · low · ctx 156K/900K ▓▓▓░░░░░ · 5h 23% · 7d 41% · cache 91%

"ctx" counts the tokens in the main conversation's context against the auto-compact window
(autoCompactWindow in settings.json, 900K in this stack on the 5.5 models' 1M window, capped at the
model's window), so the bar
shows how close the next automatic compaction is. Rate limits appear only for claude.ai Pro/Max
sessions. Stdlib only; any error prints a minimal line instead of failing. Installed by install.sh
and set as `statusLine` only when you have none; remove the key from settings.json to turn it off.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

# agent_guard.py's session-env hook records what it did in the session's state dir: a failure, or a
# hook still "running" after this long (it died midway), shows a warning in the line
SESSION_ENV_STALE_S = 30


def settings_window():
    """autoCompactWindow the session uses: CLAUDE_CODE_AUTO_COMPACT_WINDOW wins, then the
    settings.json next to this script's config dir."""
    env = os.environ.get("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "").strip()
    if env.isdigit():
        return int(env)
    try:
        s = json.loads((Path(__file__).resolve().parent.parent / "settings.json").read_text())
        v = s.get("autoCompactWindow")
        return int(v) if isinstance(v, (int, float)) else None
    except (OSError, ValueError, TypeError):
        return None


def session_env_warning(sid, now=None):
    """The session-env hook's failure for this session as a short warning, or None."""
    if not isinstance(sid, str) or not sid.strip():
        return None
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", sid)[:128]
    try:
        with open(os.path.join(base, "claude-agent-stack", safe, "session-env.json")) as f:
            st = json.load(f)
    except (OSError, ValueError):
        return None                     # not run yet, or a stack without the hook: doctor.sh tells
    if not isinstance(st, dict):
        return None
    now = time.time() if now is None else now
    ts = st.get("ts") if isinstance(st.get("ts"), (int, float)) else 0
    if st.get("state") == "failed" or (st.get("state") == "running" and now - ts > SESSION_ENV_STALE_S):
        return "! Bash sandbox env missing: doctor.sh"
    return None


def kilo(n):
    if n >= 1_000_000:
        return "%.1fM" % (n / 1e6)
    if n >= 1000:
        return "%dK" % round(n / 1000.0)
    return str(n)


def color(text, frac, on):
    if not on:
        return text
    code = "31" if frac >= 0.9 else "33" if frac >= 0.75 else "32"
    return "\033[%sm%s\033[0m" % (code, text)


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    parts = []
    agent = (data.get("agent") or {}).get("name")
    if agent:
        parts.append(str(agent))
    model = (data.get("model") or {}).get("display_name") or (data.get("model") or {}).get("id")
    if model:
        parts.append(str(model))
    effort = (data.get("effort") or {}).get("level")
    if effort:
        parts.append(str(effort))

    cw = data.get("context_window") or {}
    used = cw.get("total_input_tokens")
    if not isinstance(used, (int, float)):
        cu = cw.get("current_usage")
        # null before the first API call and right after /compact: show nothing rather than 0
        used = sum(int(cu.get(k) or 0) for k in
                   ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")) \
            if isinstance(cu, dict) else None
    size = cw.get("context_window_size") if isinstance(cw.get("context_window_size"), int) else None
    window = settings_window()
    limit = min(x for x in (window, size) if x) if (window or size) else None
    tty = os.environ.get("NO_COLOR") is None
    if limit and used is not None:
        frac = max(0.0, min(1.0, float(used) / float(limit)))
        cells = 8
        bar = "▓" * int(round(frac * cells)) + "░" * (cells - int(round(frac * cells)))
        parts.append(color("ctx %s/%s %s" % (kilo(int(used)), kilo(limit), bar), frac, tty))

    rl = data.get("rate_limits") or {}
    for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
        pct = (rl.get(key) or {}).get("used_percentage")
        if isinstance(pct, (int, float)):
            parts.append(color("%s %d%%" % (label, round(pct)), pct / 100.0, tty))
    hit = (data.get("prompt_cache") or {}).get("hit_ratio")
    if isinstance(hit, (int, float)):
        parts.append("cache %d%%" % round(hit * 100))

    warning = session_env_warning(data.get("session_id"))
    if warning:
        parts.insert(0, "\033[31m%s\033[0m" % warning if tty else warning)   # first: never cut

    line = " · ".join(parts) if parts else "claude-agent-stack"
    cols = os.environ.get("COLUMNS", "")
    if cols.isdigit() and int(cols) > 20 and len(line) > int(cols) + 40:   # ANSI codes don't count
        line = line[: int(cols) + 30]
    sys.stdout.write(line + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception:  # a status line must never error out
        sys.stdout.write("claude-agent-stack\n")
