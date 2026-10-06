"""dot-claude/hooks/eq_policy.py: the runtime Equilibrium's shared grammar, params pin, run bundle and
eq-member predicates (docs-design/RUNTIME_EQUILIBRIUM.md 2.1-2.5, 5, 6.1, 7.5-7.7, 8; contracts.md 3).

Hermetic: pure functions, plus files under tmp_path (params, manifest, symlinks). EQ_POLICY overrides the
module under test (a seeded-bug copy)."""
import base64
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
MOD_PATH = Path(os.environ.get("EQ_POLICY") or HERE.parent / "dot-claude" / "hooks" / "eq_policy.py")


def _load():
    spec = importlib.util.spec_from_file_location("eq_policy_under_test", MOD_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


P = _load()
R = "0123abcd"


# ---------------------------------------------------------------- header grammar
def hdr(*lines, problem="Prove that 1 + 1 = 2."):
    return "\n".join(lines) + "\n---\n" + problem


def test_header_minimal_and_full():
    h = P.parse_header(hdr("eq-class: RS", "eq-mode: manual"))
    assert h == {"run": None, "class": "RS", "mode": "manual", "type": None, "check": None, "segments": [],
                 "problem": "Prove that 1 + 1 = 2."}
    h = P.parse_header("eq-run: %s\n" % R + hdr("eq-class: CP", "eq-mode: auto", "eq-type: python-engineer",
                                                "eq-check: python3 -m pytest -q 'tests/a b.py'",
                                                "eq-segments: src/a.py | src/b.py"))
    assert h["run"] == R and h["class"] == "CP" and h["mode"] == "auto" and h["type"] == "python-engineer"
    assert h["check"] == ["python3", "-m", "pytest", "-q", "tests/a b.py"]
    assert h["segments"] == ["src/a.py", "src/b.py"]


def test_header_problem_kept_verbatim_including_dashes():
    body = "line 1\n---\neq-class: PF\n  indented"
    assert P.parse_header(hdr("eq-class: OE", "eq-mode: manual", problem=body))["problem"] == body


@pytest.mark.parametrize("text, why", [
    (hdr("eq-class: XX", "eq-mode: manual"), "eq-class"),
    (hdr("eq-class: RS", "eq-mode: sometimes"), "eq-mode"),
    (hdr("eq-class: RS"), "eq-mode"),
    (hdr("eq-mode: manual"), "eq-class"),
    (hdr("eq-class: RS", "eq-class: CP", "eq-mode: manual"), "duplicate"),
    (hdr("eq-class: RS", "eq-mode: manual", "eq-colour: red"), "not an eq header"),
    (hdr("eq-class: RS", "", "eq-mode: manual"), "blank line"),
    ("eq-class: RS\neq-mode: manual\nno separator", "not an eq header"),
    ("eq-class: RS\neq-mode: manual", "no `---`"),
    (hdr("eq-class: RS", "eq-mode: manual", problem="   \n"), "empty problem"),
    (hdr("eq-run: XYZ", "eq-class: RS", "eq-mode: manual"), "eq-run"),
    (hdr("eq-class: RS", "eq-mode: manual", "eq-type: blackcat"), "eq-type"),
    (hdr("eq-class: CP", "eq-mode: manual", "eq-check: pytest 'unbalanced"), "eq-check"),
    (hdr("eq-class: CP", "eq-mode: manual", "eq-check:   "), "eq-check"),
    (hdr("eq-class: CR", "eq-mode: manual", "eq-segments: a.py||b.py"), "eq-segments"),
    (hdr("eq-class: CR", "eq-mode: manual", "eq-segments: a.py|a.py"), "twice"),
    (hdr("eq-class: RS", "eq-mode: manual", problem="x\0y"), "NUL"),
    (None, "not text"),
])
def test_header_refusals(text, why):
    with pytest.raises(P.PolicyError) as e:
        P.parse_header(text)
    assert why in str(e.value)


def test_workdir_rule():
    assert P.workdir("CP", []) == "worktree" and P.workdir("CR", ["a"]) == "worktree"
    assert P.workdir("PF", []) == "dir"
    assert P.workdir("RS", ["a.md"]) == "dir" and P.workdir("RS", []) == "none"
    assert P.workdir("DS", []) == "none"


def test_class_tables():
    assert set(P.KIND) == set(P.CLASSES) == set(P.MEMBER_TOOLS) == set(P.WORKDIR)
    for tools in P.MEMBER_TOOLS.values():
        assert "Skill" in tools
        assert not {"Agent", "SendMessage", "WebSearch", "WebFetch"} & set(tools)
    assert P.MEMBER_TOOLS["DS"] == ("Skill",) and "Bash" not in P.MEMBER_TOOLS["RS"]
    assert P.PREDICTED_NEUTRAL == {"RS", "DS", "OE"}
    assert P.FALLBACK["N"] == 5 and P.FALLBACK["rounds"] == 1 and P.FALLBACK["loo_view"] == "rotation"


# ---------------------------------------------------------------- knobs (fail closed)
def test_knob_defaults():
    k = P.knobs({})
    assert k == {"STACK_EQ": 1, "STACK_EQ_MAX_N": 9, "STACK_EQ_MAX_ROUNDS": 2, "STACK_EQ_MAX_CONCURRENT_RUNS": 1,
                 "STACK_EQ_SESSION_RUNS": 3, "STACK_EQ_N": None, "STACK_EQ_ROUNDS": None,
                 "STACK_EQ_CONFIRM": "always", "STACK_EQ_WALL": "auto", "errors": []}


@pytest.mark.parametrize("env, key, want", [
    ({"STACK_EQ": "0"}, "STACK_EQ", 0),
    ({"STACK_EQ": "yes"}, "STACK_EQ", 0),
    ({"STACK_EQ": "2"}, "STACK_EQ", 0),
    ({"STACK_EQ_MAX_N": "lots"}, "STACK_EQ_MAX_N", 1),
    ({"STACK_EQ_MAX_N": "0"}, "STACK_EQ_MAX_N", 1),
    ({"STACK_EQ_MAX_N": "12"}, "STACK_EQ_MAX_N", 9),
    ({"STACK_EQ_MAX_N": "3"}, "STACK_EQ_MAX_N", 3),
    ({"STACK_EQ_MAX_ROUNDS": "-1"}, "STACK_EQ_MAX_ROUNDS", 0),
    ({"STACK_EQ_MAX_ROUNDS": "5"}, "STACK_EQ_MAX_ROUNDS", 2),
    ({"STACK_EQ_SESSION_RUNS": "many"}, "STACK_EQ_SESSION_RUNS", 0),
    ({"STACK_EQ_CONFIRM": "never"}, "STACK_EQ_CONFIRM", "always"),
    ({"STACK_EQ_CONFIRM": "over-cap"}, "STACK_EQ_CONFIRM", "over-cap"),
    ({"STACK_EQ_WALL": "off"}, "STACK_EQ_WALL", "required"),
    ({"STACK_EQ_WALL": "sandbox"}, "STACK_EQ_WALL", "sandbox"),
    ({"STACK_EQ_N": "x"}, "STACK_EQ_N", 1),
    ({"STACK_EQ_N": "15"}, "STACK_EQ_N", 9),
    ({"STACK_EQ_MAX_N": "4", "STACK_EQ_N": "7"}, "STACK_EQ_N", 4),
    ({"STACK_EQ_ROUNDS": "bad"}, "STACK_EQ_ROUNDS", 0),
])
def test_knobs_fail_closed(env, key, want):
    k = P.knobs(env)
    assert k[key] == want


@pytest.mark.parametrize("env", [{"STACK_EQ": "yes"}, {"STACK_EQ_MAX_N": "12"}, {"STACK_EQ_WALL": "off"},
                                 {"STACK_EQ_CONFIRM": "never"}, {"STACK_EQ_N": "x"}])
def test_knob_errors_reported(env):
    assert P.knobs(env)["errors"]


# ---------------------------------------------------------------- params
def entry(status="not_run", **kw):
    e = {k: None for k in P.CLASS_KEYS}
    e["status"] = status
    e.update(kw)
    return e


def validated_entry(**kw):
    e = entry("validated", member_type="mathematician", member_model_id="claude-opus-4-1-20250805",
              agent_file_sha256="a" * 64, N=5, rounds=1, view="lens", loo_view="rotation", reducer="R0", tau=0.6,
              t=2, caps={"member_tokens": 100000, "member_turns": 50, "run_tokens": 1000000},
              usd_per_mtok=3.0, cost_ratio={"median": 1.5, "ci95": [1.1, 1.9]},
              effect={"wins": 10, "losses": 2}, certainty=None,
              pool={"name": "PF-pool", "sha256": "b" * 64, "description": "lean proofs"})
    e.update(kw)
    return e


def params(**classes):
    return {"schema": "eqparams.v1", "version": 1, "created_utc": "2026-10-06T00:00:00Z", "provenance": {},
            "classes": {c: classes.get(c, entry()) for c in P.CLASSES}}


def write_pinned(tmp_path, obj, sha=None, raw=None):
    raw = raw if raw is not None else json.dumps(obj).encode()
    pp, mp = tmp_path / "eq_params.json", tmp_path / ".stack-manifest.json"
    pp.write_bytes(raw)
    mp.write_text(json.dumps({"eq_runtime": {"params_sha256": sha or hashlib.sha256(raw).hexdigest()}}))
    return str(pp), str(mp)


def test_params_shipped_shape_validates():
    assert P.validate_params(params()) == []
    assert P.validate_params(params(PF=validated_entry())) == []


@pytest.mark.parametrize("mutate, why", [
    (lambda o: o.update(extra=1), "top-level"),
    (lambda o: o.update(schema="eqparams.v2"), "schema"),
    (lambda o: o.update(version=0), "version"),
    (lambda o: o.update(version=True), "version"),
    (lambda o: o["classes"].pop("OE"), "classes"),
    (lambda o: o["classes"]["PF"].pop("pool"), "keys"),
    (lambda o: o["classes"]["PF"].update(status="maybe"), "status"),
    (lambda o: o["classes"]["PF"].update(status=None), "status is required"),
    (lambda o: o["classes"]["PF"].update(N=12), "N must"),
    (lambda o: o["classes"]["PF"].update(N=True), "N must"),
    (lambda o: o["classes"]["PF"].update(view="spiral"), "view"),
    (lambda o: o["classes"]["PF"].update(loo_view="all"), "loo_view"),
    (lambda o: o["classes"]["PF"].update(member_type="blackcat"), "member_type"),
    (lambda o: o["classes"]["PF"].update(tau=1.5), "tau"),
    (lambda o: o["classes"]["PF"].update(caps={"member_tokens": 1}), "caps"),
    (lambda o: o["classes"]["PF"].update(caps={"member_tokens": 1, "member_turns": 0, "run_tokens": 1}), "caps"),
])
def test_params_schema_refusals(mutate, why):
    o = params()
    mutate(o)
    errs = P.validate_params(o)
    assert errs and any(why in e for e in errs), errs


def test_validated_entry_needs_every_field_but_certainty():
    o = params(CP=validated_entry())
    assert P.validate_params(o) == []
    o["classes"]["CP"]["certainty"] = None
    assert P.validate_params(o) == []
    for key in P.CLASS_KEYS:
        if key in ("status", "certainty"):
            continue
        bad = copy.deepcopy(o)
        bad["classes"]["CP"][key] = None
        assert any("null in a validated entry" in e for e in P.validate_params(bad)), key


def test_load_params_ok_and_sha_mismatch(tmp_path):
    obj = params(PF=validated_entry())
    pp, mp = write_pinned(tmp_path, obj)
    got, sha, why = P.load_params(pp, mp)
    assert why is None and got == obj and sha == hashlib.sha256(Path(pp).read_bytes()).hexdigest()
    pp, mp = write_pinned(tmp_path, obj, sha="c" * 64)
    got, sha, why = P.load_params(pp, mp)
    assert got is None and "differs" in why and sha


@pytest.mark.parametrize("case", ["no_manifest_key", "schema", "not_json", "missing", "symlink", "manifest_garbage"])
def test_load_params_failures_mean_not_run(tmp_path, case):
    obj = params()
    pp, mp = write_pinned(tmp_path, obj)
    if case == "no_manifest_key":
        Path(mp).write_text(json.dumps({"eq_runtime": {}}))
    elif case == "schema":
        bad = params()
        bad["classes"]["PF"]["status"] = "nope"
        pp, mp = write_pinned(tmp_path, bad)
    elif case == "not_json":
        pp, mp = write_pinned(tmp_path, None, raw=b"{not json")
    elif case == "missing":
        os.unlink(pp)
    elif case == "symlink":
        real = tmp_path / "real.json"
        os.rename(pp, real)
        os.symlink(real, pp)
    elif case == "manifest_garbage":
        Path(mp).write_text("[1, 2")
    got, _sha, why = P.load_params(pp, mp)
    assert got is None and why
    b = P.resolve("PF", got, P.knobs({}), mode="manual")
    assert b["validated"] is False and b["status_reason"] == "no_calibration"


# ---------------------------------------------------------------- resolve: labels, clamps, fallbacks, consent
def test_fallback_bundle_unvalidated():
    b = P.resolve("CR", params(), P.knobs({}), mode="manual", fallback_caps={"member_tokens": 1000, "member_turns": 7})
    assert b["validated"] is False and b["status_reason"] == "class_not_validated"
    assert b["status_reasons"] == ["class_not_validated", "manual"]
    assert (b["N"], b["rounds"], b["loo_view"], b["view"], b["reducer"]) == (5, 1, "rotation", "kcover", "R0")
    assert b["member_type"] == "code-reviewer" and b["member_model_id"] is None and b["member_model"] is None
    assert b["caps"] == {"member_tokens": 1000, "member_turns": 7, "run_tokens": 1000 * 5 * 2}
    assert b["consent_required"] is True and b["auto_allowed"] is False
    assert b["estimate"]["tokens_worst"] == 10000 and b["estimate"]["usd_worst"] is None


def test_no_params_is_no_calibration():
    b = P.resolve("RS", None, P.knobs({}), mode="manual")
    assert b["status_reason"] == "no_calibration" and b["predicted_neutral"] and b["warnings"]
    assert b["caps"]["member_tokens"] == P.FALLBACK_MEMBER_CAPS["member_tokens"]


def test_validated_auto_bundle_is_exact():
    p = params(PF=validated_entry())
    b = P.resolve("PF", p, P.knobs({}), mode="auto")
    assert b["validated"] is True and b["status_reason"] is None
    assert b["member_model_id"] == "claude-opus-4-1-20250805" and b["member_model"] == "opus"
    assert b["caps"]["run_tokens"] == 1000000 and b["N"] == 5
    assert b["estimate"]["usd_worst"] == 3.0 and b["consent_required"] is True   # CONFIRM=always


def test_auto_refused_unless_validated():
    with pytest.raises(P.PolicyError):
        P.resolve("PF", params(), P.knobs({}), mode="auto")
    with pytest.raises(P.PolicyError):
        P.resolve("PF", None, P.knobs({}), mode="auto")
    with pytest.raises(P.PolicyError):          # capped: manual only
        P.resolve("PF", params(PF=validated_entry(N=7)), P.knobs({"STACK_EQ_MAX_N": "5"}), mode="auto")
    with pytest.raises(P.PolicyError):          # override: manual only
        P.resolve("PF", params(PF=validated_entry()), P.knobs({"STACK_EQ_N": "3"}), mode="auto")
    with pytest.raises(P.PolicyError):          # STACK_EQ=0
        P.resolve("PF", params(PF=validated_entry()), P.knobs({"STACK_EQ": "0"}), mode="manual")


def test_caps_clamp_and_label():
    p = params(PF=validated_entry(N=7, rounds=2))
    b = P.resolve("PF", p, P.knobs({"STACK_EQ_MAX_N": "5", "STACK_EQ_MAX_ROUNDS": "1"}), mode="manual")
    assert (b["N"], b["rounds"]) == (5, 1)
    assert b["validated"] is False and b["status_reason"] == "n_or_rounds_capped"
    assert b["caps"]["run_tokens"] == 100000 * 5 * 2


def test_override_label_and_cap():
    p = params(PF=validated_entry())
    b = P.resolve("PF", p, P.knobs({"STACK_EQ_N": "9", "STACK_EQ_MAX_N": "6"}), mode="manual")
    assert b["N"] == 6 and b["status_reason"] == "override"
    b = P.resolve("PF", p, P.knobs({"STACK_EQ_ROUNDS": "0"}), mode="manual")
    assert b["rounds"] == 0 and b["status_reason"] == "override"
    b = P.resolve("PF", p, P.knobs({}), mode="manual", eq_type="proof-checker")
    assert b["member_type"] == "proof-checker" and b["status_reason"] == "override" and b["member_model_id"] is None


def test_manual_of_validated_is_labelled_manual():
    b = P.resolve("PF", params(PF=validated_entry()), P.knobs({}), mode="manual")
    assert b["validated"] is False and b["status_reason"] == "manual" and b["consent_required"]


@pytest.mark.parametrize("confirm, runs, session_runs, want", [
    ("always", "3", 0, True),
    ("over-cap", "3", 0, False),
    ("over-cap", "3", 2, False),
    ("over-cap", "3", 3, True),       # past the session allowance
    ("over-cap", "0", 0, True),
])
def test_consent_matrix_validated_auto(confirm, runs, session_runs, want):
    k = P.knobs({"STACK_EQ_CONFIRM": confirm, "STACK_EQ_SESSION_RUNS": runs})
    b = P.resolve("PF", params(PF=validated_entry()), k, mode="auto", session_runs=session_runs)
    assert b["consent_required"] is want


def test_consent_over_per_run_cap():
    # worst case above the calibrated per-run cap (run_tokens smaller than one round at the member cap)
    p = params(PF=validated_entry(caps={"member_tokens": 100000, "member_turns": 5, "run_tokens": 10}))
    b = P.resolve("PF", p, P.knobs({"STACK_EQ_CONFIRM": "over-cap"}), mode="auto")
    assert b["validated"] is True
    b2 = dict(b)
    est = P.estimate(b2)
    assert est["tokens_worst"] == 10
    # the estimate equals the cap here, so no consent; a cap the estimate exceeds asks
    assert b["consent_required"] is False
    orig = P.estimate
    try:
        P.estimate = lambda bb: dict(orig(bb), tokens_worst=bb["caps"]["run_tokens"] + 1)
        b = P.resolve("PF", p, P.knobs({"STACK_EQ_CONFIRM": "over-cap"}), mode="auto")
        assert b["consent_required"] is True
    finally:
        P.estimate = orig


def test_unvalidated_always_consents_even_over_cap_mode():
    b = P.resolve("CP", params(), P.knobs({"STACK_EQ_CONFIRM": "over-cap"}), mode="manual")
    assert b["consent_required"] is True


def test_model_drift_label():
    assert P.final_label(True, None, "claude-opus-x", ["claude-opus-x", "claude-opus-x"]) == (True, None)
    assert P.final_label(True, None, "claude-opus-x", ["claude-opus-x", "claude-sonnet-y"]) == (False, "model_drift")
    assert P.final_label(True, None, "claude-opus-x", [None]) == (False, "model_drift")
    assert P.final_label(True, None, "claude-opus-x", []) == (False, "model_drift")
    assert P.final_label(False, "manual", "x", ["x"]) == (False, "manual")


def test_w3_level():
    assert P.w3_level("auto", True, "checkable") == "container"
    assert P.w3_level("auto", False, "checkable") == "sandbox"
    assert P.w3_level("sandbox", True, "checkable") == "sandbox"
    assert P.w3_level("required", False, "discrete") == "sandbox"
    with pytest.raises(P.PolicyError):
        P.w3_level("required", False, "checkable")


# ---------------------------------------------------------------- CLI grammar, tickets, consent
@pytest.mark.parametrize("args, want", [
    ([], {"sub": "help"}),
    (["--help"], {"sub": "help"}),
    (["plan", "--run", R], {"sub": "plan", "run": R, "round": None}),
    (["reduce", "--round", "0", "--run", R], {"sub": "reduce", "run": R, "round": 0}),
    (["view", "--run", R, "--round", "1"], {"sub": "view", "round": 1}),
    (["start", "--run", R, "--headless", "--consent-file", "/tmp/c.json"],
     {"sub": "start", "headless": True, "consent_file": "/tmp/c.json"}),
])
def test_parse_cli_ok(args, want):
    p = P.parse_cli(args)
    for k, v in want.items():
        assert p[k] == v


@pytest.mark.parametrize("args", [
    ["plan"], ["plan", "--run", "XYZ"], ["plan", "--run", R, "--round", "1"], ["reduce", "--run", R],
    ["view", "--run", R, "--round", "0"], ["plan", "--run", R, "--run", R], ["plan", "--run=" + R],
    ["exec", "--run", R], ["start", "--run", R, "--headless"], ["start", "--run", R, "--consent-file", "/x"],
    ["start", "--run", R, "--headless", "--consent-file", "rel.json"], ["help", "plan"],
    ["result", "--run", R, "--", "x"], ["prepare-check", "--run", R, "--round", "10"],
    ["status", "--run", R, "--headless"], [1, 2],
])
def test_parse_cli_refusals(args):
    with pytest.raises(P.PolicyError):
        P.parse_cli(args)


def test_parse_check_cli():
    assert P.parse_check_cli(["--run", R, "--cand", "3"]) == {"run": R, "cand": 3}
    assert P.parse_check_cli(["--cand", "1", "--run", R]) == {"run": R, "cand": 1}
    for bad in (["--run", R], ["--run", R, "--cand", "0"], ["--run", R, "--cand", "10"],
                ["--run", R, "--run", R], ["--run", R, "--cand", "1", "--x"], ["--cand", "1", "--cand", "2"]):
        with pytest.raises(P.PolicyError):
            P.parse_check_cli(bad)


def test_ticket_name_is_argv_hash():
    a = ["plan", "--run", R]
    blob = json.dumps(a, separators=(",", ":"), ensure_ascii=True).encode()
    assert P.ticket_name(a) == hashlib.sha256(blob).hexdigest() + ".json"
    assert P.ticket_name(a) != P.ticket_name(["plan", "--run", "0123abce"])


def test_consent_tokens_and_paths():
    assert P.consent_token(R) == "Run eq:" + R and P.consent_token(R, "remove") == "Remove eq:" + R
    env = {"XDG_STATE_HOME": "/s"}
    assert P.consent_path(env, "sid/1", R) == "/s/claude-agent-stack/sid_1/eq/consent/%s.json" % R
    assert P.consent_path(env, "sid", R, "remove").endswith("/%s-remove.json" % R)
    assert P.CONSENT_RE.search("ok: Run eq:%s (est. 1M)" % R).groups() == ("Run", R)
    assert P.CONSENT_RE.search("Run eq:%s0" % R) is None
    assert P.consent_ok({"token": "Run eq:" + R, "answer": "Run eq:%s (est)" % R, "source": "ask"}, R)
    assert not P.consent_ok({"token": "Run eq:" + R, "answer": "Cancel", "source": "ask"}, R)
    assert not P.consent_ok({"token": "Run eq:" + R, "answer": "Run eq:" + R, "source": "relay"}, R)
    with pytest.raises(P.PolicyError):
        P.consent_token("bad")


def test_store_and_find_run(tmp_path):
    env = {"XDG_STATE_HOME": str(tmp_path)}
    d = P.store_dir(env, "s-1", R)
    with pytest.raises(P.PolicyError):
        P.find_run(env, R)
    os.makedirs(d)
    assert P.find_run(env, R) == d
    os.makedirs(P.store_dir(env, "s-2", R))
    with pytest.raises(P.PolicyError):
        P.find_run(env, R)                      # two sessions: ambiguous


def test_find_run_ignores_symlinked_store(tmp_path):
    env = {"XDG_STATE_HOME": str(tmp_path)}
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    os.makedirs(os.path.join(P.state_root(env), "s-1", "eq"))
    os.symlink(elsewhere, P.store_dir(env, "s-1", R))
    with pytest.raises(P.PolicyError):
        P.find_run(env, R)


def test_member_tokens():
    assert P.member_token_re.match("eq %s m3/5" % R).groups() == (R, "3", "5")
    assert P.reconcile_token_re.match("eq %s r1 m2" % R).groups() == (R, "1", "2")
    assert not P.member_token_re.match("eq %s m3/5 please also" % R)


def test_write_json_atomic_mode_and_symlink(tmp_path):
    p = tmp_path / "x.json"
    P.write_json_atomic(str(p), {"a": 1})
    assert json.loads(p.read_text()) == {"a": 1} and (p.stat().st_mode & 0o777) == 0o600
    victim = tmp_path / "victim"
    victim.write_text("keep")
    link = tmp_path / "l.json"
    os.symlink(victim, link)
    P.write_json_atomic(str(link), {"b": 2})          # replaces the link, never writes through it
    assert victim.read_text() == "keep" and not link.is_symlink()
    assert P.read_json(str(link)) == {"b": 2}
    os.unlink(link)
    os.symlink(victim, link)
    assert P.read_json(str(link)) is None             # O_NOFOLLOW read


# ---------------------------------------------------------------- trailer
def test_trailer_roundtrip_and_forgeries():
    line = P.render_check_trailer(R, 2, 0, 0, False, b"ok\n")
    t = P.parse_check_trailer(line + "\n")
    assert t["run"] == R and t["cand"] == 2 and t["exit"] == 0 and base64.b64decode(t["tail_b64"]) == b"ok\n"
    assert P.parse_check_trailer(line) is not None
    assert P.parse_check_trailer(("x\n" + line).encode()) is None          # not the only line
    assert P.parse_check_trailer(line + "\n" + line) is None
    assert P.parse_check_trailer(" " + line) is None
    assert P.parse_check_trailer(line + "\r\n") is None
    obj = json.loads(line[len("EQCHECK "):])
    for k, v in (("extra", 1), ("exit", "0"), ("timed_out", 0), ("cand", 0), ("run", "XX"), ("tail_b64", "!!")):
        o = dict(obj)
        o[k] = v
        assert P.parse_check_trailer("EQCHECK " + json.dumps(o)) is None, k
    o = dict(obj, exit=None)                                               # exit null but not timed out
    assert P.parse_check_trailer("EQCHECK " + json.dumps(o)) is None
    o = dict(obj, exit=None, timed_out=True)
    assert P.parse_check_trailer("EQCHECK " + json.dumps(o)) is not None
    assert P.parse_check_trailer(b"\xff\xfe") is None


# ---------------------------------------------------------------- member git
@pytest.mark.parametrize("cmd", [
    "git status", "git status --porcelain -z", "git -P status", "git --no-pager diff", "git diff --stat",
    "git diff --cached", "git diff -- src/a.py", "git log", "git log --oneline -n 5", "git log -3 HEAD",
    "git log HEAD~3..HEAD --stat", "git show", "git show HEAD^", "git show HEAD:src/a.py", "git ls-files",
    "git ls-files -o --exclude-standard", "/usr/bin/git status", "git log -- src", "git show --stat HEAD~2",
])
def test_member_git_allowed(cmd):
    assert P.member_git_allowed(cmd.split()) is None


@pytest.mark.parametrize("cmd", [
    "git commit -am x", "git merge main", "git stash", "git stash list", "git worktree list", "git branch -a",
    "git checkout main", "git switch -c x", "git log --all", "git log --branches", "git log --remotes=origin",
    "git log main", "git log --tags", "git log -g", "git log --reflog", "git show main:src/a.py",
    "git show origin/eq-m2", "git diff main", "git diff HEAD", "git diff eq-m2 -- x", "git diff --no-index a b", "git diff --no-index -- /etc/hosts x",
    "git diff --output=/tmp/x", "git -C ../m2 status", "git -c core.pager=sh status", "git --git-dir=/x log",
    "git --work-tree=/x diff", "git", "git rev-parse --all", "git grep secret eq-m2", "git ls-files --with-tree=main",
    "git log --glob=refs/*", "git fetch", "git push", "git cat-file -p eq-m2", "git log --decorate=full",
])
def test_member_git_denied(cmd):
    assert P.member_git_allowed(cmd.split()), cmd


def test_member_git_non_git_is_none():
    assert P.member_git_allowed(["ls", "-la"]) is None and P.member_git_allowed([]) is None


# ---------------------------------------------------------------- member paths
@pytest.fixture()
def world(tmp_path):
    cfg = tmp_path / "cfg"
    st = tmp_path / "state"
    proj = tmp_path / "proj"
    for d in (cfg / "projects" / "p" / "subagents", st / "s1" / "eq" / R, proj / "src"):
        d.mkdir(parents=True)
    eqd = proj / ".claude-work" / "eq" / R
    m = {i: eqd / ("m%d" % i) for i in (1, 2)}
    for d in m.values():
        d.mkdir(parents=True)
    (eqd / "checks" / "c1").mkdir(parents=True)
    wt = {i: proj / ".claude" / "worktrees" / ("eq-m%d" % i) for i in (1, 2)}
    for d in wt.values():
        d.mkdir(parents=True)
    (m[2] / "secret.md").write_text("m2 answer")
    (wt[2] / "a.py").write_text("m2 code")
    kw = dict(config_dir=str(cfg), state_root=str(st), project_root=str(proj), run=R, member=1,
              member_dirs={str(i): str(d) for i, d in m.items()},
              member_worktrees={i: str(d) for i, d in wt.items()})
    return {"cfg": cfg, "st": st, "proj": proj, "m": m, "wt": wt, "eqd": eqd, "kw": kw}


def test_member_path_allowed(world):
    kw = world["kw"]
    for p in (world["m"][1] / "notes.md", world["m"][1], world["proj"] / "src" / "a.py", world["wt"][1] / "x.py",
              world["proj"] / "README.md"):
        assert P.member_path_denied(str(p), **kw) is None, p


def test_member_path_denied_rows(world):
    kw = world["kw"]
    for p in (world["cfg"] / "projects" / "p" / "subagents" / "agent-x.jsonl", world["cfg"] / "projects",
              world["st"] / "s1" / "eq" / R / "plan.json", world["st"] / "s1" / "reports" / "x.md",
              world["m"][2] / "secret.md", world["m"][2], world["eqd"] / "checks" / "c1" / "x",
              world["eqd"] / "selected.patch", world["eqd"], world["proj"] / ".claude-work" / "eq" / "ffffffff" / "m1",
              world["wt"][2] / "a.py", world["wt"][2]):
        assert P.member_path_denied(str(p), **kw), p


def test_member_path_dotdot_and_relative(world):
    kw = world["kw"]
    sneaky = str(world["m"][1]) + "/../m2/secret.md"
    assert P.member_path_denied(sneaky, **kw)
    assert P.member_path_denied("../m2/secret.md", cwd=str(world["m"][1]), **kw)
    assert P.member_path_denied("notes.md", **kw)                         # relative without cwd
    assert P.member_path_denied("notes.md", cwd=str(world["m"][1]), **kw) is None
    up = str(world["wt"][1]) + "/../eq-m2/a.py"
    assert P.member_path_denied(up, **kw)


def test_member_path_symlink_tricks(world):
    kw = world["kw"]
    link = world["m"][1] / "peek"
    os.symlink(world["m"][2], link)                                       # own dir -> sibling dir
    assert P.member_path_denied(str(link / "secret.md"), **kw)
    link2 = world["proj"] / "src" / "store"
    os.symlink(world["st"], link2)                                        # project file -> the store
    assert P.member_path_denied(str(link2 / "s1"), **kw)
    link3 = world["wt"][1] / "sib"
    os.symlink(world["wt"][2] / "a.py", link3)
    assert P.member_path_denied(str(link3), **kw)


def test_member_path_case_variant(world):
    kw = world["kw"]
    p = str(world["proj"]) + "/.CLAUDE-WORK/EQ/%s/M2/secret.md" % R
    assert P.member_path_denied(p, **kw)


def test_member_path_recursive_search(world):
    kw = world["kw"]
    assert P.member_path_denied(str(world["proj"]), recursive=True, **kw)    # contains the eq area and m2's worktree
    assert P.member_path_denied(str(world["proj"]), **kw) is None
    assert P.member_path_denied(str(world["m"][1]), recursive=True, **kw) is None
    assert P.member_path_denied(str(world["proj"] / "src"), recursive=True, **kw) is None


# ---------------------------------------------------------------- plan-time path checks
def test_settings_denied(tmp_path):
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    (home / ".ssh" / "id_ed25519").write_text("k")
    proj = home / "proj"
    proj.mkdir()
    (proj / ".env").write_text("X=1")
    (proj / "ok.py").write_text("x")
    cfg = home / ".claude"
    st = home / ".local" / "state" / "claude-agent-stack"
    settings = {"sandbox": {"filesystem": {"denyRead": [str(cfg) + "/**/stack.env", "~/.config/gh/hosts.yml"]}},
                "permissions": {"deny": ["Read(**/.env)", "Read(~/.aws/**)", "Bash(rm *)", "Read(//%s/secret/**)"
                                         % str(proj).lstrip("/")]}}
    kw = dict(home=str(home), config_dir=str(cfg), state_root=str(st))
    assert P.settings_denied(str(proj / "ok.py"), settings, **kw) is None
    assert P.settings_denied(str(home / ".ssh" / "id_ed25519"), settings, **kw)
    assert P.settings_denied(str(proj / ".env"), settings, **kw)
    assert P.settings_denied(str(proj / "secret" / "a.txt"), settings, **kw)
    assert P.settings_denied(str(home), settings, **kw)
    assert P.settings_denied(str(cfg / "hooks" / "x.py"), settings, **kw)
    assert P.settings_denied(str(st / "s" / "eq"), settings, **kw)
    link = proj / "k"
    os.symlink(home / ".ssh" / "id_ed25519", link)
    assert P.settings_denied(str(link), settings, **kw)
    assert P.under_root(str(proj / "ok.py"), str(proj)) and not P.under_root(str(link), str(proj))
