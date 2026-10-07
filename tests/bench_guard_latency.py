#!/usr/bin/env python3
"""Latency of the whole PreToolUse budget hook (`agent_guard.py budget`), one process per event as
Claude Code runs it, for one or more versions of agent_guard.py side by side (stdlib only).

  /usr/bin/python3 tests/bench_guard_latency.py --guard new=dot-config/dot-claude/hooks/agent_guard.py \
      --guard old=/path/to/an/older/checkout/dot-config/dot-claude/hooks/agent_guard.py [--n 25] [--calls 300]

Each label gets its own temp XDG_STATE_HOME, CLAUDE_CONFIG_DIR and a synthetic session laid out like
~/.claude/projects/<project>/: a main transcript with 50 API calls and a coder subagent with --calls
API calls. After SessionStart, UserPromptSubmit and SubagentStart (and two unmeasured warm-up events),
each of the --n measured rounds appends one API call to the subagent's transcript and times one
PreToolUse (Read by the subagent) through the hook; the labels alternate within a round, so drift hits
them alike. Every measured event must exit 0 and be allowed. Prints one JSON line per label (median,
p90, mean, min in ms) and, with two labels, the median delta of the second against the first.
Nothing outside the temp folders is written.
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
import uuid

PY = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable


class Session:
    def __init__(self, label, guard, calls, base):
        self.label, self.guard = label, os.path.abspath(guard)
        self.tmp = tempfile.mkdtemp(prefix="bench-%s." % label, dir=base)
        self.sid = "s-" + uuid.uuid4().hex[:12]
        proj = os.path.join(self.tmp, "projects", "p")
        self.subs = os.path.join(proj, self.sid, "subagents")
        os.makedirs(self.subs)
        self.main = os.path.join(proj, self.sid + ".jsonl")
        with open(self.main, "w") as f:
            f.write(json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n")
        self._calls(self.main, 50)
        self.sub = os.path.join(self.subs, "agent-A1.jsonl")
        self._calls(self.sub, calls)
        with open(os.path.join(self.subs, "agent-A1.meta.json"), "w") as f:
            json.dump({"agentType": "coder", "description": "bench"}, f)
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("STACK_", "BLACKCAT_", "SCREEN_", "CLAUDE_CODE_MAX"))}
        self.env.update(XDG_STATE_HOME=os.path.join(self.tmp, "xdg"), CLAUDE_CONFIG_DIR=os.path.join(self.tmp, "cfg"),
                        STACK_USAGE_COLLECT="0", PYTHONDONTWRITEBYTECODE="1")

    @staticmethod
    def _calls(path, n, tokens=10):
        with open(path, "a") as f:
            for _ in range(n):
                mid = uuid.uuid4().hex[:10]
                f.write(json.dumps({"type": "assistant", "requestId": "r" + mid,
                                    "message": {"id": mid, "usage": {"input_tokens": tokens}}}) + "\n")

    def ev(self, event, **kw):
        e = {"session_id": self.sid, "hook_event_name": event, "transcript_path": self.main, "cwd": self.tmp}
        e.update(kw)
        return e

    def run(self, ev, args=()):
        t = time.perf_counter()
        p = subprocess.run([PY, self.guard] + list(args), input=json.dumps(ev), capture_output=True, text=True,
                           env=self.env, timeout=60, check=False)
        return p, (time.perf_counter() - t) * 1000.0

    def setup(self):
        for e in (self.ev("SessionStart", source="startup"), self.ev("UserPromptSubmit", prompt_id="p1", prompt="go"),
                  self.ev("SubagentStart", agent_id="A1", agent_type="coder")):
            p, _ = self.run(e)
            if p.returncode != 0:
                raise SystemExit("%s: %s failed: %s" % (self.label, e["hook_event_name"], p.stderr[-400:]))
        for _ in range(2):
            self.pretool()

    def pretool(self):
        self._calls(self.sub, 1)
        ev = self.ev("PreToolUse", tool_name="Read", tool_use_id="tu-" + uuid.uuid4().hex[:8], prompt_id="p1",
                     tool_input={"file_path": "x"}, agent_id="A1", agent_type="coder")
        p, ms = self.run(ev, ("budget",))
        if p.returncode != 0:
            raise SystemExit("%s: PreToolUse exit %d: %s" % (self.label, p.returncode, p.stderr[-400:]))
        if p.stdout.strip():
            h = json.loads(p.stdout).get("hookSpecificOutput") or {}
            if h.get("permissionDecision", "allow") != "allow":
                raise SystemExit("%s: PreToolUse not allowed: %s" % (self.label, p.stdout[:400]))
        return ms


def summary(xs):
    xs = sorted(xs)
    return {"n": len(xs), "median_ms": round(statistics.median(xs), 2),
            "p90_ms": round(xs[min(len(xs) - 1, int(0.9 * len(xs)))], 2),
            "mean_ms": round(statistics.mean(xs), 2), "min_ms": round(xs[0], 2)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--guard", action="append", required=True, help="LABEL=path/to/agent_guard.py")
    ap.add_argument("--n", type=int, default=25)
    ap.add_argument("--calls", type=int, default=300)
    ap.add_argument("--tmp", default=None, help="parent of the temp folders (default: $TMPDIR)")
    a = ap.parse_args(argv)
    if a.n < 1:
        ap.error("--n must be >= 1")
    sessions = []
    for g in a.guard:
        label, _, path = g.partition("=")
        if not path or not os.path.isfile(path):
            ap.error("--guard wants LABEL=path to an existing agent_guard.py: %r" % g)
        sessions.append(Session(label, path, a.calls, a.tmp))
    for s in sessions:
        s.setup()
    times = {s.label: [] for s in sessions}
    for _ in range(a.n):
        for s in sessions:
            times[s.label].append(s.pretool())
    out = {}
    for s in sessions:
        out[s.label] = summary(times[s.label])
        print(json.dumps(dict(label=s.label, guard=s.guard, python=PY, calls=a.calls, **out[s.label])))
    if len(sessions) == 2:
        x, y = (out[s.label]["median_ms"] for s in sessions)
        print(json.dumps({"delta_median_ms": round(y - x, 2), "of": sessions[1].label, "vs": sessions[0].label,
                          "ratio": round(y / x, 3) if x else None}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
