"""Unit tests for lib/install_state.py: the round-2 hardening (N-MANIFEST scope rule, N-SYMLINK,
L2 restored links, L3 drift, L4 backup root). The end-to-end runs are in tests/install_smoke.sh."""
import json
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import install_state as st  # noqa: E402


def write(path, text="x\n"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


@pytest.fixture
def conf(tmp_path):
    c = tmp_path / "c"
    write(str(c / "agents" / "coder.md"), "coder\n")
    write(str(c / "settings.json"), "{}\n")
    write(str(c / ".stack-manifest.json"), "{}\n")
    return str(c)


@pytest.mark.parametrize("rel", ["hooks/../../x", "../x", "/etc/passwd", "hooks\\x", "hooks/./x",
                                 "hooks//x", "projects/x", "skills/synced/x", "", "agents/../../x"])
def test_in_scope_rejects(rel):
    assert not st.in_scope(rel)


@pytest.mark.parametrize("rel", ["agents/coder.md", "skills/a/SKILL.md", "hooks/agent_guard.py",
                                 "settings.json", "stack.env", "rules/x.md", "magg/config.json",
                                 "magg/k8s-mcp.toml"])
def test_in_scope_accepts(rel):
    assert st.in_scope(rel)


def test_staged_magg_side_file_is_planned(conf, tmp_path):
    # install.sh stages magg/k8s-mcp.toml next to magg/config.json; the plan must install it
    s = str(tmp_path / "s")
    write(os.path.join(s, "magg", "k8s-mcp.toml"), "read_only = true\n")
    plan = st.make_plan(conf, s, str(tmp_path / "r.json"))
    assert "magg/k8s-mcp.toml" in plan["added"]


def test_drift_between_stage_and_apply_aborts(conf, tmp_path):
    s, root = str(tmp_path / "s"), str(tmp_path / "bk")
    os.makedirs(s)
    snap = st.stage(conf, s, str(tmp_path / "snap.json"))
    write(os.path.join(s, "settings.json"), '{"a": 1}\n')          # the render changed it
    plan = st.make_plan(conf, s, str(tmp_path / "none.json"))
    assert plan["changed"] == ["settings.json"]
    write(os.path.join(conf, "settings.json"), '{"mine": true}\n')  # someone else saved it meanwhile
    assert st.drifted(conf, snap) == ["settings.json"]
    with pytest.raises(SystemExit) as e:
        st.apply_plan(conf, s, plan, root, "c0", snap=snap)
    assert "changed while the installer ran" in str(e.value)
    assert open(os.path.join(conf, "settings.json")).read() == '{"mine": true}\n'
    assert not os.path.exists(root) or not [d for d in os.listdir(root) if not d.startswith(".")]
    # the CLI's plan step refuses too
    assert st.main(["x", "plan", conf, s, str(tmp_path / "r.json"), str(tmp_path / "p.json"),
                    str(tmp_path / "snap.json")]) == 1


def test_apply_without_drift_works(conf, tmp_path):
    s, root = str(tmp_path / "s"), str(tmp_path / "bk")
    os.makedirs(s)
    snap = st.stage(conf, s)
    write(os.path.join(s, "settings.json"), '{"a": 1}\n')
    plan = st.make_plan(conf, s, str(tmp_path / "none.json"))
    bdir = st.apply_plan(conf, s, plan, root, "c0", snap=snap)
    assert bdir and open(os.path.join(conf, "settings.json")).read() == '{"a": 1}\n'
    assert oct(os.stat(root).st_mode & 0o777) == "0o700"


def test_unsafe_plan_paths_refused(conf, tmp_path):
    plan = {"added": [], "changed": [], "removed": ["agents/../../../victim"], "keep_linked": True}
    with pytest.raises(SystemExit) as e:
        st.apply_plan(conf, str(tmp_path), plan, str(tmp_path / "bk"), "c0")
    assert "outside the config dir" in str(e.value)


def test_symlinked_scope_dir_is_never_pruned(conf, tmp_path):
    out = tmp_path / "dotfiles-skills"
    write(str(out / "precious.txt"), "mine\n")
    write(str(out / "a" / "SKILL.md"), "a\n")
    os.symlink(str(out), os.path.join(conf, "skills"))
    assert st.linked_dirs(conf) == {"skills": os.path.realpath(str(out))}
    s = str(tmp_path / "s")
    os.makedirs(s)
    snap = st.stage(conf, s)
    os.unlink(os.path.join(s, "skills", "precious.txt"))           # the render pruned it
    plan = st.make_plan(conf, s, str(tmp_path / "none.json"))
    assert plan["removed"] == []
    assert any("skills/precious.txt: kept" in n for n in plan["notes"])
    st.apply_plan(conf, s, plan, str(tmp_path / "bk"), "c0", snap=snap)
    assert (out / "precious.txt").exists()
    # a hand-made plan that removes through the link is refused as well
    bad = {"added": [], "changed": [], "removed": ["skills/precious.txt"], "keep_linked": True}
    with pytest.raises(SystemExit):
        st.apply_plan(conf, s, bad, str(tmp_path / "bk"), "c0")
    assert (out / "precious.txt").exists()


def test_per_skill_symlink_replaced_by_the_stacks_skill(conf, tmp_path):
    """skills/ is a real dir, skills/pe a link out of C: the plan removes the link and adds the
    stack's files below the same name; that is not a write through the link (review round 2)."""
    out = tmp_path / "dotfiles-pe"
    write(str(out / "SKILL.md"), "mine\n")
    os.makedirs(os.path.join(conf, "skills"))
    os.symlink(str(out), os.path.join(conf, "skills", "pe"))
    s = str(tmp_path / "s")
    os.makedirs(s)
    snap = st.stage(conf, s)
    os.unlink(os.path.join(s, "skills", "pe"))                     # the render: the stack's skill
    write(os.path.join(s, "skills", "pe", "SKILL.md"), "stack\n")
    plan = st.make_plan(conf, s, str(tmp_path / "none.json"))
    assert plan["removed"] == ["skills/pe"] and plan["added"] == ["skills/pe/SKILL.md"]
    assert st.unsafe_paths(conf, plan) == []
    assert st.main(["x", "plan", conf, s, str(tmp_path / "r.json"), str(tmp_path / "p.json")]) == 0
    bdir = st.apply_plan(conf, s, plan, str(tmp_path / "bk"), "c0", snap=snap)
    pe = os.path.join(conf, "skills", "pe")
    assert not os.path.islink(pe) and open(os.path.join(pe, "SKILL.md")).read() == "stack\n"
    assert (out / "SKILL.md").read_text() == "mine\n"
    assert os.readlink(os.path.join(bdir, "files", "skills", "pe")) == str(out)


def test_link_inside_a_symlinked_skills_dir_is_never_written_through(conf, tmp_path):
    """skills -> dot/skills and dot/skills/pe -> pe-local (yours): the stack's skills/pe files are
    skipped with a note, never written into pe-local unsaved (review round 3, HIGH)."""
    dot = tmp_path / "dot" / "skills"
    write(str(dot / "pe-local" / "SKILL.md"), "mine\n")
    os.symlink("pe-local", str(dot / "pe"))
    os.symlink(str(dot), os.path.join(conf, "skills"))
    s = str(tmp_path / "s")
    os.makedirs(s)
    snap = st.stage(conf, s)
    staged = os.path.join(s, "skills", "pe")
    if os.path.islink(staged):
        os.unlink(staged)
    else:
        import shutil
        shutil.rmtree(staged)
    write(os.path.join(staged, "SKILL.md"), "stack\n")
    write(os.path.join(s, "skills", "other", "SKILL.md"), "other\n")
    plan = st.make_plan(conf, s, str(tmp_path / "none.json"))
    assert plan["removed"] == [] and "skills/pe/SKILL.md" not in plan["added"]
    assert "skills/other/SKILL.md" in plan["added"]
    pe_notes = [n for n in plan["notes"] if n.startswith("skills/pe:")]
    assert len(pe_notes) == 1 and pe_notes[0].startswith(
        "skills/pe: kept (a link inside your symlinked skills/)"), pe_notes
    assert st.unsafe_paths(conf, plan) == []
    st.apply_plan(conf, s, plan, str(tmp_path / "bk"), "c0", snap=snap)
    assert (dot / "pe-local" / "SKILL.md").read_text() == "mine\n"
    assert os.readlink(str(dot / "pe")) == "pe-local"
    assert (dot / "other" / "SKILL.md").read_text() == "other\n"
    # a hand-made plan that writes through that inner link is refused
    bad = {"added": ["skills/pe/SKILL.md"], "changed": [], "removed": [], "keep_linked": True}
    assert st.unsafe_paths(conf, bad) == ["skills/pe/SKILL.md"]


def test_writes_below_a_kept_symlink_still_refused(conf, tmp_path):
    """The same layout, but a plan that keeps the link and adds below it would write out of C."""
    out = tmp_path / "dotfiles-pe"
    out.mkdir()
    os.makedirs(os.path.join(conf, "skills"))
    os.symlink(str(out), os.path.join(conf, "skills", "pe"))
    plan = {"added": ["skills/pe/SKILL.md"], "changed": [], "removed": [], "keep_linked": True}
    assert st.unsafe_paths(conf, plan) == ["skills/pe/SKILL.md"]
    # a link the plan removes lower down doesn't clear a kept link above it
    os.makedirs(str(out / "sub"))
    os.symlink(str(tmp_path), str(out / "sub" / "x"))
    deep = {"added": ["skills/pe/sub/x/y.md"], "changed": [], "removed": ["skills/pe/sub/x"],
            "keep_linked": True}
    assert "skills/pe/sub/x/y.md" in st.unsafe_paths(conf, deep)
    with pytest.raises(SystemExit):
        st.apply_plan(conf, str(tmp_path / "s"), plan, str(tmp_path / "bk"), "c0")
    assert list(out.iterdir()) == [out / "sub"]


def test_plan_cli_refuses_what_apply_refuses(conf, tmp_path, capsys, monkeypatch):
    """--dry-run runs the CLI's plan step: it reports the refusal the real run would hit."""
    monkeypatch.setattr(st, "unsafe_paths", lambda c, plan: ["skills/pe/SKILL.md"])
    s = str(tmp_path / "s")
    os.makedirs(s)
    st.stage(conf, s)
    assert st.main(["x", "plan", conf, s, str(tmp_path / "r.json"), str(tmp_path / "p.json")]) == 1
    assert "refusing paths outside the config dir" in capsys.readouterr().err


def test_backup_root_symlink_refused(tmp_path):
    real = tmp_path / "elsewhere"
    real.mkdir()
    link = tmp_path / "state" / "claude-agent-stack-backups"
    link.parent.mkdir()
    os.symlink(str(real), str(link))
    with pytest.raises(SystemExit) as e:
        st.ensure_root(str(link))
    assert "symlink" in str(e.value)
    with pytest.raises(SystemExit):
        st.new_backup_dir(str(link))
    assert list(real.iterdir()) == []


def test_backup_root_created_private(tmp_path):
    root = str(tmp_path / "bk")
    assert st.ensure_root(root) is True
    assert oct(os.stat(root).st_mode & 0o777) == "0o700"
    os.chmod(root, 0o755)
    assert st.ensure_root(root) is False
    assert oct(os.stat(root).st_mode & 0o777) == "0o700"


def test_copy_private_never_follows_a_planted_link(tmp_path):
    src, victim = tmp_path / "src", tmp_path / "victim"
    src.write_text("secret\n")
    victim.write_text("keep\n")
    dst = tmp_path / "dst"
    os.symlink(str(victim), str(dst))
    with pytest.raises(OSError):
        st.copy_private(str(src), str(dst))
    assert victim.read_text() == "keep\n"


def _backup_with_link(conf, root, target):
    bdir = st.empty_backup(conf, root, "c0")
    meta = json.load(open(os.path.join(bdir, "backup.json")))
    meta["entries"]["agents/ext.md"] = {"type": "l", "target": target}
    st.write_json(os.path.join(bdir, "backup.json"), meta)
    return bdir


def test_restore_skips_links_leaving_the_config_dir(conf, tmp_path, capsys):
    root = str(tmp_path / "bk")
    bdir = _backup_with_link(conf, root, str(tmp_path / "outside.md"))
    work = str(tmp_path / "w1")
    os.makedirs(work)
    st.restore(conf, bdir, root, work, "c1", str(tmp_path))
    assert not os.path.lexists(os.path.join(conf, "agents", "ext.md"))
    assert "skipped agents/ext.md" in capsys.readouterr().out
    work = str(tmp_path / "w2")
    os.makedirs(work)
    st.restore(conf, bdir, root, work, "c1", str(tmp_path), force=True)
    assert os.readlink(os.path.join(conf, "agents", "ext.md")) == str(tmp_path / "outside.md")


def test_restore_keeps_links_inside_the_config_dir(conf, tmp_path):
    root = str(tmp_path / "bk")
    bdir = _backup_with_link(conf, root, "coder.md")               # agents/ext.md -> agents/coder.md
    work = str(tmp_path / "w")
    os.makedirs(work)
    st.restore(conf, bdir, root, work, "c1", str(tmp_path))
    assert os.readlink(os.path.join(conf, "agents", "ext.md")) == "coder.md"


def test_prefetch_warms_the_servers_cache():
    """The MCP prefetch fills the cache the servers use ($STACK_CACHE, rendered into their env),
    not ~/.cache/uv and ~/.npm (review round 2, LOW)."""
    text = open(os.path.join(ROOT, "install.sh"), encoding="utf-8").read()
    block = text[text.index('say "8/11 MCP dependency prefetch"'):text.index('say "9/11')]
    body = block[block.index("\n  (\n"):block.index("\n  )\n")]
    assert 'export UV_CACHE_DIR="$STACK_CACHE/uv" npm_config_cache="$STACK_CACHE/npm"' in body
    for cmd in ("uv run --quiet --script", "uvx --quiet markitdown-mcp", "uv tool run", "npx -y"):
        assert cmd in body, cmd


def test_lsp_npm_installs_pinned_without_scripts():
    """C7-residual: --with-lsp installs pinned versions with install scripts off."""
    text = open(os.path.join(ROOT, "install.sh"), encoding="utf-8").read()
    npm = [ln for ln in text.splitlines() if "npm install -g" in ln and not ln.lstrip().startswith("#")]
    assert npm and all("--ignore-scripts" in ln for ln in npm), npm
    import re
    for var in ("PYRIGHT_PIN", "TS_PIN"):
        assert re.search(r'(?m)^\s*%s="[a-z-]+@\d+\.\d+\.\d+"$' % var, text), var
    assert re.search(r'TSLS="typescript-language-server@\d+\.\d+\.\d+"', text)
    assert 'npm_g pyright ' not in text and 'npm_g "$TSLS" typescript ' not in text


def test_tools_venv_lock_covers_the_stack_imports():
    """The tools venv (requirements/tools.in -> tools.txt) holds every third-party import of the
    stack's scripts, MCP servers and tests, is locked like sci (hashes, 3.13, arm64 wheels, same
    cooldown), and install.sh syncs it while doctor.sh checks the same imports."""
    import ast
    import re
    req = os.path.join(ROOT, "requirements")
    norm = lambda n: re.sub(r"[-_.]+", "-", n).lower()  # noqa: E731
    dist = {"PIL": "pillow"}
    left_out = {"claude-agent-sdk"}       # inside the cooldown at the last lock (requirements/README.md)
    dirs = ["dot-claude/bin", "dot-claude/mcp", "dot-claude/hooks", "lib", "tests"]
    files = [os.path.join(ROOT, d, f) for d in dirs for f in sorted(os.listdir(os.path.join(ROOT, d)))
             if f.endswith(".py")]
    local = {os.path.basename(f)[:-3] for f in files}
    need = {}
    for f in files:
        for n in ast.walk(ast.parse(open(f, encoding="utf-8").read())):
            mods = [a.name for a in n.names] if isinstance(n, ast.Import) else \
                [n.module] if isinstance(n, ast.ImportFrom) and n.level == 0 and n.module else []
            for m in mods:
                top = m.split(".")[0]
                if top not in sys.stdlib_module_names and top not in local and top != "__future__":
                    need.setdefault(norm(dist.get(top, top)), set()).add(os.path.relpath(f, ROOT))
    names = lambda text: {norm(m.group(1)) for m in re.finditer(r"(?m)^([A-Za-z0-9][A-Za-z0-9._-]*)", text)}  # noqa: E731
    tin = open(os.path.join(req, "tools.in"), encoding="utf-8").read()
    have = names(tin)
    missing = {k: sorted(v) for k, v in need.items() if k not in have | left_out}
    assert not missing, missing
    txt = open(os.path.join(req, "tools.txt"), encoding="utf-8").read()
    sci = open(os.path.join(req, "sci.txt"), encoding="utf-8").read()
    cmd = txt.splitlines()[1]
    for flag in ("--generate-hashes", "--python-version 3.13", "--python-platform aarch64-apple-darwin",
                 "--only-binary :all:"):
        assert flag in cmd, flag
    cutoff = lambda t: re.search(r"--exclude-newer (\S+)", t.splitlines()[1]).group(1)  # noqa: E731
    assert cutoff(txt) == cutoff(sci)
    pins = re.findall(r"(?m)^([A-Za-z0-9][A-Za-z0-9._-]*)==\S+ \\\n((?:\s+--hash=sha256:[0-9a-f]{64}.*\n)+)", txt)
    assert len(pins) == len(re.findall(r"(?m)^[A-Za-z0-9][A-Za-z0-9._-]*==", txt)) > 0
    assert have <= {norm(p) for p, _ in pins}
    inst = open(os.path.join(ROOT, "install.sh"), encoding="utf-8").read()
    assert 'TOOLS_REQS="$HERE/requirements/tools.txt"' in inst
    assert 'venv_sync tools "$TOOLS_REQS" --only-binary :all:' in inst
    imports = re.search(r"TOOLS_IMPORTS='([^']+)'", inst).group(1)
    doctor = open(os.path.join(ROOT, "dot-claude", "bin", "doctor.sh"), encoding="utf-8").read()
    assert f'"$C/venvs/tools/bin/python" -c \'{imports}\'' in doctor


def test_restore_keeps_the_current_entry_where_it_skips_a_link(conf, tmp_path, capsys):
    """R3-RESTORE-LINK: skills/pe was a link out of C before the install, which put the stack's
    skill there. --restore without --force skips the link and keeps the stack's skill (it used to
    remove it too, leaving the skill missing); --force puts the link back."""
    out = tmp_path / "dotfiles-pe"
    write(str(out / "SKILL.md"), "mine\n")
    write(os.path.join(conf, "skills", "pe", "SKILL.md"), "stack\n")
    write(os.path.join(conf, "skills", "pe", "ref", "a.md"), "ref\n")
    write(os.path.join(conf, "agents", "new.md"), "added\n")
    root = str(tmp_path / "bk")
    bdir = st.empty_backup(conf, root, "c0")
    meta = json.load(open(os.path.join(bdir, "backup.json")))
    meta["entries"]["skills/pe"] = {"type": "l", "target": str(out)}
    meta["added"] = ["skills/pe/SKILL.md", "skills/pe/ref/a.md", "agents/new.md"]
    st.write_json(os.path.join(bdir, "backup.json"), meta)
    work = str(tmp_path / "w1")
    os.makedirs(work)
    st.restore(conf, bdir, root, work, "c1", str(tmp_path))
    assert "skipped skills/pe" in capsys.readouterr().out
    pe = os.path.join(conf, "skills", "pe")
    assert not os.path.islink(pe) and open(os.path.join(pe, "SKILL.md")).read() == "stack\n"
    assert os.path.exists(os.path.join(pe, "ref", "a.md"))
    assert not os.path.exists(os.path.join(conf, "agents", "new.md"))   # other added files go
    work = str(tmp_path / "w2")
    os.makedirs(work)
    st.restore(conf, bdir, root, work, "c1", str(tmp_path), force=True)
    assert os.readlink(pe) == str(out) and (out / "SKILL.md").read_text() == "mine\n"


def test_file_link_inside_a_symlinked_agents_dir_is_never_replaced(conf, tmp_path):
    """R3-WTL-INNER: agents -> dot/agents and dot/agents/coder.md -> coder-local.md (yours): with
    --write-through-links the stack's coder.md is skipped with a note, never written over the link
    in your checkout; the other agents are written through."""
    dot = tmp_path / "dot" / "agents"
    write(str(dot / "coder-local.md"), "mine\n")
    os.symlink("coder-local.md", str(dot / "coder.md"))
    import shutil
    shutil.rmtree(os.path.join(conf, "agents"))
    os.symlink(str(dot), os.path.join(conf, "agents"))
    s = str(tmp_path / "s")
    os.makedirs(s)
    snap = st.stage(conf, s)
    staged = os.path.join(s, "agents", "coder.md")
    os.unlink(staged)                                   # the render writes the stack's file
    write(staged, "stack coder\n")
    write(os.path.join(s, "agents", "writer.md"), "stack writer\n")
    plan = st.make_plan(conf, s, str(tmp_path / "none.json"))
    assert "agents/coder.md" not in plan["changed"] + plan["added"] + plan["removed"]
    assert plan["added"] == ["agents/writer.md"]
    notes = [n for n in plan["notes"] if n.startswith("agents/coder.md:")]
    assert len(notes) == 1 and "a link inside your symlinked agents/" in notes[0], plan["notes"]
    st.apply_plan(conf, s, plan, str(tmp_path / "bk"), "c0", snap=snap)
    assert os.readlink(str(dot / "coder.md")) == "coder-local.md"
    assert (dot / "coder-local.md").read_text() == "mine\n"
    assert (dot / "writer.md").read_text() == "stack writer\n"


def test_every_shipped_hook_script_matches_stack_hook_re():
    """install.sh tells the stack's hook entries from yours with STACK_HOOK_RE; a shipped hook script
    it misses is kept as yours on each re-run and the shipped copy appended again (web_caps.py, 77f5638)."""
    import re
    src = open(os.path.join(ROOT, "install.sh"), encoding="utf-8").read()
    m = re.search(r'^STACK_HOOK_RE = re\.compile\(r"([^"]+)"\)$', src, re.M)
    assert m, "STACK_HOOK_RE not found in install.sh"
    stack_re = re.compile(m.group(1))
    settings = json.load(open(os.path.join(ROOT, "dot-claude", "settings.json"), encoding="utf-8"))
    cmds = [x.get("command", "") for groups in settings.get("hooks", {}).values() for g in groups
            for x in g.get("hooks", [])]
    assert cmds
    missed = sorted({c for c in cmds if not stack_re.search(c)})
    assert not missed, "hook commands STACK_HOOK_RE misses: %s" % missed


# ---------------------------------------------------------------- S6 W4: learned limits in install.sh
def _scratch_repo(dst, settings_env=None):
    """The working tree (tracked and untracked files) as a scratch repository on main, as
    tests/install_smoke.sh builds it (install.sh runs only from main). settings_env: env entries
    put back into its dot-claude/settings.json (an older stack version)."""
    import shutil
    import subprocess
    out = subprocess.run(["git", "-C", ROOT, "ls-files", "-z", "--cached", "--others",
                          "--exclude-standard"], stdout=subprocess.PIPE, check=True).stdout.decode()
    for rel in filter(None, out.split("\0")):
        s = os.path.join(ROOT, rel)
        if not os.path.lexists(s):
            continue
        d = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy2(s, d, follow_symlinks=False)
    if settings_env:
        p = os.path.join(dst, "dot-claude", "settings.json")
        with open(p, encoding="utf-8") as f:
            s = json.load(f)
        s["env"].update(settings_env)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2)
    git = ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "-c",
           "init.defaultBranch=main", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
           "-C", dst]
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "snapshot"]):
        subprocess.run(git + args, check=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    return dst


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def _uv_python_dir():
    import shutil
    import subprocess
    uv = shutil.which("uv")
    out = subprocess.run([uv, "python", "dir"], capture_output=True, text=True, check=False).stdout.strip() \
        if uv else ""
    if not out:
        pytest.skip("needs uv (the installer links uv's managed Python 3.13 as stack-python)")
    return out


def _install(repo, home, conf, *extra):
    p = _run_install(repo, home, conf, *extra)
    assert p.returncode == 0, (p.stdout[-3000:], p.stderr[-3000:])
    return p.stdout + p.stderr


def _run_install(repo, home, conf, *extra, env_extra=None):
    """install.sh --no-mcp --no-plugins --no-deps --no-profile into a scratch HOME and config dir;
    env_extra: variables added last (STACK_PYTHON, UV_PYTHON_INSTALL_DIR, ...)."""
    import subprocess
    os.makedirs(os.path.join(home, "tmp"), exist_ok=True)
    # macOS mktemp without a template ignores TMPDIR (it asks for the per-user temp dir, which a
    # sandboxed test run may not write): give the scratch install one that uses TMPDIR
    shim = os.path.join(home, "shim")
    os.makedirs(shim, exist_ok=True)
    with open(os.path.join(shim, "mktemp"), "w") as f:
        f.write('#!/bin/sh\ncase "$*" in *XXX*) exec /usr/bin/mktemp "$@" ;; esac\n'
                'exec /usr/bin/mktemp "$@" "${TMPDIR:-/tmp}/tmp.XXXXXXXXXX"\n')
    os.chmod(os.path.join(shim, "mktemp"), 0o755)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("STACK_", "CLAUDE_", "XDG_")) and k not in (
               "EXA_API_KEY", "JINA_API_KEY", "HF_TOKEN", "WANDB_API_KEY", "GITHUB_TOKEN", "GH_TOKEN")}
    # the scratch HOME hides uv's managed Pythons: point uv at the real ones, so the installer finds
    # (never installs) the 3.13 it links as stack-python
    env.setdefault("UV_PYTHON_INSTALL_DIR", _uv_python_dir())
    env.update(HOME=home, CLAUDE_CONFIG_DIR=conf, XDG_STATE_HOME=os.path.join(home, ".local", "state"),
               TMPDIR=os.path.join(home, "tmp"), STACK_ALLOW_NON_MACOS="1", FAKE_CLAUDE_JSON=os.path.join(home, ".claude.json"),
               STACK_CLAUDE_JSON=os.path.join(home, ".claude.json"),
               PATH=os.pathsep.join((os.path.join(repo, "tests", "fake-claude"), shim, env.get("PATH", ""))))
    env.update(env_extra or {})
    return subprocess.run([os.path.join(repo, "install.sh"), "--no-mcp", "--no-plugins", "--no-deps",
                           "--no-profile", *extra], env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=900, check=False)


@pytest.mark.skipif(not os.path.isdir(os.path.join(ROOT, ".git")) and not os.path.isfile(
    os.path.join(ROOT, ".git")), reason="needs the stack's git checkout")
def test_install_seeds_live_json_once_and_retracts_the_budget_env(tmp_path):
    """install.sh stages stack_limits.py and its seed, creates live.json from the seed once (a
    second install leaves it byte-identical), and retracts STACK_PROMPT_CTX_BUDGET /
    STACK_SESSION_CTX_BUDGET while they hold an earlier version's shipped value; a value the user
    set stays (an override, origin env)."""
    home = str(tmp_path / "home")
    os.makedirs(home)
    conf = os.path.join(home, ".claude")
    old = _scratch_repo(str(tmp_path / "old"), {"STACK_PROMPT_CTX_BUDGET": "100000000",
                                                "STACK_SESSION_CTX_BUDGET": "666000000"})
    new = _scratch_repo(str(tmp_path / "new"))
    log = _install(old, home, conf)
    live = os.path.join(home, ".local", "state", "claude-agent-stack", "limits", "live.json")
    assert os.path.isfile(live), log[-2000:]
    first = _read(live)
    doc = json.loads(first)
    assert doc["vars"]["hard.prompt"]["value"] == 100000000 and doc["version"] == 1
    for f in ("stack_limits.py", "stack_limits_seed.json", "agent_effort.json"):
        assert os.path.isfile(os.path.join(conf, "hooks", f)), f
    assert os.stat(os.path.join(conf, "hooks", "stack_limits.py")).st_mode & 0o111
    sp = os.path.join(conf, "settings.json")
    s = json.loads(_read(sp))
    assert s["env"]["STACK_PROMPT_CTX_BUDGET"] == "100000000"
    s["env"]["STACK_SESSION_CTX_BUDGET"] = "777000000"            # the user's own value
    with open(sp, "w") as f:
        json.dump(s, f, indent=2)
    log = _install(new, home, conf, "--yes")
    assert _read(live) == first                                  # never rewritten
    e = json.loads(_read(sp))["env"]
    assert "STACK_PROMPT_CTX_BUDGET" not in e, log[-2000:]
    assert e["STACK_SESSION_CTX_BUDGET"] == "777000000"
    assert "retracted stack env STACK_PROMPT_CTX_BUDGET=100000000" in log
    hooks = json.loads(_read(sp))["hooks"]
    assert not any(re.search(r'stack_usage(\.py")? start', h.get("command", "")) for g in hooks["SessionStart"]
                   for h in g["hooks"])
    _install(new, home, conf)                                    # a plain re-run
    assert _read(live) == first
    assert json.loads(_read(sp))["env"]["STACK_SESSION_CTX_BUDGET"] == "777000000"


@pytest.mark.skipif(not os.path.isdir(os.path.join(ROOT, ".git")) and not os.path.isfile(
    os.path.join(ROOT, ".git")), reason="needs the stack's git checkout")
def test_install_reseeds_unlearned_limits_and_keeps_learned_ones(tmp_path):
    """A live.json written by an older stack (hard.session still at its old seed 666M, untouched)
    takes the shipped seed on install; a frozen and a learned value stay. A session started after
    the install snapshots hard.session = 1.92B with origin live."""
    import subprocess
    home = str(tmp_path / "home")
    os.makedirs(home)
    conf = os.path.join(home, ".claude")
    repo = _scratch_repo(str(tmp_path / "repo"))
    log = _install(repo, home, conf)
    live = os.path.join(home, ".local", "state", "claude-agent-stack", "limits", "live.json")
    assert os.path.isfile(live), log[-2000:]
    doc = json.loads(_read(live))
    V = doc["vars"]
    V["hard.session"]["value"] = 666000000
    V["hard.prompt"]["frozen"] = 120000000
    V["soft.agent.coder"].update(value=25000000, status="supported", n=7, changed=1.0e9, prev=19000000,
                                 recent=[{"dec": "step", "sign": 1, "rel": 0.3}])
    with open(live, "w") as f:
        json.dump(doc, f)
    log = _install(repo, home, conf, "--yes")
    assert "reseeded from the new seed: hard.session 666M -> 1.92B" in log, log[-2000:]
    V2 = json.loads(_read(live))["vars"]
    assert V2["hard.session"]["value"] == 1920000000 and V2["hard.session"]["frozen"] is None
    assert V2["hard.session"]["status"] == "unset"
    assert V2["hard.prompt"]["frozen"] == 120000000 and V2["soft.agent.coder"]["value"] == 25000000
    hooks = os.path.join(conf, "hooks")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("STACK_", "CLAUDE_", "XDG_"))}
    env.update(HOME=home, CLAUDE_CONFIG_DIR=conf, XDG_STATE_HOME=os.path.join(home, ".local", "state"))
    subprocess.run([os.path.join(conf, "bin", "stack-python"), "-c", "import sys; sys.path.insert(0, sys.argv[1]); import stack_limits "
                    "as L; L.apply_and_snapshot({'session_id': 's-after', 'source': 'startup'}, spawn=False)",
                    hooks], env=env, check=True)
    out = subprocess.run([os.path.join(conf, "bin", "stack-python"), os.path.join(hooks, "stack_limits.py"), "show", "hard.session*"],
                         env=env, check=True, stdout=subprocess.PIPE, text=True).stdout
    row = [x for x in out.splitlines() if x.startswith("hard.session ")][0].split()
    assert row[1:3] == ["1.92B", "1.92B"] and row[-1] == "live", out
