"""Tests for dot-config/dot-claude/bin/mcp-headers (the headersHelper for remote MCP servers).

Run: uv run --with pytest pytest -q tests/test_mcp_headers.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "dot-config" / "dot-claude" / "bin" / "mcp-headers"
KEYS = ("EXA_API_KEY", "JINA_API_KEY", "HF_TOKEN", "WANDB_API_KEY", "HF_HOME", "HF_TOKEN_PATH",
        "STACK_ENV_FILE", "CLAUDE_CODE_MCP_SERVER_NAME")


@pytest.fixture
def env(tmp_path):
    e = {k: v for k, v in os.environ.items() if k not in KEYS}
    e.pop("XDG_CACHE_HOME", None)  # never read the real machine's huggingface token cache
    e["HOME"] = str(tmp_path / "home")
    (tmp_path / "home").mkdir()
    return e


def headers(env, name=None, extra=None, reveal=True):
    """Runs the helper with a CLI server name (--reveal by default, so these tests see the real
    value); pass reveal=False to check the default-redacted behavior instead."""
    argv = [sys.executable, str(HELPER)] + ([name] if name else [])
    if name and reveal:
        argv.append("--reveal")
    p = subprocess.run(argv, capture_output=True, text=True, env=dict(env, **(extra or {})),
                       timeout=30)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def write_env(tmp_path, text):
    f = tmp_path / "stack.env"
    f.write_text(text)
    return str(f)


def test_keys_from_stack_env(env, tmp_path):
    f = write_env(tmp_path, 'EXA_API_KEY=exa-123\nexport JINA_API_KEY="jina-456"\n'
                            "HF_TOKEN='hf_789'\nWANDB_API_KEY=wb-0\n# EXA_API_KEY=commented\n")
    e = dict(env, STACK_ENV_FILE=f)
    assert headers(e, "exa") == {"x-api-key": "exa-123"}
    assert headers(e, "jina") == {"Authorization": "Bearer jina-456"}
    assert headers(e, "huggingface") == {"Authorization": "Bearer hf_789"}
    assert headers(e, "wandb") == {"Authorization": "Bearer wb-0"}


def test_server_name_from_claude_env(env, tmp_path):
    f = write_env(tmp_path, "EXA_API_KEY=exa-123\n")
    assert headers(env, extra={"STACK_ENV_FILE": f, "CLAUDE_CODE_MCP_SERVER_NAME": "exa"}) == {
        "x-api-key": "exa-123"}


def test_unknown_server_and_empty_key_give_empty_object(env, tmp_path):
    f = write_env(tmp_path, "EXA_API_KEY=\n")
    e = dict(env, STACK_ENV_FILE=f)
    assert headers(e, "exa") == {}
    assert headers(e, "wolfram") == {}
    assert headers(e) == {}


def test_stack_env_wins_over_process_env_and_env_is_fallback(env, tmp_path):
    f = write_env(tmp_path, "EXA_API_KEY=from-file\nJINA_API_KEY=\n")
    e = dict(env, STACK_ENV_FILE=f, EXA_API_KEY="from-env", JINA_API_KEY="jina-env")
    assert headers(e, "exa") == {"x-api-key": "from-file"}
    assert headers(e, "jina") == {"Authorization": "Bearer jina-env"}


def test_rejects_unexpanded_or_malformed_values(env, tmp_path):
    f = write_env(tmp_path, "EXA_API_KEY=$EXA\nJINA_API_KEY=has space\n")
    e = dict(env, STACK_ENV_FILE=f)
    assert headers(e, "exa") == {}
    assert headers(e, "jina") == {}


def test_default_stack_env_is_next_to_the_script(env, tmp_path):
    cfg = tmp_path / "cfg"
    (cfg / "bin").mkdir(parents=True)
    helper = cfg / "bin" / "mcp-headers"
    helper.write_text(HELPER.read_text())
    (cfg / "stack.env").write_text("JINA_API_KEY=abc\n")
    p = subprocess.run([sys.executable, str(helper), "jina", "--reveal"], capture_output=True,
                       text=True, env=env, timeout=30)
    assert json.loads(p.stdout) == {"Authorization": "Bearer abc"}


def test_huggingface_token_file_fallbacks(env, tmp_path):
    f = write_env(tmp_path, "HF_TOKEN=\n")
    home_token = Path(env["HOME"]) / ".cache" / "huggingface" / "token"
    home_token.parent.mkdir(parents=True)
    home_token.write_text("hf_home\n")
    e = dict(env, STACK_ENV_FILE=f)
    assert headers(e, "huggingface") == {"Authorization": "Bearer hf_home"}
    hf_home = tmp_path / "hfhome"
    hf_home.mkdir()
    (hf_home / "token").write_text("hf_custom")
    assert headers(dict(e, HF_HOME=str(hf_home)), "huggingface") == {
        "Authorization": "Bearer hf_custom"}
    explicit = tmp_path / "tok"
    explicit.write_text("hf_explicit")
    assert headers(dict(e, HF_HOME=str(hf_home), HF_TOKEN_PATH=str(explicit)), "huggingface") == {
        "Authorization": "Bearer hf_explicit"}
    # the token file is only a fallback for huggingface, never for other servers
    assert headers(e, "exa") == {}


def test_inline_comments_and_export_whitespace_like_a_shell(env, tmp_path):
    # the shell that sources stack.env reads these as exa-123 / jina-456 / hf_789
    f = write_env(tmp_path, "EXA_API_KEY=exa-123   # my exa key\n"
                            'JINA_API_KEY="jina-456"  # quoted, then a comment\n'
                            "export\tHF_TOKEN=hf_789\n")
    e = dict(env, STACK_ENV_FILE=f)
    assert headers(e, "exa") == {"x-api-key": "exa-123"}
    assert headers(e, "jina") == {"Authorization": "Bearer jina-456"}
    assert headers(e, "huggingface") == {"Authorization": "Bearer hf_789"}


def test_cli_argument_redacts_by_default(env, tmp_path):
    f = write_env(tmp_path, "EXA_API_KEY=exa-super-secret\nJINA_API_KEY=jina-super-secret\n")
    e = dict(env, STACK_ENV_FILE=f)
    got = headers(e, "exa", reveal=False)
    assert got != {"x-api-key": "exa-super-secret"}
    assert "exa-super-secret" not in json.dumps(got)
    assert got == {"x-api-key": "<redacted:16 chars>"}
    got = headers(e, "jina", reveal=False)
    assert "jina-super-secret" not in json.dumps(got)
    assert got == {"Authorization": "Bearer <redacted:17 chars>"}


def test_cli_argument_with_reveal_prints_the_real_value(env, tmp_path):
    f = write_env(tmp_path, "EXA_API_KEY=exa-super-secret\n")
    e = dict(env, STACK_ENV_FILE=f)
    assert headers(e, "exa", reveal=True) == {"x-api-key": "exa-super-secret"}


def test_no_key_redacts_to_empty_object_either_way(env, tmp_path):
    f = write_env(tmp_path, "EXA_API_KEY=\n")
    e = dict(env, STACK_ENV_FILE=f)
    assert headers(e, "exa", reveal=False) == {}
    assert headers(e, "exa", reveal=True) == {}


def test_claude_code_env_var_invocation_is_never_redacted(env, tmp_path):
    """Claude Code's own headersHelper call carries no CLI argument (CLAUDE_CODE_MCP_SERVER_NAME
    instead): that path must keep returning the real value, --reveal or not, or every remote MCP
    server would authenticate with a literal redaction placeholder."""
    f = write_env(tmp_path, "EXA_API_KEY=exa-super-secret\n")
    got = headers(env, extra={"STACK_ENV_FILE": f, "CLAUDE_CODE_MCP_SERVER_NAME": "exa"})
    assert got == {"x-api-key": "exa-super-secret"}


def test_key_from_entry_reads_static_headers_and_url_keys():
    import runpy
    mh = runpy.run_path(str(HELPER), run_name="mcp_headers")
    k = mh["key_from_entry"]
    assert k("exa", {"url": "https://mcp.exa.ai/mcp", "headers": {"X-API-Key": "abc"}}) == "abc"
    assert k("exa", {"url": "https://mcp.exa.ai/mcp?exaApiKey=q123"}) == "q123"
    assert k("jina", {"headers": {"Authorization": "Bearer jina_x"}}) == "jina_x"
    assert k("jina", {"headers": {"Authorization": "Bearer ${JINA_API_KEY}"}}) == ""
    assert k("wolfram", {"headers": {"x-api-key": "z"}}) == ""
