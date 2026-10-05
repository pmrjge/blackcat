"""Mutation check for test_output_shrink.py: each test must fail on at least one seeded bug.

Run: uv run --no-project --python 3.13 --with pytest python mutate.py <fixed-tree> <test file>
Copies <fixed-tree>/dot-claude to a temp dir per mutant, applies one substitution, runs the selected
tests with OUTPUT_SHRINK_ROOT pointing there, and expects a failure (killed). Nothing outside the
temp dir is written.
"""
import os
import shutil
import subprocess
import sys
import tempfile

H, ST, SJ = "dot-claude/hooks/output_shrink.py", "dot-claude/hooks/stack_hook.py", "dot-claude/settings.json"

M = [  # (test selector for -k, file, old, new)
    ("test_shadow_never_changes_output_and_writes_no_spill", H, 'if md != "on":\n        return None, row',
     'if md == "off":\n        return None, row'),
    ("test_mode_defaults_to_shadow", H, 'DEFAULT_MODE = "shadow"', 'DEFAULT_MODE = "on"'),
    ("test_off_writes_nothing", H, 'if md == "off" or not isinstance(ev, dict)', "if not isinstance(ev, dict)"),
    ("test_mode_value_is_case_and_space_tolerant", H, '"").strip().lower()', '"").strip()'),
    ("test_on_keeps_errors_summary_head_tail_in_order", H, 'take(list(reversed(err[half:])) + err[:half], "err")',
     "pass"),
    ("test_last_error_lines_win_when_errors_exceed_budget", H,
     'take(list(reversed(err[half:])) + err[:half], "err")', 'take(err, "err")'),
    ("test_npm_err_lines_count_as_errors", H, r'(?:\berr!|\b(?:error|errors|', r'(?:\b(?:err!|error|errors|'),
    ("test_stderr_is_merged_into_the_digest_and_other_fields_kept", H,
     'return out + ("\\n" if out and err else "") + err', "return out"),
    ("test_render_marks_omitted_ranges_exactly", H, '"… [lines %d-%d omitted] …" % (prev + 2, i)',
     '"… [lines %d-%d omitted] …" % (prev + 1, i)'),
    ("test_long_lines_are_cut_in_the_digest", H, "LINE_MAX = 300 ", "LINE_MAX = 30000 "),
    ("test_digest_is_bounded_and_saves_a_quarter", H, '{"err": 1500,', '{"err": 15000,'),
    ("test_logged_kept_chars_is_the_real_digest_size", H, "kept_chars=len(digest),",
     "kept_chars=sum(len(cut_line(lines[i])) + 1 for i in kept) + 240,"),
    ("test_shadow_logs_the_same_decision_as_on", H, "thr=thr[cls])", 'thr=thr[cls] + (md == "shadow"))'),
    ("test_read_keeps_a_contiguous_head_and_pages_the_rest", H, "content=head, numLines=k)",
     "content=head, numLines=len(lines))"),
    ("test_read_first_line_too_long_is_cut_and_said", H, '" (line %d cut)" % first if first_cut else ""', '""'),
    ("test_prompt_files_never_shrunk", H, "elif prompt_file(path):", "elif False:"),
    ("test_ranged_read_never_shrunk", H, 'elif inp.get("offset") is not None or inp.get("limit") is not None:',
     'elif inp.get("offset") is not None:'),
    ("test_non_text_read_untouched", H, 'resp.get("type") == "text" and ', ""),
    ("test_bash_threshold_boundary", H, "if len(text) <= thr[cls]:", "if len(text) < thr[cls]:"),
    ("test_bash_threshold_boundary and sed", H, 'VIEW_FAMILIES = {"sed", ', "VIEW_FAMILIES = {"),
    ("test_read_threshold_boundary", H, '"read": 20000}', '"read": 20001}'),
    ("test_threshold_env_override_clamped", H, "min(max(v, THR_MIN), THR_MAX)", "max(v, THR_MIN)"),
    ("test_small_outputs_are_logged_without_a_digest", H, "len(text) <= SWEEP_FLOOR", "len(text) <= 0"),
    ("test_same_call_again_returns_full_output", H, "if wfd is not None and earlier_cut(",
     "if False and earlier_cut("),
    ("test_reading_a_spill_is_never_shrunk", H, "if SPILL_DIR_RE.search(cmd):", "if False:"),
    ("test_grep_over_the_spill_directory_is_never_shrunk", H, r'SPILL_DIR_RE = re.compile(r"output-shrink/spill\b")',
     r'SPILL_DIR_RE = re.compile(r"output-shrink/spill/[A-Za-z0-9._-]+")'),
    ("test_special_bash_results_untouched", H, ' or resp.get("backgroundTaskId")', ""),
    ("test_spill_is_0600_in_0700_dirs_under_the_project", H,
     "os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=sfd)",
     "os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=sfd)"),
    ("test_existing_wide_dirs_are_tightened", H, "if private and st.st_mode & 0o077:", "if False:"),
    ("test_hostile_tool_use_id_cannot_steer_the_spill_path", H, 're.sub(r"[^A-Za-z0-9_-]", "", tuid or "")[-40:]',
     '(tuid or "")[-40:]'),
    ("test_symlink_below_the_project_disables_writes", H, "os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd",
     "os.O_RDONLY | os.O_DIRECTORY, dir_fd=parent_fd"),
    ("test_symlinked_log_is_not_followed", H, "flags | os.O_NOFOLLOW | os.O_NONBLOCK", "flags | os.O_NONBLOCK"),
    ("test_fifo_log_does_not_hang", H, "flags | os.O_NOFOLLOW | os.O_NONBLOCK", "flags | os.O_NOFOLLOW"),
    ("test_refused_project_roots_write_nothing and home", H,
     'if p in ("/", os.path.realpath(os.path.expanduser("~")))', 'if p in ("/",)'),
    ("test_refused_project_roots_write_nothing and config", H, "if any(inside(p, c) for c in config_dirs()):",
     "if False:"),
    ("test_unwritable_spill_dir_means_no_shrink", H,
     'row["cut"], row["skip"] = False, "spill-failed:%s" % type(exc).__name__\n        return None, row',
     'row["cut"], row["skip"] = False, "spill-failed:%s" % type(exc).__name__'),
    ("test_prune_removes_only_own_old_files", H, "if not SPILL_NAME_RE.match(name):\n            continue",
     "if not SPILL_NAME_RE.match(name):\n            pass"),
    ("test_git_status_stays_clean", H, 'os.write(fd, b"*\\n")', 'os.write(fd, b"\\n")'),
    ("test_spill_masks_credentials_and_keeps_line_numbers", H, "for r, rep in rx:\n            s = r.sub(rep, s)",
     "for r, rep in rx:\n            pass"),
    ("test_digest_only_holds_lines_of_the_original", H, "out.append(cut_line(lines[i]))",
     'out.append(cut_line(lines[i]) + " ")'),
    ("test_log_holds_no_output_command_or_path", H, 'row["key"] = h16(cmd)', 'row["key"] = cmd'),
    ("test_log_holds_no_output_command_or_path", H, 'i += 2 if toks[i] in GIT_ARG_OPTS else 1', "i += 1"),
    ("test_family", H, 'if not FAM_RE.match(t0):\n            return "other"', "if not FAM_RE.match(t0):\n            pass"),
    ("test_no_credential_tables_means_no_spill_and_no_shrink", H, 'data = scrub(text).encode("utf-8", "replace")',
     'data = text.encode("utf-8", "replace")'),
    ("test_scrub_masks_a_whole_pem_block", H,
     'if PEM_BEGIN.search(s):\n            out.append("***")\n            in_pem = not PEM_END.search(s)',
     'if PEM_BEGIN.search(s):\n            out.append("***")\n            in_pem = False'),
    ("test_output_never_touches_the_input", H, 'new = dict(resp, stdout=digest, stderr="")',
     'resp.update(stdout=digest, stderr="")\n    new = resp'),
    ("test_output_never_touches_the_input", H, '{"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": new}}',
     '{"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": new, "updatedInput": inp}}'),
    ("test_other_events_and_tools_ignored", H, 'ev.get("hook_event_name") != "PostToolUse"',
     'ev.get("hook_event_name") == "Nope"'),
    ("test_settings_registers_posttooluse_bash_read_only", SJ, '"matcher": "Bash|Read",', '"matcher": "Bash|Read|Grep",'),
    ("test_settings_registers_posttooluse_bash_read_only", SJ, '"autoCompactEnabled": true,', '"autoCompactEnabled": false,'),
    ("test_through_the_stack_hook_stub", ST, '"web_caps": False,\n           "output_shrink": False}', '"web_caps": False}'),
    ("test_garbage_input_fails_open", H, 'str(exc)[:200]))\n        return 0', 'str(exc)[:200]))\n        return 1'),
    ("test_self_test_passes", H, "if wfd is not None and earlier_cut(", "if False and earlier_cut("),
    ("test_report_reads_the_log", H, "n_repeat += 1", "n_repeat += 0"),
]


def main(tree, tests):
    tests = os.path.abspath(tests)
    names = sorted({l.split("(")[0][4:] for l in open(tests) if l.startswith("def test_")})
    covered, bad = set(), []
    for sel, rel, old, new in M:
        with tempfile.TemporaryDirectory() as d:
            shutil.copytree(os.path.join(tree, "dot-claude"), os.path.join(d, "dot-claude"),
                            ignore=shutil.ignore_patterns("__pycache__"))
            p = os.path.join(d, rel)
            src = open(p).read()
            if src.count(old) != 1:
                bad.append((sel, "pattern found %d times" % src.count(old)))
                continue
            open(p, "w").write(src.replace(old, new))
            r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", tests, "-k", sel],
                               env=dict(os.environ, OUTPUT_SHRINK_ROOT=d), capture_output=True, text=True, timeout=300)
            tail = (r.stdout.strip().splitlines() or [""])[-1]
            killed = r.returncode == 1 and "failed" in tail
            print("%-8s %-62s %s" % ("KILLED" if killed else "SURVIVED", sel[:62], tail[:60]))
            if killed:
                covered.add(sel.split(" and ")[0])
            else:
                bad.append((sel, tail))
    missing = [n for n in names if n not in covered]
    print("mutants %d, killed %d; tests %d, without a killed mutant: %s; problems: %s"
          % (len(M), len(M) - len(bad), len(names), missing or "none", bad or "none"))
    return 1 if missing or bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
