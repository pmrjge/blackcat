"""Seeded-mutation proof for dot-config/dot-claude/bin/stack_sdk.py (SDK-2: the design's mutants M1-M33 and the
SDK-2r review findings S*, C*, R*, V*). The human-readable index with the kill evidence is
H/.claude-work/sdk/sdk2-mutants.md; this file is the replayable source.

Each mutant is one text substitution in a scratch copy of stack_sdk.py under $TMPDIR (stack_sdk.py itself is never written);
its NAMED test in tests/test_sdk_session.py runs against that copy (SDK_HELPER, as the test file reads it) and must
FAIL (its id in pytest's FAILED/ERROR lines, or the run times out). Each anchor must match exactly once. The
unmutated copy must pass every named test first. Exit 0 iff the clean copy passes and every mutant is killed.

  uv run --no-project --python 3.13 --with pytest --with claude-agent-sdk==0.2.163 python tests/sdk_mutations.py
      [--list] [-k ID_OR_TEXT[,..]] [-j N (default 4)] [--out PATH (default "-": stdout only; the tracked record
      is refreshed with --out tests/sdk_mutations.out)]
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HELPER = REPO / "dot-config" / "dot-claude" / "bin" / "stack_sdk.py"
TESTS = "tests/test_sdk_session.py::"

MUTANTS = [  # (id, mutant, named test in tests/test_sdk_session.py, anchor, replacement)
    ('M1', 'agent name counted anywhere in server_info', 'test_load_fails_closed', 'missing = sorted(set(self.agents) - have)', 'missing = [a for a in sorted(self.agents) if a not in json.dumps(info)]'),
    ('M1', 'a missing marker passes', 'test_load_fails_closed', 'mark = read_json(path)', 'mark = read_json(path) or {"ts": time.time(), "source": sources[0], "policy": True}'),
    ('M2', 'host none drops permission-prompts', 'test_host_none', '**({"permission-prompts": "none"} if self.host == "none" else {}))', '**{})'),
    ('M2', 'host none sets can_use_tool', 'test_host_none', 'can_use_tool=None if self.host == "none" else self._can_use_tool', 'can_use_tool=self._can_use_tool'),
    ('M2', 'host none omits ExitPlanMode', 'test_host_none', 'deny += ["ExitPlanMode"] + (', 'deny += [] + ('),
    ('M2', 'caller permission-prompts allowed in extra_args', 'test_host_none', 'EXTRA_OK = ("debug", "debug-file", "verbose", "model", "fallback-model", "effort", "betas", "name")', 'EXTRA_OK = ("debug", "permission-prompts", "debug-file", "verbose", "model", "fallback-model", "effort", "betas", "name")'),
    ('M3', 'updated_permissions kept unfiltered', 'test_no_persist', '            out.append(PermissionUpdate(type="addRules", destination="session", behavior=g("behavior"), rules=rules))\n    return out', '            out.append(PermissionUpdate(type="addRules", destination="session", behavior=g("behavior"), rules=rules))\n    return list(updates or [])'),
    ('M3', 'non-session destinations kept', 'test_no_persist', 'g("destination") != "session" or ', ''),
    ('M3', 'rules for other tools kept', 'test_no_persist', 'if n == tool]', 'if n]'),
    ('M4', 'AskUserQuestion allowed without answers', 'test_ask_requires_callable', 'tool == "AskUserQuestion" and not (isinstance', 'False and not (isinstance'),
    ('M5', 'no budget check', 'test_budget_required', '        if self.host == "none" and not (isinstance(self.budget_usd, (int, float)) and self.budget_usd > 0):\n            raise UsageError', '        if False:\n            raise UsageError'),
    ('M6', 'bypassPermissions accepted', 'test_cli_modes', 'if bad or permission_mode == "bypassPermissions":', 'if bad:'),
    ('M6', 'dangerously-skip-permissions allowed in extra_args', 'test_cli_modes', 'EXTRA_OK = ("debug", "debug-file", "verbose", "model", "fallback-model", "effort", "betas", "name")', 'EXTRA_OK = ("debug", "dangerously-skip-permissions", "debug-file", "verbose", "model", "fallback-model", "effort", "betas", "name")'),
    ('M7', 'SDK adapter loses parent_tool_use_id', 'test_parity', '"parent_tool_use_id": g("parent_tool_use_id"), "message"', '"parent_tool_use_id": None, "message"'),
    ('M8', 'row keeps text', 'test_row_no_text', 'row[k] = v if ok else None', 'row[k] = v'),
    ('M8', 'row not 0600', 'test_row_no_text', 'os.fchmod(fd, 0o600)', 'os.fchmod(fd, 0o644)'),
    ('M9', 'no disconnect on exception or cancellation', 'test_graceful_close', '    async def __aexit__(self, *exc):\n        await self.disconnect()', '    async def __aexit__(self, *exc):\n        pass'),
    ('M9', 'CLI run without disconnect (SIGTERM/SIGHUP)', 'test_graceful_close', '        async with s:\n            return await s.ask(prompt)', '        await s.connect()\n        return await s.ask(prompt)'),
    ('M10', 'rate limits counted without status', 'test_ratelimit', 'by = self.rate.setdefault(str(i.get("status")), {})', 'by = self.rate.setdefault("any", {})'),
    ('M11', 'a hook registered by default', 'test_no_sdk_hooks', 'include_hook_events=True, forward_subagent_text', 'hooks={"PreToolUse": []}, include_hook_events=True, forward_subagent_text'),
    ('M12', 'report from the first result', 'test_last_result', 'res = self.results[-1] if self.results else {}', 'res = self.results[0] if self.results else {}'),
    ('M13', 'run ends at the first result with an agent in flight', 'test_bg_wait_keeps_reading', 'if r.results and r.state == "idle":', 'if r.results:'),
    ('M14', 'bg ceiling not enforced', 'test_bg_wait_ceiling', 'limits.append((self.bg_wait_s - (now - t_res - paused), "bg_wait_ceiling"))', 'limits.append((1e9, "bg_wait_ceiling"))'),
    ('M14', 'host none default deadline not 3600', 'test_bg_wait_ceiling', 'self.deadline_s = deadline_s if ok or host != "none" else DEADLINE_NONE_S', 'self.deadline_s = deadline_s'),
    ('M14', 'deadline not enforced', 'test_bg_wait_ceiling', 'limits = [(deadline - now, "deadline")] if deadline is not None else []', 'limits = []'),
    ('M15', 'local_bash holds the run', 'test_inflight_agent_types_only', 'if not n["ended"] and n["task_type"] in AGENT_TASKS]', 'if not n["ended"]]'),
    ('M16', 'schema accepted with an agent', 'test_no_schema_with_agent', 'if kw.get("output_format") and agent:', 'if False:'),
    ('M17', 'gate plan only on blocked', 'test_plan_gate_unattended', 'report["status"] in (\n            "blocked", None)', 'report["status"] in (\n            "blocked",)'),
    ('M18', 'silent fallback to the bundled CLI', 'test_cli_path_policy', '    if not p or not os.path.isfile(p) or not os.access(p, os.X_OK):\n        raise CliNotFound', '    if not p or not os.path.isfile(p) or not os.access(p, os.X_OK):\n        return None\n        raise CliNotFound'),
    ('M19', 'aborted_* reported by the text', 'test_interrupt_outcome', 'elif why.startswith("aborted") and not bounded or', 'elif False and not bounded or'),
    ('M20', 'unsanitised text reaches the tty', 'test_tty_sanitizes', 's = CTRL.sub("?", str(s))', 's = str(s)'),
    ('M20', 'uncapped text reaches the tty', 'test_tty_sanitizes', 'return s if len(s) <= cap else', 'return s if True else'),
    ('M21', 'setting_sources without user accepted', 'test_no_policy_overlay', 'if "user" not in kw.get("sources", ("user",)) or', 'if False or'),
    ('M21', 'policy overlay accepted', 'test_no_policy_overlay', 'return not isinstance(obj, dict) or any(k in obj for k in POLICY_KEYS)', 'return False'),
    ('M22', 'builders from a fixed list (a new acceptEdits agent missed)', 'test_host_none_denies_builders', 'for n, m in sorted(self.agents.items())', 'for n, m in sorted({"coder": "acceptEdits"}.items())'),
    ('M22', 'Workflow not denied under plan', 'test_host_none_denies_builders', '"default")), "Workflow"] if plan', '"default"))] if plan'),
    ('M23', 'prompt sent before the load check finished', 'test_load_check_preprompt', '            await self._load_check()\n            self.loaded = True', '            asyncio.ensure_future(self._load_check())\n            self.loaded = True'),
    ('M24', 'a stale marker satisfies (b)', 'test_load_fails_closed', 'or isinstance(ts, bool) or ts < self.t0:', 'or isinstance(ts, bool):'),
    ('M25', 'an error-outcome SessionStart satisfies (b)', 'test_load_fails_closed', 'if d.get("outcome") != "success":', 'if False:'),
    ('M26', 'idle before the result ignored', 'test_run_end_idle_first', 'self.state = d.get("state")', 'self.state = d.get("state") if self.results else self.state'),
    ('M27', 'a late line answers the next prompt', 'test_tty_no_stale_answer', 'if s >= seq:', 'if True:'),
    ('M28', 'plan approved without the nonce', 'test_tty_plan_nonce', 'return PermissionResultAllow() if ln == nonce else deny', 'return PermissionResultAllow() if ln in (nonce, "y") else deny'),
    ('M29', 'text report gives done', 'test_text_report_outcome', 'report["status"], "unknown")', 'report["status"], "done")'),
    ('M29', 'text report gives needs_user False', 'test_text_report_outcome', 'needs_user = True if ask else (None if host == "none" and report["format"] == "text" else False)', 'needs_user = True if ask else False'),
    ('M30', 'CLI ceiling env left unset', 'test_bg_wait_ceiling', '        self.env.setdefault(CEILING_ENV, "3000")', '        pass'),
    ('M30', 'CLI ceiling 0 accepted', 'test_bg_wait_ceiling', 'int(ceiling) > 0)', 'int(ceiling) >= 0)'),
    ('M31', 'explicit non-plan mode not logged gate_waived', 'test_host_none_denies_builders', 'return self.host == "none" and self.permission_mode not in (None, "plan")', 'return False'),
    ('M32', 't0 taken after connect() returns', 'test_load_fails_closed', '            self.t0 = time.time()                        # immediately before connect(): the marker is newer\n            await self._client.connect()', '            await self._client.connect()\n            self.t0 = time.time()'),
    ('M32', 'marker read before every SessionStart response', 'test_load_fails_closed', 'while not (len(done) >= need and started <= done):', 'while False:'),
    ('M33', 'include_hook_events omitted', 'test_load_fails_closed', 'include_hook_events=True, forward_subagent_text', 'forward_subagent_text'),
    ('S1', 'repository .claude/agents ignored', 'test_project_agents_do_not_pass_the_plan_gate', 'odd += project_agent_files(self.kw.get("cwd"), self.config, self.kw.get("add_dirs") or ())', 'odd += []'),
    ('S1', 'unknown server_info agents ignored', 'test_project_agents_do_not_pass_the_plan_gate', 'odd = sorted(h for h in have - set(self.agents) if ":" not in h)', 'odd = []'),
    ('S2', 'extra_args back to an exact-spelling denylist', 'test_refusals_hold_for_every_spelling', '(kw.get("extra_args") or {}).items() if k not in EXTRA_OK', '(kw.get("extra_args") or {}).items() if str(k).lstrip("-") in ("permission-mode", "settings", "sandbox")'),
    ('S2', 'settings allowed in extra_args', 'test_refusals_hold_for_every_spelling', 'EXTRA_OK = ("debug", "debug-file", "verbose", "model", "fallback-model", "effort", "betas", "name")', 'EXTRA_OK = ("debug", "settings", "debug-file", "verbose", "model", "fallback-model", "effort", "betas", "name")'),
    ('S2', 'sandbox accepted (keyword and overlay)', 'test_refusals_hold_for_every_spelling', 'POLICY_KEYS = ("hooks", "disableAllHooks", "permissions", "defaultMode", "sandbox")', 'POLICY_KEYS = ("hooks", "disableAllHooks", "permissions", "defaultMode")'),
    ('S2', 'server bypassPermissions accepted', 'test_refusals_hold_for_every_spelling', 'if actual == "bypassPermissions":', 'if False:'),
    ('C2', 'max_budget_usd/setting_sources aliases accepted', 'test_refusals_hold_for_every_spelling', '              "max_budget_usd", "setting_sources")', '              )'),
    ('S3', 'mode drift off plan accepted', 'test_mode_check_fails_closed', '                if actual != "plan":', '                if actual not in ("plan", None, "acceptEdits", "default"):'),
    ('S4', 'model answers passed to the host', 'test_ask_model_supplied_answers_do_not_count', 'inp = {k: v for k, v in inp.items() if k not in ("answers", "annotations")}', 'inp = {k: v for k, v in inp.items() if k != "annotations"}'),
    ('S5', 'labels keep newlines', 'test_tty_option_labels_cannot_forge_lines', 'return clean_text(re.sub(r"[\\n\\t]", " ", str(s)), cap)', 'return clean_text(s, cap)'),
    ('S6', 'no gap between prompts', 'test_tty_no_stale_answer_when_queued', '        await anyio.sleep(GAP_S)  ', '        pass  '),
    ('S7', 'trailing comment drops permissionMode', 'test_frontmatter_mode_fails_closed', 'v = re.sub(r"\\s+#.*$", "", v).strip()', 'v = "" if "#" in v else v.strip()'),
    ('S7', 'unreadable permissionMode treated as inherit', 'test_frontmatter_mode_fails_closed', 'fm[k] = v or ("?" if k == "permissionMode" else "")', 'fm[k] = v'),
    ('S8', 'deadline_s 0 unbounds host none', 'test_deadline_zero_keeps_the_bound', 'ok = isinstance(deadline_s, (int, float)) and deadline_s > 0', 'ok = deadline_s is not None'),
    ('C3', 'a CLI crash escapes ask()', 'test_cli_crash_is_an_error_outcome', '        except Exception as e:  # noqa: BLE001 - the CLI exited non-zero', '        except ZeroDivisionError as e:  # noqa: BLE001 - the CLI exited non-zero'),
    ('C3', 'a connect failure escapes the CLI', 'test_cli_crash_is_an_error_outcome', '    except Exception as e:  # noqa: BLE001 - the SDK or the CLI failed', '    except ZeroDivisionError as e:  # noqa: BLE001 - the SDK or the CLI failed'),
    ('C4', 'no settle between asks', 'test_second_ask_gets_its_own_reply', '                    await self._settle()  ', '                    pass  '),
    ('C5', 'first_message_s timed from the hook frames', 'test_first_message_s_measures_the_prompt', 'self.asked, r.t0, r.first, self.failure = True, time.monotonic(), None, None', 'self.asked, self.failure = True, None'),
    ('C6', 'stop(why) not mapped', 'test_stop_with_a_reason_interrupts', 'self._stop = "signal" if why == "signal" else "cancelled"', 'self._stop = why'),
    ('C7', '_eof survives disconnect', 'test_reconnect_after_eof_still_bounds', 'self.loaded, self._eof = self._client, None, None, False, False', 'self.loaded, self._eof = self._client, None, None, False, self._eof'),
    ('C8', 'close() not idempotent', 'test_closed_tty_reader_does_not_steal_a_reused_fd', '        if self.closed:\n            return\n        self.closed = True', '        self.closed = True'),
    ('C8', 'reader thread never stops', 'test_closed_tty_reader_does_not_steal_a_reused_fd', '        while not self.closed:', '        while True:'),
    ('C9', 'M32: marker read after the first success response', 'test_load_fails_closed', 'while not (len(done) >= need and started <= done):', 'while not done:'),
    ('C9', 'M17: gate plan regardless of host', 'test_plan_gate_unattended', 'gate = "ask" if ask else ("plan" if host == "none" and mode == "plan"', 'gate = "ask" if ask else ("plan" if mode == "plan"'),
    ('R1', 'project agents: only top-level *.md files count', 'test_project_agents_any_layout_fail_closed', 'if os.path.lexists(a) and os.path.realpath(a) != user]', 'if glob.glob(os.path.join(glob.escape(a), "*.md")) and os.path.realpath(a) != user]'),
    ('R1', "a linked worktree's main checkout not read", 'test_project_agents_any_layout_fail_closed', 'if os.path.isfile(g):                            # gitdir', 'if False:                            # gitdir'),
    ('R1', 'add_dirs not checked', 'test_project_agents_any_layout_fail_closed', 'roots = [os.path.join(d, str(x)) for x in extra]', 'roots = []'),
    ('R2', 'inherit-permission-mode allowed', 'test_extra_args_allowlist', 'EXTRA_OK = ("debug", "debug-file", "verbose", "model", "fallback-model", "effort", "betas", "name")', 'EXTRA_OK = ("debug", "inherit-permission-mode", "debug-file", "verbose", "model", "fallback-model", "effort", "betas", "name")'),
    ('R2', 'sandbox allowed in extra_args', 'test_extra_args_allowlist', 'EXTRA_OK = ("debug", "debug-file", "verbose", "model", "fallback-model", "effort", "betas", "name")', 'EXTRA_OK = ("debug", "sandbox", "debug-file", "verbose", "model", "fallback-model", "effort", "betas", "name")'),
    ('R3', 'no hard wrap', 'test_tty_rows_never_start_with_model_text', 'for i in range(0, len(ln) or 1, w))', 'for i in [0] if (w := 10**6))'),
    ('R3', 'options not quoted', 'test_tty_rows_never_start_with_model_text', 'menu = self.quote("\\n".join(f"{i + 1}) {one_line(o, 200)}" for i, o in enumerate(opts[:20])), 6000)', 'menu = "\\n".join(f"  {i + 1}) {one_line(o, 200)}" for i, o in enumerate(opts[:20]))'),
    ('R3', 'tabs not expanded', 'test_tty_rows_never_start_with_model_text', 'clean_text(text, cap).expandtabs(4)', 'clean_text(text, cap)'),
    ('R4', "crash after a result keeps the report's outcome", 'test_crash_after_a_result_is_an_error', '                out["outcome"] = "error"  ', '                pass  '),
    ('R4', 'a CLI error result loses its class on a crash', 'test_crash_after_a_result_is_an_error', 'if not (r.results and r.results[-1].get("is_error")):', 'if True:'),
    ('R5', 'annotations reach the callable host', 'test_ask_model_supplied_annotations_do_not_count', 'if k not in ("answers", "annotations")}', 'if k != "answers"}'),
    ('R5', 'annotations kept by the tty host', 'test_ask_model_supplied_annotations_do_not_count', 'kept = {k: v for k, v in inp.items() if k != "annotations"}', 'kept = dict(inp)'),
    ('R6', 'config_dir not passed to the CLI', 'test_config_dir_reaches_the_cli', 'if config_dir and self.env.setdefault("CLAUDE_CONFIG_DIR", config_dir) != config_dir:', 'if config_dir and self.env.get("CLAUDE_CONFIG_DIR", config_dir) != config_dir:'),
    ('S3r', 'host none leaves the mode to the settings', 'test_host_none_passes_plan_explicitly', 'mode = self.permission_mode or ("plan" if self.host == "none" else None)', 'mode = self.permission_mode'),
    ('V1', 'no TCIFLUSH before a prompt', 'test_tty_flushes_after_the_gap', '            termios.tcflush(self.rfd, termios.TCIFLUSH)', '            pass'),
    ('V1', 'TCIFLUSH before the gap', 'test_tty_flushes_after_the_gap', '        self.seq += 1                                    # a gap', '        termios.tcflush(self.rfd, termios.TCIFLUSH)\n        self.seq += 1                                    # a gap'),
    ('V2', 'grace without state frames despite an agent in flight', 'test_no_state_frames_agent_in_flight_keeps_reading', 'if r.state is None and not r.inflight():', 'if r.state is None:'),
    ('V2', 'grace once no agent is in flight, state frames or not', 'test_no_state_frames_agent_in_flight_keeps_reading', 'if r.state is None and not r.inflight():', 'if not r.inflight() or r.state is None:'),
    ('N1', 'relative add_dirs resolved against the app cwd', 'test_relative_add_dirs_resolve_against_the_session_cwd', 'roots = [os.path.join(d, str(x)) for x in extra]', 'roots = [*extra]'),
    ('N2', 'no plan-gate re-check before a prompt', 'test_project_agents_appearing_after_connect_fail_the_ask', 'if self.host == "none" and (self.permission_mode or "plan") == "plan" and (     # N2', 'if False and (     # N2'),
    ('N3', 'extra_args values unchecked', 'test_extra_args_values_cannot_carry_flags', 'or v is not None and (k == "verbose" or str(v).startswith("-"))]', 'or False]'),
    ('N3', 'a value for verbose accepted', 'test_extra_args_values_cannot_carry_flags', '(k == "verbose" or str(v).startswith("-"))]', '(str(v).startswith("-"))]'),
    ('N4', 'no host row naming the tool next to the answer', 'test_tty_answer_line_names_the_tool', 'stack_sdk: ^ {who} wants {name} "', '"'),
    ('OWN1', 'only directories count as agent paths (isdir)', 'test_agents_path_of_any_kind_fails_closed', 'if os.path.lexists(a) and os.path.realpath(a) != user]', 'if os.path.isdir(a) and os.path.realpath(a) != user]'),
    ('OWN2', 'the walk skips the parents of cwd', 'test_agents_found_up_the_parent_chain', '        d = os.path.dirname(d)\n', '        d = "/"\n'),
]


def pytest(helper: Path, tests: list[str], timeout: float = 240) -> tuple[int | None, str, float]:
    t = time.monotonic()
    env = dict(os.environ, SDK_HELPER=str(helper))
    try:
        p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *(TESTS + x for x in tests)],
                           cwd=REPO, env=env, capture_output=True, text=True, timeout=timeout, check=False)
        return p.returncode, p.stdout + p.stderr, round(time.monotonic() - t, 1)
    except subprocess.TimeoutExpired:
        return None, "TIMEOUT", round(time.monotonic() - t, 1)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--list", action="store_true")
    ap.add_argument("-k", default="")
    ap.add_argument("-j", type=int, default=4)
    ap.add_argument("--out", default="-")      # tests/sdk_mutations.out is written only when named explicitly
    a = ap.parse_args(argv)
    keys = [k for k in a.k.split(",") if k]
    todo = [m for m in MUTANTS if not keys or any(k in m[0] or k in m[1] for k in keys)]
    if a.list:
        for mid, what, test, _old, _new in todo:
            print(f"{mid:<4} {test:<52} {what}")
        return 0
    src = HELPER.read_text()
    bad = [(m[0], m[1], src.count(m[3])) for m in todo if src.count(m[3]) != 1]
    if bad:
        print("anchors that do not match exactly once:", bad)
        return 2
    scratch = Path(tempfile.mkdtemp(prefix="sdk-mutations-"))
    lines: list[str] = []
    try:
        clean = scratch / "clean.py"
        clean.write_text(src)
        names = sorted({m[2] for m in todo})
        rc, out, dt = pytest(clean, names)
        lines.append(f"BASE  {len(names)} named tests: {'PASS' if rc == 0 else 'FAIL'} ({dt}s)")
        print(lines[-1], flush=True)
        if rc != 0:
            print(out[-3000:])
            return 1

        def one(i: int) -> tuple[bool, str]:
            mid, what, test, old, new = todo[i]
            f = scratch / f"m{i:03d}.py"
            f.write_text(src.replace(old, new))
            rc, out, dt = pytest(f, [test])
            killed = rc is None or (rc != 0 and any(f"{w} {TESTS}{test}" in out for w in ("FAILED", "ERROR")))
            first = next((ln for ln in out.splitlines() if ln.startswith("E ")), "TIMEOUT" if rc is None else "")
            row = f"{'KILLED' if killed else 'ALIVE '} {mid:<4} {test:<52} {what} [{dt}s] {first[:120]}"
            print(row, flush=True)
            return killed, row
        with ThreadPoolExecutor(max(1, a.j)) as ex:
            res = list(ex.map(one, range(len(todo))))
        lines += [r for _, r in res]
        alive = [r for k, r in res if not k]
        lines.append(f"{len(res) - len(alive)} of {len(res)} killed")
        print(lines[-1])
        if a.out != "-" and not keys:
            Path(a.out).write_text("\n".join(lines) + "\n")
        return 0 if not alive else 1
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
