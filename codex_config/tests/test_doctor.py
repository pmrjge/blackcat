"""lib/doctor.py: hook trust, hash drift and skill links of an installed CODEX_HOME (read-only).

The end-to-end cases render a scratch stage and write its manifest (the stage then is the
CODEX_HOME an apply produces); the edge cases use small hand-made fixtures. Trust records follow the
vendored config.schema.json HookStateToml ({enabled?, trusted_hash?}).
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil

import pytest

from _render_helpers import Env, config_region, doctor, hook_defs, snapshot
from conftest import load_lib

toml_emit = load_lib("toml_emit")
HASH = "sha256:" + "c" * 64


def run(ch, home=None):
    out = io.StringIO()
    rc = doctor.doctor(str(ch), str(home or ch), out=out)
    return rc, out.getvalue()


def append_trust(path, keys, **rec):
    rec = rec or {"trusted_hash": HASH, "enabled": True}
    with open(path, "a") as f:
        f.write("\n" + toml_emit.dumps({"hooks": {"state": {k: dict(rec) for k in keys}}}))


@pytest.fixture(scope="module")
def installed():
    env = Env()
    env.new_stage()
    env.ok()
    env.manifest()
    return env


def keys_of(env, rel):
    return [h["key"] for h in json.loads((env.stage / ".stack-manifest.json").read_text())["hooks"]
            if h["source"].endswith("/" + rel)]


def test_fresh_install_is_untrusted(installed):
    rc, out = run(installed.stage, installed.home)
    assert rc == 1
    assert "0 of 16 stack hook keys trusted" in out and "untrusted (no record)" in out
    assert "files: no drift" in out and "INACTIVE" in out
    assert "skill links: 0 of 127 ok" in out          # nothing applied the links in this fixture


def test_trusted_in_the_profile_files_and_codex_trust_writes_are_not_drift(installed, tmp_path):
    ch = tmp_path / "ch"
    shutil.copytree(installed.stage, ch, symlinks=True)
    before = snapshot(ch)
    for rel in ("codex.config.toml", "codex-astra.config.toml"):
        append_trust(ch / rel, keys_of(installed, rel))
    rc, out = run(ch, installed.home)
    assert rc == 0, out
    assert "16 of 16 stack hook keys trusted" in out and "files: no drift" in out
    assert "changed only in [hooks.state]" in out
    # one key disabled -> untrusted again
    append_trust(ch / "config.toml", keys_of(installed, "codex.config.toml")[:1], enabled=False)
    rc, out = run(ch, installed.home)
    assert rc == 1 and "untrusted (disabled)" in out
    # doctor never writes
    after = snapshot(ch)
    assert {k for k in before if after.get(k) != before[k]} == {"codex.config.toml", "codex-astra.config.toml"}


def test_drift_of_a_stack_file_and_of_the_profile(installed, tmp_path):
    ch = tmp_path / "ch"
    shutil.copytree(installed.stage, ch, symlinks=True)
    for rel in ("codex.config.toml", "codex-astra.config.toml"):
        append_trust(ch / rel, keys_of(installed, rel))
    assert run(ch)[0] == 0
    guard = ch / "stack" / "hooks" / "codex_guard.py"
    guard.write_bytes(guard.read_bytes() + b"\n# edited\n")
    rc, out = run(ch)
    assert rc == 1 and "stack/hooks/codex_guard.py: changed since the install" in out
    guard.unlink()
    rc, out = run(ch)
    assert rc == 1 and "stack/hooks/codex_guard.py: missing" in out


def test_profile_change_outside_the_trust_records_is_drift(installed, tmp_path):
    ch = tmp_path / "ch"
    shutil.copytree(installed.stage, ch, symlinks=True)
    p = ch / "codex.config.toml"
    p.write_text(p.read_text().replace('approval_policy = "on-request"', 'approval_policy = "never"', 1))
    rc, out = run(ch)
    assert rc == 1 and "codex.config.toml: changed since the install" in out


# ------------------------------------------------------------------------------------- hand fixtures
def make_ch(tmp_path, *, ide=False, profile_trust=None, config_trust=None, files=None, links=None):
    ch = tmp_path / "ch"
    ch.mkdir()
    src = str(ch) + ("/config.toml" if ide else "/codex.config.toml")
    hooks = [dict(k, source=src) for k in hook_defs.hook_keys(src, hook_defs.hooks_table(str(ch) + "/stack/bin/codex-hook"))]
    prof = "# profile\n" + (toml_emit.dumps({"hooks": {"state": profile_trust}}) if profile_trust else "")
    (ch / "codex.config.toml").write_text(prof)
    cfg = ""
    if ide:
        cfg = (config_region.BEGIN_A + '\nmodel = "m"\n' + config_region.END_A + "\n"
               + config_region.BEGIN_B + "\n[features]\nhooks = true\n" + config_region.END_B + "\n")
    if config_trust:
        cfg += toml_emit.dumps({"hooks": {"state": config_trust}})
    if cfg:
        (ch / "config.toml").write_text(cfg)
    rec = {"codex.config.toml": hashlib.sha256((ch / "codex.config.toml").read_bytes()).hexdigest()}
    rec.update(files or {})
    regions = config_region.region_sha((ch / "config.toml").read_bytes()) if ide else {"A": None, "B": None}
    m = {"format": 1, "installer": "codex_config", "commit": "x", "files": rec, "hooks": hooks,
         "links": links or {"root": None, "links": {}}, "ide_default": ide, "regions": regions,
         "profile_name": "codex", "astra": False, "options": {}}
    (ch / ".stack-manifest.json").write_text(json.dumps(m))
    return ch, [h["key"] for h in hooks]


def all_trusted(tmp_path, ide=False):
    src = str(tmp_path / "ch") + ("/config.toml" if ide else "/codex.config.toml")
    table = hook_defs.hooks_table(str(tmp_path / "ch") + "/stack/bin/codex-hook")
    return {k["key"]: {"trusted_hash": HASH} for k in hook_defs.hook_keys(src, table)}


def test_trust_found_in_config_toml(tmp_path):
    """U1 is unverified: a record Codex wrote into config.toml counts as much as one in the profile."""
    ch, _ = make_ch(tmp_path, config_trust=all_trusted(tmp_path))
    rc, out = run(ch)
    assert rc == 0 and "8 of 8 stack hook keys trusted" in out


def test_ide_default_keys_trusted_in_config_toml_and_region_drift(tmp_path):
    ch, _ = make_ch(tmp_path, ide=True, config_trust=all_trusted(tmp_path, ide=True))
    rc, out = run(ch)
    assert rc == 0, out
    data = (ch / "config.toml").read_bytes().replace(b'model = "m"', b'model = "n"')
    (ch / "config.toml").write_bytes(data)
    rc, out = run(ch)
    assert rc == 1 and "config.toml region A: changed since the install" in out


@pytest.mark.parametrize("rec,status", [
    (None, "no record"),
    ({"enabled": True}, "no trusted_hash"),
    ({"trusted_hash": ""}, "no trusted_hash"),
    ({"trusted_hash": HASH, "enabled": False}, "disabled"),
])
def test_untrusted_key_fails(tmp_path, rec, status):
    trust = all_trusted(tmp_path)
    first = next(iter(trust))
    if rec is None:
        del trust[first]
    else:
        trust[first] = rec
    ch, _ = make_ch(tmp_path, profile_trust=trust)
    rc, out = run(ch)
    assert rc == 1 and "untrusted (%s): %s" % (status, first) in out
    assert "7 of 8" in out


def test_links_reported_without_changing_the_exit_code(tmp_path):
    root = tmp_path / "skills"
    root.mkdir()
    stack = str(tmp_path / "ch") + "/stack/skills/"
    (root / "ok").symlink_to(stack + "ok")
    (root / "moved").symlink_to("/elsewhere/moved")
    (root / "mine").mkdir()
    links = {"root": str(root), "links": {n: stack + n for n in ("ok", "moved", "mine", "gone")}}
    ch, _ = make_ch(tmp_path, profile_trust=None, config_trust=all_trusted(tmp_path), links=links)
    rc, out = run(ch)
    assert rc == 0, out
    assert "skill links: 1 of 4 ok" in out
    assert "moved: retargeted to /elsewhere/moved" in out and "mine: foreign (not a link)" in out
    assert "gone: missing" in out


def test_no_manifest_and_usage(tmp_path, capsys):
    assert doctor.main(["--codex-home", str(tmp_path)]) == 1
    assert "no stack install" in capsys.readouterr().err
    assert doctor.main([]) == 2
    assert doctor.main(["--codex-home", "relative"]) == 2


def test_unparsable_trust_file_fails(tmp_path):
    ch, _ = make_ch(tmp_path, config_trust=all_trusted(tmp_path))
    with open(ch / "config.toml", "a") as f:
        f.write("[[[ not toml\n")
    rc, out = run(ch)
    assert rc == 1 and "config.toml: does not parse as TOML" in out


def test_cli_is_read_only(tmp_path, capsys):
    ch, _ = make_ch(tmp_path, config_trust=all_trusted(tmp_path))
    before = snapshot(ch)
    st = {p: os.stat(ch / p).st_mtime_ns for p in before}
    assert doctor.main(["--codex-home", str(ch), "--home", str(tmp_path)]) == 0
    assert snapshot(ch) == before and {p: os.stat(ch / p).st_mtime_ns for p in before} == st
