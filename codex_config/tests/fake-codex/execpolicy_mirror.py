"""In-repo mirror of `codex execpolicy check` for the fake codex CLI (tests only). Stdlib, Python >= 3.9.

The fake `codex` (tests/fake-codex/codex) runs this file with the argv that follows
`execpolicy check`. It reproduces, from openai/codex at tag rust-v0.160.1 (vendored under
tests/fixtures/rules/, see its README for URLs and sha256):

- argv (execpolicycheck.rs): `-r/--rules PATH` (repeatable, required; also `--rules=PATH`),
  `--pretty`, `--resolve-host-executables`, then the command tokens (required; everything from the
  first positional on is the command, hyphen values included; a leading `--` is a separator).
- policy files (parser.rs): Starlark calls `prefix_rule(pattern, decision, match, not_match,
  justification)`, `host_executable(name, paths)` and `network_rule(host, protocol, decision,
  justification)`. A pattern element is a string or a list of alternatives; a one-item list is a
  single token; first-token alternatives become one rule per head. `decision` defaults to "allow".
  Examples are token lists or strings (split like shlex). After each file is evaluated, every
  call's `not_match` and then `match` examples are checked against a policy holding only that
  call's rules (basename fallback on), and a failure fails the load.
- matching (rule.rs, policy.rs): exact-token prefix match on the rules keyed by the first token, in
  file order then rule order; only when none match and `--resolve-host-executables` is given, an
  absolute first token falls back to the rules for its basename, gated by `host_executable` paths
  (then `resolvedProgram` is set).
- output (execpolicycheck.rs, cli/tests/execpolicy.rs): one JSON line
  `{"matchedRules":[{"prefixRuleMatch":{"matchedPrefix":[...],"decision":"...",
  "resolvedProgram"?:"...","justification"?:"..."}}],"decision"?:"..."}` where `decision` is the
  strictest match (forbidden > prompt > allow) and is omitted when nothing matched. `--pretty`
  indents by two spaces (serde_json's pretty printer).
- errors: a load or parse failure prints `Error: ...` on stderr and exits 1 (anyhow from main); a
  usage error exits 2 (clap).

Deliberate limits, all stated: only the Starlark subset that is also Python expression syntax is
read (calls with literal string / list arguments; comments; no assignments, loads, functions or
f-strings: those exit 1); string examples use Python's shlex in POSIX mode, which agrees with the
Rust shlex crate on the quoting the installer emits (token lists are used there anyway).

Seeded-bug proofs (tests/mutations/convert_rules.json, each turns test_execpolicy_mirror.py red):
skip the load-time not_match validation; drop the basename fallback; let the least strict
decision win.
"""
from __future__ import annotations

import ast
import json
import os
import shlex
import sys

DECISIONS = ("allow", "prompt", "forbidden")
RANK = {d: i for i, d in enumerate(DECISIONS)}


class PolicyError(Exception):
    pass


class UsageError(Exception):
    pass


# ------------------------------------------------------------------------------------------ parse


def _literal(node, what):
    """A string or a (nested) list of strings from the Starlark subset."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.List):
        return [_literal(e, what) for e in node.elts]
    if isinstance(node, ast.Constant) and node.value is None:
        return None
    raise PolicyError("%s: unsupported value (only strings and lists of strings)" % what)


def _pattern(raw):
    if not isinstance(raw, list):
        raise PolicyError("pattern must be a list")
    tokens = []
    for item in raw:
        if isinstance(item, str):
            tokens.append([item])
        elif isinstance(item, list):
            if not item:
                raise PolicyError("pattern alternatives cannot be empty")
            if not all(isinstance(a, str) for a in item):
                raise PolicyError("pattern alternative must be a string")
            tokens.append(list(item))
        else:
            raise PolicyError("pattern element must be a string or list of strings")
    if not tokens:
        raise PolicyError("pattern cannot be empty")
    return tokens


def _example(raw):
    if isinstance(raw, str):
        try:
            toks = shlex.split(raw)
        except ValueError:
            raise PolicyError("example string has invalid shell syntax")
        if not toks:
            raise PolicyError("example cannot be an empty string")
        return toks
    if isinstance(raw, list):
        if not raw:
            raise PolicyError("example cannot be an empty list")
        if not all(isinstance(t, str) for t in raw):
            raise PolicyError("example tokens must be strings")
        return list(raw)
    raise PolicyError("example must be a string or list of strings")


def _bind(call, params, name):
    """Starlark-style argument binding: positionals in order, then keywords; unknown or duplicate
    names are errors."""
    out = {}
    if len(call.args) > len(params):
        raise PolicyError("%s: too many positional arguments" % name)
    for p, a in zip(params, call.args):
        out[p] = _literal(a, "%s(%s)" % (name, p))
    for kw in call.keywords:
        if kw.arg is None or kw.arg not in params:
            raise PolicyError("%s: unexpected argument %r" % (name, kw.arg))
        if kw.arg in out:
            raise PolicyError("%s: argument %r given twice" % (name, kw.arg))
        out[kw.arg] = _literal(kw.value, "%s(%s)" % (name, kw.arg))
    return out


class Policy:
    def __init__(self):
        self.rules = {}           # program -> [rule]; rule = (first, rest, decision, justification)
        self.host_executables = {}

    def add_rule(self, rule):
        self.rules.setdefault(rule[0], []).append(rule)

    def matches(self, cmd, resolve):
        if not cmd:
            return []
        found = [m for r in self.rules.get(cmd[0], []) for m in [_match(r, cmd, None)] if m]
        if found or not resolve:
            return found
        first = cmd[0]
        if not os.path.isabs(first):
            return []
        base = os.path.basename(first)
        if not base or base not in self.rules:
            return []
        allowed = self.host_executables.get(base)
        if allowed is not None and os.path.normpath(first) not in allowed:
            return []
        bcmd = [base] + list(cmd[1:])
        return [m for r in self.rules[base] for m in [_match(r, bcmd, first)] if m]


def _match(rule, cmd, resolved):
    first, rest, decision, justification = rule
    n = len(rest) + 1
    if len(cmd) < n or cmd[0] != first:
        return None
    for alts, tok in zip(rest, cmd[1:n]):
        if tok not in alts:
            return None
    m = {"matchedPrefix": list(cmd[:n]), "decision": decision}
    if resolved is not None:
        m["resolvedProgram"] = resolved
    if justification is not None:
        m["justification"] = justification
    return {"prefixRuleMatch": m}


def parse_policy(policy, ident, text):
    try:
        tree = ast.parse(text, filename=ident, mode="exec")
    except SyntaxError as exc:
        raise PolicyError("%s:%s: syntax error: %s" % (ident, exc.lineno, exc.msg))
    pending = []
    for stmt in tree.body:
        if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)
                and isinstance(stmt.value.func, ast.Name)):
            raise PolicyError("%s:%d: only top-level calls are supported" % (ident, stmt.lineno))
        call = stmt.value
        fname = call.func.id
        where = "%s:%d" % (ident, stmt.lineno)
        if fname == "prefix_rule":
            a = _bind(call, ("pattern", "decision", "match", "not_match", "justification"), fname)
            if "pattern" not in a:
                raise PolicyError("%s: prefix_rule() missing pattern" % where)
            decision = a.get("decision")
            if decision is None:
                decision = "allow"
            if decision not in DECISIONS:
                raise PolicyError("%s: invalid decision: %s" % (where, decision))
            just = a.get("justification")
            if just is not None and (not isinstance(just, str) or not just.strip()):
                raise PolicyError("%s: justification cannot be empty" % where)
            tokens = _pattern(a["pattern"])
            matches = [_example(e) for e in (a.get("match") or [])]
            not_matches = [_example(e) for e in (a.get("not_match") or [])]
            rest = tokens[1:]
            rules = [(head, rest, decision, just) for head in tokens[0]]
            pending.append((where, rules, matches, not_matches))
            for r in rules:
                policy.add_rule(r)
        elif fname == "host_executable":
            a = _bind(call, ("name", "paths"), fname)
            name, paths = a.get("name"), a.get("paths")
            if not isinstance(name, str) or not name or "/" in name or name in (".", ".."):
                raise PolicyError("%s: host_executable name must be a bare executable name" % where)
            if not isinstance(paths, list):
                raise PolicyError("%s: host_executable paths must be a list" % where)
            parsed = []
            for p in paths:
                if not isinstance(p, str) or not os.path.isabs(p):
                    raise PolicyError("%s: host_executable paths must be absolute" % where)
                if os.path.basename(p) != name:
                    raise PolicyError("%s: host_executable path `%s` must have basename `%s`"
                                      % (where, p, name))
                p = os.path.normpath(p)
                if p not in parsed:
                    parsed.append(p)
            policy.host_executables[name] = parsed
        elif fname == "network_rule":
            a = _bind(call, ("host", "protocol", "decision", "justification"), fname)
            if a.get("protocol") not in ("http", "https", "https_connect", "http-connect",
                                         "socks5_tcp", "socks5_udp"):
                raise PolicyError("%s: invalid network_rule protocol" % where)
            if a.get("decision") not in ("allow", "prompt", "forbidden", "deny"):
                raise PolicyError("%s: invalid network_rule decision" % where)
        else:
            raise PolicyError("%s: unknown function %s" % (where, fname))
    # load-time example validation, per call, after the whole file (parser.rs)
    for where, rules, matches, not_matches in pending:
        local = Policy()
        local.host_executables = dict(policy.host_executables)
        for r in rules:
            local.add_rule(r)
        for ex in not_matches:
            if local.matches(ex, True):
                raise PolicyError("%s: example matched a rule it must not match: %s"
                                  % (where, shlex.join(ex)))
        bad = [shlex.join(ex) for ex in matches if not local.matches(ex, True)]
        if bad:
            raise PolicyError("%s: examples did not match the rule: %s" % (where, "; ".join(bad)))


# ------------------------------------------------------------------------------------------- argv


def parse_argv(argv):
    rules, pretty, resolve, command = [], False, False, None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--":
            command = argv[i + 1:]
            break
        if a in ("-r", "--rules"):
            if i + 1 >= len(argv):
                raise UsageError("a value is required for '--rules <PATH>'")
            rules.append(argv[i + 1])
            i += 2
            continue
        if a.startswith("--rules="):
            rules.append(a[len("--rules="):])
        elif a.startswith("-r") and len(a) > 2:
            rules.append(a[2:].lstrip("="))
        elif a == "--pretty":
            pretty = True
        elif a == "--resolve-host-executables":
            resolve = True
        elif a.startswith("-") and a != "-":
            raise UsageError("unexpected argument '%s' found" % a)
        else:
            command = argv[i:]
            break
        i += 1
    if not rules:
        raise UsageError("the following required arguments were not provided: --rules <PATH>")
    if not command:
        raise UsageError("the following required arguments were not provided: <COMMAND>...")
    return rules, pretty, resolve, command


def main(argv):
    try:
        rules, pretty, resolve, command = parse_argv(argv)
    except UsageError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return 2
    policy = Policy()
    try:
        for path in rules:
            try:
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
            except (OSError, UnicodeDecodeError) as exc:
                raise PolicyError("failed to read policy at %s: %s" % (path, exc))
            try:
                parse_policy(policy, path, text)
            except PolicyError as exc:
                raise PolicyError("failed to parse policy at %s: %s" % (path, exc))
    except PolicyError as exc:
        sys.stderr.write("Error: %s\n" % exc)
        return 1
    matched = policy.matches(command, resolve)
    out = {"matchedRules": matched}
    if matched:
        out["decision"] = max((m["prefixRuleMatch"]["decision"] for m in matched), key=RANK.get)
    if pretty:
        text = json.dumps(out, indent=2, ensure_ascii=False)
    else:
        text = json.dumps(out, separators=(",", ":"), ensure_ascii=False)
    sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
