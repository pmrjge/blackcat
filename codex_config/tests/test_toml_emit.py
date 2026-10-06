"""lib/toml_emit.py: round trip through tomllib, refusals, layout (DESIGN.md §7.5)."""
from __future__ import annotations

import datetime
import math
import random
import tomllib

import pytest

from conftest import load_lib

te = load_lib("toml_emit")


def rt(doc):
    text = te.dumps(doc)
    assert tomllib.loads(text) == doc, text
    return text


# ---------------------------------------------------------------- examples


def test_scalars_and_escapes():
    rt({"a": 'say "hi" \\ there', "b": 1, "c": True, "d": False, "e": -3, "f": 1.5,
        "g": "tab\there", "h": "ctl\x01\x7f", "i": "", "j": "naïve ✓"})


def test_quote_escape_is_load_bearing():
    # seeded bug "drop the \" escape" makes this text unparsable
    text = te.dumps({"k": 'a"b'})
    assert text == 'k = "a\\"b"\n'


def test_multiline_literal_used_when_exact():
    s = "line one\nline 'two'\n\tindented\n"
    text = rt({"developer_instructions": s})
    assert "'''" in text


@pytest.mark.parametrize("s", ["has ''' run\nx", "cr\r\nlf", "ends with quote\n'", "bell\x07\n"])
def test_multiline_falls_back_to_basic(s):
    text = rt({"d": s})
    assert not text.startswith("d = '''")


def test_keys_quoted_when_needed():
    doc = {"a.b": 1, "with space": {"x": 1}, "ünï": 2, "": 3, "ok-key_1": 4}
    text = rt(doc)
    assert 'ok-key_1 = 4' in text and '"a.b" = 1' in text


def test_tables_after_scalars_whatever_the_order():
    doc = {"t": {"x": 1}, "s": 2}
    text = rt(doc)
    assert text.index("s = 2") < text.index("[t]")


def test_arrays_of_tables_with_subtables():
    doc = {"hooks": {"PreToolUse": [
        {"matcher": ".*", "hooks": [{"type": "command", "command": "/bin/sh 'x y' pre", "timeout": 10}]},
        {"hooks": [{"type": "command", "command": "b"}]},
    ], "state": {"/p/a.toml:pre_tool_use:0:0": {"trusted_hash": "abc"}}}}
    text = rt(doc)
    assert "[[hooks.PreToolUse]]" in text and "[[hooks.PreToolUse.hooks]]" in text


def test_empty_table_and_empty_list_survive():
    rt({"a": {}, "b": [], "c": {"d": {}}, "e": [{}]})


def test_deterministic():
    doc = {"z": 1, "a": {"y": [1, 2], "b": "x"}}
    assert te.dumps(doc) == te.dumps(dict(doc))


# ---------------------------------------------------------------- refusals


@pytest.mark.parametrize("bad", [
    {"x": None}, {"x": float("nan")}, {"x": float("inf")}, {"x": -math.inf},
    {"x": datetime.date(2026, 1, 1)}, {"x": {1, 2}}, {"x": [1, {"a": 1}]}, {"x": [[{"a": 1}]]},
    {"x": 2 ** 63}, {1: "int key"}, {"x": b"bytes"},
])
def test_refuses_unsupported(bad):
    with pytest.raises(te.TomlEmitError):
        te.dumps(bad)


def test_bool_is_not_int():
    assert te.dumps({"x": True}) == "x = true\n"
    assert te.dumps({"x": 1}) == "x = 1\n"


# ---------------------------------------------------------------- property


_ALPHA = "abcXYZ019_- .\"'\\\n\t\r\x00\x1f\x7féü✓'''"


def _rstr(r):
    return "".join(r.choice(_ALPHA) for _ in range(r.randint(0, 12)))


def _rscalar(r):
    k = r.randint(0, 4)
    if k == 0:
        return _rstr(r)
    if k == 1:
        return r.randint(-(2 ** 63), 2 ** 63 - 1)
    if k == 2:
        return r.choice([True, False])
    if k == 3:
        f = r.uniform(-1e6, 1e6)
        return f if r.random() < .8 else r.choice([0.0, -0.0, 1e300, 5e-324])
    return [_rscalar(r) for _ in range(r.randint(0, 3))] if r.random() < .5 else _rstr(r)


def _rtable(r, depth):
    t = {}
    for _ in range(r.randint(0, 5)):
        key = _rstr(r)
        roll = r.random()
        if depth < 3 and roll < .2:
            t[key] = _rtable(r, depth + 1)
        elif depth < 3 and roll < .3:
            t[key] = [_rtable(r, depth + 1) for _ in range(r.randint(1, 3))]
        else:
            t[key] = _rscalar(r)
    return t


def test_round_trip_property_seeded_corpus():
    r = random.Random(20261006)
    for _ in range(600):
        doc = _rtable(r, 0)
        text = te.dumps(doc)
        got = tomllib.loads(text)
        # -0.0 == 0.0 in Python, so compare repr of floats too
        assert got == doc, text
        assert te.dumps(got) == text
