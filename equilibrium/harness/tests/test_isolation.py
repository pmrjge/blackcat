"""Isolation backend (ISOLATION.md §3; user decision 2026-10-05: Apple `container` 1.5.0, replacing Docker). The
backend is exercised with a FAKE `container` CLI (tests/fake_container, byte-identical to the repo's
tests/fake-container/container) that records argv and runs the command on the host with container paths mapped back;
the real services are never contacted and no real claude is called. Every shape the fake gives the real CLI beyond
the user's `container run --help` output is [unverified] (eq_harness.py, the comment above ISOLATION_BACKENDS)."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from test_eqsec_proofs import item_, pool_

import eq_harness as eh
import eq_mediator as md
from conftest import FIXT_FLAGS, ITEMS, container_dir, ledger, run_harness, stub_env

FAKE = Path(__file__).resolve().parent / "fake_container"
DIGEST = "sha256:" + "0" * 64  # the fake's default `image inspect` digest
OTHER = "sha256:" + "2" * 64
TAG = "eq.invalid/eq-lean:4.34.1-arm64"
IMG = f"{TAG}@{DIGEST}"
CTMP = eh.CTR_TMP  # the container's /tmp (a tmpfs), not the host's
# options of `container run` the user's `--help` (1.5.0) output lists (HANDOFF_STATE §7), plus -e/--label/-i, which
# lib/eq-container/lib.sh's comment says the help lists too [unverified: not in the excerpt relayed to the agents]
HELP_VERIFIED = {"--rm", "--read-only", "--cap-drop", "--init", "--user", "-m", "-c", "--ulimit", "--tmpfs", "--mount",
                 "-w", "--name", "--network"}
HELP_PER_LIB_SH = {"-e", "--label", "-i"}
BARE = ("--rm", "--read-only", "--init", "-i")


def dflags(**over: Any) -> dict[str, Any]:
    f = eh.load_flags(None)
    f.update(isolation="container", container_bin=str(FAKE), container_images={"PF": IMG, "CP": IMG, "CR": IMG})
    f.update(over)
    return f


def calls(log: Path) -> list[list[str]]:
    return [ln.split("\x1f") for ln in log.read_text().splitlines()] if log.exists() else []


def opts(argv: list[str]) -> tuple[dict[str, list[str]], set[str], str, list[str]]:
    """Split a `container run` argv: options with values, bare flags, the image, the container argv."""
    assert argv[1] == "run"
    vals: dict[str, list[str]] = {}
    bare: set[str] = set()
    i = 2
    while argv[i].startswith("-"):
        if argv[i] in BARE:
            bare.add(argv[i])
            i += 1
        else:
            vals.setdefault(argv[i], []).append(argv[i + 1])
            i += 2
    return vals, bare, argv[i], argv[i + 1:]


def mounts(vals: dict[str, list[str]]) -> dict[str, tuple[str, bool]]:
    """--mount entries as {target: (source, readonly)}; every one must be a bind."""
    out: dict[str, tuple[str, bool]] = {}
    for m in vals.get("--mount", []):
        kv = dict(p.partition("=")[::2] for p in m.split(","))
        assert kv["type"] == "bind"
        out[kv["target"]] = (kv["source"], "readonly" in kv)
    return out


def user_argv(inner: list[str]) -> list[str]:
    """The container argv without the copy-in prefix (`/bin/sh -c COPY_IN eq-run SRC DST ... -- ARGV`)."""
    if inner[:3] == ["/bin/sh", "-c", eh.COPY_IN]:
        return inner[inner.index("--") + 1:]
    return inner


def eqv1(call: eh.IsoCall, obj: dict[str, Any]) -> str:
    """The authenticated verdict line an EQV1 oracle prints, with the nonce the harness wrote on stdin."""
    assert call.stdin is not None
    return f"EQV1 {call.stdin.decode().strip()} {json.dumps(obj)}\n"


def iso_(tmp: Path, **over: Any) -> eh.Isolation:
    return eh.Isolation(dflags(**over), tmp / "eq", tmp / "pool")


# --- the container argv ---------------------------------------------------------------------------------------------
def test_container_argv_has_every_required_flag_and_only_two_mounts(tmp_path: Path) -> None:
    work, fx = tmp_path / "copy", tmp_path / "pool" / "fx"
    work.mkdir()
    fx.mkdir(parents=True)
    call = iso_(tmp_path).isolate(["bash", "check_lean.sh", "Answer.lean"], cls="PF", rw_dirs={"/work": work},
                                  ro_dirs={"/fixture": fx}, workdir="/work", tmp=tmp_path, arm="PF-0001.p3",
                                  env_extra={"EQ_LEAN_TOTAL": "540"})
    vals, bare, image, inner = opts(call.argv)
    assert call.argv[0] == str(FAKE) and image == TAG and user_argv(inner) == ["bash", "check_lean.sh", "Answer.lean"]
    assert call.image == IMG  # the pinned ref travels with the call: run() checks its digest
    assert bare == {"--rm", "--read-only", "--init"} and call.stdin is None  # no -i: stdin is /dev/null
    assert vals["--network"] == ["none"] and vals["--cap-drop"] == ["ALL"]
    assert vals["-m"] == ["8G"] and vals["-c"] == ["2"] and vals["--ulimit"] == ["nproc=512"]
    assert vals["--user"] == ["10001:10001"]  # the image's USER (lib/eq-container/lib.sh EQ_USER)
    assert vals["--tmpfs"][0] == f"{CTMP}:size=2G,mode=1777" and vals["-w"] == ["/work"]
    assert mounts(vals) == {"/eqsrc/work": (str(work.resolve()), True), "/fixture": (str(fx.resolve()), True)}
    assert "-v" not in vals  # every bind is a --mount, and every one is read-only
    assert re.fullmatch(r"eq-[0-9a-f]{32}", vals["--name"][0]) and call.name == vals["--name"][0]
    labels = dict(lb.split("=", 1) for lb in vals["--label"])
    assert labels.keys() == {"eq-harness", "eq-inv", "eq-started", "eq-arm"} and labels["eq-arm"] == "PF-0001.p3"
    assert all("=" in e for e in vals["-e"])  # `-e KEY` alone would inherit KEY from the host
    env = dict(e.split("=", 1) for e in vals["-e"])
    assert env["EQ_LEAN_TOTAL"] == "540" and env["HOME"] == CTMP and env["TMPDIR"] == CTMP
    joined = "\n".join(call.argv)
    assert "docker.sock" not in joined and str(Path.home()) + ":" not in joined
    assert "PATH" not in env and "EQ_ANSWER" not in env  # nothing of the host environment enters the container


def _call(tmp_path: Path, **kw: Any) -> eh.IsoCall:
    work = tmp_path / "copy"
    work.mkdir(exist_ok=True)
    return iso_(tmp_path, **kw).isolate(["true"], cls="PF", rw_dirs={"/work": work}, ro_dirs={}, workdir="/work",
                                        tmp=tmp_path)


def test_only_options_the_container_help_lists(tmp_path: Path) -> None:
    """1.5.0 has no --pids-limit, --security-opt, --memory-swap, --pull, --stop-timeout or log options; every option
    the harness passes is one `container run --help` lists (the fake refuses any other with rc 2)."""
    work = tmp_path / "copy"
    work.mkdir()
    call = iso_(tmp_path).isolate(["true"], cls="PF", rw_dirs={"/work": work}, ro_dirs={"/fixture": work},
                                  workdir="/work", tmp=tmp_path, arm="a", stdin=b"x")
    vals, bare, _, _ = opts(call.argv)
    assert set(vals) | bare <= HELP_VERIFIED | HELP_PER_LIB_SH
    for gone in ("--pids-limit", "--security-opt", "--memory-swap", "--pull", "--stop-timeout", "--log-driver",
                 "--log-opt", "-v", "--memory", "--cpus"):
        assert gone not in vals


def test_argv_agrees_with_lib_sh(tmp_path: Path) -> None:
    """Both sides build one argv: lib/eq-container/lib.sh eq_base_flags (probe.sh, eq_run) and isolate(); the copy-in
    script and the digest paths are byte-equal; the fake CLI is the repo's."""
    d = container_dir()
    if d is None:
        pytest.skip("lib/eq-container not found (set EQ_CONTAINER_DIR=<repo>/lib/eq-container)")
    env = dict(os.environ, EQ_NO_STATE_WRITE="1", EQ_STATE_DIR=str(tmp_path / "st"), EQ_CONTAINER_BIN=str(FAKE))
    for k in ("EQ_USER", "EQ_CPUS", "EQ_MEMORY", "EQ_NPROC", "EQ_TMP_SIZE", "EQ_WORK_SIZE", "EQ_RUN_MEMORY",
              "EQ_RUN_NPROC"):
        env.pop(k, None)
    cp = subprocess.run(["bash", "-c", 'source "$1" && printf "%s\\0" "${EQ_BASE_FLAGS[@]}" && printf "\\0\\0%s\\0%s" '
                         '"$EQ_COPY_IN" "$EQ_WORK_SIZE"', "x", str(d / "lib.sh")],
                        env=env, capture_output=True, text=True, check=False)
    assert cp.returncode == 0, cp.stderr
    flags_part, _, rest = cp.stdout.partition("\0\0\0")
    copy_in, _, work_size = rest.partition("\0")
    lib = ["container", "run", *flags_part.split("\0"), "IMAGE"]
    lvals, lbare, _, _ = opts(lib)
    work = tmp_path / "copy"
    work.mkdir()
    hvals, hbare, _, _ = opts(iso_(tmp_path).isolate(["true"], cls="PF", rw_dirs={"/work": work}, ro_dirs={},
                                                     workdir="/work", tmp=tmp_path).argv)
    assert lbare == hbare == {"--rm", "--read-only", "--init"}
    for k in ("--network", "--cap-drop", "-m", "-c", "--ulimit", "--user", "-w"):
        assert lvals[k] == hvals[k], k
    assert lvals["--tmpfs"] == [hvals["--tmpfs"][0]]  # /tmp
    assert f"/work:size={work_size},mode=1777" in hvals["--tmpfs"]  # eq_run's /work tmpfs
    assert sorted(lvals["-e"]) == sorted(f"{k}={v}" for k, v in eh.CONTAINER_ENV.items())
    assert copy_in == eh.COPY_IN
    spec = importlib.util.spec_from_file_location("eqc_json", d / "eqc_json.py")
    assert spec is not None and spec.loader is not None
    ej = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ej)
    assert tuple(ej.DIGEST_PATHS) == eh.INSPECT_DIGEST_PATHS
    repo_fake = d.parent.parent / "tests" / "fake-container" / "container"
    if repo_fake.is_file():
        assert repo_fake.read_bytes() == FAKE.read_bytes()


def test_r1_f4_work_is_a_capped_tmpfs_over_a_readonly_bind(tmp_path: Path) -> None:
    """R1 F4: no rw bind of a host dir; /work is a tmpfs with a size cap, filled from /eqsrc/work (read-only)."""
    vals, _, _, inner = opts(_call(tmp_path).argv)
    assert "-v" not in vals and all(ro for _, ro in mounts(vals).values())
    assert f"/work:size={eh.DEFAULT_FLAGS['container_work_size']},mode=1777" in vals["--tmpfs"]
    assert mounts(vals)["/eqsrc/work"][1] is True
    assert inner == ["/bin/sh", "-c", eh.COPY_IN, "eq-run", "/eqsrc/work", "/work", "--", "true"]
    vals, _, _, _ = opts(_call(tmp_path, container_work_size="64M").argv)
    assert "/work:size=64M,mode=1777" in vals["--tmpfs"]


@pytest.mark.parametrize("over", [{"container_work_size": "1g,mode=0777"}, {"container_tmp_size": "2G "},
                                  {"container_limits": {"nproc": 0, "memory": "8G", "cpus": "2"}},
                                  {"container_limits": {"nproc": "x", "memory": "8G", "cpus": "2"}},
                                  {"container_limits": {"nproc": 512, "memory": "8G --privileged", "cpus": "2"}},
                                  {"container_limits": {"nproc": 512, "memory": "8G", "cpus": "two"}},
                                  {"container_limits": {"memory": "8G", "cpus": "2"}}])
def test_malformed_limits_never_reach_the_argv(tmp_path: Path, over: dict[str, Any]) -> None:
    with pytest.raises(eh.IsolationError, match=r"container_limits|container limits"):
        _call(tmp_path, **over)


def test_r1_f4_writes_to_work_never_reach_the_host_copy(tmp_path: Path, clog: Path) -> None:
    """R1 F4 through the fake CLI: the code sees the copy at /work, writes there stay in the (tmpfs) container dir."""
    work = tmp_path / "copy"
    work.mkdir()
    (work / "f.txt").write_text("orig\n")
    iso = iso_(tmp_path)
    call = iso.isolate(["sh", "-c", "cat f.txt; echo tampered > f.txt; echo new > new.txt; cat f.txt"], cls="PF",
                       rw_dirs={"/work": work}, ro_dirs={}, workdir="/work", tmp=tmp_path)
    rc, out = iso.run(call, 20)
    assert rc == 0 and out.split() == ["orig", "tampered"], out
    assert (work / "f.txt").read_text() == "orig\n" and not (work / "new.txt").exists()


def test_r1_f8_digest_checked_before_and_after_every_run(tmp_path: Path, clog: Path) -> None:
    """The run names the TAG (a locally built image is found by name only), so `image inspect TAG` must report the
    pinned digest right before the run and again after it; nothing is ever pulled by digest."""
    iso = iso_(tmp_path)
    rc, _ = iso.run(_call(tmp_path), 20)
    assert rc == 0
    cs = calls(clog)
    assert [c[:2] for c in cs] == [["image", "inspect"], ["run", "--rm"], ["image", "inspect"]]
    assert cs[0][-1] == cs[2][-1] == TAG and TAG in cs[1] and IMG not in cs[1]


def test_r1_f8_an_image_swapped_during_the_run_is_an_isolation_error(tmp_path: Path, clog: Path) -> None:
    """A passing run whose image has another digest afterwards (rebuilt or retagged while it ran) is never a PASS."""
    flag = tmp_path / "swapped"
    wrap = tmp_path / "container"
    wrap.write_text(f'#!/bin/bash\n[ -e "{flag}" ] && export EQ_FAKE_CONTAINER_DIGEST={OTHER}\n'
                    f'"{FAKE}" "$@"; rc=$?\n[ "$1" = run ] && : > "{flag}"\nexit $rc\n')
    wrap.chmod(0o755)
    iso = iso_(tmp_path, container_bin=str(wrap))
    with pytest.raises(eh.IsolationError, match=r"after the run.*rebuilt or retagged"):
        iso.run(_call(tmp_path, container_bin=str(wrap)), 20)


def test_container_user_must_be_numeric(tmp_path: Path) -> None:
    with pytest.raises(eh.IsolationError):
        iso_(tmp_path, container_user="root")
    assert iso_(tmp_path, container_user="").user == f"{os.getuid()}:{os.getgid()}"


def test_network_is_never_granted(tmp_path: Path) -> None:
    with pytest.raises(eh.IsolationError):
        iso_(tmp_path).isolate(["true"], cls="PF", rw_dirs={}, ro_dirs={}, workdir="/", tmp=tmp_path, net=True)


@pytest.mark.parametrize("ref", ["eq-lean", "eq-lean:latest", "eq-lean@" + DIGEST, DIGEST, "sha256:abc", "",
                                 "eq-lean:1@sha256:" + "AB" * 32, "eq lean:1@" + DIGEST, "eq-lean:1@sha256:abc",
                                 "eq-lean:1@" + DIGEST + "\n", "Eq-Lean:1@" + DIGEST])
def test_tag_or_malformed_image_refused(ref: str) -> None:
    with pytest.raises(eh.IsolationError):
        eh.image_ref(ref)


@pytest.mark.parametrize("ref", [IMG, "eq-lean:1@" + DIGEST, "localhost:5000/eq/lean:v1.2_x@" + DIGEST])
def test_digest_pinned_image_accepted(ref: str) -> None:
    assert eh.image_ref(ref) == ref


def test_isolate_refuses_a_tagged_image(tmp_path: Path) -> None:
    with pytest.raises(eh.IsolationError):
        iso_(tmp_path, container_images={"PF": "eq-lean:latest"}).isolate(
            ["true"], cls="PF", rw_dirs={}, ro_dirs={}, workdir="/", tmp=tmp_path)


def test_flags_cli_refuses_a_tag(tmp_path: Path) -> None:
    cp = run_harness(["flags", "--out", str(tmp_path / "f.json"), "--container-image", "PF=eq-lean:latest"],
                     dict(os.environ))
    assert cp.returncode == 2 and not (tmp_path / "f.json").exists()
    cp = run_harness(["flags", "--out", str(tmp_path / "f.json"), "--container-image", f"PF={IMG}"],
                     dict(os.environ))
    assert cp.returncode == 0 and json.loads((tmp_path / "f.json").read_text())["container_images"]["PF"] == IMG


def test_inspect_digest_shapes() -> None:
    """Where CLI 1.5.0 keeps the digest (ImageResource.swift at tag 1.5.0; behaviour unverified, checklist C1):
    .configuration.descriptor.digest, and .id = its hex without "sha256:"; one digest is enough, two must agree, none
    (or a non-array, or two objects) is no digest."""
    def obj(**kw: Any) -> str:
        return json.dumps([{"configuration": {}, "id": "x", "variants": [], **kw}])
    hx, ohx = DIGEST.split(":", 1)[1], OTHER.split(":", 1)[1]
    desc = {"descriptor": {"mediaType": "application/vnd.oci.image.index.v1+json", "digest": DIGEST, "size": 1}}
    assert eh.inspect_digest(obj(configuration=desc)) == DIGEST
    assert eh.inspect_digest(obj(id=hx)) == DIGEST and eh.inspect_digest(obj(id=DIGEST)) == DIGEST
    assert eh.inspect_digest(obj(configuration=desc, id=hx)) == DIGEST  # the 1.5.0 shape
    assert eh.inspect_digest(obj(configuration=desc, id=ohx)) is None
    assert eh.inspect_digest(obj(configuration={"descriptor": {"digest": hx}})) is None  # the descriptor names sha256
    assert eh.inspect_digest(obj(configuration={"index": {"digest": DIGEST}})) is None  # not a 1.5.0 key
    assert eh.inspect_digest(obj()) is None
    assert eh.inspect_digest(obj(id=DIGEST.upper())) is None
    assert eh.inspect_digest("not json") is None and eh.inspect_digest(json.dumps({"id": DIGEST})) is None
    assert eh.inspect_digest(json.dumps([{"id": DIGEST}, {"id": DIGEST}])) is None


def test_list_rows_skips_malformed_rows() -> None:
    """[unverified] `container list --all --format json` rows: .configuration.id / .configuration.labels."""
    out = json.dumps([{"configuration": {"id": "eq-a", "labels": {"eq-harness": "1"}}}, {"configuration": {"id": 5}},
                      "junk", {"configuration": {"id": "eq-b"}}, {"id": "eq-c"}])
    assert eh.list_rows(out) == [("eq-a", {"eq-harness": "1"}), ("eq-b", {})]
    assert eh.list_rows("garbage") == [] and eh.list_rows("{}") == []


# --- mount validation ------------------------------------------------------------------------------------------------
def test_forbidden_mounts_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    for d in (".ssh", ".docker/run", "Library/Application Support/com.apple.container", "work"):
        (home / d).mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    (tmp_path / "eq" / "runs" / "d" / "grading_keys").mkdir(parents=True)
    (tmp_path / "pool" / "CP" / "oracle" / "hidden").mkdir(parents=True)
    (tmp_path / "a:b").mkdir()
    (tmp_path / "a,b").mkdir()
    (tmp_path / "a=b").mkdir()  # `--mount` splits key=value at "=" (1.5.0 Parser.mount)
    iso = eh.Isolation(dflags(), tmp_path / "eq", tmp_path / "pool")
    bad = [home, home.parent, Path("/"), home / ".ssh", home / ".docker" / "run",
           home / "Library" / "Application Support" / "com.apple.container", tmp_path / "eq",
           tmp_path / "eq" / "runs" / "d" / "grading_keys", tmp_path / "pool" / "CP" / "oracle" / "hidden",
           tmp_path / "pool", tmp_path / "a:b", tmp_path / "a,b", tmp_path / "a=b"]
    for h in bad:
        with pytest.raises(eh.IsolationError):
            iso.isolate(["true"], cls="PF", rw_dirs={"/work": h}, ro_dirs={}, workdir="/work", tmp=tmp_path)
    for ctr in ("/", CTMP, CTMP + "/x", "/a:b", "rel", "/a/../b", "/eqsrc/work", "/a,b", "/a=b", "/eq", "/eq/tunnel"):
        with pytest.raises(eh.IsolationError):
            iso.isolate(["true"], cls="PF", rw_dirs={ctr: home / "work"}, ro_dirs={}, workdir="/work", tmp=tmp_path)
    iso.forbidden = []  # the home rule alone (without the secrets list, which also covers ancestors of home)
    for h in (home, home.parent):
        with pytest.raises(eh.IsolationError, match="home directory"):
            iso.isolate(["true"], cls="PF", rw_dirs={"/work": h}, ro_dirs={}, workdir="/work", tmp=tmp_path)
    ok = iso.isolate(["true"], cls="PF", rw_dirs={"/work": home / "work"}, ro_dirs={}, workdir="/work", tmp=tmp_path)
    assert f"type=bind,source={(home / 'work').resolve()},target=/eqsrc/work,readonly" in ok.argv


def test_host_socket_never_mountable(tmp_path: Path) -> None:
    iso = iso_(tmp_path)
    assert Path("/var/run/docker.sock") in iso.forbidden and Path.home().resolve() / ".docker" in iso.forbidden
    assert Path.home().resolve() / "Library" in iso.forbidden  # the container services' own state lives under it


def test_docker_flags_are_refused_with_a_pointer() -> None:
    with pytest.raises(eh.IsolationError, match="replaced by 'container'"):
        eh.Isolation({"isolation": "docker", "docker_bin": "docker"})


# --- runs through the fake CLI ----------------------------------------------------------------------------------------
def runner_d(tmp: Path, **over: Any) -> eh.Runner:
    cfg = eh.RunConfig("d", tmp / "pool", tmp / "eq", tmp / "raw", dflags(**over), "/nonexistent", {},
                       {c: {} for c in eh.CLASSES})
    return eh.Runner(cfg, eh.Ledger(tmp / "ledger.jsonl"))


def test_run_check_goes_through_the_container(tmp_path: Path, clog: Path) -> None:
    item = item_(pool_(tmp_path, {"check.sh": 'grep -q "^GOOD$" Answer.lean && test -f /fixture/check.sh\n'}), "PF",
                 ("bash", "check.sh"))
    r, wd = runner_d(tmp_path), tmp_path / "work" / "m1"
    eh.copy_fixture(item, wd)
    assert r.run_check(item, "p3", wd, "GOOD\n")[0] is False  # /fixture is a container path: the fake maps it
    runs = [c for c in calls(clog) if c[0] == "run"]
    assert len(runs) == 1
    vals, _, image, inner = opts(["container", *runs[0]])
    assert image == TAG and user_argv(inner) == ["bash", "/fixture/check.sh"]  # R1 F6: the pristine script
    ms = mounts(vals)
    assert ms.keys() == {"/fixture", "/eqsrc/work"} and all(ro for _, ro in ms.values())
    assert "/check_runs/" in ms["/eqsrc/work"][0]  # the FRESH check copy, never the member's copy
    env = dict(e.split("=", 1) for e in vals["-e"])
    assert env["EQ_LEAN_TOTAL"] == "540"  # check_timeout_s 600 - margin 60 (container start included)
    assert r.iso.tag("PF") == {"isolation": "container", "image": IMG}


def test_run_check_verdict_through_fake(tmp_path: Path, clog: Path) -> None:
    item = item_(pool_(tmp_path, {"check.sh": 'grep -q "^GOOD$" Answer.lean\n'}), "PF", ("bash", "check.sh"))
    r, wd = runner_d(tmp_path), tmp_path / "work" / "m1"
    eh.copy_fixture(item, wd)
    assert r.run_check(item, "p3", wd, "GOOD\n")[0] is True
    assert r.run_check(item, "p3", wd, "BAD\n")[0] is False
    assert list((r.arm_dir(item, "p3") / "check_runs").iterdir()) == []


def test_r1_f6_check_script_and_its_inputs_come_from_the_readonly_fixture(tmp_path: Path, clog: Path) -> None:
    """R1 F6: compile-time code (here: the answer, sourced by the check) rewrites the file the check judges by, in
    its cwd /work. The check must run /fixture/check.sh, whose dirname "$0" is the read-only fixture."""
    check = 'sh Answer.lean; here=$(dirname "$0"); test "$(cat "$here/rule.txt")" = open\n'
    pool = pool_(tmp_path, {"check.sh": check, "rule.txt": "closed\n"})
    item = item_(pool, "PF", ("bash", "check.sh"))
    r, wd = runner_d(tmp_path), tmp_path / "work" / "m1"
    eh.copy_fixture(item, wd)
    ok, out = r.run_check(item, "p3", wd, "echo open > rule.txt\n")
    assert ok is False, out
    inner = opts(["container", *next(c for c in calls(clog) if c[0] == "run")])[3]
    assert user_argv(inner) == ["bash", "/fixture/check.sh"]
    assert (pool / "fx" / "rule.txt").read_text() == "closed\n"
    r_off = runner_d(tmp_path, isolation="off")  # 'off' keeps the argv (host paths; documented as unisolated)
    assert r_off.run_check(item, "p3", wd, "echo open > rule.txt\n")[0] is True


def test_r1_f6_owned_tests_are_mounted_readonly_over_work(tmp_path: Path, clog: Path) -> None:
    pool = pool_(tmp_path, {"check.sh": "test -f tests/t.py\n", "tests/t.py": "pass\n"})
    item = item_(pool, "CP", ("bash", "check.sh"))
    r, wd = runner_d(tmp_path), tmp_path / "work" / "m1"
    eh.copy_fixture(item, wd)
    seen: list[set[str]] = []
    real = r.iso.run

    def spy(call: eh.IsoCall, timeout_s: float) -> tuple[int | None, str]:
        vals, _, _, _ = opts(call.argv)
        ms = mounts(vals)
        assert ms["/work/tests"] == (str((pool / "fx" / "tests").resolve()), True)
        seen.append({p.name for p in Path(ms["/eqsrc/work"][0]).iterdir()})
        return real(call, timeout_s)

    r.iso.run = spy  # type: ignore[method-assign]
    ok, out = r.run_check(item, "p3", wd, None)
    assert seen == [{"check.sh"}]  # the copy-in source holds no tests/: the copy step never writes over the mount
    assert ok is True, out


def test_timeout_kills_the_container_by_name(tmp_path: Path, clog: Path) -> None:
    item = item_(pool_(tmp_path, {"check.sh": "sleep 30\n"}), "PF", ("bash", "check.sh"))
    r, wd = runner_d(tmp_path, check_timeout_s=1), tmp_path / "work" / "m1"
    eh.copy_fixture(item, wd)
    ok, out = r.run_check(item, "p3", wd, "x")
    assert ok is False and out.startswith("check timeout")
    cs = calls(clog)
    name = opts(["container", *next(c for c in cs if c[0] == "run")])[0]["--name"][0]
    assert ["kill", name] in cs


@pytest.mark.parametrize("rc", ["1", "2", "64", "125"])
def test_cli_or_code_failure_is_never_a_pass(tmp_path: Path, clog: Path, monkeypatch: pytest.MonkeyPatch,
                                             rc: str) -> None:
    """[unverified] the CLI's own failures cannot be told apart from the code's by exit code: with the services and
    the image fine, any non-zero exit is a failing check (never a pass), after the infrastructure was asked."""
    monkeypatch.setenv("EQ_FAKE_CONTAINER_RUN_RC", rc)
    item = item_(pool_(tmp_path, {"check.sh": "exit 0\n"}), "PF", ("bash", "check.sh"))
    r, wd = runner_d(tmp_path), tmp_path / "work" / "m1"
    eh.copy_fixture(item, wd)
    ok, _ = r.run_check(item, "p3", wd, "x")
    assert ok is False
    after = [c[:2] for c in calls(clog)]
    assert after[after.index(["run", "--rm"]) + 1:] == [["system", "status"], ["image", "inspect"]]


@pytest.mark.parametrize("lost", ["died", {"EQ_FAKE_CONTAINER_DOWN": "1"}, {"EQ_FAKE_CONTAINER_MISSING": TAG},
                                  {"EQ_FAKE_CONTAINER_DIGEST": OTHER}, {"EQ_FAKE_CONTAINER_INSPECT": "conflict"}])
def test_r1_f3_services_or_image_lost_raises(tmp_path: Path, clog: Path, monkeypatch: pytest.MonkeyPatch,
                                             lost: Any) -> None:
    """R1 F3: services lost with the run (or down, the image missing, rebuilt or unreadable before it) is an
    IsolationError, never a member check FAIL."""
    if lost == "died":
        lost = {"EQ_FAKE_CONTAINER_RUN_RC": "1", "EQ_FAKE_CONTAINER_DIE_ON_RUN": str(tmp_path / "died")}
    for k, v in lost.items():
        monkeypatch.setenv(k, v)
    item = item_(pool_(tmp_path, {"check.sh": "exit 0\n"}), "PF", ("bash", "check.sh"))
    r, wd = runner_d(tmp_path), tmp_path / "work" / "m1"
    eh.copy_fixture(item, wd)
    with pytest.raises(eh.IsolationError):
        r.run_check(item, "p3", wd, "x")
    assert list((r.arm_dir(item, "p3") / "check_runs").iterdir()) == []  # the check copy is still removed
    (tmp_path / "fx2").mkdir()
    (tmp_path / "fx2" / "t.sh").write_text("true\n")
    ex = iso_(tmp_path).fact_executor("CR", "CR-0001.p3")
    fc = md.FactChecker(tmp_path / "fx2", "fx2", public_check=["bash", "t.sh"], timeout_s=20, execute=ex)
    with pytest.raises(eh.IsolationError):  # a fact re-run is never REFUTED (nor unverifiable) for lost services
        fc.check({"kind": "command", "ref": "bash t.sh", "detail": "exit 0"})


def test_r1_f3_run_records_run_abort_and_exits_2(stub_bin: Path, tmp_path: Path) -> None:
    log = tmp_path / "container.log"
    cp, tmp = _run_dir(stub_bin, tmp_path, container_fixt_flags(),
                       {"EQ_FAKE_CONTAINER_LOG": str(log), "EQ_FAKE_CONTAINER_RUN_RC": "125",
                        "EQ_FAKE_CONTAINER_DIE_ON_RUN": str(tmp_path / "services-died")})
    assert cp.returncode == 2 and "isolation lost" in cp.stderr, cp.stderr
    recs = ledger(tmp)
    abort = [r for r in recs if r["record"] == "run_abort"]
    assert len(abort) == 1 and abort[0]["item"] == "PF-DEV1" and "services" in abort[0]["error"]
    assert not any(r["record"] == "check" for r in recs)  # the lost check is not recorded as a member FAIL
    assert not any(r["record"] == "run_end" for r in recs)
    assert not any(r["record"] == "item_arm" and r["label"] == abort[0]["label"] for r in recs)  # redone later


def test_sweep_removes_orphans_of_one_arm(tmp_path: Path, clog: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    iso = iso_(tmp_path)
    now = int(eh.time.time())
    monkeypatch.setenv("EQ_FAKE_CONTAINER_LABELLED", " ".join([
        f"eq-1:{iso.inv}:{now}:PF-0001.p3", f"other:{iso.inv}:{now}:PF-0001.p3", f"eq-2:{iso.inv}:{now}:PF-0001.p3",
        f"eq-3:{iso.inv}:{now}:PF-0002.p3", f"eq-4:{'c' * 32}:{now}:PF-0001.p3"]))
    assert iso.sweep("PF-0001.p3") == 2
    cs = calls(clog)
    assert cs[0] == ["list", "--all", "--format", "json"]
    assert cs[1] == ["delete", "--force", "eq-1", "eq-2"]  # this arm, this invocation, eq- names only
    assert eh.Isolation(dict(dflags(), isolation="off")).sweep() == 0
    with pytest.raises(eh.IsolationError):
        iso.sweep("bad arm")


def test_r1_f2_sweep_removes_only_this_invocations_containers(tmp_path: Path, clog: Path,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    """R1 F2: a full sweep removes this invocation's containers (label eq-inv); another invocation's live containers
    and the lib.sh probe containers (no eq-inv) are only reported; another invocation's are removed once stale."""
    iso = iso_(tmp_path)
    assert iso.sweep() == 0 and calls(clog) == [["list", "--all", "--format", "json"]]
    other, now = "c" * 32, int(eh.time.time())
    old = now - int(iso.stale_after_s()) - 10
    monkeypatch.setenv("EQ_FAKE_CONTAINER_LABELLED", " ".join([
        f"eq-live:{other}:{now - 5}",           # another invocation, running now: keep
        f"eq-stale:{other}:{old}",              # another invocation, older than any run: remove
        "eq-RUNID-probe-main::",                # lib.sh probe container (no eq-inv): keep
        f"eq-mine:{iso.inv}:{old}"]))           # this invocation's: remove
    clog.unlink()
    assert iso.sweep() == 2
    cs = calls(clog)
    assert ["delete", "--force", "eq-mine", "eq-stale"] in cs
    assert not any("eq-live" in c or "eq-RUNID-probe-main" in c for c in cs[1:])
    assert sorted(iso.foreign) == ["eq-RUNID-probe-main", "eq-live"]


def test_mediator_reruns_go_through_the_container(tmp_path: Path, clog: Path) -> None:
    (tmp_path / "fx").mkdir()
    (tmp_path / "fx" / "t.sh").write_text("echo hello\n")
    ex = iso_(tmp_path).fact_executor("CR", "CR-0001.p3")
    assert ex is not None
    st, method, _ = md.verify({"kind": "command", "ref": "bash t.sh", "detail": "exit 0 hello"}, tmp_path / "fx",
                              public_check=["bash", "t.sh"], timeout_s=20, execute=ex)
    assert st == md.VERIFIED, method
    runs = [c for c in calls(clog) if c[0] == "run"]
    assert len(runs) == 2 and all(user_argv(opts(["container", *c])[3]) == ["bash", "t.sh"] for c in runs)
    assert eh.Isolation(dict(dflags(), isolation="off")).fact_executor("CR", "x") is None


def _cp_pool(tmp_path: Path) -> tuple[Path, Path, Path]:
    """test_isolated_oracle_stages_only_allowed_inputs's pool: (pool, answer file, scoring copy)."""
    pool = tmp_path / "pool" / "CP"
    (pool / "fixtures" / "a").mkdir(parents=True)
    (pool / "fixtures" / "b").mkdir(parents=True)
    (pool / "oracle" / "hidden").mkdir(parents=True)
    (pool / "fixtures" / "a" / "m.py").write_text("x = 1\n")
    (pool / "fixtures" / "b" / "secret.py").write_text("other item\n")
    (pool / "oracle" / "hidden" / "m.py").write_text("hidden\n")
    (pool / "oracle" / "refs.py").write_text("REFERENCE ANSWERS\n")
    (pool / "oracle" / "items.json").write_text("{}\n")
    (pool / "oracle.py").write_text(
        "import json, os, sys\n"
        "seen = sorted(os.path.relpath(os.path.join(d, f), '/in') for d, _, fs in os.walk('/in') for f in fs)\n"
        "print(json.dumps({'score': 1, 'detail': seen}))\n")
    ans = tmp_path / "eq" / "runs" / "d" / "grading_keys" / "a.json"
    ans.parent.mkdir(parents=True)
    ans.write_text('{"answer": "x"}')
    wdc = tmp_path / "wdc"
    wdc.mkdir()
    (wdc / "m.py").write_text("x = 2\n")
    return pool, ans, wdc


def test_isolated_oracle_stages_only_allowed_inputs(tmp_path: Path, clog: Path) -> None:
    pool, ans, wdc = _cp_pool(tmp_path)
    iso = eh.Isolation(dflags(), tmp_path / "eq", tmp_path / "pool")
    staged: list[set[str]] = []
    real_run = iso.run

    def spy(call: eh.IsoCall, timeout_s: float) -> tuple[int | None, str]:
        vals, bare, _, inner = opts(call.argv)
        assert mounts(vals) == {"/in": (str((call.cwd / "in").resolve()), True)} and "--workdir" in inner
        assert inner[:5] == ["uv", "run", "--script", "--quiet", "/in/pool/oracle.py"]
        assert "-i" in bare  # the nonce reaches the oracle's stdin
        root = call.cwd / "in"
        staged.append({str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()})
        return 0, eqv1(call, {"score": 1})

    iso.run = spy  # type: ignore[method-assign]
    rc, out = eh.run_oracle(pool, "CP-0001", ans, "--workdir", str(wdc), iso=iso, cls="CP", fixture="fixtures/a")
    iso.run = real_run  # type: ignore[method-assign]
    assert rc == 0 and json.loads(out) == {"score": 1}
    assert staged == [{"pool/oracle.py", "pool/fixtures/a/m.py", "pool/oracle/items.json", "pool/oracle/hidden/m.py",
                       "answer.json", "workdir/m.py"}]
    with pytest.raises(eh.IsolationError):
        eh.run_oracle(pool, "CP-0001", ans, "--grader-input", "x", iso=iso, cls="CP")


@pytest.mark.parametrize("out", [
    '{"item":"CP-0001","score":0.0}\n{"score":1.0}\n',                     # answer code's JSON after the verdict
    "EQV1 0123456789abcdef0123456789abcdef {\"score\": 1.0}\n",           # a guessed nonce
    "EQV1 NONCE {\"score\": 0.0}\nEQV1 NONCE {\"score\": 1.0}\n",           # two authenticated lines
])
def test_isolated_oracle_ignores_unauthenticated_verdict(tmp_path: Path, clog: Path, out: str) -> None:
    """R1 F1: answer code shares the oracle's container and output stream; only the `EQV1 <nonce>` line counts, and
    exactly one of it."""
    pool, ans, wdc = _cp_pool(tmp_path)
    iso = eh.Isolation(dflags(), tmp_path / "eq", tmp_path / "pool")
    iso.run = lambda c, t: (0, out.replace("NONCE", c.stdin.decode().strip()))  # type: ignore[method-assign,union-attr]
    rc, got = eh.run_oracle(pool, "CP-0001", ans, "--workdir", str(wdc), iso=iso, cls="CP", fixture="fixtures/a")
    score = eh.parse_score(eh.last_json(got).get("score"))
    assert rc != 0 and score != 1.0 and got.startswith("oracle error:"), got


def test_r1_f1_host_oracle_nonce_on_stdin_and_one_verdict_line(tmp_path: Path) -> None:
    """R1 F1, backend 'off' / host oracles: the same channel (nonce on stdin, exactly one EQV1 line); a class outside
    EQV1_CLASSES keeps its raw output."""
    pool = tmp_path / "PF"
    pool.mkdir()
    (tmp_path / "a.json").write_text("{}")
    (pool / "oracle.py").write_text(
        "import json, sys\nn = sys.stdin.readline().strip()\nprint(json.dumps({'score': 1}))\n"
        "print('EQV1 ' + n + ' ' + json.dumps({'score': 0, 'detail': 'ok'}))\n")
    rc, out = eh.run_oracle(pool, "PF-0001", tmp_path / "a.json", cls="PF")
    assert rc == 0 and json.loads(out) == {"score": 0, "detail": "ok"}
    (pool / "oracle.py").write_text("import json\nprint(json.dumps({'score': 1}))\n")  # speaks no EQV1
    rc, out = eh.run_oracle(pool, "PF-0001", tmp_path / "a.json", cls="PF")
    assert rc == 1 and out.startswith("oracle error: 0 authenticated")
    rc, out = eh.run_oracle(pool, "ES-0001", tmp_path / "a.json", cls="ES")
    assert rc == 0 and json.loads(out) == {"score": 1}
    assert set(eh.EQV1_CLASSES) == {"PF", "CP", "CR"}


def test_non_executing_oracle_classes_stay_on_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []

    def fake(argv: Any, cwd: Path, env: dict[str, str], timeout_s: float, keep: int = 65536,
             stdin_data: bytes | None = None) -> tuple[int, str]:
        seen.append(list(argv))
        return 0, "{}"

    monkeypatch.setattr(eh, "run_bounded", fake)
    (tmp_path / "a.json").write_text("{}")
    eh.run_oracle(tmp_path, "ES-0001", tmp_path / "a.json", iso=iso_(tmp_path), cls="ES")
    assert seen and seen[0][0] == "uv"


# --- fail closed --------------------------------------------------------------------------------------------------
def test_preflight_fails_closed(tmp_path: Path, clog: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    iso_(tmp_path).preflight(["PF", "CP"])  # services up, images present with the pinned digest
    for shape in ("descriptor", "id"):  # either path alone is enough
        monkeypatch.setenv("EQ_FAKE_CONTAINER_INSPECT", shape)
        iso_(tmp_path).preflight(["PF"])
    for shape in ("none", "conflict"):
        monkeypatch.setenv("EQ_FAKE_CONTAINER_INSPECT", shape)
        with pytest.raises(eh.IsolationError, match="digest unreadable"):
            iso_(tmp_path).preflight(["PF"])
    monkeypatch.delenv("EQ_FAKE_CONTAINER_INSPECT")
    monkeypatch.setenv("EQ_FAKE_CONTAINER_MISSING", TAG)
    with pytest.raises(eh.IsolationError, match="not present"):
        iso_(tmp_path).preflight(["PF"])
    monkeypatch.delenv("EQ_FAKE_CONTAINER_MISSING")
    monkeypatch.setenv("EQ_FAKE_CONTAINER_DIGESTS", f"{TAG}={OTHER}")
    with pytest.raises(eh.IsolationError, match="rebuilt or retagged"):
        iso_(tmp_path).preflight(["PF"])
    monkeypatch.delenv("EQ_FAKE_CONTAINER_DIGESTS")
    monkeypatch.setenv("EQ_FAKE_CONTAINER_DOWN", "1")
    with pytest.raises(eh.IsolationError, match="services are not reachable"):
        iso_(tmp_path).preflight(["PF"])
    monkeypatch.delenv("EQ_FAKE_CONTAINER_DOWN")
    with pytest.raises(eh.IsolationError, match="is not name:tag@sha256"):
        iso_(tmp_path, container_images={"PF": ""}).preflight(["PF"])
    with pytest.raises(eh.IsolationError, match="not found"):
        iso_(tmp_path, container_bin=str(tmp_path / "no-container")).preflight(["PF"])
    with pytest.raises(eh.IsolationError, match="container limits malformed"):
        iso_(tmp_path, container_tmp_size="").preflight(["PF"])
    with pytest.raises(eh.IsolationError, match="stub"):
        iso_(tmp_path, isolation="sandbox-exec").preflight(["PF"])
    with pytest.raises(NotImplementedError):
        iso_(tmp_path, isolation="sandbox-exec").isolate(["true"], cls="PF", rw_dirs={}, ro_dirs={}, workdir="/",
                                                          tmp=tmp_path)
    with pytest.raises(eh.IsolationError):
        eh.Isolation({"isolation": "none"})


def _run_dir(stub_bin: Path, tmp: Path, flags: dict[str, Any], extra: dict[str, str]) -> tuple[Any, Path]:
    sched = tmp / "schedule.tsv"
    env = stub_env(stub_bin, tmp, **extra)
    assert run_harness(["schedule", "--items", str(ITEMS), "--stage", "d", "--out", str(sched)], env).returncode == 0
    (tmp / "flags.json").write_text(json.dumps(flags))
    cp = run_harness(["run", "--stage", "d", "--eq-root", str(tmp / "eq"), "--raw-root", str(tmp / "raw"), "--items",
                      str(ITEMS), "--flags", str(tmp / "flags.json"), "--schedule", str(sched), "--no-check",
                      "--only", "PF-DEV1"], env)
    return cp, tmp


def container_fixt_flags(**over: Any) -> dict[str, Any]:
    f = json.loads(json.dumps(FIXT_FLAGS))
    f.update(isolation="container", container_bin=str(FAKE), container_images={"PF": IMG, "CP": IMG, "CR": IMG})
    f.update(over)
    return f


def test_run_fails_closed_before_any_call(stub_bin: Path, tmp_path: Path) -> None:
    log = tmp_path / "container.log"
    cp, tmp = _run_dir(stub_bin, tmp_path, container_fixt_flags(),
                       {"EQ_FAKE_CONTAINER_LOG": str(log), "EQ_FAKE_CONTAINER_DOWN": "1"})
    assert cp.returncode == 2 and "isolation" in cp.stderr and "services are not reachable" in cp.stderr
    assert not (tmp / "stub_log.jsonl").exists() and ledger(tmp) == []  # no claude call, nothing ran unisolated
    assert not any(c[0] == "run" for c in calls(log))


def test_run_records_backend_and_sweeps_every_item_arm(stub_bin: Path, tmp_path: Path) -> None:
    log = tmp_path / "container.log"
    cp, tmp = _run_dir(stub_bin, tmp_path, container_fixt_flags(), {"EQ_FAKE_CONTAINER_LOG": str(log)})
    assert cp.returncode == 0, cp.stderr
    recs = ledger(tmp)
    start = next(r for r in recs if r["record"] == "run_start")
    assert start["isolation"]["backend"] == "container" and start["isolation"]["images"]["PF"] == IMG
    assert start["isolation"]["network"] == "none" and start["isolation"]["limits"]["nproc"] == 512
    checks = [r for r in recs if r["record"] == "check"]
    assert checks and all(r["isolation"] == "container" and r["image"] == IMG for r in checks)
    cs = calls(log)
    sweeps = [c for c in cs if c == ["list", "--all", "--format", "json"]]
    arms = {(r["item"], r["label"]) for r in recs if r["record"] == "item_arm"}
    assert arms and len(sweeps) == 2 * len(arms) + 2  # before and after every item-arm; run start and end
    runs = [opts(["container", *c])[0] for c in cs if c[0] == "run"]
    assert runs and all(v["--network"] == ["none"] for v in runs)
    invs = {lb for v in runs for lb in v["--label"] if lb.startswith("eq-inv=")}
    assert len(invs) == 1  # one invocation id per run (R1 F2)
    run_arms = {lb.split("=", 1)[1] for v in runs for lb in v["--label"] if lb.startswith("eq-arm=")}
    assert run_arms <= {f"{i}.{lab}" for i, lab in arms}


def test_one_backend_per_ledger(stub_bin: Path, tmp_path: Path) -> None:
    cp, tmp = _run_dir(stub_bin, tmp_path, dict(json.loads(json.dumps(FIXT_FLAGS)), isolation="off"), {})
    assert cp.returncode == 0 and "WARNING isolation 'off'" in cp.stderr
    shutil.rmtree(tmp / "raw")
    cp2, _ = _run_dir(stub_bin, tmp_path, container_fixt_flags(),
                      {"EQ_FAKE_CONTAINER_LOG": str(tmp_path / "c.log")})
    assert cp2.returncode == 2 and "one backend per run" in cp2.stderr


def test_isolation_probe_reports_without_guessing(tmp_path: Path, clog: Path) -> None:
    fl = tmp_path / "flags.json"
    fl.write_text(json.dumps(dflags()))
    env = dict(os.environ, EQ_FAKE_CONTAINER_DOWN="1")
    cp = run_harness(["isolation-probe", "--flags", str(fl)], env)
    assert cp.returncode == 2 and "PREFLIGHT FAIL" in cp.stdout and "normal terminal" in cp.stdout
    cp = run_harness(["isolation-probe", "--flags", str(fl), "--script", str(tmp_path / "none.sh")], dict(os.environ))
    assert cp.returncode == 2 and "PREFLIGHT PASS" in cp.stdout and "not found" in cp.stdout
    (tmp_path / "probe.sh").write_text("echo PROBE-RAN; exit 0\n")
    cp = run_harness(["isolation-probe", "--flags", str(fl), "--script", str(tmp_path / "probe.sh")], dict(os.environ))
    assert cp.returncode == 2 and "probe_inner.sh not found" in cp.stdout  # the in-container half is required too


INNER = 'echo "T|inner_ran|PASS|args $#"; echo ok > eq_probe_write; test -f in_scope.txt && echo "T|copy_seen|PASS|"\n'


def _norm(argv: list[str]) -> tuple[dict[str, list[str]], set[str], str, dict[str, bool]]:
    """A `container run` argv without what differs per call: name, eq-inv/eq-started labels, mount sources, argv."""
    vals, bare, image, _ = opts(argv)
    ms = mounts(vals)
    vals = {k: v for k, v in vals.items() if k not in ("--name", "--mount")}
    vals["--label"] = sorted(lb for lb in vals["--label"] if not lb.startswith(("eq-inv=", "eq-started=", "eq-arm=")))
    return vals, bare, image, {t: ro for t, (_, ro) in ms.items()}


def test_r1_f7_isolation_probe_runs_isolate_argv(tmp_path: Path, clog: Path) -> None:
    """R1 F7: the probe's containers are isolate()'s (same options, the flags.json image per class), with a decoy
    /work + /fixture case, an /in case (stdin), a /work cap case; probe.sh then gets EQ_PROBE_IMAGES and the CLI."""
    py_tag = "eq.invalid/eq-py-min:4.34.1-arm64"
    py = f"{py_tag}@{DIGEST}"
    flags = dflags(container_images={"PF": IMG, "CP": py, "CR": py}, container_work_size="4K")
    fl = tmp_path / "flags.json"
    fl.write_text(json.dumps(flags))
    (tmp_path / "probe.sh").write_text('echo "PROBE-RAN EQ_PROBE_IMAGES=$EQ_PROBE_IMAGES BIN=$EQ_CONTAINER_BIN '
                                       'UNRECORDED=$EQ_ALLOW_UNRECORDED"; exit 0\n')
    (tmp_path / "probe_inner.sh").write_text(INNER)
    cp = run_harness(["isolation-probe", "--flags", str(fl), "--script", str(tmp_path / "probe.sh")], dict(os.environ))
    assert f"PROBE-RAN EQ_PROBE_IMAGES={IMG} {py} BIN={FAKE} UNRECORDED=1" in cp.stdout, cp.stdout + cp.stderr
    runs = [["container", *c] for c in calls(clog) if c[0] == "run"]
    assert len(runs) == 6  # (main, /in, /work cap) x 2 distinct images
    assert sorted({opts(r)[2] for r in runs}) == sorted({TAG, py_tag})
    d = tmp_path / "ref"
    d.mkdir()
    iso = eh.Isolation(flags)
    ref_main = iso.isolate(["true"], cls="PF", rw_dirs={"/work": d}, ro_dirs={"/fixture": d}, workdir="/work", tmp=d)
    assert _norm(runs[0]) == _norm(ref_main.argv)  # the main probe's options = isolate()'s
    ref_in = iso.isolate(["true"], cls="PF", rw_dirs={}, ro_dirs={"/in": d}, workdir="/in/pool", tmp=d, stdin=b"x")
    assert _norm(runs[1]) == _norm(ref_in.argv) and "-i" in opts(runs[1])[1]
    assert "/work" in {t.split(":")[0] for t in opts(runs[2])[0]["--tmpfs"]}
    out = cp.stdout
    # probe_inner.sh args: 3 canaries, nproc, memory bytes, cpus, /work bytes (lib/eq-container/probe_inner.sh $1-$7)
    assert re.search(r"inner_ran\s+PASS\s+args 7", out) and re.search(r"copy_seen\s+PASS", out)  # copied in
    assert re.search(r"in_stdin_nonce\s+PASS", out) and re.search(r"in_staged_visible\s+PASS", out)
    assert re.search(r"in_readonly\s+FAIL", out)  # the fake cannot make /in read-only: reported, not guessed
    assert re.search(r"work_writes_stay_in_container\s+PASS", out)  # the decoy copy is bound read-only
    assert re.search(r"work_size_capped\s+FAIL", out)  # the fake has no tmpfs cap: reported, not guessed
    assert re.search(r"host_fixture_and_decoys_unchanged\s+PASS", out)
    assert cp.returncode == 1 and "HARNESS PROBE: FAIL" in out


def test_r1_f7_probe_script_resolves_in_the_repo_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for d in ("lib/eq-container", "isolation"):  # isolation/: the superseded Docker staging scripts
        (tmp_path / d).mkdir(parents=True)
        (tmp_path / d / "probe.sh").write_text("exit 0\n")
    monkeypatch.setattr(eh, "HERE", tmp_path / "harness")
    monkeypatch.delenv("EQ_CONTAINER_DIR", raising=False)
    found = [c for c in eh.probe_script_candidates() if c.is_file()]
    assert found == [tmp_path / "lib" / "eq-container" / "probe.sh"]
    monkeypatch.setenv("EQ_CONTAINER_DIR", str(tmp_path / "elsewhere"))
    assert eh.probe_script_candidates()[0] == tmp_path / "elsewhere" / "probe.sh"


def test_flags_from_image_env(tmp_path: Path) -> None:
    py = "eq.invalid/eq-py-min:4.34.1-arm64@sha256:" + "cd" * 32
    (tmp_path / "image.env").write_text(f"EQ_ISOLATION=container\nEQ_CONTAINER_IMAGE_PF={IMG}\n"
                                        f"EQ_CONTAINER_IMAGE_CP={py}\nEQ_CONTAINER_IMAGE_CR='{py}'\n")
    cp = run_harness(["flags", "--out", str(tmp_path / "f.json"), "--container-images-env",
                      str(tmp_path / "image.env")], dict(os.environ))
    assert cp.returncode == 0, cp.stderr
    assert json.loads((tmp_path / "f.json").read_text())["container_images"] == {"PF": IMG, "CP": py, "CR": py}
    (tmp_path / "image.env").write_text("EQ_CONTAINER_IMAGE_PF=eq-lean:latest\n")
    cp = run_harness(["flags", "--out", str(tmp_path / "g.json"), "--container-images-env",
                      str(tmp_path / "image.env")], dict(os.environ))
    assert cp.returncode == 2 and not (tmp_path / "g.json").exists()  # a tag is refused, as with --container-image


def test_default_flags_isolate_with_container() -> None:
    assert eh.DEFAULT_FLAGS["isolation"] == "container"
    assert eh.lean_total(eh.DEFAULT_FLAGS, float(eh.DEFAULT_FLAGS["check_timeout_s"])) == 540
    assert eh.DEFAULT_FLAGS["oracle_isolated_classes"] == ["PF", "CP"]
    real = json.loads((eh.HERE / "flags.json").read_text())
    for f in (eh.DEFAULT_FLAGS, real):
        assert not [k for k in f if k.startswith("docker")]
        assert f["container_limits"] == {"nproc": 512, "memory": "8G", "cpus": "2"}  # = lib.sh's EQ_* defaults
        assert (f["container_tmp_size"], f["container_work_size"], f["container_user"]) == ("2G", "1G", "10001:10001")
    assert {k: v for k, v in real.items() if k.startswith("container") or k.startswith("isolation")} == \
        {k: v for k, v in eh.DEFAULT_FLAGS.items() if k.startswith("container") or k.startswith("isolation")}


def test_live_mediator_uses_the_runs_backend(tmp_path: Path) -> None:
    item = item_(pool_(tmp_path, {"t.sh": "true\n"}), "CR", ("bash", "t.sh"))
    lm = runner_d(tmp_path).mediator(item, "p4", "E", None, "finding_set", 5, lambda a: None, 1)
    assert lm.checker.kw["execute"] is not None and lm.base["isolation"] == "container" and lm.base["image"] == IMG
    lm_off = runner_d(tmp_path, isolation="off").mediator(item, "p4", "E", None, "finding_set", 5, lambda a: None, 1)
    assert lm_off.checker.kw["execute"] is None and lm_off.base["isolation"] == "off"


def test_offline_facts_use_the_live_m10_rule_and_backend(full_run: Path, tmp_path: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, Any, Any]] = []
    real = md.FactChecker

    class Spy(real):  # type: ignore[valid-type,misc]
        def __init__(self, fixture: Path | None, fixture_id: str, **kw: Any) -> None:
            seen.append((fixture_id, kw.get("public_check"), kw.get("execute")))
            super().__init__(fixture, fixture_id, **kw)

    monkeypatch.setattr(md, "FactChecker", Spy)
    import argparse
    rc = md.cmd_offline_facts(argparse.Namespace(stage="d", eq_root=str(full_run / "eq"), raw_root=str(tmp_path),
                                                 items=str(ITEMS), flags=str(full_run / "flags.json")))
    assert rc == 0
    pf = [s for s in seen if s[0] and (ITEMS / "PF" / s[0]).exists()]
    items = eh.load_items(ITEMS, ["PF", "CP"])
    pf_fx = {it.fixture for it in items.values() if it.cls == "PF"}
    assert any(s[0] in pf_fx for s in seen) and pf
    assert all(s[1] is None for s in seen if s[0] in pf_fx)  # PF: no pristine re-run (M10), as live
    assert all(s[2] is None for s in seen)  # the run's flags say 'off'
