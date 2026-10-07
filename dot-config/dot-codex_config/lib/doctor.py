"""doctor: is the installed stack active? Read-only report on a CODEX_HOME (DESIGN.md §4.4, §4.5 item 0).

    doctor.py --codex-home CH [--home H]

Stdlib only, Python >= 3.11 (tomllib). Reads CH/.stack-manifest.json and never writes anything.

- Hook trust. For every stack hook key in the manifest's `hooks` (`<file>:<event>:<group>:<handler>`)
  it looks for a trust record in the `[hooks.state]` tables of config.toml and of the profile files
  (`<profile>.config.toml`, `<profile>-astra.config.toml`, profile = the manifest's profile_name).
  A record is the vendored config.schema.json HookStateToml: `{enabled?: bool, trusted_hash?: str}`.
  A key is trusted when some file holds a record with a non-empty trusted_hash and no file
  disables it (`enabled = false`); otherwise it is untrusted (no record, no hash, or disabled).
  UNVERIFIED (U1): which file Codex's /hooks writes the record into, hence all three are read.
  UNVERIFIED: whether the recorded trusted_hash still matches the current definition. It is
  Codex's own hash (the installer never computes it, §4.4), so a definition changed since the trust
  shows here as trusted and in /hooks as "Modified"; the installer's "re-trust N hooks" line
  (codex_state.py retrust) is the signal for that case.
- Hash drift. Every file the manifest records (`files`: sha256 per owned file and stack/ file) is
  hashed again, never through a link; a changed, missing or linked file is drift. One exception: a
  profile file whose TOML without [hooks.state] still has the digest render.py recorded (options
  `profile_digests`, semantic_digest) changed only in Codex's trust records (U1): a note, not
  drift. Under --ide-default the two config.toml regions are compared with the manifest's
  `regions` the same way.
- Skill links. Each manifest link in the skills root: ok, missing, retargeted (a link elsewhere) or
  foreign (not a link). Reported only; links never change the exit code.

Exit 0 when every stack hook key is trusted and nothing drifted; 1 otherwise (or no manifest, or a
file that cannot be read); 2 usage. --home H (default $HOME) is the base of the default skills root
when the manifest's links carry none.

Seeded-bug proofs (tests/mutations/doctor.json; each turns tests/test_doctor.py red): a key without a
trust record counted as trusted; a record with enabled = false counted as trusted; file drift
ignored; region drift ignored; the profile files not read for trust records; Codex's own trust
writes counted as profile drift.

Probe line for probes/ (not edited here):
  P2/U1: trust the 8 hooks in `codex --profile codex` -> /hooks, then
  `grep -n 'hooks.state' $CODEX_HOME/config.toml $CODEX_HOME/codex.config.toml` shows which file
  holds `[hooks.state."<CODEX_HOME>/codex.config.toml:pre_tool_use:0:0"] trusted_hash = ...`.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import stat
import sys
import tomllib

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name):
    path = os.path.join(_HERE, name + ".py")
    spec = importlib.util.spec_from_file_location("codex_config_%s_for_doctor" % name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


config_region = _load("config_region")
skill_links = _load("skill_links")


class DoctorError(Exception):
    """The install cannot be checked (no manifest, unreadable file): exit 1."""


def _read(path):
    """bytes of a regular file (never through a link), None when missing; "link" for a symlink."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    except OSError:
        if os.path.islink(path):
            return "link"
        raise
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            return "other"
        return f.read()


def load_manifest(ch):
    try:
        data = _read(os.path.join(ch, ".stack-manifest.json"))
    except OSError as exc:
        raise DoctorError("cannot read the manifest: %s" % exc.strerror) from None
    if not isinstance(data, bytes):
        raise DoctorError("%s has no stack install (no .stack-manifest.json)" % ch)
    try:
        m = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise DoctorError(".stack-manifest.json is not valid JSON: %s" % exc) from None
    if not isinstance(m, dict) or m.get("installer") != "codex_config":
        raise DoctorError(".stack-manifest.json is not a codex_config manifest")
    return m


def trust_sources(ch, manifest):
    name = manifest.get("profile_name") if isinstance(manifest.get("profile_name"), str) else "codex"
    return ["config.toml", name + ".config.toml", name + "-astra.config.toml"]


def trust_records(ch, rels):
    """({key: [(rel, record)]}, problems) from the [hooks.state] tables of the given files."""
    found, problems = {}, []
    for rel in rels:
        p = os.path.join(ch, rel)
        try:
            if os.path.islink(p):                      # Codex reads a linked config file too
                with open(p, "rb") as f:
                    data = f.read()
            else:
                data = _read(p)
        except OSError as exc:
            problems.append("%s: unreadable (%s)" % (rel, exc.strerror))
            continue
        if data is None:
            continue
        if not isinstance(data, bytes):
            problems.append("%s: not a regular file" % rel)
            continue
        try:
            doc = tomllib.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            problems.append("%s: does not parse as TOML (%s)" % (rel, exc))
            continue
        state = (doc.get("hooks") or {}).get("state") if isinstance(doc.get("hooks"), dict) else None
        if not isinstance(state, dict):
            continue
        for key, rec in state.items():
            if isinstance(rec, dict):
                found.setdefault(key, []).append((rel, rec))
    return found, problems


def hook_status(records):
    """trusted | disabled | no trusted_hash | no record."""
    if not records:
        return "no record"
    if any(rec.get("enabled") is False for _, rec in records):
        return "disabled"
    if any(isinstance(rec.get("trusted_hash"), str) and rec["trusted_hash"] for _, rec in records):
        return "trusted"
    return "no trusted_hash"


def check_hooks(ch, manifest):
    hooks = manifest.get("hooks")
    if not isinstance(hooks, list):
        raise DoctorError(".stack-manifest.json has no hooks list")
    found, problems = trust_records(ch, trust_sources(ch, manifest))
    rows = []
    for h in hooks:
        if not (isinstance(h, dict) and isinstance(h.get("key"), str)):
            problems.append("manifest: a hooks entry without a key")
            continue
        recs = found.get(h["key"], [])
        rows.append({"key": h["key"], "status": hook_status(recs), "files": [r for r, _ in recs]})
    return rows, problems


def semantic_digest(doc: dict) -> str:
    """sha256 of a profile document without its [hooks.state] (canonical JSON). render.py records it
    per profile file (options.json `profile_digests`, kept in the manifest's options), so a file
    whose only change is Codex's own trust records (U1) is not drift."""
    doc = dict(doc)
    hooks = doc.get("hooks")
    if isinstance(hooks, dict) and "state" in hooks:
        hooks = {k: v for k, v in hooks.items() if k != "state"}
        if hooks:
            doc["hooks"] = hooks
        else:
            del doc["hooks"]
    blob = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(blob.encode("ascii")).hexdigest()


def _only_trust_changed(data, digest):
    try:
        return semantic_digest(tomllib.loads(data.decode("utf-8"))) == digest
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        return False


def check_drift(ch, manifest):
    """(drift lines, notes): a recorded file changed, missing or linked; a region changed."""
    out, notes = [], []
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise DoctorError(".stack-manifest.json has no files table")
    options = manifest.get("options") if isinstance(manifest.get("options"), dict) else {}
    digests = options.get("profile_digests") if isinstance(options.get("profile_digests"), dict) else {}
    for rel in sorted(files):
        if not isinstance(rel, str) or rel.startswith("/") or ".." in rel.split("/"):
            out.append("%r: not a path inside CODEX_HOME" % (rel,))
            continue
        try:
            data = _read(os.path.join(ch, rel))
        except OSError as exc:
            out.append("%s: unreadable (%s)" % (rel, exc.strerror))
            continue
        if data is None:
            out.append("%s: missing" % rel)
        elif not isinstance(data, bytes):
            out.append("%s: not a regular file" % rel)
        elif hashlib.sha256(data).hexdigest() != files[rel]:
            if rel in digests and _only_trust_changed(data, digests[rel]):
                notes.append("%s: changed only in [hooks.state] (Codex's trust records)" % rel)
            else:
                out.append("%s: changed since the install" % rel)
    regions = manifest.get("regions")
    if manifest.get("ide_default") and isinstance(regions, dict):
        cfg = os.path.join(ch, "config.toml")
        data = _read(cfg)
        if not isinstance(data, bytes):
            out.append("config.toml: %s (the --ide-default regions are gone)" % (data or "missing"))
        else:
            try:
                now = config_region.region_sha(data)
            except config_region.RegionError as exc:
                out.append("config.toml: %s" % exc)
                now = {}
            for r in config_region.REGIONS:
                if r in now and now[r] != regions.get(r):
                    out.append("config.toml region %s: %s" % (
                        r, "missing" if now[r] is None else "changed since the install"))
    return out, notes


def check_links(manifest, home):
    links = manifest.get("links")
    if not isinstance(links, dict):
        return []
    root = links.get("root") if "links" in links else os.path.join(home, ".agents", "skills")
    table = links.get("links") if "links" in links else links
    if not root or not isinstance(table, dict) or not table:
        return []
    rows = []
    try:
        fd = skill_links.open_root(root)
    except skill_links.LinkError as exc:
        return [{"name": "*", "status": "root refused: %s" % exc}]
    try:
        for name in sorted(table):
            cur = skill_links.state(fd, name)
            if cur["type"] == "missing":
                status = "missing"
            elif cur["type"] != "link":
                status = "foreign (not a link)"
            elif cur["target"] == table[name]:
                status = "ok"
            else:
                status = "retargeted to %s" % cur["target"]
            rows.append({"name": name, "status": status})
    finally:
        if fd is not None:
            os.close(fd)
    return rows


def doctor(ch, home, out=sys.stdout) -> int:
    manifest = load_manifest(ch)
    hooks, problems = check_hooks(ch, manifest)
    drift, notes = check_drift(ch, manifest)
    links = check_links(manifest, home)
    bad = [h for h in hooks if h["status"] != "trusted"]
    out.write("hooks: %d of %d stack hook keys trusted\n" % (len(hooks) - len(bad), len(hooks)))
    for h in bad:
        out.write("  ! untrusted (%s): %s\n" % (h["status"], h["key"]))
    for p in problems:
        out.write("  ! %s\n" % p)
    out.write("files: %s\n" % ("no drift" if not drift else "%d drifted" % len(drift)))
    for d in drift:
        out.write("  ! %s\n" % d)
    for n in notes:
        out.write("  - %s\n" % n)
    off = [x for x in links if x["status"] != "ok"]
    out.write("skill links: %d of %d ok\n" % (len(links) - len(off), len(links)))
    for x in off:
        out.write("  - %s: %s\n" % (x["name"], x["status"]))
    if bad:
        out.write("The guard is INACTIVE until you trust its hooks: run `codex --profile %s` (or plain "
                  "`codex` for config.toml keys), then /hooks.\n" % (manifest.get("profile_name") or "codex"))
    return 1 if bad or drift or problems else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="doctor.py", description="Check the installed stack (read-only).")
    p.add_argument("--codex-home", required=True)
    p.add_argument("--home")
    try:
        a = p.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    home = a.home or os.environ.get("HOME") or os.path.expanduser("~")
    if not os.path.isabs(a.codex_home) or not os.path.isabs(home):
        sys.stderr.write("doctor.py: --codex-home and --home must be absolute paths\n")
        return 2
    try:
        return doctor(os.path.normpath(a.codex_home), os.path.normpath(home))
    except DoctorError as exc:
        sys.stderr.write("doctor.py: %s\n" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
