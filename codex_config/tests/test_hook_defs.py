"""lib/hook_defs.py (INTERFACES.md §3-C; DESIGN.md §4.4, §8.5): the hooks table, its TOML form
against config.schema.json, trust keys and fingerprints."""
from __future__ import annotations

import json
import sys

import pytest

from _guard_helpers import VENDOR
from conftest import load_lib

hd = load_lib("hook_defs")
STUB = "/Users/me/.codex/stack/bin/codex-hook"
SCHEMA = json.loads((VENDOR / "config.schema.json").read_text())["definitions"]


def test_one_group_per_event_with_the_stub_command():
    t = hd.hooks_table(STUB)
    assert list(t) == list(hd.EVENTS) and len(t) == 8
    for event, groups in t.items():
        assert len(groups) == 1 and len(groups[0]["hooks"]) == 1
        h = groups[0]["hooks"][0]
        assert h == {"type": "command", "command": "/bin/sh '%s' %s" % (STUB, hd.snake(event)),
                     "timeout": 3 if event == "SessionEnd" else 10}
        assert ("matcher" in groups[0]) == (event in ("PreToolUse", "PermissionRequest", "PostToolUse"))
        if "matcher" in groups[0]:
            assert groups[0]["matcher"] == ".*"


def test_modes_are_the_guards_modes():
    from _guard_helpers import HOOKS_SRC, load_by_path
    g = load_by_path("codex_guard_hookdefs", HOOKS_SRC / "codex_guard.py")
    assert tuple(hd.snake(e) for e in hd.EVENTS) == g.MODES
    assert {hd.snake(e): e for e in hd.EVENTS} == g.EVENT_NAMES


def test_global_scope_suffix():
    t = hd.hooks_table(STUB, scope="global")
    assert all(g[0]["hooks"][0]["command"].endswith(" --scope global") for g in t.values())
    with pytest.raises(hd.BuildError):
        hd.hooks_table(STUB, scope="other")


@pytest.mark.parametrize("bad", ["relative/codex-hook", "/x/it's/codex-hook", "/x/\nnl", None, ""])
def test_unquotable_stub_paths_refused(bad):
    with pytest.raises(hd.BuildError):
        hd.hooks_table(bad)


def test_keys_and_fingerprints():
    src = "/Users/me/.codex/codex.config.toml"
    keys = hd.hook_keys(src, hd.hooks_table(STUB))
    assert [k["key"] for k in keys] == ["%s:%s:0:0" % (src, hd.snake(e)) for e in hd.EVENTS]
    assert keys[0]["key"] == src + ":pre_tool_use:0:0"
    assert all(len(k["fingerprint"]) == 64 for k in keys)
    assert len({k["fingerprint"] for k in keys}) == 8
    assert hd.hook_keys(src, hd.hooks_table(STUB)) == keys           # deterministic


def test_fingerprint_tracks_the_definition_only():
    h = {"type": "command", "command": "/bin/sh '/a' pre_tool_use", "timeout": 10}
    base = hd.fingerprint("PreToolUse", ".*", h)
    assert hd.fingerprint("PreToolUse", ".*", dict(h)) == base
    assert hd.fingerprint("PreToolUse", ".*", dict(reversed(list(h.items())))) == base
    assert hd.fingerprint("PreToolUse", None, h) != base
    assert hd.fingerprint("PreToolUse", ".*", dict(h, timeout=11)) != base
    assert hd.fingerprint("PreToolUse", ".*", dict(h, command="/bin/sh '/b' pre_tool_use")) != base
    assert hd.fingerprint("PostToolUse", ".*", h) != base


def test_state_table_is_not_keyed():
    t = dict(hd.hooks_table(STUB), state={"x": {"trusted_hash": "h"}})
    assert len(hd.hook_keys("/f", t)) == 8


def test_table_fits_config_schema():
    events = set(SCHEMA["HooksToml"]["properties"]) - {"state"}
    group_keys = set(SCHEMA["MatcherGroup"]["properties"])
    command = next(v for v in SCHEMA["HookHandlerConfig"]["oneOf"]
                   if v["properties"]["type"].get("enum") == ["command"])
    for event, groups in hd.hooks_table(STUB).items():
        assert event in events
        for g in groups:
            assert set(g) <= group_keys
            for h in g["hooks"]:
                assert set(h) <= set(command["properties"]) and set(command["required"]) <= set(h)


@pytest.mark.skipif(sys.version_info < (3, 11), reason="tomllib (the installer side) needs 3.11")
def test_toml_round_trip():
    import tomllib
    te = load_lib("toml_emit")
    doc = {"hooks": hd.hooks_table(STUB)}
    back = tomllib.loads(te.dumps(doc))
    assert back == doc
    text = te.dumps(doc)
    assert "[[hooks.PreToolUse]]" in text and "[[hooks.PreToolUse.hooks]]" in text
