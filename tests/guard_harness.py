"""Harness for piping hook events into agent_guard.py with an isolated XDG_STATE_HOME
(used by tests/test_guard_regressions.py).

GUARD env var selects the hook file (default: dot-claude/hooks/agent_guard.py in this repo).
`Env.run(ev, patch=...)` runs the hook through guard_race_main.py, which wraps named functions
with a sleep so race windows become deterministic.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
GUARD = os.environ.get("GUARD", os.path.join(os.path.dirname(HERE), "dot-claude", "hooks",
                                             "agent_guard.py"))
KNOB_PREFIXES = ("STACK_", "BLACKCAT_", "GOD_", "SCREEN_", "STRIP_", "CLAUDE_CODE_MAX")
# The mechanics these tests exercise were written against these caps; the shipped defaults are
# checked separately (test_agent_guard.py::test_shipped_spawn_defaults).
BASELINE = {"BLACKCAT_MAX_DISPATCH": "6", "BLACKCAT_MAX_STEPS": "8", "GOD_ONCE_PER_SESSION": "0",
            "GOD_SPAWNERS": "orchestrator,main",
            "STACK_MAX_FANOUT_BY_TYPE": "orchestrator=8,planner=8,plan-reviewer=8"}


class Env:
    def __init__(self, **knobs):
        self.tmp = tempfile.mkdtemp(prefix="hookrev-")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(KNOB_PREFIXES)}
        self.env["XDG_STATE_HOME"] = os.path.join(self.tmp, "state")
        self.env.update(BASELINE)
        self.env.update({k: str(v) for k, v in knobs.items()})
        self.sid = "s-" + uuid.uuid4().hex[:10]
        self.proj = os.path.join(self.tmp, "projects", "proj")
        os.makedirs(os.path.join(self.proj, self.sid, "subagents"), exist_ok=True)
        self.transcript = os.path.join(self.proj, self.sid + ".jsonl")
        open(self.transcript, "w").write("{}\n")

    # ------------------------------------------------------------------ paths
    def sdir(self):
        return os.path.join(self.env["XDG_STATE_HOME"], "claude-agent-stack", self.sid)

    def sub_transcript(self, aid, age=0.0):
        """Create the documented subagent transcript file with an mtime `age` seconds old."""
        p = os.path.join(self.proj, self.sid, "subagents", "agent-%s.jsonl" % aid)
        open(p, "a").write("{}\n")
        t = time.time() - age
        os.utime(p, (t, t))
        return p

    def lock(self, name="god-coder.lock"):
        p = os.path.join(self.sdir(), name)
        return json.load(open(p)) if os.path.exists(p) else None

    def age_lock(self, seconds, name="god-coder.lock"):
        p = os.path.join(self.sdir(), name)
        obj = json.load(open(p))
        obj["ts"] = time.time() - seconds
        json.dump(obj, open(p, "w"))

    def reg(self, aid):
        p = os.path.join(self.sdir(), "agents", aid + ".json")
        return json.load(open(p)) if os.path.exists(p) else None

    def age_reg(self, aid, seconds, keys=("spawned", "started")):
        p = os.path.join(self.sdir(), "agents", aid + ".json")
        obj = json.load(open(p))
        for k in keys:
            if k in obj:
                obj[k] = time.time() - seconds
        json.dump(obj, open(p, "w"))

    # ------------------------------------------------------------------ events
    def base(self, event, **kw):
        ev = {"session_id": self.sid, "hook_event_name": event,
              "transcript_path": self.transcript, "cwd": self.tmp}
        ev.update({k: v for k, v in kw.items() if v is not None})
        return ev

    def pre_agent(self, child, agent_id=None, agent_type=None, prompt="p1", tid=None, **ti):
        return self.base("PreToolUse", tool_name="Agent", prompt_id=prompt,
                         tool_use_id=tid or "toolu_" + uuid.uuid4().hex[:12],
                         agent_id=agent_id, agent_type=agent_type,
                         tool_input=dict({"subagent_type": child, "prompt": "x",
                                          "description": "x"}, **ti))

    def post_agent(self, pre_ev, child_id, status="async_launched", response=None):
        ev = dict(pre_ev, hook_event_name="PostToolUse")
        ev["tool_response"] = response if response is not None else {
            "status": status, "agentId": child_id, "description": "x", "prompt": "x",
            "outputFile": "/tmp/x"}
        return ev

    def fail_agent(self, pre_ev, event="PostToolUseFailure"):
        return dict(pre_ev, hook_event_name=event, error="boom")

    def start(self, aid, atype):
        return self.base("SubagentStart", agent_id=aid, agent_type=atype)

    def stop(self, aid, atype, transcript=None):
        return self.base("SubagentStop", agent_id=aid, agent_type=atype, stop_hook_active=False,
                         agent_transcript_path=transcript, last_assistant_message="done")

    def send(self, to, agent_id=None, agent_type=None, prompt="p1"):
        return self.base("PreToolUse", tool_name="SendMessage", prompt_id=prompt,
                         tool_use_id="toolu_" + uuid.uuid4().hex[:12], agent_id=agent_id,
                         agent_type=agent_type, tool_input={"to": to, "message": "more"})

    def prompt(self, pid):
        return self.base("UserPromptSubmit", prompt_id=pid, prompt="hi")

    def screen(self, agent_id=None, agent_type=None):
        return self.base("PreToolUse", tool_name="mcp__computer-use__screenshot",
                         tool_use_id="toolu_" + uuid.uuid4().hex[:12], agent_id=agent_id,
                         agent_type=agent_type, tool_input={})

    # ------------------------------------------------------------------ running
    def _argv(self, args, patch):
        if patch:
            return [sys.executable, os.path.join(HERE, "guard_race_main.py"), GUARD, json.dumps(patch),
                    *args]
        return [sys.executable, GUARD, *args]

    def run(self, ev, args=(), extra=None, patch=None):
        e = dict(self.env, **(extra or {}))
        p = subprocess.run(self._argv(args, patch), input=json.dumps(ev), capture_output=True,
                           text=True, env=e, timeout=60)
        return Result(p)

    def spawn(self, ev, args=(), extra=None, patch=None):
        """Start the hook without waiting (for interleaving); returns Popen."""
        e = dict(self.env, **(extra or {}))
        p = subprocess.Popen(self._argv(args, patch), stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=e)
        p.stdin.write(json.dumps(ev))
        p.stdin.close()
        return p

    def run_many(self, evs, args=(), extra=None):
        procs = [self.spawn(ev, args, extra) for ev in evs]
        return [Result.from_popen(p) for p in procs]


class Result:
    def __init__(self, p):
        self.rc, self.stdout, self.stderr = p.returncode, p.stdout, p.stderr

    @classmethod
    def from_popen(cls, p):
        out, err = p.stdout.read(), p.stderr.read()
        p.wait(timeout=60)

        class _P:
            pass
        q = _P()
        q.returncode, q.stdout, q.stderr = p.returncode, out, err
        return cls(q)

    @property
    def decision(self):
        if not self.stdout.strip():
            return "allow(no-output)"
        return json.loads(self.stdout)["hookSpecificOutput"]["permissionDecision"]

    @property
    def reason(self):
        if not self.stdout.strip():
            return ""
        return json.loads(self.stdout)["hookSpecificOutput"].get("permissionDecisionReason", "")

    def __repr__(self):
        r = self.reason
        return "%s%s" % (self.decision, (" | " + r[:150]) if r else "")


def show(label, value):
    print("  %-58s %s" % (label, value))
