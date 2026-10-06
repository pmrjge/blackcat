"""lib/config_region.py: the --ide-default regions in config.toml (DESIGN.md §7.6)."""
from __future__ import annotations

import tomllib

import pytest

from conftest import load_lib

cr = load_lib("config_region")

A = 'model = "gpt-6-luna"\nmodel_reasoning_effort = "high"\napproval_policy = "on-request"\n'
B = ('[features]\nmulti_agent_v2 = false\n\n[agents]\nmax_depth = 8\n\n[agents.coder]\n'
     'description = "c"\nconfig_file = "stack/agents/coder.toml"\n\n'
     '[[hooks.PreToolUse]]\nmatcher = ".*"\n\n[[hooks.PreToolUse.hooks]]\ntype = "command"\n'
     'command = "/bin/sh \'/x/stack/bin/codex-hook\' pre_tool_use"\n')

ROOT_ONLY = b'# my settings\nnotify = ["say", "done"]\nfile_opener = "vscode"\n'
WITH_TABLES = (b'# my settings\nnotify = ["say"]\n\n[projects."/Users/me/w"]\ntrust_level = "trusted"\n\n'
               b'[mcp_servers.mine]\ncommand = "mine"\n')
CODEX_APPEND = (b'\n[hooks.state."/x/config.toml:pre_tool_use:0:0"]\ntrusted_hash = "abc"\n\n'
                b'[projects."/Users/me/other"]\ntrust_level = "trusted"\n')


def stack_doc():
    return cr.merge(tomllib.loads(A), tomllib.loads(B))


def check(data, out):
    """the contract: user bytes outside the regions intact; meaning = merge(user, stack)."""
    user = cr.remove(out)
    assert user in (data, data + b"\n", data + b"\r\n")
    assert tomllib.loads(out.decode()) == cr.merge(tomllib.loads(data.decode()), stack_doc())
    spans = cr.find(out)
    assert spans["A"][0] == 0                      # A at the very start
    assert spans["B"][1] == len(out)               # B at the very end
    return spans


@pytest.mark.parametrize("data", [b"", ROOT_ONLY, WITH_TABLES], ids=["empty", "root-only", "tables"])
def test_splice_contract(data):
    check(data, cr.splice(data, A, B))


def test_user_root_key_never_captured_by_a_region():
    out = cr.splice(WITH_TABLES, A, B)
    doc = tomllib.loads(out.decode())
    assert doc["notify"] == ["say"] and doc["model"] == "gpt-6-luna"
    assert "notify" not in doc["agents"] and "model" not in doc["projects"]


def test_idempotent_second_splice():
    once = cr.splice(WITH_TABLES, A, B)
    assert cr.splice(once, A, B) == once


def test_resplice_replaces_region_body():
    once = cr.splice(ROOT_ONLY, A, B)
    twice = cr.splice(once, A.replace("high", "xhigh"), B)
    assert cr.remove(twice) == ROOT_ONLY
    assert tomllib.loads(twice.decode())["model_reasoning_effort"] == "xhigh"


def test_codex_style_appends_after_b_survive_resplice_and_remove():
    out = cr.splice(WITH_TABLES, A, B) + CODEX_APPEND
    again = cr.splice(out, A, B)
    doc = tomllib.loads(again.decode())
    assert doc["hooks"]["state"]["/x/config.toml:pre_tool_use:0:0"]["trusted_hash"] == "abc"
    assert doc["projects"]["/Users/me/other"]["trust_level"] == "trusted"
    assert doc["hooks"]["PreToolUse"][0]["matcher"] == ".*"
    assert cr.find(again)["B"][1] == len(again)            # B moved back to the end
    assert cr.remove(out) == WITH_TABLES + CODEX_APPEND     # removal cuts exactly the regions
    assert cr.remove(again) == WITH_TABLES + CODEX_APPEND


def test_remove_exact_inverse():
    for data in (b"", ROOT_ONLY, WITH_TABLES):
        assert cr.remove(cr.splice(data, A, B)) == data


def test_remove_without_regions_is_identity():
    assert cr.remove(WITH_TABLES) == WITH_TABLES


def test_no_trailing_newline_gets_one_before_b():
    data = b'notify = ["say"]\n[t]\nx = 1'
    out = cr.splice(data, A, B)
    check(data, out)
    assert cr.remove(out) == data + b"\n"


def test_crlf_file_keeps_its_bytes_and_regions_are_lf():
    data = WITH_TABLES.replace(b"\n", b"\r\n")
    out = cr.splice(data, A, B)
    check(data, out)
    assert cr.remove(out) == data
    s, e = cr.find(out)["A"]
    assert b"\r" not in out[s:e]
    # no trailing newline in a CRLF file: the added one is CRLF
    assert cr.remove(cr.splice(data.rstrip(b"\r\n"), A, B)) == data.rstrip(b"\r\n") + b"\r\n"


def test_crlf_markers_found():
    out = cr.splice(ROOT_ONLY, A, B).replace(b"\n", b"\r\n")
    spans = cr.find(out)
    assert spans["A"][0] == 0 and spans["B"][1] == len(out)
    assert cr.remove(out) == ROOT_ONLY.replace(b"\n", b"\r\n")


def test_conflict_with_user_root_key_names_it():
    data = b'model = "o3"\n' + ROOT_ONLY
    with pytest.raises(cr.RegionConflict) as ei:
        cr.splice(data, A, B)
    assert ei.value.keys == ["model"]


def test_conflict_with_user_table_key_names_it():
    data = b'[agents]\nmax_depth = 2\n'
    with pytest.raises(cr.RegionConflict) as ei:
        cr.splice(data, A, B)
    assert ei.value.keys == ["agents.max_depth"]


def test_duplicate_table_header_is_a_conflict():
    data = b'[features]\nweb_search_request = true\n'
    with pytest.raises(cr.RegionConflict) as ei:
        cr.splice(data, A, B)
    assert ei.value.keys == ["features"]


def test_user_table_beside_stack_tables_is_fine():
    out = cr.splice(WITH_TABLES, A, B)
    doc = tomllib.loads(out.decode())
    assert doc["mcp_servers"]["mine"]["command"] == "mine"


def test_conflicts_function_dotted_and_quoted():
    assert cr.conflicts({"a": {"b": 1}, "c": 2}, {"a": {"b": 2, "d": 1}, "e": 1}) == ["a.b"]
    assert cr.conflicts({"x y": 1}, {"x y": 2}) == ['"x y"']
    assert cr.conflicts({"m": {"k": 1}}, {"m": {"j": 1}}) == []


def test_conflicts_mutually_exclusive_keys():
    """ShellEnvironmentPolicyToml: `filters` may not sit beside `exclude` or `include_only`."""
    stack = {"shell_environment_policy": {"filters": {"GH_TOKEN": "exclude"}}}
    for legacy in ("exclude", "include_only"):
        user = {"shell_environment_policy": {legacy: ["X"]}}
        assert cr.conflicts(user, stack) == ["shell_environment_policy." + legacy]
    assert cr.conflicts({"shell_environment_policy": {"inherit": "core"}}, stack) == []
    assert cr.conflicts({"shell_environment_policy": {"exclude": ["X"]}},
                        {"shell_environment_policy": {"inherit": "all"}}) == []


@pytest.mark.parametrize("bad", [
    cr.BEGIN_A.encode() + b"\n" + cr.BEGIN_A.encode() + b"\n" + cr.END_A.encode() + b"\n",
    cr.BEGIN_A.encode() + b"\nx = 1\n",
    b"x = 1\n" + cr.END_B.encode() + b"\n",
    cr.END_A.encode() + b"\n" + cr.BEGIN_A.encode() + b"\n",
    b"# >>> claude-agent-stack: begin C >>>\n",
    cr.BEGIN_A.encode() + b"\n" + cr.BEGIN_B.encode() + b"\n" + cr.END_A.encode() + b"\n" + cr.END_B.encode() + b"\n",
], ids=["dup-begin", "lone-begin", "lone-end", "end-first", "unknown", "overlap"])
def test_malformed_markers_raise_and_splice_refuses(bad):
    with pytest.raises(cr.RegionError):
        cr.find(bad)
    with pytest.raises(cr.RegionError):
        cr.splice(bad, A, B)
    with pytest.raises(cr.RegionError):
        cr.remove(bad)


def test_marker_recognised_by_prefix_and_indentation():
    data = (b"  # >>> claude-agent-stack: begin A (older wording) >>>\nmodel = \"x\"\n"
            b"# <<< claude-agent-stack: end A <<<\nrest = 1\n")
    assert cr.find(data)["A"] == (0, data.index(b"rest"))
    assert cr.remove(data) == b"rest = 1\n"


def test_table_in_region_a_refused():
    with pytest.raises(cr.RegionError):
        cr.splice(ROOT_ONLY, A + "[t]\nx = 1\n", B)
    with pytest.raises(cr.RegionError):
        cr.splice(ROOT_ONLY, 'features.x = true\n[y]\n', B)


def test_root_key_in_region_b_refused():
    with pytest.raises(cr.RegionError, match="tables only"):
        cr.splice(WITH_TABLES, A, 'stray = 1\n' + B)


def test_invalid_user_toml_refused():
    with pytest.raises(cr.RegionError, match="not valid TOML"):
        cr.splice(b"x = = 1\n", A, B)


def test_marker_in_stack_text_refused():
    with pytest.raises(cr.RegionError):
        cr.splice(b"", A + cr.END_A + "\n", B)


def test_region_sha_tracks_region_bytes_only():
    out = cr.splice(WITH_TABLES, A, B)
    shas = cr.region_sha(out)
    assert set(shas) == {"A", "B"} and all(len(v) == 64 for v in shas.values())
    assert cr.region_sha(out + CODEX_APPEND) == shas            # outside edits: same
    edited = out.replace(b'"high"', b'"low"', 1)               # /model writing in place
    assert cr.region_sha(edited)["A"] != shas["A"] and cr.region_sha(edited)["B"] == shas["B"]
    assert cr.region_sha(WITH_TABLES) == {"A": None, "B": None}


def test_empty_region_texts_write_marker_pairs():
    out = cr.splice(ROOT_ONLY, "", "")
    assert out == (cr.BEGIN_A + "\n" + cr.END_A + "\n").encode() + ROOT_ONLY + (
        cr.BEGIN_B + "\n" + cr.END_B + "\n").encode()
    assert cr.remove(out) == ROOT_ONLY
