"""settings.json Bash rules -> Codex exec-policy rules (DESIGN.md §4.1 L2, §4.3, §8.4; F4, F13, F21).

Entry points (INTERFACES.md §3-F):
- render_rules(settings, ctx, opts) -> (text, examples): the text of
  `<CODEX_HOME>/rules/claude-agent-stack.rules` and one {"pattern", "decision", "match",
  "not_match"} per prefix_rule. opts: {"git_allow_rules": bool}. ctx: codex_home, stack.
- check_examples(rules_path, codex) -> [disagreement, ...]: loads the file once, then runs
  `codex execpolicy check --rules <file> --resolve-host-executables -- <tokens>` for every match and
  not_match example and reports each one Codex decides differently (empty list = all agree).
- convert(settings, ctx, opts) -> {"text", "examples", "rules", "counts", "report"}: the same plus
  the per-rule records (with "category" and "source") and the build-report notes.
- forbidden_push_forge(settings, ctx) -> the forbidden rules of category push or forge (the
  requirements.toml `[rules]` set, DESIGN §4.5).

What is generated (rules are GLOBAL: every Codex session on this machine loads them, F4):
- `forbidden`, one prefix_rule per `Bash(...)` deny of settings.json (push, send-pack, lfs/subtree
  push, gh/tea/fj forge writes, installer tracing), plus the push forms agent_guard also blocks
  (`git-push`, `git-send-pack`, `git svn dcommit|set-tree`, `git p4 submit`). A Claude pattern is
  tokenized on spaces; a trailing `*` (or `:*`) is the prefix itself; a glob token is expanded into
  a union of alternatives only when the words that may follow its literal prefix are a known finite
  set (VOCAB); any other glob (`mcp-headers *--reveal*`) has no prefix form and is reported as
  guard-only.
- `prompt` for git subcommands that write `.git` (read-only in workspace-write, F14) and for
  `<stack>/bin/stack-install` (§4.3); a Claude `ask` Bash rule also becomes `prompt`.
- A Claude `allow` NEVER becomes a Codex `allow`: Claude's allow means "no prompt, still
  sandboxed", Codex's means "run outside the sandbox without asking" (F13). Claude allows are
  dropped (reported), except stack-install, which becomes `prompt`.
- Only with opts["git_allow_rules"] (`--git-allow-rules`): `allow` for the hook-free forms
  `git -c core.hooksPath=/dev/null add|commit …` and `… merge --ff-only …`. They run unsandboxed in
  every session; the guard must refuse `-F/--file`, `-t/--template`, `--pathspec-from-file`, `-C`,
  `--exec-path` and `-c alias.*` on them (DESIGN §4.3). `rebase` (`--exec`) and `worktree` (writes
  any path) are never allowed.
- Never `default.rules` (Codex's own approvals file).

Prefix rules match exact argv tokens from the start (vendored rule.rs/policy.rs, rust-v0.160.1):
`git -C x push`, `env git push` or `bash -c 'git push'` are not matched by `git push`; Codex splits
linear `&&`/`;`/`|` scripts (F13) and resolves `/usr/bin/git` to `git` at run time
(`resolve_host_executables: true`, vendored core_exec_policy.extract.rs). The guard's parser covers
the rest. A rules file that fails to load (for example a match example that does not match) makes
Codex drop the policy, so the installer runs check_examples before apply (DESIGN §7.3).

Seeded-bug proofs (tests/mutations/convert_rules.json, each turns test_convert_rules.py red):
flip the forbidden decision to allow; convert a Claude allow (any, or stack-install) into a Codex
allow; keep the trailing `*` (no prefix form); emit the git allow forms without the flag; let a
non-finite glob through as a literal token; make check_examples ignore a decision mismatch; run
check_examples without basename resolution.
"""
from __future__ import annotations

import ast
import fnmatch
import json
import os
import re
import shlex
import subprocess
from concurrent.futures import ThreadPoolExecutor

__all__ = ["BuildError", "RULES_FILE", "render_rules", "check_examples", "convert",
           "forbidden_push_forge", "parse_rules_text"]

RULES_FILE = "rules/claude-agent-stack.rules"
DECISIONS = ("allow", "prompt", "forbidden")
HOOK_FREE = ["git", "-c", "core.hooksPath=/dev/null"]
_BAD = re.compile(r"[\x00-\x1f\x7f]")
_GLOB = re.compile(r"[*?\[]")
_BASH = re.compile(r"Bash\((.*)\)\Z", re.S)

JUSTIFY = {
    "push": "claude-agent-stack: agents never push to a remote, in any form. Keep the work in the "
            "local repository (commit, merge into local main); publishing is the user's step.",
    "forge": "claude-agent-stack: agents never write to a forge (pull requests, reviews, comments, "
             "releases, repositories, workflows). Report the branch and commits; the user publishes.",
    "secret": "claude-agent-stack: this form prints or traces stack secrets (stack.env keys). Run "
              "the command without the tracing or reveal option.",
    "git-write": "claude-agent-stack: this git command writes .git, which is read-only inside the "
                 "sandbox; approve it to run it outside the sandbox.",
    "installer": "claude-agent-stack: stack-install runs outside the sandbox (toolsmith only; the "
                 "guard checks the argv); approve each run.",
    "ask": "claude-agent-stack: settings.json asks before this command; approve each run.",
    "git-allow": "claude-agent-stack --git-allow-rules: hook-free git form, run outside the sandbox "
                 "without a prompt; the guard refuses file-reading and exec options on it.",
}

# words that may follow a literal prefix, for expanding a glob token into a finite union
# (gh/tea/fj from agent_guard.FORGE_TREES; git porcelain from git(1))
VOCAB = {
    ("git",): ["add", "am", "apply", "archive", "bisect", "branch", "bundle", "checkout",
               "cherry-pick", "clean", "clone", "commit", "describe", "diff", "fetch",
               "format-patch", "gc", "grep", "init", "lfs", "log", "maintenance", "merge", "mv",
               "notes", "p4", "pull", "push", "range-diff", "rebase", "reflog", "remote", "repack",
               "replace", "reset", "restore", "revert", "rm", "send-email", "send-pack",
               "shortlog", "show", "sparse-checkout", "stash", "status", "submodule", "subtree",
               "svn", "switch", "tag", "worktree"],
    ("gh", "pr"): ["create", "new", "merge", "close", "reopen", "edit", "comment", "review",
                   "ready", "lock", "unlock", "update-branch", "revert", "view", "list", "ls",
                   "status", "checks", "diff", "checkout", "co"],
    ("gh", "release"): ["create", "new", "delete", "delete-asset", "edit", "upload", "view",
                        "list", "ls", "download", "verify", "verify-asset"],
    ("gh", "repo"): ["create", "new", "delete", "edit", "fork", "rename", "archive", "unarchive",
                     "sync", "deploy-key", "autolink", "view", "list", "ls", "clone",
                     "set-default", "read-dir", "read-file", "gitignore", "license"],
    ("gh", "workflow"): ["run", "enable", "disable", "view", "list", "ls"],
}

GIT_PROMPTS = [
    ["git", ["add", "commit", "merge", "rebase", "cherry-pick", "revert", "reset", "am", "rm",
             "mv", "checkout", "switch", "pull", "fetch", "gc", "update-ref"]],
    ["git", "stash", ["push", "pop", "apply", "drop", "clear", "save", "store", "branch"]],
    ["git", "branch", ["-d", "-D", "--delete", "-m", "-M", "--move", "-c", "-C", "--copy", "-f",
                       "--force", "-u", "--set-upstream-to", "--unset-upstream",
                       "--edit-description"]],
    ["git", "tag", ["-a", "-s", "-d", "-f", "-m", "-F", "--annotate", "--sign", "--delete",
                    "--force", "--message", "--file"]],
    ["git", "worktree", ["add", "remove", "move", "prune", "repair", "lock", "unlock"]],
    ["git", "remote", ["add", "remove", "rm", "rename", "set-url", "set-head", "set-branches",
                       "prune", "update"]],
]
EXTRA_PUSH = [
    (["git-push"], "agent_guard.py PUSH_PROGRAMS"),
    (["git-send-pack"], "agent_guard.py PUSH_PROGRAMS"),
    (["git", "svn", ["dcommit", "set-tree"]], "agent_guard.py PUSH_UNDER"),
    (["git", "p4", "submit"], "agent_guard.py PUSH_UNDER"),
]
GIT_ALLOWS = [
    HOOK_FREE + [["add", "commit"]],
    HOOK_FREE + ["merge", "--ff-only"],
]


class BuildError(Exception):
    """A settings.json rule cannot be converted (never guessed)."""


# ------------------------------------------------------------------------------- pattern helpers


def _alts(tok):
    return tok if isinstance(tok, list) else [tok]


def _norm_pattern(pattern):
    out = []
    for t in pattern:
        a = _alts(t)
        if not a or any(not isinstance(x, str) or not x or _BAD.search(x) for x in a):
            raise BuildError("bad pattern token %r" % (t,))
        out.append(a[0] if len(a) == 1 else list(a))
    if not out:
        raise BuildError("empty pattern")
    return out


def _star(s):
    if not isinstance(s, str) or _BAD.search(s):
        raise BuildError("control character in rule string %r" % (s,))
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _star_value(v):
    if isinstance(v, list):
        return "[" + ", ".join(_star_value(x) for x in v) + "]"
    return _star(v)


def _category(pattern):
    head = _alts(pattern[0])[0]
    if head in ("git", "git-push", "git-send-pack"):
        return "push"
    if head in ("gh", "tea", "fj"):
        return "forge"
    return "secret"


def _examples(pattern):
    first = [_alts(t)[0] for t in pattern]
    last = [_alts(t)[-1] for t in pattern]
    match = [first]
    if last + ["x"] != first:
        match.append(last + ["x"])
    not_match = [["echo"] + first]
    if len(first) >= 2:
        alts = _alts(pattern[-1])
        near = next(w for w in ("status", "--version", "zz-not-a-subcommand") if w not in alts)
        not_match.append(first[:-1] + [near])
    return match, not_match


def _rule(pattern, decision, category, source, match=None, not_match=None):
    pattern = _norm_pattern(pattern)
    m, nm = _examples(pattern)
    return {"pattern": pattern, "decision": decision, "category": category,
            "justification": JUSTIFY[category], "source": source,
            "match": match if match is not None else m,
            "not_match": not_match if not_match is not None else nm}


# ------------------------------------------------------------------------------ Claude -> tokens


def _claude_tokens(spec, ctx):
    """A Claude Bash rule body -> (pattern or None, note). None means no prefix form."""
    stack = ctx.get("stack") or os.path.join(ctx["codex_home"], "stack")
    s = spec.strip()
    if "__CLAUDE_DIR__/bin/" in s:
        s = s.replace("__CLAUDE_DIR__/bin/", stack.rstrip("/") + "/bin/")
    if re.search(r"__[A-Z][A-Z0-9_]*__", s):
        raise BuildError("unmapped placeholder in Bash(%s)" % spec)
    if s.endswith(":*"):
        s = s[:-2] + " *"
    words = s.split()
    if not words:
        raise BuildError("empty Bash() rule")
    while words and words[-1] == "*":
        words.pop()                       # trailing "*": any arguments, i.e. the prefix itself
    if not words:
        raise BuildError("Bash(%s) matches every command" % spec)
    pattern, notes = [], []
    for i, w in enumerate(words):
        if not _GLOB.search(w):
            pattern.append(w)
            continue
        # a glob token: finite only when the words allowed after the literal prefix are known
        key = tuple(pattern) if all(isinstance(x, str) for x in pattern) else None
        vocab = VOCAB.get(key) if key else None
        if vocab is None or w == "*":
            return None, "guard-only (no finite prefix form): Bash(%s)" % spec
        hits = [v for v in vocab if fnmatch.fnmatchcase(v, w)]
        if not hits:
            return None, "guard-only (the glob matches no known word): Bash(%s)" % spec
        pattern.append(hits[0] if len(hits) == 1 else hits)
        note = "expanded %r into %s: Bash(%s)" % (w, hits, spec)
        if i != len(words) - 1:
            note += " (a glob inside the command can also span words: under-approximated)"
        notes.append(note)
    return pattern, "; ".join(notes) or None


def _bash_rules(entries, what):
    out = []
    for e in entries or []:
        if not isinstance(e, str):
            raise BuildError("non-string permissions.%s entry %r" % (what, e))
        if e == "Bash":
            if what == "allow":
                continue
            raise BuildError("a blanket `Bash` %s rule cannot be converted" % what)
        m = _BASH.match(e)
        if m:
            out.append((e, m.group(1)))
    return out


# -------------------------------------------------------------------------------------- convert


def convert(settings: dict, ctx: dict, opts: dict | None = None) -> dict:
    opts = opts or {}
    if not isinstance(settings, dict):
        raise BuildError("settings must be a dict")
    if not isinstance(ctx.get("codex_home"), str) or not os.path.isabs(ctx["codex_home"]):
        raise BuildError("ctx['codex_home'] must be an absolute path")
    perms = settings.get("permissions") or {}
    rules, report = [], []
    stack = ctx.get("stack") or os.path.join(ctx["codex_home"], "stack")
    installer = os.path.join(stack, "bin", "stack-install")

    for entry, spec in _bash_rules(perms.get("deny"), "deny"):
        pattern, note = _claude_tokens(spec, ctx)
        if note:
            report.append(note)
        if pattern is None:
            continue
        rules.append(_rule(pattern, "forbidden", _category(pattern), "settings.json deny " + entry))
    for pattern, src in EXTRA_PUSH:
        rules.append(_rule(pattern, "forbidden", "push", src))

    for p in GIT_PROMPTS:
        rules.append(_rule(p, "prompt", "git-write", "DESIGN §4.3 git writes"))
    rules.append(_rule([installer], "prompt", "installer", "DESIGN §4.3 stack-install",
                       match=[[installer], [installer, "add", "x"]],
                       not_match=[["echo", installer], [installer + "-x"]]))
    for entry, spec in _bash_rules(perms.get("ask"), "ask"):
        pattern, note = _claude_tokens(spec, ctx)
        if note:
            report.append(note)
        if pattern is not None:
            rules.append(_rule(pattern, "prompt", "ask", "settings.json ask " + entry))
    for entry, spec in _bash_rules(perms.get("allow"), "allow"):
        pattern, _ = _claude_tokens(spec, ctx)
        if pattern is not None and _alts(pattern[0])[0] == installer:
            report.append("allow -> prompt (never Codex allow): %s" % entry)
        else:
            report.append("dropped Claude allow (Codex runs unmatched commands sandboxed; a Codex "
                          "allow would run them outside the sandbox): %s" % entry)

    if opts.get("git_allow_rules"):
        other = ["git", "-c", "core.hooksPath=/tmp/h"]
        for p in GIT_ALLOWS:
            tail = [_alts(t)[0] for t in p[3:]]
            tail_last = [_alts(t)[-1] for t in p[3:]]
            rules.append(_rule(p, "allow", "git-allow", "--git-allow-rules (DESIGN §4.3)",
                               match=[HOOK_FREE + tail + ["x"], HOOK_FREE + tail_last + ["-v"]],
                               not_match=[["git"] + tail + ["x"], other + tail + ["x"],
                                          HOOK_FREE + ["push"], HOOK_FREE + ["rebase", "x"]]))

    for r in rules:
        if r["decision"] == "allow" and r["category"] != "git-allow":
            raise BuildError("internal: allow outside --git-allow-rules: %r" % r["pattern"])
    counts = {d: sum(1 for r in rules if r["decision"] == d) for d in DECISIONS}
    text = _render(rules, report, opts)
    examples = [{"pattern": r["pattern"], "decision": r["decision"], "match": r["match"],
                 "not_match": r["not_match"]} for r in rules]
    return {"text": text, "examples": examples, "rules": rules, "counts": counts, "report": report}


def _render(rules, report, opts):
    out = [
        "# claude-agent-stack: Codex exec-policy rules. GLOBAL: every Codex session on this machine",
        "# loads them (rules/*.rules of CODEX_HOME). Generated by codex_config/lib/convert_rules.py",
        "# from dot-claude/settings.json; the installer overwrites this file. Put your own rules in",
        "# another file under rules/ (Codex writes its approvals to default.rules).",
        "# forbidden = never run; prompt = ask the user. A Claude `allow` is never a Codex `allow`",
        "# (Codex allow = run outside the sandbox without asking).",
    ]
    if opts.get("git_allow_rules"):
        out.append("# --git-allow-rules: the hook-free git forms at the end run outside the sandbox.")
    for note in report:
        if note.startswith("guard-only"):
            out.append("# " + note)
    for r in rules:
        out += ["", "# %s (%s)" % (r["source"], r["category"]), "prefix_rule("]
        out.append("    pattern = %s," % _star_value(r["pattern"]))
        out.append("    decision = %s," % _star(r["decision"]))
        out.append("    justification = %s," % _star(r["justification"]))
        out.append("    match = %s," % _star_value(r["match"]))
        out.append("    not_match = %s," % _star_value(r["not_match"]))
        out.append(")")
    return "\n".join(out) + "\n"


def render_rules(settings: dict, ctx: dict, opts: dict | None = None):
    res = convert(settings, ctx, opts)
    return res["text"], res["examples"]


def forbidden_push_forge(settings: dict, ctx: dict) -> list:
    return [r for r in convert(settings, ctx, {})["rules"]
            if r["decision"] == "forbidden" and r["category"] in ("push", "forge")]


# ------------------------------------------------------------------------------- check_examples


def parse_rules_text(text: str) -> list:
    """The prefix_rule calls of a rules file this module wrote: [{"pattern", "decision",
    "justification", "match", "not_match"}]. Only literal keyword arguments are read."""
    tree = ast.parse(text, mode="exec")
    out = []
    for stmt in tree.body:
        if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)
                and isinstance(stmt.value.func, ast.Name) and stmt.value.func.id == "prefix_rule"):
            raise BuildError("line %d: not a prefix_rule call" % stmt.lineno)
        kw = {k.arg: ast.literal_eval(k.value) for k in stmt.value.keywords}
        out.append({"pattern": kw["pattern"], "decision": kw.get("decision") or "allow",
                    "justification": kw.get("justification"),
                    "match": [shlex.split(e) if isinstance(e, str) else e
                              for e in kw.get("match") or []],
                    "not_match": [shlex.split(e) if isinstance(e, str) else e
                                  for e in kw.get("not_match") or []]})
    return out


def _fits(rule, m):
    """Did match entry `m` (prefixRuleMatch) come from `rule`?"""
    pm = m.get("prefixRuleMatch") or {}
    pre = pm.get("matchedPrefix") or []
    pat = rule["pattern"]
    if len(pre) != len(pat):
        return False
    head = os.path.basename(pre[0]) if pm.get("resolvedProgram") else pre[0]
    if head not in _alts(pat[0]) and pre[0] not in _alts(pat[0]):
        return False
    return (all(t in _alts(p) for t, p in zip(pre[1:], pat[1:]))
            and pm.get("decision") == rule["decision"]
            and pm.get("justification") == rule.get("justification"))


def _run(codex, rules_path, tokens):
    cmd = [codex, "execpolicy", "check", "--rules", rules_path, "--resolve-host-executables", "--"]
    try:
        r = subprocess.run(cmd + list(tokens), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, "cannot run %s: %s" % (codex, exc)
    if r.returncode != 0:
        return None, "exit %d: %s" % (r.returncode, (r.stderr or r.stdout).strip()[:500])
    try:
        return json.loads(r.stdout), None
    except ValueError:
        return None, "not JSON: %r" % r.stdout[:200]


def check_examples(rules_path: str, codex: str) -> list:
    try:
        with open(rules_path, encoding="utf-8") as fh:
            rules = parse_rules_text(fh.read())
    except (OSError, SyntaxError, ValueError, KeyError, BuildError) as exc:
        return ["%s: cannot read the rules: %s" % (rules_path, exc)]
    _, err = _run(codex, rules_path, ["true"])
    if err:
        return ["%s: codex cannot load the rules: %s" % (rules_path, err)]
    jobs = [(r, kind, ex) for r in rules for kind in ("match", "not_match") for ex in r[kind]]

    def one(job):
        rule, kind, ex = job
        res, err = _run(codex, rules_path, ex)
        label = "%s %s %s" % (json.dumps(rule["pattern"]), kind, shlex.join(ex))
        if err:
            return "%s: %s" % (label, err)
        mine = [m for m in res.get("matchedRules", []) if _fits(rule, m)]
        if kind == "match":
            if not mine:
                return "%s: not matched by its rule (got %s)" % (label, res.get("decision"))
            if res.get("decision") != rule["decision"]:
                return "%s: decision %s, rule says %s" % (label, res.get("decision"),
                                                          rule["decision"])
        elif mine:
            return "%s: matched by its rule (decision %s)" % (label, res.get("decision"))
        return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        return [d for d in pool.map(one, jobs) if d]
