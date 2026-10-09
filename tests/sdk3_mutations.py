"""Seeded-mutation proof for SDK-3: agent_guard.py's plan gate (G*) and host-stop release (R*), stack_usage.py's
entrypoint column (U*), doctor.sh's sdk line (D*) and install.sh's lock staging (I*).

Each mutant is one text substitution, which must match its file exactly once. Its NAMED test then runs against the
mutated copy and must FAIL: its id must appear in pytest's FAILED/ERROR lines, or the run must time out. SELFTEST
means `agent_guard.py --self-test` must exit non-zero. Before any mutant runs, the clean copies must pass every
named test.

Copies, never the tracked files:
- the guard and the collector run from a scratch copy of hooks/ (the rest of dot-config/dot-claude/
  linked), via GUARD= and USAGE_PY=;
- doctor.sh runs from a scratch copy, via SDK_DOCTOR=.
install.sh mutants need the checkout itself, because the install test snapshots the git tree. They run only with
--in-place: the file is restored byte for byte afterwards, and the run fails if the restore does not match.

  uv run --no-project --python 3.13 --with-requirements requirements/tools.txt python tests/sdk3_mutations.py
      [--list] [-k ID_OR_TEXT[,..]] [-j N (default 4)] [--in-place] [--out PATH (default "-": stdout only)]
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CONF = REPO / "dot-config" / "dot-claude"
FILES = {"guard": CONF / "hooks" / "agent_guard.py", "usage": CONF / "hooks" / "stack_usage.py",
         "doctor": CONF / "bin" / "doctor.sh", "install": REPO / "install.sh"}
PG, SU, SD, IS = "tests/test_plan_gate.py::", "tests/test_stack_usage.py::", "tests/test_sdk_doctor.py::", \
    "tests/test_install_state.py::"
SELFTEST = "SELFTEST"

MUTANTS = [  # (id, mutant, file key, named test, anchor, replacement)
    # ---- the plan gate
    ("G1", "no plan gate on Agent", "guard", PG + "test_plan_mode_refuses_every_builder",
     '        why = plan_gate_violation(ev, "Agent", child, spawn_row(parent, caller_is_main(ev, parent)))\n'
     '        if why:\n            deny(why)\n', ""),
    ("G2", "plan mode read as another mode", "guard", PG + "test_other_modes_and_no_reported_mode_dispatch_builders",
     'return str(ev.get("permission_mode") or "").strip() == "plan"',
     'return str(ev.get("permission_mode") or "").strip() != "plan"'),
    ("G3", "a builder listed as plan-safe", "guard", PG + "test_plan_safe_types_are_the_agents_without_a_mode",
     '"planner", "proof-checker", "scout", "security-auditor", "verifier"})',
     '"planner", "proof-checker", "scout", "security-auditor", "verifier", "coder"})'),
    ("G4", "Workflow runs in plan mode", "guard", PG + "test_no_workflow_runs_in_plan_mode",
     '    why = plan_gate_violation(ev, "Workflow")\n    if why:\n        deny(why)\n', ""),
    ("G5", "a finished builder resumes in plan mode", "guard",
     PG + "test_resuming_a_finished_builder_is_refused_in_plan_mode",
     "        or plan_resume_violation(d, ev, target_id, ttype)", "        or None"),
    ("G6", "a finished record of unknown type resumes", "guard",
     PG + "test_a_finished_record_of_unknown_type_is_refused_in_plan_mode",
     "    t = norm(rec.get(\"type\")) or norm(ttype)\n    why = plan_unsafe(ev, t)\n",
     "    t = norm(rec.get(\"type\")) or norm(ttype)\n    why = plan_unsafe(ev, t) if t else None\n"),
    ("G7", "project agents folders ignored", "guard", PG + "test_a_project_agents_folder_closes_the_gate",
     '    dirs = project_agent_dirs(ev.get("cwd"), conf)', "    dirs = []"),
    ("G8", "the walk skips the parents of cwd", "guard", PG + "test_project_agent_dirs_walk_like_stack_sdk",
     "            return roots\n        d = os.path.dirname(d)\n\n\ndef plan_unsafe",
     "            return roots\n        d = \"/\"\n\n\ndef plan_unsafe"),
    ("G9", "a linked worktree's main checkout ignored", "guard", PG + "test_project_agent_dirs_walk_like_stack_sdk",
     "        if os.path.isfile(g):                    # gitdir:", "        if False:                    # gitdir:"),
    ("G10", "self-test misses a builder in PLAN_SAFE_TYPES", "guard", SELFTEST,
     '"planner", "proof-checker", "scout", "security-auditor", "verifier"})',
     '"planner", "proof-checker", "scout", "security-auditor", "verifier", "writer"})'),
    # ---- host-stop release
    ("R1", "no release before the count", "guard", PG + "test_a_child_its_host_stopped_is_released_before_the_count",
     "        reap_host_stopped(d, ev)        # children", "        pass        # children"),
    ("R2", "any truthy stoppedByUser releases", "guard", PG + "test_only_a_true_stopped_by_user_flag_releases",
     'meta.get("stoppedByUser") is not True', 'not meta.get("stoppedByUser")'),
    ("R3", "a flag older than the latest start releases", "guard",
     PG + "test_a_child_resumed_after_the_stop_is_not_released",
     "    return t_meta >= start and t_tr <= t_meta + REAP_SLACK_S", "    return t_tr <= t_meta + REAP_SLACK_S"),
    ("R4", "a child still writing is released", "guard",
     PG + "test_a_child_still_writing_after_the_flag_is_not_released",
     "    return t_meta >= start and t_tr <= t_meta + REAP_SLACK_S", "    return t_meta >= start"),
    ("R6", "no release before a resume", "guard", PG + "test_a_host_stop_also_frees_the_slot_for_a_resume",
     "        reap_host_stopped(d, ev)        # children",
     "        tool == \"Agent\" and reap_host_stopped(d, ev)        # children"),
    # ---- the entrypoint column
    ("U1", "entrypoint never reaches the rows", "usage",
     SU + "test_entrypoint_is_the_main_transcripts_first_on_every_row_of_the_session",
     '        base["entrypoint"] = ma["ep"]     # every row', '        base["entrypoint"] = ""     # every row'),
    ("U2", "the last entrypoint wins", "usage",
     SU + "test_entrypoint_is_the_main_transcripts_first_on_every_row_of_the_session",
     '    if not a.get("ep") and valid_entrypoint(r.get("entrypoint")):',
     '    if valid_entrypoint(r.get("entrypoint")):'),
    ("U3", "an invalid entrypoint is taken", "usage",
     SU + "test_entrypoint_is_the_main_transcripts_first_on_every_row_of_the_session",
     '    if not a.get("ep") and valid_entrypoint(r.get("entrypoint")):',
     '    if not a.get("ep") and isinstance(r.get("entrypoint"), str):'),
    ("U4", "the entrypoint cell is not validated", "usage", SU + "test_entrypoint_cell_validated_on_write_and_read",
     "        return bool(ENTRYPOINT_RE.match(v))", "        return True"),
    ("U5", "the header before entrypoint is set aside", "usage",
     SU + "test_an_older_runs3_header_is_merged_not_set_aside",
     "HEADERS = (COLUMNS, COLUMNS_EQ, COLUMNS_V3)", "HEADERS = (COLUMNS, COLUMNS_V3)"),
    ("U6", "an older header is kept, not merged", "usage", SU + "test_an_older_runs3_header_is_merged_not_set_aside",
     "    legacy = size and _header_of(cur) != COLUMNS", "    legacy = size and _header_of(cur) == COLUMNS_V3"),
    ("U7", "no head read for an older state", "usage",
     SU + "test_a_handed_off_state_reads_the_entrypoint_from_the_transcript_head",
     '            ma["ep"] = head_entrypoint(mpath)', '            ma["ep"] = ""'),
    ("U8", "a collector without `cols` is kept", "usage",
     SU + "test_a_collector_without_the_column_count_is_retired",
     "            schema == SCHEMA_VERSION and cols is not None and cols >= len(COLUMNS))):",
     "            schema == SCHEMA_VERSION)):"),
    ("U9", "entrypoint not the last column", "usage", SU + "test_without_an_entrypoint_every_other_cell_is_byte_equal",
     "COLUMNS = COLUMNS_EQ + ENTRY_COLS", "COLUMNS = ENTRY_COLS + COLUMNS_EQ"),
    # ---- doctor.sh's sdk line
    ("D1", "the lock check goes online", "doctor",
     SD + "test_all_present_reads_both_versions_without_importing_the_sdk",
     'lock --script "$s" --check --offline', 'lock --script "$s" --check'),
    ("D2", "the lock check may write the lock", "doctor",
     SD + "test_all_present_reads_both_versions_without_importing_the_sdk",
     'lock --script "$s" --check --offline', 'lock --script "$s" --offline'),
    ("D3", "a stale lock reads as ok", "doctor", SD + "test_a_stale_or_missing_lock_warns",
     'elif "$uvb" lock --script "$s" --check --offline >/dev/null 2>&1 </dev/null; then',
     'elif true; then'),
    ("D4", "a missing lock reads as ok", "doctor", SD + "test_a_stale_or_missing_lock_warns",
     'if [ ! -f "$s.lock" ]; then lock="lock missing"', 'if false; then lock="lock missing"'),
    ("D5", "an environment of another version is reported as bundled", "doctor",
     SD + "test_no_environment_yet_and_an_environment_of_another_version",
     'elif [ "$ver" != "$pin" ]; then', 'elif false; then'),
    ("D6", "the SDK package is imported", "doctor",
     SD + "test_all_present_reads_both_versions_without_importing_the_sdk",
     's = u.find_spec("claude_agent_sdk")', 'import claude_agent_sdk; s = u.find_spec("claude_agent_sdk")'),
    ("D7", "a stale lock is not a warning", "doctor", SD + "test_a_stale_or_missing_lock_warns",
     '*) warn "$got — rerun install.sh" ;;', '*) ok "$got — rerun install.sh" ;;'),
    # ---- review round 1
    ("U10", "set-aside strays are never merged back", "usage",
     SU + "test_an_older_collector_of_another_session_hides_no_rows",
     "    strays = _strays(cur)\n", "    strays = []\n"),
    ("U11", "a stray of an unknown header is merged and deleted", "usage",
     SU + "test_a_stray_of_an_unknown_header_is_never_merged_or_deleted",
     "if STRAY_NAME_RE.search(os.path.basename(p)) and _header_ok(p)),",
     "if STRAY_NAME_RE.search(os.path.basename(p))),"),
    ("U12", "the older row of a key wins the merge", "usage",
     SU + "test_an_older_collector_of_another_session_hides_no_rows",
     "if k not in rows or ts(r) >= ts(rows[k]):", "if True:"),
    ("G11", "the refusal names only ExitPlanMode", "guard",
     PG + "test_the_refusal_tells_a_main_thread_without_exit_plan_mode_how_to_leave_plan",
     "leaves Plan with Shift+Tab or --permission-mode acceptEdits", "leaves Plan another way"),
    ("G12", "Skill has no handler", "guard", PG + "test_a_forked_skill_into_a_builder_is_refused_in_plan_mode",
     '    ("PreToolUse", "Skill"): on_skill,\n', ""),
    ("G13", "a fork without agent: is let through", "guard",
     PG + "test_a_forked_skill_without_an_agent_is_general_purpose_and_refused",
     'out += SKILL_AGENT_RE.findall(fm) or ["general-purpose"]', "out += SKILL_AGENT_RE.findall(fm)"),
    ("G14", "plugin skills are not read", "guard", PG + "test_plugin_and_user_skill_definitions_are_read",
     '"plugins/cache/*/*/*/skills/%s/SKILL.md", ', ""),
    ("G15", "a skill name with a path is read", "guard", PG + "test_plugin_and_user_skill_definitions_are_read",
     'SKILL_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\\Z")', 'SKILL_NAME_RE = re.compile(r".+\\Z")'),
    ("G16", "no child-side backstop", "guard",
     PG + "test_a_plan_dispatched_child_running_in_a_writing_mode_runs_nothing",
     "why = generic_agent_reason(ev) or plan_child_reason(ev)", "why = generic_agent_reason(ev)"),
    ("G17", "no marker for a plan-mode spawn", "guard",
     PG + "test_a_plan_dispatched_child_running_in_a_writing_mode_runs_nothing",
     "            mark_plan_spawn(d, tid)         # the child-side", "            pass         # the child-side"),
    ("G18", "a child without a reported mode is refused", "guard",
     PG + "test_a_plan_dispatched_child_running_in_a_writing_mode_runs_nothing",
     "    if not aid or not mode or mode in PLAN_CHILD_MODES:", "    if not aid or mode in PLAN_CHILD_MODES:"),
    ("G19", "plan markers survive a restart", "guard", PG + "test_plan_markers_are_dropped_at_startup_and_named_safely",
     '    shutil.rmtree(os.path.join(d, PLAN_DIR), ignore_errors=True)', '    pass'),
    ("G20", "the marker name is the raw tool_use_id", "guard",
     PG + "test_plan_markers_are_dropped_at_startup_and_named_safely",
     "    create_excl(os.path.join(folder, safe(tid)))", "    create_excl(os.path.join(folder, tid))"),
    # ---- review round 2
    ("U13", "an unreadable stray is a stray again", "usage", SU + "test_an_unreadable_stray_is_set_aside_once",
     "if STRAY_NAME_RE.search(os.path.basename(p)) and _header_ok(p)),", "if _header_ok(p)),"),
    ("U14", "a failing rotation stops the append", "usage", SU + "test_a_rotation_that_fails_never_stops_the_append",
     "        except OSError as exc:           # a rename or rewrite",
     "        except ValueError as exc:           # a rename or rewrite"),
    ("G21", "a command's subdirectory prefix is not read", "guard",
     PG + "test_a_forked_command_in_a_subdirectory_is_refused_in_plan_mode",
     "        if prefix:\n            found.append(", "        if False:\n            found.append("),
    ("G22", "plugin commands are not read", "guard", PG + "test_plugin_commands_and_nested_names_resolve",
     '"plugins/cache/*/*/*/commands/%s.md",', ""),
    ("G23", "an allowed Skill leaves no marker", "guard",
     PG + "test_a_skill_allowed_in_plan_mode_leaves_the_backstop_marker",
     '    mark_plan_spawn(d, ev.get("tool_use_id"))\n', ""),
    ("G24", "markers outlive the plan", "guard", PG + "test_markers_lapse_once_the_main_thread_leaves_plan",
     '        shutil.rmtree(os.path.join(state_root(), safe(ev.get("session_id"), "nosession"), PLAN_DIR), '
     'ignore_errors=True)', "        pass"),
    ("G25", "markers lapse while still planning", "guard", PG + "test_markers_lapse_once_the_main_thread_leaves_plan",
     '    if not ev.get("agent_id") and mode and mode != "plan":', '    if not ev.get("agent_id"):'),
    ("G26", "only the first 8 KB of a skill are read", "guard", PG + "test_a_frontmatter_closed_after_8_kb_is_read",
     "SKILL_HEAD = 65536", "SKILL_HEAD = 8192"),
    ("G27", "a symlinked skill is skipped", "guard", PG + "test_a_symlinked_skill_is_read_where_it_points",
     "        if os.path.normpath(q).startswith(os.path.normpath(base) + os.sep) and os.path.isfile(q) "
     "and q not in out:",
     "        if os.path.realpath(q).startswith(os.path.realpath(base) + os.sep) and os.path.isfile(q) "
     "and q not in out:"),
    # ---- security re-review of 2b96827f
    ("U15", "an unreadable stray is a stray again (reviewer's case)", "usage",
     SU + "test_an_unreadable_stray_is_set_aside_once_and_appends_go_on",
     "if STRAY_NAME_RE.search(os.path.basename(p)) and _header_ok(p)),", "if _header_ok(p)),"),
    ('G28', 'no lookup by another name', "guard",
     PG + 'test_a_forked_skill_reached_by_another_name_is_refused_in_plan_mode',
     '    found = skill_alias_files(sk, prefix, cwd, conf)',
     '    found = []'),
    ('G29', 'a frontmatter name: alias is not matched', "guard",
     PG + 'test_a_plugin_root_skill_is_read_by_its_name',
     'if m and m.group(1).rpartition(":")[2] == sk:',
     'if False:'),
    ('G30', 'a nested apps/web:deploy skill is not read', "guard",
     PG + 'test_a_forked_skill_reached_by_another_name_is_refused_in_plan_mode',
     '    if segs:\n        for r in project_roots(cwd):',
     '    if False:\n        for r in project_roots(cwd):'),
    ('G31', 'a plugin-root SKILL.md is not read', "guard",
     PG + 'test_a_plugin_root_skill_is_read_by_its_name',
     '"plugins", "cache", "*", "*", "*", "SKILL.md"',
     '"plugins", "cache", "*", "*", "*", "NONE.md"'),
    ('G32', 'a BOM hides the frontmatter', "guard",
     PG + 'test_every_yaml_spelling_of_a_fork_is_read',
     'head = fh.read(SKILL_HEAD).lstrip("\\ufeff")',
     'head = fh.read(SKILL_HEAD)'),
    ('G33', 'only the line-anchored spelling is a fork', "guard",
     PG + 'test_every_yaml_spelling_of_a_fork_is_read',
     'FORK_RE = re.compile(r"""["\']?\\bcontext["\']?\\s*:\\s*'
     '(?:(?:!\\S*|&\\S+|[|>][-+0-9]*)\\s+)*(?:["\']?fork\\b|\\*)""")',
     'FORK_RE = re.compile(r"^context:[ \\t]*[\'\\"]?fork[\'\\"]?[ \\t]*(?:#[^\\r\\n]*)?\\r?$", re.M)'),
    ('G34', 'only the first agent: key counts', "guard",
     PG + 'test_a_duplicate_agent_key_is_refused_if_either_is_a_builder',
     'out += SKILL_AGENT_RE.findall(fm) or ["general-purpose"]',
     'out += SKILL_AGENT_RE.findall(fm)[:1] or ["general-purpose"]'),
    # ---- install.sh (--in-place only)
    ("I1", "the lock is not staged", "install", IS + "test_install_stages_the_sdk_lock_beside_the_helper",
     'stage_script 644 "bin/stack_sdk.py.lock"\n', ""),
    ("I2", "the lock is not in the manifest", "install", IS + "test_install_stages_the_sdk_lock_beside_the_helper",
     '"bin/stack_sdk.py", "bin/stack_sdk.py.lock", "bin/stack-budget",', '"bin/stack_sdk.py", "bin/stack-budget",'),
]


def sandbox(root: Path, key: str, text: str) -> dict[str, str]:
    """A copy of the file under `root` with `text`; the env that points the tests at it."""
    if key in ("guard", "usage"):
        conf = root / "conf"
        shutil.copytree(CONF / "hooks", conf / "hooks", ignore=shutil.ignore_patterns("__pycache__"))
        for d in CONF.iterdir():                     # agents/, bin/, settings.json, ...: the repo's own
            if d.name != "hooks":
                os.symlink(d, conf / d.name)
        (conf / "hooks" / FILES[key].name).write_text(text)
        return {"GUARD": str(conf / "hooks" / "agent_guard.py"), "USAGE_PY": str(conf / "hooks" / "stack_usage.py")}
    if key == "doctor":
        root.mkdir(parents=True, exist_ok=True)
        (root / "doctor.sh").write_text(text)
        return {"SDK_DOCTOR": str(root / "doctor.sh")}
    raise ValueError(key)


def run_tests(tests: list[str], env: dict[str, str], timeout: float) -> tuple[int | None, str, float]:
    t = time.monotonic()
    e = dict(os.environ, **env)
    out, rc = "", 0
    try:
        named = [x for x in tests if x != SELFTEST]
        if SELFTEST in tests:
            st = tempfile.mkdtemp(prefix="sdk3-selftest-")
            p = subprocess.run([sys.executable, e.get("GUARD", str(FILES["guard"])), "--self-test"], env=dict(
                e, XDG_STATE_HOME=st), capture_output=True, text=True, timeout=timeout, check=False)
            shutil.rmtree(st, ignore_errors=True)
            out += p.stdout + p.stderr
            rc = rc or p.returncode
        if named:
            p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rfE", *named],
                               cwd=REPO, env=e, capture_output=True, text=True, timeout=timeout, check=False)
            out += p.stdout + p.stderr
            rc = rc or p.returncode
        return rc, out, round(time.monotonic() - t, 1)
    except subprocess.TimeoutExpired:
        return None, "TIMEOUT", round(time.monotonic() - t, 1)


def killed_by(test: str, rc: int | None, out: str) -> bool:
    if rc is None:
        return True
    if test == SELFTEST:
        return rc != 0 and "self-test: FAIL" in out
    return rc != 0 and any(ln.startswith((f"FAILED {test}", f"ERROR {test}")) for ln in out.splitlines())


def first_error(out: str) -> str:
    return next((ln.strip() for ln in out.splitlines() if ln.startswith("E ") or "self-test: FAIL" in ln), "")[:120]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--list", action="store_true")
    ap.add_argument("-k", default="")
    ap.add_argument("-j", type=int, default=4)
    ap.add_argument("--in-place", action="store_true", help="also run the install.sh mutants (restored after each)")
    ap.add_argument("--out", default="-")
    a = ap.parse_args(argv)
    keys = [k for k in a.k.split(",") if k]
    todo = [m for m in MUTANTS if (not keys or any(k == m[0] or k in m[1] for k in keys))
            and (a.in_place or m[2] != "install")]
    if a.list:
        for mid, what, key, test, _o, _n in MUTANTS:
            print(f"{mid:<4} {key:<8} {test.split('::')[-1]:<70} {what}")
        return 0
    src = {k: p.read_text() for k, p in FILES.items()}
    bad = [(m[0], src[m[2]].count(m[4])) for m in todo if src[m[2]].count(m[4]) != 1]
    if bad:
        print("anchors that do not match exactly once:", bad)
        return 2
    scratch = Path(tempfile.mkdtemp(prefix="sdk3-mutations-"))
    lines: list[str] = []
    try:
        for key in sorted({m[2] for m in todo} - {"install"}):          # the clean copies pass every named test
            names = sorted({m[3] for m in todo if m[2] == key})
            rc, out, dt = run_tests(names, sandbox(scratch / f"base-{key}", key, src[key]), 600)
            lines.append(f"BASE  {key:<7} {len(names)} named tests: {'PASS' if rc == 0 else 'FAIL'} ({dt}s)")
            print(lines[-1], flush=True)
            if rc != 0:
                print(out[-3000:])
                return 1

        def row(m: tuple, rc: int | None, out: str, dt: float) -> tuple[bool, str]:
            k = killed_by(m[3], rc, out)
            r = f"{'KILLED' if k else 'ALIVE '} {m[0]:<4} {m[3].split('::')[-1]:<70} {m[1]} [{dt}s] {first_error(out)}"
            print(r, flush=True)
            return k, r

        def one(i: int) -> tuple[bool, str]:
            m = todo[i]
            env = sandbox(scratch / f"m{i:03d}", m[2], src[m[2]].replace(m[4], m[5]))
            return row(m, *run_tests([m[3]], env, 600))

        copies = [i for i, m in enumerate(todo) if m[2] != "install"]
        with ThreadPoolExecutor(max(1, a.j)) as ex:
            res = list(ex.map(one, copies))
        for m in [m for m in todo if m[2] == "install"]:                # --in-place, one at a time
            path, clean = FILES["install"], src["install"]
            digest = hashlib.sha256(clean.encode()).hexdigest()
            try:
                path.write_text(clean.replace(m[4], m[5]))
                rc, out, dt = run_tests([m[3]], {}, 1800)
            finally:
                path.write_text(clean)
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                print("install.sh was not restored: stop")
                return 3
            res.append(row(m, rc, out, dt))
        lines += [r for _, r in res]
        alive = [r for k, r in res if not k]
        lines.append(f"{len(res) - len(alive)} of {len(res)} killed")
        print(lines[-1])
        if a.out != "-":
            Path(a.out).write_text("\n".join(lines) + "\n")
        return 0 if not alive else 1
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
