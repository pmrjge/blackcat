"""Hook entry: `stack_hook.py [--fail-closed] <module> [args...]` (launched by bin/stack-hook).

Imports hooks/<module>.py as a module, so its bytecode is cached in hooks/__pycache__ (timestamp
pyc; a script run as __main__ is recompiled on every call), and calls main() exactly as the
module's own `if __name__ == "__main__"` block does: same argv, stdin, stdout and exit code.
Not carried over: DeprecationWarnings raised in hook code (Python shows them only for __main__) and
compile-time SyntaxWarnings (shown only when the pyc is rewritten). An
import that fails (missing or corrupt pyc body, SyntaxError, ...) falls back to running the source
as __main__ (the direct-script path). If that fails too, or the module or interpreter is wrong:
with --fail-closed (PreToolUse entries) the guard's own guard_error deny, else exit 0 and stderr.
Kept parseable by old interpreters so the version check below can report itself."""
import json
import os
import sys

sys.pycache_prefix = None            # bytecode beside the source, in the protected hooks/__pycache__
sys.dont_write_bytecode = False      # a missing or stale pyc is rewritten once, not recompiled per call
HOOKS = os.path.dirname(os.path.abspath(__file__))   # as invoked: __file__ and argv[0] as a direct run
# hook module -> True: main(sys.argv), False: main(sys.argv[1:]), as in each module's __main__ block
MODULES = {"agent_guard": True, "stack_usage": True, "read_gate": False, "web_caps": False}
HINT = ("claude-agent-stack hook error (see above). If it persists: run ./install.sh from the stack "
        "repo, or set \"STACK_POLICY\": \"off\" in the env block of ~/.claude/settings.json to bypass "
        "the stack policy.")
# the no-push entry is absolute (agent_guard.py: "not switched off by STACK_POLICY=off"): a start
# failure there denies even under STACK_POLICY=off, so Bash stays blocked until ./install.sh
ABSOLUTE = ("agent_guard", "no-push")
HINT_ABSOLUTE = ("claude-agent-stack hook error (see above): the no-push guard cannot start, so Bash "
                 "stays blocked (STACK_POLICY=off never lifts no-push). Run ./install.sh from the stack repo.")


def fail(closed, what, absolute=False):
    if closed and (absolute or os.environ.get("STACK_POLICY", "on").strip().lower() != "off"):
        sys.stdout.write(json.dumps({  # agent_guard.guard_error's deny, verbatim shape
            "hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": "stack guard error: %s. Report STATUS: "
                                   "blocked with this message; do not retry." % what},
            "systemMessage": "%s (%s)" % (HINT_ABSOLUTE if absolute else HINT, what)}))
    else:
        sys.stderr.write("stack_hook: %s\n" % what)
    sys.stdout.flush()
    sys.exit(0)


def run(argv):
    closed = argv[:1] == ["--fail-closed"]
    argv = argv[1:] if closed else argv
    name = argv[0] if argv else ""
    absolute = tuple(argv[:2]) == ABSOLUTE
    if name not in MODULES:          # an allow-list: no paths, no other modules
        fail(closed, "unknown hook module %r" % name[:80])
    if sys.version_info < (3, 13):  # noqa: UP036 - the stack-python symlink may point at anything
        fail(closed, "hook %s needs Python >= 3.13, %s runs %d.%d (run ./install.sh)"
             % (name, sys.executable, sys.version_info[0], sys.version_info[1]), absolute)
    src = os.path.join(HOOKS, name + ".py")
    sys.argv = [src] + argv[1:]
    sys.path.insert(0, HOOKS)
    try:
        mod = __import__(name)
        if os.path.realpath(mod.__file__) != os.path.realpath(src):
            raise ImportError("%s loaded from %s" % (name, mod.__file__))
    except Exception as exc:  # noqa: BLE001 - bad pyc body (ValueError), SyntaxError, ImportError, ...
        sys.modules.pop(name, None)
        try:
            import importlib.util
            import runpy
            try:                     # a bad pyc is dropped: the next call's import rewrites it
                os.unlink(importlib.util.cache_from_source(src))
            except OSError:
                pass
            runpy.run_path(src, run_name="__main__")
        except Exception as exc2:  # noqa: BLE001
            fail(closed, "hook %s failed to start (%s: %s; then %s: %s)"
                 % (name, type(exc).__name__, exc, type(exc2).__name__, exc2), absolute)
        return 0
    return mod.main(sys.argv if MODULES[name] else sys.argv[1:])


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
