"""lib/translate.py: the corpus translates clean, the wording rules, the venv and excluded-skill
decisions, and the error paths (label:line). Seeded-bug proofs: tests/mutations/translate.json."""
from __future__ import annotations

import inspect
import re

import pytest

from _skills_helpers import (REQUIREMENTS, RULES_TEMPLATE, agent_bodies, corpus_modules,
                             installed_skill_texts, target_ctx, translate)

T = translate


def tr(text, label="x.md", **ctx_extra):
    ctx = target_ctx(modules=ctx_extra.pop("modules", ("num-ode-sde",)), **ctx_extra)
    return T.translate_text(text, label, ctx)


@pytest.fixture(scope="module")
def corpus():
    """{label: (source, translated, problems)} over the 57 agent bodies and every installed skill file."""
    ctx = target_ctx(modules=corpus_modules())
    texts = dict(agent_bodies())
    texts.update(installed_skill_texts())
    return {k: (v, *T.translate_text(v, k, ctx)) for k, v in texts.items()}


# ---------------------------------------------------------------- corpus
def test_corpus_has_no_problems(corpus):
    assert sum(k.startswith("agents/") for k in corpus) == 57
    problems = [p for _, _, probs in corpus.values() for p in probs]
    assert problems == []


def test_corpus_names_no_venv_and_no_excluded_skill(corpus):
    bad = []
    for label, (_, out, _) in corpus.items():
        for i, line in enumerate(out.split("\n"), 1):
            if "venvs/" in line or re.search(r"(?i)\b(?:sci|science|shared) venvs?\b|\bthe venvs\b", line):
                bad.append("%s:%d venv: %s" % (label, i, line[:120]))
            for name in T.EXCLUDED_SKILLS:
                if re.search(r"(?<![\w-])%s(?![\w-])" % name, line):
                    bad.append("%s:%d excluded %s" % (label, i, name))
    assert bad == []


def test_corpus_wording_bugs_gone(corpus):
    outs = "\n".join(out for _, out, _ in corpus.values())
    for wrong in ("a separate the shell", "the the shell", "own the shell", "on a background job on",
                  "`the claude-agent-stack repository`", "(the claude-agent-stack repository)"):
        assert wrong not in outs, wrong


def test_corpus_has_no_claude_only_leftovers(corpus):
    """A COMMON tool name after "word:" is prose too (orchestrator: "design: Bash is for checks"), and
    no text claims a Claude Code user command exists here (data-visualization's /dataviz)."""
    outs = "\n".join(out for _, out, _ in corpus.values())
    for wrong in ("design: Bash is for checks", "/dataviz", "`dataviz`"):
        assert wrong not in outs, wrong
    assert "design: the shell is for checks and integration" in outs


@pytest.mark.parametrize("src, want", [
    ("no design: Bash is for checks.", "no design: the shell is for checks."),
    ("one rule: Read it first.", "one rule: read it first."),
])
def test_common_name_after_a_colon_is_prose(src, want):
    assert tr(src) == (want, [])


# ---------------------------------------------------------------- the three wording bugs
@pytest.mark.parametrize("src, want", [
    ("run them in a separate Bash call;", "run them in a separate shell call;"),
    ("use the Bash tool to run it", "use the shell tool to run it"),
    ("your own Bash calls", "your own shell calls"),
    ("write with a Bash heredoc", "write with a shell heredoc"),
    ("then through Bash.", "then through the shell."),
])
def test_bash_takes_the_bare_form_after_a_determiner(src, want):
    assert tr(src) == (want, [])


def test_proof_checker_sentence():
    body = agent_bodies()["agents/proof-checker.md"]
    out, probs = tr(body, modules=corpus_modules())
    assert probs == [] and "run them in a separate shell call;" in out


@pytest.mark.parametrize("src, want", [
    ("wait on them with a Monitor until-loop on the log;", "wait on them with a polling loop on the log;"),
    ("waited on with a Monitor until-loop on the log or output frames",
     "waited on with a polling loop on the log or output frames"),
    ("Long runs wait on a Monitor until-loop.", "Long runs wait with a polling loop."),
    ("Long jobs: background, a Monitor until-loop, checkpoints", "Long jobs: background, a polling loop, checkpoints"),
])
def test_monitor_until_loop(src, want):
    assert tr(src) == (want, [])


def test_stack_repo_without_a_path():
    out, probs = tr("Edit the stack repo (`__STACK_REPO__`), never installed copies.\n"
                    "files change in its repo, `__STACK_REPO__` (its `dot-claude/`)")
    assert probs == []
    assert out.split("\n") == ["Edit the stack repo, never installed copies.",
                               "files change in its repo, the claude-agent-stack repository (its `dot-claude/`)"]


def test_stack_repo_with_a_path():
    out, probs = tr("Edit the stack repo (`__STACK_REPO__`), never.", stack_repo="/src/claude-agent-stack")
    assert (out, probs) == ("Edit the stack repo (`/src/claude-agent-stack`), never.", [])


# ---------------------------------------------------------------- venvs (the user's decision a)
@pytest.mark.parametrize("src, want", [
    ("Compute with `__CLAUDE_DIR__/venvs/sci/bin/python` (sympy, mpmath, numpy, z3) and mcp__wolfram.",
     "Compute with `uv run --with sympy --with mpmath --with numpy --with z3-solver python` and mcp__wolfram."),
    ("Environment: `__CLAUDE_DIR__/venvs/sci/bin/python` (NumPy/SciPy).",
     "Environment: `uv run --with numpy --with scipy python`."),
    ("Environment: the science venv `~/.claude/venvs/sci/bin/python` has matplotlib, seaborn; add plotly.",
     "Environment: `uv run --with matplotlib --with seaborn python`; add plotly."),
    ("symbolically (sympy in `__CLAUDE_DIR__/venvs/sci/bin/python`, or `mcp__wolfram`)",
     "symbolically (`uv run --with sympy python`, or `mcp__wolfram`)"),
    ("- Tables: extract with pdfplumber/openpyxl via `__CLAUDE_DIR__/venvs/sci/bin/python`; recompute.",
     "- Tables: extract with pdfplumber/openpyxl via `uv run --with pdfplumber --with openpyxl python`; recompute."),
    ("Environments: `__CLAUDE_DIR__/venvs/sci/bin/python`, `__CLAUDE_DIR__/venvs/ml/bin/python`.",
     "Environments: `uv run --with numpy --with scipy python`, `uv run --with torch python`."),
    ("else `__CLAUDE_DIR__/venvs/ml/bin/python` (from `./install.sh --with-ml`) or "
     "`__CLAUDE_DIR__/venvs/sci/bin/python` for light work.",
     "else `uv run --with torch python` or `uv run --with numpy --with scipy python` for light work."),
    ("`$HOME/.claude/venvs/ml/bin/python` (PyTorch; mlx on the Mac).",
     "`uv run --with torch python` (PyTorch; mlx on the Mac)."),
    ("z3-solver is in the sci venv: `__CLAUDE_DIR__/venvs/sci/bin/python`.",
     "z3-solver runs with `uv run --with z3-solver python`."),
    ("Ad-hoc work runs in the sci venv; projects pin versions.",
     "Ad-hoc work runs with `uv run --with <package>`; projects pin versions."),
    ("`linprog` (sci venv), or `highspy`", "`linprog`, or `highspy`"),
])
def test_venv_sentences_become_uv_forms(src, want):
    assert tr(src) == (want, [])


def test_venv_in_code_takes_the_block_imports():
    src = ("```sh\ngs -o x.tif file.pdf\n__CLAUDE_DIR__/venvs/sci/bin/python - <<'EOF'\n"
           "import glob, numpy as np\nfrom PIL import Image\nEOF\n```")
    out, probs = tr(src)
    assert probs == []
    assert out.split("\n")[2] == "uv run --with numpy --with pillow python - <<'EOF'"


def test_venv_in_code_with_an_unmapped_import_is_a_problem():
    out, probs = tr("```\n__CLAUDE_DIR__/venvs/sci/bin/python -c 'import qiskit'\n```", label="f.md")
    assert probs == ["f.md:2: import qiskit (no package mapping for the sci venv)"]


def test_multiline_package_list_joins_and_keeps_source_lines():
    src = ("with `__CLAUDE_DIR__/venvs/sci/bin/python` (sympy, mpmath,\n"
           "numpy, z3-solver). Use it.\n"
           "then call ToolSearch")
    out, probs = tr(src, label="e.md")
    assert out.split("\n")[0] == "with `uv run --with sympy --with mpmath --with numpy --with z3-solver python`. Use it."
    assert probs == ["e.md:3: ToolSearch"]


@pytest.mark.parametrize("src, token", [
    ("see `__CLAUDE_DIR__/venvs/sci/lib/python3.13/site-packages`", "venvs/sci/lib"),
    ("run `__CLAUDE_DIR__/venvs/gpu/bin/python` now", "unknown venv"),
    ("the shared venvs are for ad-hoc work", "shared venvs"),
    ("```\n~/.claude/venvs/ml/bin/pip install x\n```", "venvs/ml/bin/pip"),
])
def test_a_venv_left_in_the_output_is_a_problem(src, token):
    _, probs = tr(src, label="v.md")
    assert probs and all(p.startswith("v.md:") for p in probs) and any(token in p for p in probs), probs


def test_rules_template_names_no_venv_and_fits():
    data = RULES_TEMPLATE.read_bytes()
    assert b"venvs/" not in data and len(data) <= 8192
    line = [ln for ln in data.decode().split("\n") if ln.startswith("- Python runs through uv")]
    assert len(line) == 1 and "Exception: a project pinned to poetry, conda or pixi." in line[0]


def test_venv_packages_match_requirements():
    """The fixed table equals requirements/*.in (plus pillow for sci and ml); skipped where the tree
    has no requirements/ (a mutation copy)."""
    if not REQUIREMENTS.is_dir():
        pytest.skip("requirements/ not in this tree")
    for venv, pkgs in T.VENV_PACKAGES.items():
        names = []
        for line in (REQUIREMENTS / ("%s.in" % venv)).read_text().splitlines():
            line = line.split("#")[0].strip()
            if line:
                names.append(re.split(r"[<>=;\[ ]", line)[0])
        extra = {"pillow"} if venv in ("sci", "ml") else set()
        assert set(pkgs) == set(names) | extra, venv
        assert set(T.VENV_DEFAULT[venv]) <= set(pkgs)


# ---------------------------------------------------------------- excluded skills (the user's decision b)
@pytest.mark.parametrize("src", [
    "Load `stack-tree` before anything.",
    "Read `__CLAUDE_DIR__/skills/claude-code-extensions/SKILL.md` first.",
    "Run /stack-doctor.",
    "```\nclaude-code-extensions\n```",
])
def test_naming_an_excluded_skill_is_a_problem(src):
    _, probs = tr(src, label="s.md", modules=())
    assert any("not installed for Codex" in p and p.startswith("s.md:") for p in probs), probs


def test_excluded_pointers_are_dropped():
    src = ("- Related: `review-protocol` (rubric), `claude-code-extensions` (permission rules and hooks in this stack).\n"
           "- Load `claude-code-extensions` before writing any configuration, and `prompt-and-brief-design` before a prompt.\n"
           "  OpenRouter model). Empty = the default above. /stack-doctor shows the models\n"
           "  in use and checks each in its provider's catalog.\n"
           "- next")
    out, probs = tr(src)
    assert probs == []
    assert out.split("\n") == ["- Related: `review-protocol` (rubric).",
                               "- Load `prompt-and-brief-design` before a prompt.",
                               "  OpenRouter model). Empty = the default above.", "- next"]


def test_verbatim_mode_is_gone():
    assert "verbatim" not in inspect.signature(T.translate_text).parameters
    assert "verbatim" not in inspect.signature(T.render_placeholders).parameters


# ---------------------------------------------------------------- tokens, fences, paths
def test_unmapped_token_fails_with_label_and_line():
    out, probs = tr("fine line\nthen use ToolSearch to load it\n", label="agents/a.md")
    assert probs == ["agents/a.md:2: ToolSearch"]


def test_forbidden_phrase_is_reported():
    _, probs = tr("ok\nThe hook denies a push.", label="r.md")
    assert probs == ["r.md:2: the hook denies"] or probs == ["r.md:2: The hook denies"]


def test_fenced_code_is_left_alone():
    src = "```\nRead the `Read` tool, ToolSearch, Bash(git push)\n```\nthen Read `x`"
    out, probs = tr(src)
    assert probs == []
    lines = out.split("\n")
    assert lines[1] == "Read the `Read` tool, ToolSearch, Bash(git push)"
    assert lines[3] == "then read `x`"


def test_tool_names_map_outside_fences():
    out, probs = tr("Use `Grep`, `Glob` and Agent(explore); SendMessage the child.")
    assert probs == []
    assert out == "Use `rg`, `rg --files` and `spawn_agent` (agent_type explore); `send_input` the child."


def test_skill_paths_go_to_modules_or_skills():
    out, probs = tr("open `__CLAUDE_DIR__/skills/num-ode-sde/SKILL.md` and `~/.claude/skills/numerical-methods/x.md`",
                    modules=("num-ode-sde",))
    assert probs == []
    assert "`/Users/someuser1/.codex/stack/skill-modules/num-ode-sde/SKILL.md`" in out
    assert "`/Users/someuser1/.codex/stack/skills/numerical-methods/x.md`" in out


def test_skill_path_without_a_module_set_is_a_problem():
    ctx = target_ctx()
    assert "skill_modules" not in ctx
    _, probs = T.translate_text("x\nsee `__CLAUDE_DIR__/skills/num-ode-sde/SKILL.md`", "a.md", ctx)
    assert probs == ["a.md:2: skills/num-ode-sde (ctx has no skill_modules to classify it)"]


def test_hub_note_points_at_skill_modules():
    note = "`*` = not in the skill listing: Read `__CLAUDE_DIR__/skills/<name>/SKILL.md` (the Skill tool won't load it)."
    out, probs = tr(note)
    assert probs == []
    assert out == ("`*` = a module, not in the skills list: open "
                   "`/Users/someuser1/.codex/stack/skill-modules/<name>/SKILL.md` (path in its row).")


def test_unknown_placeholder_is_a_problem():
    _, probs = tr("a\nb __NOPE__ c", label="p.md")
    assert probs == ["p.md:2: __NOPE__"]
