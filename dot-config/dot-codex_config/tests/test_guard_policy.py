"""The stack policy of codex_guard (profile scope; DESIGN.md §5): caller rows from agents.json, the
BlackCat main-thread gate on Codex's namespaced tool names, built-in and unknown types, read-only
roles, tool classes, the spawn rule, MCP allowlists, toolsmith, images, and the global scope
dropping all of it."""
from __future__ import annotations

import io
import json
import os
import struct
import sys
import zlib

import pytest

from _guard_helpers import (REPO, Guard, Stack, bash, decision, event, interpreter, perm_denied,
                            pre, reason, run_stub)
from conftest import load_lib


@pytest.fixture
def stack(tmp_path):
    return Stack(tmp_path)


@pytest.fixture
def guard(stack, monkeypatch):
    return Guard(stack, monkeypatch)


def main(tool, tool_input=None, **over):
    return pre(tool, tool_input or {}, agent_type=None, **over)


# ---------------------------------------------------------------- BlackCat, the main thread
@pytest.mark.parametrize("tool", ["multi_agent_v1wait_agent", "multi_agent_v1close_agent",
                                  "update_plan", "request_user_input"])
def test_blackcat_may_use_delegation_tools(guard, tool):
    out = guard.pre(main(tool, {"ids": []} if "wait" in tool else {"plan": []}))
    assert decision(out) != "deny" or "routing" in reason(out), reason(out)


def test_blackcat_wait_agent_allowed(guard):
    assert guard.pre(main("multi_agent_v1wait_agent", {"ids": ["x"]})) is None


@pytest.mark.parametrize("tool", ["wait", "send_input", "wait_agent", "multi_agent_v1wait",
                                  "multi_agent_v1list_agents", "multi_agent_v1interrupt_agent",
                                  "multi_agent_v1", "multi_agent_v2send_message"])
def test_blackcat_refuses_plain_and_unknown_multi_agent_names(guard, tool):
    out = guard.pre(main(tool, {"id": "x"}))
    assert decision(out) == "deny" and "only delegates" in reason(out)


@pytest.mark.parametrize("tool,ti", [("apply_patch", {"command": "*** Begin Patch\n*** Add File: a\n+x\n"
                                                                  "*** End Patch\n"}),
                                     ("view_image", {"path": "/tmp/x.png"}),
                                     ("mcp__exa__web_search_exa", {"query": "x"}),
                                     ("web_search", {"query": "x"})])
def test_blackcat_refuses_other_tools(guard, tool, ti):
    assert decision(guard.pre(main(tool, ti))) == "deny"


@pytest.mark.parametrize("command", ["echo x > out.txt", "rm -rf build", "touch a", "mkdir x",
                                     "python3 script.py", "sed -i s/a/b/ f", "npm install",
                                     "git commit -m x", "cp a b", "bash run.sh", "tee f < a"])
def test_blackcat_gate_refuses_shell_writes(guard, command):
    out = guard.pre(bash(command, agent_type=None))
    assert decision(out) == "deny" and "read-only" in reason(out)


def test_blackcat_reads_are_capped_per_prompt_and_reset(guard):
    for _ in range(3):
        assert guard.pre(bash("ls -la", agent_type=None)) is None
    out = guard.pre(bash("git status", agent_type=None))
    assert decision(out) == "deny" and "already used its 3" in reason(out)
    guard.observe("user_prompt_submit", event("user_prompt_submit", agent_type=None))
    assert guard.pre(bash("git log -1", agent_type=None)) is None
    # a subagent's prompt does not reset the main thread's counter
    for _ in range(2):
        guard.pre(bash("ls", agent_type=None))
    guard.observe("user_prompt_submit", event("user_prompt_submit"))
    assert decision(guard.pre(bash("ls", agent_type=None))) == "deny"


def test_main_thread_spawn_row(guard):
    assert guard.pre(main("spawn_agent", {"agent_type": "python-engineer", "message": "m"})) is None
    out = guard.pre(main("spawn_agent", {"agent_type": "scout", "message": "m"}))
    assert decision(out) == "deny" and "may spawn only" in reason(out)


# ---------------------------------------------------------------- generic, built-in, unknown callers
@pytest.mark.parametrize("agent_type", ["default", "worker", "explorer", "general-purpose",
                                        "no-such-agent", "blackcat", "", "Bad Type!"])
@pytest.mark.parametrize("tool,ti", [("Bash", {"command": "ls"}), ("update_plan", {}),
                                     ("multi_agent_v1wait_agent", {"ids": []})])
def test_generic_and_unknown_types_run_nothing(guard, agent_type, tool, ti):
    out = guard.pre(pre(tool, ti, agent_type=agent_type))
    assert decision(out) == "deny" and "not a stack agent" in reason(out)


def test_builtin_type_names_win_over_a_colliding_row(tmp_path, monkeypatch):
    """A row named like a Codex built-in (explorer) never makes the built-in a stack agent."""
    stack = Stack(tmp_path)
    stack.agents["agents"]["explorer"] = dict(stack.agents["agents"]["coder"])
    stack.agents["agents"]["python-engineer"]["spawn"].append("explorer")
    stack.write_policy()
    guard = Guard(stack, monkeypatch)
    out = guard.pre(bash("ls", agent_type="explorer"))
    assert decision(out) == "deny" and "not a stack agent" in reason(out)
    out = guard.pre(pre("spawn_agent", {"agent_type": "explorer"}, agent_type="python-engineer"))
    assert decision(out) == "deny" and "naming a stack agent" in reason(out)


def test_agent_type_is_canonicalised(guard):
    assert guard.pre(bash("ls", agent_type="Python_Engineer")) is None
    assert guard.pre(bash("ls", agent_type="CODER")) is None


def test_missing_agent_type_is_the_main_thread_and_fails_closed(guard):
    ev = bash("npm install left-pad")
    del ev["agent_type"]
    assert decision(guard.pre(ev)) == "deny"      # the BlackCat gate, not the coder's row


# ---------------------------------------------------------------- tool classes per row
def test_row_without_shell_refuses_shell(guard):
    out = guard.pre(bash("ls", agent_type="explore"))
    assert decision(out) == "deny" and "the shell" in reason(out)


def test_row_without_spawn_refuses_spawn(guard):
    out = guard.pre(pre("spawn_agent", {"agent_type": "coder"}, agent_type="coder"))
    assert decision(out) == "deny" and "spawn_agent" in reason(out)


def test_unknown_tool_refused_for_subagents(guard):
    for tool in ("web_search", "shell", "exec_command", "Write", "Agent", "multi_agent_v1spawn"):
        out = guard.pre(pre(tool, {}, agent_type="python-engineer"))
        assert decision(out) == "deny" and "not a tool" in reason(out), tool


def test_builder_writes_pass(guard):
    assert guard.pre(bash("npm install && echo ok > out.txt", agent_type="coder")) is None
    text = "*** Begin Patch\n*** Add File: src/x.py\n+x\n*** End Patch\n"
    assert guard.pre(pre("apply_patch", {"command": text}, agent_type="coder")) is None


# ---------------------------------------------------------------- read-only roles
@pytest.mark.parametrize("agent", ["code-reviewer", "verifier"])
def test_readonly_roles_never_patch(guard, agent):
    text = "*** Begin Patch\n*** Update File: src/x.py\n@@\n-a\n+b\n*** End Patch\n"
    out = guard.pre(pre("apply_patch", {"command": text}, agent_type=agent))
    assert decision(out) == "deny" and "read-only" in reason(out)


@pytest.mark.parametrize("command", [
    "rg -n TODO src", "git diff HEAD~1", "git log --oneline -5", "git status --short",
    "git show HEAD:README.md", "uv run --no-project --with pytest pytest -q tests",
    "python3 -m pytest -q", "ruff check src", "cat a | sort | uniq -c", "find . -name '*.py'",
    "sed -n 1,20p x.py", "jq . data.json", "ls -la 2>/dev/null", "echo hi > $TMPDIR/out.txt",
    "mkdir -p .claude-work/job && pytest -q --junitxml .claude-work/job/r.xml",
    "gh pr view 3", "gh api repos/o/r/pulls", "git branch -a", "find . -exec grep -l x {} +",
    "for f in *.py; do wc -l \"$f\"; done", "python3 -c 'print(1+1)'", "bash -n install.sh",
    "cargo test", "go vet ./...", "npm test", "black --check .", "mypy src",
    "git config --get user.name", "xargs -n1 echo < list.txt", "command -v git"])
def test_readonly_allowlist_passes_reads(guard, command):
    assert guard.pre(bash(command, agent_type="code-reviewer")) is None, command


@pytest.mark.parametrize("command", [
    "echo x > src/a.py", "rm -rf build", "sed -i s/a/b/ x.py", "git commit -m x", "git checkout -b x",
    "git stash", "git branch new-feature", "npm install", "pip install x", "python3 script.py",
    "python3 -c 'import os; os.remove(\"a\")'", "find . -delete", "find . -exec rm {} +",
    "ruff check --fix .", "black .", "cargo build", "make", "curl -X POST https://x",
    "bash script.sh", "bash -c 'touch x'", "cp a src/b", "mv a b", "tee out.txt < x",
    "PATH=/tmp/x:$PATH ls", "awk '{print > \"out\"}' f", "perl -pi -e 's/a/b/' f",
    "git -c core.pager=sh log", "uv add requests", "echo $(touch x)", "if rm x; then ls; fi",
    "sed -n 'w out' f", "xargs rm < list", "gh pr merge 3", "unknown-tool --flag"])
def test_readonly_allowlist_refuses_writes(guard, command):
    out = guard.pre(bash(command, agent_type="code-reviewer"))
    assert decision(out) == "deny" and ("read-only" in reason(out) or "never" in reason(out)), command


@pytest.mark.parametrize("command", [
    "git -c alias.l=log l", "git -c alias.x='!rm -rf src' x", "git -c Alias.L=log L",
    "git --exec-path=/tmp/x log", "git --config-env=core.pager=P log",
    "git -C sub -c alias.l=log l", "git -C $D diff --output=out.patch",
    "git -C sub commit -F msg", "git commit -F msg", "git add --pathspec-from-file=list",
    "git commit -t tmpl", "git config --file /tmp/c alias.l log"])
@pytest.mark.parametrize("agent", ["code-reviewer", None])
def test_readonly_allowlist_refuses_git_flag_forms(guard, command, agent):
    out = guard.pre(bash(command, agent_type=agent))
    assert decision(out) == "deny" and ("read-only" in reason(out) or "never" in reason(out)), command


@pytest.mark.parametrize("command", ["git --exec-path", "git --exec-path /tmp/x log",
                                     "git -C sub log -1", "git -Csub status",
                                     "git -C sub diff --output=$TMPDIR/x.patch",
                                     "git -C sub log --pathspec-from-file=list"])
def test_readonly_allowlist_passes_git_flag_reads(guard, command):
    assert guard.pre(bash(command, agent_type="code-reviewer")) is None, command


def test_readonly_git_output_resolves_against_dash_c(guard, stack):
    """git -C DIR writes a relative --output under DIR: from a temp cwd, `out.patch` is scratch, but
    `-C <project>` puts it in the project."""
    tmp = stack.root / "tmp"
    ev = lambda cmd: bash(cmd, agent_type="code-reviewer", cwd=str(tmp))
    assert guard.pre(ev("git diff --output=out.patch")) is None
    out = guard.pre(ev("git -C %s diff --output=out.patch" % stack.project))
    assert decision(out) == "deny" and "scratch" in reason(out)
    out = guard.pre(ev("git -C%s/src diff --output out.patch" % stack.project))
    assert decision(out) == "deny"
    assert guard.pre(ev("git -C %s diff --output=%s/o.patch" % (stack.project, tmp))) is None


def test_readonly_escalation_refused(guard):
    ev = event("permission_request", agent_type="code-reviewer", tool_input={"command": "ls"})
    assert perm_denied(guard.perm(ev))
    ev = event("permission_request", agent_type=None, tool_input={"command": "ls"})
    assert perm_denied(guard.perm(ev))
    ev = event("permission_request", agent_type="default", tool_input={"command": "ls"})
    assert perm_denied(guard.perm(ev))


# ---------------------------------------------------------------- spawn rule
def test_spawn_requires_a_stack_agent_type(guard):
    for ti in ({"message": "x"}, {"agent_type": "default"}, {"agent_type": "worker"},
               {"agent_type": "nobody"}, {"agent_type": 3}):
        out = guard.pre(pre("spawn_agent", ti, agent_type="python-engineer"))
        assert decision(out) == "deny" and "spawn" in reason(out), ti


def test_spawn_target_must_be_in_the_callers_row(guard):
    ok = guard.pre(pre("spawn_agent", {"agent_type": "coder", "message": "m"},
                       agent_type="python-engineer"))
    assert ok is None
    out = guard.pre(pre("spawn_agent", {"agent_type": "researcher"}, agent_type="python-engineer"))
    assert decision(out) == "deny" and "may spawn only" in reason(out)
    out = guard.pre(pre("spawn_agent", {"agent_type": "python-engineer"},
                        agent_type="python-engineer"))
    assert decision(out) == "deny"                # no self-spawn beyond the row


def test_spawn_strips_model_and_effort_with_allow(guard):
    ti = {"agent_type": "coder", "message": "m", "model": "gpt-6-astra", "reasoning_effort": "max",
          "fork_context": False}
    out = guard.pre(pre("spawn_agent", ti, agent_type="python-engineer"))
    spec = out["hookSpecificOutput"]
    assert spec == {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                    "updatedInput": {"agent_type": "coder", "message": "m", "fork_context": False}}


def test_spawn_target_canonicalised(guard):
    assert guard.pre(pre("spawn_agent", {"agent_type": "Code_Reviewer"},
                         agent_type="python-engineer")) is None


# ---------------------------------------------------------------- MCP allowlist
def test_mcp_server_allowlist(guard):
    assert guard.pre(pre("mcp__libdocs__get_library_docs", {"id": "x"},
                         agent_type="python-engineer")) is None
    out = guard.pre(pre("mcp__exa__web_search_exa", {"query": "x"}, agent_type="python-engineer"))
    assert decision(out) == "deny" and "`exa`" in reason(out)
    out = guard.pre(pre("mcp__libdocs__x", {}, agent_type="verifier"))
    assert decision(out) == "deny"


def test_mcp_names_with_odd_servers(guard):
    out = guard.pre(pre("mcp__lib__docs__x", {}, agent_type="python-engineer"))
    assert decision(out) == "deny"                 # server "lib", not in the row


# ---------------------------------------------------------------- toolsmith
def test_only_toolsmith_runs_stack_install(guard, stack):
    wrapper = stack.guard["toolsmith_wrapper"]
    out = guard.pre(bash("%s install brew jq --why 'json tool'" % wrapper, agent_type="coder"))
    assert decision(out) == "deny" and "only the toolsmith" in reason(out)
    out = guard.pre(bash("env X=1 stack-install status", agent_type="python-engineer"))
    assert decision(out) == "deny"


@pytest.mark.parametrize("command", ["env -C /tmp stack-install status", "env -P /usr/bin stack-install status",
                                     "/usr/bin/env -u X stack-install status",
                                     "/usr/bin/timeout -s KILL 30 stack-install status",
                                     "/usr/bin/nice -n 5 stack-install status", "sudo -H stack-install status",
                                     "sudo -P stack-install status"])
def test_upper_case_value_options_and_wrapper_paths_still_reach_stack_install(guard, command):
    """T11b Open 3 (parity with agent_guard): value options compare case-sensitively, wrappers by basename."""
    out = guard.pre(bash(command, agent_type="python-engineer"))
    assert decision(out) == "deny" and "only the toolsmith" in reason(out), command


def test_stack_install_as_an_argument_after_a_wrapper_is_not_a_call(guard):
    assert guard.pre(bash("env -C /tmp ls stack-install", agent_type="python-engineer")) is None

def test_toolsmith_argv_checked_and_ticket_written(guard, stack):
    wrapper = stack.guard["toolsmith_wrapper"]
    out = guard.pre(bash("%s install brew jq --why 'json tool' --for coder" % wrapper,
                         agent_type="toolsmith"))
    assert out is None
    tickets = list((stack.xdg / "claude-agent-stack" / "toolsmith" / "tickets").glob("*.json"))
    assert len(tickets) == 1 and json.loads(tickets[0].read_text())["argv"][:2] == ["install", "brew"]
    for cmd in ("%s install pip x --why 'a b c'" % wrapper, "ls", "%s status; ls" % wrapper,
                "%s install brew jq --why 'json tool' --for nobody" % wrapper,
                "%s run rq-0123456789ab" % wrapper):
        out = guard.pre(bash(cmd, agent_type="toolsmith"))
        assert decision(out) == "deny" and "installer rule" in reason(out), cmd


def test_stack_install_escalation_only_for_toolsmith(guard, stack):
    cmd = "%s install brew jq --why 'json tool'" % stack.guard["toolsmith_wrapper"]
    assert perm_denied(guard.perm(event("permission_request", agent_type="coder",
                                        tool_input={"command": cmd})))
    assert guard.perm(event("permission_request", agent_type="toolsmith",
                            tool_input={"command": cmd})) is None


# ---------------------------------------------------------------- images
def png(path, w, h):
    raw = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">IIBBBBB", w, h, 8, 2,
                                                                               0, 0, 0)
    path.write_bytes(raw + struct.pack(">I", zlib.crc32(raw[12:]) & 0xFFFFFFFF))
    return path


def heic(path, w, h):
    box = struct.pack(">I", 20) + b"ispe" + b"\x00" * 4 + struct.pack(">II", w, h)
    path.write_bytes(struct.pack(">I", 24) + b"ftypheic" + b"\x00" * 12 + box)
    return path


def test_view_image_size_limit(guard, stack):
    small = png(stack.project / "small.png", 1920, 1080)
    big = png(stack.project / "big.png", 1921, 100)
    assert guard.pre(pre("view_image", {"path": str(small)})) is None
    out = guard.pre(pre("view_image", {"path": str(big)}))
    assert decision(out) == "deny" and "1921x100" in reason(out)
    assert decision(guard.pre(pre("view_image", {"path": "big.png"}))) == "deny"   # relative to cwd


def test_view_image_heic_and_unknown_formats(guard, stack):
    assert decision(guard.pre(pre("view_image", {"path": str(heic(stack.project / "a.heic",
                                                                     4032, 3024))}))) == "deny"
    assert guard.pre(pre("view_image", {"path": str(heic(stack.project / "b.heic", 800, 600))})) is None
    (stack.project / "c.tiff").write_bytes(b"II*\x00" + b"\x00" * 64)
    assert decision(guard.pre(pre("view_image", {"path": str(stack.project / "c.tiff")}))) == "deny"
    assert decision(guard.pre(pre("view_image", {}))) == "deny"


def test_mcp_image_arguments_checked(guard, stack):
    big = png(stack.project / "shot.png", 3000, 2000)
    out = guard.pre(pre("mcp__image-studio__edit_image", {"input_image": str(big), "prompt": "x"},
                        agent_type="designer"))
    assert decision(out) == "deny" and "3000x2000" in reason(out)


# ---------------------------------------------------------------- global scope: no stack policy
def test_global_scope_has_no_caller_policy(guard):
    for ev in (bash("npm install", agent_type="default"), main("apply_patch", {"command": ""}),
               pre("mcp__exa__x", {}, agent_type="verifier"), bash("rm -rf build", agent_type=None)):
        assert guard.pre(ev, scope="global") is None


def managed_dir(tmp_path, stack):
    """The managed tier's flat directory exactly as requirements.py writes it (codex-hook, the guard,
    the SUPPORT_FILES and guard.json; no agents.json), plus a stack-python link for speed."""
    req = load_lib("requirements")
    out = tmp_path / "build"
    req.run(["--codex-home", str(stack.codex_home), "--home", str(stack.home), "--src", str(REPO),
             "--out", str(out), "--managed-dir", str(tmp_path / "managed-target"),
             "--etc-dir", str(tmp_path / "etc"), "--state-dir", str(stack.state)],
            out_stream=io.StringIO())
    mh = out / "managed-hooks"
    os.symlink(interpreter(), mh / "stack-python")
    return mh


@pytest.mark.skipif(sys.version_info < (3, 11), reason="requirements.py (installer side) needs 3.11")
def test_global_scope_runs_from_the_managed_dir_without_agents_json(tmp_path):
    stack = Stack(tmp_path)
    mh = managed_dir(tmp_path, stack)
    assert sorted(p.name for p in mh.iterdir()) == ["codex-hook", "codex_guard.py", "guard.json",
                                                    "stack-python", "stack_io.py",
                                                    "toolsmith_policy.py"]
    stub = mh / "codex-hook"
    ch = stack.codex_home
    denied = [bash("git push origin main", agent_type="default"),
              bash("bash -c 'gh pr merge 1'", agent_type=None),
              bash("cat %s/auth.json" % ch), bash("rm -rf %s/stack" % ch, agent_type=None),
              bash("git commit -F ~/.codex/auth.json", agent_type="code-reviewer"),
              pre("apply_patch", {"command": "*** Begin Patch\n*** Add File: %s/x\n+x\n*** End Patch\n"
                                  % ch}, agent_type=None),
              pre("mcp__fs__read_file", {"path": "%s/stack.env" % ch}, agent_type="no-such-agent")]
    for ev in denied:
        rc, out, err = run_stub(stack, "pre_tool_use", ev, scope="global", stub=stub)
        assert rc == 0 and decision(out) == "deny", (ev["tool_input"], err)
    rc, out, err = run_stub(stack, "permission_request",
                            event("permission_request", tool_input={"command": "git -C /x commit"}),
                            scope="global", stub=stub)
    assert rc == 0 and perm_denied(out), err
    # the profile's policy is off: built-in types, BlackCat's gate, read-only roles, MCP rows
    allowed = [bash("npm install", agent_type="default"), bash("rm -rf build", agent_type="verifier"),
               main("apply_patch", {"command": "*** Begin Patch\n*** Add File: src/x.py\n+x\n"
                                               "*** End Patch\n"}),
               main("web_search", {"query": "x"}), pre("mcp__exa__web_search_exa", {"q": "x"},
                                                       agent_type="python-engineer")]
    for ev in allowed:
        rc, out, err = run_stub(stack, "pre_tool_use", ev, scope="global", stub=stub)
        assert rc == 0 and out is None, (ev["tool_name"], out, err)
    for mode in ("post_tool_use", "subagent_start", "user_prompt_submit", "session_end"):
        assert run_stub(stack, mode, event(mode), scope="global", stub=stub)[:2] == (0, None)
    assert not (stack.state / "sessions").exists()     # the global scope keeps no state


def test_global_scope_never_reads_agents_json(tmp_path, monkeypatch):
    stack = Stack(tmp_path, layout="flat")
    (stack.policy_dir / "agents.json").write_text("{broken")
    guard = Guard(stack, monkeypatch)
    assert decision(guard.pre(bash("git push"), scope="global")) == "deny"
    assert guard.pre(bash("npm install", agent_type="default"), scope="global") is None
    assert "policy cannot be read" in reason(guard.pre(bash("ls")))           # profile: closed


def test_global_scope_prefers_the_guard_json_beside_it(tmp_path, monkeypatch):
    """A managed (flat) guard reads its own guard.json, not a policy/ dir next to its parent."""
    stack = Stack(tmp_path, layout="flat")
    decoy = tmp_path / "policy"
    decoy.mkdir()
    (decoy / "guard.json").write_text(json.dumps(dict(stack.guard, codex_home=str(tmp_path / "d"),
                                                      credentials={"paths": [], "globs": []})))
    guard = Guard(stack, monkeypatch)
    out = guard.pre(bash("cat %s/.ssh/id_ed25519" % stack.home), scope="global")
    assert decision(out) == "deny" and "credential" in reason(out)


@pytest.mark.parametrize("damage", ["missing", "unreadable", "malformed", "not-an-object"])
def test_profile_scope_without_a_readable_agents_json_fails_closed(tmp_path, monkeypatch, damage):
    stack = Stack(tmp_path)
    f = stack.policy_dir / "agents.json"
    if damage == "missing":
        f.unlink()
    elif damage == "unreadable":
        f.chmod(0)
    else:
        f.write_text("{x" if damage == "malformed" else "[1]")
    guard = Guard(stack, monkeypatch)
    try:
        for ev in (bash("ls"), bash("ls", agent_type=None), pre("update_plan", {}, agent_type=None)):
            out = guard.pre(ev)
            assert decision(out) == "deny" and "policy cannot be read" in reason(out), damage
        assert perm_denied(guard.perm(event("permission_request")))
        for mode in ("post_tool_use", "subagent_stop", "user_prompt_submit"):
            assert guard.run(mode, event(mode)) == (0, None)
        assert guard.pre(bash("ls"), scope="global") is None                  # global: no agents.json
    finally:
        f.exists() and f.chmod(0o600)


def test_global_scope_without_any_policy_file(tmp_path, monkeypatch):
    stack = Stack(tmp_path)
    (stack.policy_dir / "guard.json").unlink()
    guard = Guard(stack, monkeypatch)
    assert decision(guard.pre(bash("git push"), scope="global")) == "deny"
    assert decision(guard.pre(bash("cat ~/.codex/auth.json"), scope="global")) == "deny"
    assert guard.pre(bash("ls"), scope="global") is None
    assert decision(guard.pre(bash("ls"))) == "deny"            # profile scope fails closed
