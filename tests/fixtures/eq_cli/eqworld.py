"""One scratch world for the stack-eq / stack-eq-check tests: HOME, a config dir with the hooks under test
(EQ_HOOKS_SRC overrides their source dir: a seeded-bug copy) and the fake eq_core, the launchers, a
stack-python link to this interpreter, a git project, and helpers that play the guard's part (brief.json,
tickets, members.json, captures, consent records, check verdicts). Never the real ~/.claude or ~/.local/state."""
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
HOOKS_SRC = Path(os.environ.get("EQ_HOOKS_SRC") or REPO / "dot-claude" / "hooks")
REAL_HOOKS = REPO / "dot-claude" / "hooks"
# the real eq_core (a sibling build): this repo's hooks once merged, or EQ_CORE_SRC (its worktree's hooks dir)
REAL_CORE = Path(os.environ.get("EQ_CORE_SRC") or REAL_HOOKS)
CLASSES = ("PF", "CP", "CR", "RS", "ES", "DS", "OE")
CLASS_KEYS = ("status", "member_type", "member_model_id", "agent_file_sha256", "N", "rounds", "view", "loo_view",
              "reducer", "tau", "t", "caps", "usd_per_mtok", "cost_ratio", "effect", "certainty", "pool")
GIT = ["git", "-c", "user.name=eq test", "-c", "user.email=eq@test.invalid", "-c", "init.defaultBranch=main",
       "-c", "commit.gpgsign=false"]
R = "0123abcd"
SID = "sess-1"


def sh(cmd, cwd=None, env=None, check=True):
    p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True)
    if check and p.returncode:
        raise AssertionError("%s -> %d: %s" % (cmd, p.returncode, p.stderr.decode()[-500:]))
    return p


class World:
    def __init__(self, tmp, core="fake"):
        self.t = Path(os.path.realpath(tmp))
        self.home = self.t / "home"
        self.home.mkdir()
        self.tmpdir = self.t / "tmp"
        self.tmpdir.mkdir()
        self.cfg = self.home / ".claude"
        self.hooks = self.cfg / "hooks"
        self.bin = self.cfg / "bin"
        self.hooks.mkdir(parents=True)
        self.bin.mkdir()
        for f in ("eq_policy.py", "eq_cli.py", "eq_isolation.py"):
            shutil.copy(HOOKS_SRC / f, self.hooks / f)
        if core == "fake":
            shutil.copy(HERE / "eq_core.py", self.hooks / "eq_core.py")
        elif core == "real":
            for f in ("eq_core.py", "eq_schemas.json", "eq_lenses.json"):
                if (REAL_CORE / f).exists():
                    shutil.copy(REAL_CORE / f, self.hooks / f)
        if not (self.hooks / "eq_schemas.json").exists():
            (self.hooks / "eq_schemas.json").write_text(json.dumps({c: {"type": "object"} for c in CLASSES}))
        shutil.copy(REAL_HOOKS / "stack_limits_seed.json", self.hooks / "stack_limits_seed.json")
        for f in ("stack-eq", "stack-eq-check"):
            shutil.copy(REPO / "dot-claude" / "bin" / f, self.bin / f)
            os.chmod(self.bin / f, 0o755)
        os.symlink(sys.executable, self.bin / "stack-python")
        self.settings = {"sandbox": {"filesystem": {"denyRead": [str(self.cfg) + "/**/stack.env"]}},
                         "permissions": {"deny": ["Read(~/.ssh/**)", "Read(**/.env)", "Read(~/.aws/**)"]}}
        (self.cfg / "settings.json").write_text(json.dumps(self.settings))
        self.manifest = {}
        self.set_params(self.params())
        self.state = self.home / ".local" / "state" / "claude-agent-stack"
        self.proj = None

    # -------------------------------------------------- config
    def params(self):
        return {"schema": "eqparams.v1", "version": 1, "created_utc": "2026-10-06T00:00:00Z", "provenance": {},
                "classes": {c: dict({k: None for k in CLASS_KEYS}, status="not_run") for c in CLASSES}}

    def set_params(self, obj):
        raw = json.dumps(obj).encode()
        (self.hooks / "eq_params.json").write_bytes(raw)
        self.manifest["eq_runtime"] = {"params_sha256": hashlib.sha256(raw).hexdigest()}
        self.write_manifest()

    def write_manifest(self):
        (self.cfg / ".stack-manifest.json").write_text(json.dumps(self.manifest))

    def env(self, **kw):
        e = {"HOME": str(self.home), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "TMPDIR": str(self.tmpdir),
             "LANG": "C"}
        e.update({k: v for k, v in kw.items() if v is not None})
        return e

    # -------------------------------------------------- the project
    def project(self, files=None):
        p = self.home / "proj"
        p.mkdir()
        files = files if files is not None else {
            "README.md": "demo\n",
            "check.sh": "#!/bin/sh\necho run >> \"$HOME/check-runs.log\"\n. ./tests/run.sh\n",
            "tests/run.sh": "v=$(cat src/value.txt)\nif [ \"$v\" = 42 ]; then echo PASS; exit 0; fi\n"
                            "echo \"FAIL $v\"; exit 1\n",
            "src/value.txt": "0\n",
        }
        for rel, text in files.items():
            (p / rel).parent.mkdir(parents=True, exist_ok=True)
            (p / rel).write_text(text)
        sh(GIT + ["init", "-q"], cwd=p)
        sh(GIT + ["add", "-A"], cwd=p)
        sh(GIT + ["commit", "-q", "-m", "init"], cwd=p)
        self.proj = p
        return p

    def worktree(self, i):
        wt = self.proj / ".claude" / "worktrees" / ("eq-m%d" % i)
        sh(GIT + ["worktree", "add", "-q", "-b", "eq-m%d" % i, str(wt), "HEAD"], cwd=self.proj)
        return wt

    # -------------------------------------------------- the guard's part
    def store(self, run=R, sid=SID):
        return self.state / sid / "eq" / run

    def brief(self, header, problem="Make src/value.txt hold 42.", cwd=None, run=R, sid=SID):
        d = self.store(run, sid)
        d.mkdir(parents=True, mode=0o700)
        for x in (d, d.parent, d.parent.parent, self.state):
            os.chmod(x, 0o700)
        h = {"class": None, "mode": "manual", "type": None, "check": None, "segments": []}
        h.update(header)
        (d / "brief.json").write_text(json.dumps({
            "schema": "eqbrief.v1", "run": run, "session": sid, "tool_use_id": "toolu_1", "caller_type": "blackcat",
            "caller_id": None, "cwd": str(cwd or self.proj), "created": time.time(), "header": h, "problem": problem}))
        return d

    def ticket(self, args, run=R, sid=SID, ts=None, argv=None):
        d = self.state / "eq-tickets"
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        blob = json.dumps(list(args), separators=(",", ":"), ensure_ascii=True).encode()
        name = hashlib.sha256(blob).hexdigest() + ".json"
        (d / name).write_text(json.dumps({"argv": list(argv if argv is not None else args),
                                          "ts": time.time() if ts is None else ts,
                                          "session": sid, "run": run, "agent_id": "a1", "agent_type": "equilibrium"}))
        return d / name

    def eq(self, *args, ticket=True, env=None, **tk):
        if ticket:
            self.ticket(args, **tk)
        return subprocess.run([str(self.bin / "stack-eq"), *args], env=env or self.env(), capture_output=True,
                              text=True, cwd=str(self.proj or self.home))

    def check(self, run, cand, env=None):
        return subprocess.run([str(self.bin / "stack-eq-check"), "--run", run, "--cand", str(cand)],
                              env=env or self.env(), capture_output=True, cwd=str(self.proj or self.home))

    def members(self, recs, run=R, sid=SID):
        (self.store(run, sid) / "members.json").write_text(json.dumps(recs))

    def capture(self, rnd, i, answer, status="ok", model=None, run=R, sid=SID):
        d = self.store(run, sid) / ("r%d" % rnd)
        d.mkdir(exist_ok=True, mode=0o700)
        (d / ("m%d.json" % i)).write_text(json.dumps({
            "run": run, "round": rnd, "member": i, "status": status, "answer": answer, "errors": [], "model": model,
            "model_drift": False, "agent_id": "m%d" % i, "ts": time.time()}))

    def verdict(self, rnd, i, stdout, rc, run=R, sid=SID, policy=None):
        """The guard's PostToolUse record of one stack-eq-check call, from its trailer (contracts.md 6)."""
        t = policy.parse_check_trailer(stdout) if policy else None
        ok = t is not None and t["run"] == run and t["cand"] == i and t["round"] == rnd and t["exit"] == 0 \
            and not t["timed_out"] and rc == 0
        verdict = "pass" if ok else ("fail" if t is not None else "unverifiable")
        d = self.store(run, sid) / ("r%d" % rnd)
        d.mkdir(exist_ok=True, mode=0o700)
        (d / ("check-c%d.json" % i)).write_text(json.dumps({
            "cand": i, "round": rnd, "exit": t["exit"] if t else None, "exit_source": "tool_response",
            "timed_out": bool(t and t["timed_out"]), "tail": "", "verdict": verdict}))
        return verdict

    def consent(self, kind="run", run=R, sid=SID, answer=None):
        tok = ("Run eq:%s" if kind == "run" else "Remove eq:%s") % run
        d = self.state / sid / "eq" / "consent"
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        name = "%s.json" % run if kind == "run" else "%s-remove.json" % run
        (d / name).write_text(json.dumps({"token": tok, "answer": answer or tok + " (est.)", "ts": time.time(),
                                          "source": "ask"}))


def mode(p):
    return stat.S_IMODE(os.lstat(p).st_mode)
