"""Seeded-mutation proof for tests/sdk_probes_e.py: the consent gate (its value is the run's own cap), the cross-run
ledger check, the caps and the fail-closed cost book, and the readings the second probe set added (E1's validity
gate and trust split, E3d's terminal, E3P's E3c2a and E3e).
Each mutant is one or more exact text substitutions in a scratch copy of sdk_probes_e.py
(beside a copy of sdk_probes.py, which it loads) under $TMPDIR; sdk_probes_e.py itself is never written. Its
NAMED test in tests/test_sdk_probes_e_fake.py runs against that copy (SDK_PROBES_E_SCRIPT) and must FAIL (its id
in pytest's FAILED/ERROR lines, or the run times out). Every anchor must match exactly once, and the unmutated
copy must pass every named test first. Exit 0 iff the clean copy passes and every mutant is killed.

  uv run --no-project --python 3.13 --with pytest --with claude-agent-sdk==0.2.163 python tests/sdk_probes_e_mutations.py
      [--list] [-k ID[,..]] [-j N (default 4)] [--out PATH (default "-": stdout only; the tracked record is
      refreshed with --out tests/sdk_probes_e_mutations.out)]
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
SCRIPT = REPO / "tests" / "sdk_probes_e.py"
BASE = REPO / "tests" / "sdk_probes.py"
TESTS = "tests/test_sdk_probes_e_fake.py::"
T_ENV = "test_a_paid_run_needs_the_flag_and_the_exact_consent_env"
T_CAPS = "test_caps_shrink_with_the_reported_spend_and_stop_before_the_envelope"
T_REG = "test_a_probe_outside_its_envelope_or_without_a_turn_limit_is_refused"
T_VALUE = "test_the_consent_value_is_the_runs_own_cap"
T_CROSS = "test_a_paid_run_is_refused_when_the_prior_ledgers_plus_its_cap_exceed_the_consent"
T_FIRST = "test_the_first_runs_ledgers_replay_to_the_analysis_figure"
T_REPLAY = "test_ledger_replay_books_reservations_at_cap_and_fails_closed"
T_BOUND = "test_the_run_is_bounded_by_its_own_cap"
T_INVALID = "test_a_leg_without_the_verifier_bash_or_a_model_is_invalid"
T_TRUST = "test_e1b_reads_the_trust_warning_and_the_trusted_leg_reads_its_own_control"
T_E3P = "test_e3p_answers_from_an_agent_childs_resume_and_its_first_tool_call"
T_GOOD = "test_every_part_answers_in_the_good_world_within_its_caps"
VALID = "    out[\"valid\"] = out[\"agent_setting\"] == E1_AGENT and out[\"bash_tool\"] and out[\"model\"] is not None\n"
GATE = "        if prior[\"used\"] + cap > TOTAL_CAP_USD + 1e-9:\n            ap.error(\"refused: the prior"
T_GUARD = "test_e1s_command_passes_the_guards_read_only_rule_for_the_verifier"
T_CUT = "test_a_bash_call_cut_before_its_tool_result_is_not_a_denial"
T_OPEN = "test_a_run_in_progress_counts_at_its_cap"
PREVIEW = ("            s.overlay = overlay\n            opts = s.preview()          # the options it would connect with: "
           "a refusal may come here too\n        except ValueError as e:         # e.g. a helper that refuses "
           "CLAUDE_CODE_SANDBOXED (sdk/env-channel)\n            raise HelperRefused(type(e).__name__) from e\n")

MUTANTS = [  # (id, mutant, named test, [(anchor, replacement), ...])
    ("G1", "a paid run without the consent env", T_ENV,
     [("    if consent != need:\n", "    if False:\n")]),
    ("G2", "any non-empty consent env accepted", T_ENV,
     [("    if consent != need:\n", "    if not consent:\n")]),
    ("G3", "paid is the default (dry run only on --dry-run)", "test_dry_run_is_the_default_and_spends_nothing",
     [("    if not a.paid:\n        try:\n", "    if a.dry_run:\n        try:\n")]),
    ("G4", "the ledger does not open with the envelope", "test_a_paid_run_logs_the_envelope_first_and_reports",
     [("        ledger.write(envelope_event(probes, today, prior))", "        ledger.write({\"ev\": \"start\"})")]),
    # no C1 ("a probe cap above its envelope accepted": `0 < b <= env` -> `0 < b`): an equivalent mutant, since one
    # probe above its group's envelope is always a group sum above it (C3's check)
    ("C1", "a probe cap of 0, NaN or a string accepted", T_REG,
     [("not math.isfinite(b) or not 0 < b <= env:", "not b <= env:")]),
    ("C2", "no turn limit required", T_REG,
     [("        if isinstance(t, bool) or not isinstance(t, int) or not 0 < t <= 12:\n", "        if False:\n")]),
    ("C3", "the caps of a group may sum above its envelope", "test_group_sums_and_the_total_are_enforced",
     [("        if s > ENVELOPE[g] + 1e-9:\n", "        if False:\n")]),
    ("C4", "the runtime cap ignores the group's envelope", T_CAPS,
     [("        left = min(total - spent, ENVELOPE[p.group] - by[p.group])\n", "        left = total - spent\n")]),
    ("C5", "the runtime cap ignores the run's total", T_CAPS,
     [("        left = min(total - spent, ENVELOPE[p.group] - by[p.group])\n",
       "        left = ENVELOPE[p.group] - by[p.group]\n")]),
    ("C6", "a session's cap not bounded by what the probe has left", "test_a_session_never_gets_more_than_its_probe_has_left",
     [("        b = min(self.cap - self.spent, self.cap * share,", "        b = min(self.cap, self.cap * share,")]),
    ("C7", "no floor: a session may start with almost nothing left", "test_a_session_never_gets_more_than_its_probe_has_left",
     [("        if not b >= MIN_SESSION_USD:\n", "        if not b > 0:\n")]),
    ("U1", "a missing cost counts as $0", "test_an_unreported_cost_fails_closed",
     [("            elif not valid_cost(c):\n", "            elif c is not None and not valid_cost(c):\n"),
      ("                cost = max(self.floor.pop(key, 0.0), float(c))\n",
       "                cost = max(self.floor.pop(key, 0.0), float(c or 0))\n")]),
    ("U2", "an unreported cost does not stop the run", "test_an_unreported_cost_fails_closed",
     [("            row.facts[\"cost_unknown\"], stop = True, \"cost_unknown\"\n",
       "            row.facts[\"cost_unknown\"] = True\n")]),
    ("U3", "after an unreported cost, sessions still start", "test_an_unreported_cost_fails_closed",
     [("        if self.unknown_cost:\n            raise BudgetError(\"%s: a session's cost was not reported: nothing "
       "more starts\" % self.probe.pid)\n        b = min(",
       "        if False:\n            raise BudgetError(\"x\")\n        b = min("),
      ("        if self.unknown_cost:\n            raise BudgetError(\"%s: a session's cost was not reported: nothing "
       "more starts\" % self.probe.pid)\n        super().check(opts)",
       "        super().check(opts)")]),
    ("U4", "a later result lowers an unreported session's booking", "test_an_unreported_cost_fails_closed",
     [("            if key in self.unknown_keys:\n                pass", "            if False:\n                pass")]),
    ("U5", "a session cut short by CapUsed stops the whole run", T_CAPS,
     [("        except CapUsed:\n            fail = \"cap_used\"\n", "")]),
    ("R1", "the report's prompt check is off", "test_render_never_carries_prompt_text_and_lists_every_part",
     [("    if any(frag in flat for frag in prompt_fragments()):\n", "    if False:\n")]),
    ("R2", "E1: a PreToolUse hook's decision read as the rule's", "test_a_hook_decision_or_an_unloaded_stack_leaves_e1_unknown",
     [("    if sum(leg[\"hook_decisions\"].values()):\n", "    if False:\n")]),
    ("R3", "E1c read from permission_denials without the control's calibration",
     "test_a_hook_decision_or_an_unloaded_stack_leaves_e1_unknown",
     [("    f[\"denials_calibrated\"] = calibrated = v.get(\"control\") == \"denied\" and f.get(\"control_denied\") is True\n",
       "    f[\"denials_calibrated\"] = calibrated = True\n")]),
    ("R4", "the CLI's config dir exported (CLAUDE_CONFIG_DIR renames the login's keychain entry)", T_GOOD,
     [("        env = dict({\"XDG_STATE_HOME\": self.state, CEILING_ENV: \"3000\"}, **(env or {}))",
       "        env = dict({\"XDG_STATE_HOME\": self.state, CEILING_ENV: \"3000\", \"CLAUDE_CONFIG_DIR\": "
       "self.cfg.config_dir}, **(env or {}))")]),
    # review round 1 (F1-F5): each fix's mutant puts the old behaviour back, so its proof test fails before the fix
    ("F1", "open_turn books nothing (a second turn stays at the first turn's cost)",
     "test_an_open_turn_counts_at_the_whole_cap",
     [("        if key in self.unknown_keys or key not in self.caps:\n            return\n", "        return\n")]),
    ("F1", "a turn's result may undercut what was reported before (no floor)", "test_an_open_turn_counts_at_the_whole_cap",
     [("                cost = max(self.floor.pop(key, 0.0), float(c))\n", "                cost = float(c)\n")]),
    ("F1", "no open_turn before E2b's second prompt", "test_the_report_and_ledger_of_a_full_run_have_no_prompt_text",
     [("        c.open_turn(s.key)\n        await s.turn(PROMPTS[\"e2_dispatch\"]",
       "        await s.turn(PROMPTS[\"e2_dispatch\"]")]),
    ("F2", "E1's rule legs read without their control's denial", "test_e1_rule_legs_need_a_denied_control",
     [("        elif control is not None and v.get(control) != \"denied\" or part == \"E1c\" and not calibrated:\n",
       "        elif part == \"E1c\" and not calibrated:\n")]),
    ("F3", "the installed helper not checked before the ledger",
     "test_e1_needs_the_v2_helper_installed_and_the_others_do_not",
     [("    if missing := [n for n in need_names if not hasattr(helper, n)]:\n", "    if missing := []:\n")]),
    ("R5", "E2a allow read without the control guard", "test_e2a_needs_a_control_the_rules_do_not_touch",
     [(" or k[\"allow_marker\"] else b[\"allow_marker\"]", " else b[\"allow_marker\"]")]),
    ("R5", "E2a deny read without the control guard", "test_e2a_needs_a_control_the_rules_do_not_touch",
     [(" or not k[\"deny_marker\"] else not b[\"deny_marker\"]", " else not b[\"deny_marker\"]")]),
    ("R5", "E2a addDirs read without the control guard", "test_e2a_needs_a_control_the_rules_do_not_touch",
     [(" or not k[\"read_failed\"] else not b[\"read_failed\"]", " else not b[\"read_failed\"]")]),
    ("F5", "E3c2 answered without a toolUseId", "test_e3c2_needs_a_tool_use_id",
     [(" if resumed and isinstance(tid0, str) and c1 is not None", " if resumed and c1 is not None")]),
    # review round 2
    ("S1", "the resume turn closed by any result (a late one of an earlier turn too)",
     "test_a_late_result_does_not_close_the_resume_turn",
     [("                return at is not None and any(map(is_result, later[at:])) and not agents_running(s.msgs)\n",
       "                return any(map(is_result, later)) and not agents_running(s.msgs)\n")]),
    ("S1", "an unproven session re-booked without a ledger event", "test_a_late_result_does_not_close_the_resume_turn",
     [("        self.ledger({\"ev\": \"reserve\", \"probe\": self.probe.pid, \"session\": key, \"usd\": self.costs[key], "
       "\"unproven\": True})\n", "")]),
    ("S2", "E3c2's reading omits the missing toolUseId", "test_e3c2_needs_a_tool_use_id",
     [("E3c1 unknown, or no toolUseId before the resume\"", "or E3c1 unknown\"")]),
    ("S3", "settle()'s whole-cap booking left out of the ledger",
     "test_a_session_closed_with_an_agent_running_is_rebooked_in_the_ledger",
     [("        if self.costs.get(key) != before:\n", "        if False:\n")]),
    # the second probe set (sdk/probes-e2): the consent value, the cross-run ledger check, the run's own cap
    ("G5", "a partial run accepts the full 2.00 consent", T_VALUE,
     [("    if FULL_SET <= {p.pid for p in probes}:\n        return CONSENT_VALUE\n",
       "    if True:\n        return CONSENT_VALUE\n")]),
    ("G6", "a run with all of E1-E3 needs its caps' sum, not 2.00", T_VALUE,
     [("    if FULL_SET <= {p.pid for p in probes}:\n        return CONSENT_VALUE\n",
       "    if False:\n        return CONSENT_VALUE\n")]),
    ("G7", "the run's cap not passed to run_probes", T_VALUE,
     [("run_probes(probes, cfg, helper, rows, ledger.write, total=cap)",
       "run_probes(probes, cfg, helper, rows, ledger.write)")]),
    ("G8", "run_probes ignores the run's cap (the $2.00 always)", T_BOUND,
     [("    total = TOTAL_CAP_USD if total is None else total\n", "    total = TOTAL_CAP_USD\n")]),
    ("G9", "a run cap outside (0, 2.00] accepted", T_BOUND,
     [("    if isinstance(total, bool) or not isinstance(total, (int, float)) or not 0 < total <= TOTAL_CAP_USD + 1e-9:\n",
       "    if False:\n")]),
    ("X1", "no cross-run refusal", T_CROSS, [(GATE, GATE.replace("    if prior[\"used\"] + cap > TOTAL_CAP_USD + 1e-9:",
                                                                 "    if False:"))]),
    ("X2", "the cross-run check leaves out this run's own cap", T_CROSS,
     [(GATE, GATE.replace("prior[\"used\"] + cap >", "prior[\"used\"] >"))]),
    ("X3", "a session never reported counts $0 (not its cap)", T_FIRST,
     [("    unrep = sum(v for k, v in book.items() if not reported.get(k))\n", "    unrep = 0.0\n")]),
    ("X4", "a result never replaces its session's reservation", T_REPLAY,
     [("            book[key] = float(usd)                      # a result replaces its session's reservation\n",
       "            book[key] = max(book.get(key, 0.0), float(usd))\n")]),
    ("X5", "a ledger line that is not JSON is skipped", T_REPLAY,
     [("            raise LedgerUnreadable(\"%s:%d is not JSON\" % (name, n)) from e\n", "            continue\n")]),
    ("X6", "an event the replay does not know is booked as spend", T_REPLAY,
     [("        if what not in LEDGER_EVENTS:\n", "        if what is None:\n")]),
    ("X7", "the default directory's ledgers ignored when --out points elsewhere",
     "test_the_default_directorys_ledgers_count_when_the_report_goes_elsewhere",
     [("    dirs = [os.path.dirname(base.default_out(today + \"-e\"))] + ([os.path.dirname(out)] if out else [])\n",
       "    dirs = [os.path.dirname(out)] if out else []\n")]),
    ("X8", "an unreadable ledger lets the paid run start at $0 prior", "test_an_unreadable_ledger_refuses_the_paid_run",
     [("            ap.error(\"refused: a ledger in the default or the report directory cannot be replayed, so the "
       "prior \"\n                     \"spend is unknown: %s\" % e)\n",
       "            prior = {\"ledgers\": 0, \"reported\": 0.0, \"unreported\": 0.0, \"used\": 0.0, \"left\": 2.0, \"e\": str(e)}\n")]),
    ("X9", "a cost_unknown booking lowered by a later result", T_REPLAY,
     [("            sticky.add(key)\n", "            pass\n")]),
    ("X10", "the replay's total may fall below the run's own probe_end and end totals", T_REPLAY,
     [("\"used\": max(rep + unrep, sum(ends.values()), end_usd, open_cap)}", "\"used\": rep + unrep}")]),
    # E1': the verifier main thread, the validity gate, the trust split
    ("V1", "an invalid leg read as a measurement", "test_a_blackcat_main_thread_makes_every_e1_leg_invalid",
     [("    if not leg.get(\"valid\"):\n        return \"invalid\"\n",
       "    if False:\n        return \"invalid\"\n")]),
    ("V2", "validity without the agent setting", T_INVALID,
     [(VALID, "    out[\"valid\"] = out[\"bash_tool\"] and out[\"model\"] is not None\n")]),
    ("V3", "validity without Bash in the tools", T_INVALID,
     [(VALID, "    out[\"valid\"] = out[\"agent_setting\"] == E1_AGENT and out[\"model\"] is not None\n")]),
    ("V4", "validity without a recorded model", T_INVALID,
     [(VALID, "    out[\"valid\"] = out[\"agent_setting\"] == E1_AGENT and out[\"bash_tool\"]\n")]),
    ("V5", "an invalid control does not invalidate its rule legs",
     "test_an_invalid_control_makes_its_rule_legs_invalid",
     [("        if lv == \"invalid\" or (control is not None and v.get(control) == \"invalid\"):\n",
       "        if lv == \"invalid\":\n")]),
    ("V6", "E1's main thread without an agent (the first runs' Session(None))", T_GOOD,
     [("                E1_AGENT, host=\"none\", budget_usd=budget,",
       "                None, host=\"none\", budget_usd=budget,")]),
    ("V7", "a cap_used E1 loses the legs it measured", "test_e1_cut_by_its_cap_keeps_what_it_measured",
     [("    except CapUsed:                                     # the legs measured so far still answer\n"
       "        e1_answers(c, v)\n        raise\n", "    except CapUsed:\n        raise\n")]),
    ("V8", "a helper refusing the trust env crashes E1",
     "test_a_helper_that_refuses_the_trust_env_skips_only_the_trusted_legs",
     [("        except ValueError as e:         # e.g. a helper",
       "        except KeyError as e:         # e.g. a helper")]),
    ("T1", "the trust warning not read (a dropped rule reads no)", T_TRUST,
     [("            dropped = a == \"no\" and leg in (\"repo_rule\", \"trusted_repo_rule\") and f.get(leg + \"_trust_warning\")\n",
       "            dropped = False\n")]),
    ("T2", "the trusted repo rule read against the untrusted control", T_TRUST,
     [("           \"E1bt\": (\"trusted_repo_rule\", \"trusted_control\"),",
       "           \"E1bt\": (\"trusted_repo_rule\", \"control\"),")]),
    ("T3", "the trusted legs run without CLAUDE_CODE_SANDBOXED", T_TRUST,
     [("env=dict(TRUST_ENV) if trusted else None", "env=None")]),
    ("T4", "the CLI's stderr not scanned for the trust warning", T_TRUST,
     [("                if TRUST_WARNING in str(line):\n", "                if False:\n")]),
    # E3d's reading, E3' (E3P)
    ("D1", "a refused resume read as unknown (not terminal)", "test_a_refused_resume_reads_terminal_for_e3d",
     [("    if refused and not resumed:\n        return \"terminal\"\n",
       "    if False:\n        return \"terminal\"\n")]),
    ("D2", "a refusal phrase overrides a success:true record", "test_e3d_reading_and_the_refusal_detector",
     [("            refused = RESUME_REFUSED in text and tur.get(\"success\") is not True\n",
       "            refused = RESUME_REFUSED in text\n")]),
    ("P1", "E3c2a answered without a proven, unrefused resume", T_E3P,
     [(" if resumed and not refused and isinstance(tid0, str) \\", " if isinstance(tid0, str) \\")]),
    ("P2", "E3e read from a child's last row, not its first", T_E3P,
     [("            first.setdefault(r[\"agent_id\"], r)\n", "            first[r[\"agent_id\"]] = r\n")]),
    ("P3", "E3e says yes when the meta.json was missing at a first call", T_E3P,
     [("    c.answers[\"E3e\"] = \"no\" if False in at_first else",
       "    c.answers[\"E3e\"] = \"no\" if False in at_first[:0] else")]),
    ("H1", "the hook logger reports meta.json present without looking",
     "test_the_hook_logger_checks_meta_json_where_agent_guard_looks",
     [("    row[\"meta_json\"], row[\"meta_tool_use_id\"] = any(os.path.isfile(p) for p in metas), False\n",
       "    row[\"meta_json\"], row[\"meta_tool_use_id\"] = True, False\n")]),
    ("M1", "the report header names one fixed model", "test_the_report_and_ledger_of_a_full_run_have_no_prompt_text",
     [("cell(meta.get(\"system_cli\")), models), \"\",", "cell(meta.get(\"system_cli\")), MODEL), \"\",")]),
    ("M2", "the sessions' init models not recorded", T_GOOD,
     [("            if getattr(m, \"subtype\", \"\") == \"init\" and isinstance(model, str) and IDENT_RX.fullmatch(model):\n",
       "            if False:\n")]),
    # sdk/probes-e2 review, round 1: each fix's mutant puts the reviewed behaviour back
    ("Q1", "E1's script and marker outside scratch (the guard refuses the verifier's call)", T_GUARD,
     [("    work = os.path.join(cwd, \".claude-work\")\n", "    work = cwd\n")]),
    ("Q2", "E1's script outside scratch: every leg hook_decided under the real read-only guard", T_GOOD,
     [("    work = os.path.join(cwd, \".claude-work\")\n", "    work = cwd\n")]),
    ("Q3", "E1c's stack leg run although the guard can only decide it", T_GOOD,
     [("            if rule == \"stack\" and E1C_NOT_RUN:", "            if False:")]),
    ("Q4", "a call cut before its tool result read as a denial", T_CUT,
     [("    if not leg.get(\"decided\"):\n        return \"undecided\"\n", "    if False:\n        return \"undecided\"\n")]),
    ("Q5", "every attempted call counted as decided", T_CUT,
     [("            \"decided\": any(i in errs or i in den for i in ids),\n", "            \"decided\": bool(ids),\n")]),
    ("Q6", "a run without its end counts only what it booked so far", T_OPEN,
     [("\"used\": max(rep + unrep, sum(ends.values()), end_usd, open_cap)}",
       "\"used\": max(rep + unrep, sum(ends.values()), end_usd)}")]),
    ("Q7", "a finished run still counts at its whole cap", T_OPEN,
     [("            end_usd, open_cap = float(usd), 0.0\n", "            end_usd = float(usd)\n")]),
    ("Q8", "a run in progress invisible to a second start", "test_a_second_run_started_while_one_runs_counts_it_at_its_cap",
     [("            open_cap = float(cap) if valid_cost(cap) else 0.0\n", "            open_cap = 0.0\n")]),
    ("Q9", "no lock around the gate and the envelope", "test_two_starts_are_serialised_by_the_lock",
     [("        fcntl.flock(lock_fd, fcntl.LOCK_EX)\n", "        pass\n")]),
    ("Q10", "the ledger beside an --out report, not in the default directory",
     "test_the_ledger_goes_to_the_default_directory_whatever_out_says",
     [("            ledger = Ledger(os.path.join(ldir, os.path.basename(out).removesuffix(\".md\") + \".ledger.jsonl\"))\n",
       "            ledger = Ledger(out.removesuffix(\".md\") + \".ledger.jsonl\")\n")]),
    ("Q11", "E3c2a's resume proven by a growing transcript alone (no SendMessage call)", "test_e3c2a_needs_a_sendmessage_call",
     [("    resumed = sends > 0 and lines0 is not None", "    resumed = lines0 is not None")]),
    ("Q13", "a denied SendMessage (an error result) counted as a resume", "test_e3c2a_needs_a_sendmessage_call",
     [("            sends = len([i for i, _, parent in calls(s.msgs[n:], \"SendMessage\") if parent is None\n"
       "                         and errs.get(i) is False])\n",
       "            sends = len([i for i, _, parent in calls(s.msgs[n:], \"SendMessage\") if parent is None])\n")]),
    ("Q12", "a helper refusing the trust env in preview() crashes E1",
     "test_a_helper_whose_preview_refuses_the_trust_env_skips_only_the_trusted_legs",
     [(PREVIEW, ("        except ValueError as e:\n            raise HelperRefused(type(e).__name__) from e\n"
                 "        s.overlay = overlay\n        opts = s.preview()\n"))]),
]


def pytest(script: Path, tests: list[str], timeout: float = 300) -> tuple[int | None, str, float]:
    t = time.monotonic()
    env = dict(os.environ, SDK_PROBES_E_SCRIPT=str(script))
    try:
        p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *(TESTS + x for x in tests)],
                           cwd=REPO, env=env, capture_output=True, text=True, timeout=timeout, check=False)
        return p.returncode, p.stdout + p.stderr, round(time.monotonic() - t, 1)
    except subprocess.TimeoutExpired:
        return None, "TIMEOUT", round(time.monotonic() - t, 1)


def copy_pair(d: Path, src: str) -> Path:
    d.mkdir(parents=True)
    shutil.copyfile(BASE, d / "sdk_probes.py")
    (d / "sdk_probes_e.py").write_text(src)
    return d / "sdk_probes_e.py"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--list", action="store_true")
    ap.add_argument("-k", default="")
    ap.add_argument("-j", type=int, default=4)
    ap.add_argument("--out", default="-")
    a = ap.parse_args(argv)
    keys = [k for k in a.k.split(",") if k]
    todo = [m for m in MUTANTS if not keys or m[0] in keys]
    if a.list:
        for mid, what, test, _subs in todo:
            print(f"{mid:<3} {test:<72} {what}")
        return 0
    src = SCRIPT.read_text()
    bad = [(m[0], src.count(old)) for m in todo for old, _ in m[3] if src.count(old) != 1]
    if bad:
        print("anchors that do not match exactly once:", bad)
        return 2
    scratch = Path(tempfile.mkdtemp(prefix="sdk-probes-e-mutations-"))
    lines: list[str] = []
    try:
        names = sorted({m[2] for m in todo})
        rc, out, dt = pytest(copy_pair(scratch / "clean", src), names)
        lines.append(f"BASE  {len(names)} named tests: {'PASS' if rc == 0 else 'FAIL'} ({dt}s)")
        print(lines[-1], flush=True)
        if rc != 0:
            print(out[-3000:])
            return 1

        def one(i: int) -> tuple[bool, str]:
            mid, what, test, subs = todo[i]
            text = src
            for old, new in subs:
                text = text.replace(old, new)
            rc, out, dt = pytest(copy_pair(scratch / f"m{i:03d}", text), [test])
            killed = rc is None or (rc != 0 and any(f"{w} {TESTS}{test}" in out for w in ("FAILED", "ERROR")))
            first = next((ln for ln in out.splitlines() if ln.startswith("E ")), "TIMEOUT" if rc is None else "")
            row = f"{'KILLED' if killed else 'ALIVE '} {mid:<3} {test:<72} {what} [{dt}s] {first[:110]}"
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
