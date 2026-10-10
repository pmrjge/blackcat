#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""B1-T14's fold driver (docs/BAYES.md A.11.3, WP5 5b): one shipped-fitter fit per rolling-origin fold, stdlib only.

Run (the user, from a terminal, after confirming that no C10, equilibrium run or other fit is active):
    B1_REPO=<main checkout> uv run --no-cache --script tests/b1_folds.py --data <copy>/usage --out-dir D \
        [--snapshots <copy>/limits/snapshots] [--python <tools venv python>] [--folds N] [--no-accel-lock]
then  tests/b1_backtest.py --data <copy>/usage --hyper-dir D ...

Sessions are ordered by their first row (b1_backtest.session_order, the same rows and order the backtest reads).
Fold k (k >= --min-train-sessions, the last --folds N) tests on session k and trains on sessions 0 .. k - 1 only:
the driver builds a temporary state directory (XDG_STATE_HOME under the work directory, 0700) holding only the
usage rows of those sessions (each runs*.csv filtered line by line, header kept) and their limits snapshots, and
runs the shipped fitter with its shipped sampler (no --chains/--draws/--tune/--timeout override):

    <python> -I -B <B1_REPO>/dot-config/dot-claude/hooks/stack_bayes.py fit --no-sched --out <fold>/bayes.json \
        --regime <the test session's regime>

The fitter reads its seed beside itself (B1_REPO's, the backtest's). --regime (owned by WP5 5c) is the regime the
fit treats as current: the test session's (its earliest row's `regime` cell), never the live or checkout regime;
a fitter whose --help does not offer --regime is refused. The fit runs with cwd /, niced, in its own session, and
is killed with its process group after --timeout seconds.

Per fold it writes into --out-dir: fold<k>_turns.json and fold<k>_ctx.json (hyper.turns and hyper.ctx of the
fold's bayes.json, the shape b1_backtest.load_hyper_file reads), fold<k>_gate.json (fold, test session, training
sessions, evidence id, regime, data.regime_current, sampler, stack_limits.model_gate recomputed from each model's
diag for turns-nb2s-h4 and ctx-ln-h4, ok, reason), fold<k>_bayes.json and fold<k>.log. A fold whose fit produced
no valid bayes.json (exit code, timeout, the reader's validation, another evidence id or seed) or whose test
session has no regime gets ok false with the reason and no hyper files: never dropped, and the gates are never
loosened; b1_backtest then reads the family as blocked:gate.

Refusals (exit 2, nothing fitted): an --out-dir or --work-dir that resolves into the live state directory
(~/.local/state/claude-agent-stack or $XDG_STATE_HOME/claude-agent-stack); a fitter without --regime; the live
<state>/accel.lock held by someone else or not obtainable (stack_usage.accel_acquire, kept for the whole run and
passed to each fit), unless --no-accel-lock. Exit 0 when every fold's gates pass, 1 when one fails (blocked:gate),
2 on a refusal or an error.
"""
import argparse
import csv
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import b1_backtest as BT  # noqa: E402  (puts B1_REPO's hooks on sys.path)

L = BT.L
HOOKS = BT.HOOKS
FITTER = os.path.join(HOOKS, "stack_bayes.py")
MODELS = ("turns-nb2s-h4", "ctx-ln-h4")
HYPER_KEYS = ("turns", "ctx")
ACCEL_HOLDER = "b1-folds"
FIT_WALL_S = 960                 # the driver's own cap per fold: above stack_bayes' FIT_TIMEOUT_S (930 s)
HELP_TIMEOUT_S = 60
NICE = 10
ENV_DROP = ("VIRTUAL_ENV", "CONDA_PREFIX", "CONDA_DEFAULT_ENV", "UV_INTERNAL__PARENT_INTERPRETER", "UV_PYTHON",
            "UV_CONFIG_FILE", "PYTHONPATH", "PYTHONHOME", "XDG_STATE_HOME")
ENV_DROP_PREFIXES = ("PYTENSOR", "NUMBA_", "AESARA", "THEANO")


class Refused(Exception):
    """A precondition the driver will not run without (exit 2)."""


# ---------------------------------------------------------------- the live state directory
def live_state_roots():
    """The live state directories: ~/.local/state/claude-agent-stack and, when XDG_STATE_HOME is set,
    $XDG_STATE_HOME/claude-agent-stack (resolved)."""
    bases = [os.path.expanduser("~/.local/state")]
    if os.environ.get("XDG_STATE_HOME"):
        bases.append(os.environ["XDG_STATE_HOME"])
    return sorted({os.path.realpath(os.path.join(b, "claude-agent-stack")) for b in bases})


def inside(path, root):
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def refuse_live_target(path, what):
    for root in live_state_roots():
        if inside(path, root):
            raise Refused(f"{what} {path} resolves into the live state directory {root}: refused (A.11.3)")


# ---------------------------------------------------------------- the fitter
def fitter_env(xdg):
    """The fit's environment: the caller's, without venv/PYTHON*/compile-cache knobs (as stack_usage.bayes_env),
    XDG_STATE_HOME = the fold's temporary state; the STACK_* knobs are kept (the fit ignores the regime they hash
    because --regime overrides it)."""
    env = {k: v for k, v in os.environ.items() if k not in ENV_DROP and not k.startswith(ENV_DROP_PREFIXES)}
    env.update(PATH="/usr/bin:/bin:/usr/sbin:/sbin", PYTHONDONTWRITEBYTECODE="1")
    if xdg is not None:
        env["XDG_STATE_HOME"] = xdg
    return env


def has_regime_option(python, fitter):
    """Whether the fitter's --help offers --regime (WP5 5c's option)."""
    try:
        p = subprocess.run([python, "-I", "-B", fitter, "--help"], stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, cwd="/", env=fitter_env(None), timeout=HELP_TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return p.returncode == 0 and "--regime" in p.stdout


def _nice(pid):
    """Lower the fit's priority (after the spawn: no preexec_fn, which is unsafe with threads)."""
    try:
        os.setpriority(os.PRIO_PROCESS, pid, max(NICE, os.getpriority(os.PRIO_PROCESS, pid)))
    except OSError:
        pass


def run_fit(cmd, env, log_path, timeout, keep_fds):
    """(returncode or None, last stdout line, None | "timeout"): its own session and process group, cwd /,
    niced; stdout and stderr to log_path; the whole group killed after `timeout` seconds."""
    with open(log_path, "wb") as log:
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env, cwd="/",
                             close_fds=True, pass_fds=tuple(keep_fds), start_new_session=True)
        _nice(p.pid)
        why = None
        try:
            p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            why = "timeout"
        except BaseException:
            _killpg(p)
            raise
        if why:
            _killpg(p)
    last = ""
    try:
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            lines = [x.strip() for x in fh.read().splitlines() if x.strip().startswith("bayes:")]
        last = lines[-1][:300] if lines else ""
    except OSError:
        pass
    return (None if why else p.returncode), last, why


def _term(signum, frame):
    raise SystemExit(128 + signum)


def _killpg(p):
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except OSError:
        try:
            p.kill()
        except OSError:
            pass
    p.wait()


# ---------------------------------------------------------------- a fold's state
def filter_csv(src, dst, keep):
    """Copy the header and the lines of src whose `session` cell is in keep (each line parsed on its own, as
    stack_limits._csv_rows; lines it cannot parse are left out, as the reader drops them). Returns lines kept."""
    n, header, idx = 0, None, None
    with open(src, encoding="utf-8", errors="replace", newline="") as fh, \
            open(dst, "w", encoding="utf-8", newline="") as out:
        for ln in fh:
            try:
                cells = next(csv.reader((ln.replace("\x00", ""),)), None)
            except csv.Error:
                continue
            if not cells:
                continue
            if header is None:
                header = cells
                idx = header.index("session") if "session" in header else None
                out.write(ln if ln.endswith("\n") else ln + "\n")
                continue
            if idx is not None and idx < len(cells) and cells[idx].strip() in keep:
                out.write(ln if ln.endswith("\n") else ln + "\n")
                n += 1
    return n


def build_state(root, data, snapshots, train):
    """<root>/claude-agent-stack/{usage,limits/snapshots} with the training sessions' rows and snapshots only."""
    st = os.path.join(root, "claude-agent-stack")
    usage, snaps = os.path.join(st, "usage"), os.path.join(st, "limits", "snapshots")
    for d in (root, st, usage, os.path.dirname(snaps), snaps):
        os.makedirs(d, mode=0o700, exist_ok=True)
    keep = set(train)
    for src in BT.data_paths(data):
        filter_csv(src, os.path.join(usage, os.path.basename(src)), keep)
    copied = 0
    if snapshots and os.path.isdir(snapshots):
        for s in sorted(keep):
            if not L.ID_RE.match(s):
                continue
            p = os.path.join(snapshots, s + ".json")
            if os.path.isfile(p) and not os.path.islink(p):
                shutil.copyfile(p, os.path.join(snaps, s + ".json"))
                copied += 1
    return st, copied


def check_doc(path, seed, eid):
    """(doc, None) for a bayes.json the reader accepts with the fold's evidence id, seed and both hyper models;
    (None, reason) otherwise."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read(L.BAYES_MAX_BYTES + 1)
    except OSError as exc:
        return None, f"no bayes.json ({type(exc).__name__})"
    if len(raw) > L.BAYES_MAX_BYTES:
        return None, "bayes.json too large"
    try:
        doc = json.loads(raw.decode("utf-8"), parse_constant=_no_constant)
        L._bayes_doc_checked(doc, seed)
    except (ValueError, RecursionError, L._BayesInvalid) as exc:
        return None, f"bayes.json invalid ({str(exc)[:120]})"
    if doc["evidence_id"] != eid:
        return None, "bayes.json evidence_id is not the fold's training rows'"
    if not all(k in (doc.get("hyper") or {}) for k in HYPER_KEYS) or not all(m in doc["models"] for m in MODELS):
        return None, "bayes.json lacks hyper.turns/hyper.ctx or a model"
    return doc, None


def _no_constant(name):
    raise ValueError(f"non-finite number {name}")


def write_json(path, doc):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def fit_fold(k, order, by_sess, a, seed, work, keep_fds):
    """Build fold k's state, run the fitter, write the fold's files. Returns the gate document."""
    test_s, train_s = order[k], list(order[:k])
    if test_s in train_s:
        raise ValueError(f"fold {k}: the test session is in its training set")
    train_rows = [r for s in train_s for r in by_sess[s]]
    eid = L.evidence_id(train_rows)
    regime = BT.fold_regime(by_sess[test_s])
    gate = {"fold": k, "test_session": test_s, "train_sessions": train_s, "evidence_id": eid, "regime": regime,
            "regimes_seen": sorted({r["regime"] for r in by_sess[test_s] if r.get("regime")}),
            "data": {"regime_current": None}, "fitter": a.fitter, "python": a.python, "sampler": None,
            "models": {m: {"ok": False} for m in MODELS}, "ok": False, "reason": None, "rc": None, "summary": None}
    out = os.path.join(a.out_dir, f"fold{k}")
    for suffix in ("_turns.json", "_ctx.json", "_bayes.json"):          # never a stale file from an earlier run
        if os.path.lexists(out + suffix):
            os.unlink(out + suffix)
    if not regime:
        gate["reason"] = "the test session has no regime cell: no fit (never the live or checkout regime)"
        write_json(out + "_gate.json", gate)
        return gate
    fold_dir = os.path.join(work, f"fold{k}")
    xdg = os.path.join(fold_dir, "state")
    refuse_live_target(xdg, "fold state")
    os.mkdir(fold_dir, 0o700)                       # FileExistsError: never a fold state left by an earlier run
    st, gate["snapshots"] = build_state(xdg, a.data, a.snapshots, train_s)
    os.symlink(os.path.join(work, "bayes-cache"), os.path.join(st, "bayes-cache"))   # compile caches across folds
    seen, _ = L.read_rows(BT.data_paths(os.path.join(st, "usage")), models=L.agent_models(
        os.path.join(BT.REPO, "dot-config", "dot-claude", "agents")))
    seen_s = {r["session"] for r in seen}
    if test_s in seen_s or not seen_s <= set(train_s) or L.evidence_id(seen) != eid:
        raise ValueError(f"fold {k}: the fold's state does not hold exactly its training rows")
    bayes = os.path.join(fold_dir, "bayes.json")
    cmd = [a.python, "-I", "-B", a.fitter, "fit", "--no-sched", "--out", bayes, "--regime", regime]
    t0 = time.monotonic()
    rc, summary, why = run_fit(cmd, fitter_env(xdg), out + ".log", a.timeout, keep_fds)
    gate.update(rc=rc, summary=summary, seconds=round(time.monotonic() - t0, 1))
    if rc != 0:
        gate["reason"] = f"fit failed: {why or f'exit {rc}'}"
    else:
        doc, why = check_doc(bayes, seed, eid)
        if doc is None:
            gate["reason"] = why
        else:
            shutil.copyfile(bayes, out + "_bayes.json")
            for key in HYPER_KEYS:
                write_json(out + f"_{key}.json", doc["hyper"][key])
            gate["models"] = {m: {"ok": bool(L.model_gate(doc["models"][m])), "diag": doc["models"][m].get("diag")}
                              for m in MODELS}
            gate["data"] = {"regime_current": (doc.get("data") or {}).get("regime_current")}
            gate.update(sampler=doc.get("sampler"), fit_id=doc.get("fit_id"))
            gate["ok"] = all(v["ok"] for v in gate["models"].values())
            if not gate["ok"]:
                gate["reason"] = "model gate failed: " + ",".join(m for m in MODELS if not gate["models"][m]["ok"])
    write_json(out + "_gate.json", gate)
    if not a.keep_work:
        shutil.rmtree(fold_dir, ignore_errors=True)
    return gate


def take_accel_lock():
    """The live <state>/accel.lock through stack_usage.accel_acquire (fd), or Refused."""
    import stack_usage
    fd = stack_usage.accel_acquire(ACCEL_HOLDER)
    if fd is None:
        raise Refused(f"{stack_usage.accel_lock_path()} is held by another accelerator job or cannot be taken: "
                      "refused (run when no C10, equilibrium run or fit is active, or pass --no-accel-lock)")
    return fd


def run(a):
    a.out_dir = os.path.abspath(a.out_dir)
    refuse_live_target(a.out_dir, "--out-dir")
    if a.work_dir:
        refuse_live_target(a.work_dir, "--work-dir")
    if not has_regime_option(a.python, a.fitter):
        raise Refused(f"{a.fitter} has no --regime option (WP5 5c), or `{a.python} -I -B {a.fitter} --help` did "
                      "not run: a fold fit must treat the test session's regime as current, never the live or "
                      "checkout one (A.11.3); refused")
    seed = L.load_seed()
    _rows, order, by_sess = BT.read_data(a.data)
    folds = BT.fold_ids(len(order), a.min_train_sessions, a.folds)
    if not folds:
        raise ValueError("no fold to fit (too few sessions)")
    fd = None if a.no_accel_lock else take_accel_lock()
    try:
        os.makedirs(a.out_dir, mode=0o700, exist_ok=True)
        work = a.work_dir or tempfile.mkdtemp(prefix=".b1-folds-", dir=a.out_dir)
        work = os.path.abspath(work)
        refuse_live_target(work, "work directory")
        os.makedirs(os.path.join(work, "bayes-cache"), mode=0o700, exist_ok=True)
        gates = []
        try:
            for k in folds:
                g = fit_fold(k, order, by_sess, a, seed, work, () if fd is None else (fd,))
                print(f"fold {k}: test {g['test_session']} trains on {len(g['train_sessions'])} sessions, regime "
                      f"{g['regime']} ({g['data']['regime_current']}), gates "
                      f"{ {m: v['ok'] for m, v in g['models'].items()} }" + (f": {g['reason']}" if g["reason"] else ""),
                      flush=True)
                gates.append(g)
        finally:
            if not a.work_dir and not a.keep_work:
                shutil.rmtree(work, ignore_errors=True)
    finally:
        if fd is not None:
            os.close(fd)
    return gates


def main(argv=None):
    ap = argparse.ArgumentParser(description="B1-T14 fold driver: one shipped-fitter fit per fold (BAYES.md A.11.3)")
    ap.add_argument("--data", required=True, help="directory with runs*.csv (a copy of <state>/usage)")
    ap.add_argument("--snapshots", default=None,
                    help="limits snapshots directory (default: <data>/../limits/snapshots when it exists)")
    ap.add_argument("--out-dir", required=True, help="where fold<k>_{turns,ctx,gate,bayes}.json and logs go")
    ap.add_argument("--work-dir", default=None, help="the folds' temporary state (default: a temporary directory "
                                                     "inside --out-dir, removed at the end)")
    ap.add_argument("--keep-work", action="store_true", help="keep the folds' temporary state")
    ap.add_argument("--python", default=os.path.join(os.environ.get("CLAUDE_CONFIG_DIR")
                                                     or os.path.expanduser("~/.claude"), "venvs", "tools", "bin",
                                                     "python"),
                    help="the interpreter with the Bayes lock (default: the installed tools venv's)")
    ap.add_argument("--fitter", default=FITTER, help="stack_bayes.py (default: B1_REPO's hooks)")
    ap.add_argument("--folds", type=int, default=0, help="fit the last N folds (0: all), as b1_backtest --folds")
    ap.add_argument("--min-train-sessions", type=int, default=2)
    ap.add_argument("--timeout", type=int, default=FIT_WALL_S, help="wall-clock cap of one fold's fit, seconds")
    ap.add_argument("--no-accel-lock", action="store_true",
                    help="run without the live accel.lock (only when you know no other accelerator job runs)")
    a = ap.parse_args(argv)
    if a.snapshots is None:
        cand = os.path.join(os.path.dirname(os.path.abspath(a.data)), "limits", "snapshots")
        a.snapshots = cand if os.path.isdir(cand) else None
    a.fitter = os.path.abspath(a.fitter)
    try:
        prev = (signal.signal(signal.SIGTERM, _term),)  # a SIGTERM kills the running fit's group (run_fit)
    except ValueError:                                  # not the main thread: the timeout still holds
        prev = None
    try:
        gates = run(a)
    except Refused as exc:
        sys.stderr.write(f"b1_folds: {exc}\n")
        return 2
    except (OSError, ValueError, KeyError, L.SeedError) as exc:
        sys.stderr.write(f"b1_folds: {type(exc).__name__}: {exc}\n")
        return 2
    finally:
        if prev is not None:
            signal.signal(signal.SIGTERM, prev[0])
    bad = [g["fold"] for g in gates if not g["ok"]]
    print(f"b1_folds: {len(gates)} folds, " + (f"gate failed in folds {bad}: blocked:gate" if bad else "every gate passes"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
