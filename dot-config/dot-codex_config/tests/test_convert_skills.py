"""lib/convert_skills.py: the real corpus split, staged and checked; fixture trees for bytes, modes,
symlinks, frontmatter and errors. Seeded-bug proofs: tests/mutations/convert_skills.json."""
from __future__ import annotations

import json
import os
import re
import stat

import pytest

from _skills_helpers import (REPO, SKILLS, convert_skills, hub_body, make_src, overrides, skill_md,
                             target_ctx, translate)

CS = convert_skills
CTX = target_ctx()
STACK = CTX["stack"]


def _description(text):
    m = re.search(r"(?m)^description:\s*(.*)$", text.split("---", 2)[1])
    v = m.group(1).strip()
    return json.loads(v) if v.startswith('"') else v


def _frontmatter_keys(text):
    return re.findall(r"(?m)^([\w-]+):", text.split("---", 2)[1])


@pytest.fixture(scope="module")
def real(tmp_path_factory):
    stage = tmp_path_factory.mktemp("stage") / "stack"
    return stage, CS.convert(str(REPO), str(stage), CTX)


def expected_split():
    """Independent of the module: settings.json skillOverrides over the shipped dirs, minus EXCLUDED."""
    so = overrides()
    shipped = sorted(p.parent.name for p in SKILLS.glob("*/SKILL.md"))
    modules = sorted(n for n in shipped if so.get(n) in ("user-invocable-only", "off"))
    listed = sorted(n for n in shipped if n not in modules and n not in translate.EXCLUDED_SKILLS)
    core = sorted(n for n in listed if so.get(n, "on") == "on")
    return shipped, listed, modules, core


# ---------------------------------------------------------------- classification
def test_classify_matches_skill_overrides():
    shipped, listed, modules, core = expected_split()
    cls = CS.classify(str(REPO))
    assert cls["listed"] == listed and cls["modules"] == modules and cls["core"] == core
    assert not set(cls["listed"]) & set(cls["modules"])
    assert not set(cls["listed"] + cls["modules"]) & set(translate.EXCLUDED_SKILLS)
    assert cls["excluded"] == sorted(translate.EXCLUDED_SKILLS)
    assert cls["excluded_modules"] == []
    assert len(listed) + len(modules) + len(cls["excluded"]) == len(shipped)


def test_real_split_on_disk(real):
    stage, r = real
    _, listed, modules, core = expected_split()
    assert r["listed"] == listed and r["modules"] == modules
    assert sorted(os.listdir(stage / "skills")) == listed
    assert sorted(os.listdir(stage / "skill-modules")) == modules
    rep = r["report"]
    assert (rep["listed"], rep["modules"], rep["core"], rep["short"]) == (
        len(listed), len(modules), len(core), len(listed) - len(core))
    assert r["links"] == {n: "%s/skills/%s" % (STACK, n) for n in listed}


def test_excluded_skills_absent_everywhere(real):
    stage, r = real
    for name in translate.EXCLUDED_SKILLS:
        assert not (stage / "skills" / name).exists() and not (stage / "skill-modules" / name).exists()
        assert name not in r["links"] and name not in r["listed"] and name not in r["modules"]
    assert r["report"]["excluded"] == sorted(translate.EXCLUDED_SKILLS)


def test_no_installed_text_names_an_excluded_skill_or_a_venv(real):
    stage, _ = real
    bad = []
    for p in sorted(stage.rglob("*.md")):
        text = p.read_text(encoding="utf-8")
        for line_no, name in translate.excluded_refs(text):
            bad.append("%s:%d %s" % (p.relative_to(stage), line_no, name))
        if "venvs/" in text:
            bad.append("%s venvs/" % p.relative_to(stage))
    assert bad == []


# ---------------------------------------------------------------- hub tables
def test_hub_rows_carry_absolute_reachable_paths(real):
    stage, r = real
    reached = set()
    for kind in ("skills", "skill-modules"):
        for p in sorted((stage / kind).glob("*/SKILL.md")):
            for line in p.read_text(encoding="utf-8").split("\n"):
                m = re.match(r"\|\s*`([a-z0-9-]+)`\*(.*)", line)
                if not m:
                    continue
                want = " (`%s/skill-modules/%s/SKILL.md`)" % (STACK, m.group(1))
                assert m.group(2).startswith(want + " |"), line
                assert (stage / "skill-modules" / m.group(1) / "SKILL.md").is_file()
                reached.add(m.group(1))
    assert reached == set(r["modules"])
    assert r["report"]["rows_linked"] >= len(r["modules"])


def test_link_rows_unit():
    text = "| Module | When |\n|---|---|\n| `num-ode-sde`* | odes |\n```\n| `x`* | in code |\n```\n| `postgresql` | db |"
    out = CS._link_rows(text, "/S/stack", {"num-ode-sde"}, "h.md").split("\n")
    assert out[2] == "| `num-ode-sde`* (`/S/stack/skill-modules/num-ode-sde/SKILL.md`) | odes |"
    assert out[4] == "| `x`* | in code |" and out[6] == "| `postgresql` | db |"
    with pytest.raises(CS.BuildError, match="postgresql"):
        CS._link_rows("| `postgresql`* | db |", "/S/stack", set(), "h.md")


# ---------------------------------------------------------------- listing
def test_budget_fits_and_is_recomputable(real):
    stage, r = real
    chars = 0
    for n in r["listed"]:
        desc = _description((stage / "skills" / n / "SKILL.md").read_text(encoding="utf-8"))
        path = max("%s/skills/%s/SKILL.md" % (STACK, n), "%s/%s/SKILL.md" % (CTX["skills_root"], n), key=len)
        chars += len("- %s: %s (file: %s)\n" % (n, desc, path))
    assert r["budget_chars"] == chars
    assert r["budget_tokens"] == -(-chars // 4) <= CS.SKILLS_MAX_CONTEXT_TOKENS == 6000


def test_descriptions_core_full_rest_short_modules_full(real):
    stage, r = real
    _, listed, modules, core = expected_split()
    for n in listed + modules:
        kind = "skills" if n in listed else "skill-modules"
        out = (stage / kind / n / "SKILL.md").read_text(encoding="utf-8")
        src, probs = translate.translate_text(_description((SKILLS / n / "SKILL.md").read_text(encoding="utf-8")),
                                              n, dict(CTX, skill_modules=frozenset(modules)))
        got = _description(out)
        assert probs == []
        assert _frontmatter_keys(out) == ["name", "description"], n
        if n in core or n in modules:
            assert got == src, n
        else:
            assert len(got) <= 60, (n, got)
            assert src.startswith(got.rstrip("…")), (n, got)


@pytest.mark.parametrize("desc", ["Use for X.\n? name", "Use for X\u0085? name", "Use for X more",
                                  "del\x7fx", "a\n---\nbody", "tab\tand\rcr"])
def test_skill_md_description_stays_one_yaml_line(desc):
    """A description holding a line break or a control character (C0, DEL, C1 with NEL, LS, PS, BOM)
    is written double-quoted with every such character escaped: emitted plain it added YAML
    structure (a `? name` key, a `---` that closes the frontmatter early, a parse error)."""
    text = "---\nname: demo\ndescription: %s\n---\nbody\n" % json.dumps(desc)
    md, got = CS._skill_md(text, "demo", "skills/demo/SKILL.md", short=False)
    assert got == desc
    assert md.startswith("---\n") and md.endswith("\n---\nbody\n"), repr(md)
    lines = md[len("---\n"):-len("\n---\nbody\n")].split("\n")
    assert [ln.split(":", 1)[0] for ln in lines] == ["name", "description"], lines
    raw = re.compile("[\\x00-\\x1f\\x7f-\\x9f\\u2028\\u2029\\ufeff]")
    assert not any(raw.search(ln) for ln in lines), lines
    assert json.loads(lines[1][len("description: "):]) == desc


def test_short_description_unit():
    assert CS.short_description("Use for any Go work — modules, errors.") == "Use for any Go work"
    long_ = "Load before sculpting, retopology, UVs, baking or texture painting — ZBrush"
    got = CS.short_description(long_)
    assert got == "Load before sculpting, retopology, UVs, baking or texture…" and len(got) <= 60


def test_real_text_rewrites_landed(real):
    stage, _ = real
    nm = (stage / "skills" / "numerical-methods" / "SKILL.md").read_text(encoding="utf-8")
    assert "`uv run --with numpy --with scipy --with mpmath --with sympy --with hypothesis python`" in nm
    assert "%s/skill-modules/<name>/SKILL.md" % STACK in nm
    assert "__CLAUDE_DIR__" not in nm and "Skill tool" not in nm


# ---------------------------------------------------------------- fixture trees
def fixture_src(tmp_path, **files_of):
    skills = {
        "hub": {"SKILL.md": skill_md("hub", "Load before hub work — long tail of words, more words.",
                                     hub_body("mod-a")),
                "scripts/run.sh": ("#!/bin/sh\necho hi\n", 0o755),
                "data/blob.bin": (bytes(range(256)) + b"\xff\xfe__CLAUDE_DIR__", 0o644)},
        "mod-a": {"SKILL.md": skill_md("mod-a", "A module for testing — with a long description kept whole.",
                                      "See `__CLAUDE_DIR__/skills/hub/data/blob.bin`.\n")},
        "core-one": {"SKILL.md": skill_md("core-one", "Use for core things — a full description is kept here.")},
    }
    for k, v in files_of.items():
        skills[k.replace("_", "-")] = v
    so = {"hub": "name-only", "mod-a": "user-invocable-only"}
    return make_src(tmp_path / "src", skills, so)


def test_fixture_bytes_modes_and_layout(tmp_path):
    src = fixture_src(tmp_path)
    stage = tmp_path / "stage"
    r = CS.convert(str(src), str(stage), CTX)
    assert (r["listed"], r["modules"]) == (["core-one", "hub"], ["mod-a"])
    blob = stage / "skills" / "hub" / "data" / "blob.bin"
    assert blob.read_bytes() == (src / "dot-config/dot-claude/skills/hub/data/blob.bin").read_bytes()
    run = stage / "skills" / "hub" / "scripts" / "run.sh"
    assert run.read_bytes() == b"#!/bin/sh\necho hi\n"
    assert stat.S_IMODE(run.stat().st_mode) == 0o755
    assert stat.S_IMODE(blob.stat().st_mode) == 0o644
    assert stat.S_IMODE((stage / "skills" / "hub" / "SKILL.md").stat().st_mode) == 0o644
    assert r["report"]["copied"] == 2 and r["report"]["executable"] == 1
    mod = (stage / "skill-modules" / "mod-a" / "SKILL.md").read_text()
    assert "`%s/skills/hub/data/blob.bin`" % STACK in mod


def test_fixture_descriptions(tmp_path):
    src = fixture_src(tmp_path)
    stage = tmp_path / "stage"
    CS.convert(str(src), str(stage), CTX)
    read = lambda k, n: _description((stage / k / n / "SKILL.md").read_text())  # noqa: E731
    assert read("skills", "hub") == "Load before hub work"
    assert read("skills", "core-one") == "Use for core things — a full description is kept here."
    assert read("skill-modules", "mod-a") == "A module for testing — with a long description kept whole."


def test_fixture_excluded_skill_and_its_only_module(tmp_path):
    src = fixture_src(tmp_path,
                      stack_tree={"SKILL.md": skill_md("stack-tree", "Claude-only.", hub_body("lone-mod"),
                                                       **{"disable-model-invocation": "true"})},
                      lone_mod={"SKILL.md": skill_md("lone-mod", "Only the excluded hub reaches me.")})
    so = json.loads((src / "dot-config/dot-claude/settings.json").read_text())["skillOverrides"]
    so["lone-mod"] = "user-invocable-only"
    (src / "dot-config/dot-claude/settings.json").write_text(json.dumps({"skillOverrides": so}))
    cls = CS.classify(str(src))
    assert cls["excluded"] == ["stack-tree"] and cls["excluded_modules"] == ["lone-mod"]
    assert "stack-tree" not in cls["listed"] and "lone-mod" not in cls["modules"]
    stage = tmp_path / "stage"
    r = CS.convert(str(src), str(stage), CTX)
    assert sorted(os.listdir(stage / "skills")) == ["core-one", "hub"]
    assert sorted(os.listdir(stage / "skill-modules")) == ["mod-a"]
    assert r["report"]["excluded_modules"] == ["lone-mod"]


@pytest.mark.parametrize("where", ["file", "dir"])
def test_symlink_in_source_is_refused(tmp_path, where):
    src = fixture_src(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_text("SECRET")
    sk = src / "dot-config" / "dot-claude" / "skills"
    if where == "file":
        (sk / "hub" / "data" / "link.txt").symlink_to(secret)
    else:
        (sk / "hub" / "linked").symlink_to(tmp_path)
    stage = tmp_path / "stage"
    with pytest.raises(CS.BuildError, match="symlink in the skill source tree"):
        CS.convert(str(src), str(stage), CTX)
    assert not any("SECRET" in p.read_text(errors="replace") for p in stage.rglob("*") if p.is_file())


def test_symlinked_skill_dir_is_refused(tmp_path):
    src = fixture_src(tmp_path)
    real_dir = tmp_path / "elsewhere"
    real_dir.mkdir()
    (real_dir / "SKILL.md").write_text(skill_md("evil", "x"))
    (src / "dot-config" / "dot-claude" / "skills" / "evil").symlink_to(real_dir)
    with pytest.raises(CS.BuildError, match="symlink in the skill source tree"):
        CS.classify(str(src))


def test_translate_problem_names_file_and_line(tmp_path):
    src = fixture_src(tmp_path, bad={"SKILL.md": skill_md("bad", "x."), "references/r.md": "ok\nuse ToolSearch\n"})
    with pytest.raises(CS.BuildError, match=r"skills/bad/references/r\.md:2: ToolSearch"):
        CS.convert(str(src), str(tmp_path / "stage"), CTX)


def test_frontmatter_argument_hint_dropped_unknown_key_refused(tmp_path):
    src = fixture_src(tmp_path, hinted={"SKILL.md": skill_md("hinted", "Use it.", **{"argument-hint": "<x>"})})
    stage = tmp_path / "stage"
    CS.convert(str(src), str(stage), CTX)
    assert _frontmatter_keys((stage / "skills" / "hinted" / "SKILL.md").read_text()) == ["name", "description"]
    src2 = fixture_src(tmp_path / "b", odd={"SKILL.md": skill_md("odd", "Use it.", **{"disable-model-invocation": "true"})})
    with pytest.raises(CS.BuildError, match="disable-model-invocation"):
        CS.convert(str(src2), str(tmp_path / "b" / "stage"), CTX)


def test_unreachable_module_and_nonempty_stage_refused(tmp_path):
    src = fixture_src(tmp_path, orphan={"SKILL.md": skill_md("orphan", "Nobody links me.")})
    so = json.loads((src / "dot-config/dot-claude/settings.json").read_text())["skillOverrides"]
    so["orphan"] = "user-invocable-only"
    (src / "dot-config/dot-claude/settings.json").write_text(json.dumps({"skillOverrides": so}))
    with pytest.raises(CS.BuildError, match="orphan"):
        CS.classify(str(src))
    src2 = fixture_src(tmp_path / "b")
    stage = tmp_path / "b" / "stage"
    (stage / "skills").mkdir(parents=True)
    (stage / "skills" / "leftover").write_text("x")
    with pytest.raises(CS.BuildError, match="not an empty directory"):
        CS.convert(str(src2), str(stage), CTX)


def test_budget_over_the_cap_is_an_error(tmp_path, monkeypatch):
    src = fixture_src(tmp_path)
    monkeypatch.setattr(CS, "SKILLS_MAX_CONTEXT_TOKENS", 10)
    with pytest.raises(CS.BuildError, match="max_context_tokens"):
        CS.convert(str(src), str(tmp_path / "stage"), CTX)
