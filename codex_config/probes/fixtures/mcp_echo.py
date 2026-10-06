#!/usr/bin/env python3
"""Trivial stdio MCP server (stdlib only): one tool, probe_echo. Logs every request method to argv[1]."""
import json
import sys

LOG = sys.argv[1] if len(sys.argv) > 1 else None


def log(line):
    if LOG:
        with open(LOG, "a") as f:
            f.write(line + "\n")


def send(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


for raw in sys.stdin:
    raw = raw.strip()
    if not raw:
        continue
    try:
        req = json.loads(raw)
    except ValueError:
        continue
    method, rid = req.get("method"), req.get("id")
    log("method=%s" % method)
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": (req.get("params") or {}).get("protocolVersion", "2024-11-05"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "probe_echo", "version": "0"}}})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": rid, "result": {"tools": [{
            "name": "probe_echo", "description": "Echo the given text back (probe fixture).",
            "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}]}})
    elif method == "tools/call":
        text = ((req.get("params") or {}).get("arguments") or {}).get("text", "")
        log("tools/call text=%s" % text)
        send({"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": "echo:" + text}]}})
    elif rid is not None:
        send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "unsupported"}})
