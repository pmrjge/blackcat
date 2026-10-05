"""WALL test fixtures: FAKES ONLY. Every tool the broker may run is a throwaway script in tmp; no network, no docker,
no real host action. Run from STAGE:
uv run --no-project --with pytest pytest -q -p no:cacheprovider wall/tests
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import os
import secrets
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

WALL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WALL))

import eq_wall as ew  # noqa: E402
import eq_wall_client as wc  # noqa: E402


def toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return json.dumps(v)
    if isinstance(v, list):
        return "[" + ", ".join(toml_value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{k} = {toml_value(x)}" for k, x in v.items()) + " }"
    raise TypeError(type(v))


def policy_toml(kinds: list[str] | None = None, tools: list[dict[str, Any]] | None = None,
                domains: list[str] | None = None, fetch: tuple[str, str] | None = None,
                manifest: str | None = None, required: bool = True, limits: dict[str, int] | None = None,
                extra: str = "") -> str:
    out = ['schema = "eqwall.policy.v1"', "[limits]"]
    out += [f"{k} = {v}" for k, v in (limits or {}).items()]
    out += ["[kinds]", f"allowed = {toml_value(kinds or [])}", "[web]"]
    if fetch:
        out += [f"fetch_command = {toml_value(fetch[0])}", f"fetch_command_sha256 = {toml_value(fetch[1])}"]
    out += [f"domains = {toml_value(domains or [])}", "[tools_manifest]"]
    if manifest is not None:
        out.append(f"path = {toml_value(manifest)}")
    out.append(f"required = {toml_value(required)}")
    for t in tools or []:
        out.append("[[tool]]")
        out += [f"{k} = {toml_value(v)}" for k, v in t.items()]
    return "\n".join(out) + "\n" + extra


@dataclasses.dataclass
class W:
    root: Path
    tunnel: Path
    state: Path
    run_id: str
    nonce: str
    bin: Path
    brokers: list[ew.Broker] = dataclasses.field(default_factory=list)

    # -- fakes -----------------------------------------------------------------------------------------------------
    def tool_script(self, name: str, body: str) -> tuple[str, str]:
        p = self.bin / name
        p.write_text("#!/bin/sh\n" + body + "\n")
        p.chmod(0o755)
        return str(p), ew.sha256_file(p)

    def tool(self, name: str = "faketool", body: str = 'echo "ARGS:$*"', **over: Any) -> dict[str, Any]:
        cmd, sha = self.tool_script(name, body)
        t = {"name": name, "kind": "missing-tool", "command": cmd, "command_sha256": sha, "fixed_args": [],
             "args": [{"name": "mode", "type": "enum", "values": ["fast", "full"]},
                      {"name": "n", "type": "int", "min": 1, "max": 9},
                      {"name": "word", "type": "str", "pattern": "[-a-z$()]{1,16}"}],
             "externally_visible": False, "destructive": False, "timeout_s": 20, "max_output_bytes": 65536}
        t.update(over)
        return t

    def policy(self, name: str = "policy.toml", **kw: Any) -> Path:
        p = self.root / name
        p.write_text(policy_toml(**kw))
        return p

    @property
    def verdicts(self) -> Path:
        return self.state / "verdicts.jsonl"

    @property
    def consents(self) -> Path:
        return self.state / "consents.jsonl"

    def broker(self, policy: Path, nonce: str | None = None) -> ew.Broker:
        b = ew.Broker(state_dir=self.state, tunnel_root=self.tunnel, run_id=self.run_id, nonce=nonce or self.nonce,
                      policy=ew.load_policy(policy), verdicts_path=self.verdicts, consents_path=self.consents)
        self.brokers.append(b)
        return b

    # -- the user's stores (written by the test acting as the user) ------------------------------------------------
    def verdict(self, cls: str, **over: Any) -> None:
        rec = {"class_sha256": cls, "tool": "t", "verdict": "pass", "reviewer": "security-auditor",
               "review_ref": "test", "open_high_critical": 0}
        rec.update(over)
        ew.append_store(self.verdicts, rec, ew.VERDICT_SCHEMA)

    def consent(self, action: str, run_id: str | None = None) -> None:
        ew.append_store(self.consents, {"action_sha256": action, "run_id": run_id or self.run_id,
                                        "granted_by": "user", "statement": "test"}, ew.CONSENT_SCHEMA)

    # -- the container side (simulated: it writes into the channel dir) --------------------------------------------
    def channel(self, item: str = "PF-0001", arm: str = "p1") -> ew.Channel:
        return ew.open_channel(self.tunnel, self.state, self.run_id, self.nonce, item, arm, "p1")

    def info(self, ch: ew.Channel) -> dict[str, Any]:
        return json.loads((ch.host_dir / ew.CHANNEL_FILE).read_text())

    def req(self, ch: ew.Channel, kind: str = "missing-tool", tool: str = "faketool", **kw: Any) -> dict[str, Any]:
        if kind != "web-research":
            kw.setdefault("argv", [tool, "fast", "3", "abc"])
            kw.setdefault("args", [{"name": "mode", "type": "enum", "value": "fast"},
                                   {"name": "n", "type": "int", "value": 3},
                                   {"name": "word", "type": "str", "value": "abc"}])
        return wc.build_request(self.info(ch), kind, tool, kw.pop("justification", "needed for the item check"),
                                **kw)

    def put(self, ch: ew.Channel, req: dict[str, Any] | bytes, rid: str | None = None) -> str:
        if isinstance(req, dict):
            rid = rid or req["request_id"]
            data = ew.canon(req)
        else:
            rid = rid or secrets.token_hex(16)
            data = req
        (ch.host_dir / f"req-{rid}.json").write_bytes(data)
        return rid

    def resp(self, ch: ew.Channel, rid: str) -> dict[str, Any]:
        obj = json.loads((ch.host_dir / f"resp-{rid}.json").read_text())
        return wc.check_response(obj, rid)

    def ask(self, b: ew.Broker, ch: ew.Channel, req: dict[str, Any] | bytes, rid: str | None = None
            ) -> dict[str, Any]:
        rid = self.put(ch, req, rid)
        b.poll_once()
        return self.resp(ch, rid)

    def audit(self) -> list[dict[str, Any]]:
        return ew.verify_audit(self.state / "audit" / f"{self.run_id}.jsonl")


@pytest.fixture
def w(tmp_path: Path) -> Any:
    root = tmp_path.resolve()
    tunnel, state, bin_ = root / "tunnel", root / "state", root / "bin"
    for d in (tunnel, state, bin_):
        d.mkdir(mode=0o700)
    run_id = uuid.uuid4().hex
    ew.prepare_run(tunnel, state, run_id)
    ww = W(root, tunnel, state, run_id, secrets.token_hex(32), bin_)
    yield ww
    for b in ww.brokers:
        b.audit.close()
        with contextlib.suppress(OSError):
            os.close(b.run_fd)
