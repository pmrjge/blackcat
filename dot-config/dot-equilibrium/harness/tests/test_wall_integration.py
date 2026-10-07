"""WALL integration in the harness (../wall/WALL_DESIGN.md §8): frozen tunnel/broker config, the probe receipt gate,
the per-run nonce, the ONE tunnel mount added by isolate(), sandboxed member execution (an AMENDMENT proposal, off by
default), the broker lifecycle and the audit log copied into the ledger. Fake container CLI, stub claude,
default-deny policy: no real host action, no container services, no network."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest
from test_isolation import DIGEST, FAKE, IMG, TAG, calls, container_fixt_flags, dflags, mounts, opts

import eq_harness as eh
from conftest import ITEMS, STAGE, container_dir, ledger, run_harness, stub_env

WALLDIR = STAGE / "wall"
POLICY = WALLDIR / "policy.default.toml"
# the WALL tunnel probe: lib/eq-container/probe.d/50-tunnel.sh (the container version). Its --inner half is POSIX sh
# and backend-neutral, so without the repo dir the isolation-probe cases fall back to the superseded staging copy;
# its host mode (lib.sh, the container CLI) is tested only against the repo dir.
CDIR = container_dir()
TSCRIPT = (CDIR if CDIR is not None else STAGE / "isolation") / "probe.d" / "50-tunnel.sh"
needs_cdir = pytest.mark.skipif(CDIR is None, reason="lib/eq-container not found (EQ_CONTAINER_DIR unset)")


def wall_section(policy: Path = POLICY) -> dict[str, Any]:
    h = {"policy_sha256": eh.sha256_file(policy), "broker_sha256": eh.sha256_file(WALLDIR / "eq_wall.py"),
         "client_sha256": eh.sha256_file(WALLDIR / "eq_wall_client.py")}
    ew = eh.load_wall_module(WALLDIR / "eq_wall.py", h["broker_sha256"])
    return {"enabled": True, "mechanism": ew.MECHANISM, "ctr_path": eh.CTR_TUNNEL, **h,
            "config_sha256": ew.config_hash(h["policy_sha256"], h["broker_sha256"], h["client_sha256"])}


@pytest.fixture
def wenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    root = tmp_path.resolve()
    env = {"EQ_WALL_DIR": str(WALLDIR), "EQ_TUNNEL_DIR": str(root / "tun"), "EQ_WALL_STATE_DIR": str(root / "wst")}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("EQ_WALL_POLICY", raising=False)
    return env


def wflags(**over: Any) -> dict[str, Any]:
    return dflags(wall=wall_section(), **over)


# the rows only tunnel_probe()'s host side writes (pinned here: the gate must require each of them)
HOST_ROW_NAMES = ("tunnel_only_extra_mount", "tunnel_roundtrip", "host_process_unsignalled",
                  "sibling_channel_unchanged")
HOST_ROWS = [[n, "PASS", "fake"] for n in HOST_ROW_NAMES]
PASS_ROWS = [*([n, "PASS", "fake"] for n in eh.TUNNEL_PROBE_REQUIRED), *HOST_ROWS]


def receipt(state: Path, flags: dict[str, Any], result: str = "PASS", **over: Any) -> None:
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    rec = {"schema": "eqwall.probe.v1", "result": result, "config_sha256": flags["wall"]["config_sha256"],
           "images": {c: r for c, r in flags["container_images"].items() if r}, "rows": PASS_ROWS}
    rec.update(over)
    (state / "tunnel_probe.json").write_text(json.dumps(rec))


# ---------------------------------------------------------------------------------------------------------------------
# frozen configuration
# ---------------------------------------------------------------------------------------------------------------------


def test_flags_cli_freezes_the_wall_section(tmp_path: Path) -> None:
    cp = run_harness(["flags", "--out", str(tmp_path / "f.json"), "--wall-policy", str(POLICY), "--wall-dir",
                      str(WALLDIR), "--member-exec", "sandbox"], dict(os.environ))
    assert cp.returncode == 0, cp.stderr
    f = json.loads((tmp_path / "f.json").read_text())
    assert {k: v for k, v in f["wall"].items() if k != "comment"} == wall_section()
    assert f["member_exec"] == "sandbox"
    plain = json.loads(json.dumps(eh.DEFAULT_FLAGS))
    assert "wall" not in plain and "member_exec" not in plain  # pre-registered default: no WALL, host members


def test_wall_refuses_any_change_to_the_frozen_configuration(tmp_path: Path, wenv: dict[str, str],
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    iso = eh.Isolation(wflags())
    eh.Wall(wflags(), iso)  # the real files match
    alt = tmp_path / "walt"
    shutil.copytree(WALLDIR, alt, ignore=shutil.ignore_patterns("__pycache__", "tests"))
    (alt / "eq_wall.py").write_text((alt / "eq_wall.py").read_text() + "\n# drift\n")
    monkeypatch.setenv("EQ_WALL_DIR", str(alt))
    with pytest.raises(eh.IsolationError, match="broker differs from the frozen"):
        eh.Wall(wflags(), eh.Isolation(wflags()))
    shutil.copy(WALLDIR / "eq_wall.py", alt / "eq_wall.py")
    (alt / "eq_wall_client.py").write_text((alt / "eq_wall_client.py").read_text() + "\n# drift\n")
    with pytest.raises(eh.IsolationError, match=r"client\.py differs"):
        eh.Wall(wflags(), eh.Isolation(wflags()))
    monkeypatch.setenv("EQ_WALL_DIR", str(WALLDIR))
    pol = tmp_path / "policy.toml"
    pol.write_text(POLICY.read_text().replace("max_requests_per_run = 64", "max_requests_per_run = 65"))
    monkeypatch.setenv("EQ_WALL_POLICY", str(pol))
    with pytest.raises(eh.IsolationError, match=r"policy .* differs from the frozen"):
        eh.Wall(wflags(), eh.Isolation(wflags()))
    monkeypatch.delenv("EQ_WALL_POLICY")
    for k, v in (("config_sha256", "0" * 64), ("mechanism", "socket-v1"), ("ctr_path", "/eq/other")):
        f = wflags()
        f["wall"][k] = v
        with pytest.raises(eh.IsolationError, match="configuration differs"):
            eh.Wall(f, eh.Isolation(f))
    f = wflags(isolation="off")
    with pytest.raises(eh.IsolationError, match="container backend"):
        eh.Wall(f, eh.Isolation(f))


def test_wall_roots_must_be_disjoint_and_never_secrets(tmp_path: Path, wenv: dict[str, str],
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EQ_WALL_STATE_DIR", str(Path(wenv["EQ_TUNNEL_DIR"]) / "state"))
    with pytest.raises(eh.IsolationError, match="disjoint"):
        eh.Wall(wflags(), eh.Isolation(wflags()))


def test_probe_receipt_gate(tmp_path: Path, wenv: dict[str, str]) -> None:
    f = wflags()
    w = eh.Wall(f, eh.Isolation(f))
    state = Path(wenv["EQ_WALL_STATE_DIR"])
    with pytest.raises(eh.IsolationError, match="no tunnel probe receipt"):
        w.check_probe(["PF"])
    for res, over, msg in (("FAIL", {}, "did not PASS"), ("PASS", {"config_sha256": "1" * 64}, "another tunnel"),
                           ("PASS", {"images": {"PF": "x@sha256:" + "0" * 64}}, "does not cover the PF")):
        receipt(state, f, res, **over)
        with pytest.raises(eh.IsolationError, match=msg):
            w.check_probe(["PF"])
    receipt(state, f)
    w.check_probe(["PF", "CP"])
    assert re.fullmatch(r"[0-9a-f]{64}", str(w.receipt_sha256))
    (state / "tunnel_probe.json").unlink()
    (state / "tunnel_probe.json").symlink_to(tmp_path / "elsewhere.json")
    (tmp_path / "elsewhere.json").write_text(json.dumps({"result": "PASS"}))
    with pytest.raises(eh.IsolationError, match="no tunnel probe receipt"):
        w.check_probe(["PF"])


def test_probe_receipt_rows_are_revalidated(wenv: dict[str, str]) -> None:
    """DRYRUN defect: a receipt marked PASS was accepted with no rows, a missing required row or a FAIL row. The
    gate now re-checks `rows` against TUNNEL_PROBE_REQUIRED (PASS or INFO each) and refuses any FAIL row."""
    f = wflags()
    w = eh.Wall(f, eh.Isolation(f))
    state = Path(wenv["EQ_WALL_STATE_DIR"])
    drop = [r for r in PASS_ROWS if r[0] != "host_signal_blocked"]
    for rows, msg in (([], "host_signal_blocked"), (drop, "host_signal_blocked"),
                      ([*PASS_ROWS, ["tunnel_roundtrip", "FAIL", "nothing arrived"]], "tunnel_roundtrip FAIL"),
                      ([*(r for r in PASS_ROWS if r[0] != "no_inherited_fds"), ["no_inherited_fds", "MAYBE", "x"]],
                       "no_inherited_fds MAYBE"),
                      ("PASS", "rows malformed"), ([*PASS_ROWS, ["x", "PASS"]], "rows malformed")):
        receipt(state, f, rows=rows)
        with pytest.raises(eh.IsolationError, match=msg):
            w.check_probe(["PF"])
    info = [[n, "INFO" if n == "outbound_blocked" else "PASS", "d"] for n in eh.TUNNEL_PROBE_REQUIRED]
    receipt(state, f, rows=[*info, *HOST_ROWS, ["second_socket_blocked", "INFO", "n/a"]])
    w.check_probe(["PF"])  # INFO is not a FAIL (the probe's own rule)


def test_probe_receipt_requires_the_host_side_rows(wenv: dict[str, str]) -> None:
    """R2b (a): a receipt holding every in-container row but lacking one of the rows only the host side of
    tunnel_probe() writes (only extra mount, round trip, host sleeper, sibling channel) must be refused."""
    f = wflags()
    w = eh.Wall(f, eh.Isolation(f))
    state = Path(wenv["EQ_WALL_STATE_DIR"])
    inner = [[n, "PASS", "fake"] for n in eh.TUNNEL_PROBE_REQUIRED]
    for name in HOST_ROW_NAMES:
        receipt(state, f, rows=[*inner, *(r for r in HOST_ROWS if r[0] != name)])
        with pytest.raises(eh.IsolationError, match=f"lacks required row.*{name}"):
            w.check_probe(["PF"])
    receipt(state, f, rows=[*inner, *HOST_ROWS])
    w.check_probe(["PF"])


def test_the_broker_that_starts_must_be_the_frozen_one(tmp_path: Path, wenv: dict[str, str],
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    """W5 / N24#7 (CWE-367): Wall.__init__ hashes eq_wall.py and the policy, but `serve` re-reads both from disk.
    A rewrite between the two must not yield a running broker: broker_start's hashes are compared with flags.json."""
    alt = tmp_path / "walt"
    shutil.copytree(WALLDIR, alt, ignore=shutil.ignore_patterns("__pycache__", "tests"))
    monkeypatch.setenv("EQ_WALL_DIR", str(alt))
    for fname in ("eq_wall.py", "policy.default.toml"):
        f = wflags()
        w = eh.Wall(f, eh.Isolation(f))  # the bytes on disk match flags.json here
        orig = (alt / fname).read_text()
        (alt / fname).write_text(orig + "\n# rewritten after the hash check\n")
        try:
            with pytest.raises(eh.IsolationError, match="not the frozen one"):
                w.start()
            assert w.proc is not None and w.proc.wait(timeout=20) is not None  # killed, not left serving
        finally:
            (alt / fname).write_text(orig)
    f = wflags()
    w = eh.Wall(f, eh.Isolation(f))
    w.start()  # the unmodified copy starts
    w.stop(eh.Ledger(tmp_path / "ledger.jsonl"), "d")


def test_broker_stderr_is_private(tmp_path: Path, wenv: dict[str, str]) -> None:
    """N24#6: broker.stderr is created 0600 (O_EXCL|O_NOFOLLOW), as INSTALLER_WALL §4 requires of every WALL file."""
    f = wflags()
    w = eh.Wall(f, eh.Isolation(f))
    w.start()
    try:
        p = w.state / "runs" / str(w.run_id) / "broker.stderr"
        assert p.is_file() and not p.is_symlink() and (p.stat().st_mode & 0o777) == 0o600
    finally:
        w.stop(eh.Ledger(tmp_path / "ledger.jsonl"), "d")


def _slow_policy(tmp_path: Path, seconds: int) -> Path:
    tool = tmp_path / "bin" / "slowtool"
    tool.parent.mkdir(mode=0o700)
    tool.write_text(f"#!/bin/sh\nsleep {seconds}\necho slept\n")
    tool.chmod(0o755)
    real = tool.resolve()
    pol = tmp_path / "slow.toml"
    pol.write_text('schema = "eqwall.policy.v1"\n[limits]\nexec_timeout_s = 30\n[kinds]\nallowed = ["missing-tool"]\n'
                   '[web]\ndomains = []\n[tools_manifest]\nrequired = false\n[[tool]]\nname = "slowtool"\n'
                   f'kind = "missing-tool"\ncommand = "{real}"\ncommand_sha256 = "{eh.sha256_file(real)}"\n'
                   "args = []\ntimeout_s = 20\nmax_output_bytes = 4096\n")
    return pol


def test_close_channel_waits_for_a_busy_broker(tmp_path: Path, wenv: dict[str, str],
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """N24#3: the broker is serial; while channel A's approved tool runs (no audit record for up to exec_timeout_s),
    closing channel B with a short timeout used to raise 'stalled' (run_abort) on a healthy broker. The wait is now
    max(timeout_s, exec_timeout_s + 60) and restarts whenever the audit log grows."""
    pol = _slow_policy(tmp_path, 3)
    monkeypatch.setenv("EQ_WALL_POLICY", str(pol))
    f = dflags(wall=wall_section(pol))
    w = eh.Wall(f, eh.Isolation(f))
    ew = w.ew
    ew.append_store(w.state / "verdicts.jsonl", {"class_sha256": ew.class_hash(ew.load_policy(pol).tools["slowtool"]),
                                                 "tool": "slowtool", "verdict": "pass", "reviewer": "security-auditor",
                                                 "review_ref": "test", "open_high_critical": 0}, ew.VERDICT_SCHEMA)
    spec = importlib.util.spec_from_file_location("eq_wall_client_t", WALLDIR / "eq_wall_client.py")
    assert spec is not None and spec.loader is not None
    wc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wc)
    led = eh.Ledger(tmp_path / "ledger.jsonl")
    w.start()
    try:
        a = w.open_channel("PF-0001", "p1", "00001_member")
        b = w.open_channel("PF-0001", "p2", "00002_member")
        rq = wc.build_request(json.loads((a.host_dir / ew.CHANNEL_FILE).read_text()), "missing-tool", "slowtool",
                              "needed for the check", argv=["slowtool"], args=[])
        req = a.host_dir / f"req-{rq['request_id']}.json"
        req.write_bytes(ew.canon(rq))
        t0 = time.monotonic()
        while req.exists() and time.monotonic() - t0 < 20:  # the broker took it: the 3 s tool is running
            time.sleep(0.02)
        t1 = time.monotonic()
        w.close_channel(b, led, "d", timeout_s=1.0)
        assert time.monotonic() - t1 > 1.0  # it outlasted timeout_s instead of calling a busy broker stalled
        w.close_channel(a, led, "d", timeout_s=1.0)
        res = [r for r in eh.read_ledger(led.path) if r.get("wall_record") == "result"]
        assert len(res) == 1 and res[0]["rc"] == 0 and not res[0]["timed_out"]
    finally:
        w.stop(led, "d")


# ---------------------------------------------------------------------------------------------------------------------
# the ONE tunnel mount
# ---------------------------------------------------------------------------------------------------------------------


def _channel(tmp_path: Path) -> tuple[eh.Isolation, Any, Path]:
    f = wflags()
    iso = eh.Isolation(f)
    w = eh.Wall(f, iso)
    run_id = "a" * 32
    w.ew.prepare_run(w.tunnel_root, w.state, run_id)
    ch = w.ew.open_channel(w.tunnel_root, w.state, run_id, "b" * 64, "PF-0001", "p1", "c1")
    d = tmp_path / "work"
    d.mkdir(exist_ok=True)
    return iso, ch, d


def test_isolate_adds_exactly_one_writable_mount_the_tunnel(tmp_path: Path, wenv: dict[str, str]) -> None:
    iso, ch, d = _channel(tmp_path)
    call = iso.isolate(["true"], cls="PF", rw_dirs={"/work": d}, ro_dirs={"/fixture": d}, workdir="/work", tmp=d,
                       tunnel=ch.host_dir)
    vals, _, _, _ = opts(call.argv)
    ms = mounts(vals)
    assert ms[eh.CTR_TUNNEL] == (str(ch.host_dir.resolve()), False)
    assert [t for t, (_, ro) in ms.items() if not ro] == [eh.CTR_TUNNEL]  # the only writable host mount
    assert vals["--network"] == ["none"]
    plain = iso.isolate(["true"], cls="PF", rw_dirs={"/work": d}, ro_dirs={}, workdir="/work", tmp=d)
    assert not any(t.startswith("/eq/") for t in mounts(opts(plain.argv)[0]))  # checks/oracles: never a tunnel


def test_tunnel_mount_refusals(tmp_path: Path, wenv: dict[str, str]) -> None:
    iso, ch, d = _channel(tmp_path)
    for ctr in ("/eq", "/eq/tunnel", "/eq/x"):
        with pytest.raises(eh.IsolationError, match="not allowed"):
            iso.isolate(["true"], cls="PF", rw_dirs={}, ro_dirs={ctr: d}, workdir="/work", tmp=d)
    link = ch.host_dir.parent / ("c" + "9" * 32)
    link.symlink_to(ch.host_dir)
    loose = ch.host_dir.parent / ("c" + "8" * 32)
    loose.mkdir(mode=0o755)
    loose.chmod(0o755)
    shallow = Path(wenv["EQ_TUNNEL_DIR"]) / "shallow"
    shallow.mkdir(mode=0o700)
    cut = ch.host_dir.parent / "c="  # `--mount` drops the empty piece after "=": the CLI would mount the run dir
    cut.mkdir(mode=0o700)
    for bad, msg in ((link, "real 0700 directory"), (loose, "real 0700 directory"), (shallow, "<tunnel root>"),
                     (cut, "<tunnel root>"),
                     (tmp_path / "missing", "does not exist")):
        with pytest.raises(eh.IsolationError, match=msg):
            iso.isolate(["true"], cls="PF", rw_dirs={}, ro_dirs={}, workdir="/work", tmp=d, tunnel=bad)
    off = eh.Isolation(dflags(isolation="off"))
    with pytest.raises(eh.IsolationError, match="only under the container backend"):
        off.isolate(["true"], cls="PF", rw_dirs={}, ro_dirs={}, workdir="/work", tmp=d, tunnel=ch.host_dir)
    bare = eh.Isolation(dflags())
    with pytest.raises(eh.IsolationError, match="no WALL tunnel root"):
        bare.isolate(["true"], cls="PF", rw_dirs={}, ro_dirs={}, workdir="/work", tmp=d, tunnel=ch.host_dir)


# ---------------------------------------------------------------------------------------------------------------------
# sandboxed member execution (eqbox MCP server)
# ---------------------------------------------------------------------------------------------------------------------


def test_member_tools_replace_bash_only_in_sandbox_mode() -> None:
    f = dflags()
    assert eh.member_tools(f, "PF") == ([*f["allowed_tools"]["PF"], "Skill"], False)  # + Skill: COMPARE_eq §12 A4
    f["member_exec"] = "sandbox"
    tools, boxed = eh.member_tools(f, "PF")
    assert boxed and "Bash" not in tools and eh.MEMBER_EXEC_TOOL in tools and "Skill" in tools
    assert eh.member_tools(f, "RS") == ([*f["allowed_tools"]["RS"], "Skill"], False)  # no Bash, nothing to box


def _spec(tmp_path: Path, iso: eh.Isolation, ch: Any | None, d: Path) -> dict[str, Any]:
    return {"flags": iso.flags, "cls": "PF", "workdir": str(d), "arm": "PF-0001.p1", "inv": iso.inv,
            "eq_root": str(tmp_path), "items_dir": str(ITEMS), "tunnel": None if ch is None else str(ch.host_dir),
            "timeout_s": 30, "max_calls": 2, "log": str(tmp_path / "eqbox.jsonl")}


def test_member_exec_server_runs_argv_in_the_sandbox(tmp_path: Path, wenv: dict[str, str], clog: Path) -> None:
    iso, ch, d = _channel(tmp_path)
    spec = _spec(tmp_path, iso, ch, d)
    st: dict[str, int] = {}
    h = eh.member_exec_handle
    init = h(iso, spec, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "x"}}, st)
    assert init is not None and init["result"]["serverInfo"]["name"] == "eqbox"
    assert h(iso, spec, {"jsonrpc": "2.0", "method": "notifications/initialized"}, st) is None
    tl = h(iso, spec, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, st)
    assert tl is not None and [t["name"] for t in tl["result"]["tools"]] == ["sandbox_exec"]
    r = h(iso, spec, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                      "params": {"name": "sandbox_exec", "arguments": {"argv": ["echo", "hello-box"]}}}, st)
    assert r is not None and not r["result"]["isError"] and "exit 0" in r["result"]["content"][0]["text"]
    assert "hello-box" in r["result"]["content"][0]["text"]
    run = next(["container", *c] for c in calls(clog) if c[0] == "run")
    vals, _, image, _ = opts(run)
    assert image == TAG and vals["--network"] == ["none"] and f"eq-inv={iso.inv}" in vals["--label"]
    ms = mounts(vals)
    assert [t for t, (_, ro) in ms.items() if not ro] == [eh.CTR_TUNNEL] and ms["/eqsrc/work"][1]
    for bad in ({"argv": ["a\0b"]}, {"argv": "echo hi"}, {"argv": []}, {"argv": ["x"], "cwd": "/"}):
        r = h(iso, spec, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                          "params": {"name": "sandbox_exec", "arguments": bad}}, st)
        assert r is not None and r["result"]["isError"] and "refused" in r["result"]["content"][0]["text"]
    r = h(iso, spec, {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                      "params": {"name": "sandbox_exec", "arguments": {"argv": ["true"]}}}, st)
    r = h(iso, spec, {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                      "params": {"name": "sandbox_exec", "arguments": {"argv": ["true"]}}}, st)
    assert r is not None and "call limit" in r["result"]["content"][0]["text"]
    assert h(iso, spec, {"jsonrpc": "2.0", "id": 7, "method": "resources/list"}, st)["error"]["code"] == -32601  # type: ignore[index]
    assert len((tmp_path / "eqbox.jsonl").read_text().splitlines()) == 2


def test_member_exec_server_over_stdio(tmp_path: Path, wenv: dict[str, str], clog: Path) -> None:
    iso, _ch, d = _channel(tmp_path)
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps(_spec(tmp_path, iso, None, d)))
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "sandbox_exec", "arguments": {"argv": ["echo", "via-stdio"]}}}]
    cp = subprocess.run(["uv", "run", "--script", "--quiet", str(eh.HERE / "eq_harness.py"), "member-exec", "--spec",
                         str(spec)], input="\n".join(json.dumps(m) for m in msgs) + "\nnot json\n",
                        capture_output=True, text=True, check=False, env=dict(os.environ))
    out = [json.loads(ln) for ln in cp.stdout.splitlines()]
    assert [o.get("id") for o in out] == [1, 2, None] and out[2]["error"]["code"] == -32700
    assert "via-stdio" in out[1]["result"]["content"][0]["text"]


def test_eqbox_server_reads_no_uv_config_and_runs_from_a_fixed_cwd(tmp_path: Path, wenv: dict[str, str],
                                                                   clog: Path) -> None:
    """N23 focus 7: claude starts the eqbox server in the member's cwd with the member's environment; uv then read
    the user-level uv.toml (a file a host-side member can write) before running the server. The MCP entry now says
    `uv run --no-config --directory /` (uv 0.12.22 already ignores a cwd uv.toml for --script: the fixed cwd is
    defence in depth)."""
    iso, _ch, d = _channel(tmp_path)
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps(_spec(tmp_path, iso, None, d)))
    cfg = eh.member_exec_mcp_config(spec)["mcpServers"]["eqbox"]
    assert cfg["command"] == "uv" and cfg["args"][:5] == ["run", "--no-config", "--directory", "/", "--script"]
    member = tmp_path / "member"
    member.mkdir()
    for name, body in (("uv.toml", "x = = y\n"), ("pyproject.toml", "[project\n"), (".python-version", "3.99\n")):
        (member / name).write_text(body)
    xdg = tmp_path / "xdg"
    (xdg / "uv").mkdir(parents=True)
    (xdg / "uv" / "uv.toml").write_text("x = = y\n")  # a hostile user-level uv config
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}]
    cp = subprocess.run([cfg["command"], *cfg["args"]], cwd=member, input=json.dumps(msgs[0]) + "\n",
                        capture_output=True, text=True, check=False, env=dict(os.environ, XDG_CONFIG_HOME=str(xdg)))
    out = [json.loads(ln) for ln in cp.stdout.splitlines()]
    assert out and out[0]["result"]["serverInfo"]["name"] == "eqbox", cp.stderr


# ---------------------------------------------------------------------------------------------------------------------
# run: gate, lifecycle, ledger
# ---------------------------------------------------------------------------------------------------------------------


def boxed_flags(**over: Any) -> dict[str, Any]:
    """The fixture pools give ES Bash too (the real pools: PF, CP, CR only), so ES needs an image when boxed."""
    return container_fixt_flags(container_images={"PF": IMG, "CP": IMG, "CR": IMG, "ES": IMG}, **over)


def _run(stub_bin: Path, tmp: Path, flags: dict[str, Any], env_extra: dict[str, str]) -> tuple[Any, Path]:
    sched = tmp / "schedule.tsv"
    env = stub_env(stub_bin, tmp, EQ_FAKE_CONTAINER_LOG=str(tmp / "container.log"), **env_extra)
    assert run_harness(["schedule", "--items", str(ITEMS), "--stage", "d", "--out", str(sched)], env).returncode == 0
    (tmp / "flags.json").write_text(json.dumps(flags))
    cp = run_harness(["run", "--stage", "d", "--eq-root", str(tmp / "eq"), "--raw-root", str(tmp / "raw"), "--items",
                      str(ITEMS), "--flags", str(tmp / "flags.json"), "--schedule", str(sched), "--no-check",
                      "--only", "PF-DEV1"], env)
    return cp, tmp


def test_run_refuses_without_a_passing_tunnel_probe(stub_bin: Path, tmp_path: Path, wenv: dict[str, str]) -> None:
    f = boxed_flags(wall=wall_section(), member_exec="sandbox")
    cp, tmp = _run(stub_bin, tmp_path, f, wenv)
    assert cp.returncode == 2 and "no tunnel probe receipt" in cp.stderr
    assert not (tmp / "stub_log.jsonl").exists() and ledger(tmp) == []
    receipt(Path(wenv["EQ_WALL_STATE_DIR"]), f, "FAIL")
    cp, tmp = _run(stub_bin, tmp_path, f, wenv)
    assert cp.returncode == 2 and "did not PASS" in cp.stderr and ledger(tmp) == []


def test_run_with_the_wall_records_nonce_channels_and_audit(stub_bin: Path, tmp_path: Path,
                                                            wenv: dict[str, str]) -> None:
    f = boxed_flags(wall=wall_section(), member_exec="sandbox")
    state = Path(wenv["EQ_WALL_STATE_DIR"])
    receipt(state, f)
    cp, tmp = _run(stub_bin, tmp_path, f, wenv)
    assert cp.returncode == 0, cp.stderr
    recs = ledger(tmp)
    start = next(r for r in recs if r["record"] == "run_start")
    w = start["wall"]
    assert w["enabled"] and w["config_sha256"] == f["wall"]["config_sha256"] and start["member_exec"] == "sandbox"
    nonce = (state / "runs" / w["run_id"] / "nonce.revealed").read_text().strip()
    assert eh.sha256_text(nonce) == w["nonce_sha256"] and nonce not in json.dumps(recs)  # committed, not logged
    wrecs = [r for r in recs if r["record"] == "wall"]
    kinds = [r["wall_record"] for r in wrecs]
    assert kinds[0] == "broker_start" and kinds[-1] == "broker_stop"
    boxed = [r for r in recs if r["record"] == "call" and r.get("member_exec") == "sandbox"]
    assert boxed and all(r["wall_channel"] for r in boxed)
    assert kinds.count("channel_open") == kinds.count("channel_close") == len(boxed)
    assert all("raw_b64" not in r for r in wrecs)
    for r in boxed:
        argv = r["argv"]
        tools = argv[argv.index("--allowedTools") + 1:]
        assert "Bash" not in tools[:tools.index("--disallowedTools")] and eh.MEMBER_EXEC_TOOL in tools
        assert argv[argv.index("--mcp-config") + 1].count("member-exec") == 1
    arms = [r for r in recs if r["record"] == "item_arm"]
    assert arms and all(r["wall_requests"] == 0 and r["wall_used"] is False for r in arms)
    ew = eh.load_wall_module(WALLDIR / "eq_wall.py", eh.sha256_file(WALLDIR / "eq_wall.py"))
    assert len(ew.verify_audit(state / "audit" / f"{w['run_id']}.jsonl")) == len(wrecs)
    assert ew.replay(state, w["run_id"], POLICY, state / "verdicts.jsonl", state / "consents.jsonl") == []
    assert list((Path(wenv["EQ_TUNNEL_DIR"]) / w["run_id"]).iterdir()) == []  # every channel removed
    documented = set(re.findall(r"`([A-Za-z_0-9]+)`", (eh.HERE / "LEDGER_SCHEMA.md").read_text()))
    for r in recs:  # every field of a WALL run is in LEDGER_SCHEMA.md
        assert not set(r) - documented, (r["record"], set(r) - documented)
    assert set(start["wall"]) <= documented
    # one configuration per ledger: the same stage without the WALL is refused
    shutil.rmtree(tmp / "raw")
    cp2, _ = _run(stub_bin, tmp_path, boxed_flags(), wenv)
    assert cp2.returncode == 2 and "another WALL / member_exec configuration" in cp2.stderr


def test_broken_audit_chain_is_an_isolation_error(tmp_path: Path, wenv: dict[str, str]) -> None:
    f = wflags()
    w = eh.Wall(f, eh.Isolation(f))
    w.start()
    led = eh.Ledger(tmp_path / "ledger.jsonl")
    w.stop(led, "d")
    assert [r["wall_record"] for r in eh.read_ledger(led.path)] == ["broker_start", "broker_stop"]
    lines = w.audit_path.read_text().splitlines()
    lines[0] = lines[0].replace('"broker_start"', '"broker_restart"')
    w.audit_path.write_text("\n".join(lines) + "\n")
    with pytest.raises(eh.IsolationError, match="audit log"):
        w.import_audit(led, "d")


def test_each_channel_carries_the_frozen_client(tmp_path: Path, wenv: dict[str, str]) -> None:
    """The member's only WALL interface inside the container is /eq/tunnel/eq_wall_client.py: the harness writes the
    bytes it hash-checked at start (wall.client_sha256), never a file re-read later."""
    f = wflags()
    w = eh.Wall(f, eh.Isolation(f))
    w.start()
    try:
        ch = w.open_channel("PF-0001", "p1", "00001_member")
        got = ch.host_dir / "eq_wall_client.py"
        assert got.read_bytes() == (WALLDIR / "eq_wall_client.py").read_bytes()
        assert eh.sha256_file(got) == f["wall"]["client_sha256"] and (got.stat().st_mode & 0o777) == 0o600
        w.close_channel(ch, eh.Ledger(tmp_path / "ledger.jsonl"), "d")
    finally:
        w.stop(eh.Ledger(tmp_path / "ledger.jsonl"), "d")


def test_member_exec_needs_container(stub_bin: Path, tmp_path: Path) -> None:
    from conftest import FIXT_FLAGS
    f = dict(json.loads(json.dumps(FIXT_FLAGS)), member_exec="sandbox")
    cp, tmp = _run(stub_bin, tmp_path, f, {})
    assert cp.returncode == 2 and "'sandbox' needs container" in cp.stderr and ledger(tmp) == []


# ---------------------------------------------------------------------------------------------------------------------
# isolation-probe: the tunnel case and its receipt
# ---------------------------------------------------------------------------------------------------------------------


def test_isolation_probe_runs_the_tunnel_case_and_writes_the_receipt(tmp_path: Path, wenv: dict[str, str],
                                                                     clog: Path) -> None:
    fl = tmp_path / "flags.json"
    f = wflags(container_work_size="4K")
    fl.write_text(json.dumps(f))
    (tmp_path / "probe.sh").write_text("echo PROBE-RAN; exit 0\n")
    (tmp_path / "probe_inner.sh").write_text('echo "T|inner_ran|PASS|"\n')
    env = dict(os.environ, **wenv)
    cp = run_harness(["isolation-probe", "--flags", str(fl), "--script", str(tmp_path / "probe.sh"),
                      "--tunnel-script", str(TSCRIPT)], env)
    out = cp.stdout
    assert re.search(r"tunnel_only_extra_mount\s+PASS", out), out + cp.stderr
    assert re.search(r"tunnel_roundtrip\s+PASS", out)  # the fake maps /eq/tunnel to the channel dir
    assert re.search(r"host_paths_absent\s+FAIL", out)  # the fake runs on the host: reported, never guessed
    rec = json.loads((Path(wenv["EQ_WALL_STATE_DIR"]) / "tunnel_probe.json").read_text())
    assert rec["result"] == "FAIL" and rec["config_sha256"] == f["wall"]["config_sha256"]
    assert cp.returncode == 1
    tunnel_runs = [c for c in calls(clog) if c[0] == "run" and any("target=/eq/tunnel" in x for x in c)]
    assert len(tunnel_runs) == 1  # one image in dflags -> one tunnel container
    assert str(FAKE)  # the fake CLI, never the real services


def test_isolation_probe_requires_every_tunnel_row(tmp_path: Path, wenv: dict[str, str], clog: Path) -> None:
    """A tunnel probe that dies early (or an image whose shell prints garbage) must never yield a PASS receipt: every
    in-container row is required, and a result other than PASS/FAIL/INFO is a FAIL."""
    fl = tmp_path / "flags.json"
    f = wflags(container_work_size="4K")
    fl.write_text(json.dumps(f))
    (tmp_path / "probe.sh").write_text("echo PROBE-RAN; exit 0\n")
    (tmp_path / "probe_inner.sh").write_text('echo "T|inner_ran|PASS|"\n')
    short = tmp_path / "short-tunnel.sh"  # writes the round-trip file, reports two rows, then "crashes"
    short.write_text('printf probe > "$5/req-probe.json"\necho "T|tunnel_writable|PASS|ok"\n'
                     'echo "T|outbound_blocked|MAYBE|garbage"\nexit 0\n')
    cp = run_harness(["isolation-probe", "--flags", str(fl), "--script", str(tmp_path / "probe.sh"),
                      "--tunnel-script", str(short)], dict(os.environ, **wenv))
    out = cp.stdout
    assert re.search(r"tunnel_roundtrip\s+PASS", out), out + cp.stderr
    assert re.search(r"outbound_blocked\s+FAIL", out)  # MAYBE is not a result
    for need in ("tunnel_single_host_mount", "host_paths_absent", "host_signal_blocked", "no_inherited_fds"):
        assert re.search(rf"{need}\s+FAIL\s+the in-container tunnel probe did not report this row", out), need
    rec = json.loads((Path(wenv["EQ_WALL_STATE_DIR"]) / "tunnel_probe.json").read_text())
    assert rec["result"] == "FAIL" and cp.returncode == 1


# ---------------------------------------------------------------------------------------------------------------------
# probe.d/50-tunnel.sh under probe.sh's hook contract (section G): `T|name|RESULT|detail` rows; no row, or a non-zero
# exit without a FAIL row, is a FAIL. Fake container CLI (it runs the in-container half on the host, so the isolation
# rows FAIL here by construction: what is checked is the contract, the image under probe and the positive control).
# ---------------------------------------------------------------------------------------------------------------------
PROBE_TAG = "eq.invalid/eq-probe-under-test:1"


def _hook_env(tmp_path: Path, clog: Path, *, down: bool = False) -> dict[str, str]:
    assert CDIR is not None
    env = dict(os.environ, EQ_CONTAINER_BIN=str(FAKE), EQ_HOST_ARCH="arm64", EQ_FAKE_CONTAINER_LOG=str(clog),
               EQ_STATE_DIR=str(tmp_path / "isostate"), EQ_ALLOW_UNRECORDED="1", EQ_PROBE_HOOK=str(TSCRIPT),
               EQ_PROBE_IMAGE=f"{PROBE_TAG}@{DIGEST}", EQ_PROBE_LIB=str(CDIR / "lib.sh"),
               EQ_FAKE_CONTAINER_DOWN="1" if down else "0")
    for k in ("EQ_IMAGE", "EQ_RUN_IMAGE", "EQ_WORK_ROOT", "EQ_NO_STATE_WRITE"):
        env.pop(k, None)
    return env


def _hook_rows(out: str) -> list[list[str]]:
    return [ln.split("|", 3) for ln in out.splitlines() if ln.startswith("T|")]


@needs_cdir
def test_tunnel_hook_meets_the_probe_d_contract(tmp_path: Path, clog: Path) -> None:
    cp = subprocess.run(["bash", str(TSCRIPT)], env=_hook_env(tmp_path, clog), capture_output=True, text=True,
                        check=False, timeout=300, cwd=tmp_path)  # cwd: probe.sh runs hooks from a writable dir
    rows = _hook_rows(cp.stdout)
    names = {r[1]: r[2] for r in rows}
    assert rows, cp.stdout + cp.stderr  # a hook without rows is a FAIL in probe.sh
    assert all(r[2] in ("PASS", "FAIL", "INFO") for r in rows)
    assert cp.returncode == 0 or "FAIL" in names.values()  # never a non-zero exit without a FAIL row
    for need in (*eh.TUNNEL_PROBE_REQUIRED, "tunnel_roundtrip", "host_process_unsignalled",
                 "sibling_channel_unchanged"):
        assert need in names, (need, cp.stdout)
    assert names["tunnel_roundtrip"] == "PASS"  # positive control: /eq/tunnel reached the host channel
    assert names["host_signal_blocked"] == "FAIL" and cp.returncode == 1  # the fake shares the host PID space
    cs = calls(clog)
    run = next(c for c in cs if c[0] == "run")
    tun = [x for x in run if "target=/eq/tunnel" in x]
    assert len(tun) == 1  # ONE extra mount
    # the image probe.sh names is the one verified (its digest, by TAG, right before the run), and the run names the TAG
    assert any(c[:2] == ["image", "inspect"] and c[-1] == PROBE_TAG for c in cs[:cs.index(run)])
    assert PROBE_TAG in run and not any("@sha256:" in x for x in run)


@needs_cdir
def test_tunnel_hook_without_the_probe_image_stops_before_any_container_call(tmp_path: Path, clog: Path) -> None:
    """Hook mode probes only the image probe.sh names: without EQ_PROBE_IMAGE it stops at once (non-zero, no row,
    so probe.sh counts a FAIL) and never falls back to the profile image or asks the CLI anything."""
    env = _hook_env(tmp_path, clog)
    env.pop("EQ_PROBE_IMAGE")
    cp = subprocess.run(["bash", str(TSCRIPT)], env=env, capture_output=True, text=True, check=False, timeout=60,
                        cwd=tmp_path)
    assert cp.returncode != 0 and _hook_rows(cp.stdout) == [], cp.stdout + cp.stderr
    assert "probe.sh sets EQ_PROBE_IMAGE for its hooks" in cp.stderr
    assert calls(clog) == []


@needs_cdir
def test_tunnel_hook_reports_a_fail_row_when_the_services_are_down(tmp_path: Path, clog: Path) -> None:
    cp = subprocess.run(["bash", str(TSCRIPT)], env=_hook_env(tmp_path, clog, down=True), capture_output=True,
                        text=True, check=False, timeout=60, cwd=tmp_path)
    assert cp.returncode != 0 and _hook_rows(cp.stdout) == [
        ["T", "tunnel_container", "FAIL", "the container CLI or its services are not usable (eq_need_container)"]]
