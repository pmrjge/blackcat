"""tests/fake-codex/execpolicy_mirror.py: the fake `codex execpolicy check` must behave like the real
one at rust-v0.160.1 (vendored sources and tests under tests/fixtures/rules/)."""
from __future__ import annotations

import json
import re

import pytest

from _rules_helpers import FIXTURES, execpolicy


def write(tmp_path, text, name="p.rules"):
    p = tmp_path / name
    p.write_text(text)
    return p


GIT_PUSH = 'prefix_rule(\n    pattern = ["git", "push"],\n    decision = "forbidden",\n)\n'


def test_cli_output_matches_upstream_cli_test(tmp_path):
    # vendored codex-rs/cli/tests/execpolicy.rs: exact JSON for both upstream cases
    src = (FIXTURES / "cli_tests_execpolicy.rs").read_text()
    assert '"matchedPrefix": ["git", "push"]' in src and "pushing is blocked in this repo" in src
    p = write(tmp_path, GIT_PUSH)
    rc, out, _ = execpolicy(p, "git", "push", "origin", "main")
    assert rc == 0
    assert out == ('{"matchedRules":[{"prefixRuleMatch":{"matchedPrefix":["git","push"],'
                   '"decision":"forbidden"}}],"decision":"forbidden"}\n')
    p2 = write(tmp_path, GIT_PUSH.replace(
        ")\n", '    justification = "pushing is blocked in this repo",\n)\n'), "j.rules")
    rc, out, _ = execpolicy(p2, "git", "push", "origin", "main")
    assert json.loads(out) == {"decision": "forbidden", "matchedRules": [{"prefixRuleMatch": {
        "matchedPrefix": ["git", "push"], "decision": "forbidden",
        "justification": "pushing is blocked in this repo"}}]}


def test_no_match_omits_decision(tmp_path):
    rc, out, _ = execpolicy(write(tmp_path, GIT_PUSH), "git", "status")
    assert rc == 0 and out == '{"matchedRules":[]}\n'


def test_upstream_example_policy_loads_and_its_examples_hold(tmp_path):
    ex = FIXTURES / "example.codexpolicy"
    assert json.loads(execpolicy(ex, "git", "reset", "--hard", "x")[1])["decision"] == "forbidden"
    assert json.loads(execpolicy(ex, "git", "reset", "--merge")[1]) == {"matchedRules": []}
    assert json.loads(execpolicy(ex, "cp", "-r", "a", "b")[1])["decision"] == "prompt"
    assert json.loads(execpolicy(ex, "ls", "-l")[1])["decision"] == "allow"


def test_multiple_files_and_strictest_decision(tmp_path):
    # basic.rs parses_multiple_policy_files / strictest_decision_wins_across_matches
    a = write(tmp_path, 'prefix_rule(pattern = ["git"], decision = "prompt")\n', "a.rules")
    b = write(tmp_path, 'prefix_rule(pattern = ["git", "commit"], decision = "forbidden")\n', "b.rules")
    rc, out, _ = execpolicy([a, b], "git", "commit", "-m", "hi")
    assert json.loads(out) == {"decision": "forbidden", "matchedRules": [
        {"prefixRuleMatch": {"matchedPrefix": ["git"], "decision": "prompt"}},
        {"prefixRuleMatch": {"matchedPrefix": ["git", "commit"], "decision": "forbidden"}}]}
    assert json.loads(execpolicy([a, b], "git", "status")[1])["decision"] == "prompt"


def test_first_token_alias_and_tail_alternatives(tmp_path):
    # basic.rs only_first_token_alias_expands_to_multiple_rules / tail_aliases_are_not_cartesian
    p = write(tmp_path, 'prefix_rule(pattern = [["bash", "sh"], ["-c", "-l"]])\n'
                        'prefix_rule(pattern = ["npm", ["i", "install"], ["--legacy-peer-deps", "--no-save"]])\n')
    assert json.loads(execpolicy(p, "sh", "-l", "echo")[1])["matchedRules"][0][
        "prefixRuleMatch"]["matchedPrefix"] == ["sh", "-l"]
    got = json.loads(execpolicy(p, "npm", "install", "--no-save", "leftpad")[1])
    assert got["matchedRules"][0]["prefixRuleMatch"]["matchedPrefix"] == [
        "npm", "install", "--no-save"]
    assert json.loads(execpolicy(p, "npm", "--no-save", "i")[1]) == {"matchedRules": []}


def test_prefix_match_is_exact_tokens(tmp_path):
    p = write(tmp_path, GIT_PUSH)
    for cmd in (["git", "-C", "x", "push"], ["git", "pushx"], ["env", "git", "push"], ["git"]):
        assert json.loads(execpolicy(p, *cmd)[1]) == {"matchedRules": []}, cmd


def test_host_executable_resolution(tmp_path):
    p = write(tmp_path, GIT_PUSH)
    assert json.loads(execpolicy(p, "/usr/bin/git", "push")[1]) == {"matchedRules": []}
    got = json.loads(execpolicy(p, "/usr/bin/git", "push", flags=["--resolve-host-executables"])[1])
    assert got["decision"] == "forbidden"
    assert got["matchedRules"][0]["prefixRuleMatch"]["resolvedProgram"] == "/usr/bin/git"
    gated = write(tmp_path, GIT_PUSH + 'host_executable(name = "git", paths = ["/opt/git/bin/git"])\n',
                  "g.rules")
    flags = ["--resolve-host-executables"]
    assert json.loads(execpolicy(gated, "/usr/bin/git", "push", flags=flags)[1]) == {"matchedRules": []}
    assert json.loads(execpolicy(gated, "/opt/git/bin/git", "push", flags=flags)[1])["decision"] == \
        "forbidden"


@pytest.mark.parametrize("bad", [
    'prefix_rule(pattern = ["git", "push"], match = [["git", "pull"]])\n',
    'prefix_rule(pattern = ["git", "push"], not_match = ["git push origin"])\n',
    'prefix_rule(pattern = ["git"], decision = "deny")\n',
    'prefix_rule(pattern = ["git"], justification = "  ")\n',
    'prefix_rule(pattern = [])\n',
    'prefix_rule(pattern = ["git", []])\n',
    'x = 1\n',
    'load("other.star", "f")\n',
    'prefix_rule(pattern = ["git"], colour = "red")\n',
])
def test_load_errors_exit_1(tmp_path, bad):
    rc, out, err = execpolicy(write(tmp_path, bad), "git", "status")
    assert rc == 1 and out == "" and err.startswith("Error: ")


def test_string_examples_are_shell_split(tmp_path):
    p = write(tmp_path, 'prefix_rule(pattern = ["git", "commit"], decision = "prompt",\n'
                        '    match = ["git commit -m \'two words\'"], not_match = ["git \'commit x\'"])\n')
    assert execpolicy(p, "git", "commit")[0] == 0


@pytest.mark.parametrize("argv, code", [
    ([], 2), (["--rules"], 2), (["--bogus", "x"], 2),
])
def test_usage_errors_exit_2(tmp_path, argv, code):
    import subprocess
    from _rules_helpers import FAKE_CODEX, codex_env
    p = subprocess.run([str(FAKE_CODEX), "execpolicy", "check"] + argv, capture_output=True,
                       text=True, env=codex_env())
    assert p.returncode == code


def test_missing_command_is_usage_error(tmp_path):
    rc, _, err = execpolicy(write(tmp_path, GIT_PUSH))
    assert rc == 2 and "COMMAND" in err


def test_separator_and_hyphen_tokens(tmp_path):
    p = write(tmp_path, 'prefix_rule(pattern = ["git", "--version"], decision = "prompt")\n')
    assert json.loads(execpolicy(p, "git", "--version", flags=["--"])[1])["decision"] == "prompt"
    assert json.loads(execpolicy(p, "git", "--version")[1])["decision"] == "prompt"
    assert json.loads(execpolicy(p, "git", "--version", flags=["--pretty"])[1])["decision"] == \
        "prompt"


def test_pretty_is_two_space_indent(tmp_path):
    rc, out, _ = execpolicy(write(tmp_path, GIT_PUSH), "git", "push", flags=["--pretty"])
    assert out.startswith('{\n  "matchedRules": [\n    {\n')
    assert re.search(r'\n  "decision": "forbidden"\n}\n\Z', out)
