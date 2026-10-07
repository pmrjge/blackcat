"""Minimal deterministic TOML writer for the Codex installer. Stdlib only, Python >= 3.9.

The standard library reads TOML (tomllib, 3.11+) but cannot write it, and the installer is
stdlib-only at run time, so this module writes the subset the installer needs (DESIGN.md §7.5):

- values: str, int (int64), bool, finite float, lists of those (nested lists too);
- tables (dict) and arrays of tables (a non-empty list whose items are all dicts);
- keys: bare when they match [A-Za-z0-9_-]+, else a quoted basic string.

Anything else (None, NaN, inf, datetimes, sets, a list mixing dicts and scalars, a dict inside an
inline array, an int outside int64) raises TomlEmitError: the caller's data is wrong, never guessed.

Layout. Key order is the caller's insertion order, so the same input always gives the same bytes.
Within one table the scalar keys come first, then sub-tables and arrays of tables, because TOML
cannot return to a table's own keys after a sub-table header. An empty dict is written as an empty
header so that it exists after a round trip. A multi-line string (one that holds a newline) is
written as a ''' literal when that is exact (no ''' run, no control character but tab and LF, no
trailing quote), and as an escaped basic string otherwise.

Contract (tests/test_toml_emit.py): tomllib.loads(dumps(x)) == x for every x this module accepts.

Seeded-bug proofs (each turns tests/test_toml_emit.py red): drop the `"` escape in _basic();
emit a multi-line literal even when the text holds '''; write scalars after sub-tables;
accept float("nan"); treat bool as int.
"""
from __future__ import annotations

import math
import re

__all__ = ["TomlEmitError", "dumps", "dumps_value", "quote_key", "basic_string"]

_BARE_KEY = re.compile(r"[A-Za-z0-9_-]+\Z")
_INT64 = (-(2 ** 63), 2 ** 63 - 1)
# characters a basic string must escape (TOML 1.0: U+0000-U+001F, U+007F, quote, backslash)
_ESC = {"\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r", '"': '\\"', "\\": "\\\\"}
_NEEDS_ESC = re.compile(r'[\x00-\x1f\x7f"\\]')
# a multi-line literal string may hold tab and LF but no other control character
_LITERAL_BAD = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class TomlEmitError(TypeError):
    """The value cannot be written by this emitter (unsupported type or invalid value)."""


def basic_string(s: str) -> str:
    """A one-line TOML basic string for any str."""
    def esc(m):
        c = m.group()
        return _ESC.get(c) or "\\u%04X" % ord(c)
    return '"' + _NEEDS_ESC.sub(esc, s) + '"'


def _basic(s: str) -> str:
    return basic_string(s)


def _string(s: str) -> str:
    if "\n" in s and "'''" not in s and not _LITERAL_BAD.search(s) and not s.endswith("'"):
        # the newline right after the opening ''' is trimmed by TOML, so the text is exact
        return "'''\n" + s + "'''"
    return _basic(s)


def quote_key(k) -> str:
    if not isinstance(k, str):
        raise TomlEmitError("TOML keys must be str, got %s" % type(k).__name__)
    return k if _BARE_KEY.match(k) else _basic(k)


def _path(keys) -> str:
    return ".".join(quote_key(k) for k in keys)


def _is_table_array(v) -> bool:
    return isinstance(v, list) and len(v) > 0 and all(isinstance(i, dict) for i in v)


def dumps_value(v, _where="value") -> str:
    """One inline TOML value (no tables)."""
    if isinstance(v, bool):              # before int: bool is a subclass of int
        return "true" if v else "false"
    if isinstance(v, int):
        if not _INT64[0] <= v <= _INT64[1]:
            raise TomlEmitError("%s: integer %d is outside int64" % (_where, v))
        return str(v)
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            raise TomlEmitError("%s: NaN and inf are refused" % _where)
        r = repr(v)
        return r if ("." in r or "e" in r or "E" in r) else r + ".0"
    if isinstance(v, str):
        return _string(v)
    if isinstance(v, list):
        if any(isinstance(i, dict) for i in v):
            raise TomlEmitError("%s: a list of tables must hold only tables" % _where)
        return "[" + ", ".join(dumps_value(i, _where) for i in v) + "]"
    raise TomlEmitError("%s: unsupported type %s" % (_where, type(v).__name__))


def _table(out, path, table, header, array=False):
    if not isinstance(table, dict):
        raise TomlEmitError("%s: expected a table" % (_path(path) or "<root>"))
    scalars = [(k, v) for k, v in table.items() if not isinstance(v, dict) and not _is_table_array(v)]
    subs = [(k, v) for k, v in table.items() if isinstance(v, dict) or _is_table_array(v)]
    if header:
        if out:
            out.append("")
        out.append(("[[%s]]" if array else "[%s]") % _path(path))
    for k, v in scalars:
        out.append("%s = %s" % (quote_key(k), dumps_value(v, _path(path + [k]))))
    for k, v in subs:
        sub = path + [k]
        if isinstance(v, dict):
            # a table with scalars, or an empty one, needs its header; one holding only
            # sub-tables is defined implicitly by them
            need = not v or any(not isinstance(x, dict) and not _is_table_array(x) for x in v.values())
            _table(out, sub, v, header=need)
        else:
            for item in v:
                _table(out, sub, item, header=True, array=True)


def dumps(doc: dict) -> str:
    """The TOML text of a root table; ends with one newline (empty doc: empty string)."""
    if not isinstance(doc, dict):
        raise TomlEmitError("the root must be a dict")
    out = []
    _table(out, [], doc, header=False)
    return "\n".join(out) + ("\n" if out else "")
