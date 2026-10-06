"""The compact hand-back protocol between an agent and its subagents (stdlib only, Python 3.8+, POSIX).

Imported by agent_guard.py: its SubagentStop handler validates a stack subagent's final reply, its
PreToolUse(Agent) handler measures the brief (STACK_REPORT_FORMAT, see agent_guard.py and CONFIG.md
"Message protocol"). Everything here is pure text work except file_meta (stat and hash of the paths a
report names, under the safety rules below) and transcript_last_tool / transcript_handback (a bounded
tail read; the latter returns the SubagentHandback message that is the report of such a run, S4 L7 B1).

The model-written report (rules "Briefs and hand-backs"; the STATUS prefix and keys every existing parser
reads):

  STATUS: done|partial|failed|blocked [· E:look|E:drop]
  RESULT: <answer, numbers, decisions; never file contents>
  FILES:
  - <path> — <purpose, or `deleted`>
  EVIDENCE: <command + <= 5 lines of output, or → path[:a-b]>
  NEXT: <agent: step | ASK USER: question (options)>

check() sorts what is wrong into hard violations (the only ones STACK_REPORT_FORMAT=compact restates,
once) and soft ones (logged only):
  hard: no or invalid STATUS; a non-done report without EVIDENCE or NEXT; a blob (blob_score) and a size
        above OVERRUN x the class cap, both only for the classes whose caps are hard
  soft: everything else (a size above the cap but within OVERRUN, blobs and sizes of the review and plan
        classes, an implied E flag, a done report that says "skipped"/"unverified"/"not run" with no E flag,
        missing files: file_meta runs after the decision and never decides a block)
The caps are provisional (plan S5b calibrates them from observe-mode data); FILES lines do not count.

file_meta safety (the review of the plan): a path is resolved (realpath) and looked at only when it lies
inside the event cwd, $CLAUDE_PROJECT_DIR or the main checkout's .claude-work/ (a root that is / or the
home folder or one of its ancestors does not count, and credential paths never do), else it is recorded as
`outside` with no stat; open(O_RDONLY|O_NONBLOCK|O_NOFOLLOW|O_NOCTTY), the descriptor's own path checked
again (F_GETPATH, /proc/self/fd), then fstat S_ISREG (no lstat-then-open); hashing (files up to HASH_MAX,
not iCloud-dataless) runs in a daemon thread joined for at most META_BUDGET_S seconds; at most FILES_MAX
paths.
"""
import errno
import hashlib
import json
import math
import os
import re
import stat
import threading
import time

STATUSES = ("done", "partial", "failed", "blocked")
EFLAGS = ("look", "drop")
# role class of each agent type; every other type is a builder
CLASS_OF = {
    "oracle": "lookup", "scout": "lookup", "explore": "lookup", "claude-code-guide": "lookup",
    "orchestrator": "coord",
    "code-reviewer": "review", "plan-reviewer": "review", "security-auditor": "review",
    "verifier": "review", "proof-checker": "review",
    "planner": "plan",
}
# chars the model writes (FILES lines excluded), by class and status; hard: a size above OVERRUN x cap and a
# blob are hard violations, soft classes only log them. PROVISIONAL (plan.md table, enforced only in
# STACK_REPORT_FORMAT=compact, which is not the default): on the 80 frozen pre-protocol hand-backs (builder 65,
# lookup 8, review 6, plan 1, coord 0) 70/80 would be restated at 1.0x and 60/80 at 1.5x; the p90 of the
# rewritten compliant builder reports is 3,100 chars done (n=29) and 3,200 otherwise (n=19)
# (claude_next_steps/work_carried/compact-protocol/measurement/COUNTERFACTUAL.md, 2026-10-03). Plan step S5b
# sets the caps from that and the observe-mode usage/reports.jsonl before compact becomes the default.
CAPS = {
    "lookup": {"done": 1000, "other": 1000, "hard": True},
    "builder": {"done": 800, "other": 2500, "hard": True},
    "coord": {"done": 2500, "other": 2500, "hard": True},
    "review": {"done": 6000, "other": 6000, "hard": False},
    "plan": {"done": 12000, "other": 12000, "hard": False},
}
OVERRUN = 1.5
BRIEF_CAP = 2000              # agent-written brief chars (a `USER:` block is exempt); soft, a warning
TEXT_MAX = 2 << 20            # chars of a report analysed (the rest is counted, not scanned)
FILES_MAX = 20                # paths file_meta looks at
HASH_MAX = 8 << 20            # bytes hashed per file (larger: size and mtime only)
META_BUDGET_S = 2.0           # seconds the hash thread is waited for, all files together
TAIL_MAX = 256 << 10          # bytes of a transcript tail transcript_last_tool reads
REASON_MAX = 400
SF_DATALESS = 0x40000000      # macOS st_flags: an iCloud placeholder (a read would download it)

KEY_RE = re.compile(r"^[ \t>*_`]*(STATUS|RESULT|FILES|EVIDENCE|NEXT)[*_`]*[ \t]*:[ \t]*[*_`]*[ \t]*(.*)$")
WORD_RE = re.compile(r"(done|partial|failed|blocked)\b", re.I)
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z_-]{0,19}")
EFLAG_RE = re.compile(r"\bE[ \t]*:[ \t]*(look|drop)\b", re.I)
FENCE_RE = re.compile(r"^[ \t]*(```|~~~)")
CLEAN_MAX = 400               # chars of a first line that can be the clean-finish line
CLEAN_RE = re.compile(r"[*`_ ]*.+? · \d{4}-\d{2}-\d{2}(?: \d{2}:\d{2})? · [A-Za-z0-9_-]+[*`_ ]*\Z")
PURPOSE_SEP = re.compile(r"(?<!\s)\s+(?:—|–|--?)\s+")   # (?<!\s): linear on long blank runs
BULLET_RE = re.compile(r"^(?:[-*+•]|\d{1,3}[.)])\s+")
RANGE_RE = re.compile(r":\d+(?:-\d+)?\Z")
NONE_WORDS = ("", "-", "—", "none", "(none)", "n/a", "nothing")
NONE_RE = re.compile(r"^\(?(none|nothing|no files)(\)|\s|\Z)", re.I)
PAREN_RE = re.compile(r"^(\S.*?)(?<!\s)\s+\(([^()]*)\)\Z")
DELETED_RE = re.compile(r"^\(?deleted\b", re.I)
VERDICT_RE = re.compile(r"\bVERDICT\b[*_`:\s]*(pass-with-fixes|pass|fail)\b", re.I)
COUNT_RE = re.compile(r"\b(\d{1,4})\s+(CRITICAL|HIGH|MEDIUM|LOW|BLOCKING)\b")
SUSPECT_RE = re.compile(r"\b(skipped|unverified|not run|not verified|not tested)\b", re.I)
READ_LINE_RE = re.compile(r"^\s*\d+\t")
B64_RE = re.compile(r"[A-Za-z0-9+/]{200,}")
CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
PASTED_RE = re.compile(r"(?m)^[ \t>*_`]*STATUS[*_`]*[ \t]*:[ \t]*[*_`]*[ \t]*(done|partial|failed|blocked)\b"
                       r"|<usage>|\bagentId:\s*[A-Za-z0-9_-]{6,}")
USER_RE = re.compile(r"(?m)^[ \t]*USER:")
# matched case-insensitively (APFS is case-insensitive by default): parts and path substrings, lower case
CREDENTIAL_PARTS = frozenset((".ssh", ".aws", ".gnupg", ".kube", ".docker", ".netrc", ".git-credentials",
                              ".pypirc", ".npmrc", "keychains", ".credentials.json", ".claude.json",
                              "stack.env", "claude-agent-stack-backups"))
CREDENTIAL_SUBSTR = ("/.config/gh/", "/.config/gcloud/", "/.config/git/credentials", "/.cache/huggingface/token",
                     "/.claude/ide/", "/.claude/backup-")
ENV_FILE_RE = re.compile(r"^\.env(\..*)?\Z", re.I)

GRAMMAR = ("STATUS: done|partial|failed|blocked [· E:look|E:drop]\nRESULT: answer, no file contents\n"
           "FILES:\n- path — purpose\nEVIDENCE: command + <= 5 lines, or → path\n"
           "NEXT: agent: step | ASK USER: question (options)")


def role_class(agent_type):
    return CLASS_OF.get(str(agent_type or ""), "builder")


def cap_for(cls, status):
    row = CAPS.get(cls) or CAPS["builder"]
    return row["done"] if status == "done" else row["other"]


def est_tokens(chars):
    """ceil(chars / 3): an estimate (tests/prompt_budget.py uses the same ratio), never a token count."""
    return int(math.ceil(chars / 3.0)) if isinstance(chars, int) and chars > 0 else 0


def unwrap(text):
    """A reply the model wrapped in one code fence (the first non-empty line opens a ``` or ~~~ fence and a
    STATUS line is inside it): the same text without that fence's two marker lines, so the fence is neither a
    blob nor a fenced report (8 of the 80 frozen hand-backs were wrapped so: markup, not content). Any other
    text comes back unchanged."""
    if not isinstance(text, str):
        return ""
    lines = text.split("\n")
    first = next((i for i, ln in enumerate(lines) if ln.strip()), None)
    if first is None:
        return text
    m = FENCE_RE.match(lines[first])
    if not m:
        return text
    close = next((j for j in range(first + 1, len(lines)) if re.match(r"^[ \t]*%s[ \t]*$" % re.escape(m.group(1)),
                                                                       lines[j])), len(lines))
    inner = lines[first + 1:close]
    if not any(KEY_RE.match(ln) and KEY_RE.match(ln).group(1) == "STATUS" for ln in inner):
        return text
    return "\n".join(lines[:first] + inner + lines[close + 1:])


def _fence_flags(lines):
    """Per line: inside a ``` or ~~~ fence (fence marker lines count as inside)."""
    flags, open_ = [], None
    for ln in lines:
        m = FENCE_RE.match(ln)
        if m and (open_ is None or m.group(1) == open_):
            flags.append(True)
            open_ = None if open_ else m.group(1)
            continue
        flags.append(open_ is not None)
    return flags


def _files(block):
    """FILES block -> [{path, purpose, deleted}]: one `path — purpose` per line (a `- ` bullet is fine), or
    the older comma-separated list on one line."""
    out = []
    for ln in block.splitlines():
        ln = BULLET_RE.sub("", ln.strip())
        if not ln:
            continue
        m = PURPOSE_SEP.search(ln)
        items = [(ln[:m.start()], ln[m.end():])] if m else [(p, "") for p in ln.split(",")]
        for p, purpose in items:
            p = p.strip()
            par = PAREN_RE.match(p)
            if par:
                p, purpose = par.group(1), purpose or par.group(2)
            p = RANGE_RE.sub("", p.strip("`'\"").strip())
            purpose = purpose.strip()
            if p.lower() in NONE_WORDS or NONE_RE.match(p):
                continue
            out.append({"path": p[:1024], "purpose": purpose[:200], "deleted": bool(DELETED_RE.match(purpose))})
    return out


def parse(text):
    """A final reply -> {format, status, status_raw, eflag, result, files, evidence, evidence_ref, next,
    verdict, counts, header, wrapped, chars, files_chars}. format: status (a STATUS line), clean (the old
    clean-finish line, no STATUS), text (neither) or empty. A whole-reply fence is removed first (unwrap). The
    first STATUS line outside a code fence counts (else the first inside one); the fields run from it to the
    end. chars counts the reply as sent (fence included)."""
    text = text if isinstance(text, str) else ""
    r = {"format": "empty", "status": None, "status_raw": None, "eflag": None, "result": None, "files": [],
         "evidence": None, "evidence_ref": None, "next": None, "verdict": None, "counts": {}, "header": False,
         "wrapped": False, "chars": len(text), "files_chars": 0}
    body = unwrap(text[:TEXT_MAX])
    r["wrapped"] = body != text[:TEXT_MAX]
    if not body.strip():
        return r
    lines = body.split("\n")
    first = next((ln for ln in lines if ln.strip()), "")
    r["header"] = len(first) <= CLEAN_MAX and bool(CLEAN_RE.match(first.strip()))
    fenced = _fence_flags(lines)
    keys = [KEY_RE.match(ln) for ln in lines]
    idx = [i for i, m in enumerate(keys) if m and m.group(1) == "STATUS"]
    start = next((i for i in idx if not fenced[i]), idx[0] if idx else None)
    if start is None:
        r["format"] = "clean" if r["header"] else "text"
        v = VERDICT_RE.search(body)
        r["verdict"] = v.group(1).lower() if v else None
        return r
    r["format"] = "status"
    got, key, files_chars = {}, None, 0
    for i in range(start, len(lines)):
        ln, m = lines[i], keys[i]
        if m and (fenced[start] or not fenced[i]) and not (i > start and m.group(1) == "STATUS"):
            key = m.group(1)
            got.setdefault(key, [])
            if m.group(2).strip():
                got[key].append(m.group(2).rstrip())
        elif key and not FENCE_RE.match(ln):
            got[key].append(ln.rstrip())
        if key == "FILES":
            files_chars += len(ln) + 1
    rest = (got.get("STATUS") or [""])[0]
    w = WORD_RE.match(rest.strip())
    if w:
        r["status"] = w.group(1).lower()
    else:
        tok = TOKEN_RE.match(rest.strip().strip("*`_|[ "))
        r["status_raw"] = tok.group(0).lower() if tok else ""
    e = EFLAG_RE.search(rest)
    r["eflag"] = e.group(1).lower() if e else None

    def field(k):
        s = "\n".join(got.get(k) or []).strip()
        return s or None

    r["result"], r["evidence"], r["next"] = field("RESULT"), field("EVIDENCE"), field("NEXT")
    r["files"] = _files("\n".join(got.get("FILES") or []))
    r["files_chars"] = files_chars
    ev = r["evidence"] or ""
    if ev.startswith(("→", "->")):
        ref = ev.lstrip("→->").strip().split()[0] if ev.lstrip("→->").strip() else ""
        r["evidence_ref"] = RANGE_RE.sub("", ref.strip("`'\""))[:1024] or None
    src = r["result"] or body
    v = VERDICT_RE.search(src)
    if v:
        r["verdict"] = v.group(1).lower()
        line = src[src.rfind("\n", 0, v.start()) + 1:].split("\n", 1)[0]
        r["counts"] = {k.upper(): int(n) for n, k in COUNT_RE.findall(line)}
    return r


def parse_json(text):
    """STACK_REPORT_FORMAT=json: the last line that is a JSON object with status and result (as
    bin/stack_sdk.py parse_report) -> the parse() shape, format json; None when there is none."""
    for ln in reversed([x.strip() for x in str(text or "")[:TEXT_MAX].splitlines() if x.strip()]):
        if not ln.startswith("{"):
            continue
        try:
            obj = json.loads(ln)
        except (ValueError, RecursionError):
            continue
        if not isinstance(obj, dict) or not {"status", "result"} <= set(obj):
            continue
        st = str(obj.get("status") or "").strip().lower()
        files = obj.get("files") or []
        files = files if isinstance(files, list) else [files]
        ef = str(obj.get("eflag") or "").strip().lower()
        r = parse("")
        r.update(format="json", chars=len(str(text)), status=st if st in STATUSES else None,
                 status_raw=None if st in STATUSES else st[:20], eflag=ef if ef in EFLAGS else None,
                 result=str(obj.get("result") or "") or None, evidence=str(obj.get("evidence") or "") or None,
                 next=str(obj.get("next") or "") or None,
                 files=[{"path": str(f)[:1024], "purpose": "", "deleted": False} for f in files if str(f).strip()])
        return r
    return None


def blob_score(text):
    """(score, hits): pasted content in a report or brief. Hits: read_output (10+ lines that look like Read
    output), fence (a code fence over 15 lines or 1,500 chars), base64_or_hex (a run of 200+), control
    (control or binary characters), long_line (a line over 2,000 chars). score = len(hits)."""
    text = text if isinstance(text, str) else ""
    body = text[:TEXT_MAX]
    hits = []
    lines = body.split("\n")
    if sum(1 for ln in lines if READ_LINE_RE.match(ln)) >= 10:
        hits.append("read_output")
    open_, n, size = None, 0, 0
    for ln in lines:
        m = FENCE_RE.match(ln)
        if open_ is None:
            if m:
                open_, n, size = m.group(1), 0, 0
            continue
        if m and m.group(1) == open_:
            if n > 15 or size > 1500:
                hits.append("fence")
                break
            open_ = None
            continue
        n += 1
        size += len(ln) + 1
    else:
        if open_ is not None and (n > 15 or size > 1500):
            hits.append("fence")
    if B64_RE.search(body):
        hits.append("base64_or_hex")
    if CTRL_RE.search(body):
        hits.append("control")
    if any(len(ln) > 2000 for ln in lines):
        hits.append("long_line")
    return len(hits), hits


def check(parsed, agent_type, text=None):
    """parse() (or parse_json()) result + the agent type -> {class, cap, chars, counted, eflag, hard, soft,
    blob}. eflag: the report's flag, else `look` for a non-done status (implied; the validator sets it)."""
    cls = role_class(agent_type)
    st = parsed.get("status")
    cap = cap_for(cls, st)
    hard_cls = CAPS.get(cls, CAPS["builder"])["hard"]
    hard, soft = [], []
    if st is None:
        hard.append("invalid_status" if parsed.get("status_raw") else "no_status")
    elif st != "done":
        if not parsed.get("evidence"):
            hard.append("no_evidence")
        if not parsed.get("next"):
            hard.append("no_next")
        if not parsed.get("eflag"):
            soft.append("eflag_implied")
    _, hits = blob_score(unwrap(text) if isinstance(text, str) else "")
    if hits:
        (hard if hard_cls else soft).append("blob")
    chars = int(parsed.get("chars") or 0)
    counted = max(chars - int(parsed.get("files_chars") or 0), 0)
    if counted > cap:
        (hard if hard_cls and counted > OVERRUN * cap else soft).append("size")
    if st == "done" and not parsed.get("eflag") and SUSPECT_RE.search(parsed.get("result") or ""):
        soft.append("suspect")
    eflag = parsed.get("eflag") or ("look" if st in ("partial", "failed", "blocked") else None)
    return {"class": cls, "cap": cap, "chars": chars, "counted": counted, "eflag": eflag, "hard": hard,
            "soft": soft, "blob": hits}


def restate_reason(hard, cls, cap):
    """The block reason of a compact-mode restate (<= REASON_MAX chars): what is wrong + the grammar."""
    words = {"no_status": "no STATUS line", "invalid_status": "STATUS is not done|partial|failed|blocked",
             "no_evidence": "EVIDENCE missing (required unless done)",
             "no_next": "NEXT missing (required unless done)", "blob": "pasted content (files go by path)",
             "size": "over the %s cap of %d chars" % (cls, cap)}
    what = "; ".join(words.get(h, str(h)[:40]) for h in hard)
    room = REASON_MAX - len(GRAMMAR) - len("Hand-back format: . Reply again, once, as:\n")
    return "Hand-back format: %s. Reply again, once, as:\n%s" % (what[:room], GRAMMAR)


def brief_stats(prompt):
    """An Agent call's prompt -> {brief_chars (agent-written: a `USER:` block to the end is exempt),
    brief_user_chars, brief_blob, brief_pasted, brief_warn (the compact-mode warning or None)}."""
    prompt = prompt if isinstance(prompt, str) else ""
    m = USER_RE.search(prompt)
    own = prompt[:m.start()] if m else prompt
    _, hits = blob_score(own)
    pasted = bool(PASTED_RE.search(own[:TEXT_MAX]))
    out = {"brief_chars": len(own), "brief_user_chars": len(prompt) - len(own), "brief_blob": hits,
           "brief_pasted": pasted, "brief_warn": None}
    why = []
    if len(own) > BRIEF_CAP:
        why.append("%d agent-written chars (cap %d)" % (len(own), BRIEF_CAP))
    if pasted:
        why.append("a pasted report")
    if hits:
        why.append("pasted content (%s)" % ", ".join(hits))
    if why:
        out["brief_warn"] = ("Brief check (STACK_REPORT_FORMAT=compact): %s. Pass paths and plan nodes "
                             "(GOAL/IN/C/DONE/OUT), never contents or reports; a user's prompt goes after USER:."
                             % "; ".join(why))
    return out


# ---------------------------------------------------------------- file metadata
def _real(p):
    try:
        return os.path.realpath(p)
    except (OSError, ValueError):
        return None


def _inside(path, root):
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _broad(root):
    """/, the home folder and its ancestors are no root: a cwd of ~ must not open ~/.ssh."""
    home = _real(os.path.expanduser("~")) or ""
    return root in ("", os.sep) or root == home or _inside(home, root)


def _credential(path):
    low = path.lower()
    return any(p in CREDENTIAL_PARTS or ENV_FILE_RE.match(p) for p in low.split(os.sep)) \
        or any(s in low for s in CREDENTIAL_SUBSTR)


def _read_small(path, cap=4096):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        return os.read(fd, cap).decode("utf-8", "replace")
    except OSError:
        return None
    finally:
        os.close(fd)


def main_work_dir(cwd):
    """<main checkout>/.claude-work for a cwd inside a git checkout or one of its worktrees (read from
    .git and commondir, no git process), else None."""
    cur = _real(cwd) if isinstance(cwd, str) and os.path.isabs(cwd) else None
    for _ in range(64):
        if not cur:
            return None
        dot = os.path.join(cur, ".git")
        try:
            st = os.lstat(dot)
        except OSError:
            st = None
        if st is not None and stat.S_ISDIR(st.st_mode):
            return os.path.join(cur, ".claude-work")
        if st is not None and stat.S_ISREG(st.st_mode):
            txt = _read_small(dot) or ""
            m = re.match(r"gitdir:\s*(.+)", txt.strip())
            if not m:
                return None
            gitdir = m.group(1).strip()
            gitdir = gitdir if os.path.isabs(gitdir) else os.path.join(cur, gitdir)
            common = (_read_small(os.path.join(gitdir, "commondir")) or "").strip()
            common = _real(os.path.join(gitdir, common)) if common else None
            if common and os.path.basename(common) == ".git":
                return os.path.join(os.path.dirname(common), ".claude-work")
            return None
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent
    return None


def allowed_roots(cwd, project_dir=None):
    """The real paths file_meta may look inside: the event cwd, $CLAUDE_PROJECT_DIR (neither when it is /,
    the home folder or an ancestor of it) and the main checkout's .claude-work/."""
    roots = []
    for c in (cwd, project_dir):
        r = _real(c) if isinstance(c, str) and os.path.isabs(c) else None
        if r and not _broad(r) and r not in roots:
            roots.append(r)
    for c in (cwd, project_dir):
        w = main_work_dir(c) if isinstance(c, str) else None
        # the checkout is resolved, never .claude-work itself: an agent may make that a symlink
        top = _real(os.path.dirname(w)) if w else None
        w = os.path.join(top, ".claude-work") if top else None
        if w and not _broad(w) and w not in roots:
            roots.append(w)
    return roots


def _fd_path(fd):
    """The path the kernel holds for an open descriptor (macOS F_GETPATH, Linux /proc), or None."""
    try:
        import fcntl
        if hasattr(fcntl, "F_GETPATH"):
            raw = fcntl.fcntl(fd, fcntl.F_GETPATH, bytes(1024))
            return os.fsdecode(raw.split(b"\0", 1)[0])
    except (OSError, ValueError, ImportError):
        return None
    try:
        return os.readlink("/proc/self/fd/%d" % fd)
    except OSError:
        return None


def _resolve(path, cwd):
    """A FILES path -> its real path (relative to cwd, ~ expanded), or None."""
    p = os.path.expanduser(path)
    if not os.path.isabs(p):
        if not (isinstance(cwd, str) and os.path.isabs(cwd)):
            return None
        p = os.path.join(cwd, p)
    return _real(p)


def _hash_jobs(jobs, out):
    for key, fd in jobs:
        h = hashlib.sha256()
        try:
            while True:
                b = os.read(fd, 1 << 20)
                if not b:
                    break
                h.update(b)
            out[key] = h.hexdigest()[:8]
        except OSError:
            out[key] = None
        finally:
            try:
                os.close(fd)
            except OSError:
                pass


def file_meta(files, cwd, project_dir=None, budget=META_BUDGET_S):
    """parse()'s files -> [{path, state, size?, mtime?, sha8?}]; state ok | missing | deleted (named
    `deleted` and absent) | outside (not looked at) | not_regular | symlink | error. At most FILES_MAX
    paths (the rest: state skipped). Never raises for one path; the hash thread is waited for `budget` s."""
    roots = allowed_roots(cwd, project_dir)
    out, jobs = [], []
    t0 = time.monotonic()
    for i, f in enumerate(files or []):
        path = str(f.get("path") or "")
        shown = CTRL_RE.sub("?", path)[:300]
        rec = {"path": shown}
        out.append(rec)
        if i >= FILES_MAX:
            rec["state"] = "skipped"
            continue
        real = _resolve(path, cwd)
        if not real or not any(_inside(real, r) for r in roots) or _credential(real):
            rec["state"] = "outside"
            continue
        flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NOCTTY", 0) \
            | getattr(os, "O_CLOEXEC", 0)
        try:
            fd = os.open(real, flags)
        except FileNotFoundError:
            rec["state"] = "deleted" if f.get("deleted") else "missing"
            continue
        except OSError as exc:
            rec["state"] = "symlink" if exc.errno == errno.ELOOP else "error"
            continue
        keep = False
        try:
            held = _fd_path(fd)
            held = _real(held) if held else None
            if held is not None and (not any(_inside(held, r) for r in roots) or _credential(held)):
                rec["state"] = "outside"           # swapped after the realpath: no stat recorded
                continue
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                rec["state"] = "not_regular"
                continue
            rec.update(state="ok", size=st.st_size, mtime=int(st.st_mtime))
            if st.st_size <= HASH_MAX and not (getattr(st, "st_flags", 0) & SF_DATALESS):
                jobs.append((i, fd))
                keep = True
        except OSError:
            rec["state"] = "error"
        finally:
            if not keep:
                os.close(fd)
    if jobs:
        sums = {}
        t = threading.Thread(target=_hash_jobs, args=(jobs, sums), name="stack-report-hash")
        t.daemon = True
        t.start()
        t.join(max(budget - (time.monotonic() - t0), 0.05))
        for key, _fd in jobs:
            if sums.get(key):
                out[key]["sha8"] = sums[key]
            else:
                out[key]["hash"] = "timeout" if key not in sums else "error"
    return out


def _tail(path, cap):
    """The last `cap` bytes of a transcript (an absolute path to a regular file, no symlink followed), or
    None."""
    if not (isinstance(path, str) and os.path.isabs(os.path.expanduser(path))):
        return None
    try:
        fd = os.open(os.path.expanduser(path), os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_NOCTTY", 0))
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return None
        os.lseek(fd, max(st.st_size - cap, 0), os.SEEK_SET)
        return os.read(fd, cap)
    except OSError:
        return None
    finally:
        os.close(fd)


def transcript_handback(path, cap=TAIL_MAX):
    """S4 L7 B1: the SubagentHandback message that ended a run. Only the NEWEST assistant record of the
    transcript's tail counts (a resumed run that answers in text is no hand-back, whatever an earlier run
    called): its last SubagentHandback tool_use's input `message`, "" when that is missing or not a
    string; None when the newest assistant record holds no SubagentHandback (or none is in the tail)."""
    data = _tail(path, cap)
    for line in reversed(data.split(b"\n") if data else []):
        if b'"assistant"' not in line:
            continue
        try:
            rec = json.loads(line.decode("utf-8", "replace"))
        except (ValueError, RecursionError):
            continue
        if not isinstance(rec, dict) or rec.get("type") != "assistant":
            continue
        msg = rec.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        uses = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"
                and b.get("name") == "SubagentHandback"] if isinstance(content, list) else []
        if not uses:
            return None
        tin = uses[-1].get("input")
        text = tin.get("message") if isinstance(tin, dict) else None
        return text if isinstance(text, str) else ""
    return None


def transcript_last_tool(path, cap=TAIL_MAX):
    """Name of the last tool_use in a transcript's tail (bounded read; regular files only), or None."""
    data = _tail(path, cap)
    if data is None:
        return None
    for line in reversed(data.split(b"\n")):
        if b'"tool_use"' not in line:
            continue
        try:
            rec = json.loads(line.decode("utf-8", "replace"))
        except (ValueError, RecursionError):
            continue
        msg = rec.get("message") if isinstance(rec, dict) else None
        content = msg.get("content") if isinstance(msg, dict) else None
        names = [b.get("name") for b in content or [] if isinstance(b, dict) and b.get("type") == "tool_use"]
        if names and isinstance(names[-1], str):
            return names[-1][:80]
    return None
