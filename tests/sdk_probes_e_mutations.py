"""Seeded-mutation proof for tests/sdk_probes_e.py: the consent gate, the caps and the fail-closed cost book (and two
of E1's readings). Each mutant is one or more exact text substitutions in a scratch copy of sdk_probes_e.py
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

MUTANTS = [  # (id, mutant, named test, [(anchor, replacement), ...])
    ("G1", "a paid run without the consent env", T_ENV,
     [("    if consent != CONSENT_VALUE:\n", "    if False:\n")]),
    ("G2", "any non-empty consent env accepted", T_ENV,
     [("    if consent != CONSENT_VALUE:\n", "    if not consent:\n")]),
    ("G3", "paid is the default (dry run only on --dry-run)", "test_dry_run_is_the_default_and_spends_nothing",
     [("    if not a.paid:\n        print_plan", "    if a.dry_run:\n        print_plan")]),
    ("G4", "the ledger does not open with the envelope", "test_a_paid_run_logs_the_envelope_first_and_reports",
     [("    ledger.write(envelope_event(probes, today))\n", "    ledger.write({\"ev\": \"start\"})\n")]),
    # no C1 ("a probe cap above its envelope accepted": `0 < b <= env` -> `0 < b`): an equivalent mutant, since one
    # probe above its group's envelope is always a group sum above it (C3's check)
    ("C1", "a probe cap of 0, NaN or a string accepted", T_REG,
     [("not math.isfinite(b) or not 0 < b <= env:", "not b <= env:")]),
    ("C2", "no turn limit required", T_REG,
     [("        if isinstance(t, bool) or not isinstance(t, int) or not 0 < t <= 12:\n", "        if False:\n")]),
    ("C3", "the caps of a group may sum above its envelope", "test_group_sums_and_the_total_are_enforced",
     [("        if s > ENVELOPE[g] + 1e-9:\n", "        if False:\n")]),
    ("C4", "the runtime cap ignores the group's envelope", T_CAPS,
     [("        left = min(TOTAL_CAP_USD - spent, ENVELOPE[p.group] - by[p.group])\n",
       "        left = TOTAL_CAP_USD - spent\n")]),
    ("C5", "the runtime cap ignores the $2.00 total", T_CAPS,
     [("        left = min(TOTAL_CAP_USD - spent, ENVELOPE[p.group] - by[p.group])\n",
       "        left = ENVELOPE[p.group] - by[p.group]\n")]),
    ("C6", "a session's cap not bounded by what the probe has left", "test_a_session_never_gets_more_than_its_probe_has_left",
     [("        b = min(self.cap - self.spent, self.cap * share,", "        b = min(self.cap, self.cap * share,")]),
    ("C7", "no floor: a session may start with almost nothing left", "test_a_session_never_gets_more_than_its_probe_has_left",
     [("        if not b >= MIN_SESSION_USD:\n", "        if not b > 0:\n")]),
    ("U1", "a missing cost counts as $0", "test_an_unreported_cost_fails_closed",
     [("            elif not valid_cost(c):\n", "            elif c is not None and not valid_cost(c):\n"),
      ("                cost = float(c)\n", "                cost = float(c or 0)\n")]),
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
     [("    calibrated = v.get(\"control\") == \"denied\" and f.get(\"control_denied\") is True\n",
       "    calibrated = True\n")]),
    ("R4", "the CLI's config dir exported (CLAUDE_CONFIG_DIR renames the login's keychain entry)",
     "test_every_part_answers_in_the_good_world_within_its_caps",
     [("        env = dict({\"XDG_STATE_HOME\": self.state, CEILING_ENV: \"3000\"}, **(env or {}))",
       "        env = dict({\"XDG_STATE_HOME\": self.state, CEILING_ENV: \"3000\", \"CLAUDE_CONFIG_DIR\": "
       "self.cfg.config_dir}, **(env or {}))")]),
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
