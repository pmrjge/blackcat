"""hook_defs: the guard's inline hook definitions and their trust keys (INTERFACES.md §3-C).

hooks_table(stub, scope="profile") -> the `hooks` table a profile file (or the --ide-default region)
carries, without `state`: one matcher group per event, one command handler each,
`/bin/sh '<stub>' <mode>` (+ ` --scope global`), timeout 10 s (SessionEnd 3 s), matcher ".*" on the
three tool events (DESIGN.md §8.5; config.schema.json MatcherGroup / HookHandlerConfig).

hook_keys(source_file, table) -> [{"key", "event", "fingerprint"}]: the key Codex stores trust under,
`<source_file>:<snake_event>:<group>:<handler>` (DESIGN F11), and a fingerprint, the sha256 of the
canonical JSON of {event, matcher, handler}: it changes exactly when the definition Codex hashes
changes (command, timeout, matcher, ...), never with the script's bytes (DESIGN §4.4).

Stdlib only; Python >= 3.9 (it never imports tomllib). Seeded-bug proofs (tests/mutations/hook_defs.json):
SessionEnd's timeout set to 10, the matcher dropped from PreToolUse, the stub path left unquoted,
the fingerprint ignoring the matcher, a CamelCase event in the key, `--scope global` dropped.
"""
import hashlib
import json
import re

EVENTS = ("PreToolUse", "PermissionRequest", "PostToolUse", "SubagentStart", "SubagentStop",
          "UserPromptSubmit", "SessionStart", "SessionEnd")
TOOL_EVENTS = ("PreToolUse", "PermissionRequest", "PostToolUse")
TIMEOUT_S, SESSION_END_TIMEOUT_S = 10, 3
MATCH_ALL = ".*"
# characters the stub path may hold: it is single-quoted in an sh command, so no quote, no control
# characters (the installer's BAD_PATH_CHARS refuse more)
_PATH_OK = re.compile(r"/[^'\x00-\x1f\x7f]*\Z")


class BuildError(Exception):
    """A stub path that cannot be written into a hook command."""


def snake(event):
    """PreToolUse -> pre_tool_use (the guard's mode names and the trust-key segment)."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", event).lower()


def command_for(stub, event, scope="profile"):
    if not isinstance(stub, str) or not _PATH_OK.match(stub):
        raise BuildError("the stub path must be absolute, without ' or control characters: %r"
                         % (stub,))
    if scope not in ("profile", "global"):
        raise BuildError("scope must be profile or global, not %r" % (scope,))
    cmd = "/bin/sh '%s' %s" % (stub, snake(event))
    return cmd + " --scope global" if scope == "global" else cmd


def hooks_table(stub, scope="profile"):
    table = {}
    for event in EVENTS:
        handler = {"type": "command", "command": command_for(stub, event, scope),
                   "timeout": SESSION_END_TIMEOUT_S if event == "SessionEnd" else TIMEOUT_S}
        group = {"hooks": [handler]}
        if event in TOOL_EVENTS:
            group = {"matcher": MATCH_ALL, "hooks": [handler]}
        table[event] = [group]
    return table


def fingerprint(event, matcher, handler):
    blob = json.dumps({"event": event, "matcher": matcher, "handler": handler}, sort_keys=True,
                      separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode("ascii")).hexdigest()


def hook_keys(source_file, table):
    out = []
    for event in sorted(table, key=lambda e: EVENTS.index(e) if e in EVENTS else len(EVENTS)):
        if event == "state":
            continue
        for g, group in enumerate(table[event]):
            for h, handler in enumerate(group.get("hooks", [])):
                out.append({"key": "%s:%s:%d:%d" % (source_file, snake(event), g, h),
                            "event": event,
                            "fingerprint": fingerprint(event, group.get("matcher"), handler)})
    return out
