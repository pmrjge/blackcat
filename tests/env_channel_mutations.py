"""Seeded-mutation proof for the environment-channel rules (probe E2a, 2026-10-09): agent_guard.py's "envchan" scan
kind (X*) and with-stack-env's stack.env filter (W*). stack_sdk.py's refusal is in tests/sdk_mutations.py (E2a).

Each mutant is one text substitution, which must match its file exactly once, in a scratch copy (the guard through
tests/sdk3_mutations.py's sandbox, via GUARD=; with-stack-env via WITH_STACK_ENV=). Its NAMED test must then FAIL
(its id in pytest's FAILED/ERROR lines, or a timeout). The clean copies must pass every named test first.

  uv run --no-project --python 3.13 --with-requirements requirements/tools.txt python tests/env_channel_mutations.py
      [--list] [-k ID_OR_TEXT[,..]] [-j N (default 4)] [--out PATH (default "-": stdout only)]
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sdk3_mutations import CONF, first_error, killed_by, run_tests, sandbox  # noqa: E402

FILES = {"guard": CONF / "hooks" / "agent_guard.py", "wse": CONF / "bin" / "with-stack-env"}
EG, WS = "tests/test_guard_env_channel.py::", "tests/test_with_stack_env.py::"
DENY, ALLOW = EG + "test_channel_assignment_is_denied", EG + "test_channel_mention_is_allowed"

MUTANTS = [  # (id, mutant, file key, named test, anchor, replacement)
    ("X1", "the scan's trigger misses the channel names", "guard", EG + "test_a_parser_failure_fails_closed",
     'r"CLAUDE_BG_|CLAUDE_CODE_SESSION_KIND|CLAUDE_CODE_SANDBOXED")   # + ENV_CHANNEL_RE', 'r"CLAUDE_BG_NEVER")'),
    ("X2", "envchan not in the secrets scan", "guard", DENY,
     '_Scan(("secrets", "install", "envchan"), ev=ev)', '_Scan(("secrets", "install"), ev=ev)'),
    ("X3", "NAME=value at command position unchecked", "guard", DENY,
     'if "envchan" in want and here_cmd and (ENV_CHANNEL_RE.fullmatch(name) or ENV_CHANNEL_RE.fullmatch(val)):',
     'if False:'),
    ("X4", "a value naming the channel (V=NAME) unchecked", "guard", DENY,
     'ENV_CHANNEL_RE.fullmatch(name) or ENV_CHANNEL_RE.fullmatch(val)):', 'ENV_CHANNEL_RE.fullmatch(name)):'),
    ("X5", "NAME=value denied anywhere (echo NAME=1)", "guard", ALLOW,
     '"envchan" in want and here_cmd and (', '"envchan" in want and ('),
    ("X6", "binders unchecked (export NAME)", "guard", DENY,
     'if not found and "envchan" in want and base in ENV_CHANNEL_BINDERS:', 'if False:'),
    ("X7", "printf's text operands read as names", "guard", ALLOW,
     '    if base == "printf":                       # printf -v NAME',
     '    if False:                       # printf -v NAME'),
    ("X8", "printf -vNAME missed", "guard", DENY,
     ' + [a[2:] for a in args if a.startswith("-v")]', ''),
    ("X9", "launchctl: every subcommand read as setenv", "guard", ALLOW,
     'args = args[1:2] if args[:1] == ["setenv"] else []', 'args = args[1:2]'),
    ("X10", "launchctl setenv not checked", "guard", DENY,
     '"getopts", "printf", "launchctl"}', '"getopts", "printf"}'),
    ("X11", "a binder's REF=NAME value unchecked", "guard", DENY,
     'if any(ENV_CHANNEL_RE.fullmatch(x) for x in a.split("=", 1))), None)',
     'if ENV_CHANNEL_RE.fullmatch(a.split("=", 1)[0])), None)'),
    ("X12", "names matched by prefix", "guard", ALLOW,
     'here_cmd and (ENV_CHANNEL_RE.fullmatch(name)', 'here_cmd and (ENV_CHANNEL_RE.match(name)'),
    ("X13", "names matched anywhere", "guard", ALLOW,
     'here_cmd and (ENV_CHANNEL_RE.fullmatch(name)', 'here_cmd and (ENV_CHANNEL_RE.search(name)'),
    ("X14", "CLAUDE_CODE_SANDBOXED missing", "guard", DENY,
     'ENV_CHANNEL_RE = re.compile(r"CLAUDE_BG_\\w*|CLAUDE_CODE_SESSION_KIND|CLAUDE_CODE_SANDBOXED")',
     'ENV_CHANNEL_RE = re.compile(r"CLAUDE_BG_\\w*|CLAUDE_CODE_SESSION_KIND")'),
    ("X15", "CLAUDE_BG_* missing", "guard", DENY,
     'ENV_CHANNEL_RE = re.compile(r"CLAUDE_BG_\\w*|', 'ENV_CHANNEL_RE = re.compile(r"'),
    ("X16", "the hook gives another rule's reason", "guard", EG + "test_the_hook_denies_with_the_channel_reason",
     '             ENV_CHANNEL_REASON % what if kind == "envchan" else\n', ''),
    ("W1", "channel keys loaded from stack.env", "wse", WS + "test_exec_mode_skips_the_channel_keys_with_a_warning",
     '    case "$k" in CLAUDE_BG_*|CLAUDE_CODE_SESSION_KIND|CLAUDE_CODE_SANDBOXED)\n',
     '    case "$k" in NEVER_A_KEY)\n'),
    ("W2", "skipped silently", "wse", WS + "test_exec_mode_skips_the_channel_keys_with_a_warning",
     '      echo "with-stack-env: $k in stack.env skipped', '      : "with-stack-env: $k in stack.env skipped'),
    ("W3", "only CLAUDE_BG_ itself, not CLAUDE_BG_*", "wse", WS + "test_only_and_print_env_skip_them_too",
     'in CLAUDE_BG_*|CLAUDE_CODE_SESSION_KIND', 'in CLAUDE_BG_|CLAUDE_CODE_SESSION_KIND'),
    ("W4", "CLAUDE_CODE_SANDBOXED loaded (also with --only)", "wse", WS + "test_only_and_print_env_skip_them_too",
     '|CLAUDE_CODE_SANDBOXED)\n', '|CLAUDE_CODE_SESSION_KIND_NEVER)\n'),
]


def box(root: Path, key: str, text: str) -> dict[str, str]:
    if key == "guard":
        return sandbox(root, key, text)
    root.mkdir(parents=True, exist_ok=True)
    (root / "with-stack-env").write_text(text)
    return {"WITH_STACK_ENV": str(root / "with-stack-env")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--list", action="store_true")
    ap.add_argument("-k", default="")
    ap.add_argument("-j", type=int, default=4)
    ap.add_argument("--out", default="-")
    a = ap.parse_args(argv)
    keys = [k for k in a.k.split(",") if k]
    todo = [m for m in MUTANTS if not keys or any(k == m[0] or k in m[1] for k in keys)]
    if a.list:
        for mid, what, key, test, _o, _n in todo:
            print(f"{mid:<4} {key:<6} {test.split('::')[-1]:<55} {what}")
        return 0
    src = {k: p.read_text() for k, p in FILES.items()}
    bad = [(m[0], src[m[2]].count(m[4])) for m in todo if src[m[2]].count(m[4]) != 1]
    if bad:
        print("anchors that do not match exactly once:", bad)
        return 2
    scratch = Path(tempfile.mkdtemp(prefix="env-channel-mutations-"))
    lines: list[str] = []
    try:
        for key in sorted({m[2] for m in todo}):                        # the clean copies pass every named test
            names = sorted({m[3] for m in todo if m[2] == key})
            rc, out, dt = run_tests(names, box(scratch / f"base-{key}", key, src[key]), 600)
            lines.append(f"BASE  {key:<5} {len(names)} named tests: {'PASS' if rc == 0 else 'FAIL'} ({dt}s)")
            print(lines[-1], flush=True)
            if rc != 0:
                print(out[-3000:])
                return 1

        def one(i: int) -> tuple[bool, str]:
            mid, what, key, test, old, new = todo[i]
            rc, out, dt = run_tests([test], box(scratch / f"m{i:03d}", key, src[key].replace(old, new)), 600)
            k = killed_by(test, rc, out)
            r = f"{'KILLED' if k else 'ALIVE '} {mid:<4} {test.split('::')[-1]:<55} {what} [{dt}s] {first_error(out)}"
            print(r, flush=True)
            return k, r
        with ThreadPoolExecutor(max(1, a.j)) as ex:
            res = list(ex.map(one, range(len(todo))))
        lines += [r for _, r in res]
        alive = [r for k, r in res if not k]
        lines.append(f"{len(res) - len(alive)} of {len(res)} killed")
        print(lines[-1])
        if a.out != "-":
            Path(a.out).write_text("\n".join(lines) + "\n")
        return 0 if not alive else 1
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
