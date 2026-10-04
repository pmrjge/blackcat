"""install.sh --diff: what differs between the repo's dot-claude/ and an installed config dir. Read-only.

  stack_diff.py --repo REPO [--config-dir PATH]

Target: --config-dir > CLAUDE_CONFIG_DIR > ~/.claude (as install.sh, without its safety checks: nothing
is written). Compared, per area: agents/, rules/, skills/ (claude.ai's
synced/ aside), the hooks/, bin/ (the stack-python link aside), mcp/ (vendor/ aside) and magg/ files
install.sh stages, stack-plugins/, settings.json's hook wiring (event, matcher, command) and magg's
catalog entries (minus enabled/kits).

Text is compared after the installer's own render: __CLAUDE_DIR__, __HOME__, __STACK_*__ are filled in;
tool paths it found at install time (__UV__, __PYTHON3__, ...) match any path, consistently within a
file; agents also go through install.sh's drop_servers and mcp_cache_env (their source is
read from install.sh, so the two cannot drift; if that read fails, a note says so).

Exit 0 always (differences are output, not errors); 2 on a usage error (unknown option, a target that
is a file). Writes nothing: run it with python3 -B; no temp file, no cache, no git lock.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import subprocess
import sys

KNOWN_DIRS = ("hooks", "bin", "mcp", "magg")
TOOL_PLACEHOLDERS = ("__PYTHON3__", "__UV__", "__UVX__", "__NPX__", "__NODE__", "__MAGG__", "__HUETENSION__")
PLACEHOLDER_RE = re.compile(r"__[A-Z][A-Z0-9_]*__")
SKIP_NAMES = (".DS_Store", "__pycache__")


def usage(msg):
    sys.stderr.write("install.sh --diff: %s\nusage: ./install.sh --diff [--config-dir PATH]\n" % msg)
    sys.exit(2)


# ---------------------------------------------------------------- the installer's own code

def extract(src, name):
    """Source of the top-level `def name(` or `name = ...` statement in install.sh's Python."""
    m = re.search(r"(?m)^(?:def %s\(|%s = )" % (re.escape(name), re.escape(name)), src)
    if not m:
        raise KeyError(name)
    lines = src[m.start():].split("\n")
    out = [lines[0]]
    for line in lines[1:]:
        if line and not line[0].isspace() and not line.startswith((")", "]", "}")):
            break
        out.append(line)
    return "\n".join(out).rstrip() + "\n"


def installer_code(install_text, subs):
    """drop_servers, mcp_cache_env, MACOS_ONLY_SERVERS from install.sh."""
    ns = {"re": re, "json": json, "os": os, "SUBS": subs}
    for name in ("MACOS_ONLY_SERVERS", "drop_servers", "MCP_CACHE_ENV", "mcp_cache_env"):
        exec(compile(extract(install_text, name), "install.sh:" + name, "exec"), ns)
    return ns


def staged_files(install_text):
    """{installed rel path: repo rel path} of the files install.sh stages one by one (stage_script
    lines, `for f in ...` loops, and the copies it takes from tests/)."""
    out = {}
    for d, f in re.findall(r"stage_script\s+\d+\s+\"?(%s)/([A-Za-z0-9_.-]+)" % "|".join(KNOWN_DIRS), install_text):
        out["%s/%s" % (d, f)] = "dot-claude/%s/%s" % (d, f)
    for names, d in re.findall(r"(?m)^\s*for f in ([^;\n]+); do[^\n]*stage_script\s+\d+\s+\"(%s)/\$f\""
                               % "|".join(KNOWN_DIRS), install_text):
        for f in names.split():
            out["%s/%s" % (d, f)] = "dot-claude/%s/%s" % (d, f)
    for names, d, src in re.findall(r"(?m)^for f in ([^;\n]+); do\n\s*rm -rf \"\$S/(\w+)/\$f\" && "
                                    r"cp \"\$HERE/([\w-]+)/\$f\"", install_text):
        for f in names.split():
            out["%s/%s" % (d, f)] = "%s/%s" % (src, f)
    return out


# ---------------------------------------------------------------- comparison

class Matcher:
    """Text equality after rendering, with the tool placeholders as consistent wildcards."""

    def __init__(self, subs):
        self.subs = subs
        self.learned = {}

    def render(self, text):
        for k, v in self.subs.items():
            text = text.replace(k, v)
        return text

    def same(self, repo_text, installed_text):
        r = self.render(repo_text)
        if not any(p in r for p in TOOL_PLACEHOLDERS):
            return r == installed_text
        parts, seen = [], set()
        for piece in re.split(r"(%s)" % "|".join(TOOL_PLACEHOLDERS), r):
            if piece in TOOL_PLACEHOLDERS:
                g = piece.strip("_")
                parts.append("(?P=%s)" % g if g in seen else r"(?P<%s>[^\s\"',]+)" % g)
                seen.add(g)
            else:
                parts.append(re.escape(piece))
        m = re.fullmatch("".join(parts), installed_text, re.S)
        if m:
            for g, v in m.groupdict().items():
                self.learned.setdefault("__%s__" % g, v)
        return bool(m)

    def show(self, text):
        """The render, with the tool paths learned from matching files where known."""
        r = self.render(text)
        for k, v in self.learned.items():
            r = r.replace(k, v)
        return r

    def counts(self, repo_text, installed_text):
        """(+lines, -lines) from the repo's render to the installed text."""
        r = self.show(repo_text)
        add = rem = 0
        for line in difflib.unified_diff(r.splitlines(), installed_text.splitlines(), lineterm="", n=0):
            if line.startswith(("+++", "---", "@@")):
                continue
            add += line.startswith("-")       # in the repo, not installed: the install would add it
            rem += line.startswith("+")
        return add, rem


def read(path):
    with open(path, "rb") as f:
        return f.read()


def walk(base):
    """Relative file paths under base (symlinks listed, not followed; caches skipped)."""
    out = set()
    if not os.path.isdir(base):
        return out
    for root, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_NAMES and not os.path.islink(os.path.join(root, d)))
        links = [d for d in os.listdir(root) if os.path.islink(os.path.join(root, d)) and os.path.isdir(os.path.join(root, d))]
        for fn in list(files) + links:
            if fn in SKIP_NAMES or fn.endswith(".pyc"):
                continue
            out.add(os.path.relpath(os.path.join(root, fn), base))
    return out


class Diff:
    def __init__(self, repo, c, subs, install_text):
        self.repo, self.c, self.m = repo, c, Matcher(subs)
        self.rows = {}          # area -> list of (sign, rel, note)
        self.notes = []
        self.install_text = install_text
        try:
            self.code = installer_code(install_text, subs)
        except Exception as exc:  # noqa: BLE001 - install.sh changed shape: say so, compare plainly
            self.code = None
            self.notes.append("agents compared without install.sh's copy/server transforms (%s: %s)"
                              % (type(exc).__name__, exc))
        try:
            self.manifest = json.loads(read(os.path.join(c, ".stack-manifest.json")))
        except (OSError, ValueError):
            self.manifest = {}
        if not isinstance(self.manifest, dict):
            self.manifest = {}

    def add(self, area, sign, rel, note=""):
        self.rows.setdefault(area, []).append((sign, rel, note))

    def edited(self, rel, data):
        h = (self.manifest.get("files") or {}).get(rel)
        return bool(h) and hashlib.sha256(data).hexdigest() != h

    def compare(self, area, rel, repo_bytes, render, transform=None):
        """rel exists on both sides: compare and record a difference."""
        path = os.path.join(self.c, rel)
        try:
            inst = read(path)
        except OSError as exc:
            self.add(area, "?", rel, "unreadable: %s" % exc.strerror)
            return
        if not render:
            if inst != repo_bytes:
                self.add(area, "~", rel, "repo %d bytes, installed %d" % (len(repo_bytes), len(inst)))
            return
        try:
            rt, it = repo_bytes.decode("utf-8"), inst.decode("utf-8")
        except UnicodeDecodeError:
            if inst != repo_bytes:
                self.add(area, "~", rel, "binary differs")
            return
        if transform:
            rt = transform(rt)
        if not self.m.same(rt, it):
            a, r = self.m.counts(rt, it)
            note = "+%d -%d lines to install" % (a, r)
            if self.edited(rel, inst):
                note += "; edited since the last install"
            self.add(area, "~", rel, note)

    # -- areas

    def tree(self, area, repo_base, inst_rel, render, skip=()):
        """A directory the installer mirrors file by file."""
        rset = {p for p in walk(repo_base) if not p.endswith(".new")}
        if rset and not os.path.lexists(os.path.join(self.c, inst_rel)):
            self.add(area, "+", inst_rel + "/", "whole folder, %d files%s" % (
                len(rset), "; install.sh --no-plugins leaves it out" if inst_rel == "stack-plugins" else ""))
            return
        iset = {p for p in walk(os.path.join(self.c, inst_rel)) if not p.startswith(tuple(skip))}
        for p in sorted(rset - iset):
            self.add(area, "+", "%s/%s" % (inst_rel, p))
        for p in sorted(iset - rset):
            self.add(area, "-", "%s/%s" % (inst_rel, p))
        for p in sorted(rset & iset):
            self.compare(area, "%s/%s" % (inst_rel, p), read(os.path.join(repo_base, p)), render)

    def agents(self):
        src = os.path.join(self.repo, "dot-claude", "agents")
        targets = {f for f in sorted(os.listdir(src)) if f.endswith(".md")} if os.path.isdir(src) else set()
        inst = {p for p in walk(os.path.join(self.c, "agents")) if "/" not in p}
        for f in sorted(targets - inst):
            self.add("agents", "+", "agents/" + f)
        for f in sorted(inst - targets):
            self.add("agents", "-", "agents/" + f)
        ae_built = os.path.isfile(os.path.join(self.c, "mcp", "vendor", "after-effects-mcp", "build", "index.js"))
        for f in sorted(targets & inst):
            rel = "agents/" + f

            def transform(text, rel=rel):
                if not self.code:
                    return text
                k = self.code
                text = self.m.render(text)
                if sys.platform != "darwin":
                    text = k["drop_servers"](text, k["MACOS_ONLY_SERVERS"])
                elif rel == "agents/motion-designer.md" and not ae_built:
                    text = k["drop_servers"](text, ("after-effects",))
                if rel == "agents/researcher.md":
                    try:
                        installed = read(os.path.join(self.c, rel)).decode("utf-8", "replace")
                    except OSError:
                        installed = ""
                    if "mcpServers:\n  - spider\n" in installed:     # install.sh's SPIDER_REWRITE
                        text = re.sub(r"mcpServers:\n  - spider:\n(?:      .*\n)+", "mcpServers:\n  - spider\n", text)
                return k["mcp_cache_env"](text)
            self.compare("agents", rel, read(os.path.join(src, f)), True, transform)

    def skills(self):
        src = os.path.join(self.repo, "dot-claude", "skills")
        rnames = {d for d in os.listdir(src) if os.path.isdir(os.path.join(src, d))} if os.path.isdir(src) else set()
        ib = os.path.join(self.c, "skills")
        inames = {d for d in os.listdir(ib) if d not in SKIP_NAMES and d != "synced"} if os.path.isdir(ib) else set()
        for n in sorted(rnames - inames):
            self.add("skills", "+", "skills/%s/" % n, "whole skill")
        for n in sorted(inames - rnames):
            self.add("skills", "-", "skills/%s%s" % (n, "/" if os.path.isdir(os.path.join(ib, n)) else ""),
                     "whole skill")
        for n in sorted(rnames & inames):
            self.tree("skills", os.path.join(src, n), "skills/" + n, True)

    def staged(self):
        files = staged_files(self.install_text)
        for d in KNOWN_DIRS:
            area = d
            mine = {rel: srel for rel, srel in files.items() if rel.startswith(d + "/")}
            inst = {"%s/%s" % (d, p) for p in walk(os.path.join(self.c, d))
                    if not (d == "mcp" and p.startswith("vendor/")) and not (d == "magg" and p == "config.json")
                    and not (d == "magg" and p.startswith("kit.d/"))
                    and not (d == "bin" and p == "stack-python")}  # the installer's link to uv's Python
            for rel in sorted(set(mine) - inst):
                self.add(area, "+", rel)
            for rel in sorted(inst - set(mine)):
                self.add(area, "-", rel)
            for rel in sorted(set(mine) & inst):
                try:
                    data = read(os.path.join(self.repo, mine[rel]))
                except OSError:
                    self.add(area, "?", rel, "missing in the repo: %s" % mine[rel])
                    continue
                self.compare(area, rel, data, False)
            # repo files in these dirs that install.sh does not stage: informational
            repo_dir = os.path.join(self.repo, "dot-claude", d)
            for p in sorted(walk(repo_dir)):
                rel = "%s/%s" % (d, p)
                if rel not in mine and not (d == "magg" and p == "config.json"):
                    self.notes.append("dot-claude/%s is not installed by install.sh (not staged)" % rel)

    def settings_hooks(self):
        def wiring(data):
            out = []
            hooks = data.get("hooks") if isinstance(data, dict) else None
            for ev, groups in sorted(hooks.items() if isinstance(hooks, dict) else []):
                for g in groups if isinstance(groups, list) else []:
                    if not isinstance(g, dict) or not isinstance(g.get("hooks"), list):
                        continue
                    for h in g["hooks"]:
                        if isinstance(h, dict) and h.get("command"):
                            out.append((ev, g.get("matcher") or "", h["command"]))
            return out
        try:
            repo = wiring(json.loads(read(os.path.join(self.repo, "dot-claude", "settings.json"))))
        except (OSError, ValueError) as exc:
            self.notes.append("repo settings.json unreadable: %s" % exc)
            return
        p = os.path.join(self.c, "settings.json")
        if not os.path.exists(p):
            for ev, mt, cmd in repo:
                self.add("settings.json hooks", "+", "%s [%s] %s" % (ev, mt or "*", self.m.show(cmd)))
            return
        try:
            inst = wiring(json.loads(read(p)))
        except (OSError, ValueError) as exc:
            self.add("settings.json hooks", "?", "settings.json", "unreadable: %s" % exc)
            return
        used = set()
        for ev, mt, cmd in repo:
            hit = next((i for i, (e, m, c) in enumerate(inst)
                        if i not in used and e == ev and m == mt and self.m.same(cmd, c)), None)
            if hit is None:
                self.add("settings.json hooks", "+", "%s [%s] %s" % (ev, mt or "*", self.m.show(cmd)))
            else:
                used.add(hit)
        for i, (ev, mt, cmd) in enumerate(inst):
            if i not in used:
                self.add("settings.json hooks", "-", "%s [%s] %s" % (ev, mt or "*", cmd))

    def magg_catalog(self):
        try:
            repo = json.loads(read(os.path.join(self.repo, "dot-claude", "magg", "config.json"))).get("servers") or {}
        except (OSError, ValueError, AttributeError):
            return
        p = os.path.join(self.c, "magg", "config.json")
        try:
            inst = json.loads(read(p)).get("servers") or {}
        except FileNotFoundError:
            inst = {}
        except (OSError, ValueError, AttributeError) as exc:
            self.add("magg catalog", "?", "magg/config.json", "unreadable: %s" % exc)
            return

        def core(e):
            return json.dumps({k: v for k, v in e.items() if k not in ("enabled", "kits")}, sort_keys=True) \
                if isinstance(e, dict) else json.dumps(e)
        for k in sorted(set(repo) - set(inst)):
            self.add("magg catalog", "+", k)
        for k in sorted(set(inst) - set(repo)):
            self.add("magg catalog", "-", k, "yours or no longer shipped")
        for k in sorted(set(repo) & set(inst)):
            if not self.m.same(core(repo[k]), core(inst[k])):
                self.add("magg catalog", "~", k, "entry differs")

    def run(self):
        dot = os.path.join(self.repo, "dot-claude")
        steps = (("agents", self.agents),
                 ("rules", lambda: self.tree("rules", os.path.join(dot, "rules"), "rules", True)),
                 ("skills", self.skills), ("hooks, bin, mcp, magg", self.staged),
                 ("stack-plugins", lambda: self.tree("stack-plugins", os.path.join(dot, "stack-plugins"),
                                                     "stack-plugins", False)),
                 ("settings.json hooks", self.settings_hooks), ("magg catalog", self.magg_catalog))
        for area, step in steps:
            try:
                step()
            except Exception as exc:  # noqa: BLE001 - an area that can't be compared is a note; exit stays 0
                self.notes.append("%s: not compared (%s: %s)" % (area, type(exc).__name__, exc))


def git_head(repo):
    try:
        return subprocess.run(["git", "-C", repo, "rev-parse", "--short", "HEAD"], stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, timeout=10,
                              env=dict(os.environ, GIT_OPTIONAL_LOCKS="0")).stdout.decode().strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def main(argv):
    repo, cdir, cset = None, None, False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--repo" and i + 1 < len(argv):
            repo, i = argv[i + 1], i + 2
        elif a == "--config-dir" and i + 1 < len(argv):
            cdir, cset, i = argv[i + 1], True, i + 2
        else:
            usage("unknown argument %r" % a)
    if not repo or not os.path.isdir(os.path.join(repo, "dot-claude")):
        usage("--repo must name the stack checkout (with dot-claude/)")
    home = os.path.expanduser("~")
    # install.sh's own resolution (lexical: a symlinked ~/.claude keeps its name, as __CLAUDE_DIR__ does)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import install_state as ist
    try:
        raw, src = ist.choose_config_dir(cdir or "", cset, os.environ.get("CLAUDE_CONFIG_DIR", ""), home)
        c = ist.expand_path(raw, home, ist._cwd())
    except ist.ConfigDirError as exc:
        usage(str(exc))
    how = {"flag": "--config-dir", "env": "CLAUDE_CONFIG_DIR"}.get(src, "default")
    if os.path.exists(c) and not os.path.isdir(c):
        usage("%s is not a folder" % c)
    state = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.join(home, ".local", "state"), "claude-agent-stack")
    subs = {"__CLAUDE_DIR__": c, "__HOME__": home, "__STACK_REPO__": repo, "__STACK_BACKUPS__": state + "-backups",
            "__STACK_CACHE__": state + "-cache", "__STACK_STATE__": state}
    head = git_head(repo)
    print("stack diff (read-only): repo %s (commit %s) vs installed %s (%s)" % (repo, head, c, how))
    if not os.path.isdir(c):
        print("  nothing installed: %s does not exist" % c)
        return 0
    try:
        install_text = read(os.path.join(repo, "install.sh")).decode("utf-8")
    except OSError as exc:
        usage("cannot read install.sh: %s" % exc)
    d = Diff(repo, c, subs, install_text)
    inst_commit = (d.manifest.get("commit") or "")[:7]
    print("  installed from commit %s" % (inst_commit or "unknown (no .stack-manifest.json)"))
    d.run()
    total = {"+": 0, "-": 0, "~": 0, "?": 0}
    label = {"+": "repo only", "-": "installed only", "~": "differs", "?": "unreadable"}
    for area in ("agents", "rules", "skills", "hooks", "bin", "mcp", "magg", "magg catalog",
                 "stack-plugins", "settings.json hooks"):
        rows = d.rows.get(area, [])
        if not rows:
            print("%s: in sync" % area)
            continue
        counts = {s: sum(1 for r in rows if r[0] == s) for s in total}
        print("%s: %s" % (area, ", ".join("%d %s" % (n, label[s]) for s, n in counts.items() if n)))
        for sign, rel, note in rows:
            total[sign] += 1
            print("  %s %-15s %s%s" % (sign, label[sign], rel, ("  (%s)" % note) if note else ""))
    for n in d.notes:
        print("note: %s" % n)
    print("summary: %d repo only, %d installed only, %d differ%s. Nothing was written; ./install.sh applies "
          "the repo (installed-only stack files are pruned unless --no-prune)."
          % (total["+"], total["-"], total["~"], (", %d unreadable" % total["?"]) if total["?"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
