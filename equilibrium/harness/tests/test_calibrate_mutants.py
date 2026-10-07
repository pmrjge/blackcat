"""Seeded bugs of eq_calibrate.py: each mutation, applied to a temp copy, must make its guarding tests fail.

Kept here (not in tests/mutations.py, whose single shared list other parts edit). Always on: every anchor occurs
exactly once in eq_calibrate.py. Opt-in (minutes): EQ_CALIBRATE_MUTANTS=1 runs every mutant (EQ_CALIBRATE_MUTANTS_ONLY=
C53,C54: those only) in a fresh copy of equilibrium/{harness,calibration} with the same interpreter and requires a
non-zero pytest exit.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parent.parent
T = "test_calibrate.py::"

# (id, guarded rule, old, new, test selections)
MUTANTS: list[tuple[str, str, str, str, list[str]]] = [
    ("C01", "one-SE rule uses the SE", '"within_1se": bool(gap <= se + 1e-12)', '"within_1se": bool(gap <= 1e-12)',
     [T + "test_one_se_rule_picks_the_smallest_value_within_one_se"]),
    ("C02", "one-SE SE is the paired difference's", "        se = float(d.std(ddof=1))",
     "        se = float(boot[:, g].std(ddof=1))", [T + "test_one_se_uses_the_paired_difference_se"]),
    ("C03", "one-SE: the smallest qualifying value (ties -> smaller)",
     'choice = next(r["value"] for r in rows if r["within_1se"])',
     'choice = [r["value"] for r in rows if r["within_1se"]][-1]',
     [T + "test_one_se_ties_go_to_the_smaller_value_and_n_one_is_possible"]),
    ("C04", "N* = 1 is not eligible", '"eligible": choice > 1,', '"eligible": True,',
     [T + "test_stage_p_n_star_one_marks_a_class_not_eligible"]),
    ("C05", "N* bootstrap seed eq|nstar", "choice, table = one_se_select(s, M_GRID, SEED_NSTAR)",
     "choice, table = one_se_select(s, M_GRID, SEED_ROUNDS)", [T + "test_score_m_is_the_mean_over_every_subset"]),
    ("C06", "score(m) over all C(9, m) subsets", "subs = list(itertools.combinations(members, m))",
     "subs = [tuple(members[:m])]", [T + "test_score_m_is_the_mean_over_every_subset"]),
    ("C07", "plurality ties: expectation over the tied keys",
     "return math.fsum(grade(k) for k in tied) / len(tied)", "return grade(tied[0])",
     [T + "test_plurality_expected_averages_ties_and_scores_abstention_zero"]),
    ("C08", "verify-then-select: passers only", "vals = [h for p, h in zip(passed, hidden, strict=True) if p]",
     "vals = [h for p, h in zip(passed, hidden, strict=True) if True]",
     [T + "test_checkable_expected_is_the_mean_hidden_score_of_the_passers"]),
    ("C09", "finding sets: verified singles accepted",
     "if c.support >= t or (c.support == 1 and any((f.member, f.payload) in verified for f in c.findings)):",
     "if c.support >= t:", [T + "test_findings_score_threshold_verified_singles_and_false_findings"]),
    ("C10", "finding sets: false findings cost 0.5 / n", "return (len(bugs) - 0.5 * false) / n_seeded",
     "return len(bugs) / n_seeded", [T + "test_findings_score_threshold_verified_singles_and_false_findings"]),
    ("C11", "ES calibration score capped at ln 10", "return -min(e, ES_CAP)", "return -e",
     [T + "test_es_error_and_score_cap"]),
    ("C12", "stop rule: fixed point", "            if canon(seq[r]) == canon(seq[r - 1]):\n                break",
     "            if canon(seq[r]) == canon(seq[r - 1]):\n                pass",
     [T + "test_stop_rule_keeps_round_zero_at_quorum_and_stops_at_a_fixed_point"]),
    ("C13", "stop rule: quorum ceil(tau n) reached", "return bool(c) and max(c.values()) >= q",
     "return bool(c) and max(c.values()) > q",
     [T + "test_stop_rule_keeps_round_zero_at_quorum_and_stops_at_a_fixed_point"]),
    ("C14", "branches: the evidence gate (accepted only)", 'if rec is not None and rec.get("accepted") is True:',
     "if rec is not None:", [T + "test_evidence_gate_keeps_a_rejected_proposal"]),
    ("C15", "LOO variant: none unless some net > 0", "if not net or max(net.values()) <= 0:",
     "if not net or max(net.values()) < 0:", [T + "test_choose_variant_rules"]),
    ("C16", "LOO variant: ties -> rotation", 'VARIANT_PREF = ("rotation", "random", "leader")',
     'VARIANT_PREF = ("random", "rotation", "leader")', [T + "test_choose_variant_rules"]),
    ("C17", "LOO variant compared at R = 2", 'wtl(cls, ((x[v][2], x["none"][2])', 'wtl(cls, ((x[v][0], x["none"][0])',
     [T + "test_stage_p_writes_a_valid_version_with_every_selection"]),
    ("C18", "certainty: 95 % lower bound > 0.5",
     'r["qualifies"] = bool(r["ci95"] is not None and r["ci95"][0] > 0.5)',
     'r["qualifies"] = bool(r["auroc"] is not None and r["auroc"] > 0.5)',
     [T + "test_choose_certainty_takes_the_highest_qualifying_auroc"]),
    ("C19", "certainty: the highest qualifying AUROC", 'r, pts = max(ok, key=lambda x:',
     'r, pts = min(ok, key=lambda x:', [T + "test_choose_certainty_takes_the_highest_qualifying_auroc"]),
    ("C20", "certainty AUROC seed eq|auroc",
     "r = auroc_ci([p[0] for p in pts], [p[1] for p in pts], SEED_AUROC)\n                r[\"signal\"] = s",
     "r = auroc_ci([p[0] for p in pts], [p[1] for p in pts], SEED_NSTAR)\n                r[\"signal\"] = s",
     [T + "test_choose_certainty_takes_the_highest_qualifying_auroc"]),
    ("C21", "q keeps the p cut points", 'cuts = [b["hi"] for b in prev["bins"][:-1]]',
     "cuts = isotonic_cuts([p[0] for p in pts], [p[1] for p in pts])",
     [T + "test_reestimate_keeps_the_signal_and_the_p_cuts"]),
    ("C22", "isotonic: one level per fitted rate", "        if rate(st[i]) == rate(st[i + 1]):",
     "        if False:", [T + "test_choose_certainty_takes_the_highest_qualifying_auroc"]),
    ("C23", "H1/H2: Holm over the primary family", 'adj = ea.holm([per[c][h]["p"] for c, h in tests])',
     'adj = [per[c][h]["p"] for c, h in tests]', [T + "test_stage_q_validates_on_holm_and_the_ship_rule"]),
    ("C24", "confirmed only in E's favour",
     'confirmed = {h: t[h]["p_holm"] <= ALPHA and t[h]["wins"] > t[h]["losses"] for h in ("H1", "H2")}',
     'confirmed = {h: t[h]["p_holm"] <= ALPHA for h in ("H1", "H2")}', [T + "test_stage_q_refuted"]),
    ("C25", "ship rule 2^ratio <= m", 'and t[h]["cost_ratio"]["median"] <= m_ship]', "]",
     [T + "test_stage_q_ship_rule_fails_above_m"]),
    ("C26", "refuted status", "refuted = all(", "refuted = False and all(", [T + "test_stage_q_refuted"]),
    ("C27", "cost-ratio bootstrap seed per contrast", "lo, hi = ea.boot_median_ci(arr, SEED_P1[cname])",
     'lo, hi = ea.boot_median_ci(arr, SEED_P1["E-G"])', [T + "test_cost_ratio_uses_each_contrasts_p1_seed"]),
    ("C28", "route 2 within 1 %", "if rel > ROUTE2_RTOL:", "if rel > 0.05:",
     [T + "test_route2_disagreement_beyond_one_percent_is_refused"]),
    ("C29", "route 2: a fork's parent messages excluded", "            own.pop(k, None)", "            pass",
     [T + "test_transcript_usage_dedupes_streams_and_excludes_fork_parent"]),
    ("C30", "route 2: streamed messages counted once", 'out[str(m["id"])] = m',
     'out[str(m["id"]) + str(len(out))] = m', [T + "test_transcript_usage_dedupes_streams_and_excludes_fork_parent"]),
    ("C31", "freeze: A6 pre-registered", 'if not re.search(r"\\*\\*A6\\b", sec12):', "if False:",
     [T + "test_refuses_a_broken_freeze[no_a6]"]),
    ("C32", "freeze: live ledger = frozen copy",
     "if not live.is_file() or live.read_bytes() != led_frozen.read_bytes():", "if not live.is_file():",
     [T + "test_refuses_a_broken_freeze[ledger_appended]"]),
    ("C33", "freeze: pools verified",
     '        _verify_lines(pf.parent, pf.read_text(encoding="utf-8").splitlines(), f"items/{c}/pool.sha256")\n',
     "", [T + "test_refuses_a_broken_freeze[pool]"]),
    ("C34", "freeze: the stage collected", "if not fa.is_file() or not man.is_file():", "if False:",
     [T + "test_refuses_an_unfrozen_stage"]),
    ("C35", "freeze: the sidecar verified", 'n_files = _verify_lines(eq_root, st.splitlines(), "COMPARE_eq.sha256")',
     "n_files = 1", [T + "test_refuses_a_broken_freeze[sidecar_file]"]),
    ("C36", "chain: version bytes verified", 'if not vp.is_file() or sha256_file(vp) != h.get("sha256"):',
     "if not vp.is_file():", [T + "test_chain_is_append_only_and_verified"]),
    ("C37", "chain: prev_sha256 links", '"prev_sha256": lines[-1]["sha256"] if lines else None,',
     '"prev_sha256": None,', [T + "test_stage_p_writes_a_valid_version_with_every_selection"]),
    ("C38", "caps: tokens ceil2(q90 x 1.25)", "member_tokens = ceil2(q90(toks) * 1.25)",
     "member_tokens = ceil2(q90(toks) * 1.5)", [T + "test_stage_p_caps_usd_and_models"]),
    ("C39", "caps: turns ceil(q90 x 1.25)", "member_turns = math.ceil(q90(turns) * 1.25) if turns else None",
     "member_turns = math.ceil(q90(turns)) if turns else None", [T + "test_stage_p_caps_usd_and_models"]),
    ("C40", "caps: per-run N x member x (1 + rounds) + helpers",
     "run_tokens = None if n is None or rounds is None else n * member_tokens * (1 + rounds) + extra",
     "run_tokens = None if n is None or rounds is None else n * member_tokens + extra",
     [T + "test_stage_p_caps_usd_and_models"]),
    ("C41", "USD per context token (output excluded)", "acc[m][1] += c.ctx", "acc[m][1] += c.ctx + c.out",
     [T + "test_usd_per_mtok_is_per_model"]),
    ("C42", "model id from the transcripts", "        if tp is not None:\n            _, model =",
     "        if False:\n            _, model =", [T + "test_stage_p_writes_a_valid_version_with_every_selection"]),
    ("C43", "validated needs every field", "        if missing:\n            raise CalibrationError(f\"class {c}",
     "        if False:\n            raise CalibrationError(f\"class {c}",
     [T + "test_stage_q_refuses_a_validated_class_with_a_missing_field"]),
    ("C44", "an ineligible class is never primary", "if n is None or n < 3:", "if n is None:",
     [T + "test_stage_q_refuses_an_ineligible_primary"]),
    ("C45", "validation needs route 2", "if validated and not route2_on:", "if False:",
     [T + "test_stage_q_refuses_validation_without_route2"]),
    ("C46", "H4: Holm over 3", 'adj = ea.holm([tests[a]["p"] for a in ("R1", "R3", "ENS")])',
     'adj = [tests[a]["p"] for a in ("R1", "R3", "ENS")]', [T + "test_stage_q_h4_picks_a_confirmed_alternative"]),
    ("C47", "H5: the chosen variant is the first-named arm", "pairs.append((u.score, g))", "pairs.append((g, u.score))",
     [T + "test_h5_sign_test_on_reconciled_items"]),
    ("C48", "RS equivalence merge applied", "return None if k is None else mapping.get(k, k)", "return k",
     [T + "test_rs_equivalence_merge_is_applied"]),
    ("C49", "version number = chain length", '    params["version"] = k\n', '    params["version"] = 1\n',
     [T + "test_chain_is_append_only_and_verified"]),
    ("C50", "certainty for binary classes only", "        for cls in BINARY:\n            us = units.get(cls, [])",
     "        for cls in (*BINARY, \"CR\"):\n            us = units.get(cls, [])",
     [T + "test_certainty_is_chosen_on_p_by_the_lower_bound"]),
    ("C51", "q status of non-primary classes", '        classes[c]["status"] = "not_run"',
     '        classes[c]["status"] = classes[c]["status"]', [T + "test_a_q_rerun_resets_classes_outside_its_primary"]),
    ("C52", "p5 screening refused", 'if any(c.label == "p5" and c.cls == cls for c in st.calls):', "if False:",
     [T + "test_p5_calls_are_refused"]),
    # COMPARE_eq §12 A6 (2026-10-07): p7 branch lines, the candidate status, ratio underflow
    ("C53", "read_stage: p7 branch mediator lines never stand for the arm's own",
     'if r.get("node") is not None or r.get("branch") is not None:', 'if r.get("node") is not None:',
     [T + "test_adapter_skips_mediator_records_of_a_branch"]),
    ("C54", "candidate: member_model_id required (eq_policy.CANDIDATE_REQUIRED)",
     'CANDIDATE_REQUIRED = ("member_type", "member_model_id", "N",', 'CANDIDATE_REQUIRED = ("member_type", "N",',
     [T + "test_candidate_needs_every_runtime_bundle_key"]),
    ("C55", "candidate: N* >= 3 only",
     'return all(e.get(k) is not None for k in CANDIDATE_REQUIRED) and int(e["N"]) >= 3',
     "return all(e.get(k) is not None for k in CANDIDATE_REQUIRED)",
     [T + "test_candidate_needs_every_runtime_bundle_key"]),
    ("C56", "underflow: |ln a - ln b| where the ratio leaves the float range",
     "return abs(math.log(r)) if 0 < r < math.inf else abs(math.log(a) - math.log(b))", "return abs(math.log(r))",
     ["test_underflow.py::test_calibrate_ratio_sites_survive_underflow_and_overflow"]),
]


def test_every_anchor_occurs_once():
    src = (HARNESS / "eq_calibrate.py").read_text()
    bad = [(mid, src.count(old)) for mid, _, old, _, _ in MUTANTS if src.count(old) != 1]
    assert not bad
    assert len({m[0] for m in MUTANTS}) == len(MUTANTS)


@pytest.mark.skipif(os.environ.get("EQ_CALIBRATE_MUTANTS") != "1", reason="opt-in: EQ_CALIBRATE_MUTANTS=1")
def test_every_mutant_is_killed(tmp_path: Path):
    survived = []
    only = [x for x in os.environ.get("EQ_CALIBRATE_MUTANTS_ONLY", "").split(",") if x]  # e.g. C53,C54: a subset
    assert set(only) <= {m[0] for m in MUTANTS}, only
    for mid, what, old, new, sel in MUTANTS:
        if only and mid not in only:
            continue
        root = tmp_path / mid / "equilibrium"
        root.mkdir(parents=True)
        shutil.copytree(HARNESS, root / "harness", ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
        shutil.copytree(HARNESS.parent / "calibration", root / "calibration")
        f = root / "harness" / "eq_calibrate.py"
        f.write_text(f.read_text().replace(old, new))
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider",
                            *[f"harness/tests/{s}" for s in sel]], cwd=root, capture_output=True, text=True,
                           timeout=900, check=False)
        print(f"{mid} {'KILLED' if r.returncode else 'SURVIVED'} {what}")
        if r.returncode == 0:
            survived.append(mid)
    assert not survived
