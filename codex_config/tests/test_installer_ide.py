"""codex_config/install.sh --ide-default end to end (DESIGN section 9 "--ide-default region 12", 7.6).

The real installer on a scratch HOME / CODEX_HOME with a pre-seeded config.toml (see
_installer_helpers.Sandbox for the scratch tree and its archives). The renderer's own region tests are
test_render_regions.py / test_config_region.py; these go through install.sh: flag pass-through, the
confirmation, the manifest, backup and restore, the profiles in this mode.

The 12 rows: off by default; splice (empty / root-keys-only / tables); user root key never captured;
conflict stops naming the key; idempotent; edited region stops unless --force; Codex-style tables outside
the regions survive; --no-ide-default removes exactly the regions; --restore round-trip and
--force-config; no [hooks] in the profiles; re-trust of the region's hook keys; refusal without --yes.

Seeded-bug proofs: tests/mutations/install_sh.json and tests/mutations/*_e2e.json.
"""
# ruff: noqa: F401, F811  (fixtures imported by name, used as arguments)
from __future__ import annotations

import re
import tomllib

import pytest

from _installer_helpers import (BEGIN_A, BEGIN_B, END_A, END_B, Sandbox, _sandbox, fresh, installed, out,  # noqa: F401
                                tree_hash)

EVENTS = ("pre_tool_use", "permission_request", "post_tool_use", "subagent_start", "subagent_stop",
          "user_prompt_submit", "session_start", "session_end")
CODEX_TAIL = ('\n[hooks.state."/x/config.toml:pre_tool_use:0:0"]\ntrusted_hash = "sha256:%s"\n'
              '\n[projects."/work/proj"]\ntrust_level = "trusted"\n' % ("cd" * 32))
USER_FILES = {
    "empty": b"",
    "root_only": b'my_key = "v"\nother = [1, 2]\n',
    "tables": b'my_key = 1\n\n[mytable]\nz = 2\n\n[projects."/x"]\ntrust_level = "trusted"\n',
    "no_final_newline": b'my_key = 1\n[mytable]\nz = 2',
    "disjoint_subtable": b'[agents.mine]\ndescription = "mine"\n',   # merges into the stack's [agents]
}


def _spans(text: bytes):
    """(a_start, a_end, b_start, b_end): byte offsets of the two marked regions, markers included."""
    lines = text.splitlines(True)
    pos, got = 0, {}
    for ln in lines:
        s = ln.decode()
        for tag, key in ((BEGIN_A, "a0"), (BEGIN_B, "b0")):
            if s.startswith(tag):
                got[key] = pos
        for tag, key in ((END_A, "a1"), (END_B, "b1")):
            if s.startswith(tag):
                got[key] = pos + len(ln)
        pos += len(ln)
    return got["a0"], got["a1"], got["b0"], got["b1"]


def _outside(text: bytes) -> bytes:
    a0, a1, b0, b1 = _spans(text)
    return text[:a0] + text[a1:b0] + text[b1:]


def _stack_doc(text: bytes) -> dict:
    a0, a1, b0, b1 = _spans(text)
    return tomllib.loads((text[a0:a1] + text[b0:b1]).decode())


def _merge(user, stack):
    out_ = dict(user)
    for k, v in stack.items():
        if k in out_:
            assert isinstance(out_[k], dict) and isinstance(v, dict), "key defined on both sides: %s" % k
            out_[k] = _merge(out_[k], v)
        else:
            out_[k] = v
    return out_


def _seed(sbx, name):
    if USER_FILES.get(name) is not None:
        (sbx.ch / "config.toml").write_bytes(USER_FILES[name])


def _hook_handlers(doc):
    return sum(len(g["hooks"]) for groups in doc.get("hooks", {}).items() if groups[0] != "state" for g in groups[1])


@pytest.fixture(scope="module")
def _ide_ready(_sandbox):
    _sandbox.restore("fresh")
    _sandbox.run("--ide-default", "--yes", check=0)
    _sandbox.archive("ide")


@pytest.fixture
def ide(_sandbox, _ide_ready):
    """The scratch tree after `install.sh --ide-default --yes` on an absent config.toml."""
    _sandbox.restore("ide")
    return _sandbox


# 1 ---- off by default ----------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["absent", "root_only", "tables"])
def test_config_toml_is_untouched_without_the_flag(name, fresh):
    _seed(fresh, name)
    cfg = fresh.ch / "config.toml"
    before = cfg.read_bytes() if cfg.exists() else None
    fresh.run("--yes", check=0)
    assert (cfg.read_bytes() if cfg.exists() else None) == before
    assert fresh.manifest()["ide_default"] is False
    again = fresh.run("--yes", check=0)
    assert "Nothing to change" in again.stdout and (cfg.read_bytes() if cfg.exists() else None) == before


# 2 ---- splice ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["absent", "empty", "root_only", "tables", "no_final_newline",
                                  "disjoint_subtable"])
def test_splice_keeps_user_bytes_and_equals_the_merge(name, fresh):
    _seed(fresh, name)
    user = USER_FILES.get(name, b"")
    r = fresh.run("--ide-default", "--yes", check=0)
    assert "EVERY Codex session" in r.stdout
    got = fresh.config()
    a0, a1, b0, b1 = _spans(got)
    assert a0 == 0 and a1 <= b0 and got.count(BEGIN_A.encode()) == 1 and got.count(BEGIN_B.encode()) == 1
    assert got[b1:].strip() == b"", "region B is the last thing in the file"
    # the user's bytes outside the regions: unchanged (the splice may only add blank separator lines)
    outside = _outside(got)
    assert outside.replace(b"\n", b"") == user.replace(b"\n", b""), (outside, user)
    assert [ln for ln in outside.splitlines() if ln.strip()] == [ln for ln in user.splitlines() if ln.strip()]
    udoc = tomllib.loads(user.decode())
    assert tomllib.loads(got.decode()) == _merge(udoc, _stack_doc(got))
    # the manifest records the regions and the post-install hash
    m = fresh.manifest()
    assert m["ide_default"] is True and m["regions"]["A"] and m["regions"]["B"] and m["config_toml_sha256"]


def test_region_a_holds_root_keys_only_and_region_b_tables_only(fresh):
    _seed(fresh, "tables")
    fresh.run("--ide-default", "--yes", check=0)
    got = fresh.config()
    a0, a1, b0, b1 = _spans(got)
    a_doc = tomllib.loads(got[a0:a1].decode())
    assert a_doc and all(not isinstance(v, dict) for v in a_doc.values())
    assert {"model", "approval_policy", "default_permissions", "developer_instructions"} <= set(a_doc)
    assert not [ln for ln in got[a0:a1].decode().splitlines() if ln.startswith("[")]
    b_doc = tomllib.loads(got[b0:b1].decode())
    assert b_doc and all(isinstance(v, dict) for v in b_doc.values())
    assert {"features", "agents", "permissions", "hooks"} <= set(b_doc)


# 3 ---- a user root key is never captured by a region -----------------------------------------------------------
def test_user_root_keys_stay_at_the_root_outside_the_regions(fresh):
    _seed(fresh, "tables")
    fresh.run("--ide-default", "--yes", check=0)
    got = fresh.config()
    a0, a1, b0, b1 = _spans(got)
    doc = tomllib.loads(got.decode())
    assert doc["my_key"] == 1 and "my_key" not in doc["mytable"] and doc["mytable"] == {"z": 2}
    assert b"my_key" not in got[a0:a1] and b"my_key" not in got[b0:b1]
    first_table = got.index(b"[mytable]")
    assert a1 <= got.index(b"my_key") < first_table < b0    # still before the user's first table


# 4 ---- conflicts -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("user,named", [
    (b'model = "mine"\n', "model"),
    (b'approval_policy = "never"\n', "approval_policy"),
    (b'my_key = 1\n\n[features]\nx = true\n', "features"),
    (b'[agents]\nmax_threads = 2\n', "agents"),
])
def test_a_conflicting_user_key_or_table_stops_the_run_naming_it(user, named, fresh):
    (fresh.ch / "config.toml").write_bytes(user)
    before = fresh.fingerprint()
    r = fresh.run("--ide-default", "--yes")
    assert r.returncode != 0
    assert named in r.stderr and "defined both by you and by the stack" in r.stderr
    assert "Nothing was changed" in r.stderr
    assert fresh.fingerprint() == before and not fresh.backups() and not (fresh.ch / "stack").exists()


# 5 ---- idempotence -------------------------------------------------------------------------------------------------
def test_second_run_with_the_flag_changes_nothing(ide):
    before = ide.fingerprint()
    n = len(ide.backups())
    for _ in range(2):
        r = ide.run("--ide-default", "--yes", check=0)
        assert "Nothing to change" in r.stdout and "Backup:" not in r.stdout
        assert ide.fingerprint() == before and len(ide.backups()) == n
    assert "no changes" in ide.run("--ide-default", "--dry-run", check=0).stdout


@pytest.mark.xfail(strict=True, reason="BUG: a flagless re-run after `--ide-default` plans a manifest-only update "
                   "(options.ide_default_source flag -> kept, render.py options.json), so the second run is not "
                   "idempotent and writes a backup")
def test_flagless_rerun_after_ide_default_plans_nothing(ide):
    r = ide.run("--yes", check=0)
    assert "Nothing to change" in r.stdout


@pytest.mark.xfail(strict=True, reason="BUG: a flagless re-run after `--no-ide-default` plans a manifest-only update "
                   "(options.ide_default_source flag -> default), so it is not idempotent and writes a backup")
def test_flagless_rerun_after_no_ide_default_plans_nothing(ide):
    ide.run("--no-ide-default", "--yes", check=0)
    assert "Nothing to change" in ide.run("--yes", check=0).stdout


# 6 ---- an edited region ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("args", [("--ide-default", "--yes"), ("--yes",)])
def test_an_edited_region_stops_with_a_diff_unless_force(args, ide):
    cfg = ide.ch / "config.toml"
    good = cfg.read_bytes()
    cfg.write_bytes(good.replace(b'model = "gpt-6-luna"', b'model = "gpt-6-sol"', 1))
    edited = cfg.read_bytes()
    assert edited != good
    before = ide.fingerprint()
    r = ide.run(*args)
    assert r.returncode != 0
    assert "changed since the last install" in r.stderr and "--force" in r.stderr
    assert "--- config.toml region A (as found)" in r.stderr and '-model = "gpt-6-sol"' in r.stderr
    assert '+model = "gpt-6-luna"' in r.stderr
    assert ide.fingerprint() == before
    ok = ide.run(*args, "--force", check=0)
    assert "overwrote edited stack region" in out(ok)
    assert cfg.read_bytes() == good


def test_an_edit_inside_region_b_stops_too_and_an_edit_outside_does_not(ide):
    cfg = ide.ch / "config.toml"
    good = cfg.read_bytes()
    cfg.write_bytes(good.replace(b"[features]\n", b"[features]\nzzz = true\n", 1))
    r = ide.run("--yes")
    assert r.returncode != 0 and "region B" in r.stderr and "zzz = true" in r.stderr
    cfg.write_bytes(good + b"\n[mine]\nmy_after = 1\n")        # a table of the user's after the regions
    ide.run("--yes", check=0)
    got = cfg.read_bytes()
    assert tomllib.loads(got.decode())["mine"] == {"my_after": 1}
    assert b"[mine]\nmy_after = 1\n" in _outside(got) and got[_spans(got)[3]:].strip() == b""


# 7 ---- Codex-style writes outside the regions -----------------------------------------------------------------------
@pytest.mark.parametrize("args", [("--ide-default", "--yes"), ("--yes",)])
def test_codex_style_tables_outside_the_regions_survive_a_rerun(args, ide):
    cfg = ide.ch / "config.toml"
    cfg.write_bytes(cfg.read_bytes() + CODEX_TAIL.encode())
    tail_doc = tomllib.loads(CODEX_TAIL)
    ide.edit_repo("codex_config/lib/hook_defs.py", "TIMEOUT_S, SESSION_END_TIMEOUT_S = 10, 3",
                  "TIMEOUT_S, SESSION_END_TIMEOUT_S = 11, 3")
    r = ide.run(*args, check=0)
    assert "Backup:" in r.stdout            # the region really was rewritten
    got = ide.config()
    # the user's bytes survive outside the regions (region B is re-spliced at the very end of the file)
    assert _outside(got).replace(b"\n", b"") == CODEX_TAIL.encode().replace(b"\n", b"")
    doc = tomllib.loads(got.decode())
    assert doc["hooks"]["state"] == tail_doc["hooks"]["state"] and doc["projects"] == tail_doc["projects"]
    assert doc["hooks"]["PreToolUse"][0]["hooks"][0]["timeout"] == 11
    assert got[_spans(got)[3]:].strip() == b""


# 8 ---- --no-ide-default -----------------------------------------------------------------------------------------------
def test_no_ide_default_removes_exactly_the_regions(fresh):
    _seed(fresh, "tables")
    user = USER_FILES["tables"]
    fresh.run("--ide-default", "--yes", check=0)
    cfg = fresh.ch / "config.toml"
    spliced = cfg.read_bytes()
    cfg.write_bytes(spliced + CODEX_TAIL.encode())          # Codex wrote after the regions
    fresh.run("--no-ide-default", "--yes", check=0)
    got = cfg.read_bytes()
    assert BEGIN_A.encode() not in got and BEGIN_B.encode() not in got and b"claude-agent-stack" not in got
    assert got.replace(b"\n", b"") == (user + CODEX_TAIL.encode()).replace(b"\n", b"")
    assert got.startswith(b"my_key = 1\n")
    m = fresh.manifest()
    assert m["ide_default"] is False and m["regions"] == {"A": None, "B": None}
    # the full profiles are back, with their hooks
    for name in ("codex.config.toml", "codex-astra.config.toml"):
        doc = tomllib.loads((fresh.ch / name).read_text())
        assert len(doc["hooks"]) >= 8 and "agents" in doc, name
    assert not (b"claude-agent-stack" in (fresh.ch / "config.toml").read_bytes())    # and the mode stays off
    fresh.run("--yes", check=0)
    assert fresh.manifest()["ide_default"] is False and b"claude-agent-stack" not in cfg.read_bytes()


def test_no_ide_default_on_an_absent_config_leaves_it_absent(fresh):
    fresh.run("--no-ide-default", "--yes", check=0)
    assert not (fresh.ch / "config.toml").exists()


# 9 ---- --restore -----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["absent", "root_only", "tables"])
def test_restore_of_an_unchanged_config_round_trips(name, fresh):
    _seed(fresh, name)
    cfg = fresh.ch / "config.toml"
    before = cfg.read_bytes() if cfg.exists() else None
    fresh.run("--ide-default", "--yes", check=0)
    assert cfg.read_bytes() != before
    fresh.run("--restore", "latest", "--yes", check=0)
    assert (cfg.read_bytes() if cfg.exists() else None) == before


def test_restore_of_a_changed_config_needs_force_config_not_force(fresh):
    _seed(fresh, "tables")
    fresh.run("--ide-default", "--yes", check=0)
    cfg = fresh.ch / "config.toml"
    cfg.write_bytes(cfg.read_bytes() + CODEX_TAIL.encode())
    before = fresh.fingerprint()
    for extra in ((), ("--force",)):
        r = fresh.run("--restore", "latest", "--yes", *extra)
        assert r.returncode != 0 and "--force-config" in r.stderr and "--no-ide-default" in r.stderr, extra
        assert fresh.fingerprint() == before, extra
    fresh.run("--restore", "latest", "--yes", "--force-config", check=0)
    assert cfg.read_bytes() == USER_FILES["tables"]


# 10 --- no profile carries [hooks] -------------------------------------------------------------------------------------------
def test_no_profile_carries_hooks_in_this_mode_so_each_hook_runs_once(ide):
    cfg = tomllib.loads(ide.config().decode())
    assert sorted(cfg["hooks"]) == ["PermissionRequest", "PostToolUse", "PreToolUse", "SessionEnd", "SessionStart",
                                    "SubagentStart", "SubagentStop", "UserPromptSubmit"]
    total = _hook_handlers(cfg)
    for name in ("codex.config.toml", "codex-astra.config.toml"):
        doc = tomllib.loads((ide.ch / name).read_text())
        assert set(doc.get("hooks", {})) <= {"state"}, name
        total += _hook_handlers(doc)
    assert total == 8


def test_without_the_flag_the_profiles_carry_the_hooks_and_config_toml_none(installed):
    for name in ("codex.config.toml", "codex-astra.config.toml"):
        assert _hook_handlers(tomllib.loads((installed.ch / name).read_text())) == 8, name
    assert not (installed.ch / "config.toml").exists()


# 11 --- re-trust ------------------------------------------------------------------------------------------------------------------
def test_re_trust_is_reported_for_the_regions_hook_keys(fresh):
    r = fresh.run("--ide-default", "--yes", check=0)
    m = re.search(r"re-trust (\d+) hook\(s\) in /hooks:\n((?:      .*\n)+)", r.stdout)
    assert m and int(m.group(1)) == 8
    assert m.group(2).split() == ["%s/config.toml:%s:0:0" % (fresh.ch, e) for e in EVENTS]
    assert "source is config.toml" in r.stdout


def test_a_changed_hook_definition_is_re_trusted_under_the_regions_keys(ide):
    assert "no hook definition changed" in ide.run("--ide-default", "--dry-run", check=0).stdout
    ide.edit_repo("codex_config/lib/hook_defs.py", "TIMEOUT_S, SESSION_END_TIMEOUT_S = 10, 3",
                  "TIMEOUT_S, SESSION_END_TIMEOUT_S = 11, 3")
    r = ide.run("--ide-default", "--yes", check=0)
    keys = re.search(r"re-trust: re-trust (\d+) hook\(s\) in /hooks:\n((?:      .*\n)+)", r.stdout).group(2).split()
    assert keys == ["%s/config.toml:%s:0:0" % (ide.ch, e) for e in EVENTS if e != "session_end"]


# 12 --- confirmation ---------------------------------------------------------------------------------------------------------------
def test_ide_default_without_yes_and_without_a_terminal_is_refused(fresh):
    before = fresh.fingerprint()
    r = fresh.run("--ide-default")
    assert r.returncode != 0
    assert "EVERY Codex session" in r.stdout and "no terminal to ask" in r.stderr and "--yes" in r.stderr
    assert "Nothing in" in r.stderr and "was changed" in r.stderr
    assert fresh.fingerprint() == before and not (fresh.ch / "config.toml").exists()


def test_ide_default_with_no_prompt_is_refused_unless_yes(fresh):
    before = fresh.fingerprint()
    r = fresh.run("--ide-default", "--no-prompt")
    assert r.returncode != 0 and "--no-prompt forbids asking" in r.stderr
    assert fresh.fingerprint() == before
    fresh.run("--ide-default", "--no-prompt", "--yes", check=0)
    assert BEGIN_A.encode() in fresh.config()


def test_a_typed_answer_is_not_a_terminal_so_stdin_cannot_approve(fresh):
    r = fresh.run("--ide-default", stdin="y\n")
    assert r.returncode != 0 and not (fresh.ch / "config.toml").exists()


def test_ide_default_dry_run_needs_no_answer_and_writes_nothing(fresh):
    _seed(fresh, "tables")
    before = fresh.fingerprint()
    r = fresh.run("--ide-default", "--dry-run", check=0)
    assert "Dry run done" in r.stdout and fresh.fingerprint() == before
    d = fresh.run("--ide-default", "--diff", check=0)
    assert "config.toml" in d.stdout and fresh.fingerprint() == before
