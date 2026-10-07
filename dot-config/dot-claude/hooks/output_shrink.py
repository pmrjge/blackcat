"""PostToolUse output shrink (Stage 4 lever L2): a large Bash or Read result is cut to its decisive
lines before it enters the context; the full output stays reachable.

Hook: PostToolUse `Bash|Read`, `/bin/sh <config>/bin/stack-hook output_shrink` (fail-open: any error
leaves the output unchanged). It never touches `tool_input`, so the command the guard checked is the
command that ran. Claude Code fires PostToolUse only for results it treats as valid (a Bash exit 0,
or exit 1 of grep/rg/find/diff/test/git diff/git grep); a failing command goes to PostToolUseFailure,
which cannot replace output, and keeps Claude Code's own head-and-tail excerpt.

Mode, STACK_OUTPUT_SHRINK (environment; settings.json `env`):
  shadow (default; also any unknown value)  decide exactly as `on` would and log the decision; the
         output is never changed and no spill file is written.
  on     Bash over its threshold: the full output, credentials masked, goes to a 0600 spill file and
         Claude gets a header with its path plus the decisive lines (error lines first, then
         summaries, tail, head, diff/heading structure), in their original order with the omitted
         line ranges marked. Read over its threshold (no offset/limit given): the result keeps a
         contiguous head (so Claude Code's line numbers stay true) and `additionalContext` gives
         the line numbers where definitions and headings start in the hidden part and how to page
         it (offset/limit; never file text: hook context reaches the model as system text, so a
         line of an untrusted file must not); the file itself is the full output.
  off    nothing runs, nothing is written.

Never shrunk: a Read with offset or limit (the range was chosen), a Read of a prompt file (SKILL.md,
CLAUDE.md, skills/, rules/, agents/), any Read or Bash that touches the spill directory (a re-read: logged),
images, background and interrupted commands, a Bash result Claude Code already persisted
(`persistedOutputPath`, past its ~30,000-character inline limit: Claude gets a 2,000-character
preview and the path of Claude Code's own full copy) or returned as `structuredContent`, and a Bash
command identical to one this agent already had cut in this session (running it again returns the
full output; a repeated Read of an unchanged file is answered by Claude Code itself, so a Read is
paged with offset/limit instead).

Thresholds (characters; env STACK_OUTPUT_SHRINK_BASH / _VIEW / _READ, clamped to 4000..200000), from
the measured distribution (Stage 4 MEASURE.md, csv/h4_tool_sizes.csv, h4_bash_families.csv, 18,000
calls over 5 sessions): Bash 8000 (4.2% of Bash calls exceed it: the 3.2% ceiling); Bash viewing
commands (sed, cat, head, tail, nl, git show/diff/log/blame: output Claude asked for line by line)
20000; Read 20000, unbounded reads only (121 of 2045 reads, the 2.1% "read discipline" ceiling).

Files, under the session's project (CLAUDE_PROJECT_DIR, else the event's cwd; never $HOME, `/` or a
Claude config directory): `.claude-work/output-shrink/` (0700, with a `*` .gitignore) holding
`log.jsonl` (one row per Bash/Read call: sizes, decision, kept line ranges, the exact digest size,
family (Bash: a plain lower-case command name and git/uv subcommand; Read: a plain extension; else
"other"), a hash of the command or path; never output text, commands or paths; 0600; rotated to
log.1.jsonl at 32 MB)
and `spill/` (on mode: one 0600 file per cut, at most 4 MB each; files older than 7 days and the
oldest past 64 MB in total are pruned, only names this hook writes). Every directory is opened with
O_NOFOLLOW|O_DIRECTORY relative to its parent, every file with O_NOFOLLOW (spill files O_EXCL): a
symlink anywhere below the project root disables the hook's writes, and a refused write means no
shrink. The spill copy is scrubbed line by line with bin/stack-tree's credential tables (`_REDACT`,
`_KV`) plus whole PEM private-key blocks; when those tables cannot load nothing is spilled and
nothing is shrunk.

`output_shrink.py report [DIR_OR_LOG ...] [--json]` reads the logs (default: the current project)
and prints the realised cut, error-line retention, re-read and repeat rates and a threshold sweep.
`output_shrink.py --self-test` runs the decision on synthetic events in a temporary project.
"""
import hashlib
import json
import os
import re
import secrets
import shlex
import stat
import sys
import time

MODES = ("off", "shadow", "on")
DEFAULT_MODE = "shadow"
DEFAULTS = {"bash": 8000, "view": 20000, "read": 20000}
ENV_KEYS = {"bash": "STACK_OUTPUT_SHRINK_BASH", "view": "STACK_OUTPUT_SHRINK_VIEW",
            "read": "STACK_OUTPUT_SHRINK_READ"}
THR_MIN, THR_MAX = 4000, 200000
SWEEP_FLOOR = 4000          # digests are computed (and logged) above this size, for the threshold sweep
LINE_MAX = 300              # one kept line, characters
BUDGET = {"err": 1500, "sum": 500, "tail": 800, "head": 500, "struct": 500}   # Bash digest, characters
READ_HEAD = 3000            # Read: contiguous head kept, characters
OUTLINE_MAX = 1500          # Read: line numbers of the hidden part's definitions and headings, characters
LOG_MAX = 32 << 20
SPILL_MAX = 4 << 20
SPILL_DIR_MAX = 64 << 20
SPILL_AGE_S = 7 * 86400
REPEAT_SCAN = 256 << 10     # bytes of the log's tail searched for an earlier cut of the same call
TOK_PER_CHAR = 0.424        # tool-result tokens per character (MEASURE h4_tools.json fit)
DIRNAME = "output-shrink"
SPILL_NAME_RE = re.compile(r"^\d{8}T\d{6}Z-(?:bash|read)-[A-Za-z0-9_-]{1,40}-[0-9a-f]{8}\.txt$")
SPILL_REF_RE = re.compile(r"\.claude-work/output-shrink/spill/([A-Za-z0-9._-]+)")
SPILL_DIR_RE = re.compile(r"output-shrink/spill\b")         # any touch of the spill directory is a re-read
FAM_RE = re.compile(r"^[a-z][a-z0-9_.+-]{0,23}$")           # a logged family: a plain command name only
SUB_RE = re.compile(r"^[a-z][a-z0-9-]{0,23}$")
EXT_RE = re.compile(r"^\.[a-z0-9]{1,10}$")                   # a logged Read family: a plain extension only
GIT_ARG_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"}   # take the next word
VIEW_FAMILIES = {"sed", "cat", "head", "tail", "nl", "bat", "less", "more", "git show", "git diff",
                 "git log", "git blame"}

ERR_RE = re.compile(
    r"(?i)(?:\berr!|\b(?:error|errors|failed|failure|failures|fatal|exception|traceback|panic(?:ked)?|"
    r"abort(?:ed)?|denied|refused|segmentation fault|core dumped|not found|no such file|cannot|can't|"
    r"unable to|undefined reference|timed? ?out)\b|\b[A-Z][a-zA-Z]*(?:Error|Exception)\b|"
    r"^\s*File \".+\", line \d+|^\s*(?:E |FAIL\b|FAILED\b|ERROR\b|!))")
SUM_RE = re.compile(
    r"(?i)(?:^=+ .* =+$|^-+ .* -+$|\b\d+ (?:passed|failed|errors?|skipped|xfailed|xpassed|warnings?|"
    r"tests?|deselected)\b|^ran \d+ tests?|^ok\b|^test result:|\bsummary\b|\btotal\b|\bfiles? changed\b|"
    r"\bexit (?:code|status)\b|\bbuild (?:succeeded|failed|successful)\b|\b\d+ (?:insertions?|deletions?)\b|"
    r"\bfinished\b|\bdone\b)")
STRUCT_RE = re.compile(r"^(?:diff --git |@@ |\+\+\+ |--- |commit [0-9a-f]{7,}|#{1,6} |==> .* <==$)")
OUTLINE_RE = re.compile(
    r"^(?:\s{0,4}(?:(?:pub(?:\([^)]*\))?|export|public|private|protected|static|async|abstract|final)\s+)*"
    r"(?:def|class|fn|func|function|struct|enum|trait|impl|interface|type|module|mod|package|namespace|"
    r"object|record|protocol|extension)\b|#{1,6}\s|\[[^\]\n]+\]\s*$|[A-Za-z_][\w.-]*\s*:\s*$|##? \S)")
PROMPT_FILES = {"SKILL.md", "CLAUDE.md", "AGENTS.md", "CLAUDE.local.md"}

_TABLES = []


# ---------------------------------------------------------------- settings
def mode():
    m = os.environ.get("STACK_OUTPUT_SHRINK", "").strip().lower()
    return m if m in MODES else DEFAULT_MODE


def thresholds():
    out = {}
    for k, d in DEFAULTS.items():
        try:
            v = int(os.environ.get(ENV_KEYS[k], "").strip() or d)
        except ValueError:
            v = d
        out[k] = min(max(v, THR_MIN), THR_MAX)
    return out


def h16(s):
    return hashlib.sha256(s.encode("utf-8", "surrogatepass")).hexdigest()[:16]


# ---------------------------------------------------------------- classification
def family(cmd):
    """A command's family as in the Stage 4 measurement: the first command after `cd x &&` and
    VAR=value prefixes; `git <sub>`, `uv run`. It is logged, so only a plain command name passes
    (FAM_RE, SUB_RE): anything else, a credential in `git -c k=v` or a token as the first word, is
    "other"."""
    for seg in re.split(r"&&|\|\||;|\n", cmd or ""):
        try:
            toks = shlex.split(seg)              # a quoted `git -c k="a b"` value is one word
        except ValueError:
            toks = seg.strip().split()
        while toks and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[0]):
            toks = toks[1:]
        if not toks or toks[0] in ("cd", "set", "export", "pushd", "source", "."):
            continue
        t0 = os.path.basename(toks[0].strip("'\"()"))
        if not FAM_RE.match(t0):
            return "other"
        if t0 == "git":
            i = 1
            while i < len(toks) and toks[i].startswith("-"):   # git -C <dir> -c <k=v> --no-pager <sub>
                i += 2 if toks[i] in GIT_ARG_OPTS else 1
            return "git " + toks[i] if i < len(toks) and SUB_RE.match(toks[i]) else "git"
        if t0 == "uv" and len(toks) > 1:
            return "uv " + toks[1] if SUB_RE.match(toks[1]) else "uv"
        return t0
    return "other"


def read_family(path):
    """A Read's logged family: a short plain extension (EXT_RE), "none" without one, else "other"
    (an extension is part of the path, so nothing else of it is logged)."""
    ext = os.path.splitext(path)[1].lower()
    return ext if EXT_RE.match(ext) else ("other" if ext else "none")


def prompt_file(path):
    base = os.path.basename(path)
    if base in PROMPT_FILES:
        return True
    parts = path.replace("\\", "/").split("/")
    return base.endswith(".md") and bool({"skills", "rules", "agents"} & set(parts))


def bash_text(resp):
    out, err = resp.get("stdout") or "", resp.get("stderr") or ""
    if not isinstance(out, str) or not isinstance(err, str):
        return None
    return out + ("\n" if out and err else "") + err


# ---------------------------------------------------------------- digests
def cut_line(s):
    return s if len(s) <= LINE_MAX else s[:LINE_MAX] + "… [+%d chars]" % (len(s) - LINE_MAX)


def select(lines):
    """Kept line indices and per-class counts for a Bash digest: error lines (the last ones first,
    then the first ones), summaries (from the end), the tail, the head, structure lines."""
    kept, counts = set(), {}
    n = len(lines)
    err = [i for i, s in enumerate(lines) if ERR_RE.search(s)]

    def take(order, cls):
        room = BUDGET[cls]
        for i in order:
            if i in kept:
                continue
            cost = len(cut_line(lines[i])) + 1
            if cost > room:
                if cls in ("tail", "head"):
                    break               # contiguous classes stop at the first line that does not fit
                continue
            kept.add(i)
            room -= cost
            counts[cls] = counts.get(cls, 0) + 1

    half = len(err) // 2
    take(list(reversed(err[half:])) + err[:half], "err")
    take([i for i in range(n - 1, -1, -1) if SUM_RE.search(lines[i])], "sum")
    take(range(n - 1, -1, -1), "tail")
    take(range(n), "head")
    take([i for i in range(n) if STRUCT_RE.search(lines[i])], "struct")
    counts["err_total"] = len(err)
    counts["err_kept"] = sum(1 for i in err if i in kept)
    return sorted(kept), counts


def render(lines, kept, header):
    out, prev = [header], -1
    for i in kept:
        if i > prev + 1:
            out.append("… [lines %d-%d omitted] …" % (prev + 2, i))
        out.append(cut_line(lines[i]))
        prev = i
    if prev < len(lines) - 1:
        out.append("… [lines %d-%d omitted] …" % (prev + 2, len(lines)))
    return "\n".join(out)


def ranges(idx, cap=30):
    out = []
    for i in idx:
        if out and out[-1][1] == i - 1:
            out[-1][1] = i
        else:
            out.append([i, i])
    return out[:cap]


def read_head(content):
    """(head text, number of lines, first line cut) for a Read result: whole lines up to READ_HEAD."""
    lines = content.split("\n")
    used, k = 0, 0
    for s in lines:
        if used + len(s) + 1 > READ_HEAD:
            break
        used += len(s) + 1
        k += 1
    if k == 0:
        return lines[0][:READ_HEAD] + "… [line cut]", 1, True
    return "\n".join(lines[:k]), k, False


def outline(lines, start_idx, first_no):
    """Line numbers ("L<n>") of the definitions and headings from start_idx on. Numbers only: the
    note goes to additionalContext, which reaches the model as system text, so no file text."""
    out, used = [], 0
    for i in range(start_idx, len(lines)):
        if OUTLINE_RE.search(lines[i]):
            row = "L%d" % (first_no + i)
            if used + len(row) + 2 > OUTLINE_MAX:
                out.append("…")
                break
            out.append(row)
            used += len(row) + 2
    return out


# ---------------------------------------------------------------- credential scrub (spill copy)
def tables():
    """bin/stack-tree's (redact_kv, _REDACT): one source of the credential patterns. Loaded without
    writing bytecode into bin/."""
    if not _TABLES:
        import importlib.machinery
        import importlib.util
        path = os.path.join(os.path.dirname(os.path.realpath(__file__)), os.pardir, "bin", "stack-tree")
        loader = importlib.machinery.SourceFileLoader("stack_tree_for_shrink", path)
        mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        old, sys.dont_write_bytecode = sys.dont_write_bytecode, True
        try:
            loader.exec_module(mod)
        finally:
            sys.dont_write_bytecode = old
        if not (callable(getattr(mod, "redact_kv", None)) and isinstance(getattr(mod, "_REDACT", None), list)
                and mod._REDACT):
            raise RuntimeError("stack-tree credential tables missing")
        _TABLES[:] = [mod.redact_kv, mod._REDACT]
    return _TABLES


PEM_BEGIN = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY( BLOCK)?-----")
PEM_END = re.compile(r"-----END [A-Z0-9 ]*PRIVATE KEY( BLOCK)?-----")


def scrub(text):
    """The text with credentials masked line by line (the line count never changes, so the omitted
    ranges in the digest still point at the same lines), PEM private-key blocks fully."""
    redact_kv, rx = tables()
    out, in_pem = [], False
    for s in text.split("\n"):
        if in_pem:
            out.append("***")
            in_pem = not PEM_END.search(s)
            continue
        if PEM_BEGIN.search(s):
            out.append("***")
            in_pem = not PEM_END.search(s)
            continue
        s = redact_kv(s)
        for r, rep in rx:
            s = r.sub(rep, s)
        out.append(s)
    return "\n".join(out)


# ---------------------------------------------------------------- safe files
def config_dirs():
    here = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))     # <config>/hooks/.. = <config>
    dirs = {here, os.path.realpath(os.path.expanduser("~/.claude"))}
    if os.environ.get("CLAUDE_CONFIG_DIR"):
        dirs.add(os.path.realpath(os.path.expanduser(os.environ["CLAUDE_CONFIG_DIR"])))
    return dirs


def inside(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")


def project_root(ev):
    p = os.environ.get("CLAUDE_PROJECT_DIR") or (ev.get("cwd") if isinstance(ev.get("cwd"), str) else "")
    if not p or not os.path.isabs(p):
        return None
    p = os.path.realpath(p)
    if p in ("/", os.path.realpath(os.path.expanduser("~"))) or not os.path.isdir(p):
        return None
    if any(inside(p, c) for c in config_dirs()):
        return None
    return p


def open_dir(parent_fd, name, create=True, private=True):
    """A directory fd for `name` under parent_fd: created 0700 when missing, never a symlink, ours;
    `private`: group and other bits an existing one has are removed (the shared .claude-work keeps its)."""
    if create:
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
    st = os.fstat(fd)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        os.close(fd)
        raise OSError("not our directory: %s" % name)
    if private and st.st_mode & 0o077:
        try:
            os.fchmod(fd, stat.S_IMODE(st.st_mode) & 0o700)
        except OSError:
            os.close(fd)
            raise
    return fd


def work_dir(root):
    """fd of <root>/.claude-work/output-shrink (with its `*` .gitignore)."""
    rfd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        cfd = open_dir(rfd, ".claude-work", private=False)
    finally:
        os.close(rfd)
    try:
        wfd = open_dir(cfd, DIRNAME)
    finally:
        os.close(cfd)
    try:
        fd = os.open(".gitignore", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=wfd)
        try:
            os.write(fd, b"*\n")
        finally:
            os.close(fd)
    except FileExistsError:
        pass
    return wfd


def open_file(dfd, name, flags):
    fd = os.open(name, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=dfd)
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
        os.close(fd)
        raise OSError("not our file: %s" % name)
    if stat.S_IMODE(st.st_mode) != 0o600:
        os.fchmod(fd, 0o600)
    return fd, st


def append_row(wfd, row):
    line = (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
    try:
        st = os.stat("log.jsonl", dir_fd=wfd, follow_symlinks=False)
        if stat.S_ISREG(st.st_mode) and st.st_size + len(line) > LOG_MAX:
            os.replace("log.jsonl", "log.1.jsonl", src_dir_fd=wfd, dst_dir_fd=wfd)
    except FileNotFoundError:
        pass
    fd, _ = open_file(wfd, "log.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def earlier_cut(wfd, sid, aid, tool, key):
    """True when the log's tail holds a cut of this call (same session, agent, tool, key)."""
    try:
        fd, st = open_file(wfd, "log.jsonl", os.O_RDONLY)
    except OSError:
        return False
    try:
        os.lseek(fd, max(0, st.st_size - REPEAT_SCAN), 0)
        data = os.read(fd, REPEAT_SCAN)
    finally:
        os.close(fd)
    for raw in reversed(data.split(b"\n")):
        if key.encode() not in raw:
            continue
        try:
            r = json.loads(raw)
        except ValueError:
            continue
        if r.get("cut") and r.get("key") == key and r.get("sid") == sid and r.get("aid") == aid \
                and r.get("tool") == tool:
            return True
    return False


def prune(sfd, now):
    items = []
    for name in os.listdir(sfd):
        if not SPILL_NAME_RE.match(name):
            continue
        try:
            st = os.stat(name, dir_fd=sfd, follow_symlinks=False)
        except OSError:
            continue
        if stat.S_ISREG(st.st_mode) and st.st_uid == os.getuid():
            items.append((st.st_mtime, st.st_size, name))
    items.sort()
    total = sum(x[1] for x in items)
    for mtime, size, name in items:
        if now - mtime <= SPILL_AGE_S and total <= SPILL_DIR_MAX * 3 // 4:
            break
        try:
            os.unlink(name, dir_fd=sfd)
            total -= size
        except OSError:
            pass
    return total


def spill_name(tool, tuid, now):
    """A spill file name (SPILL_NAME_RE): time, tool, the tool_use_id's safe characters, 32 random bits."""
    return "%s-%s-%s-%s.txt" % (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now)), tool.lower(),
                                re.sub(r"[^A-Za-z0-9_-]", "", tuid or "")[-40:] or "call", secrets.token_hex(4))


def spill(wfd, name, text, now):
    """Write the scrubbed full output to spill/<name>. Raises on any refusal."""
    data = scrub(text).encode("utf-8", "replace")
    if len(data) > SPILL_MAX:
        data = data[:SPILL_MAX] + b"\n... [output-shrink: spill cut at 4 MB]\n"
    sfd = open_dir(wfd, "spill")
    try:
        if prune(sfd, now) + len(data) > SPILL_DIR_MAX:
            raise OSError("spill directory full")
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=sfd)
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
        finally:
            os.close(fd)
    finally:
        os.close(sfd)


def bash_header(text, lines, kept, path):
    return ("[output-shrink: %s chars in %s lines; shown: the %d decisive lines (errors, summaries, tail, "
            "head). Full output, credentials masked: %s (Read it with offset/limit, or grep it); the same "
            "command again returns it unshrunk.]" % (format(len(text), ","), format(len(lines), ","),
                                                      len(kept), path))


def read_note(lines, text, first, k, first_cut, ol):
    last = first + k - 1
    # a repeat of the same Read is answered by Claude Code's own dedup ("file unchanged"), so the way
    # to the whole result is a ranged Read (never shrunk), not the same call again
    note = ("output-shrink: this Read returned %d lines (%d chars); only lines %d-%d are shown%s. The file "
            "holds the rest: Read it again with offset=%d and a limit, or with offset=%d and limit=%d for the "
            "whole result, or grep it." % (len(lines), len(text), first, last,
                                           " (line %d cut)" % first if first_cut else "", last + 1, first,
                                           len(lines)))
    if ol:
        note += " Definitions and headings in the hidden lines start at: " + ", ".join(ol)
    return note


# ---------------------------------------------------------------- the decision
def decide(ev, md, thr, wfd, root, now):
    """(hook output or None, log row or None)."""
    tool = ev.get("tool_name")
    inp = ev.get("tool_input") if isinstance(ev.get("tool_input"), dict) else {}
    resp = ev.get("tool_response")
    sid, aid = str(ev.get("session_id") or "")[:80], str(ev.get("agent_id") or "")[:80]
    row = {"v": 1, "ts": round(now, 3), "sid": sid, "aid": aid, "atype": str(ev.get("agent_type") or "")[:60],
           "tool": tool, "mode": md, "cut": False}
    if tool == "Bash":
        cmd = inp.get("command") if isinstance(inp.get("command"), str) else ""
        row["fam"] = family(cmd)
        row["key"] = h16(cmd)
        text = bash_text(resp) if isinstance(resp, dict) else None
        if text is None:
            row["skip"] = "shape"
            return None, row
        if SPILL_DIR_RE.search(cmd):
            row["skip"], row["refs"] = "reread", SPILL_REF_RE.findall(cmd)[:5]
        elif resp.get("persistedOutputPath") or resp.get("structuredContent"):
            row["skip"] = "persisted"    # Claude Code shows its own preview and keeps the full copy
        elif resp.get("isImage") or resp.get("interrupted") or resp.get("backgroundTaskId"):
            row["skip"] = "special"
        cls = "view" if row["fam"] in VIEW_FAMILIES else "bash"
    elif tool == "Read":
        path = inp.get("file_path") if isinstance(inp.get("file_path"), str) else ""
        row["key"] = h16(path)
        row["fam"] = read_family(path)
        f = resp.get("file") if isinstance(resp, dict) else None
        if not (isinstance(resp, dict) and resp.get("type") == "text" and isinstance(f, dict)
                and isinstance(f.get("content"), str)):
            row["skip"] = "shape"
            return None, row
        text = f["content"]
        if SPILL_DIR_RE.search(path):
            row["skip"], row["refs"] = "reread", SPILL_REF_RE.findall(path)[:5]
        elif inp.get("offset") is not None or inp.get("limit") is not None:
            row["skip"] = "ranged"
        elif prompt_file(path):
            row["skip"] = "prompt-file"
        cls = "read"
    else:
        return None, None
    lines = text.split("\n")
    row.update(cls=cls, chars=len(text), lines=len(lines), thr=thr[cls])
    if "skip" in row or len(text) <= SWEEP_FLOOR:
        return None, row
    # the digest, for the decision and for the threshold sweep (logged at every size above the floor);
    # kept_chars is the exact size Claude would get (shadow builds the same text as on mode)
    if cls == "read":
        first = int(f.get("startLine") or 1)
        head, k, first_cut = read_head(text)
        ol = outline(lines, k, first)
        note = read_note(lines, text, first, k, first_cut, ol)
        row.update(kept=[[0, k - 1]], kept_lines=k, kept_chars=len(head) + len(note), outline=len(ol))
    else:
        kept, counts = select(lines)
        name = spill_name(tool, str(ev.get("tool_use_id") or ""), now)
        digest = render(lines, kept, bash_header(text, lines, kept,
                                                 os.path.join(root, ".claude-work", DIRNAME, "spill", name)))
        row.update(kept=ranges(kept), kept_lines=len(kept), kept_chars=len(digest),
                   err_total=counts["err_total"], err_kept=counts["err_kept"])
    if len(text) <= thr[cls]:
        return None, row
    if wfd is not None and earlier_cut(wfd, sid, aid, tool, row["key"]):
        row["skip"] = "repeat"
        return None, row
    row["cut"] = True
    if md != "on":
        return None, row
    if cls == "read":
        new = dict(resp, file=dict(f, content=head, numLines=k))
        return ({"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": new,
                                        "additionalContext": note}}, row)
    try:
        spill(wfd, name, text, now)
    except Exception as exc:  # noqa: BLE001 - no spill, no shrink: the full output must stay reachable
        row["cut"], row["skip"] = False, "spill-failed:%s" % type(exc).__name__
        return None, row
    row["spill"] = name
    new = dict(resp, stdout=digest, stderr="")
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": new}}, row


def handle(ev, now=None):
    """The hook's JSON output for one event, or None (output unchanged)."""
    md = mode()
    if md == "off" or not isinstance(ev, dict) or ev.get("hook_event_name") != "PostToolUse" \
            or ev.get("tool_name") not in ("Bash", "Read"):
        return None
    now = time.time() if now is None else now
    root = project_root(ev)
    if root is None:
        return None
    try:
        wfd = work_dir(root)
    except OSError:
        return None                       # no log, no spill: never shrink blind
    try:
        out, row = decide(ev, md, thresholds(), wfd, root, now)
        if row is not None:
            try:
                append_row(wfd, row)
            except OSError:
                pass
        return out if md == "on" else None
    finally:
        os.close(wfd)


# ---------------------------------------------------------------- report
def load_rows(targets):
    rows = []
    for t in targets:
        files = [t] if os.path.isfile(t) else [os.path.join(t, ".claude-work", DIRNAME, n)
                                                for n in ("log.1.jsonl", "log.jsonl")]
        for p in files:
            if not os.path.isfile(p):
                continue
            with open(p, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(r, dict) and r.get("v") == 1:
                        rows.append(r)
    rows.sort(key=lambda r: r.get("ts", 0))
    return rows


def report(rows, window=20):
    """Realised cut, error retention, re-read and repeat rates, threshold sweep."""
    out = {"rows": len(rows), "sessions": len({r.get("sid") for r in rows}),
           "modes": {}, "by_class": {}, "sweep": {}}
    for r in rows:
        out["modes"][r.get("mode")] = out["modes"].get(r.get("mode"), 0) + 1
    total_chars = sum(r.get("chars", 0) for r in rows)
    by_agent = {}
    for i, r in enumerate(rows):
        by_agent.setdefault((r.get("sid"), r.get("aid")), []).append(i)
    follow = {}                           # row index -> later rows of the same agent (window)
    for idx in by_agent.values():
        for j, i in enumerate(idx):
            follow[i] = idx[j + 1:j + 1 + window]
    cut_chars = 0
    reread_chars = 0
    n_cut = n_reread = n_repeat = 0
    err_total = err_kept = 0
    for i, r in enumerate(rows):
        c = out["by_class"].setdefault(r.get("cls", "?"), {"calls": 0, "chars": 0, "over": 0, "cut": 0,
                                                           "cut_chars": 0})
        c["calls"] += 1
        c["chars"] += r.get("chars", 0)
        if r.get("chars", 0) > r.get("thr", 1 << 60):
            c["over"] += 1
        if not r.get("cut"):
            continue
        saved = max(0, r.get("chars", 0) - r.get("kept_chars", 0))
        c["cut"] += 1
        c["cut_chars"] += saved
        cut_chars += saved
        n_cut += 1
        err_total += r.get("err_total", 0)
        err_kept += r.get("err_kept", 0)
        later = [rows[k] for k in follow.get(i, [])]
        rr = [x for x in later if r.get("spill") and r["spill"] in (x.get("refs") or [])]
        rp = [x for x in later if x.get("key") == r.get("key") and x.get("tool") == r.get("tool")]
        if rr:
            n_reread += 1
            reread_chars += sum(x.get("chars", 0) for x in rr)
        if rp:
            n_repeat += 1
            reread_chars += sum(x.get("chars", 0) for x in rp)
    # baseline: how often a large call that was NOT cut is repeated anyway
    big = [i for i, r in enumerate(rows) if not r.get("cut") and r.get("chars", 0) > SWEEP_FLOOR
           and "skip" not in r]
    base_rep = sum(1 for i in big if any(rows[k].get("key") == rows[i].get("key")
                                         and rows[k].get("tool") == rows[i].get("tool") for k in follow.get(i, [])))
    for t in (4000, 8000, 12000, 20000, 30000):
        s = sum(max(0, r.get("chars", 0) - r.get("kept_chars", 0)) for r in rows
                if "kept_chars" in r and r.get("chars", 0) > t and r.get("skip") in (None, "repeat"))
        out["sweep"][str(t)] = {"cut_chars": s, "share_of_logged_chars": round(s / total_chars, 4) if total_chars else 0}
    out.update(
        logged_chars=total_chars, cut_events=n_cut, cut_chars=cut_chars,
        cut_tokens_est=round(cut_chars * TOK_PER_CHAR),
        realised_cut_share=round(cut_chars / total_chars, 4) if total_chars else 0,
        net_cut_chars=cut_chars - reread_chars,
        reread_rate=round(n_reread / n_cut, 4) if n_cut else None,
        repeat_rate_after_cut=round(n_repeat / n_cut, 4) if n_cut else None,
        repeat_rate_baseline=round(base_rep / len(big), 4) if big else None,
        error_lines_kept=round(err_kept / err_total, 4) if err_total else None,
        window=window)
    return out


def print_report(rep):
    w = sys.stdout.write
    w("output-shrink log: %d rows, %d sessions, modes %s\n" % (rep["rows"], rep["sessions"], rep["modes"]))
    w("logged output %s chars; cut events %d; cut %s chars (~%s tokens) = %.1f%% of logged chars; "
      "net of re-reads %s chars\n" % (format(rep["logged_chars"], ","), rep["cut_events"],
                                      format(rep["cut_chars"], ","), format(rep["cut_tokens_est"], ","),
                                      100 * rep["realised_cut_share"], format(rep["net_cut_chars"], ",")))
    w("re-read rate (spill read later, on mode) %s; repeat rate after a cut %s vs baseline %s (next %d calls "
      "of the same agent); error lines kept %s\n" % (rep["reread_rate"], rep["repeat_rate_after_cut"],
                                                     rep["repeat_rate_baseline"], rep["window"],
                                                     rep["error_lines_kept"]))
    w("%-6s %8s %12s %7s %6s %12s\n" % ("class", "calls", "chars", "over", "cut", "cut_chars"))
    for k, c in sorted(rep["by_class"].items()):
        w("%-6s %8d %12d %7d %6d %12d\n" % (k, c["calls"], c["chars"], c["over"], c["cut"], c["cut_chars"]))
    w("threshold sweep (all classes at one threshold, same digests):\n")
    for t, s in rep["sweep"].items():
        w("  %6s chars: cut %12d = %.1f%%\n" % (t, s["cut_chars"], 100 * s["share_of_logged_chars"]))


# ---------------------------------------------------------------- self-test
def self_test():
    import tempfile
    old = dict(os.environ)
    try:
        with tempfile.TemporaryDirectory() as d:
            os.environ["CLAUDE_PROJECT_DIR"] = d
            fake = "ghp" + "_" + "Q7w" * 12
            body = "\n".join(["line %d ok" % i for i in range(2000)] + ["Error: boom " + fake, "1 failed, 9 passed"])
            ev = {"hook_event_name": "PostToolUse", "tool_name": "Bash", "session_id": "s", "tool_use_id": "t1",
                  "tool_input": {"command": "make test"}, "cwd": d,
                  "tool_response": {"stdout": body, "stderr": "", "interrupted": False, "isImage": False}}
            os.environ["STACK_OUTPUT_SHRINK"] = "shadow"
            assert handle(ev) is None
            os.environ["STACK_OUTPUT_SHRINK"] = "on"
            ev["session_id"] = "s2"
            out = handle(ev)
            s = out["hookSpecificOutput"]["updatedToolOutput"]["stdout"]
            assert "Error: boom" in s and "1 failed" in s and len(s) < 5000, s[:200]
            spills = os.listdir(os.path.join(d, ".claude-work", DIRNAME, "spill"))
            with open(os.path.join(d, ".claude-work", DIRNAME, "spill", spills[0]), encoding="utf-8") as fh:
                data = fh.read()
            assert fake not in data and "line 1999 ok" in data
            assert handle(ev) is None                     # the same call again: unshrunk
    finally:
        os.environ.clear()
        os.environ.update(old)
    sys.stdout.write("output_shrink self-test: ok\n")
    return 0


def main(argv):
    if argv[:1] == ["--self-test"]:
        return self_test()
    if argv[:1] == ["report"]:
        args = [a for a in argv[1:] if not a.startswith("--")]
        rep = report(load_rows(args or [os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()]))
        if "--json" in argv:
            sys.stdout.write(json.dumps(rep, indent=1, sort_keys=True) + "\n")
        else:
            print_report(rep)
        return 0
    try:
        ev = json.loads(sys.stdin.read() or "null")
        out = handle(ev)
    except Exception as exc:  # noqa: BLE001 - fail open: the output stays as it was
        sys.stderr.write("output_shrink: %s: %s\n" % (type(exc).__name__, str(exc)[:200]))
        return 0
    if out is not None:
        sys.stdout.write(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
