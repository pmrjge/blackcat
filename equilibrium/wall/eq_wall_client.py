# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""In-container WALL client (stdlib only): writes ONE structured request into the tunnel (/eq/tunnel) and waits for
the broker's response, validating it against eqwall.response.v1. Identity and token come from
/eq/tunnel/.channel.json (written by the harness before the mount). Nothing here can approve anything: the broker
decides on the host.

  python3 eq_wall_client.py missing-tool --tool T --arg name:type:value ... --justification "..." [-- argv...]
  python3 eq_wall_client.py web-research --url https://host/path --justification "..."

Exit 0 = approved (the response JSON on stdout), 3 = denied, 4 = error/timeout, 2 = usage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Any

REQ_SCHEMA = "eqwall.request.v1"
RESP_SCHEMA = "eqwall.response.v1"
RESP_KEYS = {"schema", "request_id", "decision", "reason", "next", "summary", "output_path", "output_sha256",
             "output_bytes", "data_notice", "audit_seq"}


def canon(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def content_hash(req: dict[str, Any]) -> str:
    body = {k: v for k, v in req.items() if k not in ("content_sha256", "token")}
    return hashlib.sha256(b"EQWALL-CONTENT-V1\0" + canon(body)).hexdigest()


def build_request(info: dict[str, Any], kind: str, tool: str, justification: str, *, argv: list[str] | None = None,
                  url: str | None = None, args: list[dict[str, Any]] | None = None,
                  request_id: str | None = None) -> dict[str, Any]:
    req: dict[str, Any] = {"schema": REQ_SCHEMA, "request_id": request_id or secrets.token_hex(16),
                           "run_id": info["run_id"], "item": info["item"], "arm": info["arm"],
                           "channel": info["channel"], "kind": kind, "tool": tool, "args": args or [],
                           "justification": justification}
    if argv is not None:
        req["argv"] = argv
    if url is not None:
        req["url"] = url
    req["content_sha256"] = content_hash(req)
    req["token"] = info["token"]
    return req


def check_response(obj: Any, rid: str) -> dict[str, Any]:
    if not isinstance(obj, dict) or set(obj) != RESP_KEYS or obj.get("schema") != RESP_SCHEMA:
        raise ValueError("response does not match eqwall.response.v1")
    if obj["request_id"] != rid or obj["decision"] not in ("approved", "denied", "error"):
        raise ValueError("response for another request, or a bad decision")
    if obj["output_path"] is not None and not str(obj["output_path"]).startswith("/eq/tunnel/out-"):
        raise ValueError("output_path outside the tunnel")
    if len(json.dumps(obj)) > 16384:
        raise ValueError("response too large")
    return obj


def send(tunnel: Path, req: dict[str, Any], timeout_s: float = 120.0, poll_s: float = 0.1) -> dict[str, Any]:
    rid = req["request_id"]
    tmp = tunnel / f".req-{rid}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, canon(req))
    finally:
        os.close(fd)
    os.rename(tmp, tunnel / f"req-{rid}.json")  # atomic: the broker never sees a half-written request
    deadline = time.monotonic() + timeout_s
    resp = tunnel / f"resp-{rid}.json"
    while time.monotonic() < deadline:
        try:
            fd = os.open(resp, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            time.sleep(poll_s)
            continue
        try:
            data = os.read(fd, 65536)
        finally:
            os.close(fd)
        return check_response(json.loads(data), rid)
    raise TimeoutError(f"no WALL response for {rid} within {timeout_s:.0f}s")


def parse_arg(spec: str) -> dict[str, Any]:
    name, typ, value = spec.split(":", 2)
    return {"name": name, "type": typ, "value": int(value) if typ == "int" else value}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="eq_wall_client.py")
    p.add_argument("kind", choices=["web-research", "missing-tool", "other"])
    p.add_argument("--tunnel", default="/eq/tunnel")
    p.add_argument("--tool", default="fetch")
    p.add_argument("--url")
    p.add_argument("--arg", action="append", default=[], help="name:type:value (type enum|int|str|infile)")
    p.add_argument("--justification", required=True)
    p.add_argument("--timeout", type=float, default=120.0)
    p.add_argument("rest", nargs="*", help="exact argv after --: the tool name then the rendered args")
    a = p.parse_args(argv)
    tunnel = Path(a.tunnel)
    try:
        info = json.loads((tunnel / ".channel.json").read_text())
        args = [parse_arg(s) for s in a.arg]
    except (OSError, ValueError) as e:
        print(f"eq_wall_client: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    argv_req = None if a.kind == "web-research" else (a.rest or None)
    req = build_request(info, a.kind, a.tool, a.justification, argv=argv_req, url=a.url, args=args)
    try:
        resp = send(tunnel, req, a.timeout)
    except (OSError, ValueError, TimeoutError) as e:
        print(f"eq_wall_client: {type(e).__name__}: {e}", file=sys.stderr)
        return 4
    print(json.dumps(resp, indent=1))
    return 0 if resp["decision"] == "approved" else 3 if resp["decision"] == "denied" else 4


if __name__ == "__main__":
    sys.exit(main())
