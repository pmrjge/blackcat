#!/usr/bin/env python3
"""codex_guard: the claude-agent-stack guard hook for the Codex CLI (stdlib only, Python >= 3.9, POSIX).

Run by the POSIX sh stub `codex-hook` as `codex_guard.py <mode> [--scope global]`, the hook event JSON
on stdin (Codex rust-v0.160.1, hooks/src/schema.rs). Modes and what each does (DESIGN.md §4, §5, §8.5):

  pre_tool_use        the gate. Profile-neutral checks first (also in `--scope global`, the managed
                      tier): no push and no forge write in any shell form (a port of agent_guard's
                      no-push scanner; tests/test_no_push.py is its oracle), no `codex -c/--config/
                      --dangerously-*`, no Bash-level write/rename/chmod/delete under a protected root
                      (CODEX_HOME, ~/.agents, the guard state), no credential path (Codex's auth.json,
                      stack.env, the credential set) through shell, apply_patch, view_image or MCP path
                      arguments, apply_patch paths resolved against cwd with symlinks resolved. Then the
                      stack policy (profile scope only): the caller is the canonical agent_type
                      (lowercase, `_` -> `-`); no agent_type = the main thread = the `blackcat` row
                      (delegate only: spawn_agent, the multi_agent_v1 tools, update_plan,
                      request_user_input, a few read-only shell calls per prompt); built-in, generic
                      and unknown types run nothing; per-role tool classes (shell, apply_patch, spawn,
                      MCP servers), read-only roles (shell held to a read-only allowlist), the spawn
                      rows (target in the caller's row, model/reasoning_effort stripped through
                      updatedInput), send_input/resume_agent/close_agent routed against the session's
                      spawn tree, web taint (nmem_remember refused to web-reached agents), one agent on
                      computer-use at a time, images <= image_max_px, toolsmith-only stack-install
                      (argv checked by toolsmith_policy.py), and the caps (MCP calls per session and per
                      agent, spawns per caller per prompt, tool calls per agent).
  permission_request  denies an escalation that pushes, writes a forge, touches a protected root or a
                      credential, relaunches codex with overrides, gives git a place to read a file or
                      run code from (-C, --exec-path=, --git-dir, --work-tree, --config-env, -c with
                      an alias, command, include or hooks-path key, -F/--file, -t/--template,
                      --pathspec-from-file in any abbreviation or short cluster, GIT_* or EDITOR in
                      its environment; the --git-allow-rules form is held to the same in PreToolUse),
                      or comes from a caller that may not escalate (built-ins, the main thread,
                      read-only roles; stack-install from anyone but toolsmith).
  git options         everywhere: -c alias.<x>=, GIT_CONFIG_KEY_<n>/VALUE_<n> and
                      GIT_CONFIG_PARAMETERS are read like aliases (a hidden push or `!cmd` is found,
                      alias names case-insensitive, a value decided at run time is opaque); -C and
                      --exec-path never hide the subcommand; a credential named by a file-reading
                      option (git commit -F <codex_home>/auth.json, -t~/.ssh/x, --pathspec-from=)
                      is resolved against the -C directories and denied; the read-only allowlist
                      refuses -c/--exec-path=/--config-env and resolves --output against -C.
  post_tool_use, subagent_start, subagent_stop, user_prompt_submit, session_start, session_end
                      observe only, never block: they build the spawn tree (PostToolUse(spawn_agent)
                      parsed defensively, SubagentStart matched to the pending spawn), propagate taint,
                      reset the per-prompt counters (a main-thread UserPromptSubmit) and release the
                      computer-use lock.
  --self-test         a push is denied, a read allowed, a read of auth.json denied (exit 0/1).

Layout: the policy is <guard dir>/../policy/{agents,guard}.json (the installed stack/ tree), else
<guard dir>/{agents,guard}.json (a flat copy). `--scope global` (the managed tier: requirements.py's
flat managed-hooks/ holds guard.json and no agents.json) reads the guard.json beside itself first,
never reads agents.json and keeps no state; without any guard.json it takes HOME/CODEX_HOME defaults.
The profile scope fails closed (every gated call denied) when agents.json or guard.json is missing,
unreadable or malformed. stack_io.py and toolsmith_policy.py (named in hooks/SUPPORT_FILES) sit
beside this file and are loaded by path (SourceFileLoader), never through sys.path. State lives in
guard.json's state_dir: sessions/<session_id>/state.json under an fcntl.flock, written atomically.

Bytecode: the stub loads this file by path under `python -I`, so <guard dir>/__pycache__ is used; the
installer precompiles it after apply with each target interpreter (stack-python, /usr/bin/python3):
`<python> -I -c 'import py_compile, sys; [py_compile.compile(f, doraise=True,
invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH) for f in sys.argv[1:]]' <hooks>/*.py`
(Apple's 3.9 under -I never writes bytecode itself). Measured p95 per hook call: test_guard_perf.py.

Fail closed: any internal error in pre_tool_use or permission_request is a deny with the reason; an
unreadable event or policy is a deny; the stub exits 2 when no Python is found. Observe-only modes
swallow errors and print nothing. Output follows the hooks_schema.rs wire structs exactly
(deny_unknown_fields): hookSpecificOutput {hookEventName, permissionDecision, permissionDecisionReason}
or {hookEventName, permissionDecision: "allow", updatedInput}; PermissionRequest {hookEventName,
decision: {behavior: "deny", message}}. Allowed calls print nothing.

Seeded-bug proofs (tests/mutations/codex_guard.json, 34 rows, each caught by the named test):
  nopush     git push let through; alias names case-sensitive; GIT_CONFIG_* pager/editor/alias
             not read; abbreviated --fil/--te/--pathspec-from and short -F/-t clusters not file
             options; escalated -c core.editor/include.path/hooksPath pass; GIT_EXEC_PATH before
             an unsandboxed git passes
  protect    CODEX_HOME dropped from the roots; apply_patch into a root allowed; auth.json via
             shell, apply_patch, MCP path args; git file-option credentials unchecked; -C ignored
             for them; PermissionRequest checked like a sandboxed call
  policy     BlackCat refuses multi_agent_v1wait_agent; unknown multi_agent_v1* or plain names
             accepted; the BlackCat gate passes a shell write; spawn rows ignored; a row named like
             a built-in runs it; unknown types fall back to the BlackCat row; read-only roles write;
             MCP allowlist dropped; PermissionRequest lets BlackCat escalate; git --output not
             resolved against -C; the managed guard reads ../policy first; global scope needs
             agents.json; profile scope runs on an empty policy without agents.json
  state      send_input routed to any agent; taint lost on a child's report or on send_input; the
             state lock never taken (caps under 24 concurrent processes); the catch-all lets an
             internal error through
"""
import contextlib
import fcntl
import fnmatch
import json
import os
import re
import sys
import time
from importlib.machinery import SourceFileLoader

GUARD_DIR = os.path.dirname(os.path.abspath(__file__))


def load_by_path(name, path):
    """The module at `path`, loaded by path (never through sys.path, CWE-427). SourceFileLoader
    rather than importlib.util: on Python 3.9 importlib.util pulls in typing, about 20 ms of
    compiling per hook call under Apple's `python3 -I`, which caches no stdlib bytecode."""
    loader = SourceFileLoader(name, path)
    mod = type(sys)(name)
    mod.__file__, mod.__loader__ = path, loader
    loader.exec_module(mod)
    return mod

# ---------------------------------------------------------------- modes, tools and wire names
MODES = ("pre_tool_use", "permission_request", "post_tool_use", "subagent_start", "subagent_stop",
         "user_prompt_submit", "session_start", "session_end")
GATING = ("pre_tool_use", "permission_request")
EVENT_NAMES = {"pre_tool_use": "PreToolUse", "permission_request": "PermissionRequest",
               "post_tool_use": "PostToolUse", "subagent_start": "SubagentStart",
               "subagent_stop": "SubagentStop", "user_prompt_submit": "UserPromptSubmit",
               "session_start": "SessionStart", "session_end": "SessionEnd"}
MAIN_ROW = "blackcat"          # the main thread's policy row (agents.json "blackcat")
MAIN_KEY = "main"              # the main thread in the spawn tree
# Hook tool names (DESIGN F10, F22; hook_names.rs). One table, pinned by
# tests/test_guard_contract.py; probe P13 updates it. Everything else is an unknown tool: refused.
MA_PREFIX = "multi_agent_v1"
MA_TOOLS = ("send_input", "resume_agent", "wait_agent", "close_agent")
TOOL_CLASSES = {"Bash": "shell", "apply_patch": "patch", "spawn_agent": "spawn",
                "update_plan": "plan", "request_user_input": "ask", "view_image": "image"}
for _t in MA_TOOLS:
    TOOL_CLASSES[MA_PREFIX + _t] = "ma"
MCP_RE = re.compile(r"mcp__([A-Za-z0-9][A-Za-z0-9_.-]*?)__([A-Za-z0-9][A-Za-z0-9_.-]*)\Z")
MAIN_CLASSES = ("spawn", "ma", "plan", "ask")      # plus counted read-only shell calls
TYPE_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
MAX_EVENT = 8 * 1024 * 1024    # bytes of event JSON read from stdin
LOCK_WAIT_S = 3.0              # flock wait before the call is refused (the hook timeout is 10 s)

# ---------------------------------------------------------------- defaults (= templates/guard.base.json)
DEFAULT_CAPS = {
    "mcp_calls_per_session": 600,
    "mcp_calls_per_agent": 64,
    "spawns_per_prompt": 12,
    "spawns_per_prompt_by_type": {"blackcat": 24, "orchestrator": 32, "main-coder": 6,
                                  "ninja-coder": 5, "researcher": 4, "planner": 8},
    "screen_lock_ttl_s": 900,
}
DEFAULT_IMAGE_MAX_PX = 1920
# MCP servers that carry no web content (the rest taint the caller: an unknown server fails closed)
DEFAULT_NON_WEB_MCP = ["neural-memory", "wolfram", "wandb", "image-studio", "illustrator",
                       "after-effects", "premiere", "blender", "huetension", "ide"]
DEFAULT_MEMORY_WRITE_TOOLS = ["mcp__neural-memory__nmem_remember"]
DEFAULT_COMPUTER_USE_SERVER = "computer-use"

# ---------------------------------------------------------------- reasons
NO_PUSH_REASON = ("Blocked by the stack's git rule: agents never push to a remote, in any form "
                  "(git push, send-pack, lfs/subtree push; also inside bash -c, eval or $(...)). "
                  "Keep the work in the local repository: commit, merge it back into local main "
                  "(git merge --ff-only) and report the commits; pushing is the user's own step.")
FORGE_REASON = ("Blocked by the stack's git rule: agents never write to a forge, and `%s` "
                "creates, merges, comments on or changes something on GitHub/Gitea/Forgejo "
                "(gh, tea and fj, `gh api`/`tea api` with a write method, an HTTP write to a forge "
                "host; inside bash -c or eval too). Read-only forge commands (view, list, status, "
                "checks, diff) are fine. Publishing is the user's own step: report the branch, "
                "the commits and the command for the user to run.")
OPAQUE_REASON = ("Blocked by the stack's git rule (agents never push): `%s` cannot be checked, "
                 "because the shell decides it only when the command runs. Write the git or forge "
                 "subcommand literally, without variables, globs or deep nesting.")
INDEX_REASON = ("Blocked by the stack's git rule: `%s` hides working-tree edits from git status/diff "
                "(assume-unchanged, skip-worktree, direct index writes, sparse checkout), which would "
                "blind the installer's review of the checkout; edit and commit files normally.")
SECRETS_REASON = ("Blocked by the stack's secret-hardening rule: `%s` would put a real API key or "
                  "token into this transcript. Agents never print key values; `mcp-headers "
                  "<server>` and `with-stack-env --print-env` show redacted forms. If a real value "
                  "must be checked, stop and ask the user.")
CODEX_FLAG_REASON = ("Blocked by the stack's self-protection rule: `%s` starts Codex with a "
                     "configuration override (-c/--config, --profile, --enable/--disable, "
                     "--add-dir), a sandbox or approval policy that turns its guards off, or a "
                     "--dangerously-* flag. Agents never relaunch Codex with changed settings: "
                     "ask the user.")
GITESC_REASON = ("Blocked by the stack's git rule: `%s` lets git read a file or run code outside the "
                 "sandbox (-C, -F/--file, --exec-path, -c alias.*). Run plain git inside the working "
                 "tree, without those options.")
PROTECT_REASON = ("Blocked by the stack's self-protection rule: `%s` would write, rename, re-mode or "
                  "delete %s, under a protected root (CODEX_HOME, ~/.agents or the guard's state). "
                  "The stack changes only through its installer: report the change you need.")
PROTECT_ESC_REASON = ("Blocked by the stack's self-protection rule: this escalation runs outside the "
                      "sandbox and touches %s, under a protected root (CODEX_HOME, ~/.agents or the "
                      "guard's state).")
CRED_REASON = ("Blocked by the stack's credential rule: %s names %s, a credential file (Codex's "
               "auth.json, stack.env or a path in the stack's credential set). Agents never read or "
               "write credentials: ask the user to check it themselves.")
PATCH_REASON = ("Blocked by the stack's self-protection rule: apply_patch would change %s, under a "
                "protected root (CODEX_HOME, ~/.agents or the guard's state). The stack changes "
                "only through its installer: report the change you need.")
PATCH_INPUT_REASON = ("Blocked: the stack's guard cannot read this apply_patch call's input (%s), so "
                      "it cannot check the paths it writes.")
UNREADABLE_REASON = "Blocked: the stack's guard cannot read this call's %s, so it cannot check it."
GENERIC_REASON = ("Blocked by the stack's agent rule: `%s` is not a stack agent (built-in, generic "
                  "and unknown agent types run no tools). Spawn a stack agent by its agent_type.")
MAIN_REASON = ("Blocked by the stack's BlackCat rule: the main thread only delegates (spawn_agent, "
               "send_input, resume_agent, wait_agent, close_agent, update_plan, request_user_input, "
               "and up to %d read-only shell calls per prompt); `%s` is not one of these. Spawn the "
               "stack agent that does this work.")
MAIN_READS_REASON = ("Blocked by the stack's BlackCat rule: the main thread already used its %d "
                     "read-only shell calls for this prompt. Delegate the rest to a stack agent.")
UNKNOWN_TOOL_REASON = ("Blocked by the stack's agent rule: `%s` is not a tool the stack's guard "
                       "knows, so it is refused (fail closed).")
CLASS_REASON = ("Blocked by the stack's agent rule: %s does not hold %s (its role's tool set). "
                "Delegate the step or report what you need.")
READONLY_REASON = ("Blocked by the stack's read-only rule: %s runs read-only shell commands only, and "
                   "`%s` %s. Allowed: tests, linters and type checkers, git and gh reads, inspection "
                   "(ls, cat, rg, jq, find without -delete/-exec of a writer), --version/--help; files "
                   "are written in scratch dirs only. Report the change as a finding instead.")
READONLY_PATCH_REASON = ("Blocked by the stack's read-only rule: %s is a read-only role and never "
                         "runs apply_patch. Report the change as a finding instead.")
SPAWN_MISSING_REASON = ("Blocked by the stack's spawn rule: spawn_agent needs an agent_type naming a "
                        "stack agent (no generic, built-in or default agents).")
SPAWN_ROW_REASON = ("Blocked by the stack's spawn rule: %s may spawn only %s; `%s` is not in its "
                    "row. Return STATUS: partial with NEXT naming the agent instead.")
SPAWN_CAP_REASON = ("Blocked by the stack's fan-out cap: %s already spawned %d agents for this "
                    "prompt (cap %d). Wait for running children and reuse them.")
ROUTE_REASON = ("Blocked by the stack's routing rule: %s `%s` is not your own child, your parent or "
                "an agent your row may spawn in this session's spawn tree (unknown ids are refused).")
ROUTE_ID_REASON = "Blocked by the stack's routing rule: %s needs the target agent's id."
MCP_SERVER_REASON = ("Blocked by the stack's agent rule: %s does not use the MCP server `%s` (its "
                     "role's tool set lists %s). Delegate to an agent that holds it.")
MCP_CAP_REASON = ("Blocked by the stack's MCP cap: %s reached %d MCP calls (%s). Finish with what "
                  "you have and report STATUS: partial.")
CALLS_CAP_REASON = ("Blocked by the stack's turn cap: %s reached its %d tool calls. Finish with what "
                    "you have and report STATUS: partial.")
TAINT_REASON = ("Blocked by the stack's web-taint rule: %s has read web content (its own web tools, "
                "a tainted child's report or a message from a tainted agent), so it does not write "
                "the shared memory. Hand the finding back instead.")
SCREEN_REASON = ("Blocked by the stack's computer-use rule: one agent at a time on the screen, and "
                 "%s holds it. Wait for it to finish.")
IMAGE_REASON = ("Blocked by the stack's image rule: %s is %s px, above the %d px limit on the longer "
                "side. Make a downscaled copy in scratch (sips -Z %d in --out out) and use that.")
IMAGE_UNKNOWN_REASON = ("Blocked by the stack's image rule: the size of %s cannot be read (PNG, JPEG, "
                        "GIF, WebP, BMP and HEIC headers are read). Convert it to PNG or JPEG of at "
                        "most %d px in scratch and use that.")
IMAGE_INPUT_REASON = "Blocked by the stack's image rule: view_image names no readable image path."
TOOLSMITH_ONLY_REASON = ("Blocked by the stack's installer rule: only the toolsmith agent runs "
                         "stack-install. Return STATUS: partial with NEXT: toolsmith naming the "
                         "package, its installer and the pinned version you need.")
TOOLSMITH_SHAPE_REASON = ("Blocked by the stack's installer rule: toolsmith's shell runs only "
                          "`%s <subcommand> ...` as one plain command (%s). No other program, no "
                          "shell syntax; `%s help` lists the subcommands.")
TOOLSMITH_ARGV_REASON = "Blocked by the stack's installer rule: `stack-install %s` is refused: %s."
ESCALATE_REASON = ("Blocked by the stack's escalation rule: %s does not run commands outside the "
                   "sandbox. Delegate the step or report what you need.")
POLICY_REASON = ("Blocked: the stack's guard policy cannot be read (%s); every call is refused until "
                 "the installer is re-run (fail closed).")
INTERNAL_REASON = ("Blocked: the stack's guard hit an internal error (%s); the call is refused "
                   "(fail closed). Report it with this text.")


# ================================================================ shell scanner (port)
# Ported from dot-claude/hooks/agent_guard.py at commit 5f6b3ae (no-push mode: constants, forge
# trees, curl/wget/httpie forge writes, the lexer and _Scan; the protect and install kinds removed,
# a "codex" and a "gitesc" kind added). tests/test_no_push.py's corpus is the oracle
# (tests/test_guard_nopush.py); keep both copies in step when one changes.
GIT_OPTS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env",
                       "--super-prefix", "--exec-path", "--attr-source"}
PUSH_SUBCOMMANDS = {"push", "send-pack"}
PUSH_UNDER = {"lfs": {"push"}, "subtree": {"push"}, "svn": {"dcommit", "set-tree"},
              "p4": {"submit"}}                      # git lfs push, git svn dcommit, ...
PUSH_PROGRAMS = {"git-push", "git-send-pack"}         # "$(git --exec-path)/git-push"
PROGRAMS = {"git", "gh", "tea", "fj"} | PUSH_PROGRAMS
PUSH_RE = re.compile(r"(?:^|[\s;&|(`'\"])(?:\S*/)?git(?:\s+-{1,2}[^\s]+(?:\s+[^\s-][^\s]*)?)*?"
                     r"\s+['\"]?(?:push|send-pack|(?:lfs|subtree)\s+['\"]?push)\b")
# config keys whose value git runs as a command (git -c KEY=VALUE, git config KEY VALUE)
GIT_EXEC_KEY_RE = re.compile(
    r"(?:alias\..+|core\.(?:editor|pager|sshcommand|fsmonitor|askpass)|sequence\.editor|pager\..+|"
    r"diff\.external|diff\..+\.(?:command|textconv)|difftool\..+\.cmd|mergetool\..+\.cmd|"
    r"merge\..+\.driver|filter\..+\.(?:clean|smudge|process)|interactive\.difffilter|"
    r"gpg\.program|gpg\..+\.program|credential\.helper|credential\..+\.helper|"
    r"uploadpack\.packobjectshook|sendemail\..+|remote\..+\.uploadpack|core\.gitproxy)\Z", re.I)
# Index blinding (CWE-345): install.sh reviews the checkout with `git status`/`git diff`; these
# make git skip a file's working-tree content, so an edited file would be installed unseen.
# update-index options are matched by any prefix (git accepts unique abbreviations); the
# clearing forms (--no-assume-unchanged, --no-skip-worktree) stay allowed.
INDEX_BLIND_OPTS = ("assume-unchanged", "skip-worktree", "cacheinfo", "index-info")
INDEX_BLIND_KEYS = {"core.sparsecheckout", "core.sparsecheckoutcone", "core.ignorestat"}
INDEX_BLIND_ENV_RE = re.compile(r"GIT_CONFIG_(?:KEY_\d+|PARAMETERS)=", re.I)
INDEX_BLIND_TEXT_RE = re.compile(r"core\.(?:sparsecheckout(?:cone)?|ignorestat)\b", re.I)
GIT_CONFIG_NOSET = {"--get", "--get-all", "--get-regexp", "--get-urlmatch", "--get-color",
                    "--get-colorbool", "-l", "--list", "--unset", "--unset-all", "-e", "--edit",
                    "--remove-section", "--rename-section"}
GIT_CONFIG_VALUE_OPTS = {"-f", "--file", "--blob", "--type", "--default", "--comment", "--value"}
ENV_EXEC_RE = re.compile(r"(?:GIT_[A-Z0-9_]+|EDITOR|VISUAL|PAGER|SSH_ASKPASS)=(.*)\Z", re.S)
ASSIGN_RE = re.compile(r"[A-Za-z_]\w*\+?=")
OPAQUE_SUB_RE = re.compile(r"[$`{}*?\[\]\x00]")      # expansions and globs: decided at run time
EXPANSION_RE = re.compile(r"\$(?:\{[^}]*\}|[A-Za-z_]\w*|[@*#?$!0-9-])")
PWSH = {"pwsh", "powershell", "pwsh.exe", "powershell.exe"}
SHELLS = {"sh", "bash", "rbash", "zsh", "dash", "ksh", "ksh93", "mksh", "pdksh", "ash", "yash",
          "posh", "fish", "csh", "tcsh"} | PWSH
# programs that run their (joined) arguments as shell code
STRING_RUNNERS = {"eval", "ssh", "watch", "su", "runuser", "script", "flock", "tmux", "screen",
                  "parallel", "expect", "iex", "invoke-expression"}
HEREDOC_RUNNERS = SHELLS | {"eval", "ssh"}           # read a heredoc on stdin as commands
INTERPRETER_RE = re.compile(r"(?:python|pypy|perl|ruby|node|nodejs|deno|bun|php|lua|luajit|"
                            r"osascript|Rscript|R|julia)[\d.]*(?:\.exe)?\Z")
CODE_FLAG_RE = re.compile(r"-[A-Za-z]*[ceErp]\Z|--(?:eval|command|print)\Z")
CODE_PUNCT_RE = re.compile(r"[\[\](){},;:+'\"`]")     # os.system("git push"), ['gh','pr','create']
# inline code is checked only when it can start a process (print('git push') is text)
EXEC_HINT_RE = re.compile(r"\b(?:system|exec\w*|popen\w*|spawn\w*|run|call|check_\w+|proc_open|"
                          r"passthru|shell_exec|start)\s*[(\"'\[{]|\bsystem\s+\S|subprocess|"
                          r"Deno\.(?:Command|run)|"
                          r"child_process|\bos\.|Runtime|ProcessBuilder|do shell script|`|%x[({\[]|"
                          r"\bqx\s*[({\[/]", re.I)
CODE_ARGS_KEY_RE = re.compile(r"\b(?:args|argv|arguments|cmd)\b")   # Deno.Command('git', {args: [..]})
# `sh -c CODE a b`: a and b are data unless CODE runs a positional parameter as a command
POSITIONAL_CMD_RE = re.compile(r"(?:^|[;&|({\n`]|\b(?:eval|exec|then|do|else|command|sudo|env|"
                               r"xargs|nohup|time)\b)\s*[\"']?\$(?:[@*0-9]|\{[@*0-9])")
HELP_BOOL_OPTS = {"--fill", "--fill-first", "--fill-verbose", "--draft", "--web", "--squash",
                  "--merge", "--rebase", "--delete-branch", "--auto", "--admin", "--approve",
                  "--dry-run", "--yes", "--no-maintainer-edit", "--disable-auto",
                  "-s", "-m", "-r", "-d", "-f", "-w", "-y", "-a", "-c"}
# words after which the next word is still a command name (`exec git-push`, `env X=1 cmd`)
PREFIX_WORDS = {"exec", "command", "builtin", "nohup", "time", "env", "sudo", "doas", "xargs",
                "timeout", "nice", "stdbuf", "noglob", "then", "do", "else", "elif", "if",
                "while", "until", "!", "{"}
SEP_RE = re.compile(r"[;&|()\n]+\Z")                  # shlex tokens that end a simple command
REDIR_OP_RE = re.compile(r"[<>]+&?\Z|&>+\Z")
# fast path: a command that names none of these (after dropping quotes, backslashes and
# expansions: g''it, g${X}it) and holds no escape that could spell one ($'\x67it', printf
# '\147it') is not checked further
TRIGGER_RE = re.compile(r"(?<![A-Za-z0-9_-])(?:git|gh|tea|fj)")
ESCAPE_RE = re.compile(r"\$'|\\(?:x[0-9A-Fa-f]|u[0-9A-Fa-f]|[0-7])")
# fast path for the "secrets" scan kind (below): checked only when that kind is requested. Not
# word-bounded (unlike TRIGGER_RE): over-matching only causes an extra full parse, never a miss.
SECRETS_TRIGGER_RE = re.compile(r"mcp-headers|with-stack-env|install\.sh|install_state|doctor\.sh|credential|"
                                r"security|CLAUDE_CODE_MCP_SERVER_NAME")
SECRETS_PROGRAMS = {"mcp-headers", "with-stack-env"}
INSTALLER_SCRIPTS = {"install.sh", "doctor.sh"}

# ... nor a command the shell only knows at run time: `$G push`, pwsh -EncodedCommand, a
# decoded pipeline into a shell (base64 -d | sh)
OPAQUE_HINT_RE = re.compile(r"\$[\w{(@*!#?-]\S*\s+(?:push|send-pack)\b|\b(?:pwsh|powershell)\b|"
                            r"\|\s*(?:\S*/)?(?:sh|bash|zsh|dash|ksh|fish|source|\.)(?:\s|$)|"
                            r"\benv\s[^;&|\n]*-S", re.I)
# a pipeline into a shell whose text starts as a literal (echo, printf, <<<) and is transformed
# on the way (base64 -d, rev, tr, sed ...) runs commands nobody can read here: refused.
# Downloads and files (curl | bash, gunzip -c x.gz | sh) are scripts, out of sight like any file.
LITERAL_SOURCES = {"echo", "printf", "print"}
PASS_THROUGH = {"cat", "tee", "echo", "printf", "print"}
LENIENT_RE = re.compile(r"\n|[;&|()<>]+|[^\s;&|()<>'\"]+")
HEREDOC_OP_RE = re.compile(r"<<(-?)[ \t]*(?:(['\"])([^'\"\n]+)\2|(\\?)([A-Za-z0-9_][\w.-]*))")
ANSI_C_RE = re.compile(r"\$'((?:[^'\\]|\\.)*)'", re.S)
ANSI_ESC_RE = re.compile(r"\\(x[0-9A-Fa-f]{1,2}|u[0-9A-Fa-f]{1,4}|U[0-9A-Fa-f]{1,8}|[0-7]{1,3}"
                         r"|c.|.)", re.S)
ANSI_ESC = {"a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b", "f": "\f", "n": "\n", "r": "\r",
            "t": "\t", "v": "\v", "\\": "\\", "'": "'", '"': '"', "?": "?"}
SUBST_MARK = "\x00S%d\x00"                            # NULs never survive into a shell command
SUBST_MARK_RE = re.compile("\x00S(\\d+)\x00")
MAX_NEST, MAX_SCANS, MAX_FORGE_WORDS, DEADLINE_S = 8, 2000, 12, 6.0
MAX_COMMAND, MAX_HEREDOCS_PER_LINE = 1000000, 64   # characters of code (heredoc bodies apart)
# closer -> (opener, closer) keywords, to find the compound command a heredoc on `done` feeds
COMPOUND_OPENERS = {"done": (r"(?:while|until|for|select)", "done"), "fi": ("if", "fi"),
                    "esac": ("case", "esac"), "}": (r"\{", r"\}"), ")": (r"\(", r"\)")}
# options of prefix commands that take a value (sudo -u deploy bash, timeout -s KILL 60 sh)
PREFIX_VALUE_OPTS = {"-u", "-g", "-C", "-h", "-p", "-U", "-D", "-R", "-T", "-s", "-k", "-i",
                     "-o", "-e", "-n", "-I", "-P", "-L", "-d", "-E", "-a", "--user", "--group",
                     "--signal", "--kill-after", "--chdir", "--unset", "--adjustment"}
EXEC_OPTS = {"-exec", "-execdir", "-ok", "-okdir"}     # find -exec CMD ...
DOC_COMMANDS = {"man", "info", "help", "whatis", "apropos", "tldr", "which", "whereis", "type",
                "whence", "command -v"}               # man git push: a manual page, not a push
# pwsh command-line switches in the order pwsh matches them: (name, shortest prefix, kind);
# pwsh takes any prefix at least that long (CommandLineParameterParser.cs, MatchSwitch)
PWSH_SWITCHES = [
    ("version", "v", "flag"), ("help", "h", "flag"), ("?", "?", "flag"), ("login", "l", "flag"),
    ("noexit", "noe", "flag"), ("noprofile", "nop", "flag"), ("nologo", "nol", "flag"),
    ("noninteractive", "noni", "flag"), ("socketservermode", "so", "flag"),
    ("v2socketservermode", "v2so", "flag"), ("servermode", "s", "flag"),
    ("namedpipeservermode", "nam", "flag"), ("sshservermode", "sshs", "flag"),
    ("noprofileloadtime", "noprofileloadtime", "flag"), ("interactive", "i", "flag"),
    ("configurationfile", "configurationfile", "value"), ("configurationname", "config", "value"),
    ("custompipename", "cus", "value"), ("commandwithargs", "commandwithargs", "code"),
    ("cwa", "cwa", "code"), ("command", "c", "code"), ("windowstyle", "w", "value"),
    ("file", "f", "file"), ("isswait", "isswait", "flag"), ("outputformat", "o", "value"),
    ("of", "o", "value"), ("inputformat", "inp", "value"), ("if", "if", "value"),
    ("executionpolicy", "ex", "value"), ("ep", "ep", "value"), ("encodedcommand", "e", "encoded"),
    ("ec", "e", "encoded"), ("encodedarguments", "encodeda", "encoded"), ("ea", "ea", "encoded"),
    ("settingsfile", "settings", "value"), ("sta", "sta", "flag"), ("mta", "mta", "flag"),
    ("workingdirectory", "wo", "value"), ("wd", "wd", "value"),
    ("removeworkingdirectorytrailingcharacter", "removeworkingdirectorytrailingcharacter", "flag"),
    ("token", "to", "value"), ("utctimestamp", "utc", "value"),
]


class _TooComplex(Exception):
    """The command cannot be checked within the guard's limits: it is refused as opaque."""

# Forge CLIs: command tree -> WRITE (refused), READ (stop: fine), a subtree, or a special check.
# Checked against the gh manual (cli.github.com/manual, Sep 2026), tea's docs/CLI.md (main) and
# forgejo-cli's clap definitions (codeberg.org/forgejo-contrib/forgejo-cli, main). "a|b" spells
# aliases; "*" is what a group means when only unknown words follow it.
WRITE, READ = "write", "read"
GH_API = ("api", {"-X", "--method"}, {"-f", "-F", "--field", "--raw-field", "--input"},
          {"-H", "--header", "-q", "--jq", "-t", "--template", "-p", "--preview", "--hostname",
           "--cache"})
TEA_API = ("api", {"-X", "--method"}, {"-f", "-F", "--field", "--Field", "-d", "--data"},
           {"-H", "--header", "-l", "--login", "-o", "--output", "-R", "--remote", "-r", "--repo"})


def _forge_tree(spec):
    if not isinstance(spec, dict):
        return spec
    return {k: _forge_tree(sub) for keys, sub in spec.items() for k in keys.split("|")}


FORGE_TREES = {
    "gh": _forge_tree({
        "pr": {"create|new|merge|close|reopen|edit|comment|review|ready|lock|unlock|"
               "update-branch|revert": WRITE,
               "view|list|ls|status|checks|diff|checkout|co": READ},
        "issue": {"create|new|close|reopen|edit|comment|delete|transfer|lock|unlock|pin|unpin":
                  WRITE, "develop": ("unless-flag", ("-l", "--list")),
                  "view|list|ls|status": READ},
        "release": {"create|new|delete|delete-asset|edit|upload": WRITE,
                    "view|list|ls|download|verify|verify-asset": READ},
        "repo": {"create|new|delete|edit|fork|rename|archive|unarchive|sync": WRITE,
                 "deploy-key": {"add|delete": WRITE, "list|ls": READ},
                 "autolink": {"create|new|delete": WRITE, "list|ls|view": READ},
                 "view|list|ls|clone|set-default|read-dir|read-file|gitignore|license": READ},
        "discussion": {"create|comment|edit": WRITE, "view|list|ls": READ},
        "gist": {"create|new|delete|edit|rename": WRITE, "view|list|ls|clone": READ},
        "label": {"create|delete|edit|clone": WRITE, "list|ls": READ},
        "workflow": {"run|enable|disable": WRITE, "view|list|ls": READ},
        "run": {"rerun|cancel|delete": WRITE, "view|list|ls|download|watch": READ},
        "secret": {"set|delete|remove": WRITE, "list|ls": READ},
        "variable": {"set|delete|remove": WRITE, "get|list|ls": READ},
        "cache": {"delete": WRITE, "list|ls": READ},
        "ssh-key|gpg-key": {"add|delete": WRITE, "list|ls": READ},
        "project": {"close|copy|create|delete|edit|field-create|field-delete|item-add|"
                    "item-archive|item-create|item-delete|item-edit|link|mark-template|unlink":
                    WRITE, "view|list|ls|field-list|item-list": READ},
        "codespace|cs": {"create|delete|edit|rebuild|stop": WRITE,
                         "ports": {"visibility": WRITE, "forward": READ},
                         "view|list|ls|logs|code|jupyter|ssh|cp": READ},
        "agent-task|agent-tasks|agent|agents": {"create": WRITE, "view|list": READ},
        "skill|skills": {"publish": WRITE,
                         "install|add|list|ls|preview|show|search|update": READ},
        "api": GH_API,
        "alias": {"set": ("gh-alias",), "import|list|ls|delete": READ},
        "auth|config|extension|extensions|ext|completion|help|browse|status|search|attestation|"
        "at|ruleset|rs|org|licenses|preview|copilot|version": READ,
    }),
    "tea": _forge_tree({
        "issues|issue|i": {"create|c|edit|e|reopen|open|close": WRITE, "list|ls": READ},
        "pulls|pull|pr": {"create|c|close|reopen|open|edit|e|review|approve|lgtm|a|reject|merge|m|"
                          "reply|resolve|unresolve|clean": WRITE,
                          "list|ls|checkout|co|review-comments|rc": READ},
        "labels|label": {"create|c|update|delete|rm": WRITE, "list|ls": READ},
        "milestones|milestone|ms": {"create|c|close|delete|rm|reopen|open": WRITE,
                                    "issues|i": {"add|a|remove|r": WRITE}, "list|ls": READ},
        "releases|release|r": {"create|c|delete|rm|edit|e": WRITE,
                               "assets|asset|a": {"create|c|delete|rm": WRITE, "list|ls": READ},
                               "list|ls": READ},
        "times|time|t": {"add|a|delete|rm|reset": WRITE, "list|ls": READ},
        "organizations|organization|org": {"create|c|delete|rm": WRITE, "list|ls": READ},
        "repos|repo": {"create|c|create-from-template|ct|fork|f|migrate|m|delete|rm|edit|e": WRITE,
                       "list|ls|search|s": READ},
        "branches|branch|b": {"protect|P|unprotect|U|rename|rn": WRITE, "list|ls": READ},
        "actions|action": {
            "secrets|secret": {"create|add|set|delete|remove|rm": WRITE, "list|ls": READ},
            "variables|variable|vars|var": {"set|create|update|delete|remove|rm": WRITE,
                                            "list|ls": READ},
            "runs|run": {"delete|remove|rm|cancel": WRITE,
                         "list|ls|view|show|get|logs|log": READ},
            "workflows|workflow": {"dispatch|trigger|run|enable|disable": WRITE,
                                   "list|ls|view|show|get": READ}},
        "wiki": {"create|c|edit|e|delete|rm": WRITE, "list|ls|view|revisions|history": READ},
        "webhooks|webhook|hooks|hook": {"create|c|delete|rm|update|edit|u": WRITE, "list|ls": READ},
        # tea < 0.12 had `tea comment <index> <body>` ("*": two or more words the tree lacks)
        "comments|comment|c": {"add|a|edit|e|delete|rm": WRITE, "list|ls": READ, "*": WRITE},
        "notifications|notification|n": {"read|r|unread|u|pin|p|unpin": WRITE, "ls|list": READ},
        "ssh-keys|ssh-key": {"add|delete|rm": WRITE, "list|ls": READ},
        "admin|a": {"users|u": {"create|add|new|edit|update|e|u|delete|rm|remove": WRITE,
                                "list|ls": READ}},
        "api": TEA_API,
        "logins|login|logout|whoami|open|o|clone|C|help|h": READ,
    }),
    "fj": _forge_tree({
        "repo": {"create|fork|migrate|star|unstar|watch|unwatch|delete|edit|units|unit": WRITE,
                 "labels|label": {"create|delete|edit": WRITE, "view": READ},
                 "view|readme|clone|star-status|watch-status|browse": READ},
        "issue": {"create|edit|comment|assign|unassign|close": WRITE,
                  "depend|block": {"add|remove": WRITE, "list": READ},
                  "search|view|templates|browse": READ},
        "pr": {"create|comment|assign|unassign|edit|close|merge": WRITE,
               "depend|block": {"add|remove": WRITE, "list": READ},
               "search|view|status|checkout|browse|review": READ},
        "milestone": {"create|edit|delete": WRITE, "search|view": READ},
        "actions": {"dispatch": WRITE, "variables|secrets": {"create|delete": WRITE, "list": READ},
                    "tasks": READ},
        "release": {"create|edit|delete": WRITE, "asset": {"create|delete": WRITE, "download": READ},
                    "list|view|browse": READ},
        "tag": {"create|delete": WRITE, "list|view": READ},
        "user": {"follow|unfollow|block|unblock|edit": WRITE,
                 "key|gpg": {"upload|delete": WRITE, "list|view|verify": READ},
                 "search|view|browse|following|followers|repos|orgs|activity": READ},
        "org": {"create|edit": WRITE, "visibility": ("if-flag", ("-s", "--set")),
                "team": {"create|edit|delete": WRITE,
                         "repo|member": {"add|rm": WRITE, "list": READ}, "list|view": READ},
                "label": {"add|edit|rm": WRITE, "list": READ},
                "repo": {"create": WRITE, "list": READ},
                "list|view|activity|members": READ},
        "wiki|auth|whoami|version|completion|help": READ,
    }),
}

# fast path for the forge-over-HTTP check: a command that names no forge host cannot hit it
FORGE_NET_TRIGGER_RE = re.compile(r"github|gitlab|gitea|codeberg|bitbucket", re.I)
FORGE_HOSTS = ("github.com", "api.github.com", "uploads.github.com", "gitlab.com", "codeberg.org",
               "bitbucket.org", "api.bitbucket.org", "gitea.com")
NET_CLIENTS = {"curl", "wget", "http", "https", "xh", "xhs"}
GH_VALUE_OPTS = {"-h", "--hostname", "-R", "--repo", "-s", "--scopes", "-p", "--git-protocol",
                 "-u", "--user"}
GIT_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix",
                  "--config-env", "--attr-source"}
SECURITY_VALUE_CHARS = "aCcDGjlsty"
CURL_VALUE_SHORT = "HAeoubcwxKmrEYCDdFTXzUPQty"
CURL_VALUE_LONG = {"header", "user-agent", "referer", "output", "user", "cookie", "cookie-jar",
                   "write-out", "proxy", "proxy-user", "config", "max-time", "connect-timeout",
                   "range", "cacert", "cert", "key", "limit-rate", "retry", "continue-at",
                   "dump-header", "resolve", "connect-to", "oauth2-bearer", "aws-sigv4",
                   "unix-socket"}
CURL_WRITE_LONG = ("request", "data", "data-raw", "data-binary", "data-urlencode", "data-ascii",
                   "form", "form-string", "upload-file", "json")
WGET_VALUE_SHORT = "OoPUeiBtTwQaIXlADR"
WGET_VALUE_LONG = {"header", "user-agent", "output-document", "output-file", "referer",
                   "directory-prefix", "input-file", "load-cookies", "save-cookies", "http-user",
                   "http-password", "user", "password", "proxy-user", "proxy-password", "tries",
                   "timeout", "wait", "append-output", "base"}
WGET_WRITE_LONG = ("method", "post-data", "post-file", "body-data", "body-file")
HTTPIE_VALUE_OPTS = {"-a", "--auth", "-A", "--auth-type", "--session", "--session-read-only",
                     "--proxy", "--timeout", "--verify", "--cert", "--cert-key", "-o", "--output",
                     "--pretty", "-s", "--style", "-p", "--print", "-P", "--history-print",
                     "--max-redirects", "--max-headers", "--default-scheme", "--ssl",
                     "--unix-socket", "--response-charset", "--response-mime", "--format-options",
                     "--chunked-size", "--curl-file", "--cert-key-pass", "--http-version"}
HTTPIE_ITEM_SEPS = (":=@", "=@", ":=", "==", "=", "@", ":")
HTTPIE_WRITE_SEPS = {":=@", "=@", ":=", "=", "@"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _forge_host_of(url):
    """True when the URL's host (not its path or query) is a forge host or one of its subdomains."""
    import urllib.parse
    url = url.strip().strip("\"'")
    if not url or url[:1] == "-":
        return False
    if "://" not in url:
        url = "http://" + url.lstrip("/")
    try:
        host = urllib.parse.urlsplit(url).netloc.rpartition("@")[2]
    except ValueError:
        return False
    host = re.sub(r":\d*\Z", "", host.lower())
    for piece in re.split(r"[{},\[\]]", host):        # curl globs: https://{a.com,github.com}/
        piece = piece.strip(".")
        if piece and any(piece == h or piece.endswith("." + h) for h in FORGE_HOSTS):
            return True
    return False


def _abbrev(name, options, minimum):
    """The option `name` spells, as an exact name or an unambiguous-enough prefix (curl and wget
    accept `--dat` for `--data`); None if it spells none of them."""
    if name in options:
        return name
    if len(name) >= minimum:
        return next((o for o in options if o.startswith(name)), None)
    return None


def _curl_write(args):
    """(urls, is_write) of a curl command line."""
    urls, data, other, get, method, k = [], False, False, False, "", 0
    while k < len(args):
        a = args[k]
        k += 1
        if a == "--":
            urls += args[k:]
            break
        if a.startswith("--"):
            name, eq, val = a[2:].partition("=")
            opt = _abbrev(name, CURL_WRITE_LONG, 3)
            if name == "url" or (opt is None and name in CURL_VALUE_LONG) or opt is not None:
                if not eq and k < len(args):
                    val, k = args[k], k + 1
            if name == "url":
                urls.append(val)
            elif opt is None and _abbrev(name, ("get",), 3):
                get = True
            elif opt == "request":
                method = val
            elif opt is not None and opt.startswith("data"):
                data = True
            elif opt is not None:
                other = True
            continue
        if a[:1] == "-" and len(a) > 1:
            for pos, c in enumerate(a[1:], 1):
                if c == "G":
                    get = True
                elif c in CURL_VALUE_SHORT:
                    val = a[pos + 1:]
                    if not val and k < len(args):
                        val, k = args[k], k + 1
                    if c == "X":
                        method = val
                    elif c == "d":
                        data = True
                    elif c in "FT":
                        other = True
                    break
            continue
        urls.append(a)
    bad_method = bool(method) and method.upper() not in SAFE_METHODS
    return urls, other or (data and not get) or bad_method


def _wget_write(args):
    urls, write, k = [], False, 0
    while k < len(args):
        a = args[k]
        k += 1
        if a == "--":
            urls += args[k:]
            break
        if a.startswith("--"):
            name, eq, val = a[2:].partition("=")
            opt = _abbrev(name, WGET_WRITE_LONG, 4)
            if opt is not None or (name in WGET_VALUE_LONG and not eq):
                if not eq and k < len(args):
                    val, k = args[k], k + 1
            if opt == "method":
                write = write or val.upper() not in SAFE_METHODS
            elif opt is not None:
                write = True
            continue
        if a[:1] == "-" and len(a) > 1:
            for pos, c in enumerate(a[1:], 1):
                if c in WGET_VALUE_SHORT:
                    if not a[pos + 1:] and k < len(args):
                        k += 1
                    break
            continue
        urls.append(a)
    return urls, write


def _httpie_item_sep(item):
    """The separator httpie reads in a request item: the earliest one, the longest on a tie."""
    best = None
    for sep in HTTPIE_ITEM_SEPS:
        p = item.find(sep)
        if p >= 0 and (best is None or p < best[0] or (p == best[0] and len(sep) > len(best[1]))):
            best = (p, sep)
    return best[1] if best else None


def _httpie_write(args):
    pos, write, k = [], False, 0
    while k < len(args):
        a = args[k]
        k += 1
        if a == "--":
            pos += args[k:]
        elif a == "--raw" or a.startswith("--raw="):
            write, k = True, k + (a == "--raw")
        elif a in HTTPIE_VALUE_OPTS:
            k += 1
        elif a[:1] != "-" or len(a) == 1:
            pos.append(a)
        if a == "--":
            break
    method = None
    if len(pos) >= 2 and re.match(r"[A-Za-z]+\Z", pos[0]):
        method = pos.pop(0).upper()
    if method and method not in SAFE_METHODS:
        write = True
    write = write or any(_httpie_item_sep(x) in HTTPIE_WRITE_SEPS for x in pos[1:])
    return pos[:1], write


def _r2_net(prog, args):
    """("forge", what) for curl, wget or httpie/xh sending a write to a forge host."""
    if prog == "curl":
        urls, write = _curl_write(args)
    elif prog == "wget":
        urls, write = _wget_write(args)
    else:
        urls, write = _httpie_write(args)
    if write:
        for u in urls:
            if _forge_host_of(u):
                return ("forge", "%s (a write request to %s)" % (prog, u[:80]))
    return None


def _cluster_has(arg, want, value_chars):
    """A short-option cluster (`-sw`, `-ht`) holds one of `want` before any option that takes a
    value (the rest of the word is that value)."""
    if arg[:1] != "-" or arg[:2] == "--":
        return False
    for c in arg[1:]:
        if c in want:
            return True
        if c in value_chars:
            return False
    return False


def _first_positional(args, value_opts):
    k = 0
    while k < len(args):
        if args[k] in value_opts:
            k += 2
        elif args[k][:1] == "-":
            k += 1
        else:
            return k
    return None


def _plain_args(args):
    """args without redirections (`2>&1`, `> f`, `< f`): the words the program itself gets."""
    out, k = [], 0
    while k < len(args):
        a = args[k]
        if REDIR_OP_RE.match(a) or re.match(r"\d*[<>]", a):
            k += 1 if re.search(r"&\d+\Z", a) else 2
        elif a.isdigit() and k + 1 < len(args) and REDIR_OP_RE.match(args[k + 1]):
            k += 1
        else:
            out.append(a)
            k += 1
    return out


def _r2_gh(args):
    """`gh auth ...` prints or stores the token: everything except `gh auth status` without -t."""
    k = _first_positional(args, GH_VALUE_OPTS)
    if k is None or args[k] != "auth":
        return None
    rest = args[k + 1:]
    j = _first_positional(rest, GH_VALUE_OPTS)
    if j is None:
        return None                            # `gh auth` alone prints its help
    if rest[j] == "status":
        tail = rest[:j] + rest[j + 1:]
        if not any(a == "--show-token" or _cluster_has(a, "t", "hRspu") for a in tail):
            return None
    return ("secrets", "gh auth %s" % rest[j])


def _r2_git(args):
    """`git credential fill|approve|reject` and `git credential-<helper>` print stored secrets."""
    k = 0
    while k < len(args) and args[k][:1] == "-":
        k += 2 if args[k] in GIT_VALUE_OPTS else 1
    if k >= len(args):
        return None
    sub = args[k]
    if sub == "credential" and args[k + 1:k + 2] and args[k + 1] in ("fill", "approve", "reject"):
        return ("secrets", "git credential %s" % args[k + 1])
    if sub.startswith("credential-"):
        return ("secrets", "git %s" % sub)
    return None


def _r2_security(args):
    """macOS keychain dumps: find-*-password with -w/-g, dump-keychain, export."""
    k = 0
    while k < len(args) and args[k][:1] == "-":
        k += 1
    if k >= len(args):
        return None
    sub, rest = args[k], args[k + 1:]
    if sub in ("dump-keychain", "export"):
        return ("secrets", "security %s" % sub)
    if sub in ("find-generic-password", "find-internet-password") and any(
            _cluster_has(a, "wg", SECURITY_VALUE_CHARS) for a in rest):
        return ("secrets", "security %s -w/-g" % sub)
    return None


def _shell_words(command):
    """shlex words, with each unquoted newline kept as a "\\n" separator token."""
    import shlex
    lex = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>\n")
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    lex.commenters = ""
    out = []
    for w in lex:
        if "\n" in w and w.strip("\n") and SEP_RE.match(w.replace("<", "").replace(">", "") or "x"):
            w = w.replace("\n", "")            # "|\n" continues the pipeline: plain "|"
        out.append(w)
    return out


def _c_unescape(s):
    """C-style escapes as bash's $'...', printf and echo -e read them."""
    def esc(m):
        e = m.group(1)
        try:
            if e[0] in "xuU":
                return chr(int(e[1:], 16))
            if e[0] in "01234567":
                return chr(int(e, 8) & 0xFF)
        except (ValueError, OverflowError):
            return ""
        if e[0] == "c" and len(e) == 2:
            return chr(ord(e[1]) & 0x1F)
        return ANSI_ESC.get(e, "\\" + e)
    return ANSI_ESC_RE.sub(esc, s)


def _command_position(prefix):
    """True when a substitution that starts after `prefix` (the text of its simple command so
    far) is the command name, so its output runs; False for an argument or a word part
    (`VAR=$(...)`, `--x=$(...)`)."""
    s = prefix.rstrip('"')                     # the opening quote of "$(...)"
    if s and not s[-1].isspace() and s[-1] not in ";&|(!{`\n":
        return False
    s = s.rstrip()
    if not s or s[-1] in ";&|(!{`\n":
        return True
    last = re.split(r"[\s;&|(]", s)[-1]
    return last in PREFIX_WORDS or bool(re.match(r"[A-Za-z_]\w*=\S*\Z", last))


def _script_position(prefix):
    """"script" when `<(...)` after `prefix` is the script a shell or `source` reads."""
    words = re.findall(r"[^\s;&|(]+", prefix.rsplit("\n", 1)[-1])
    while words and (ASSIGN_RE.match(words[0]) or words[0] in PREFIX_WORDS):
        words = words[1:]
    if words and (_base(words[0]) in SHELLS | {"source", "."}) and not any(
            w[:1] == "-" and "c" in w[1:] and not w.startswith("--") for w in words[1:]):
        return "script"
    return False


def _heredoc_owner(text, seg, i):
    """The command a heredoc feeds: its simple command, or the whole compound command when `<<`
    follows `done`, `fi`, `esac`, `}` or `)` (while read l; do eval "$l"; done <<EOF)."""
    own = text[max(seg, i - 512):i]
    words = own.split()
    if words and words[0] in COMPOUND_OPENERS:
        opener, closer = COMPOUND_OPENERS[words[0]]
        lo = max(0, seg - 4096)
        window = text[lo:seg]
        kw = r"(?<![\w-])(?:(%s)|(%s))(?![\w-])" if words[0][0].isalpha() else r"(%s)|(%s)"
        depth, start = 1, 0
        for m in reversed(list(re.finditer(kw % (opener, closer), window))):
            depth += 1 if m.group(2) else -1
            if not depth:
                start = m.start()
                break
        own = text[lo + start:i]
    return own


def _at_command_start(text, i):
    j = i - 1
    while j >= 0 and text[j] in " \t":
        j -= 1
    return j < 0 or text[j] in ";&|(\n{"


def _lex(text, deadline=None):
    """One quote-aware pass over a command, linear in its length. Returns (the text with comments,
    line continuations and heredoc bodies removed, `$'...'` decoded, and every outermost $(...)
    or `...` replaced by a SUBST_MARK placeholder; [(the command owning a heredoc, body, delimiter
    quoted?)]; [(substitution text, in command position?)]). `<<` inside quotes or arithmetic is
    no heredoc; a heredoc or substitution inside "$(...)" still counts; `$(` in single quotes is
    literal."""
    out, heredocs, substs, pending, stack, seg_stack = [], [], [], [], [], []
    i, n, nsub, seg = 0, len(text), 0, 0     # nsub: open $( and `; seg: start of the command
    sub_start = sub_pos = sub_kind = None
    glued, steps = -1, 0                     # glued: just after a $(...) or $((...)) ended
    while i < n:
        steps += 1
        if not steps & 0x3FFF and deadline is not None and time.monotonic() > deadline:
            raise _TooComplex("a command too large to check in time")
        c = text[i]
        ctx = stack[-1] if stack else None
        in_sub = nsub > 0
        opener = None
        if ctx == "'":
            if c == "'":
                stack.pop()
        elif ctx in ("A", "a"):                # arithmetic: only $(...) and parentheses count
            if text.startswith("$(", i) and not text.startswith("$((", i):
                opener = "$("
            elif c == "(":
                stack.append("a")
            elif c == ")" and ctx == "a":
                stack.pop()
            elif ctx == "A" and text.startswith("))", i):
                stack.pop()
                if not in_sub:
                    out.append("))")
                i += 2
                glued = i
                continue
        elif ctx == '"':
            if c == "\\" and i + 1 < n:
                if text[i + 1] != "\n" and not in_sub:    # backslash-newline: a continuation
                    out.append(text[i:i + 2])
                i += 2
                continue
            if c == '"':
                stack.pop()
            elif text.startswith("$((", i):
                stack.append("A")
                if not in_sub:
                    out.append("$((")
                i += 3
                continue
            elif text.startswith("$(", i):
                opener = "$("
            elif c == "`":
                opener = "`"
        else:                                  # the shell reads code here (None, "$", "(", "`")
            if c == "\\" and i + 1 < n:
                if text[i + 1] != "\n" and not in_sub:
                    out.append(text[i:i + 2])
                i += 2
                continue
            if c == "#" and (i == 0 or text[i - 1] in " \t\n;&|(<>"
                             or (text[i - 1] == ")" and glued != i)):   # a comment
                j = text.find("\n", i)
                i = n if j < 0 else j
                continue
            if c == "$" and text.startswith("$'", i):    # $'...': decoded into plain quotes
                m = ANSI_C_RE.match(text, i)
                if m:
                    if not in_sub:
                        out.append("'%s'" % _c_unescape(m.group(1)).replace("'", "'\"'\"'"))
                    i = m.end()
                    continue
            if c in "'\"":
                stack.append(c)
            elif text.startswith("$((", i) or (text.startswith("((", i)
                                               and _at_command_start(text, i)):
                stack.append("A")
                w = "$((" if c == "$" else "(("
                if not in_sub:
                    out.append(w)
                i += len(w)
                continue
            elif text.startswith("$(", i):
                opener = "$("
            elif c in "<>" and text[i + 1:i + 2] == "(" and text[i - 1:i] != c:
                opener = c + "("                   # process substitution <(...) >(...)
            elif c == "(" and ctx in ("$", "("):   # a subshell inside a substitution
                stack.append("(")
            elif c == ")" and ctx == "(":
                stack.pop()
            elif (c == ")" and ctx == "$") or (c == "`" and ctx == "`"):
                stack.pop()
                nsub -= 1
                seg = seg_stack.pop() if seg_stack else 0
                if not nsub:                   # an outermost substitution closed
                    inner = text[sub_start:i]
                    if sub_kind == "`":        # \` \$ \\ are one level of escaping
                        inner = re.sub(r"\\([\\`$])", r"\1", inner)
                    substs.append((inner, sub_pos))
                    out.append(SUBST_MARK % (len(substs) - 1))
                i += 1
                glued = i
                continue
            elif c == "`":
                opener = "`"
            elif c == "<" and text.startswith("<<", i) and not text.startswith("<<<", i) \
                    and (i == 0 or text[i - 1] != "<"):
                m = HEREDOC_OP_RE.match(text, i)
                if m:
                    if len(pending) >= MAX_HEREDOCS_PER_LINE:
                        raise _TooComplex("more than %d heredocs on one line"
                                          % MAX_HEREDOCS_PER_LINE)
                    pending.append((m.group(3) or m.group(5), bool(m.group(2) or m.group(4)),
                                    _heredoc_owner(text, seg, i), m.end()))
                    if not in_sub:
                        out.append(" ")
                    i = m.end()
                    continue
            elif c == "\n" and pending:        # the bodies start on the next line
                eol = i
                i += 1
                for delim, quoted, before, op_end in pending:
                    after = re.split(r";|&&|\|\||(?<![<>])&(?![>&])",
                                     text[op_end:min(eol, op_end + 512)])[0]
                    body, end_re = [], re.compile(r"[ \t]*%s[ \t]*(?=\)|\Z)" % re.escape(delim))
                    while i < n:
                        j = text.find("\n", i)
                        j = n if j < 0 else j
                        m = end_re.match(text, i, j)
                        if m:
                            i = m.end() if m.end() < j else j + 1
                            break
                        body.append(text[i:j])
                        i = j + 1
                    heredocs.append((before + " " + after, "\n".join(body), quoted))
                pending, seg = [], i
                if not in_sub:
                    out.append("\n")
                continue
            if c in ";|()\n" or (c == "&" and text[i - 1:i] not in ("<", ">")
                                   and text[i + 1:i + 2] != ">"):     # not 2>&1, &>
                seg = i + 1
        if opener:
            if not in_sub:
                sub_start, sub_kind = i + len(opener), opener
                before = text[max(seg, i - 256):i]
                sub_pos = _script_position(before) if opener == "<(" else \
                    False if opener == ">(" else _command_position(before)
            seg_stack.append(seg)
            seg = i + len(opener)
            stack.append("`" if opener == "`" else "$")
            nsub += 1
            i += len(opener)
            continue
        if not in_sub:
            out.append(c)
        i += 1
    if nsub and sub_start is not None:         # unterminated: the rest is the substitution
        substs.append((text[sub_start:], sub_pos))
        out.append(SUBST_MARK % (len(substs) - 1))
    return "".join(out), heredocs, substs


def _restorer(substs):
    """Put the substitutions of one _lex call back into words taken from its text."""
    def restore(s):
        if "\x00" not in s:
            return s
        return SUBST_MARK_RE.sub(lambda m: "$(%s)" % substs[int(m.group(1))][0]
                                 if int(m.group(1)) < len(substs) else "", s)
    return restore


def _printf(args):
    """What `printf FORMAT ARGS...` prints (%s-style directives; the format repeats for extra
    arguments), for reading the output of $(printf 'git %s' push) as a command."""
    while args and args[0].startswith("-") and args[0] != "--":
        args = args[2:] if args[0] == "-v" else args[1:]
    if args[:1] == ["--"]:
        args = args[1:]
    if not args:
        return ""
    fmt, vals, out = _c_unescape(args[0]), list(args[1:]), []
    directive = re.compile(r"%[-+ #0]*\d*(?:\.\d+)?([a-zA-Z%])")
    for _ in range(64):
        used = [False]

        def sub(m):
            if m.group(1) == "%":
                return "%"
            used[0] = True
            return vals.pop(0) if vals else ""
        out.append(directive.sub(sub, fmt))
        if not vals or not used[0]:
            break
    return "".join(out)


def _raw_substs(s):
    """$(...) and `...` in an unquoted heredoc body (quotes are text there; \\$ and \\` are not
    substitutions)."""
    found, i, n = [], 0, len(s)
    while i < n:
        if s[i] == "\\":
            i += 2
        elif s.startswith("$(", i):
            depth, j = 1, i + 2
            while j < n and depth:
                depth += {"(": 1, ")": -1}.get(s[j], 0)
                j += 1
            found.append(s[i + 2:j - 1] if depth == 0 else s[i + 2:])
            i = j
        elif s[i] == "`":
            j = s.find("`", i + 1)
            j = n if j < 0 else j
            found.append(s[i + 1:j])
            i = j + 1
        else:
            i += 1
    return found


def _heredoc_runs_code(owner):
    """Whether the command that owns a heredoc (or a later stage of its pipeline) reads the body
    as commands: a shell, eval or ssh, or `source /dev/stdin`."""
    if re.match(r"\s*(?:while|until|for|select|if|case)\b|\s*[{(]", owner):
        # a compound command: its stdin reaches every command in it; look at command words only
        for part in re.split(r";|&&|\|\||\||\n|[{}()]|(?<![\w-])(?:do|then|else|elif)(?![\w-])",
                             owner):
            words = [w for w in part.split() if not ASSIGN_RE.match(w)]
            if not words or words[0] in ("for", "select", "case", "done", "fi", "esac"):
                continue
            while words and words[0] in PREFIX_WORDS | {"while", "until", "if", "!"}:
                words = words[1:]
            if words and (_base(words[0]) in HEREDOC_RUNNERS or (
                    words[0] in ("source", ".") and words[1:2] and words[1] in
                    ("/dev/stdin", "/dev/fd/0", "-"))):
                return True
        return False
    for stage in owner.split("|"):
        words = re.findall(r"[^\s;&()<>'\"`]+", stage)[:8]
        if any(_base(w) in HEREDOC_RUNNERS for w in words):
            return True
        if words[:1] in (["source"], ["."]) and set(words[1:2]) & {"/dev/stdin", "/dev/fd/0", "-"}:
            return True
    return False


def _rest(words, j, limit=256):
    """words[j:] up to the next command separator (at most `limit` words)."""
    k, end = j, min(len(words), j + limit)
    while k < end and not SEP_RE.match(words[k]):
        k += 1
    return words[j:k]


def _after_pipe(words, i):
    """words[i] is the command of a pipeline stage after `|` (past env, sudo, options, X=1)."""
    j = i - 1
    while j >= 0 and not SEP_RE.match(words[j]) and (
            words[j] in PREFIX_WORDS or words[j][:1] == "-" or _duration(words[j])
            or ASSIGN_RE.match(words[j]) or (j > 0 and words[j - 1] in PREFIX_VALUE_OPTS)):
        j -= 1
    return j >= 0 and words[j] in ("|", "|&")


def _duration(word):
    return bool(re.match(r"\d+(?:\.\d+)?[smhd]?\Z", word))


def _stage_head(stage):
    """The program a pipeline stage runs (past X=1, env/sudo/timeout and their options)."""
    k, n = 0, len(stage)
    while k < n:
        w = stage[k]
        if ASSIGN_RE.match(w) or w in PREFIX_WORDS or _duration(w):
            k += 1
        elif w[:1] == "-" and k > 0:
            k += 2 if w in PREFIX_VALUE_OPTS else 1
        else:
            return _base(w)
    return ""


def _skip_redirections(words, k, end):
    """Index of the first word at or after k that is not a redirection (`2>/dev/null`, `>log`)."""
    while k < end:
        if words[k].isdigit() and k + 1 < end and REDIR_OP_RE.match(words[k + 1]):
            k += 1
        elif REDIR_OP_RE.match(words[k]):
            k += 2
        else:
            break
    return k


def _base(word):
    return word.rsplit("/", 1)[-1]


def _pwsh_switch(arg):
    """(name, kind) of a pwsh switch spelled any way pwsh accepts (-c, -Comm, --command, /c)."""
    key = arg.strip()
    if key[:1] not in ("-", "/", "\u2013", "\u2014"):
        return None, None
    key = key[1:]
    if key[:1] == arg.strip()[:1] and key[:1] in ("-", "\u2013", "\u2014"):
        key = key[1:]
    key = key.split(":", 1)[0].lower()
    for name, shortest, kind in PWSH_SWITCHES:
        if len(key) >= len(shortest) and name.startswith(key):
            return name, kind
    return key, "flag"


def _pwsh_args(base, rest):
    """How pwsh/powershell reads its arguments: ("code", text), ("encoded", None),
    ("file", None) or (None, None) when it reads commands from stdin."""
    k = 0
    while k < len(rest):
        name, kind = _pwsh_switch(rest[k])
        if name is None:                       # a bare argument
            if base.startswith("pwsh"):
                return "file", None            # pwsh: a script file
            return "code", " ".join(rest[k:])  # Windows PowerShell: a command
        if kind in ("code", "encoded", "file"):
            colon = rest[k].partition(":")[2]
            code = " ".join(([colon] if colon else []) + rest[k + 1:])
            return kind, code
        k += 2 if kind == "value" and ":" not in rest[k] else 1
    return None, None


def _expansion(word):
    return "$" in word or "\x00" in word or "`" in word



def _api_writes(args, method_opts, body_opts, value_opts):
    """gh api / tea api: a write unless the method is GET/HEAD (default GET; gh sends POST once a
    field or --input is given). GraphQL: a write when it carries a mutation."""
    method, body, positional, k = None, False, [], 0
    while k < len(args):
        a = args[k]
        name, eq, val = a.partition("=")
        if a == "--":
            positional.extend(args[k + 1:])
            break
        if a.startswith("--") and eq:
            method = val if name in method_opts else method
            body = body or name in body_opts
        elif a in method_opts:
            method, k = (args[k + 1] if k + 1 < len(args) else ""), k + 1
        elif a in body_opts:
            body, k = True, k + 1
        elif a in value_opts:
            k += 1
        elif a[:1] == "-" and a[:2] != "--" and len(a) > 2 and a[:2] in method_opts:
            method = a[2:].lstrip("=")           # -XPOST
        elif a[:1] == "-" and a[:2] != "--" and len(a) > 2 and a[:2] in body_opts:
            body = True                          # -fkey=value
        elif not a.startswith("-"):
            positional.append(a)
        k += 1
    if positional and positional[0].strip("/").lower() == "graphql":
        return any(re.search(r"\bmutation\b", a, re.I) for a in args)
    if method is not None:
        return method.strip().upper() not in ("GET", "HEAD", "OPTIONS")
    return body


class _Scan(object):
    """One detection run (ported from agent_guard._Scan, protect/install kinds removed): which
    kinds to report ("push", "forge", "opaque", "index", "secrets", "codex", "gitesc"), a work
    budget and a deadline (a hook that times out does not block, so a slow check must deny
    instead). "secrets" flags `--reveal` on mcp-headers or with-stack-env, env/printenv under
    with-stack-env and `bash -x`/`sh -x`/`zsh -x` on install.sh or doctor.sh. "codex" flags the
    `codex` CLI started with -c/--config or a --dangerously-* flag (DESIGN 4.2 c). "gitesc" flags
    git options that read files or run code outside the sandbox: -C, -F/--file, --exec-path,
    -c alias.* (DESIGN 4.3)."""

    def __init__(self, want):
        self.want, self.budget = set(want), MAX_SCANS
        self.deadline = time.monotonic() + DEADLINE_S

    def hit(self, kind, what):
        if len(what) > 200:
            what = what[:197] + "..."
        return (kind, what) if kind in self.want else None

    def scan(self, command, depth=0):
        """First remote write in a shell command: (kind, what), or None."""
        if not isinstance(command, str):
            return None
        command = command.replace("\x00", "")
        bare = re.sub(r"['\"\\]", "", command)
        secrets_trigger = ("secrets" in self.want and SECRETS_TRIGGER_RE.search(bare)) or (
            "forge" in self.want and FORGE_NET_TRIGGER_RE.search(bare))
        codex_trigger = "codex" in self.want and CODEX_TRIGGER_RE.search(bare)
        if not (TRIGGER_RE.search(EXPANSION_RE.sub("", bare)) or ESCAPE_RE.search(command)
                or OPAQUE_HINT_RE.search(bare) or secrets_trigger or codex_trigger):
            return None                        # names no git/gh/tea/fj/codex/..., even obfuscated
        self.budget -= 1
        if depth > MAX_NEST or self.budget < 0:
            return self.hit("opaque", "a command nested too deeply to check")
        if time.monotonic() > self.deadline:
            return self.hit("opaque", "a command too large to check in time")
        try:
            text, heredocs, substs = _lex(command, self.deadline)
        except _TooComplex as exc:
            return self.hit("opaque", str(exc))
        if len(text) > MAX_COMMAND:            # shlex below is not interruptible (~3 s a MB)
            return self.hit("opaque", "a command too large to check in time")
        for inner, cmd_pos in substs:
            found = self.scan(inner, depth + 1)
            if not found and cmd_pos:          # its output is run: `$(echo 'git push')`
                found = self.run_output(inner, depth + 1)
            if found:
                return found
        for owner, body, quoted in heredocs:
            if time.monotonic() > self.deadline:
                return self.hit("opaque", "a command too large to check in time")
            found = self.scan(body, depth + 1) if _heredoc_runs_code(owner) else None
            for inner in ([] if quoted or found else _raw_substs(body)):
                found = found or self.scan(inner, depth + 1)
            if found:
                return found
        return self.scan_words(self.words(text), depth, _restorer(substs))

    def run_output(self, inner, depth):
        """What a substitution prints, read as commands: its multi-word words (echo 'git push')
        and heredoc bodies (cat <<EOF)."""
        try:
            text, heredocs, substs = _lex(inner, self.deadline)
        except _TooComplex as exc:
            return self.hit("opaque", str(exc))
        restore = _restorer(substs)
        words = [restore(w) for w in self.words(text)]
        found = self.each_phrase(words, depth)
        if not found and words and _base(words[0]) == "printf":   # printf 'git %s' push
            found = self.each_phrase([_printf(words[1:])], depth)
        for _, body, _ in heredocs:
            found = found or self.scan(body, depth)
        return found

    @staticmethod
    def words(text):
        try:
            return _shell_words(text)
        except ValueError:                     # unbalanced quotes: the shell would refuse it too
            return LENIENT_RE.findall(text)

    def each_phrase(self, words, depth):
        """Scan every multi-word word as a command (text that a shell will read as code)."""
        for w in words:
            for phrase in dict.fromkeys((w, _c_unescape(w))):     # printf 'git push\n' | sh
                found = self.scan(phrase, depth) if re.search(r"\s", phrase) else None
                if found:
                    return found
        return None

    def scan_words(self, words, depth, restore=lambda s: s):
        n = len(words)
        ends = [n] * (n + 1)                   # ends[k]: the first separator at or after k
        for k in range(n - 1, -1, -1):
            ends[k] = k if SEP_RE.match(words[k]) else ends[k + 1]
        covered = stdin_done = stmt_start = 0  # covered, stdin_done: words already re-scanned
        cmd_pos, xargs_seen, head = True, False, None   # head: this simple command's program
        env_cfg = None                         # git config from the environment (_env_config)
        for i, w in enumerate(words):
            if not i % 512 and time.monotonic() > self.deadline:
                return self.hit("opaque", "a command too large to check in time")
            if SEP_RE.match(w):
                if w not in ("|", "|&", "(", ")"):
                    stmt_start, xargs_seen = i + 1, False
                cmd_pos, head = True, None
                continue
            base, found, end = _base(w), None, ends[i + 1]
            if "\x00" in w:                    # $(which python3) -c ...: the program it names
                m = re.match(r"\$\((?:which|command -v|type -p|whence -p)\s+(\S+)\)\Z", restore(w))
                base = _base(m.group(1)) if m else base
            here_cmd = cmd_pos
            if here_cmd and head is None and not (ASSIGN_RE.match(w) or w in PREFIX_WORDS):
                head = base
            cmd_pos = (cmd_pos and (bool(ASSIGN_RE.match(w)) or w in PREFIX_WORDS
                                    or (w[:1] == "-" and i > 0 and words[i - 1] in PREFIX_WORDS))
                       ) or w in EXEC_OPTS
            if head in DOC_COMMANDS:           # man git push, which gh, help push
                continue
            if base in ("xargs", "parallel"):
                xargs_seen = True
            if ASSIGN_RE.match(w):             # GIT_EDITOR='git push' git commit, export PAGER=...
                m = ENV_EXEC_RE.match(w)
                found = self.scan(restore(m.group(1)), depth + 1) if m else None
                if not found and INDEX_BLIND_ENV_RE.match(w) and INDEX_BLIND_TEXT_RE.search(w):
                    found = self.hit("index", w.split("=", 1)[0] + "=" + "core.sparseCheckout/"
                                     "ignoreStat")       # GIT_CONFIG_KEY_0=core.sparseCheckout
                if not found and GIT_ENV_CONFIG_RE.match(w):
                    if env_cfg is None:
                        env_cfg = _env_config(words, restore)
                    found = self.env_config(env_cfg, depth)
                if not found and "gitesc" in self.want:
                    found = _gitesc_env(w, words, restore)
                    found = found and self.hit("gitesc", found)
            elif base in PUSH_PROGRAMS and here_cmd:
                found = self.hit("push", base)       # not `ls .../git-push`
            elif base == "git":
                if env_cfg is None:
                    env_cfg = _env_config(words, restore)
                found = self.git(words, i, end, xargs_seen, depth, restore, env_cfg)
            elif w in PUSH_SUBCOMMANDS and i > 0 and _expansion(words[i - 1]) \
                    and self.was_command(words, i - 1):
                found = self.hit("opaque", "%s %s" % (restore(words[i - 1]), w))
            elif _expansion(base) and _base(EXPANSION_RE.sub("", SUBST_MARK_RE.sub("", w))) \
                    in PROGRAMS:
                found = self.hit("opaque", restore(w))     # g${X}it: spelled at run time
            if not found and "secrets" in self.want and base in SECRETS_PROGRAMS and here_cmd:
                found = self.secrets_helper(base, words, i + 1, end, restore)
            if not found and "secrets" in self.want and base in SHELLS and here_cmd:
                found = self.secrets_bash_x(base, words, i + 1, end, restore)
            if not found and self.want & R2_KINDS:
                found = _r2_scan(self, w, base, words, i, end, restore, here_cmd)
            if not found and "codex" in self.want and base == "codex" and here_cmd:
                found = _codex_flags(self, words, i + 1, end, restore)
            if not found and base in FORGE_TREES:
                found = self.forge(base, words, i + 1, end, depth, xargs_seen)
            if not found and w == "<<<" and i + 1 < n:     # a here-string that becomes code
                stage = words[stmt_start:end]
                if any(_base(x) in SHELLS | STRING_RUNNERS | {"xargs", "source", "."}
                       for x in stage):
                    found = self.scan(restore(words[i + 1]), depth + 1)
            lbase = base.lower()
            if not found and base == "env":    # env -S 'git push': one string, split into words
                for k in range(i + 1, end):
                    x = words[k]
                    if x in ("-S", "--split-string") or x.startswith("--split-string="):
                        val = x.split("=", 1)[1] if "=" in x else " ".join(words[k + 1:end])
                        found = self.scan(restore(val), depth + 1)
                        break
                    if x.startswith("-S") and len(x) > 2:
                        found = self.scan(restore(x[2:] + " " + " ".join(words[k + 1:end])),
                                          depth + 1)
                        break
            if not found and lbase in ("start-process", "saps"):    # PowerShell
                args = [restore(x) for x in words[i + 1:end]
                        if not x.lower().startswith(("-argumentlist", "-filepath", "-wait",
                                                     "-nonewwindow"))]
                found = self.scan(" ".join(a.replace(",", " ") for a in args), depth + 1)
            runner = base in SHELLS or lbase in STRING_RUNNERS or base == "alias" \
                or INTERPRETER_RE.match(base)
            if not found and runner and i >= covered:
                # (a runner's arguments are this runner's business: later runners among them
                # are arguments too, or were re-scanned with them)
                covered, rest = end, [restore(x) for x in words[i + 1:end]]
                if base in SHELLS:
                    found = self.shell(base, rest, depth)
                elif lbase in STRING_RUNNERS:
                    found = self.scan(" ".join(rest), depth + 1) if rest else None
                elif base == "alias":
                    for x in rest:
                        found = found or self.scan(x.partition("=")[2], depth + 1)
                else:                          # python -c, node -e, deno eval, osascript -e
                    for k in range(1, len(rest)):
                        code_flag = CODE_FLAG_RE.match(rest[k - 1]) or (k == 1 and rest[0] == "eval")
                        if code_flag and EXEC_HINT_RE.search(rest[k]):
                            code = CODE_ARGS_KEY_RE.sub(" ", CODE_PUNCT_RE.sub(" ", rest[k]))
                            found = found or self.scan(code, depth + 1)
            if not found and i >= stdin_done and base in SHELLS | {"source", "."} \
                    and self.reads_stdin(words, i):
                stdin_done = i
                while stdin_done < n and not (SEP_RE.match(words[stdin_done])
                                              and words[stdin_done] not in ("|", "|&", "(", ")")):
                    stdin_done += 1
                found = self.each_phrase([restore(x) for x in words[stmt_start:stdin_done]],
                                         depth + 1)
                if not found and self.transformed_literal(words, stmt_start, i):
                    found = self.hit("opaque", "commands decoded into %s (%s)" % (
                        base, " ".join(restore(x) for x in words[stmt_start:i + 1])[:120]))
            if found:
                return found
        return None

    @staticmethod
    def transformed_literal(words, a, i):
        """A pipeline words[a:i] that starts from literal text (echo, printf, a here-string) and
        transforms it (base64 -d, rev, tr, sed ...) before a shell reads it."""
        stages, cur = [], []
        for x in words[a:i]:
            if x in ("|", "|&"):
                stages.append(cur)
                cur = []
            else:
                cur.append(x)
        stages.append(cur)
        heads = [_stage_head(st) for st in stages if st]
        literal = bool(heads) and (heads[0] in LITERAL_SOURCES or "<<<" in words[a:i])
        return literal and any(h not in PASS_THROUGH for h in heads if h)

    @staticmethod
    def was_command(words, j):
        """words[j] is the command name of its simple command (after separators, X=1, env ...)."""
        k = j - 1
        while k >= 0 and (ASSIGN_RE.match(words[k]) or words[k] in PREFIX_WORDS):
            k -= 1
        return k < 0 or bool(SEP_RE.match(words[k]))

    def shell(self, base, rest, depth):
        """sh/bash/zsh/pwsh ...: the -c (-Command) string, the positional arguments it expands
        ($1, $@), and a here-string it reads as commands."""
        if base in PWSH:
            return self.pwsh(base, rest, depth)
        code, k = self.shell_code(rest)
        if code is None:
            for j in range(len(rest) - 1):
                if rest[j] == "<<<":           # sh <<< 'git push'
                    return self.scan(rest[j + 1], depth + 1)
            return None
        found = self.scan(code, depth + 1)
        if not found and POSITIONAL_CMD_RE.search(code):      # sh -c '"$1"' _ 'git push'
            found = self.scan(" ".join(rest[k + 1:]), depth + 1)
        return found

    def pwsh(self, base, rest, depth):
        """pwsh/powershell: the -Command text (everything after it) or commands on stdin."""
        kind, code = _pwsh_args(base, rest)
        if kind == "encoded":
            return self.hit("opaque", "%s -EncodedCommand" % base)
        return self.scan(code, depth + 1) if kind == "code" and code != "-" else None

    @staticmethod
    def shell_code(rest):
        """(the command string of `sh -c STRING`, its index), or (None, index); option clusters
        like -lc, -ec, -xc count, and fish --command, pwsh -Command."""
        seen_c, k = False, 0
        while k < len(rest):
            x = rest[k]
            xl = x.lower()
            if xl.startswith("--command=") or xl.startswith("-command="):
                return x.split("=", 1)[1], k
            if x in ("-o", "+o", "-O", "+O", "--rcfile", "--init-file"):
                k += 2
                continue
            if xl in ("-command", "-c", "-commandwithargs", "-cwa"):
                seen_c, k = True, k + 1
                continue
            if x[:1] in "-+" and len(x) > 1:
                seen_c = seen_c or x == "--command" or (not x.startswith("--") and "c" in x[1:])
                k += 1
                continue
            return (x, k) if seen_c else (None, k)
        return None, k

    @staticmethod
    def reads_stdin(words, i):
        """sh/bash/source reading commands from a pipe, a redirect or a process substitution."""
        rest = _rest(words, i + 1)
        if _base(words[i]) in PWSH:            # pwsh -Command -, or no command or file at all
            kind, code = _pwsh_args(_base(words[i]), rest)
            if kind not in (None, "stdin") and code != "-":
                return False
        elif _base(words[i]) in SHELLS and _Scan.shell_code(rest)[0] is not None:
            return False
        first = next((x for x in rest if not x.startswith("-")), "")
        return _after_pipe(words, i) or first.startswith("<") or \
            first in ("/dev/stdin", "/dev/fd/0", "-")

    def git(self, words, i, end, xargs_seen, depth, restore, env_cfg=()):
        k, aliases = i + 1, {}
        for key, value in env_cfg:             # GIT_CONFIG_KEY_0=alias.p GIT_CONFIG_VALUE_0=push
            if value is not None and key.lower().startswith("alias."):
                aliases[key[6:].lower()] = value
        while True:                            # global options (and redirections among them)
            k = _skip_redirections(words, k, end)
            if k >= end or not words[k].startswith("-"):
                break
            opt = words[k]
            if opt in GIT_OPTS_WITH_VALUE:
                val, k = (words[k + 1] if k + 1 < end else ""), k + 2
            else:
                opt, _, val = opt.partition("=")
                k += 1
            key, _, value = restore(val).partition("=")
            if "gitesc" in self.want:
                found = _gitesc_global(opt, key, value)
                if found:
                    return self.hit("gitesc", found)
            if opt == "--config-env" and GIT_EXEC_KEY_RE.match(key):
                return self.hit("opaque", "git --config-env " + restore(val))
            if opt in ("-c", "--config-env") and (key.lower() in INDEX_BLIND_KEYS
                                                   or _expansion(key)):
                found = self.hit("index", "git %s %s" % (opt, key))   # -c core.sparseCheckout=true
                if found:
                    return found
            if opt == "-c":                    # git -c alias.p=push p, -c core.editor=...
                found = self.git_config_value(key, value, depth)
                if found:
                    return found
                if key.lower().startswith("alias."):
                    aliases[key[6:].lower()] = value       # alias names are case-insensitive
        if k >= end:
            return self.hit("opaque", "xargs git (the subcommand comes from stdin)") \
                if xargs_seen else None
        sub = words[k]
        if sub.lower() in aliases:             # -c alias.p='!sh' p -c 'git push': with its args
            body = aliases[sub.lower()]
            import shlex
            tail = " ".join(shlex.quote(restore(x)) for x in words[k + 1:min(end, k + 257)])
            found = self.scan((body[1:] if body.startswith("!") else "git " + body) + " " + tail,
                              depth + 1)
            if found:
                return found
        if sub in PUSH_SUBCOMMANDS:
            return self.hit("push", "git " + sub)
        if sub in PUSH_UNDER and PUSH_UNDER[sub] & set(words[k + 1:min(end, k + 6)]):
            return self.hit("push", "git %s %s" % (sub, "/".join(sorted(PUSH_UNDER[sub]))))
        args = [restore(x) for x in words[k + 1:min(end, k + 257)]]
        if "gitesc" in self.want:
            found = next(("git %s %s %s" % (sub, flag, v) for flag, v in _git_file_values(sub, args)
                          if v != "-"), None)
            if found:
                return self.hit("gitesc", found)
        found = self.git_index_blind(sub, args)
        if found:
            return found
        if sub == "config":                    # defining an alias or editor that pushes
            for j in range(len(args) - 1):
                if GIT_EXEC_KEY_RE.match(args[j]) and not args[j + 1].startswith("-"):
                    found = found or self.git_config_value(args[j], args[j + 1], depth)
        elif sub == "submodule" and "foreach" in args[:3]:
            cmd = args[args.index("foreach") + 1:]
            while cmd and cmd[0] in ("--recursive", "--quiet", "-q", "--"):
                cmd = cmd[1:]
            found = self.scan(" ".join(cmd), depth + 1)
        elif sub == "rebase":
            for j, a in enumerate(args):
                code = args[j + 1] if a in ("-x", "--exec") and j + 1 < len(args) else \
                    a[7:] if a.startswith("--exec=") else a[2:] if a.startswith("-x") else None
                found = found or (self.scan(code, depth + 1) if code else None)
        elif sub == "bisect" and args[:1] == ["run"]:
            found = self.scan(" ".join(args[1:]), depth + 1)
        for code in _git_command_values(sub, args):
            found = found or self.scan(code, depth + 1)
        if not found and any(a.lower().startswith("ext::") for a in args):
            found = self.hit("opaque", "git %s ext::... (a command run as a transport)" % sub)
        if found:
            return found
        if OPAQUE_SUB_RE.search(sub):
            return self.hit("opaque", "git " + restore(sub))
        return None

    def env_config(self, pairs, depth):
        """git configuration set through the environment (GIT_CONFIG_KEY_<n>/GIT_CONFIG_VALUE_<n>,
        GIT_CONFIG_PARAMETERS) is read like `git -c`: an alias or command value is scanned; a key or
        value the shell decides at run time, or an exec key without its value, is opaque."""
        for key, value in pairs:
            if key is None or _expansion(key) or (value is None and GIT_EXEC_KEY_RE.match(key)):
                return self.hit("opaque", "git configuration from the environment (%s)"
                                % (key or "GIT_CONFIG_PARAMETERS"))
            found = self.git_config_value(key, value, depth) if value is not None else None
            if found:
                return found
        return None

    def git_config_value(self, key, value, depth):
        """A config value that git runs as a command: alias bodies (`!cmd` or git arguments),
        editors, pagers, ssh commands, filters, credential helpers."""
        if not GIT_EXEC_KEY_RE.match(key):
            return None
        if key.lower().startswith("alias.") and not value.startswith("!"):
            return self.scan("git " + value, depth + 1)
        return self.scan(value.lstrip("!"), depth + 1)

    def git_index_blind(self, sub, args):
        """Index blinding (INDEX_REASON): `git update-index` with an INDEX_BLIND_OPTS option (any
        prefix, or a word the shell decides at run time), `git sparse-checkout` other than
        `list`/help, `git config` setting an INDEX_BLIND_KEYS key (or a key decided at run time)
        or an alias that runs update-index/sparse-checkout."""
        if "index" not in self.want:
            return None
        if sub == "update-index":
            for a in args:
                if a == "--":
                    break
                name = a[2:].partition("=")[0] if a[:2] == "--" else ""
                if name and any(o.startswith(name) for o in INDEX_BLIND_OPTS):
                    return self.hit("index", "git update-index " + a)
                if a[:1] in "$`*?[{" or (a[:1] == "-" and OPAQUE_SUB_RE.search(a)):
                    return self.hit("index", "git update-index %s (decided at run time)" % a)
            return None
        if sub == "sparse-checkout":
            if args[:1] in (["list"], ["-h"], ["--help"]):
                return None
            return self.hit("index", "git sparse-checkout " + " ".join(args[:2]))
        if sub != "config":
            return None
        for j in range(len(args) - 1):         # git config alias.x 'update-index ...'
            if args[j].lower().startswith("alias.") and \
                    re.search(r"\b(?:update-index|sparse-checkout)\b", args[j + 1]):
                return self.hit("index", "git config %s (runs update-index/sparse-checkout)"
                                % args[j])
        if any(a.partition("=")[0] in GIT_CONFIG_NOSET for a in args):
            return None
        pos, j = [], 0
        while j < len(args):
            a = args[j]
            if a in GIT_CONFIG_VALUE_OPTS:
                j += 2
                continue
            if a[:1] != "-" or a == "-":
                pos.append(a)
            j += 1
        if pos[:1] == ["set"]:                 # get/unset/list...: pos[0] is no key, so no hit
            pos = pos[1:]
        if len(pos) >= 2 and (pos[0].lower() in INDEX_BLIND_KEYS or _expansion(pos[0])):
            return self.hit("index", "git config %s" % pos[0])
        return None

    def forge(self, tool, words, start, end, depth, xargs_seen=False):
        """Walk the forge's command tree over words[start:end] (options skipped; unknown words,
        such as option values, numbers and branch names, are passed over)."""
        if "forge" not in self.want:
            return None
        for k in range(start, min(end, start + 64)):
            prev = words[k - 1] if k > start else ""
            if words[k] in ("--help", "-h") and not (prev[:1] == "-" and "=" not in prev
                                                     and prev not in HELP_BOOL_OPTS):
                return None                    # help, not `--body -h`
        root = node = FORGE_TREES[tool]
        path, extra, seen, prev = [tool], 0, 0, ""
        for k in range(start, end):
            a = words[k]
            if a.startswith("-"):
                prev = a
                continue
            seen += 1
            if seen > MAX_FORGE_WORDS:
                break
            nxt = node.get(a)
            if nxt is None:
                if node is root and _expansion(a) and not (prev[:1] == "-" and "=" not in prev):
                    return self.hit("opaque", "%s %s" % (tool, a))    # gh $CMD merge 3
                extra, prev = extra + 1, a
                continue
            path.append(a)
            if nxt == WRITE:
                return self.hit("forge", " ".join(path))
            if nxt == READ:
                return None
            if isinstance(nxt, tuple):
                return self.forge_special(nxt, words[k + 1:end], path, depth)
            node, extra, prev = nxt, 0, a
        if len(path) > 1 and extra >= 2 and node.get("*") == WRITE:
            return self.hit("forge", " ".join(path))
        if len(path) == 1 and xargs_seen:
            return self.hit("opaque", "xargs %s (the subcommand comes from stdin)" % tool)
        return None

    def forge_special(self, spec, rest, path, depth):
        what = " ".join(path)
        if spec[0] == "api":
            return self.hit("forge", what + " (write method)") if _api_writes(rest, *spec[1:]) \
                else None
        if spec[0] in ("if-flag", "unless-flag"):
            flagged = any(a in spec[1] or a.split("=", 1)[0] in spec[1] for a in rest)
            return self.hit("forge", what) if flagged == (spec[0] == "if-flag") else None
        if spec[0] == "gh-alias":              # gh alias set NAME EXPANSION [--shell]
            pos = [a for a in rest if not a.startswith("-")]
            if len(pos) < 2:
                return None
            exp = pos[1]
            if exp.startswith("!") or "--shell" in rest or "-s" in rest:
                return self.scan(exp.lstrip("!"), depth + 1)
            words = self.words(exp)
            return self.forge("gh", words, 0, len(words), depth + 1)
        return None

    def secrets_helper(self, base, words, start, end, restore):
        """mcp-headers and with-stack-env redact key values by default; `--reveal` prints them in
        plaintext, so any agent call carrying it is refused (`--reveal=...` and a `--` before it
        too: the helpers look for the bare word anywhere). with-stack-env in exec mode hands the
        keys to its command, so a command that only dumps the environment (env, printenv, set,
        export, declare) is refused as well. The redacted forms pass. Claude Code's own
        mcp-headers invocation (CLAUDE_CODE_MCP_SERVER_NAME, no argument) never reaches a Bash
        hook."""
        args = [restore(x) for x in words[start:end]]
        if any(a == "--reveal" or a.startswith("--reveal=") for a in args):
            return self.hit("secrets", "%s --reveal" % base)
        if base == "mcp-headers" and not [a for a in _plain_args(args) if a != "--reveal"]:
            # no server name: headersHelper mode (the name comes from the environment) prints
            # the real header
            return self.hit("secrets", "mcp-headers with no server name (prints the real header)")
        if base == "with-stack-env" and args[:1] != ["--print-env"]:
            rest = args[2:] if args[:1] == ["--only"] else args
            k = 0
            while k < len(rest) - 1 and (ASSIGN_RE.match(rest[k]) or rest[k] in ("env", "-i", "--")):
                k += 1                         # with-stack-env env X=1 printenv
            cmd = _base(rest[k]) if rest else ""
            if cmd in ("env", "printenv", "set", "export", "declare", "typeset", "compgen"):
                return self.hit("secrets", "with-stack-env ... %s" % cmd)
        return None

    def secrets_bash_x(self, base, words, start, end, restore):
        """bash -x / sh -x / zsh -x (or a combined short option: -xv, -ex) on install.sh or
        doctor.sh: xtrace echoes every key the script reads or masks as it runs."""
        args = [restore(x) for x in words[start:end]]
        has_x = any(a == "-x" or a == "--xtrace"
                    or (a[:1] == "-" and a[:2] != "--" and "x" in a[1:]) for a in args)
        if not has_x:
            return None
        for a in args:
            if not a.startswith("-") and _base(a) in INSTALLER_SCRIPTS:
                return self.hit("secrets", "%s -x %s" % (base, _base(a)))
        return None



# ================================================================ read-only, image and toolsmith tables (port)
# From the same agent_guard.py: MUTATE_CODE_RE and the RO_* tables of _ReadOnly, image_size,
# wrapper_invoked and its TOOLSMITH_* constants.
MUTATE_CODE_RE = re.compile(
    r"\b(?:remove|removedirs|unlink|unlinkSync|rmtree|rmdir|rmdirSync|rmSync|rename|renames|"
    r"renameSync|truncate|chmod|lchmod|chown|symlink|symlinkSync|link|write_text|write_bytes|"
    r"writeFile|writeFileSync|appendFile|appendFileSync|copyfile|copy2|copytree|copyFile|"
    r"copyFileSync|move|touch|utime|system|popen)\s*\(|\bos\.replace\s*\(|"
    r"\bopen\s*\([^)]*,\s*['\"][^'\"]*[wax+]|\bopen\s*\(?\s*\w+\s*,\s*['\"]\s*(?:>|\+<|\|)|"
    r"\bunlink\b|\brename\b|subprocess|child_process|File\.(?:delete|write|rename|unlink)|"
    r"FileUtils|"
    # R: cat(..., file=), write.csv/write.table/..., writeLines, saveRDS, sink, file.copy/create/
    # append; Julia: rm, cp, mv, mkpath, write (not to stdout/stderr); Lua: io.output; PHP: fopen
    # in a write mode, fwrite, file_put_contents. Free functions only: a method call
    # (sys.stdout.write, process.stdout.write) is not one of them.
    r"\bcat\s*\([^)]*\bfile\s*=|\bwrite\.\w+\s*\(|\bfile\.(?:copy|create|append|remove)\s*\(|"
    r"(?<![.\w])(?:rm|cp|mv|mkpath|writeLines|saveRDS|sink|fwrite|file_put_contents)\s*\(|"
    r"(?<![.\w])write\s*\((?!\s*std(?:out|err)\b)|(?<![.\w])fopen\s*\([^)]*,\s*['\"][^'\"]*[wax+]|"
    r"\bio\.output\s*\(", re.I)

TRUNCATE_VALUE_OPTS = {"-s", "--size", "-r", "--reference"}

RO_PLAIN = {
    "ls", "cat", "head", "tail", "wc", "file", "stat", "du", "df", "pwd", "echo", "printf", "true",
    "false", "test", "[", "[[", "which", "whereis", "type", "date", "cal", "uname", "sw_vers", "id",
    "whoami", "groups", "hostname", "basename", "dirname", "realpath", "readlink", "sort", "uniq",
    "cut", "tr", "grep", "egrep", "fgrep", "zgrep", "rg", "ag", "ack", "tree", "jq", "xxd",
    "hexdump", "od", "strings", "diff", "cmp", "comm", "column", "nl", "fold", "fmt", "tac", "rev",
    "paste", "join", "shasum", "sha1sum", "sha256sum", "sha512sum", "md5", "md5sum", "b2sum",
    "cksum", "base64", "sleep", "seq", "expr", "bc", "locale", "getconf", "nproc", "ps", "uptime",
    "vm_stat", "iostat", "lsof", "otool", "nm", "objdump", "size", "zcat", "bzcat", "xzcat",
    "gzcat", "cd", "pushd", "popd", ":", "wait", "read", "unset", "local", "shopt", "hash",
    "exit", "return", "break", "continue", "dig", "nslookup", "host", "mdls", "mdfind",
    "system_profiler", "ioreg", "nvidia-smi", "tput", "clear", "iconv", "look", "tsort", "numfmt",
    "factor", "shuf", "apropos", "whatis", "ping", "traceroute", "netstat", "ifconfig", "sysctl",
    "pathchk", "mktemp", "cloc", "tokei", "scc", "gron", "xsv", "qsv", "bat", "difft", "delta",
    "wdiff", "colordiff", "z3", "cvc5", "set", "trap", "pdfinfo", "pdffonts",
}
RO_OUT_OPTS_PLAIN = {"sort", "iconv", "shuf", "base64", "tree", "cloc", "scc", "xsv", "qsv"}
# wrappers: the command they run is checked; options that take a value, per wrapper
RO_WRAPPERS = {"time": {"-f", "--format", "-o", "--output"}, "nice": {"-n", "--adjustment"},
               "nohup": set(), "stdbuf": {"-i", "-o", "-e", "--input", "--output", "--error"},
               "timeout": {"-s", "--signal", "-k", "--kill-after"},
               "gtimeout": {"-s", "--signal", "-k", "--kill-after"}, "command": set(),
               "builtin": set(), "noglob": set(), "caffeinate": {"-t", "-w"}, "chronic": set(),
               "env": {"-u", "--unset"}, "exec": {"-a"}}
RO_VERSION_FLAGS = {"--version", "-V", "--help", "-h", "-help", "--usage"}
RO_WRITERS = {"mkdir", "touch", "rm", "rmdir", "unlink", "tee", "truncate", "chmod", "ln", "cp",
              "mv", "install", "rsync", "ditto", "dd", "shred"}
RO_WRITER_VALUE_OPTS = {
    "touch": {"-t", "-d", "-r", "--date", "--reference"}, "mkdir": {"-m", "--mode"},
    "install": {"-m", "--mode", "-o", "--owner", "-g", "--group", "-t", "--target-directory",
                "-S", "--suffix"},
    "cp": {"-t", "--target-directory", "-S", "--suffix"},
    "mv": {"-t", "--target-directory", "-S", "--suffix"},
    "ln": {"-t", "--target-directory", "-S", "--suffix"}, "truncate": TRUNCATE_VALUE_OPTS,
    "rsync": {"-e", "--rsh", "--exclude", "--include", "--filter", "-f", "--files-from",
              "--exclude-from", "--include-from", "--log-file", "--partial-dir", "--temp-dir",
              "-T", "--backup-dir", "--chmod", "--chown", "--rsync-path", "-B", "--block-size",
              "--compare-dest", "--copy-dest", "--link-dest", "--suffix"},
}
# option names whose value is an output file or dir: must be scratch
RO_OUT_OPTS = {"-o", "--output", "--output-file", "--out", "--outdir", "--out-dir", "--outfile",
               "--report-path", "--report", "--sarif-output", "--json-output", "--junitxml",
               "--junit-xml", "--html", "--cov-report", "--basetemp", "--target-dir",
               "--build-dir", "--output-dir", "--log-file", "--result-log",
               "--test-reporter-destination", "--text-output", "--junit-xml-output",
               "--gitlab-sast-output", "--gitlab-secrets-output", "--vim-output",
               "--emacs-output", "--report-file", "--sql"}
RO_TOOL_OUTS = {"pytest": RO_OUT_OPTS - {"-o"}, "py.test": RO_OUT_OPTS - {"-o"},
                "grype": {"--file"}, "syft": {"--file"}, "gitleaks": RO_OUT_OPTS | {"-r"}}
# `python -m X`: modules that only check, test or print
RO_PY_MODULES = {"pytest", "unittest", "doctest", "mypy", "pyright", "basedpyright", "pylint",
                 "flake8", "pyflakes", "pycodestyle", "pydocstyle", "bandit", "pip_audit",
                 "json.tool", "tabnanny", "py_compile", "compileall", "site", "sysconfig",
                 "platform", "tokenize", "ast", "dis", "ruff", "black", "isort", "semgrep",
                 "detect_secrets", "vulture", "radon", "xenon", "pipdeptree", "pip", "mccabe",
                 "codespell", "ty", "pyrefly", "coverage"}
# formatters: allowed only with a flag that makes them report instead of rewrite
RO_CHECK_ONLY = {
    "black": ({"--check", "--diff"}, set()),
    "isort": ({"--check", "--check-only", "-c", "--diff"}, set()),
    "prettier": ({"--check", "-c", "--list-different", "-l"}, {"--write", "-w"}),
    "rustfmt": ({"--check"}, set()), "gofmt": ({"-l", "-d"}, {"-w"}),
    "shfmt": ({"-d", "-l"}, {"-w", "--write"}), "clang-format": ({"--dry-run", "-n"}, {"-i"}),
    "autopep8": ({"--diff"}, {"-i", "--in-place"}), "yapf": ({"--diff", "-d"}, {"-i", "--in-place"}),
    "mdformat": ({"--check"}, set()), "stylua": ({"--check"}, set()),
    "taplo": ({"check", "--check"}, set()), "dprint": ({"check"}, {"fmt"}),
    "nixfmt": ({"--check", "-c"}, set()),
}
# linters, scanners and test runners: allowed; these arguments would change files or post results
RO_TOOLS = {
    "mypy": set(), "pyright": set(), "basedpyright": set(), "pylint": set(), "flake8": set(),
    "pyflakes": set(), "pycodestyle": set(), "pydocstyle": set(), "bandit": set(),
    "vulture": set(), "shellcheck": set(), "hadolint": set(), "actionlint": set(),
    "yamllint": set(), "vale": {"sync"}, "markdownlint": {"--fix", "-f"},
    "markdownlint-cli2": {"--fix"}, "eslint": {"--fix"}, "stylelint": {"--fix"},
    "golangci-lint": {"--fix"}, "staticcheck": set(), "govulncheck": set(),
    "codespell": {"-w", "--write-changes", "-i", "--interactive"},
    "typos": {"-w", "--write-changes"}, "lychee": set(), "gitleaks": set(), "trufflehog": set(),
    "osv-scanner": {"fix"}, "pip-audit": {"--fix"},
    "trivy": {"plugin", "clean", "server", "module", "registry"}, "grype": set(), "syft": set(),
    "checkov": set(), "tfsec": set(), "kube-linter": set(),
    "semgrep": {"--autofix", "ci", "publish", "login", "logout", "install-semgrep-pro"},
    "detect-secrets": {"audit"},
    "pytest": {"--snapshot-update", "--inline-snapshot", "--force-regen", "--regen-all"},
    "py.test": {"--snapshot-update", "--inline-snapshot"},
    "jest": {"-u", "--updateSnapshot"}, "vitest": {"-u", "--update"}, "mocha": set(),
    "ava": {"-u", "--update-snapshots"},
    "playwright": {"install", "install-deps", "codegen", "--update-snapshots", "-u", "open"},
    "cypress": {"open", "install"}, "ctest": set(), "ty": set(), "pyrefly": {"init"},
    "sqlfluff": {"fix", "format"}, "svelte-check": set(), "vue-tsc": set(),
    "cargo-deny": {"fix", "init"}, "radon": set(), "xenon": set(), "pipdeptree": set(),
    "lean": set(), "coverage": {"erase", "combine"},
}
RO_GIT_READ = {"diff", "log", "show", "status", "blame", "annotate", "grep", "ls-files", "ls-tree",
               "rev-parse", "rev-list", "describe", "cat-file", "merge-base", "shortlog",
               "for-each-ref", "name-rev", "count-objects", "whatchanged", "range-diff", "cherry",
               "check-ignore", "check-attr", "check-ref-format", "var", "help", "version",
               "show-ref", "show-branch", "diff-tree", "diff-files", "diff-index", "verify-commit",
               "verify-tag", "ls-remote"}
# git subcommands that only read when used with one of these words or flags
RO_GIT_LIST = {"branch": {"-a", "-r", "-v", "-vv", "--list", "-l", "--contains", "--merged",
                          "--no-merged", "--show-current", "--format", "--sort", "--points-at",
                          "--all", "--remotes", "--verbose", "--color", "--no-color", "--column",
                          "--no-column", "--abbrev", "--no-abbrev", "--ignore-case"},
               "tag": {"-l", "--list", "-n", "--contains", "--merged", "--no-merged", "--sort",
                       "--format", "--points-at", "--column", "--color", "--ignore-case"},
               "remote": {"-v", "--verbose", "show", "get-url"}, "stash": {"list", "show"},
               "worktree": {"list"}, "notes": {"list", "show"}, "submodule": {"status", "summary"},
               "lfs": {"ls-files", "status", "env"}, "sparse-checkout": {"list"},
               "bisect": {"log", "visualize", "view"}}
RO_GIT_BARE_OK = {"remote", "notes", "submodule"}       # the bare subcommand lists
RO_GIT_CONFIG_READ = {"--get", "--get-all", "--get-regexp", "--get-urlmatch", "--list", "-l",
                      "get", "list"}
RO_GIT_CONFIG_WRITE = {"--add", "--unset", "--unset-all", "--replace-all", "--rename-section",
                       "--remove-section", "-e", "--edit", "set", "unset", "rename-section",
                       "remove-section", "edit"}
RO_GH_VERBS = {"view", "list", "ls", "status", "checks", "diff", "verify", "logs"}
# variables whose value runs code or moves programs, config or temp files
RO_EXEC_VAR_RE = re.compile(
    r"(?:PATH|LD_\w+|DYLD_\w+|BASH_ENV|ENV|PROMPT_COMMAND|PS[0-4]|IFS|SHELLOPTS|BASHOPTS|CDPATH|"
    r"TMPDIR|PYTHONSTARTUP|PYTHONHOME|PYTHONINSPECT|NODE_OPTIONS|NODE_PATH|PERL5OPT|PERL5LIB|"
    r"PERLLIB|RUBYOPT|RUBYLIB|JAVA_TOOL_OPTIONS|_JAVA_OPTIONS|JDK_JAVA_OPTIONS|GIT_\w+|EDITOR|"
    r"VISUAL|PAGER|MANPAGER|LESSOPEN|LESSCLOSE|SSH_ASKPASS|SUDO_ASKPASS|BROWSER|HISTFILE|ZDOTDIR|"
    r"XDG_CONFIG_HOME|HOME|SHELL|CARGO_HOME|RUSTC_WRAPPER|RUSTC|CC|CXX|MAKEFLAGS|NPM_CONFIG_\w+|"
    r"npm_config_\w+|UV_\w+|PIP_\w+|"
    # library and config search paths: they load code the agent may have written into scratch
    r"PYTHONPATH|PYTHONUSERBASE|PYTHONPYCACHEPREFIX|PYTEST_ADDOPTS|PYTEST_PLUGINS|JULIA_LOAD_PATH|"
    r"JULIA_DEPOT_PATH|JULIA_PROJECT|R_LIBS|R_LIBS_USER|R_LIBS_SITE|R_PROFILE|R_PROFILE_USER|"
    r"R_ENVIRON|R_ENVIRON_USER|LUA_PATH\w*|LUA_CPATH\w*|LUA_INIT\w*|"
    # C compilers: where they find the programs they run, edits to their command line, dep files
    r"COMPILER_PATH|GCC_EXEC_PREFIX|CCC_OVERRIDE_OPTIONS|DEPENDENCIES_OUTPUT|SUNPRO_DEPENDENCIES|"
    # TeX (kpathsea reads any texmf.cnf variable, also as NAME_progname, from the environment)
    r"openout_any\w*|openin_any\w*|shell_escape\w*|TEXMFCNF\w*|TEXMFOUTPUT\w*|"
    # allowlisted readers that take options (a pager, a preprocessor) from a config file or var
    r"RIPGREP_CONFIG_PATH|BAT_\w+|DELTA_\w+|ACK_\w+|ACKRC|GOFLAGS)\Z")
RO_SAFE_VARS = {"GIT_TERMINAL_PROMPT", "GIT_OPTIONAL_LOCKS", "GIT_LITERAL_PATHSPECS",
                "GIT_NO_REPLACE_OBJECTS", "UV_NO_SYNC", "UV_FROZEN", "UV_OFFLINE", "UV_PYTHON",
                "UV_NO_PROGRESS", "UV_LOCKED", "PIP_DISABLE_PIP_VERSION_CHECK"}
RO_DEVICES = {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty", "-"}
RO_CODE_BAD_RE = re.compile(
    MUTATE_CODE_RE.pattern + r"|\b(?:exec|eval|compile|__import__|getattr|setattr|globals|"
    r"execfile|spawn\w*|fork|execute|execSync|execFile\w*|shell_exec|passthru|proc_open|"
    r"file_put_contents|fopen|fwrite|mkdir|makedirs|mkdtemp|rm|rmSync|cp|cpSync|"
    r"createWriteStream|writelines|urlopen|urlretrieve|download\w*|install\.packages|"
    r"saveRDS|writeLines|sink|import_module|load_module|spec_from_file_location|exec_module|"
    r"addsitedir)\s*\(|__builtins__|importlib|\brunpy\b|\bsys\.path\b|\bSourceFileLoader\b|"
    r"\bsite\.addsitedir|ctypes|\bpty\b|\bsocket\b|urllib|"
    r"\brequests\b|httpx|http\.client|aiohttp|\bfetch\s*\(|XMLHttpRequest|\bdgram\b|"
    r"\bos\.(?:system|exec\w*|spawn\w*|fork|kill|putenv|environ|getenv)|process\.(?:env|binding|"
    r"kill)|\.write\s*\(|\.(?:to_csv|to_parquet|to_json|to_excel|to_feather|to_pickle|to_sql|"
    r"savefig|save|savez\w*|tofile|dump)\s*\(|Pkg\.|Deno\.|Bun\.|IO\.(?:popen|write)|%x|\bqx\b|"
    r"\bENV\b|\bgetenv\b|\bsignal\.|\bshutil\b|\.(?:unlink|rmdir|rename|replace|mkdir|touch|"
    r"symlink_to|hardlink_to|chmod)\s*\(", re.I)
RO_SHELL_NAMES = {"sh", "bash", "zsh", "dash", "ksh", "ksh93", "mksh", "ash", "rbash"}
# a command word naming its program by path counts as the named tool only in these directories
# (and never when the directory or the file resolves into scratch)
RO_SYSTEM_BIN = {"/bin", "/sbin", "/usr/bin", "/usr/sbin", "/usr/local/bin", "/opt/homebrew/bin",
                 "/opt/local/bin", "/Library/Developer/CommandLineTools/usr/bin"}
RO_VENV_BIN_RE = re.compile(r"/(?:\.?venv|venvs/[^/]+|\.tox/[^/]+)/bin\Z|/node_modules/\.bin\Z")
# plain commands whose option runs another program
RO_PAGER_HEADS = {"bat", "delta", "ack", "difft"}
# options of uniq/xxd that take a value (their second operand is an output file)
RO_OPERAND_VALUE_OPTS = {"uniq": {"-f", "-s", "-w"}, "xxd": {"-c", "-g", "-l", "-s", "-o", "-n", "-R"}}


def _heredoc_interpreter(owner):
    """The command that owns a heredoc is an interpreter reading its program from stdin
    (`python3 - <<EOF`, `node <<EOF`, `perl <<EOF`)."""
    words = [w for w in re.findall(r"[^\s;&|()<>'\"`]+", owner.rsplit("\n", 1)[-1])
             if not ASSIGN_RE.match(w) and w not in PREFIX_WORDS]
    return bool(words) and bool(INTERPRETER_RE.match(_base(words[0])))


def image_size(b):
    """(width, height) from a PNG, GIF, BMP, WebP or JPEG header; None if unknown."""
    import struct
    if b[:8] == b"\x89PNG\r\n\x1a\n" and len(b) >= 24:
        return struct.unpack(">II", b[16:24])
    if b[:6] in (b"GIF87a", b"GIF89a") and len(b) >= 10:
        return struct.unpack("<HH", b[6:10])
    if b[:2] == b"BM" and len(b) >= 26:
        w, h = struct.unpack("<ii", b[18:26])
        return abs(w), abs(h)
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP" and len(b) >= 30:
        kind = b[12:16]
        if kind == b"VP8 ":
            return (struct.unpack("<H", b[26:28])[0] & 0x3FFF, struct.unpack("<H", b[28:30])[0] & 0x3FFF)
        if kind == b"VP8L":
            bits = int.from_bytes(b[21:25], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if kind == b"VP8X":
            return int.from_bytes(b[24:27], "little") + 1, int.from_bytes(b[27:30], "little") + 1
        return None
    if b[:2] == b"\xff\xd8":
        i, n = 2, len(b)
        while i + 9 < n:
            if b[i] != 0xFF:
                i += 1
                continue
            m = b[i + 1]
            if m == 0xFF or m == 0x01 or 0xD0 <= m <= 0xD8:
                i += 1 if m == 0xFF else 2
                continue
            seg = struct.unpack(">H", b[i + 2:i + 4])[0]
            if m in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", b[i + 5:i + 9])
                return w, h
            i += 2 + seg
    return None


TOOLSMITH_META_RE = re.compile(r"[;&|<>()$`*?\[\]{}~!#\\\r\n\t]")
TOOLSMITH_SEG_RE = re.compile(r"\$\(|[;&|()`{}\n]")
TOOLSMITH_PREFIX_WORDS = {"env", "command", "builtin", "exec", "nohup", "time", "nice", "timeout",
                          "gtimeout", "sudo", "doas", "xargs", "noglob", "stdbuf", "caffeinate",
                          "then", "do", "else", "elif", "if", "while", "until", "!", "watch",
                          "parallel", "flock", "chronic"}

TOOLSMITH_HEREDOC_RE = re.compile(r"<<-?[ \t]*(['\"]?)([A-Za-z0-9_][\w.-]*)\1[^\n]*\n(.*?)(?:\n[ \t]*\2[ \t]*(?=\n|\Z)|\Z)",
                                  re.S)
# wrapper options that take a value (timeout -s KILL 30, stdbuf -o L, nice -n 5, env -u X), per wrapper
TOOLSMITH_VALUE_OPTS = {"timeout": {"-s", "-k", "--signal", "--kill-after"},
                        "gtimeout": {"-s", "-k", "--signal", "--kill-after"},
                        "stdbuf": {"-i", "-o", "-e", "--input", "--output", "--error"},
                        "nice": {"-n", "--adjustment"}, "env": {"-u", "--unset", "-C", "--chdir", "-P"},
                        "sudo": {"-u", "-g", "-C", "-h", "-p", "-U"}, "exec": {"-a"}}


def wrapper_invoked(command):
    """True when a simple command of `command` has stack-install as its command word. Heredoc bodies
    are data (a commit message naming the executor); a body fed to a shell runs sandboxed anyway,
    since only a call whose every command starts with the executor's path leaves the sandbox. A
    segment the shell lexer cannot read counts when it names stack-install."""
    import shlex
    text = re.sub(r"\\\r?\n", "", str(command or ""))
    if "stack-install" not in re.sub(r"['\"\\]", "", text).lower():
        return False
    text = TOOLSMITH_HEREDOC_RE.sub("<<x\n", text)
    for seg in TOOLSMITH_SEG_RE.split(text):
        try:
            words = shlex.split(seg, comments=False)
        except ValueError:
            if "stack-install" in re.sub(r"['\"\\]", "", seg).lower():
                return True
            continue
        k, wrapper = 0, None
        while k < len(words):
            low = words[k].lower()
            if wrapper == "env" and low in ("-s", "--split-string") and k + 1 < len(words):
                if "stack-install" in words[k + 1].lower():
                    return True                 # env -S 'stack-install ...': one string, split by env
                k += 2
                continue
            if wrapper and low in TOOLSMITH_VALUE_OPTS.get(wrapper, ()):
                k += 2
                continue
            if low in TOOLSMITH_PREFIX_WORDS:
                wrapper = low
            if low in TOOLSMITH_PREFIX_WORDS or low[:1] in "-+" or low[:1].isdigit() or \
                    re.match(r"[a-z_][a-z0-9_]*\+?=", low):
                k += 1
                continue
            if low.rstrip("/").rsplit("/", 1)[-1] == "stack-install":
                return True
            break
    return False



# ================================================================ Codex guard


# ---------------------------------------------------------------- scanner additions for Codex
CODEX_TRIGGER_RE = re.compile(r"codex", re.I)
# codex flags an agent never passes (DESIGN 4.2 c): overrides, the bypass flags, another profile
# (a profile without the stack's hooks)
CODEX_BAD_LONG = ("--config", "--profile", "--yolo", "--enable", "--disable", "--add-dir",
                  "--dangerously-bypass-approvals-and-sandbox")
# (short, long, the values that keep the sandbox and approvals on): anything else is a hit
CODEX_POLICY_OPTS = (("-s", "--sandbox", ("read-only", "workspace-write")),
                     ("-a", "--ask-for-approval", ("untrusted", "on-request", "on-failure")))
# git options that read a file of the caller's choosing (DESIGN 4.3): long names, matched by any
# prefix of two or more letters (parse-options takes unique abbreviations: --fil, --pathspec-from),
# and per subcommand the short options that take a value (a cluster ends at the first of them,
# whose value is the rest of the word or the next word) and which of those name a file
GIT_FILE_LONG = ("file", "template", "pathspec-from-file")
GIT_SHORT_VALUE = {"commit": "mFcCt", "tag": "mFu", "merge": "mFsX", "notes": "mFcC"}
# short options whose value is optional and attached only (-S<keyid>, -u<mode>, -n<num>)
GIT_SHORT_OPTIONAL = {"commit": "Su", "tag": "n", "merge": "S"}
GIT_SHORT_FILE = {"commit": "Ft", "tag": "F", "merge": "F", "notes": "F"}
# what an escalated (or --git-allow-rules) git may not carry: global options that move the
# repository, its config or its programs, -c keys whose value git runs or that load more config
GITESC_GLOBAL = ("-C", "--exec-path", "--git-dir", "--work-tree", "--config-env")
GITESC_KEY_RE = re.compile(r"(?:include\.path|includeif\..+\.path|core\.(?:hookspath|gitproxy|worktree)|"
                           r"remote\..+\.(?:uploadpack|receivepack)|protocol\.(?:.+\.)?allow)\Z",
                           re.I)
GITESC_SAFE_ENV = {"GIT_TERMINAL_PROMPT", "GIT_OPTIONAL_LOCKS", "GIT_LITERAL_PATHSPECS",
                   "GIT_NO_REPLACE_OBJECTS", "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL",
                   "GIT_AUTHOR_DATE", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL",
                   "GIT_COMMITTER_DATE"}
GITESC_ENV_RE = re.compile(r"(?:GIT_\w+|EDITOR|VISUAL|PAGER|SSH_ASKPASS)\+?=")
GIT_WORD_RE = re.compile(r"(?<![A-Za-z0-9_.-])git(?![A-Za-z0-9_.-])")
GIT_ENV_CONFIG_RE = re.compile(r"(?:GIT_CONFIG_KEY_\d+|GIT_CONFIG_PARAMETERS)\+?=")
GIT_CONFIG_KEY_RE = re.compile(r"GIT_CONFIG_KEY_(\d+)\Z")
NO_PUSH_KINDS = ("push", "forge", "opaque", "index")
SHELL_KINDS = NO_PUSH_KINDS + ("secrets", "codex")
HOOKS_PATH_RE = re.compile(r"core\.hookspath\s*=\s*/dev/null", re.I)   # the --git-allow-rules form


def _codex_flags(scan, words, start, end, restore):
    """A hit for a codex launch that changes its own settings: `-c k=v`/`--config`, `--profile`/
    `-p`, `--yolo`, `--dangerously-*`, the feature toggles `--enable`/`--disable`, `--add-dir`,
    and a sandbox (-s/--sandbox) or approval policy (-a/--ask-for-approval) other than the
    literal safe values (so danger-full-access, never, or a value decided at run time). Separate,
    `=` and attached values count, and long options by any prefix of four or more characters."""
    for k in range(start, end):
        a = restore(words[k])
        name, eq, val = a.partition("=")
        if a[:2] == "--" and len(name) >= 4 and (
                any(o.startswith(name) for o in CODEX_BAD_LONG) or name.startswith("--dang")):
            return scan.hit("codex", "codex " + name[:40])
        if a in ("-c", "-p") or (a[:2] in ("-c", "-p") and len(a) > 2):
            return scan.hit("codex", "codex " + name[:40])
        for short, long_, safe in CODEX_POLICY_OPTS:
            if a[:2] == short or (a[:2] == "--" and len(name) >= 4 and long_.startswith(name)):
                if a[:2] == short:
                    value = a[2:].lstrip("=") if len(a) > 2 else None
                else:
                    value = val if eq else None
                if value is None:
                    value = restore(words[k + 1]) if k + 1 < end else ""
                if value not in safe:
                    return scan.hit("codex", "codex %s %s" % (short if a[:2] == short else long_,
                                                              value[:40]))
    return None


# git options whose value git hands to the shell as a command, per subcommand: (short options,
# long options). The long names are matched by any unique prefix (git's parse-options).
GIT_COMMAND_OPTS = {
    "fetch": ("", ("--upload-pack",)), "pull": ("", ("--upload-pack",)),
    "clone": ("u", ("--upload-pack",)), "ls-remote": ("u", ("--upload-pack", "--exec")),
    "fetch-pack": ("", ("--upload-pack", "--exec")), "archive": ("", ("--exec",)),
    "difftool": ("x", ("--extcmd",)),
    "filter-branch": ("", ("--env-filter", "--tree-filter", "--index-filter", "--parent-filter",
                           "--msg-filter", "--commit-filter", "--tag-name-filter", "--setup")),
}


def _git_command_values(sub, args):
    """The command strings `git <sub> args` runs through the shell (upload-pack programs,
    filter-branch filters, difftool -x), for the push scan."""
    if sub not in GIT_COMMAND_OPTS:
        return []
    shorts, longs = GIT_COMMAND_OPTS[sub]
    out, k = [], 0
    while k < len(args):
        a = args[k]
        k += 1
        if a == "--":
            break
        name, eq, val = a.partition("=")
        if a[:2] == "--" and len(name) >= 4 and any(o.startswith(name) for o in longs):
            if not eq:
                val, k = (args[k] if k < len(args) else ""), k + 1
            out.append(val)
        elif a[:1] == "-" and a[:2] != "--" and len(a) >= 2 and a[1] in shorts:
            val = a[2:]
            if not val:
                val, k = (args[k] if k < len(args) else ""), k + 1
            out.append(val)
    return out


def _git_file_values(sub, args):
    """[(option, value)] for the options of `git <sub> args` that read (or write) a file of the
    caller's choosing: -F/--file (commit, tag, merge, notes; any --file, git config's too),
    -t/--template (commit; init and clone take a template directory), --pathspec-from-file (add,
    checkout, commit, reset, restore, rm, stash). Abbreviated long options and short clusters
    (`-aF msg`, `-qFmsg`) count. A value of `-` is stdin."""
    out, k = [], 0
    value_short, file_short = GIT_SHORT_VALUE.get(sub, ""), GIT_SHORT_FILE.get(sub, "")
    optional = GIT_SHORT_OPTIONAL.get(sub, "")
    while k < len(args):
        a = args[k]
        k += 1
        if a == "--":
            break
        if a[:2] == "--":
            name, eq, val = a[2:].partition("=")
            if len(name) >= 2 and any(o.startswith(name) for o in GIT_FILE_LONG):
                if not eq:
                    val, k = (args[k] if k < len(args) else ""), k + 1
                out.append(("--" + name, val))
            continue
        if a[:1] != "-" or len(a) < 2 or not value_short:
            continue
        for pos, c in enumerate(a[1:], 1):
            if c in optional:
                break                          # its value, if any, is the rest of the word
            if c in value_short:
                val = a[pos + 1:]
                if not val:
                    val, k = (args[k] if k < len(args) else ""), k + 1
                if c in file_short:
                    out.append(("-" + c, val))
                break
    return out


def _gitesc_global(opt, key, value):
    """The hit text when an escalated git global option is one of GITESC_GLOBAL (also -C<dir>) or a
    `-c` key whose value runs code or loads config (alias.*, core.editor, include.path, a hooks
    path other than /dev/null, ...); else None."""
    if opt in GITESC_GLOBAL or (opt[:2] == "-C" and len(opt) > 2):
        return "git " + opt
    if opt != "-c":
        return None
    low = key.lower()
    if low == "core.hookspath" and value == "/dev/null":
        return None                            # the --git-allow-rules hook-free form
    if GIT_EXEC_KEY_RE.match(key) or GITESC_KEY_RE.match(key) or _expansion(key):
        return "git -c " + key
    return None


def _gitesc_env(word, words, restore):
    """The hit text for an environment assignment that changes what an escalated git runs or reads
    (GIT_EXEC_PATH, GIT_DIR, GIT_CONFIG_*, GIT_SSH_COMMAND, EDITOR, ...) when the command runs git;
    the identity and lock variables (GITESC_SAFE_ENV) and PAGER=cat pass."""
    if not GITESC_ENV_RE.match(word):
        return None
    name, _, value = word.partition("=")
    name = name.rstrip("+")
    if name in GITESC_SAFE_ENV or (name in ("PAGER", "GIT_PAGER") and restore(value) == "cat"):
        return None
    if not any(GIT_WORD_RE.search(restore(x)) for x in words):
        return None
    return "%s=... (git run outside the sandbox)" % name


def _config_parameters(value):
    """(key, value) pairs of a GIT_CONFIG_PARAMETERS value (`'k'='v' 'k2'='v2'`, or `'k=v'`), None
    when it does not split."""
    import shlex
    try:
        items = shlex.split(value)
    except ValueError:
        return None
    return [(k, v if eq else "true") for k, eq, v in (x.partition("=") for x in items)]


def _env_config(words, restore):
    """git configuration the environment of this command sets: [(key, value)] from
    GIT_CONFIG_KEY_<n>/GIT_CONFIG_VALUE_<n> (value None when no GIT_CONFIG_VALUE_<n> is set) and
    from GIT_CONFIG_PARAMETERS ([(None, None)] when it does not split)."""
    assigns = {}
    for w in words:
        if ASSIGN_RE.match(w):
            name, _, val = w.partition("=")
            assigns.setdefault(name.rstrip("+"), restore(val))
    out = []
    for name in sorted(assigns):
        m = GIT_CONFIG_KEY_RE.match(name)
        if m:
            out.append((assigns[name], assigns.get("GIT_CONFIG_VALUE_" + m.group(1))))
    if "GIT_CONFIG_PARAMETERS" in assigns:
        pairs = _config_parameters(assigns["GIT_CONFIG_PARAMETERS"])
        out.extend(pairs if pairs is not None else [(None, None)])
    return out


R2_KINDS = {"secrets", "forge"}


def _r2_scan(scan, w, base, words, i, end, restore, here_cmd):
    """agent_guard's round-2 checks kept for Codex: credential printers (gh auth, git credential,
    security find-*-password -w) and forge writes through curl/wget/httpie."""
    if not here_cmd or ASSIGN_RE.match(w):
        return None
    found = None
    if "secrets" in scan.want:
        if base in ("gh", "git", "security"):
            args = [restore(x) for x in words[i + 1:end]]
            found = (_r2_gh if base == "gh" else _r2_git if base == "git" else _r2_security)(args)
        elif base.startswith("git-credential"):
            found = ("secrets", base)
    if not found and "forge" in scan.want and base in NET_CLIENTS:
        found = _r2_net(base, [restore(x) for x in words[i + 1:end]])
    return scan.hit(*found) if found else None


def remote_write_in(command):
    """(kind, what) for the first push, forge write, index blinding or unresolvable git/forge
    subcommand in a shell command, else None. Same contract as agent_guard.remote_write_in."""
    return _Scan(NO_PUSH_KINDS).scan(command)


def shell_rule_hit(command, escalation=False):
    """(kind, what) for every profile-neutral shell rule the scanner checks: no-push, secrets,
    codex flags, and (escalated or --git-allow-rules form) git's file/code options."""
    kinds = SHELL_KINDS
    if escalation or HOOKS_PATH_RE.search(command):
        kinds = kinds + ("gitesc",)
    return _Scan(kinds).scan(command)


def rule_reason(kind, what):
    return {"push": NO_PUSH_REASON, "forge": FORGE_REASON % what, "opaque": OPAQUE_REASON % what,
            "index": INDEX_REASON % what, "secrets": SECRETS_REASON % what,
            "codex": CODEX_FLAG_REASON % what, "gitesc": GITESC_REASON % what}.get(
                kind, OPAQUE_REASON % what)


# ---------------------------------------------------------------- paths: protected roots, credentials
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic", ".heif", ".tif", ".tiff",
             ".avif")
CRED_NAMES = ("stack.env",)            # a credential wherever it sits
TOKEN_RE = re.compile(r"[^\s'\"`;&|()<>,=]+")
SEG_SPLIT_RE = re.compile(r"[;&|\n]+|\$\(|[<>]\(|`")
ASSIGN_TEXT_RE = re.compile(r"(?<![\w$])([A-Za-z_]\w*)=([^\s;&|()<>'\"`]+)")
CD_RE = re.compile(r"(?:^|[\s;&|(])(?:cd|pushd)\s+([^\s;&|()<>]+)")
REDIRECT_RE = re.compile(r"(?:^|[^<>&=-])(?:\d*|&)>{1,2}\|?(?!&)\s*([^\s;&|()<>]*)")
VAR_RE = re.compile(r"\$(?:\{([A-Za-z_]\w*)\}|([A-Za-z_]\w*))")
PROTECTED_TEXT_RE = re.compile(r"(?:^|/)\.codex(?:/|\Z)|\$\{?CODEX_HOME\b|(?:^|/)\.agents(?:/|\Z)|"
                               r"(?:^|/)\.local/state/codex-agent-stack(?:/|\Z)")
PLAIN_WRITERS = {"cp", "gcp", "mv", "install", "rsync", "ditto", "tee", "dd", "rm", "unlink", "rmdir",
                 "shred", "truncate", "ln", "chmod", "chown", "chgrp", "chflags", "touch", "mkdir",
                 "tar", "gtar", "bsdtar", "unzip", "patch", "sponge", "xargs", "apply_patch",
                 "xattr", "setfacl", "mkfifo", "mknod", "install_name_tool", "cpio", "pax"}
FIND_WRITE_OPTS = {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0",
                   "-fprintf", "-fls"}
MAX_REALPATHS = 256


def within(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")


def real_path(path):
    """realpath of an absolute path; a missing tail resolves its longest existing prefix."""
    head, tail = path, []
    while head not in ("", "/") and not os.path.lexists(head):
        head, name = os.path.split(head)
        tail.insert(0, name)
    return os.path.normpath(os.path.join(os.path.realpath(head or "/"), *tail))


def _variants(path, budget=None):
    """The lexical and the symlink-resolved form of an absolute path (both are checked)."""
    lex = os.path.normpath(path)
    if budget is not None:
        if budget[0] <= 0:
            return (lex,)
        budget[0] -= 1
    real = real_path(path)
    return (lex,) if real == lex else (lex, real)


class Paths(object):
    """The protected roots and the credential set of guard.json, each as given and resolved."""

    def __init__(self, guard):
        self.codex_home = os.path.normpath(guard["codex_home"])
        self.home = os.path.normpath(guard["home"])
        self.state_dir = os.path.normpath(guard["state_dir"])
        # CODEX_HOME, ~/.agents and the state dir are always protected, whatever the list says
        base = [self.codex_home, os.path.join(self.home, ".agents"), self.state_dir]
        self.roots = self._expand(base + list(guard.get("protected_roots") or []))
        creds = guard.get("credentials") or {}
        cred_paths = [os.path.join(self.codex_home, "auth.json"),
                      os.path.join(self.codex_home, "stack.env")] + list(creds.get("paths") or [])
        self.creds = self._expand(cred_paths)
        # the directories that hold a credential (strict ancestors of a listed path): a recursive
        # reader handed one of them reads the credential. $HOME and / are left out (a search of
        # the whole home is not refused); the glob credentials (**/.env) have no fixed holder.
        skip = set(_variants(self.home)) | {"/"}
        self.holders = []
        for c in self.creds:
            d = os.path.dirname(c)
            while d and d != "/":
                if d not in skip and d not in self.holders:
                    self.holders.append(d)
                d = os.path.dirname(d)
        self.globs = [g for g in (creds.get("globs") or []) if isinstance(g, str) and g]
        self.vars = {"HOME": self.home, "CODEX_HOME": self.codex_home}
        wrapper = guard.get("toolsmith_wrapper")
        self.wrapper = wrapper if _abs_str(wrapper) else os.path.join(self.codex_home, "stack", "bin",
                                                                      "stack-install")

    @staticmethod
    def _expand(paths):
        out = []
        for p in paths:
            if isinstance(p, str) and os.path.isabs(p):
                for v in _variants(p):
                    if v not in out and v != "/":
                        out.append(v)
        return out

    def protected(self, path, budget=None):
        return any(within(v, r) for v in _variants(path, budget) for r in self.roots)

    def credential(self, path, budget=None):
        for v in _variants(path, budget):
            if os.path.basename(v) in CRED_NAMES or any(within(v, c) for c in self.creds):
                return True
            if any(fnmatch.fnmatchcase(v, g) for g in self.globs):
                return True
        return False

    def holds_credential(self, path, budget=None):
        """`path` is a directory holding a listed credential (not $HOME or /)."""
        return any(v in self.holders for v in _variants(path, budget))

    def glob_credential(self, pattern, holders=False):
        """A shell glob (`~/.codex/*.json`, `~/.*`) that expands to a listed credential, or with
        holders=True to a directory holding one."""
        targets = self.creds + (self.holders if holders else [])
        return any(_glob_match(os.path.normpath(pattern), t) for t in targets)

    def expand(self, token, bases, assigns=None):
        """Absolute candidates for a path-like token: ~, $HOME, $CODEX_HOME, $TMPDIR and NAME=value
        assignments of the same command expanded; relative paths joined to every base. [] when a
        variable is unknown (the textual checks still see the token)."""
        t = token[7:] if token.startswith("file://") else token
        if t == "~" or t.startswith("~/"):
            t = self.home + t[1:]
        env = dict(self.vars)
        if os.environ.get("TMPDIR", "").startswith("/"):
            env["TMPDIR"] = os.environ["TMPDIR"]
        env.update(assigns or {})
        unknown = []

        def sub(m):
            name = m.group(1) or m.group(2)
            if name not in env:
                unknown.append(name)
                return ""
            return env[name]
        if "$" in t:
            t = VAR_RE.sub(sub, t)
            if unknown or "$" in t:
                return []
            if t.startswith("~/"):
                t = self.home + t[1:]
        if not t:
            return []
        if os.path.isabs(t):
            return [t]
        return [os.path.join(b, t) for b in bases if b]


GLOB_CHARS_RE = re.compile(r"[*?\[]")


def _glob_match(pattern, path):
    """The shell's pathname expansion of `pattern` would produce `path`: component by component,
    and a leading dot only matched by a pattern component that starts with a dot."""
    pp, tp = pattern.split("/"), path.split("/")
    if len(pp) != len(tp):
        return False
    for p, t in zip(pp, tp):
        if t[:1] == "." and p[:1] != "." and GLOB_CHARS_RE.search(p):
            return False
        if not fnmatch.fnmatchcase(t, p):
            return False
    return True


# Recursive readers (DESIGN 4.2 f): handed a directory, these read the files under it, so a
# directory that holds a credential (CODEX_HOME, ~/.ssh, ~/.aws, ...) counts as the credential.
# Always recursive: the recursive greps (rg, ag, ack, ugrep), archivers and copiers (tar, zip -r,
# rsync, ditto, cpio, pax, 7z, scp, rclone), difftastic. Recursive with a flag: grep -r/-R/
# --recursive/-d recurse, cp -r/-R/-a, diff -r, zip -r. find counts when it runs a command
# (-exec, -ok, ...) or pipes into xargs; fd with -x/-X; git with --no-index. Listings (ls -R,
# find without -exec, tree, du, stat) name files and stay allowed. Not covered: a copy read later
# (`cp -r` is itself refused), interpreters walking a tree.
RECURSIVE_ALWAYS = {"rg", "ag", "ack", "ack-grep", "ugrep", "ug", "pt", "sift", "tar", "gtar",
                    "bsdtar", "ditto", "rsync", "cpio", "pax", "7z", "7za", "7zz", "scp", "rclone",
                    "difft"}
RECURSIVE_FLAG = {"grep": "rR", "egrep": "rR", "fgrep": "rR", "zgrep": "rR", "ggrep": "rR",
                  "cp": "rRa", "gcp": "rRa", "diff": "rR", "colordiff": "rR", "zip": "rR"}
RECURSIVE_LONG = ("--recursive", "--dereference-recursive", "--archive", "--recurse-paths",
                  "--directories=recurse")
XARGS_PIPE_RE = re.compile(r"\|\s*(?:\S*/)?xargs\b")


def _recursive_read(words, text):
    """The simple command (dequoted words) reads every file under a directory operand."""
    for j, w in enumerate(words):
        b, rest = _base(w), words[j + 1:]
        if b in RECURSIVE_ALWAYS:
            return True
        if b in RECURSIVE_FLAG:
            letters = RECURSIVE_FLAG[b]
            for k, a in enumerate(rest):
                if a in RECURSIVE_LONG or (a == "-d" and rest[k + 1:k + 2] == ["recurse"]) or (
                        a[:1] == "-" and a[:2] != "--" and any(c in a[1:] for c in letters)):
                    return True
        if b == "find" and (any(a in EXEC_OPTS or a.startswith("-fprint") or a == "-fls"
                                for a in rest) or XARGS_PIPE_RE.search(text)):
            return True
        if b in ("fd", "fdfind") and any(a in ("-x", "-X", "--exec", "--exec-batch")
                                         or a.startswith("--exec") for a in rest):
            return True
        if b == "git" and "--no-index" in rest:
            return True
    return False


def _dequote(text):
    return re.sub(r"['\"\\]", "", text)


def _assignments(text):
    out = {}
    for m in ASSIGN_TEXT_RE.finditer(text):
        out.setdefault(m.group(1), m.group(2))
    return out


def _path_like(token):
    return "/" in token or token[:1] in ("~", ".", "$") or token in ("auth.json",) + CRED_NAMES


def shell_bases(text, cwd, paths, assigns):
    """Directories a relative path in `text` may resolve against: cwd and every cd/pushd target."""
    bases = [cwd] if cwd else []
    for m in CD_RE.finditer(text):
        for cand in paths.expand(m.group(1), bases[:1] or ["/"], assigns):
            if cand not in bases and len(bases) < 16:
                bases.append(os.path.normpath(cand))
    return bases


RUNNER_HEADS = SHELLS | STRING_RUNNERS | {"sudo", "doas", "env", "nohup", "timeout", "gtimeout",
                                          "time", "exec", "command", "builtin", "nice", "stdbuf",
                                          "caffeinate", "xargs", "find", "source", "."}
STDIN_CODE_RE = re.compile(r"\|\s*(?:\S*/)?(?:sh|bash|zsh|dash|ksh|fish|source|\.|python[\d.]*|perl|"
                           r"ruby|node|osascript)(?:\s|\Z)|\b(?:eval|iex)\b")


def _head_writes(b, nxt):
    """Program `b` with arguments `nxt` writes files: a writer, sed/perl -i, find -delete/-exec,
    curl/wget -o, awk system()/-i, or inline interpreter code."""
    if b in PLAIN_WRITERS:
        return True
    if b in ("sed", "gsed", "perl", "ruby") and any(
            a == "--in-place" or a.startswith("--in-place=") or
            (a[:1] == "-" and a[:2] != "--" and "i" in a[1:].split("e")[0]) for a in nxt[:8]):
        return True
    if b == "find" and any(a in FIND_WRITE_OPTS for a in nxt):
        return True
    if b in ("curl", "wget") and any(a in ("-o", "-O", "--output", "--output-document", "-P",
                                           "--directory-prefix", "--remote-name")
                                     or (a[:1] == "-" and a[:2] != "--" and ("o" in a or "O" in a))
                                     for a in nxt):
        return True
    if b in ("awk", "gawk", "mawk", "nawk") and ("system" in " ".join(nxt) or "-i" in nxt):
        return True
    return bool(INTERPRETER_RE.match(b)) and any(CODE_FLAG_RE.match(a) or a == "eval"
                                                for a in nxt[:4])


def _segment_writes(words):
    """The simple command (dequoted words) writes files. Its command word decides (after X=1 and
    wrappers); only a runner (a shell, eval, sudo, env, xargs, find, ...) has every later word read
    as a possible command, so `git commit -m 'rm ...'` is data and `bash -c 'rm ...'` is not."""
    k = 0
    while k < len(words) and (ASSIGN_RE.match(words[k]) or words[k] in PREFIX_WORDS):
        k += 1
    if k >= len(words):
        return False
    head = _base(words[k])
    if _head_writes(head, words[k + 1:]):
        return True
    if head not in RUNNER_HEADS:
        return False
    return any(_head_writes(_base(w), words[j + 1:]) for j, w in enumerate(words) if j > k)


def _code_writes(text):
    """Inline interpreter code (python -c ..., node -e ...) or commands read from a pipe or eval:
    its text is split by the segment cut, so every segment of such a command counts as a writer."""
    for seg in SEG_SPLIT_RE.split(text):
        words = TOKEN_RE.findall(seg)
        if any(INTERPRETER_RE.match(_base(w)) and any(CODE_FLAG_RE.match(a) or a == "eval"
                                                     for a in words[j + 1:j + 5])
               for j, w in enumerate(words)):
            return True
    return bool(STDIN_CODE_RE.search(text))


def shell_path_violation(command, cwd, paths, escalation=False):
    """("cred"|"protect", token) for a shell command that names a credential path anywhere, or that
    writes (a redirection target, or a writing simple command naming it) under a protected root;
    with escalation=True any mention of a protected root counts. Textual and nesting-agnostic
    (quotes and backslashes dropped; $(...), backticks, bash -c strings and heredoc bodies cut
    into their own segments): the sandbox (L1) is the primary line, this the second. A command
    too large to check in DEADLINE_S is refused."""
    text = _dequote(command)
    assigns = _assignments(text)
    bases = shell_bases(text, cwd, paths, assigns)
    in_root = any(paths.protected(b) or paths.credential(b) for b in bases)
    budget, deadline = [MAX_REALPATHS], time.monotonic() + DEADLINE_S
    codex_named = ".codex" in text or "CODEX_HOME" in text or paths.codex_home in text
    all_write = escalation or _code_writes(text)

    def check(token, write, where=None, recursive=False):
        cands = paths.expand(token, where or bases, assigns)
        base = os.path.basename(token.rstrip("/"))
        if base in CRED_NAMES or (base == "auth.json" and codex_named):
            return ("cred", token)
        for c in cands:
            if paths.credential(c, budget):
                return ("cred", token)
            if GLOB_CHARS_RE.search(c) and paths.glob_credential(c, recursive):
                return ("cred", token)
            if recursive and paths.holds_credential(c, budget):
                return ("cred", token)
        if write and (PROTECTED_TEXT_RE.search(token) or any(paths.protected(c, budget)
                                                            for c in cands)):
            return ("protect", token)
        return None

    for raw in (command, text):
        for m in REDIRECT_RE.finditer(raw):
            target = _dequote(m.group(1))
            if target and target not in RO_DEVICES:
                found = check(target, True)
                if found:
                    return found
    for n, seg in enumerate(SEG_SPLIT_RE.split(text)):
        if not n % 64 and time.monotonic() > deadline:
            return ("protect", "(a command too large to check in time)")
        words = TOKEN_RE.findall(seg)
        where = bases
        if "git" in seg:                       # git -C DIR ... -F FILE: FILE is read from DIR
            dirs, files = _git_reads(seg.split())
            where = _git_bases(dirs, bases, paths, assigns)
            for f in files:
                found = check(f, False, where)
                if found:
                    return found
        writes = all_write or _segment_writes(words)
        recursive = _recursive_read(words, text)
        if recursive:                          # `cd ~/.codex && rg x`: the cwd is an operand
            for b in where:
                if paths.holds_credential(b, budget):
                    return ("cred", b)
        found = _git_dir_violation(words, check, in_root)
        if found:
            return found
        for w in words:
            if in_root or _path_like(w) or (writes and PROTECTED_TEXT_RE.search(w)) or (
                    recursive and w[:1] != "-"):
                found = check(w, writes, where, recursive)
                if found:
                    return found
    return None


def _git_reads(words):
    """([-C dirs], [file values]) of the git commands among `words` (dequoted, whitespace-split):
    the -C directories in order, and the values of git's file-reading options (_git_file_values)
    other than `-` (stdin)."""
    dirs, files = [], []
    for k, w in enumerate(words):
        if _base(w) != "git":
            continue
        j = k + 1
        while j < len(words) and words[j][:1] == "-":
            o = words[j]
            if o == "-C":
                dirs.append(words[j + 1] if j + 1 < len(words) else "")
                j += 2
            elif o[:2] == "-C":
                dirs.append(o[2:])
                j += 1
            else:
                j += 2 if o in GIT_OPTS_WITH_VALUE else 1
        if j < len(words):
            files += [v for _, v in _git_file_values(words[j], words[j + 1:j + 257]) if v and v != "-"]
    return dirs, files


def _git_bases(dirs, bases, paths, assigns):
    """The bases plus the directories `git -C a -C b` runs in (a, then a/b, against every base);
    an unresolvable -C value adds nothing (its files are still checked against the bases)."""
    out, cur = list(bases), list(bases)
    for d in dirs[:8]:
        nxt = [os.path.normpath(c) for c in paths.expand(d, cur or ["/"], assigns)]
        if not nxt:
            break
        cur = nxt[:16]
        out += [c for c in cur if c not in out]
    return out[:32]


GIT_DIR_OPTS = ("-C", "--git-dir", "--work-tree")


def _git_dir_violation(words, check, in_root):
    """git writes its repository: a -C/--git-dir/--work-tree value under a protected root (or any
    git run while cwd or a cd target is inside one) counts as a write there. Commit messages and
    other arguments are data."""
    for k, w in enumerate(words):
        if _base(w) != "git":
            continue
        if in_root:
            return ("protect", w)
        for j in range(k + 1, min(len(words), k + 12)):
            a = words[j]
            value = words[j + 1] if a in GIT_DIR_OPTS and j + 1 < len(words) else (
                a[2:] if a[:2] == "-C" and len(a) > 2 else None)
            if value:
                found = check(value, True)
                if found:
                    return found
    return None


def path_reason(found, label):
    kind, token = found
    shown = "`%s`" % token[:160]
    return CRED_REASON % (label, shown) if kind == "cred" else PROTECT_REASON % (label[:160], shown)


# ---------------------------------------------------------------- apply_patch
PATCH_HEADER_RE = re.compile(r"^[ \t]*\*\*\* (?:Add File|Update File|Delete File|Move to):[ \t]*(.*?)[ \t]*$",
                             re.M)


def patch_texts(tool_input):
    """Every string of apply_patch's input (the patch is tool_input.command per the docs; other
    keys are read too, since the field name is unverified)."""
    if isinstance(tool_input, str):
        return [tool_input]
    if not isinstance(tool_input, dict):
        return None
    out = [v for v in tool_input.values() if isinstance(v, str)]
    for v in tool_input.values():
        if isinstance(v, list):
            out.extend(x for x in v if isinstance(x, str))
    return out


def patch_violation(texts, cwd, paths):
    """(kind, path) for the first patch path (Add/Update/Delete File, Move to) that resolves,
    against cwd with symlinks resolved, under a protected root or to a credential; ("cwd", path)
    when a relative path has no absolute cwd to resolve against."""
    for text in texts:
        for m in PATCH_HEADER_RE.finditer(text):
            p = m.group(1)
            if not p:
                continue
            p = os.path.expanduser(p) if p.startswith("~") else p
            if not os.path.isabs(p):
                if not cwd:
                    return ("cwd", p)
                p = os.path.join(cwd, p)
            if paths.credential(p):
                return ("cred", m.group(1))
            if paths.protected(p):
                return ("protect", m.group(1))
    return None


def patch_reason(found):
    kind, p = found
    if kind == "cwd":
        return PATCH_INPUT_REASON % ("the event has no absolute cwd for `%s`" % p[:120])
    if kind == "cred":
        return CRED_REASON % ("apply_patch", "`%s`" % p[:160])
    return PATCH_REASON % ("`%s`" % p[:160])


# ---------------------------------------------------------------- images


def heic_size(b):
    """The largest (width, height) of the `ispe` properties in an ISOBMFF (HEIC/HEIF/AVIF) header."""
    best, i = None, b.find(b"ispe")
    while 0 <= i and i + 16 <= len(b):
        w, h = int.from_bytes(b[i + 8:i + 12], "big"), int.from_bytes(b[i + 12:i + 16], "big")
        if best is None or max(w, h) > max(best):
            best = (w, h)
        i = b.find(b"ispe", i + 4)
    return best


def file_image_size(path):
    """(width, height) from the header of a regular file; None when unknown or not a regular file
    (O_NONBLOCK and fstat: a FIFO or a device is never read)."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        import stat
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        head = os.read(fd, 1 << 20)
    except OSError:
        return None
    finally:
        os.close(fd)
    size = image_size(head)
    if size is None and head[4:8] == b"ftyp":
        size = heic_size(head)
    return size


def image_violation(path, max_px):
    """The deny reason for an image file above max_px (or of unreadable size), else None.
    A missing file passes (the tool reports it)."""
    if not os.path.isfile(path):
        return None
    size = file_image_size(path)
    if size is None:
        return IMAGE_UNKNOWN_REASON % ("`%s`" % path[:160], max_px)
    if max(size) > max_px:
        return IMAGE_REASON % ("`%s`" % path[:160], "%dx%d" % size, max_px, max_px - 1)
    return None


# ---------------------------------------------------------------- read-only allowlist
# The idea of agent_guard._ReadOnly, smaller: every simple command (also inside $(...), bash -c,
# find -exec and xargs) must be on the allowlist below; files are written only in scratch dirs
# ($TMPDIR, /tmp, /var/folders, ./.claude-work); anything not recognised is refused (fail closed).
# Inline code passes only without file, process, module or network calls (RO_CODE_BAD_RE).
RO_SCRATCH_TMP = ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders")
RO_EXPORTS = {"export", "declare", "typeset", "local", "readonly"}
RO_DATA_KW = {"for", "case", "select", "in", "function"}     # their words are data, not commands
RO_PREFIX_KW = {"if", "while", "until", "!", "then", "do", "else", "elif", "{", "}", "done", "fi",
                "esac"}                                     # a command follows (or nothing)
RO_BRANCH_BAD = {"-d", "-D", "-m", "-M", "-c", "-C", "--delete", "--move", "--copy", "-u",
                 "--set-upstream-to", "--unset-upstream", "--edit-description", "-f", "--force",
                 "--create-reflog", "-t", "--track", "--no-track"}
RO_FIRST_WORD = {"stash": {"list", "show"}, "worktree": {"list"}, "notes": {"list", "show"},
                 "submodule": {"status", "summary"}, "lfs": {"ls-files", "status", "env"},
                 "sparse-checkout": {"list"}, "bisect": {"log", "visualize", "view"},
                 "remote": {"-v", "--verbose", "show", "get-url"}}
RO_GIT_OPTS_FLAG = {"--no-pager", "-P", "--no-optional-locks", "--literal-pathspecs",
                    "--no-replace-objects", "--glob-pathspecs", "--noglob-pathspecs",
                    "--icase-pathspecs", "--paginate", "-p"}
RO_GIT_OPTS_VALUE = {"-C", "--git-dir", "--work-tree", "--namespace"}
RO_UV_FLAGS = {"--no-project", "--frozen", "--locked", "--isolated", "--no-sync", "-q", "--quiet",
               "--offline", "--no-progress", "--all-extras", "--no-dev", "--exact", "-v",
               "--verbose", "--no-config", "--managed-python", "--no-managed-python"}
RO_UV_VALUES = {"--with", "--with-requirements", "--with-editable", "--python", "-p", "--project",
                "--directory", "--extra", "--group", "--package", "--index", "--index-url",
                "--default-index", "--env-file", "--only-group", "--no-group"}
RO_XARGS_VALUES = {"-I", "-i", "-n", "-L", "-l", "-P", "-d", "-E", "-e", "-s", "-a", "-R", "-S",
                   "--max-args", "--max-lines", "--max-procs", "--delimiter", "--arg-file",
                   "--replace", "--eof", "--max-chars"}
RO_NPM_SUBS = {"test", "t", "ls", "list", "outdated", "view", "info", "why", "explain", "audit",
               "--version", "-v", "help"}
RO_NPM_SCRIPTS = {"test", "lint", "typecheck", "type-check", "check"}
RO_CARGO_SUBS = {"check", "test", "clippy", "metadata", "tree", "search", "verify-project",
                 "version", "--version", "-V", "help", "bench", "nextest"}
RO_GO_SUBS = {"test", "vet", "list", "version", "doc", "help"}
RO_CODE_FLAGS = {"-c", "-e", "-E", "--eval", "-p", "--print", "-r"}
PYTHON_RE = re.compile(r"(?:python|pypy)[\d.]*\Z")
SED_WRITE_RE = re.compile(r"[;{}\n/\d$]\s*[wWe](?:\s|$)|/[gpIiMm0-9]*[we](?:\s|;|$)|^\s*[wWe]\s")
AWK_BAD_RE = re.compile(r"system\s*\(|\|\s*\"|\"\s*\||>|\|&|getline")


def _scratch(path, cwd):
    """`path` (as typed) lies in a scratch dir: $TMPDIR, the temp dirs, ./.claude-work."""
    if path in RO_DEVICES:
        return True
    p = path
    tmp = os.environ.get("TMPDIR", "")
    if tmp.startswith("/"):
        p = re.sub(r"\A\$(?:\{TMPDIR\}|TMPDIR)(?=/|\Z)", lambda m: tmp.rstrip("/"), p)
    if re.search(r"[$`*?\[\]{}~]", p):
        return False
    if not os.path.isabs(p):
        if not cwd:
            return False
        p = os.path.join(cwd, p)
    tmp_roots = _real_roots(list(RO_SCRATCH_TMP) + ([tmp] if tmp.startswith("/") else []))
    work = _real_roots([os.path.join(cwd, ".claude-work")] if cwd else [])
    # the project is the project's own even when it lives under a temp dir (a checkout in /tmp):
    # only its ./.claude-work is scratch, unless cwd is itself a temp root (or holds one)
    project = [] if not cwd else [c for c in _real_roots([cwd])
                                  if not any(within(r, c) for r in tmp_roots)]
    for v in _variants(p):
        if any(within(v, w) for w in work):
            continue
        if any(within(v, c) for c in project) or not any(within(v, r) for r in tmp_roots):
            return False
    return True


def _real_roots(paths):
    out = []
    for r in paths:
        for v in _variants(r):
            if v not in out and v != "/":
                out.append(v)
    return out


def _ro_outputs(rest, names, cwd, getopt=False):
    """An output option whose value is not scratch: --output FILE, --output=FILE, -o FILE and the
    attached short form -oFILE. getopt=True (the GNU-style plain tools: sort, shuf, iconv, tree,
    ...) also reads -o inside a short cluster (-ro FILE, -roFILE) and any unique abbreviation of
    --output (--out, --outp=FILE)."""
    for k, a in enumerate(rest):
        name, eq, val = a.partition("=")
        nxt = rest[k + 1] if k + 1 < len(rest) else ""
        value = None
        if name in names or (getopt and _long_abbrev(name, "--output")):
            value = val if eq else nxt
        elif a[:1] == "-" and a[:2] != "--" and len(a) > 2:
            if a[:2] in names:
                value = a[2:]
            elif getopt and "-o" in names and "o" in a[1:]:
                value = a[a.index("o", 1) + 1:] or nxt
        if value is not None and not _scratch(value, cwd):
            return (a, "writes outside the scratch dirs")
    return None


def _long_abbrev(name, option, minimum=3):
    """`name` is `option` or a getopt_long abbreviation of it (at least `minimum` characters)."""
    return name[:2] == "--" and len(name) >= minimum and option.startswith(name)


def _ro_by_path(word, cwd):
    """A command word naming its program by path ("/" in it) is the named tool only in a system
    bin dir or a project virtualenv/node_modules bin that is not scratch; anything else runs
    whatever was written there (a scratch copy of /bin/sh named cat)."""
    if re.search(r"[$`*?\[\]{}~\x00]", word):
        return (word[:80], "names its program through a variable, ~ or a glob")
    if not os.path.isabs(word) and not cwd:
        return (word[:80], "runs a program by a relative path")
    p = os.path.normpath(os.path.join(cwd or "/", word))
    d = os.path.dirname(p)
    if not (d in RO_SYSTEM_BIN or RO_VENV_BIN_RE.search(d)) or _scratch(d, cwd) \
            or _scratch(real_path(d), cwd) or _scratch(real_path(p), cwd):
        return (word[:80], "runs a program by path (only system and project tool dirs are "
                           "allowed; run tools by name)")
    return None


def _ro_var_name(word):
    """The variable a read/printf -v/declare name argument binds (PATH[0], 'PATH?prompt')."""
    return re.split(r"[\[?]", word, maxsplit=1)[0]


def _ro_binds(head, rest):
    """hash -p, read, printf -v and declare -n bind a variable or a command path without an
    assignment word: refused for the exec-relevant variables (and hash -p, declare -n always)."""
    names = []
    if head == "hash":
        if any(a[:1] == "-" and a[:2] != "--" and "p" in a for a in rest):
            return ("hash -p", "binds a command name to a program path")
        return None
    if head in ("declare", "typeset", "local") and any(
            a[:1] == "-" and a[:2] != "--" and "n" in a for a in rest):
        return ("%s -n" % head, "makes a name reference (it can set any variable)")
    if head == "read":
        for a in rest:
            names.append(a[2:] if a[:1] == "-" and len(a) > 2 else a)
    elif head == "printf":
        for k, a in enumerate(rest):
            if a == "-v" and k + 1 < len(rest):
                names.append(rest[k + 1])
            elif a.startswith("-v") and len(a) > 2:
                names.append(a[2:])
    for n in names:
        name = _ro_var_name(n)
        if RO_EXEC_VAR_RE.match(name) and name not in RO_SAFE_VARS:
            return ("%s %s" % (head, n)[:80], "sets %s, which changes what programs run or load"
                    % name)
    return None


def _ro_plain(head, word0, rest, cwd, depth):
    """The plain readers' special cases: what runs code (trap, rg --pre, sort --compress-program,
    a pager option), what writes (an output operand or option, mktemp outside scratch) and what
    prints the whole environment (bare set)."""
    bad = _ro_binds(head, rest)
    if bad:
        return bad
    if head == "trap":
        args = rest[1:] if rest[:1] == ["--"] else rest
        code = args[0] if args and args[0] not in ("-", "-l", "-p") else ""
        return readonly_violation(code, cwd, depth + 1) if code.strip() else None
    if head == "set":
        return None if rest and rest[0][:1] in "-+" else (
            word0, "prints every shell variable (they can hold keys)")
    if head == "sysctl" and any(a == "-w" or "=" in a for a in rest):
        return (word0, "changes a kernel setting")
    if head == "sort" and any(a.startswith("--co") for a in rest):
        return ("sort --compress-program", "runs a compression program")
    if head == "rg" and any(a.partition("=")[0] == "--pre" for a in rest):
        return ("rg --pre", "runs a preprocessor command")
    if head in RO_PAGER_HEADS and any(a.partition("=")[0] == "--pager" for a in rest):
        return ("%s --pager" % word0, "runs a pager command")
    if head == "mktemp":
        return _ro_mktemp(rest, cwd)
    if head in RO_OPERAND_VALUE_OPTS:
        ops, k, opts = [], 0, RO_OPERAND_VALUE_OPTS[head]
        while k < len(rest):
            a = rest[k]
            if a in opts:
                k += 2
                continue
            if a[:1] != "-" or a == "-":
                ops.append(a)
            k += 1
        if len(ops) >= 2 and not _scratch(ops[1], cwd):
            return ("%s %s" % (word0, ops[1])[:80], "writes outside the scratch dirs")
    if head in RO_OUT_OPTS_PLAIN:
        return _ro_outputs(rest, RO_OUT_OPTS, cwd, getopt=True)
    return None


def _ro_mktemp(rest, cwd):
    """mktemp creates its file in scratch only: no -p/--tmpdir outside scratch, and a template
    holding "/" (or any template without -t/-p/--tmpdir, which is relative to cwd) is scratch."""
    tdir, implied, temps, k = None, False, [], 0
    while k < len(rest):
        a = rest[k]
        if a == "-p":
            tdir, k = (rest[k + 1] if k + 1 < len(rest) else ""), k + 2
            continue
        if a.startswith("--tmpdir"):
            tdir = a.partition("=")[2] or "$TMPDIR"
        elif a[:1] == "-" and a[:2] != "--" and len(a) > 1:
            if "t" in a:
                implied = True
            if "p" in a:
                tail = a[a.index("p") + 1:]
                if tail:
                    tdir = tail
                else:
                    tdir, k = (rest[k + 1] if k + 1 < len(rest) else ""), k + 1
        elif a[:1] != "-":
            temps.append(a)
        k += 1
    if tdir is not None and not _scratch(tdir, cwd):
        return ("mktemp " + tdir[:70], "creates a file outside the scratch dirs")
    for t in temps:
        if (implied or tdir is not None) and "/" not in t:
            continue
        if implied or not _scratch(t, cwd):    # -t TEMPLATE is relative to $TMPDIR: no "/"
            return ("mktemp " + t[:70], "creates a file outside the scratch dirs")
    return None


def _ro_assign(word):
    name = word.split("=", 1)[0].rstrip("+")
    if RO_EXEC_VAR_RE.match(name) and name not in RO_SAFE_VARS:
        return (word[:80], "sets %s, which changes what programs run or load" % name)
    return None


def _ro_redirections(words, cwd):
    """(the words without redirections, None) or (None, violation): a redirection writes only to
    a device or a scratch path; fd duplications (2>&1) are fine."""
    out, k = [], 0
    while k < len(words):
        w = words[k]
        if w.isdigit() and k + 1 < len(words) and (REDIR_OP_RE.match(words[k + 1])
                                                    or words[k + 1] in (">|", "<>")):
            k += 1
            continue
        if REDIR_OP_RE.match(w) or w in (">|", "<>", "<<<"):
            target = words[k + 1] if k + 1 < len(words) else ""
            writes = ">" in w
            dup = w.endswith("&") and (target.isdigit() or target == "-")
            if writes and not dup and not _scratch(target, cwd):
                return None, ((w + " " + target)[:80], "writes outside the scratch dirs")
            k += 2
            continue
        out.append(w)
        k += 1
    return out, None


def _ro_unwrap(args, cwd=None):
    """Drop assignments, keywords and wrappers (time, nice, timeout, env, command, ...) in front of
    a command: (the command words, None) or (None, violation). A wrapper named by path is checked
    like any program by path; time's output file must be scratch; env with no command prints the
    environment, and env -S runs a string the check does not split."""
    while args:
        w = args[0]
        if ASSIGN_RE.match(w):
            bad = _ro_assign(w)
            if bad:
                return None, bad
            args = args[1:]
            continue
        if w in RO_PREFIX_KW:
            args = args[1:]
            continue
        if w in RO_DATA_KW:
            return [], None                    # for/case/select headers: their words are data
        b = _base(w)
        if b in RO_WRAPPERS:
            if "/" in w:
                bad = _ro_by_path(w, cwd)
                if bad:
                    return None, bad
            opts, k = RO_WRAPPERS[b], 1
            while k < len(args) and (args[k][:1] == "-" or ASSIGN_RE.match(args[k])
                                     or (b in ("timeout", "gtimeout") and _duration(args[k]))):
                a = args[k]
                if ASSIGN_RE.match(a):
                    bad = _ro_assign(a)
                    if bad:
                        return None, bad
                name = a.partition("=")[0]
                if b == "env" and (a.startswith("-S") or _long_abbrev(name, "--split-string")):
                    return None, ("env " + a[:60], "runs a string the read-only check does "
                                                   "not split (env -S)")
                if b == "time" and (a.startswith("-o") or _long_abbrev(name, "--output")):
                    val = a.partition("=")[2] if "=" in a else (
                        a[2:] if a[:2] == "-o" and len(a) > 2 else
                        (args[k + 1] if k + 1 < len(args) else ""))
                    if not _scratch(val, cwd):
                        return None, ("time " + a[:60], "writes outside the scratch dirs")
                k += 2 if a in opts else 1
            if b == "env" and k >= len(args):
                return None, ("env", "prints the environment (it can hold keys)")
            args = args[k:]
            continue
        return args, None
    return args, None


def readonly_violation(command, cwd, depth=0):
    """(what, why) when a shell command is not on the read-only allowlist, else None."""
    if not isinstance(command, str):
        return ("(not a string)", "cannot be read")
    if depth > MAX_NEST:
        return (command[:80], "nests too deeply to check")
    try:
        text, heredocs, substs = _lex(command, time.monotonic() + DEADLINE_S)
    except _TooComplex as exc:
        return (command[:80], str(exc))
    for inner, _ in substs:
        bad = readonly_violation(inner, cwd, depth + 1)
        if bad:
            return bad
    for owner, body, quoted in heredocs:
        if _heredoc_runs_code(owner) or _heredoc_interpreter(owner):
            return (owner.strip()[:80], "feeds a heredoc to a shell or interpreter")
        for inner in ([] if quoted else _raw_substs(body)):
            bad = readonly_violation(inner, cwd, depth + 1)
            if bad:
                return bad
    try:
        words = _shell_words(text)
    except ValueError:
        return (command[:80], "has unbalanced quotes")
    restore = _restorer(substs)
    seg = []
    for w in words + [";"]:
        if SEP_RE.match(w):
            bad = _ro_simple([restore(x) for x in seg], cwd, depth) if seg else None
            if bad:
                return bad
            seg = []
        else:
            seg.append(w)
    return None


def _ro_simple(words, cwd, depth):
    args, bad = _ro_redirections(words, cwd)
    if bad:
        return bad
    args, bad = _ro_unwrap(args, cwd)
    if bad or not args:
        return bad
    return _ro_command(_base(args[0]), args[0], args[1:], cwd, depth)


def _ro_command(head, word0, rest, cwd, depth):
    if "/" in word0:                           # every head: plain, find -exec, xargs, uv run, uvx
        bad = _ro_by_path(word0, cwd)
        if bad:
            return bad
    if len(rest) == 1 and rest[0] in RO_VERSION_FLAGS:
        return None
    if head in RO_EXPORTS:
        bad = _ro_binds(head, rest)
        if bad:
            return bad
        if not [a for a in rest if a[:1] != "-"]:
            return (word0, "prints variables (they can hold keys)") if head != "local" else None
        for a in rest:
            bad = _ro_assign(a) if ASSIGN_RE.match(a) else None
            if bad:
                return bad
        return None
    if head in RO_PLAIN:
        return _ro_plain(head, word0, rest, cwd, depth)
    if head in RO_WRITERS:
        return _ro_writer(head, word0, rest, cwd)
    handler = RO_HANDLERS.get(head)
    if handler is not None:
        return handler(head, word0, rest, cwd, depth)
    if PYTHON_RE.match(head):
        return _ro_python(head, word0, rest, cwd, depth)
    if head in RO_CHECK_ONLY:
        need, bad = RO_CHECK_ONLY[head]
        if any(a in bad for a in rest) or not any(a in need for a in rest):
            return (word0, "rewrites files unless run with %s" % "/".join(sorted(need)))
        return None
    if head in RO_TOOLS:
        banned = RO_TOOLS[head]
        for a in rest:
            if a in banned or a.split("=", 1)[0] in banned:
                return ("%s %s" % (word0, a), "changes files or posts results")
        return _ro_outputs(rest, RO_TOOL_OUTS.get(head, RO_OUT_OPTS), cwd)
    return (word0[:80], "is not on the read-only allowlist")


def _ro_writer(head, word0, rest, cwd):
    """A writer (mkdir, touch, rm, cp, mv, tee, ...) whose targets are all scratch."""
    value_opts = RO_WRITER_VALUE_OPTS.get(head, set())
    if head == "rsync" and any(a.startswith("--remove-source") for a in rest):
        return (word0, "removes its source files")
    if head == "dd":
        targets = [a[3:] for a in rest if a.startswith("of=")]
    else:
        targets, k = [], 0
        while k < len(rest):
            a = rest[k]
            if a in value_opts:
                if a in ("-t", "--target-directory") and k + 1 < len(rest):
                    targets.append(rest[k + 1])
                k += 2
                continue
            if a == "--":
                targets.extend(rest[k + 1:])
                break
            if a[:1] != "-" or a == "-":
                targets.append(a)
            k += 1
        if head == "chmod" and targets:
            targets = targets[1:]              # the mode
        if head in ("cp", "install", "rsync", "ditto") and targets:
            targets = targets[-1:]             # sources are read; the destination is written
    for t in targets:
        if t != "-" and not _scratch(t, cwd):
            return ("%s %s" % (word0, t)[:80], "writes outside the scratch dirs")
    return None


def _ro_sed(head, word0, rest, cwd, depth):
    scripts, k, explicit = [], 0, False
    while k < len(rest):
        a = rest[k]
        if a == "--in-place" or a.startswith("--in-place="):
            return (word0 + " " + a, "edits files in place")
        if a in ("-e", "--expression") and k + 1 < len(rest):
            scripts.append(rest[k + 1])
            explicit, k = True, k + 2
            continue
        if a in ("-f", "--file"):
            return (word0 + " " + a, "runs a script file the check cannot read")
        if a[:1] == "-" and a[:2] != "--" and len(a) > 1:
            for c in a[1:]:
                if c == "i":
                    return (word0 + " " + a, "edits files in place")
                if c in "ef":
                    break
        elif a[:1] != "-" and not explicit and not scripts:
            scripts.append(a)
        k += 1
    for s in scripts:
        if SED_WRITE_RE.search(s):
            return (word0, "its script writes a file or runs a command (w/W/e)")
    return None


def _ro_awk(head, word0, rest, cwd, depth):
    k = 0
    while k < len(rest):
        a = rest[k]
        if a in ("-f", "--file", "-i", "--include", "-l", "--load", "-E", "--exec"):
            return (word0 + " " + a, "loads program text the check cannot read")
        if a in ("-v", "-F", "--assign", "--field-separator"):
            k += 2
            continue
        if a[:1] != "-":
            if AWK_BAD_RE.search(a):
                return (word0, "its program writes, pipes or runs commands")
            return None
        k += 1
    return None


def _ro_find(head, word0, rest, cwd, depth):
    k = 0
    while k < len(rest):
        a = rest[k]
        if a == "-delete" or a.startswith("-fprint") or a == "-fls":
            return ("find " + a, "deletes or writes files")
        if a in EXEC_OPTS:
            j, inner = k + 1, []
            while j < len(rest) and rest[j] not in (";", "+"):
                inner.append(rest[j])
                j += 1
            if not inner:
                return ("find " + a, "runs nothing it can check")
            bad = _ro_command(_base(inner[0]), inner[0], inner[1:], cwd, depth + 1)
            if bad:
                return bad
            k = j + 1
            continue
        k += 1
    return None


def _ro_xargs(head, word0, rest, cwd, depth):
    k = 0
    while k < len(rest) and rest[k][:1] == "-":
        k += 2 if rest[k] in RO_XARGS_VALUES else 1
    inner = rest[k:]
    if not inner:
        return None                            # echo: prints its input
    if _base(inner[0]) in RO_WRITERS:
        return ("xargs " + inner[0], "writes to operands read from stdin")
    return _ro_command(_base(inner[0]), inner[0], inner[1:], cwd, depth + 1)


def _git_cwd(cwd, d):
    """The directory `git -C d` runs in, from `cwd`; None when the shell decides it at run time
    (then a relative output path is never scratch)."""
    if cwd is None or not d or re.search(r"[$`*?\[\]{}~]", d):
        return None
    return os.path.normpath(os.path.join(cwd, d))


def _ro_git(head, word0, rest, cwd, depth):
    k = 0
    while k < len(rest) and rest[k][:1] == "-":
        o = rest[k]
        if o == "-C" or (o[:2] == "-C" and len(o) > 2):
            # git -C DIR: relative paths (an --output file) are DIR's, not the caller's cwd
            cwd = _git_cwd(cwd, rest[k + 1] if o == "-C" and k + 1 < len(rest) else o[2:])
            k += 2 if o == "-C" else 1
            continue
        if o in RO_GIT_OPTS_VALUE:
            k += 2
            continue
        if o in RO_GIT_OPTS_FLAG or o.partition("=")[0] in RO_GIT_OPTS_VALUE:
            k += 1
            continue
        if o in ("--version", "--help", "-h", "--exec-path"):
            return None                        # bare --exec-path prints the path and exits
        return ("git " + o, "sets a git option the read-only check refuses (-c, which can define "
                            "an alias or a command, --exec-path=DIR, --config-env)")
    if k >= len(rest):
        return None
    sub, args = rest[k], rest[k + 1:]
    if sub in RO_GIT_READ:
        for a in args:
            # -O<cmd> attached, --open-files-in-pager / --ext-diff by any abbreviation (git takes
            # unique prefixes), ls-remote's --upload-pack/--exec/-u<cmd>
            if a.startswith("-O") or a.startswith("--op") or a.startswith("--ext") or (
                    sub == "ls-remote" and (a.startswith("-u") or a.startswith("--up")
                                            or a.startswith("--exe"))):
                return ("git %s %s" % (sub, a[:60]), "runs another program")
        for k, a in enumerate(args):
            name, eq, val = a.partition("=")
            if _long_abbrev(name, "--output", 4):
                value = val if eq else (args[k + 1] if k + 1 < len(args) else "")
                if not _scratch(value, cwd):
                    return ("git %s %s" % (sub, a[:60]), "writes outside the scratch dirs")
        return None
    if sub in RO_FIRST_WORD:
        if not args:
            return None if sub in RO_GIT_BARE_OK else ("git " + sub, "changes the repository")
        if args[0] in RO_FIRST_WORD[sub]:
            return None
        return ("git %s %s" % (sub, args[0]), "changes the repository")
    if sub in ("branch", "tag"):
        allowed = RO_GIT_LIST[sub]
        opts = [a.partition("=")[0] for a in args if a[:1] == "-"]
        if any(o in RO_BRANCH_BAD or o not in allowed for o in opts):
            return ("git %s %s" % (sub, " ".join(args[:2])), "changes the repository")
        if [a for a in args if a[:1] != "-"] and not opts:
            return ("git %s %s" % (sub, args[0]), "creates a branch or tag")
        return None
    if sub == "config":
        if any(a in RO_GIT_CONFIG_WRITE for a in args):
            return ("git config", "changes the configuration")
        if any(a in RO_GIT_CONFIG_READ for a in args):
            return None
        pos = [a for a in args if a[:1] != "-"]
        return None if len(pos) == 1 else ("git config", "changes the configuration")
    return ("git " + sub, "changes the repository or runs code")


def _ro_gh(head, word0, rest, cwd, depth):
    pos, k = [], 0
    while k < len(rest):
        a = rest[k]
        if a in GH_VALUE_OPTS:
            k += 2
            continue
        if a[:1] != "-":
            pos.append(a)
        k += 1
    if not pos or pos[0] in ("search", "status", "version", "help", "--version"):
        return None
    if pos[0] == "api":
        tail = rest[rest.index("api") + 1:]
        return ("gh api", "sends a write request") if _api_writes(tail, *GH_API[1:]) else None
    if pos[0] == "auth" and pos[1:2] == ["status"] and not any(
            a == "--show-token" or _cluster_has(a, "t", "hRspu") for a in rest):
        return None
    if len(pos) >= 2 and pos[1] in RO_GH_VERBS:
        return None
    return ("gh " + " ".join(pos[:2]), "is not a gh read")


def _ro_code(word0, code):
    if RO_CODE_BAD_RE.search(code):
        return (word0, "inline code that writes, runs, loads or reaches the network")
    return None


def _ro_python(head, word0, rest, cwd, depth):
    k = 0
    while k < len(rest) and rest[k][:1] == "-" and rest[k] not in ("-c", "-m", "-"):
        if rest[k] in ("-V", "--version", "-h", "--help"):
            return None
        k += 2 if rest[k] in ("-W", "-X") else 1
    if k >= len(rest) or rest[k] == "-":
        return (word0, "reads its program from stdin")
    a = rest[k]
    if a == "-c":
        return _ro_code(word0, rest[k + 1] if k + 1 < len(rest) else "")
    if a == "-m" and k + 1 < len(rest):
        mod, margs = rest[k + 1], rest[k + 2:]
        if mod not in RO_PY_MODULES:
            return ("%s -m %s" % (word0, mod), "is not a read-only module")
        if mod == "pip":
            sub = next((x for x in margs if x[:1] != "-"), "")
            return None if sub in ("list", "show", "freeze", "check", "") else (
                "pip " + sub, "changes the environment")
        name = mod.replace("_", "-")
        if name in RO_TOOLS or mod in RO_TOOLS:
            return _ro_command(name if name in RO_TOOLS else mod, mod, margs, cwd, depth)
        if name in RO_CHECK_ONLY or mod in ("ruff",):
            return _ro_command(name, mod, margs, cwd, depth)
        return None
    return ("%s %s" % (word0, a), "runs a script the read-only check cannot read")


def _ro_ruff(head, word0, rest, cwd, depth):
    sub = next((a for a in rest if a[:1] != "-"), "check")
    if sub == "check" and not any(a.split("=")[0] in ("--fix", "--unsafe-fixes", "--fix-only",
                                                      "--add-noqa") for a in rest):
        return _ro_outputs(rest, {"-o", "--output-file"}, cwd)
    if sub == "format" and any(a in ("--check", "--diff") for a in rest):
        return None
    if sub in ("version", "rule", "linter", "config"):
        return None
    return ("ruff " + sub, "rewrites files (use check without --fix, or format --check)")


def _ro_uv(head, word0, rest, cwd, depth):
    if head == "uvx":
        k = 0
        while k < len(rest) and rest[k][:1] == "-":
            k += 2 if rest[k] in RO_UV_VALUES or rest[k] == "--from" else 1
        inner = rest[k:]
        return _ro_command(_base(inner[0]), inner[0], inner[1:], cwd, depth + 1) if inner else None
    k = 0
    while k < len(rest) and rest[k][:1] == "-":
        k += 2 if rest[k] in RO_UV_VALUES else 1
    if k >= len(rest):
        return None
    sub, tail = rest[k], rest[k + 1:]
    if sub == "run":
        j = 0
        while j < len(tail) and tail[j][:1] == "-":
            if tail[j] in ("-m", "--module", "--script", "-s"):
                return ("uv run " + tail[j], "runs code the read-only check cannot read")
            if tail[j] not in RO_UV_FLAGS and tail[j] not in RO_UV_VALUES and \
                    tail[j].partition("=")[0] not in RO_UV_VALUES:
                return ("uv run " + tail[j], "is an option the read-only check does not know")
            j += 2 if tail[j] in RO_UV_VALUES else 1
        inner = tail[j:]
        if not inner:
            return ("uv run", "runs nothing it can check")
        return _ro_command(_base(inner[0]), inner[0], inner[1:], cwd, depth + 1)
    first = next((x for x in tail if x[:1] != "-"), "")
    if sub in ("pip",) and first in ("list", "show", "freeze", "check", "tree"):
        return None
    if sub == "python" and first in ("list", "find", "dir"):
        return None
    if sub in ("tree", "version", "help", "--version") or (sub == "lock" and "--check" in tail):
        return None
    return ("uv " + sub, "changes the environment or the project")


def _ro_cargo(head, word0, rest, cwd, depth):
    sub = next((a for a in rest if a[:1] != "-" or a in ("--version", "-V")), "")
    if sub == "fmt":
        return None if "--check" in rest else ("cargo fmt", "rewrites files (use --check)")
    if sub in RO_CARGO_SUBS and "--fix" not in rest:
        return None
    return ("cargo " + sub, "builds, installs or changes files")


def _ro_go(head, word0, rest, cwd, depth):
    sub = next((a for a in rest if a[:1] != "-"), "")
    if sub == "env" and not any(a in ("-w", "-u") for a in rest):
        return None
    if sub in RO_GO_SUBS:
        return _ro_outputs(rest, {"-o", "-coverprofile", "-cpuprofile", "-memprofile"}, cwd)
    return ("go " + sub, "builds, installs or changes files")


def _ro_npm(head, word0, rest, cwd, depth):
    pos = [a for a in rest if a[:1] != "-"]
    sub = pos[0] if pos else (rest[0] if rest else "")
    if sub == "audit" and "fix" in pos:
        return ("%s audit fix" % head, "changes the dependencies")
    if sub in RO_NPM_SUBS:
        return None
    if sub in ("run", "run-script") and pos[1:2] and pos[1] in RO_NPM_SCRIPTS:
        return None
    if head == "yarn" and sub in RO_NPM_SCRIPTS:
        return None
    return ("%s %s" % (head, sub), "changes the project or runs a script the check cannot read")


def _ro_interp(head, word0, rest, cwd, depth):
    for k, a in enumerate(rest):
        if head in ("perl", "ruby") and a[:1] == "-" and a[:2] != "--" and "i" in a[1:].split("e")[0]:
            return ("%s %s" % (word0, a), "edits files in place")
        if a in RO_CODE_FLAGS and k + 1 < len(rest):
            return _ro_code(word0, rest[k + 1])
        if a == "eval" and k == 0 and len(rest) > 1:
            return _ro_code(word0, rest[1])
    return (word0, "runs a script the read-only check cannot read")


def _ro_shell(head, word0, rest, cwd, depth):
    code, _ = _Scan.shell_code(rest)
    if code is not None:
        return readonly_violation(code, cwd, depth + 1)
    if any(_cluster_has(a, "n", "o") for a in rest):
        return None                            # bash -n script: syntax only
    return (word0, "runs a script the read-only check cannot read")


RO_HANDLERS = {"sed": _ro_sed, "gsed": _ro_sed, "awk": _ro_awk, "gawk": _ro_awk, "mawk": _ro_awk,
               "nawk": _ro_awk, "find": _ro_find, "xargs": _ro_xargs, "git": _ro_git,
               "gh": _ro_gh, "ruff": _ro_ruff, "uv": _ro_uv, "uvx": _ro_uv, "cargo": _ro_cargo,
               "go": _ro_go, "npm": _ro_npm, "pnpm": _ro_npm, "yarn": _ro_npm,
               "node": _ro_interp, "nodejs": _ro_interp, "deno": _ro_interp, "bun": _ro_interp,
               "ruby": _ro_interp, "perl": _ro_interp}
for _sh in RO_SHELL_NAMES:
    RO_HANDLERS[_sh] = _ro_shell


# ---------------------------------------------------------------- toolsmith (stack-install)
_SUPPORT = {}


def support_module(name):
    """hooks/<name>.py beside this file, loaded by path once (raises when missing: callers fail
    closed)."""
    if name not in _SUPPORT:
        _SUPPORT[name] = load_by_path("codex_guard_" + name, os.path.join(GUARD_DIR, name + ".py"))
    return _SUPPORT[name]


def is_wrapper_call(command, wrapper):
    """One plain command whose first word is exactly the stack-install wrapper (no shell syntax)."""
    import shlex
    text = command.strip()
    if TOOLSMITH_META_RE.search(text):
        return False
    try:
        words = shlex.split(text)
    except ValueError:
        return False
    return bool(words) and words[0] == wrapper


def toolsmith_command(ctx, command):
    """The deny reason for a toolsmith shell call, or None once it is allowed and its one-use
    ticket is written (agent_guard's toolsmith rule, with the wrapper path from guard.json)."""
    import shlex
    wrapper = ctx.guard.get("toolsmith_wrapper") or ""
    text = command.strip()
    bad = TOOLSMITH_META_RE.search(text)
    if not os.path.isabs(wrapper):
        return TOOLSMITH_SHAPE_REASON % ("stack-install", "guard.json names no wrapper", "stack-install")
    if bad:
        return TOOLSMITH_SHAPE_REASON % (wrapper, "%r is shell syntax" % bad.group(0), wrapper)
    try:
        words = shlex.split(text)
    except ValueError as exc:
        return TOOLSMITH_SHAPE_REASON % (wrapper, "unbalanced quotes (%s)" % exc, wrapper)
    if not words or words[0] != wrapper:
        return TOOLSMITH_SHAPE_REASON % (wrapper, "the first word is %r" % (words[0][:80] if words
                                                                           else ""), wrapper)
    args = words[1:]
    policy = support_module("toolsmith_policy")
    try:
        p = policy.parse(args)
    except policy.PolicyError as exc:
        return TOOLSMITH_ARGV_REASON % (" ".join(args)[:160], str(exc)[:300])
    who = p.get("req_for")
    if who and who != "user" and who not in ctx.agents["agents"]:
        return TOOLSMITH_ARGV_REASON % (" ".join(args)[:160], "--for %r is not a stack agent" % who)
    if p["sub"] == "run":
        approved = os.path.join(policy.state_dir(os.environ), "approved", p["id"] + ".json")
        if not os.path.isfile(approved):
            return TOOLSMITH_ARGV_REASON % (" ".join(args)[:160], "%s is not approved: the user "
                                            "runs `%s approve %s` in a terminal first"
                                            % (p["id"], wrapper, p["id"]))
    write_ticket(ctx, policy, args)
    return None


def write_ticket(ctx, policy, args):
    """The one-use ticket the executor claims for exactly `args` (raises on failure)."""
    folder = os.path.join(policy.state_dir(os.environ), "tickets")
    for d in (os.path.dirname(os.path.dirname(folder)), os.path.dirname(folder), folder):
        os.makedirs(d, mode=0o700, exist_ok=True)
    support_module("stack_io").write_json_atomic(
        os.path.join(folder, policy.ticket_name(args)),
        {"argv": list(args), "ts": time.time(), "session": ctx.session, "agent_id": ctx.agent_id,
         "agent_type": ctx.caller, "parent_id": None, "parent_type": None, "host": "codex"})


# ---------------------------------------------------------------- policy files


class PolicyError(Exception):
    """guard.json or agents.json is missing or malformed: gated calls are refused."""


def _abs_str(v):
    return isinstance(v, str) and os.path.isabs(v)


def read_json_file(path, limit=4 * 1024 * 1024):
    try:
        with open(path, "rb") as f:
            raw = f.read(limit + 1)
    except OSError as exc:
        raise PolicyError("%s: %s" % (os.path.basename(path), exc.strerror or exc))
    if len(raw) > limit:
        raise PolicyError("%s is too large" % os.path.basename(path))
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        raise PolicyError("%s is not JSON" % os.path.basename(path))
    if not isinstance(obj, dict):
        raise PolicyError("%s is not an object" % os.path.basename(path))
    return obj


def policy_dir(scope="profile"):
    """The directory holding guard.json: the installed stack/policy, else the guard's own (flat)
    directory. The global scope (the managed tier's flat, root-owned copy) looks beside itself
    first, so a policy dir next to the managed dir's parent never replaces it."""
    dirs = [os.path.join(os.path.dirname(GUARD_DIR), "policy"), GUARD_DIR]
    if scope == "global":
        dirs.reverse()
    for d in dirs:
        if os.path.isfile(os.path.join(d, "guard.json")):
            return d
    return None


def default_guard():
    """Profile-neutral defaults for `--scope global` without a guard.json beside the guard."""
    home = os.environ.get("HOME") or os.path.expanduser("~")
    ch = os.environ.get("CODEX_HOME") or os.path.join(home, ".codex")
    if not (os.path.isabs(home) and os.path.isabs(ch)):
        raise PolicyError("HOME/CODEX_HOME are not absolute")
    state = os.path.join(home, ".local", "state", "codex-agent-stack")
    return {"schema": 1, "codex_home": ch, "home": home, "state_dir": state,
            "protected_roots": [ch, os.path.join(home, ".agents"), state],
            "credentials": {"paths": [], "globs": []}}


def validate_guard(g):
    if g.get("schema") != 1:
        raise PolicyError("guard.json schema is not 1")
    for key in ("codex_home", "home", "state_dir"):
        if not _abs_str(g.get(key)):
            raise PolicyError("guard.json %s is not an absolute path" % key)
    roots = g.get("protected_roots")
    if not isinstance(roots, list) or not all(_abs_str(r) for r in roots):
        raise PolicyError("guard.json protected_roots is not a list of absolute paths")
    creds = g.get("credentials")
    if not isinstance(creds, dict) or not isinstance(creds.get("paths", []), list) or \
            not isinstance(creds.get("globs", []), list):
        raise PolicyError("guard.json credentials is not {paths: [], globs: []}")
    caps = g.get("caps", {})
    if not isinstance(caps, dict):
        raise PolicyError("guard.json caps is not an object")
    for key, default in DEFAULT_CAPS.items():
        if key in caps and not isinstance(caps[key], type(default)):
            raise PolicyError("guard.json caps.%s has the wrong type" % key)
    px = g.get("image_max_px", DEFAULT_IMAGE_MAX_PX)
    if not isinstance(px, int) or px <= 0:
        raise PolicyError("guard.json image_max_px is not a positive integer")
    return g


ROW_BOOLS = ("apply_patch", "shell", "spawn_tool", "readonly", "web_ingesting", "installer")


def validate_agents(a):
    if a.get("schema") != 1:
        raise PolicyError("agents.json schema is not 1")
    rows, bc = a.get("agents"), a.get("blackcat")
    if not isinstance(rows, dict) or not isinstance(bc, dict):
        raise PolicyError("agents.json needs agents and blackcat objects")
    for name, row in rows.items():
        if not isinstance(row, dict) or not TYPE_RE.match(name):
            raise PolicyError("agents.json row %r is malformed" % name[:40])
        if not all(isinstance(row.get(k, False), bool) for k in ROW_BOOLS):
            raise PolicyError("agents.json row %s has a non-boolean tool class" % name)
        if not all(isinstance(row.get(k, []), list) for k in ("spawn", "mcp")):
            raise PolicyError("agents.json row %s: spawn/mcp are not lists" % name)
        cap = row.get("max_tool_calls")
        if cap is not None and (not isinstance(cap, int) or isinstance(cap, bool)):
            raise PolicyError("agents.json row %s: max_tool_calls is not an integer" % name)
    if not isinstance(bc.get("spawn", []), list) or not isinstance(bc.get("mcp", []), list) or \
            not isinstance(bc.get("max_shell_reads_per_prompt", 3), int):
        raise PolicyError("agents.json blackcat row is malformed")
    if not isinstance(a.get("builtin_types", []), list):
        raise PolicyError("agents.json builtin_types is not a list")
    return a


def load_policy(scope):
    """(guard, agents). The global scope (the managed tier: requirements.py's flat managed-hooks/
    copy holds guard.json and no agents.json) never reads agents.json, so agents is None and only
    the profile-neutral checks run; without any guard.json it uses default_guard(). The profile
    scope needs both files: a missing, unreadable or malformed one is a PolicyError, which the
    gating modes turn into a deny (fail closed)."""
    d = policy_dir(scope)
    if d is None:
        if scope == "global":
            return validate_guard(default_guard()), None
        raise PolicyError("guard.json not found beside the guard")
    guard = validate_guard(read_json_file(os.path.join(d, "guard.json")))
    if scope == "global":
        return guard, None
    return guard, validate_agents(read_json_file(os.path.join(d, "agents.json")))


def cap(guard, key):
    return (guard.get("caps") or {}).get(key, DEFAULT_CAPS[key])


# ---------------------------------------------------------------- state (flock + atomic writes)
MAX_AGENTS, MAX_PENDING, PENDING_TTL_S = 4096, 256, 3600


def safe_id(value):
    if isinstance(value, str) and ID_RE.match(value) and value not in (".", ".."):
        return value
    import hashlib
    return "h-" + hashlib.sha256(repr(value).encode("utf-8", "replace")).hexdigest()[:32]


def fresh_state():
    return {"v": 1, "epoch": 0, "bc_shell": 0, "spawns": {}, "mcp_session": 0, "mcp_agent": {},
            "calls": {}, "agents": {}, "pending": []}


@contextlib.contextmanager
def locked_json(folder, name, fresh):
    """Read-modify-write `folder/name` under an exclusive flock on `folder/.lock`; the new state is
    written atomically (stack_io.write_json_atomic) when the block exits without an exception. The
    lock wait is bounded (LOCK_WAIT_S): a call that cannot get it is refused, never let through."""
    io = support_module("stack_io")
    os.makedirs(folder, mode=0o700, exist_ok=True)
    fd = os.open(os.path.join(folder, ".lock"), os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                 0o600)
    try:
        deadline = time.monotonic() + LOCK_WAIT_S
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (BlockingIOError, InterruptedError):
                if time.monotonic() > deadline:
                    raise RuntimeError("the guard state lock is busy")
                time.sleep(0.005)
        path = os.path.join(folder, name)
        state = io.read_json(path, default=None, limit=8 * 1024 * 1024)
        if not isinstance(state, dict) or state.get("v") != 1:
            state = fresh()
        yield state
        io.write_json_atomic(path, state)
    finally:
        os.close(fd)                           # closing the fd releases the flock


def session_state(ctx):
    return locked_json(os.path.join(ctx.paths.state_dir, "sessions", ctx.session), "state.json",
                       fresh_state)


def screen_state(ctx):
    return locked_json(os.path.join(ctx.paths.state_dir, "screen"), "screen.json",
                       lambda: {"v": 1, "holder": None, "ts": 0})


def trim_state(st):
    now = time.time()
    st["pending"] = [p for p in st["pending"] if now - p.get("ts", 0) < PENDING_TTL_S][-MAX_PENDING:]
    agents = st["agents"]
    if len(agents) > MAX_AGENTS:
        for k in [k for k, v in agents.items() if v.get("stopped")][:len(agents) - MAX_AGENTS]:
            del agents[k]


# ---------------------------------------------------------------- the call's context


def canon(agent_type):
    """lowercase, `_` -> `-`; "" when not a plausible type (then nothing matches it)."""
    if not isinstance(agent_type, str):
        return ""
    t = agent_type.strip().lower().replace("_", "-")
    return t if TYPE_RE.match(t) else ""


def classify(tool):
    """(class, detail): shell, patch, spawn, ("ma", name), plan, ask, image, ("mcp", server,
    tool), ("unknown", name)."""
    if not isinstance(tool, str):
        return ("unknown", repr(tool)[:60])
    cls = TOOL_CLASSES.get(tool)
    if cls == "ma":
        return ("ma", tool[len(MA_PREFIX):])
    if cls:
        return (cls,)
    m = MCP_RE.match(tool)
    if m:
        return ("mcp", m.group(1), m.group(2))
    return ("unknown", tool[:80])


class Ctx(object):
    """One hook call: the event, the policy and who is calling."""

    def __init__(self, mode, scope, ev, guard, agents):
        self.mode, self.scope, self.ev = mode, scope, ev
        self.guard, self.agents = guard, agents
        self.paths = Paths(guard)
        self.tool = ev.get("tool_name")
        self.raw_input = ev.get("tool_input")
        self.ti = self.raw_input if isinstance(self.raw_input, dict) else {}
        cwd = ev.get("cwd")
        self.cwd = os.path.normpath(cwd) if _abs_str(cwd) else None
        self.session = safe_id(ev.get("session_id"))
        aid, at = ev.get("agent_id"), ev.get("agent_type")
        self.is_main = at is None
        self.caller = MAIN_ROW if self.is_main else canon(at)
        self.agent_id = aid if isinstance(aid, str) and ID_RE.match(aid) else None
        if self.is_main:
            self.key = MAIN_KEY
        else:
            self.key = "a:" + self.agent_id if self.agent_id else "t:" + (self.caller or "?")
        self.row = self._row()

    def _row(self):
        if self.agents is None:
            return None
        if self.is_main:
            return self.agents["blackcat"]
        if not self.caller or self.caller in self.agents.get("builtin_types", []):
            return None
        return self.agents["agents"].get(self.caller)

    def label(self):
        return "BlackCat (the main thread)" if self.is_main else (self.caller or "this agent")

    def holder(self):
        return "%s/%s" % (self.session, self.key)


def shell_command(raw_input):
    """tool_input.command as one shell string (an argv list is quoted back), or None."""
    cmd = raw_input.get("command") if isinstance(raw_input, dict) else None
    if isinstance(cmd, str):
        return cmd
    if isinstance(cmd, list) and cmd and all(isinstance(x, str) for x in cmd):
        import shlex
        return " ".join(shlex.quote(x) for x in cmd)
    return None


# ---------------------------------------------------------------- tool-input walking
PATHISH_KEY_RE = re.compile(r"(?:path|paths|file|files|filename|filepath|file_path|dir|directory|"
                            r"root|cwd|uri|url|src|source|dest|destination|target|output|input|"
                            r"image|images|filePaths?)\Z", re.I)
WRITEISH_RE = re.compile(r"write|edit|create|delete|remove|move|rename|save|upload|put|append|"
                         r"patch|replace|mkdir|copy|update|insert|drop|install|set", re.I)


def input_strings(obj, key="", depth=0, out=None):
    """(key, string) pairs of a tool input, depth- and count-bounded."""
    out = [] if out is None else out
    if depth > 6 or len(out) > 500:
        return out
    if isinstance(obj, str):
        out.append((key, obj))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            input_strings(v, str(k), depth + 1, out)
    elif isinstance(obj, list):
        for v in obj:
            input_strings(v, key, depth + 1, out)
    return out


def _pathish(key, value):
    if len(value) > 4096 or "\n" in value:
        return False
    return bool(PATHISH_KEY_RE.match(key)) or value.startswith(("/", "~/", "./", "../", "file://"))


def input_paths(ctx, obj):
    """Absolute candidates for the path-like strings of a tool input."""
    out = []
    bases = [ctx.cwd] if ctx.cwd else []
    for key, value in input_strings(obj):
        if _pathish(key, value):
            for c in ctx.paths.expand(value, bases):
                out.append((value, c))
    return out


def input_path_violation(ctx, obj, writeish):
    """A credential path in any path-like argument; a protected-root path when the tool writes."""
    for value, c in input_paths(ctx, obj):
        if ctx.paths.credential(c):
            return CRED_REASON % ("`%s`" % str(ctx.tool)[:80], "`%s`" % value[:160])
        if writeish and ctx.paths.protected(c):
            return PROTECT_REASON % (str(ctx.tool)[:80], "`%s`" % value[:160])
    return None


# ---------------------------------------------------------------- decisions
DENY, ALLOW = "deny", "allow"


def universal_pre(ctx, cls, escalation=False):
    """The profile-neutral checks (both scopes): a reason, or None."""
    kind = cls[0]
    if kind == "shell":
        cmd = shell_command(ctx.raw_input)
        if cmd is None:
            return UNREADABLE_REASON % "command"
        found = shell_rule_hit(cmd, escalation)
        if found:
            return rule_reason(*found)
        found = patch_violation([cmd], ctx.cwd, ctx.paths) if PATCH_HEADER_RE.search(cmd) else None
        if found:
            return patch_reason(found)
        if escalation and is_wrapper_call(cmd, ctx.paths.wrapper):
            escalation = False                 # the executor's own path is not a touch of the root
        found = shell_path_violation(cmd, ctx.cwd or os.getcwd(), ctx.paths, escalation)
        if found:
            if escalation and found[0] == "protect":
                return PROTECT_ESC_REASON % ("`%s`" % found[1][:160])
            return path_reason(found, "`%s`" % cmd.strip()[:120])
        return None
    if kind == "patch":
        texts = patch_texts(ctx.raw_input)
        if texts is None:
            return PATCH_INPUT_REASON % "no patch text"
        found = patch_violation(texts, ctx.cwd, ctx.paths)
        return patch_reason(found) if found else None
    if kind in ("image", "mcp"):
        writeish = kind == "mcp" and (escalation or bool(WRITEISH_RE.search(cls[2])))
        return input_path_violation(ctx, ctx.raw_input, writeish)
    return None


def image_candidates(ctx):
    bases = [ctx.cwd] if ctx.cwd else []
    out = []
    for key, value in input_strings(ctx.raw_input):
        if len(value) < 4096 and "\n" not in value:
            for c in ctx.paths.expand(value, bases):
                out.append(c)
    return out


def image_pre(ctx):
    px = ctx.guard.get("image_max_px", DEFAULT_IMAGE_MAX_PX)
    cands = image_candidates(ctx)
    if not cands:
        return IMAGE_INPUT_REASON
    for c in cands:
        why = image_violation(c, px)
        if why:
            return why
    return None


def mcp_image_pre(ctx):
    px = ctx.guard.get("image_max_px", DEFAULT_IMAGE_MAX_PX)
    for value, c in input_paths(ctx, ctx.raw_input):
        if c.lower().endswith(IMAGE_EXT):
            why = image_violation(c, px)
            if why:
                return why
    return None


def decide_pre(ctx):
    """(DENY, reason) | (ALLOW, updated_input) | None for a PreToolUse event."""
    cls = classify(ctx.tool)
    why = universal_pre(ctx, cls)
    if why:
        return (DENY, why)
    if ctx.scope == "global":
        return None
    if ctx.row is None:
        return (DENY, GENERIC_REASON % (ctx.ev.get("agent_type") if isinstance(
            ctx.ev.get("agent_type"), str) else "(none)")[:60])
    if ctx.is_main:
        return main_pre(ctx, cls)
    return agent_pre(ctx, cls)


def main_pre(ctx, cls):
    """BlackCat, the main thread: delegate-only."""
    bc = ctx.row
    reads = bc.get("max_shell_reads_per_prompt", 3)
    kind = cls[0]
    if kind == "shell":
        bad = readonly_violation(shell_command(ctx.raw_input), ctx.cwd)
        if bad:
            return (DENY, READONLY_REASON % (ctx.label(), bad[0][:160], bad[1][:300]))
        with session_state(ctx) as st:
            if st["bc_shell"] >= reads:
                return (DENY, MAIN_READS_REASON % reads)
            st["bc_shell"] += 1
        return None
    if kind in MAIN_CLASSES or (kind == "mcp" and cls[1] in bc.get("mcp", [])):
        return dynamic_pre(ctx, cls)
    name = ctx.tool if isinstance(ctx.tool, str) else repr(ctx.tool)
    return (DENY, MAIN_REASON % (reads, name[:80]))


def agent_pre(ctx, cls):
    """A stack subagent: its row's tool classes, then the stateful checks."""
    row, kind = ctx.row, cls[0]
    if kind == "unknown":
        return (DENY, UNKNOWN_TOOL_REASON % cls[1])
    if kind == "shell":
        return shell_pre(ctx)
    if kind == "patch":
        if row.get("readonly"):
            return (DENY, READONLY_PATCH_REASON % ctx.label())
        if not row.get("apply_patch"):
            return (DENY, CLASS_REASON % (ctx.label(), "apply_patch"))
    if kind == "spawn" and not row.get("spawn_tool"):
        return (DENY, CLASS_REASON % (ctx.label(), "spawn_agent"))
    if kind == "image":
        why = image_pre(ctx)
        if why:
            return (DENY, why)
    if kind == "mcp":
        if cls[1] not in row.get("mcp", []):
            return (DENY, MCP_SERVER_REASON % (ctx.label(), cls[1], ", ".join(row.get("mcp", []))
                                               or "none"))
        why = mcp_image_pre(ctx)
        if why:
            return (DENY, why)
    return dynamic_pre(ctx, cls)


def shell_pre(ctx):
    row = ctx.row
    if not row.get("shell"):
        return (DENY, CLASS_REASON % (ctx.label(), "the shell"))
    cmd = shell_command(ctx.raw_input)
    if row.get("installer") and ctx.caller == "toolsmith":
        why = toolsmith_command(ctx, cmd)
        return (DENY, why) if why else dynamic_pre(ctx, ("shell",))
    if wrapper_invoked(cmd):
        return (DENY, TOOLSMITH_ONLY_REASON)
    if row.get("readonly"):
        bad = readonly_violation(cmd, ctx.cwd)
        if bad:
            return (DENY, READONLY_REASON % (ctx.label(), bad[0][:160], bad[1][:300]))
    return dynamic_pre(ctx, ("shell",))


def is_tainted(ctx, st):
    rec = st["agents"].get(ctx.key) or {}
    return bool((ctx.row or {}).get("web_ingesting")) or bool(rec.get("tainted"))


def taint(st, key):
    rec = st["agents"].setdefault(key, {})
    rec["tainted"] = True


def dynamic_pre(ctx, cls):
    """The stateful checks under the session lock; counters change only when the call is allowed."""
    kind = cls[0]
    with session_state(ctx) as st:
        trim_state(st)
        if not ctx.is_main:
            limit = ctx.row.get("max_tool_calls")
            n = st["calls"].get(ctx.key, 0)
            if isinstance(limit, int) and limit > 0 and n >= limit:
                return (DENY, CALLS_CAP_REASON % (ctx.label(), limit))
        if kind == "spawn":
            out = spawn_check(ctx, st)
        elif kind == "ma":
            out = ma_check(ctx, cls[1], st)
        elif kind == "mcp":
            out = mcp_check(ctx, cls, st)
        else:
            out = None
        if out is not None and out[0] == DENY:
            return out
        if not ctx.is_main:
            st["calls"][ctx.key] = st["calls"].get(ctx.key, 0) + 1
    if kind == "mcp" and cls[1] == ctx.guard.get("computer_use_server", DEFAULT_COMPUTER_USE_SERVER):
        why = screen_acquire(ctx)
        if why:
            return (DENY, why)
    return out


def spawn_check(ctx, st):
    target = canon(ctx.ti.get("agent_type"))
    agents = ctx.agents
    if not target or target in agents.get("builtin_types", []) or target not in agents["agents"]:
        return (DENY, SPAWN_MISSING_REASON)
    allowed = ctx.row.get("spawn", [])
    if target not in allowed:
        return (DENY, SPAWN_ROW_REASON % (ctx.label(), ", ".join(allowed) or "no agent", target))
    by_type = cap(ctx.guard, "spawns_per_prompt_by_type")
    limit = by_type.get(ctx.caller, cap(ctx.guard, "spawns_per_prompt"))
    n = st["spawns"].get(ctx.key, 0)
    if isinstance(limit, int) and limit > 0 and n >= limit:
        return (DENY, SPAWN_CAP_REASON % (ctx.label(), n, limit))
    st["spawns"][ctx.key] = n + 1
    st["pending"].append({"tool_use_id": str(ctx.ev.get("tool_use_id") or "")[:128],
                          "type": target, "parent": ctx.key, "parent_type": ctx.caller,
                          "tainted": is_tainted(ctx, st), "ts": time.time(), "bound": None})
    updated = dict(ctx.ti)
    stripped = [k for k in ("model", "reasoning_effort") if k in updated]
    for k in stripped:
        del updated[k]
    return (ALLOW, updated) if stripped else None


def target_ids(ti, many=False):
    keys = ("id", "agent_id", "target", "thread_id")
    out = [ti[k] for k in keys if isinstance(ti.get(k), str)]
    if many:
        for k in ("ids", "agent_ids", "targets"):
            if isinstance(ti.get(k), list):
                out.extend(x for x in ti[k] if isinstance(x, str))
    return [x for x in out if ID_RE.match(x)]


def ma_check(ctx, name, st):
    """send_input/resume_agent/close_agent go to your own child, your parent, or (resume) an agent
    your row may spawn, in this session's spawn tree; unknown ids are refused. Taint flows both
    ways along a message, and from a waited-on child to the waiter."""
    agents = st["agents"]
    if name == "wait_agent":
        for i in target_ids(ctx.ti, many=True):
            if (agents.get("a:" + i) or {}).get("tainted"):
                taint(st, ctx.key)
        return None
    ids = target_ids(ctx.ti)
    if not ids:
        return (DENY, ROUTE_ID_REASON % name)
    tkey = "a:" + ids[0]
    rec = agents.get(tkey)
    mine = agents.get(ctx.key) or {}
    ok = rec is not None and (rec.get("parent") == ctx.key or (
        name != "close_agent" and mine.get("parent") == tkey) or (
        name == "resume_agent" and rec.get("type") in ctx.row.get("spawn", [])))
    if not ok:
        return (DENY, ROUTE_REASON % (name, ids[0][:80]))
    if is_tainted(ctx, st):
        taint(st, tkey)
    if rec.get("tainted") and name != "close_agent":
        taint(st, ctx.key)
    return None


def mcp_check(ctx, cls, st):
    server, tool = cls[1], ctx.tool
    if tool in ctx.guard.get("memory_write_tools", DEFAULT_MEMORY_WRITE_TOOLS) and is_tainted(ctx, st):
        return (DENY, TAINT_REASON % ctx.label())
    per_session, per_agent = cap(ctx.guard, "mcp_calls_per_session"), cap(ctx.guard,
                                                                          "mcp_calls_per_agent")
    n_s, n_a = st["mcp_session"], st["mcp_agent"].get(ctx.key, 0)
    if per_session > 0 and n_s >= per_session:
        return (DENY, MCP_CAP_REASON % ("this session", per_session, "mcp_calls_per_session"))
    if per_agent > 0 and n_a >= per_agent:
        return (DENY, MCP_CAP_REASON % (ctx.label(), per_agent, "mcp_calls_per_agent"))
    st["mcp_session"], st["mcp_agent"][ctx.key] = n_s + 1, n_a + 1
    if server not in ctx.guard.get("non_web_mcp_servers", DEFAULT_NON_WEB_MCP):
        taint(st, ctx.key)
    return None


def screen_acquire(ctx):
    ttl = cap(ctx.guard, "screen_lock_ttl_s")
    with screen_state(ctx) as sc:
        cur, now = sc.get("holder"), time.time()
        if cur and cur != ctx.holder() and now - float(sc.get("ts") or 0) < ttl:
            return SCREEN_REASON % (sc.get("label") or "another agent")
        sc.update(holder=ctx.holder(), ts=now, label=ctx.label())
    return None


def screen_release(ctx, session_only=False):
    with screen_state(ctx) as sc:
        cur = sc.get("holder") or ""
        if cur == ctx.holder() or (session_only and cur.startswith(ctx.session + "/")):
            sc.update(holder=None, ts=0, label=None)


def decide_permission(ctx):
    """(DENY, message) or None for a PermissionRequest (an escalation out of the sandbox)."""
    cls = classify(ctx.tool)
    why = universal_pre(ctx, cls, escalation=True)
    if why:
        return (DENY, why)
    if cls[0] == "shell":
        cmd = shell_command(ctx.raw_input) or ""
        toolsmith = ctx.scope == "profile" and ctx.caller == "toolsmith" and bool(
            (ctx.row or {}).get("installer"))
        if ctx.scope == "profile" and wrapper_invoked(cmd) and not toolsmith:
            return (DENY, TOOLSMITH_ONLY_REASON)
    if ctx.scope == "global":
        return None
    if ctx.row is None:
        return (DENY, GENERIC_REASON % str(ctx.ev.get("agent_type"))[:60])
    if ctx.is_main or ctx.row.get("readonly"):
        return (DENY, ESCALATE_REASON % ctx.label())
    return None


# ---------------------------------------------------------------- observe-only events
SPAWN_ID_KEYS = ("agent_id", "id", "thread_id", "agentId", "threadId", "conversation_id")
SPAWN_ID_RE = re.compile(r"\b(?:agent_id|thread_id|id)\b[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9][A-Za-z0-9._-]{0,127})")


def parse_spawn_id(resp, depth=0):
    """The child's id in spawn_agent's tool_response, whose shape is unverified (probe P13): a dict
    key, a JSON string, or `id: ...` text; None when not found (the SubagentStart match is the
    fallback)."""
    if depth > 3:
        return None
    if isinstance(resp, str):
        try:
            return parse_spawn_id(json.loads(resp), depth + 1)
        except ValueError:
            m = SPAWN_ID_RE.search(resp[:4096])
            return m.group(1) if m and ID_RE.match(m.group(1)) else None
    if isinstance(resp, dict):
        for k in SPAWN_ID_KEYS:
            v = resp.get(k)
            if isinstance(v, str) and ID_RE.match(v):
                return v
        for k in ("result", "output", "content", "structuredContent", "agent"):
            found = parse_spawn_id(resp.get(k), depth + 1)
            if found:
                return found
    if isinstance(resp, list):
        for v in resp[:8]:
            found = parse_spawn_id(v, depth + 1)
            if found:
                return found
    return None


def observe(ctx):
    mode = ctx.mode
    if mode == "session_end":
        screen_release(ctx, session_only=True)
        return
    if mode == "session_start":
        return
    with session_state(ctx) as st:
        trim_state(st)
        if mode == "user_prompt_submit" and ctx.is_main:
            st["epoch"] += 1
            st["bc_shell"], st["spawns"] = 0, {}
        elif mode == "post_tool_use" and ctx.tool == "spawn_agent":
            post_spawn(ctx, st)
        elif mode == "subagent_start" and ctx.agent_id:
            subagent_start(ctx, st)
        elif mode == "subagent_stop" and ctx.agent_id:
            rec = st["agents"].setdefault(ctx.key, {"type": ctx.caller})
            rec["stopped"] = True
            if rec.get("tainted") and rec.get("parent"):
                taint(st, rec["parent"])
    if mode == "subagent_stop" and ctx.agent_id:
        screen_release(ctx)


def post_spawn(ctx, st):
    tuid = str(ctx.ev.get("tool_use_id") or "")[:128]
    child = parse_spawn_id(ctx.ev.get("tool_response"))
    pend = next((p for p in st["pending"] if tuid and p.get("tool_use_id") == tuid), None)
    if child is None:
        return                                 # SubagentStart binds the pending spawn instead
    if pend is not None:
        st["pending"].remove(pend)
        info = {"type": pend["type"], "parent": pend["parent"], "parent_type": pend["parent_type"],
                "tainted": bool(pend.get("tainted"))}
    else:
        info = {"type": canon(ctx.ti.get("agent_type")), "parent": ctx.key,
                "parent_type": ctx.caller, "tainted": bool((st["agents"].get(ctx.key) or {}).get(
                    "tainted"))}
    rec = st["agents"].setdefault("a:" + child, {})
    info["tainted"] = info["tainted"] or bool(rec.get("tainted"))
    rec.update(info)


def subagent_start(ctx, st):
    rec = st["agents"].get(ctx.key)
    if rec is None or rec.get("parent") is None:
        pend = next((p for p in st["pending"] if p.get("type") == ctx.caller and not p.get("bound")),
                    None)
        rec = rec or {}
        rec.update(type=ctx.caller, parent=pend["parent"] if pend else None,
                   parent_type=pend["parent_type"] if pend else None,
                   tainted=bool(rec.get("tainted") or (pend and pend.get("tainted"))))
        if pend:
            pend["bound"] = ctx.agent_id
        st["agents"][ctx.key] = rec
    if ctx.row and ctx.row.get("web_ingesting"):
        rec["tainted"] = True


# ---------------------------------------------------------------- output and entry point


def pre_output(decision):
    kind, value = decision
    spec = {"hookEventName": "PreToolUse", "permissionDecision": kind}
    if kind == DENY:
        spec["permissionDecisionReason"] = value
    else:
        spec["updatedInput"] = value
    return {"hookSpecificOutput": spec}


def permission_output(decision):
    return {"hookSpecificOutput": {"hookEventName": "PermissionRequest",
                                   "decision": {"behavior": "deny", "message": decision[1]}}}


def deny_output(mode, reason):
    return pre_output((DENY, reason)) if mode == "pre_tool_use" else permission_output((DENY, reason))


def parse_event(raw):
    if len(raw) > MAX_EVENT:
        raise PolicyError("the event is larger than %d bytes" % MAX_EVENT)
    ev = json.loads(raw.decode("utf-8"))
    if not isinstance(ev, dict):
        raise ValueError("the event is not a JSON object")
    return ev


def gate(mode, scope, raw, policy=None):
    """The output object for a gating mode, or None (no output: the call proceeds). `policy`:
    (guard, agents) already loaded (the self-test), else read from the policy dir."""
    try:
        ev = parse_event(raw)
    except (ValueError, RecursionError, PolicyError) as exc:
        return deny_output(mode, UNREADABLE_REASON % ("event (%s)" % str(exc)[:120]))
    try:
        guard, agents = policy if policy is not None else load_policy(scope)
    except PolicyError as exc:
        return deny_output(mode, POLICY_REASON % str(exc)[:200])
    ctx = Ctx(mode, scope, ev, guard, agents)
    if mode == "pre_tool_use":
        decision = decide_pre(ctx)
        return pre_output(decision) if decision else None
    decision = decide_permission(ctx)
    return permission_output(decision) if decision else None


def run(argv, stdin, stdout):
    """The hook: exit status 0 (also for a deny, which is in the JSON) or 2 (usage, or no way to
    write the deny)."""
    args = list(argv)
    scope = "profile"
    if args[-2:] == ["--scope", "global"]:
        scope, args = "global", args[:-2]
    if args == ["--self-test"]:
        return self_test(scope, stdout)
    if len(args) != 1 or args[0] not in MODES:
        sys.stderr.write("usage: codex_guard.py <%s> [--scope global] | --self-test\n" % "|".join(MODES))
        return 2
    mode = args[0]
    try:
        raw = stdin.read(MAX_EVENT + 1)
    except Exception:  # noqa: BLE001 - an unreadable stdin is an unreadable event
        raw = b""
    if mode in GATING:
        try:
            out = gate(mode, scope, raw)
        except Exception as exc:  # noqa: BLE001 - fail closed on any internal error
            out = deny_output(mode, INTERNAL_REASON % ("%s: %s" % (type(exc).__name__, exc))[:200])
        try:
            if out is not None:
                stdout.write(json.dumps(out, separators=(",", ":")) + "\n")
                stdout.flush()
        except Exception as exc:  # noqa: BLE001 - no way to say deny on stdout: exit 2 says it
            sys.stderr.write("codex_guard: %s\n" % exc)
            return 2
        return 0
    try:
        ev = parse_event(raw)
        guard, agents = load_policy(scope)
        if scope == "profile":
            observe(Ctx(mode, scope, ev, guard, agents))
    except Exception:  # noqa: BLE001 - observe-only events never block
        pass
    return 0


def self_test(scope, stdout):
    """A push is denied, a read allowed and a read of auth.json denied, through gate() with the
    installed policy and a throwaway state dir (exit 0 when all three hold, else 1)."""
    try:
        guard, agents = load_policy(scope)
    except PolicyError as exc:
        stdout.write("self-test: FAIL policy: %s\n" % exc)
        return 1
    home = guard["home"]
    auth = os.path.join(guard["codex_home"], "auth.json")
    cases = [("push", "git push origin main", True), ("read", "ls -la", False),
             ("auth.json", "cat '%s'" % auth, True)]
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix="codex-guard-selftest-")
    test_guard = dict(guard, state_dir=os.path.join(tmp, "state"))
    ok = True
    try:
        for name, cmd, want_deny in cases:
            ev = {"session_id": "self-test", "turn_id": "t", "cwd": home, "hook_event_name":
                  "PreToolUse", "model": "m", "permission_mode": "default", "tool_name": "Bash",
                  "tool_input": {"command": cmd}, "tool_use_id": "u-" + name,
                  "transcript_path": None}
            out = gate("pre_tool_use", scope, json.dumps(ev).encode("utf-8"), (test_guard, agents))
            denied = bool(out) and out["hookSpecificOutput"].get("permissionDecision") == DENY
            good = denied == want_deny
            ok = ok and good
            stdout.write("self-test: %s %s (%s)\n" % ("ok  " if good else "FAIL", name,
                                                       "denied" if denied else "allowed"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:], sys.stdin.buffer, sys.stdout))
