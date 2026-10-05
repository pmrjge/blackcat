# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Shared parts of the instructor scripts (imported, never a recipe): argument allowlist, detail log, list-form
subprocess calls, the output contract: stdout is one line `OK|FAIL|NOOP <verb> key=value... log=<path>`, exit OK 0,
FAIL 1, bad argument 2 (a FAIL line), NOOP 3; details in <checkout>/.claude-work/instr/. A Bash PreToolUse hook
sees only `just ... <recipe> <args>`, never the commands run here, so each argument meets its own allowlist here."""
from __future__ import annotations

import argparse
import contextlib
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import NoReturn

EXIT, BAD_ARG = {"OK": 0, "FAIL": 1, "NOOP": 3}, 2
# git without repo-local hooks, fsmonitor commands or transports (.git/config is agent-writable)
GIT = ("git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "protocol.allow=never")
_BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,99}")
_PATH = re.compile(r"/[A-Za-z0-9._/+@-]{0,500}")


def branch_name(s: str) -> str:
    """argparse type: a plain local branch name (used as refs/heads/<name>, never as an option)."""
    bad = ".." in s or "//" in s or "/." in s or s.endswith((".lock", "/", ".")) or s == "HEAD"
    if not _BRANCH.fullmatch(s) or bad:
        raise argparse.ArgumentTypeError("branch name outside the allowlist")
    return s


def abs_path(s: str) -> Path:
    """argparse type: an absolute path of plain characters, no '..' component."""
    if not _PATH.fullmatch(s) or ".." in s.split("/"):
        raise argparse.ArgumentTypeError("path outside the allowlist")
    return Path(s)


def bounded_int(lo: int, hi: int):
    def conv(s: str) -> int:
        if not re.fullmatch(r"[0-9]{1,5}", s) or not lo <= int(s) <= hi:
            raise argparse.ArgumentTypeError(f"an integer in {lo}..{hi}")
        return int(s)
    return conv


def abort(verb: str, reason: str, code: int = EXIT["FAIL"]) -> NoReturn:  # a FAIL line without a log
    print(f"FAIL {verb} reason={reason} log=none", flush=True)
    sys.exit(code)


class Parser(argparse.ArgumentParser):  # a usage error: a FAIL line, exit 2, the message on stderr
    def __init__(self, verb: str, **kw):
        super().__init__(prog=verb, allow_abbrev=False, **kw)
        self.verb = verb

    def error(self, message: str):
        print(f"{self.verb}: {message}", file=sys.stderr)
        abort(self.verb, "bad-arg", BAD_ARG)


def clean_env(drop: tuple[str, ...] = ()) -> dict[str, str]:
    """The caller's environment without GIT_* (so -C decides the repository) and without `drop`."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k not in drop}
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def git_out(args: list[str], cwd: Path) -> tuple[int, str]:
    """A read-only git query: (exit code, stripped stdout)."""
    cp = subprocess.run([*GIT, *args], cwd=cwd, env=clean_env(), stdin=subprocess.DEVNULL,
                        capture_output=True, text=True, errors="replace")
    return cp.returncode, cp.stdout.strip()


def toplevel(repo: Path | None) -> Path | None:
    """The checkout that holds `repo` (default: the current directory), None outside git."""
    if repo is not None and not repo.is_dir():
        return None
    rc, out = git_out(["rev-parse", "--show-toplevel"], repo or Path.cwd())
    return Path(out) if rc == 0 and out else None


def _value(v) -> str:
    return re.sub(r"[^\x21-\x7e]", "_", str(v))[:160] or "-"


class Run:
    """One recipe run: a detail log, logged list-form commands, the status line."""

    def __init__(self, verb: str, checkout: Path):
        log_dir = checkout / ".claude-work" / "instr"
        if not (log_dir.parent.is_symlink() or log_dir.is_symlink()):  # nothing is made through a link
            log_dir.mkdir(parents=True, exist_ok=True)
        if log_dir.resolve() != checkout.resolve() / ".claude-work" / "instr":
            abort(verb, "log-dir-is-a-link")
        base, self.verb = f"{verb}-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}", verb
        for n in range(100):  # a fresh file, never an existing one (or a link placed there)
            self.log_path = log_dir / (base + (f"-{n}" if n else "") + ".log")
            with contextlib.suppress(FileExistsError):
                self.log = open(self.log_path, "x", encoding="utf-8", errors="replace")  # noqa: SIM115
                break
        else:
            abort(verb, "no-fresh-log")
        self.note(f"# {verb} {time.strftime('%F %T')} argv={shlex.join(sys.argv[1:])}")

    def note(self, text: str) -> None:
        self.log.write(text + "\n")
        self.log.flush()

    def step(self, label: str, argv: list[str], cwd: Path, env: dict[str, str] | None = None,
             timeout: int = 3600) -> tuple[int, str]:
        """Run one command, its output streamed into the log; returns (exit code, that output)."""
        self.note(f"\n## {label}: $ {shlex.join(argv)}   (cwd {cwd})")
        start, t0 = self.log.tell(), time.monotonic()
        try:
            p = subprocess.Popen(argv, cwd=cwd, env=env or clean_env(), stdin=subprocess.DEVNULL,
                                 stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as e:
            self.note(f"cannot start: {e}")
            return 127, ""
        try:
            rc = p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
            rc = p.wait()
            self.note(f"timeout after {timeout}s")
        self.log.seek(0, os.SEEK_END)
        with open(self.log_path, encoding="utf-8", errors="replace") as f:
            f.seek(start)
            out = f.read()
        self.note(f"## {label}: exit {rc} in {time.monotonic() - t0:.1f}s")
        return rc, out

    def plan(self, steps: list[tuple[str, list[str], Path]]) -> None:
        self.note("\n# plan\n" + "\n".join(f"{lb}: $ {shlex.join(av)}   (cwd {cwd})" for lb, av, cwd in steps))

    def finish(self, status: str, **kv) -> int:
        line = " ".join([status, self.verb, *(f"{k}={_value(v)}" for k, v in kv.items()),
                         f"log={self.log_path}"])
        self.note("\n" + line)
        self.log.close()
        print(line, flush=True)
        return EXIT[status]
