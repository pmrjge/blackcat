# /// script
# requires-python = ">=3.11"
# dependencies = ["pytest"]
# ///
"""Seeded mutations of the WALL: each one disables one guard in a temp copy of wall/, and the tests named for it
must fail. Exit 0 iff the unmutated copy passes every selection and every mutation is KILLED.

  uv run --script wall/tests/mutations.py        (output kept in wall/tests/mutations.out by the caller)
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

WALL = Path(__file__).resolve().parent.parent
T = "test_wall.py::"

# (id, guarded property, file, old, new, test selections); `old` may be a list of (old, new) pairs (then new = "")
MUTATIONS: list[tuple[str, str, str, Any, str, list[str]]] = [
    ("W01", "identity comes from the host registration", "eq_wall.py",
     "    if (req[\"run_id\"], req[\"channel\"], req[\"item\"], req[\"arm\"]) != (ctx.run_id, ctx.channel, ctx.item, "
     "ctx.arm):", "    if False:",
     [T + "test_forged_identity_token_and_content_are_refused"]),
    ("W02", "per-channel HMAC token", "eq_wall.py",
     'if not hmac.compare_digest(req["token"], channel_token(nonce, ctx.run_id, ctx.channel)):', "if False:",
     [T + "test_forged_identity_token_and_content_are_refused"]),
    ("W03", "content hash", "eq_wall.py",
     'if req["content_sha256"] != content_hash(req):', "if False:",
     [T + "test_forged_identity_token_and_content_are_refused"]),
    ("W04", "replay of a request id", "eq_wall.py",
     "    if rid in state.seen:", "    if False:",
     [T + "test_replayed_request_id_is_refused"]),
    ("W05", "request quotas", "eq_wall.py",
     'if state.per_channel.get(ctx.channel, 0) >= lim["max_requests_per_channel"] or \\', "if False and \\",
     [T + "test_request_quotas_per_channel_and_run"]),
    ("W06", "never push / forge write (request side)", "eq_wall.py",
     "    if tool in NEVER_COMMANDS or any(", "    if False and any(",
     [T + "test_never_push_or_forge_write_even_if_requested"]),
    ("W07", "kind allowlist (default deny)", "eq_wall.py",
     '    if req["kind"] not in policy.kinds_allowed:', "    if False:",
     [T + "test_default_policy_denies_everything"]),
    ("W08", "TOOLS-manifest-covered request refused", "eq_wall.py",
     "elif tool.lower() in manifest:", "elif False:",
     [T + "test_tools_manifest_covered_request_is_refused"]),
    ("W09", "a verdict is required", "eq_wall.py",
     "    if verdict_for(verdicts, cls) is None:", "    if False:",
     [T + "test_verdict_hash_confusion"]),
    ("W10", "only security-auditor verdicts count", "eq_wall.py",
     ' and last.get("reviewer") == "security-auditor"', "",
     [T + "test_only_a_clean_security_auditor_pass_approves"]),
    ("W11", "class hash binds the binary sha256", "eq_wall.py",
     ' "command_sha256": self.command_sha256,\n', "\n",
     [T + "test_verdict_hash_confusion"]),
    ("W12", "consent is single use", "eq_wall.py",
     '\n              and c.get("granted_by") == "user" and c.get("record_sha256") not in state.consumed]',
     '\n              and c.get("granted_by") == "user"]',
     [T + "test_consent_is_single_use_and_bound_to_the_exact_action"]),
    ("W13", "snapshots never follow symlinks", "eq_wall.py",
     "fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=dir_fd)",
     "fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=dir_fd)",
     [T + "test_read_regular_never_follows_or_blocks"]),
    ("W14", "hard-linked files refused", "eq_wall.py",
     "        if st.st_nlink != 1:\n            raise Refused(\"entry\"", "        if False:\n            raise "
     "Refused(\"entry\"",
     [T + "test_hardlinked_request_is_refused"]),
    ("W15", "non-regular tunnel entries removed", "eq_wall.py",
     "                    if not remove_entry(cfd, n):  # e.g.", "                    if False:  # e.g.",
     [T + "test_stale_fifo_in_the_tunnel_is_removed_without_blocking"]),
    ("W16", "tunnel flood trips the channel", "eq_wall.py",
     'if entries > lim["max_tunnel_entries"] or total > lim["max_tunnel_bytes"]:', "if False:",
     [T + "test_tunnel_flood_trips_the_channel"]),
    ("W17", "responses via private temp + rename (planted symlink replaced)", "eq_wall.py",
     '    tmp = f".w-{secrets.token_hex(8)}.tmp"', "    tmp = name",
     [T + "test_write_atomic_replaces_a_symlink_swapped_in_after_the_scan"]),
    ("W18", "command re-hashed on its private copy before exec", "eq_wall.py",
     "        if sha256_bytes(exe_bytes) != plan.command_sha256:", "        if False:",
     [T + "test_command_swapped_after_policy_load_is_not_run"]),
    ("W19", "minimal environment for host execution", "eq_wall.py",
     '        env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp), "TMPDIR": str(tmp), "LANG": "C.UTF-8"}',
     "        env = dict(os.environ)",
     [T + "test_execution_is_confined_and_output_scrubbed"]),
    ("W20", "secret scrubbing of tool output", "eq_wall.py",
     "            text, n_scrub = scrub(res.output.decode(\"utf-8\", \"replace\"),",
     "            text, n_scrub = (res.output.decode(\"utf-8\", \"replace\"), 0) or scrub(\"\",",
     [T + "test_execution_is_confined_and_output_scrubbed"]),
    ("W21", "timeout kills the whole process group", "eq_wall.py",
     "                    os.killpg(p.pid, signal.SIGKILL)", "                    pass",
     [T + "test_tool_output_cap_and_timeout_kill_the_process_group"]),
    ("W22", "output cap", "eq_wall.py",
     "                if len(buf) > cap:\n                    truncated = True",
     "                if False:\n                    truncated = True",
     [T + "test_tool_output_cap_and_timeout_kill_the_process_group"]),
    ("W23", "audit log never under the tunnel root", "eq_wall.py",
     "    if tr == sr or tr.is_relative_to(sr) or sr.is_relative_to(tr):", "    if False:",
     [T + "test_audit_log_never_under_the_tunnel_root"]),
    ("W24", "audit log 0600, one link, no symlink", "eq_wall.py",
     "        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != os.getuid() or st.st_mode & "
     "0o077:", "        if False:",
     [T + "test_audit_log_symlink_or_loose_mode_is_refused"]),
    ("W25", "audit hash chain verified", "eq_wall.py",
     '\n                or rec.get("record_sha256") != dhash("EQWALL-AUDIT-V1", body)):', "):",
     [T + "test_audit_chain_detects_any_edit"]),
    ("W26", "policy refuses never-allowed commands", "eq_wall.py",
     [("    if os.path.basename(cmd) in NEVER_COMMANDS:", "    if False:"),
      ("        if os.path.basename(real) in NEVER_COMMANDS:", "        if False:")], "",
     [T + "test_policy_refuses_never_commands"]),
    ("W27", "policy refuses symlinked commands", "eq_wall.py",
     "        if real != cmd:", "        if False:",
     [T + "test_policy_refuses_symlink_sha_mismatch_unknown_keys_and_ceilings"]),
    ("W28", "option injection (leading '-')", "eq_wall.py",
     'if v.startswith("-") and not spec.allow_dash:', "if False:",
     [T + "test_argv_injection_is_refused"]),
    ("W29", "argv equals tool + rendered typed args", "eq_wall.py",
     '        if req["argv"] != [tool, *rendered]:', "        if False:",
     [T + "test_argv_injection_is_refused"]),
    ("W30", "https only", "eq_wall.py",
     'if u.scheme != "https" or u.username', "if u.username",
     [T + "test_web_research_refuses_off_policy_urls"]),
    ("W31", "user-only grants need a terminal", "eq_wall.py",
     "    if not (os.isatty(0) and os.isatty(1)):", "    if False:",
     [T + "test_grants_need_the_users_terminal"]),
    ("W32", "one broker per run (flock)", "eq_wall.py",
     "            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)", "            pass",
     [T + "test_second_broker_for_the_same_run_is_refused"]),
    ("W33", "client: response schema", "eq_wall_client.py",
     '    if obj["output_path"] is not None and not str(obj["output_path"]).startswith("/eq/tunnel/out-"):',
     "    if False:",
     [T + "test_client_rejects_malformed_or_foreign_responses"]),
    ("W34", "a tripped channel is never served again", "eq_wall.py",
     "            if ch in self.tripped:  #", "            if False:  #",
     [T + "test_tunnel_flood_trips_the_channel"]),
    ("W35", "missing TOOLS manifest fails closed", "eq_wall.py",
     "                if policy.manifest_required:", "                if False:",
     [T + "test_missing_manifest_fails_closed"]),
    ("W36", "kind 'other' always needs user consent", "eq_wall.py",
     ' or req["kind"] == "other"', "",
     [T + "test_other_kind_always_needs_user_consent"]),
    ("W37", "a stale path where the run dir goes is refused", "eq_wall.py",
     "        (t / run_id).mkdir(mode=0o700)", "        (t / run_id).mkdir(mode=0o700, exist_ok=True)",
     [T + "test_stale_run_dir_at_the_tunnel_path_is_refused"]),
    ("W38", "channel dir must stay 0700", "eq_wall.py",
     "    if st.st_uid != os.getuid() or st.st_mode & 0o077:\n        os.close(fd)",
     "    if st.st_uid != os.getuid():\n        os.close(fd)",
     [T + "test_channel_mode_widened_is_refused"]),
    ("W39", "unknown request fields refused", "eq_wall.py",
     "    extra = set(obj) - REQ_KEYS\n    if extra:", "    extra = set(obj) - REQ_KEYS\n    if False:",
     [T + "test_unknown_fields_cannot_smuggle_cwd_env_or_verdicts"]),
    ("W40", "later revocation withdraws a verdict", "eq_wall.py",
     "        if v.get(\"class_sha256\") == class_sha:\n            last = v",
     "        if v.get(\"class_sha256\") == class_sha and last is None:\n            last = v",
     [T + "test_a_later_revocation_withdraws_the_verdict"]),
    ("W41", "infiles executed from the decision-time snapshot (no TOCTOU)", "eq_wall.py",
     "            res = run_confined(d.plan, self.work_root, infiles)",
     "            res = run_confined(d.plan, self.work_root, snapshot_infiles(cfd, list(d.plan.infiles), "
     "self.policy.limits[\"max_infile_bytes\"]))",
     [T + "test_infiles_are_snapshotted_at_decision_time_not_execution_time"]),
    ("W42", "consent binds the infile bytes", "eq_wall.py",
     "    act = action_hash(req, {a[\"value\"]: snap.get(a[\"value\"]) for a in req[\"args\"] if a[\"type\"] == "
     "\"infile\"})",
     "    act = action_hash(req)",
     [T + "test_consent_binds_the_infile_content"]),
    ("W43", "infile bytes capped per request (all infiles together)", "eq_wall.py",
     "            left -= len(out[n])", "            left -= 0",
     [T + "test_infile_bytes_are_capped_per_request"]),
    ("W44", "remove_entry depth bound (W1)", "eq_wall.py",
     "    if _depth >= MAX_REMOVE_DEPTH:\n        return False\n", "",
     [T + "test_remove_entry_is_depth_bounded",
      T + "test_deep_directory_in_the_tunnel_trips_without_killing_the_broker"]),
    ("W45", "an unremovable entry trips the channel (W1)", "eq_wall.py",
     '                        self.trip(ch, cfd, f"unremovable {kind} {n[:80]!r}")\n                        return 0\n',
     "                        pass\n",
     [T + "test_deep_directory_in_the_tunnel_trips_without_killing_the_broker"]),
    ("W46", "one channel's broker error never stops the broker (W1)", "eq_wall.py",
     "            except Exception as e:  # one channel's failure",
     "            except ZeroDivisionError as e:  # one channel's failure",
     [T + "test_a_broker_error_on_one_channel_trips_it_and_serves_the_rest"]),
    ("W47", "abuse budget trips the channel (W2)", "eq_wall.py",
     "return self.refused.get(ch, 0) > ABUSE_BUDGET_FACTOR",
     "return False and self.refused.get(ch, 0) > ABUSE_BUDGET_FACTOR",
     [T + "test_unauthenticated_request_flood_is_bounded"]),
    ("W48", "refused requests spend the budget (W2)", "eq_wall.py",
     "if self.handle(cfd, ch, ctx, n) in REFUSED_CODES:", "if self.handle(cfd, ch, ctx, n) in ():",
     [T + "test_unauthenticated_request_flood_is_bounded"]),
    ("W49", "the abuse budget survives a broker restart (W2)", "eq_wall.py",
     '                if r["code"] in REFUSED_CODES:', "                if False:",
     [T + "test_restarted_broker_keeps_the_abuse_budget"]),
    ("W50", "removed non-regular entries spend the budget (W2)", "eq_wall.py",
     "                    self.refused[ch] = self.refused.get(ch, 0) + 1\n                    if self._over_budget",
     "                    if self._over_budget",
     [T + "test_restarted_broker_keeps_the_abuse_budget"]),
    ("W51", "only a REGULAR .channel.json is exempt (R2c F2)", "eq_wall.py",
     "return name == CHANNEL_FILE and stat.S_ISREG(st.st_mode) and st.st_size <= 4096",
     "return name == CHANNEL_FILE and st.st_size <= 4096",
     [T + "test_a_directory_named_channel_json_is_purged"]),
    ("W52", "a tripped channel's purge spares only the regular identity file (R2c F2)", "eq_wall.py",
     "for n in os.listdir(cfd):\n                    if not is_identity_file(cfd, n):",
     "for n in os.listdir(cfd):\n                    if n != CHANNEL_FILE:",
     [T + "test_a_tripped_channel_purges_a_directory_named_channel_json"]),
]


def make_copy(root: Path) -> Path:
    shutil.copytree(WALL, root / "wall", ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc",
                                                                         ".ruff_cache", "mutations.out"))
    return root / "wall"


def pytest(w: Path, sel: list[str]) -> int:
    args = [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *[str(w / "tests" / s) for s in sel]]
    env = {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1", "HOME": str(Path.home()),
           "TMPDIR": tempfile.gettempdir()}
    return subprocess.run(args, cwd=w.parent, capture_output=True, text=True, check=False, env=env,
                          timeout=600).returncode


def main() -> int:
    bad = 0
    with tempfile.TemporaryDirectory(prefix="wallmut") as td:
        base = make_copy(Path(td) / "base")
        sels = sorted({s for m in MUTATIONS for s in m[5]})
        rc = pytest(base, sels)
        print(f"BASE  unmutated copy, {len(sels)} selections: {'PASS' if rc == 0 else f'FAIL (exit {rc})'}")
        bad += rc != 0
        for mid, what, fname, old, new, sel in MUTATIONS:
            w = make_copy(Path(td) / mid)
            src = (w / fname).read_text()
            pairs = old if isinstance(old, list) else [(old, new)]
            counts = [src.count(o) for o, _ in pairs]
            if counts != [1] * len(pairs):
                print(f"{mid}  {what}: mutation anchor counts {counts} (ERROR)")
                bad += 1
                continue
            for o, nw in pairs:
                src = src.replace(o, nw)
            (w / fname).write_text(src)
            rc = pytest(w, sel)
            verdict = "KILLED" if rc != 0 else "SURVIVED"
            bad += rc == 0
            print(f"{mid}  {verdict:8s} (pytest exit {rc})  {what}  [{fname}: {pairs[0][0].strip()[:50]!r}]")
    print(f"mutations: {len(MUTATIONS)}, problems: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
