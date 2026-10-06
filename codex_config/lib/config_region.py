"""The stack's two marked regions in CODEX_HOME/config.toml (--ide-default, DESIGN.md §7.6). Stdlib only.

config.toml is the user's file (and Codex writes it too: /hooks trust, [projects.*], /model). Under
--ide-default the installer owns two regions in it, each delimited by whole-line comment markers:

- region A at the very start of the file, root keys only (model, approval_policy, ...): TOML cannot
  return to the root table after a table header, so root keys must come before the user's tables;
- region B at the end of the file, tables only ([features], [agents.*], [[hooks.*]], ...).

Rules:
- Exactly one begin and one end marker line per region (or none of either). Anything else (a
  duplicate, a lone marker, an end before its begin, overlapping regions, an unrecognised
  `# >>> claude-agent-stack` / `# <<< claude-agent-stack` line) raises RegionError and the caller
  leaves the file untouched.
- Bytes outside the regions never change. One exception: a file whose last line has no newline gets
  one (in the file's own style) before region B is appended, so that B starts on its own line;
  remove() keeps that newline.
- Conflict check: no key may be defined both by the user's part and by the stack's regions
  (conflicts() names the dotted keys), and tomllib.loads(result) must equal merge(user, stack).
  splice() raises RegionConflict (a RegionError with .keys) when either fails.
- Line endings: the user's bytes keep theirs (CRLF stays CRLF). The regions are always written with
  LF: mixed line endings are valid TOML, and the region bytes (hence region_sha) do not depend on
  the file around them.
- Marker lines are recognised by their fixed prefix (`# >>> claude-agent-stack: begin A`, ...), so a
  later version may reword the rest of the line; optional indentation and a trailing CR are allowed.

API: find(data) -> {"A": (start, end)|None, "B": ...}; splice(data, a_text, b_text) -> bytes;
remove(data) -> bytes; region_sha(data) -> {"A": hex|None, "B": hex|None};
conflicts(user_doc, stack_doc) -> [dotted key]; merge(a, b) -> dict; BEGIN_A, END_A, BEGIN_B, END_B.

Seeded-bug proofs (tests/mutations/config_region.json; each turns tests/test_config_region.py red):
write region A after the user's first table; skip the conflict check; let remove() cut one line
past the end marker; accept a second begin marker; let B hold a root key (drop the tables-only check).
"""
from __future__ import annotations

import hashlib
import json
import re
import tomllib

__all__ = ["BEGIN_A", "END_A", "BEGIN_B", "END_B", "RegionError", "RegionConflict", "find", "splice",
           "remove", "region_sha", "conflicts", "merge"]

BEGIN_A = "# >>> claude-agent-stack: begin A (install.sh --ide-default rewrites this region) >>>"
END_A = "# <<< claude-agent-stack: end A <<<"
BEGIN_B = "# >>> claude-agent-stack: begin B (install.sh --ide-default rewrites this region) >>>"
END_B = "# <<< claude-agent-stack: end B <<<"
REGIONS = ("A", "B")

# any line that looks like one of the stack's markers; each must then be a begin or an end below
_ANY = re.compile(rb"^[ \t]*#[ \t]*(?:>>>|<<<)[ \t]*claude-agent-stack\b[^\n]*$", re.MULTILINE)
_BEGIN = re.compile(rb"[ \t]*# >>> claude-agent-stack: begin ([AB])(?![A-Za-z0-9_])[^\n]*")
_END = re.compile(rb"[ \t]*# <<< claude-agent-stack: end ([AB])(?![A-Za-z0-9_])[^\n]*")
_BARE = re.compile(r"[A-Za-z0-9_-]+\Z")
_PROBE = "__claude_agent_stack_probe__"


class RegionError(ValueError):
    """config.toml cannot be spliced safely: the file must be left as it is."""


class RegionConflict(RegionError):
    """A key is defined both by the user's part of config.toml and by the stack's regions."""

    def __init__(self, keys, why="defined both by you and by the stack's --ide-default regions"):
        self.keys = list(keys)
        super().__init__("config.toml: %s: %s" % (why, ", ".join(self.keys)))


def _line_no(data: bytes, pos: int) -> int:
    return data.count(b"\n", 0, pos) + 1


def find(data: bytes) -> dict:
    """{"A": (start, end) | None, "B": ...}: byte offsets of each region, from the start of its begin
    marker line to just past its end marker line's newline (or the end of data)."""
    begins = {r: [] for r in REGIONS}
    ends = {r: [] for r in REGIONS}
    for m in _ANY.finditer(data):
        line = m.group(0)
        b, e = _BEGIN.fullmatch(line), _END.fullmatch(line)
        if b:
            begins[b.group(1).decode()].append(m)
        elif e:
            ends[e.group(1).decode()].append(m)
        else:
            raise RegionError("config.toml line %d is an unrecognised claude-agent-stack marker line"
                              % _line_no(data, m.start()))
    out = {}
    for r in REGIONS:
        bs, es = begins[r], ends[r]
        if not bs and not es:
            out[r] = None
            continue
        if len(bs) != 1 or len(es) != 1:
            raise RegionError("config.toml has %d begin and %d end marker lines for region %s (one of "
                              "each expected)" % (len(bs), len(es), r))
        b, e = bs[0], es[0]
        if e.start() < b.end():
            raise RegionError("config.toml: the end marker of region %s comes before its begin marker" % r)
        end = e.end() + 1 if data[e.end():e.end() + 1] == b"\n" else e.end()
        out[r] = (b.start(), end)
    if out["A"] and out["B"]:
        (a0, a1), (b0, b1) = out["A"], out["B"]
        if a0 < b1 and b0 < a1:
            raise RegionError("config.toml: regions A and B overlap")
    return out


def remove(data: bytes) -> bytes:
    """data with both regions cut out exactly (marker lines included); every other byte kept."""
    spans = sorted((s for s in find(data).values() if s), reverse=True)
    out = data
    for s, e in spans:
        out = out[:s] + out[e:]
    return out


def region_sha(data: bytes) -> dict:
    """{"A": sha256 hex of region A's bytes (markers included) | None, "B": ...}."""
    return {r: (hashlib.sha256(data[s[0]:s[1]]).hexdigest() if s else None)
            for r, s in find(data).items()}


def _dotted(path) -> str:
    return ".".join(k if _BARE.match(k) else json.dumps(k, ensure_ascii=False) for k in path)


def conflicts(user_doc: dict, stack_doc: dict, _path=()) -> list:
    """Dotted keys defined on both sides. Two tables of the same name are not a conflict by
    themselves (a user [mcp_servers.mine] beside the stack's [mcp_servers.jina]); their keys are
    compared one level down."""
    out = []
    for k, s in stack_doc.items():
        if k not in user_doc:
            continue
        u = user_doc[k]
        if isinstance(u, dict) and isinstance(s, dict):
            out += conflicts(u, s, _path + (k,))
        else:
            out.append(_dotted(_path + (k,)))
    return out


def merge(a: dict, b: dict) -> dict:
    """a deep merge of two documents with no key in common at a leaf (tables are merged)."""
    out = dict(a)
    for k, v in b.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = merge(out[k], v)
        elif k in out:
            raise RegionConflict([k])
        else:
            out[k] = v
    return out


def _shared_tables(a: dict, b: dict, _path=()) -> list:
    """The deepest table names both documents define (a duplicate [table] header is invalid TOML)."""
    out = []
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            inner = _shared_tables(a[k], v, _path + (k,))
            out += inner or [_dotted(_path + (k,))]
    return out


def _loads(text: str, what: str) -> dict:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise RegionError("%s is not valid TOML: %s" % (what, exc)) from None


def _block(begin: str, text: str, end: str) -> bytes:
    body = text.replace("\r\n", "\n").rstrip("\n")
    for line in body.split("\n"):
        if _ANY.match(line.encode("utf-8")):
            raise RegionError("the stack's region text contains a claude-agent-stack marker line")
    return ("%s\n%s%s\n" % (begin, body + "\n" if body else "", end)).encode("utf-8")


def _check_parts(a_text: str, b_text: str):
    """A holds root keys only (nothing after it can be captured by a table header in it); B holds
    tables only (no key of it lands in the user's last table)."""
    a_doc = _loads(a_text, "region A")
    probe = _loads(a_text.rstrip("\n") + "\n%s = 1\n" % _PROBE, "region A")
    if probe.get(_PROBE) != 1:
        raise RegionError("region A holds a table header: it may hold root keys only")
    b_doc = _loads(b_text, "region B")
    probe = _loads("[%s]\n%s" % (_PROBE, b_text), "region B")
    if probe.get(_PROBE):
        raise RegionError("region B holds a root key: it may hold tables only")
    return a_doc, b_doc


def splice(data: bytes, a_text: str, b_text: str) -> bytes:
    """config.toml's bytes with region A (a_text) at the very start and region B (b_text) at the end.
    Existing regions are replaced (moved to their places if something was written before A or after
    B); every byte outside them is kept. RegionError (file must stay untouched) on malformed markers,
    invalid TOML, a table in A, a root key in B; RegionConflict on a key defined on both sides."""
    user = remove(data)
    try:
        user_text = user.decode("utf-8")
    except UnicodeDecodeError:
        raise RegionError("config.toml is not UTF-8 text") from None
    user_doc = _loads(user_text, "config.toml (outside the stack's regions)")
    a_doc, b_doc = _check_parts(a_text, b_text)
    stack_doc = merge(a_doc, b_doc)
    found = conflicts(user_doc, stack_doc)
    if found:
        raise RegionConflict(found)
    a_block = _block(BEGIN_A, a_text, END_A)
    b_block = _block(BEGIN_B, b_text, END_B)
    if user and not user.endswith(b"\n"):
        user += b"\r\n" if b"\r\n" in user else b"\n"
    result = a_block + user + b_block
    try:
        got = tomllib.loads(result.decode("utf-8"))
    except tomllib.TOMLDecodeError:
        raise RegionConflict(_shared_tables(user_doc, stack_doc),
                             "a table defined both by you and by the stack's regions") from None
    if got != merge(user_doc, stack_doc):
        raise RegionError("splicing the stack's regions would change the meaning of your config.toml")
    return result
