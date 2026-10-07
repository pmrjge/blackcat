"""The equilibrium runtime's calibration pin (RUNTIME_EQUILIBRIUM.md §7.5-§7.6).

dot-config/dot-claude/hooks/eq_params.json is a byte copy of dot-config/dot-equilibrium/calibration/params.json (the
latest version written by dot-config/dot-equilibrium/harness/eq_calibrate.py), whose sha256 is the params.json.sha256
sidecar and the last history line; it validates against dot-config/dot-equilibrium/calibration/params.schema.json
(eqparams.v1). Until a calibration validates a class,
every class is not_run (nothing is auto-routed).

Run: ~/.claude/venvs/tools/bin/python -m pytest -q tests/test_eq_params_pin.py   (stdlib + pytest + jsonschema)
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parent.parent
CAL = ROOT / "dot-config" / "dot-equilibrium" / "calibration"
HOOK = ROOT / "dot-config" / "dot-claude" / "hooks" / "eq_params.json"
CLASSES = ("PF", "CP", "CR", "RS", "ES", "DS", "OE")
CLASS_KEYS = {"status", "member_type", "member_model_id", "agent_file_sha256", "N", "rounds", "view", "loo_view",
              "reducer", "tau", "t", "caps", "usd_per_mtok", "cost_ratio", "effect", "certainty", "pool"}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def schema() -> dict:
    s = json.loads((CAL / "params.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(s)
    return s


def history() -> list[dict]:
    return [json.loads(ln) for ln in (CAL / "params.history.jsonl").read_text(encoding="utf-8").splitlines()
            if ln.strip()]


def test_hook_copy_equals_params_and_sidecar():
    side = (CAL / "params.json.sha256").read_text(encoding="utf-8").split()
    assert side[1:] == ["params.json"]
    assert sha(HOOK) == sha(CAL / "params.json") == side[0]
    assert HOOK.read_bytes() == (CAL / "params.json").read_bytes()


def test_params_is_the_latest_history_version_and_the_chain_links():
    lines = history()
    assert lines, "params.history.jsonl is empty"
    prev = None
    for i, h in enumerate(lines):
        assert set(h) == {"version", "created_utc", "sha256", "prev_sha256", "stages", "amendment", "reason"}
        assert h["version"] == i
        assert h["prev_sha256"] == prev
        assert sha(CAL / f"params.v{i}.json") == h["sha256"]
        prev = h["sha256"]
    assert sha(CAL / "params.json") == prev
    assert json.loads((CAL / "params.json").read_text(encoding="utf-8"))["version"] == lines[-1]["version"]


def test_hook_copy_validates_against_the_schema():
    jsonschema.Draft202012Validator(schema()).validate(json.loads(HOOK.read_text(encoding="utf-8")))


def test_every_version_validates_and_has_the_pinned_shape():
    v = jsonschema.Draft202012Validator(schema())
    for h in history():
        p = json.loads((CAL / f"params.v{h['version']}.json").read_text(encoding="utf-8"))
        v.validate(p)
        assert p["schema"] == "eqparams.v1"
        assert set(p["classes"]) == set(CLASSES)
        for c in CLASSES:
            assert set(p["classes"][c]) == CLASS_KEYS


def test_version_zero_is_no_calibration():
    p = json.loads((CAL / "params.v0.json").read_text(encoding="utf-8"))
    assert p["version"] == 0
    for c in CLASSES:
        e = p["classes"][c]
        assert e["status"] == "not_run"
        assert all(e[k] is None for k in CLASS_KEYS - {"status"})
    assert p["provenance"]["stages"] == []
    assert "no calibration" in p["provenance"]["note"]
    assert history()[0]["reason"] == "no calibration"


def validated_entry() -> dict:
    return {"status": "validated", "member_type": "researcher", "member_model_id": "claude-opus-x",
           "agent_file_sha256": "0" * 64, "N": 5, "rounds": 1, "view": "kcover", "loo_view": "rotation",
           "reducer": "R0", "tau": 0.6, "t": 2,
           "caps": {"member_tokens": 1000, "member_turns": 10, "run_tokens": 10000}, "usd_per_mtok": 3.0,
           "cost_ratio": {"median": 1.5, "ci95": [1.2, 1.9]},
           "effect": {"wins": 30, "losses": 10, "ties": 100, "pi_hat": 0.75, "ci95": [0.59, 0.87], "p_holm": 0.004},
           "certainty": None, "pool": {"name": "RS pool", "sha256": "1" * 64, "description": "d"}}


@pytest.mark.parametrize("key", sorted(CLASS_KEYS - {"status", "certainty"}))
def test_schema_requires_every_key_but_certainty_when_validated(key):
    """A validated class with a null key (other than certainty) fails; the same entry not_run passes."""
    p = json.loads((CAL / "params.v0.json").read_text(encoding="utf-8"))
    full = validated_entry()
    v = jsonschema.Draft202012Validator(schema())
    p["version"] = 1  # version 0 admits only not_run classes (test_schema_version_zero_is_all_not_run)
    p["classes"]["RS"] = full
    v.validate(p)
    p["classes"]["RS"] = full | {key: None}
    with pytest.raises(jsonschema.ValidationError):
        v.validate(p)
    p["classes"]["RS"] = full | {key: None, "status": "not_run"}
    v.validate(p)


def test_schema_refuses_an_extra_or_missing_class_key_and_n_one_validated():
    p = json.loads((CAL / "params.v0.json").read_text(encoding="utf-8"))
    v = jsonschema.Draft202012Validator(schema())
    bad = json.loads(json.dumps(p))
    bad["classes"]["PF"]["eligible"] = True
    assert not v.is_valid(bad)
    bad = json.loads(json.dumps(p))
    del bad["classes"]["PF"]["pool"]
    assert not v.is_valid(bad)
    bad = json.loads(json.dumps(p))
    del bad["classes"]["OE"]
    assert not v.is_valid(bad)
    bad = json.loads(json.dumps(p))
    bad["version"] = 1
    bad["classes"]["CP"] = validated_entry()
    assert v.is_valid(bad)
    bad["classes"]["CP"]["N"] = 1  # N* = 1: not eligible, never validated
    assert not v.is_valid(bad)


@pytest.mark.parametrize("status", ["validated", "not_established", "refuted"])
def test_schema_version_zero_is_all_not_run(status):
    """Version 0 (no calibration) is valid only when every class is not_run; the shipped files are version 0."""
    v = jsonschema.Draft202012Validator(schema())
    p = json.loads((CAL / "params.v0.json").read_text(encoding="utf-8"))
    assert p["version"] == 0 and v.is_valid(p)
    for shipped in (CAL / "params.json", HOOK):
        assert v.is_valid(json.loads(shipped.read_text(encoding="utf-8")))
    for cls in CLASSES:
        bad = json.loads(json.dumps(p))
        bad["classes"][cls] = validated_entry() | {"status": status}
        assert not v.is_valid(bad), (cls, status)
        bad["version"] = 1  # the same entry in a calibrated version is accepted
        assert v.is_valid(bad), (cls, status)
    # a not_run class that differs from the all-null shape is still version-0 valid (status is the only rule here)
    ok = json.loads(json.dumps(p))
    ok["classes"]["RS"]["status"] = "not_run"
    assert v.is_valid(ok)


def test_schema_version_zero_refuses_a_null_status():
    v = jsonschema.Draft202012Validator(schema())
    p = json.loads((CAL / "params.v0.json").read_text(encoding="utf-8"))
    p["classes"]["DS"]["status"] = None
    assert not v.is_valid(p)


# ---- the `candidate` contract (T11b/T11a2): one rule set on every side -------------------------------------------
HOOKS = ROOT / "dot-config" / "dot-claude" / "hooks"
HARNESS = ROOT / "dot-config" / "dot-equilibrium" / "harness"


def _eq_policy():
    spec = importlib.util.spec_from_file_location("eq_policy_params_pin", HOOKS / "eq_policy.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _consts(path: Path) -> dict:
    """Module-level literal constants of a harness file (read by AST: the harness needs numpy, the hooks do not)."""
    out = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            v = node.value
            if isinstance(v, ast.Call) and getattr(v.func, "attr", None) == "compile" and v.args:
                out[node.targets[0].id] = ("re", ast.literal_eval(v.args[0]))
                continue
            try:
                out[node.targets[0].id] = ast.literal_eval(v)
            except ValueError:
                pass
    return out


def _candidate(**kw) -> dict:
    e = {k: None for k in CLASS_KEYS} | {
        "status": "candidate", "member_type": "researcher", "member_model_id": "claude-opus-x", "N": 5, "rounds": 1,
        "view": "kcover", "loo_view": "rotation", "reducer": "R0", "tau": 0.6, "t": 2,
        "caps": {"member_tokens": 1000, "member_turns": 10, "run_tokens": 10000}}
    return e | kw


def test_candidate_contract_is_one_rule_set():
    """eq_policy (runtime) = params.schema.json = eq_harness (E_rt --params) = eq_calibrate (writer, + pool, N >= 3):
    the status names, the keys a candidate needs non-null, and the model-id rule."""
    P = _eq_policy()
    s = schema()
    cls_def = s["$defs"]["class"]
    assert set(cls_def["properties"]["status"]["enum"]) == set(P.STATUSES)
    then = next(r["then"]["properties"] for r in cls_def["allOf"]
                if r["if"]["properties"]["status"] == {"const": "candidate"})
    assert set(then) == set(P.CANDIDATE_REQUIRED)
    h = _consts(HARNESS / "eq_harness.py")
    assert h["BUNDLE_KEYS"] == P.CANDIDATE_REQUIRED and set(h["E_RT_PARAM_STATUSES"]) == {"candidate", "validated"}
    c = _consts(HARNESS / "eq_calibrate.py")
    assert c["CANDIDATE_REQUIRED"] == (*P.CANDIDATE_REQUIRED, "pool")
    assert c["RUNTIME_MODEL_ID_RE"] == ("re", P.MODEL_ID_RE.pattern)
    # ECMA/Python `$` also matches before a final newline; Python's `\Z` does not: `(?!\n)$` is the same anchor
    pattern = cls_def["properties"]["member_model_id"]["pattern"]
    assert pattern == "^" + P.MODEL_ID_RE.pattern.removesuffix(r"\Z") + r"(?!\n)$"
    flags = json.loads((HARNESS / "flags.json").read_text(encoding="utf-8"))
    assert flags["s_star"] == P.S_STAR and set(P.S_STAR.values()) <= set(P.MEMBER_TYPES)  # calibrate's member_type


@pytest.mark.parametrize("case", [
    {}, {"version": 0}, *({"null": k} for k in sorted(CLASS_KEYS - {"status"})),
    *({"member_model_id": m} for m in ("claude-x-4-6[1m]", "us.anthropic.claude-x-4-5-20250929-v1:0", "X",
                                       "ab", "Claude-Opus", "claude-x-4-5-20250929", "claude-x-4.6",
                                       "claude-x-4-6\n"))],  # Python `$` matches before a final newline
    ids=lambda c: ",".join(f"{k}={v}" for k, v in c.items()) or "base")
def test_candidate_entry_schema_valid_iff_runtime_valid(case):
    """For candidate entries the schema and eq_policy.validate_params agree: on the required keys (null), on version 0
    and on the model id. Above all no schema-valid file is one the runtime refuses whole."""
    P = _eq_policy()
    p = json.loads((CAL / "params.v0.json").read_text(encoding="utf-8"))
    p["version"] = case.get("version", 1)
    e = _candidate()
    if "null" in case:
        e[case["null"]] = None
    if "member_model_id" in case:
        e["member_model_id"] = case["member_model_id"]
    p["classes"]["RS"] = e
    schema_ok = jsonschema.Draft202012Validator(schema()).is_valid(p)
    runtime_errs = P.validate_params(p)
    assert schema_ok == (not runtime_errs), (schema_ok, runtime_errs)
