"""The stack's block in CLAUDE.md. Stdlib only.

CLAUDE.md in the config dir is the user's file. The installer owns one block in it: the lines from a
begin marker line to an end marker line, both written by this module. Every byte outside the block
stays exactly as it is. install.sh loads this file by path from its source snapshot and calls stage()
on the staged copy of the config dir; install_state.py then backs up, applies and restores CLAUDE.md
as a whole file, like any other file of the stack's scope. lib/stack_diff.py (install.sh --diff)
reads the installed block through find_block().

The block's body is dot-claude/CLAUDE.block.md (rendered by install.sh); the marker lines are this
module's, so a template edit can never break them. A marker line of any stack version is recognised
by its fixed prefix, so a later version can reword the rest of the line.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat

NAME = "CLAUDE.md"
BEGIN = "<!-- claude-agent-stack: begin (install.sh rewrites this block; your own text goes outside it) -->"
END = "<!-- claude-agent-stack: end -->"
BOM = b"\xef\xbb\xbf"
# One whole line: optional indentation, the fixed prefix, anything up to "-->", trailing blanks, an
# optional CR (a CRLF file). Text that merely mentions a marker inside a sentence is not a marker.
_BEGIN_RE = re.compile(rb"^(?:\xef\xbb\xbf)?[ \t]*<!-- claude-agent-stack: begin\b[^\n]*?-->[ \t]*\r?$", re.MULTILINE)
_END_RE = re.compile(rb"^(?:\xef\xbb\xbf)?[ \t]*<!-- claude-agent-stack: end\b[^\n]*?-->[ \t]*\r?$", re.MULTILINE)


class BlockError(ValueError):
    """CLAUDE.md's marker lines do not delimit exactly one block: the file is left as it is."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def render_block(body: str) -> bytes:
    """The whole block (marker lines included, newline-terminated) for a template body. A body that
    holds a marker line itself would make the next run see two blocks: refused."""
    text = body.strip("\r\n")
    raw = text.encode("utf-8")
    if _BEGIN_RE.search(raw) or _END_RE.search(raw):
        raise ValueError("the block template contains a claude-agent-stack marker line")
    if "\x00" in text:
        raise ValueError("the block template contains a NUL character")
    inner = text + "\n" if text else ""
    return f"{BEGIN}\n{inner}{END}\n".encode()


def find_block(data: bytes):
    """(start, end) byte offsets of the one block in data, end past the end marker line's newline
    (or the end of data); None when data has no marker line. BlockError when the marker lines do
    not delimit exactly one block."""
    begins = list(_BEGIN_RE.finditer(data))
    ends = list(_END_RE.finditer(data))
    if not begins and not ends:
        return None
    if len(begins) > 1 or len(ends) > 1:
        raise BlockError(f"{len(begins)} begin and {len(ends)} end marker lines (one of each expected)")
    if not ends:
        raise BlockError("a begin marker line without an end marker line")
    if not begins:
        raise BlockError("an end marker line without a begin marker line")
    b, e = begins[0], ends[0]
    if e.start() < b.end():
        raise BlockError("the end marker line comes before the begin marker line")
    start = b.start() + (len(BOM) if data.startswith(BOM, b.start()) else 0)
    end = e.end() + 1 if data[e.end():e.end() + 1] == b"\n" else e.end()
    return start, end


def splice(data, block):
    """CLAUDE.md's bytes with `block` in place: data None = no file, block None = no block (any
    existing one is removed). The user's bytes outside the block are kept; a new block goes at the
    end after one blank line, and removing it takes that separator back with it. BlockError (from
    find_block) when data's marker lines are malformed."""
    if data is None:
        return block
    span = find_block(data)
    if block is None:
        if span is None:
            return data
        before, after = data[:span[0]], data[span[1]:]
        if not after and before.endswith(b"\n\n"):
            before = before[:-1]                   # the blank line an append put before the block
        return before + after
    if span is not None:
        return data[:span[0]] + block + data[span[1]:]
    if not data:
        return block
    return data + (b"\n" if data.endswith(b"\n") else b"\n\n") + block


def stage(dest_dir, body, prev=None, live=None):
    """Bring dest_dir/CLAUDE.md (the installer's staged copy of the config dir) in line with `body`
    (the rendered template; None when the stack ships no block). prev: the manifest's
    claude_md_block entry from the last install, or None. live: the config dir's own CLAUDE.md. The
    staging copies only files and links, so a directory or FIFO there is missing from dest_dir and
    only `live` shows it: without this check the plan would add a file over it, and the apply would
    remove the directory with no backup.

    Returns {"action", "why", "entry"}. action: created (no file before), added (appended to your
    file), updated (an earlier version of the stack's block), replaced (a block that is not the one
    the last install wrote: edited, or unknown to the manifest), unchanged, removed (the stack ships
    no block any more), absent (no block shipped, none present), skipped (the file is left as it is;
    `why` says why). entry: the manifest entry to keep ({"sha256", "created"}), None to drop it; a
    skipped run keeps prev."""
    prev = prev if isinstance(prev, dict) else None       # a hand-edited manifest: start over
    if live is not None and os.path.lexists(live) and not (os.path.islink(live) or os.path.isfile(live)):
        return {"action": "skipped", "entry": prev, "why": "not a regular file: left as it is"}
    path = os.path.join(dest_dir, NAME)
    if os.path.islink(path):
        target = "".join(c if c.isprintable() else "?" for c in os.readlink(path))   # printed in a note
        return {"action": "skipped", "entry": prev,
                "why": f"a symlink to {target} (yours): nothing is written through it, so the stack's "
                       "block is not in it"}
    if os.path.lexists(path) and not os.path.isfile(path):
        return {"action": "skipped", "entry": prev, "why": "not a regular file: left as it is"}
    data = None
    if os.path.isfile(path):
        try:
            with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as f:
                data = f.read()
            data.decode("utf-8")
        except OSError as exc:
            return {"action": "skipped", "entry": prev, "why": f"unreadable ({exc.strerror}): left as it is"}
        except UnicodeDecodeError:
            return {"action": "skipped", "entry": prev, "why": "not UTF-8 text: left as it is"}
    block = render_block(body) if body is not None else None
    try:
        new = splice(data, block)
        span = find_block(data) if data is not None else None
    except BlockError as exc:
        return {"action": "skipped", "entry": prev,
                "why": f"left as it is: {exc}; leave one begin and one end marker line of the stack's "
                       "block (or none), then run ./install.sh again"}
    if data is not None and new != data and not os.stat(path).st_mode & stat.S_IWUSR:
        # the staged copy keeps your mode: a write-protected file is yours to keep as it is
        return {"action": "skipped", "entry": prev,
                "why": "read-only: left as it is (make it writable, then run ./install.sh again)"}
    created = prev is not None and prev.get("created") is True
    if block is None:
        if span is None:
            return {"action": "absent", "why": "", "entry": None}
        if created and not new.strip():
            os.unlink(path)                        # the stack made the file and only its block was left
        else:
            _write(path, new)
        return {"action": "removed", "why": "the stack no longer ships a CLAUDE.md block", "entry": None}
    if new == data:
        action = "unchanged"
    elif data is None:
        action, created = "created", True
    elif span is None:
        action = "added"
    elif prev is not None and prev.get("sha256") == sha256(data[span[0]:span[1]]):
        action = "updated"
    else:
        action = "replaced"
    if new != data:
        _write(path, new)
    why = ("the stack's block in it differed from the one the last install wrote (the backup keeps "
           "your version; your text outside the block is kept)") if action == "replaced" else ""
    return {"action": action, "why": why, "entry": {"sha256": sha256(block), "created": created}}


def _write(path, data):
    """Write the staged copy in place (its mode stays; a new file gets 0644 under the umask). Never
    through a link: stage() refused one, and O_NOFOLLOW keeps it that way."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
