"""Static analysis of lib/eq-container/Dockerfile.minimal and Dockerfile.toolchains (DESIGN_DISTROLESS.md): the distroless rules
the builds depend on, written as functions of the Dockerfile text so that a seeded fault can be applied in memory.

Every rule runs on the real files (no problem expected) and on seeds, each of which breaks exactly the rule it names (a problem
naming it is expected). The rules: every FROM is scratch, an earlier stage or a digest-pinned ${ARG}; each final stage of an
[[image]] of TOOLS.toml is FROM its base (scratch, or ${DISTROLESS_CC} whose value is a gcr.io/distroless/*-debian13 digest
reference, never latest or debug); finals hold one COPY of an assemble layer, no RUN, USER 10001:10001, no ENTRYPOINT, EXPOSE,
VOLUME or HEALTHCHECK, PATH only below /opt; no apt, dpkg or snapshot anywhere and apk only in the stage bash-builder; each final
has a check stage (exec-form RUN) FROM it; the ARGs are global, equal to PINS, bare in the stages (KEEP_EXTS apart); every curl
refuses http; every download of the fetch stage is sha256sum -c checked before it is used; no ADD; COPY --from names an earlier
stage. The assemble scripts call no ldd, dpkg, apt-get or ldconfig.
Run: /Users/pmrj/.claude/venvs/tools/bin/python -m pytest -q tests/test_eq_container_dockerfiles.py
"""
import json
import re
import shlex
import tomllib
from collections import namedtuple
from pathlib import Path

import pytest

from conftest import EQC_LIB

FILES = ("Dockerfile.minimal", "Dockerfile.toolchains")
DIGEST_REF = re.compile(r"@sha256:[0-9a-f]{64}$")
DISTROLESS_SHAPE = re.compile(r"gcr\.io/distroless/[a-z0-9-]+-debian13(?::([A-Za-z0-9._-]+))?@sha256:[0-9a-f]{64}")
Instr = namedtuple("Instr", "kw args line")


class Stage:
    def __init__(self, ref, name, line):
        self.ref, self.name, self.line, self.instrs = ref, name, line, []


class Dockerfile:
    def __init__(self, text: str):
        self.global_args, self.stages = [], []
        for no, line in logical_lines(text):
            kw, _, args = line.partition(" ")
            kw, args = kw.upper(), args.strip()
            if kw == "FROM":
                toks = [t for t in args.split() if not t.startswith("--")]
                name = toks[2] if len(toks) >= 3 and toks[1].upper() == "AS" else None
                self.stages.append(Stage(toks[0], name, no))
            elif not self.stages:
                self.global_args.append(Instr(kw, args, no))
            else:
                self.stages[-1].instrs.append(Instr(kw, args, no))
        self.globals = {}
        for i in self.global_args:
            if i.kw == "ARG" and "=" in i.args:
                self.globals.setdefault(i.args.partition("=")[0], i.args.partition("=")[2])

    def stage(self, name):
        return next((s for s in self.stages if s.name and s.name.lower() == name.lower()), None)


def logical_lines(text: str) -> list:
    """(line number, instruction) with the `\\` continuations joined and the comment and blank lines dropped."""
    out, buf, start = [], None, 0
    for no, raw in enumerate(text.split("\n"), 1):
        s = raw.strip()
        if s.startswith("#") or not s:
            continue
        if buf is None:
            cur, start = s, no
        else:
            cur = buf + " " + s
        if cur.endswith("\\"):
            buf = cur[:-1].rstrip()
            continue
        out.append((start, cur))
        buf = None
    return out


def pins_of(lib: Path) -> dict:
    d = {}
    for ln in (lib / "PINS").read_text().splitlines():
        m = re.match(r"^([A-Z0-9_]+)=(.*)$", ln)
        if m:
            d.setdefault(m.group(1), []).append(m.group(2))
    return d


class Ctx:
    def __init__(self, name: str, text: str):
        self.name, self.text, self.df = name, text, Dockerfile(text)
        m = tomllib.loads((EQC_LIB / "TOOLS.toml").read_text())
        self.images = [i for i in m["image"] if i["dockerfile"] == name]
        self.pins = pins_of(EQC_LIB)


def image_refs(c: Ctx) -> list:
    """(where, value) of everything that names an image: every FROM and the ARGs whose key says so."""
    out = [("FROM at line %d" % s.line, s.ref) for s in c.df.stages]
    out += [("ARG %s" % k, v) for k, v in c.df.globals.items() if k.endswith("_IMAGE") or k == "DISTROLESS_CC"]
    return out


# ------------------------------------------------------------------------------------------------------------------- the rules
def rule_from(c):
    out, known = [], set()
    for st in c.df.stages:
        if st.ref != "scratch" and st.ref.lower() not in known:
            m = re.fullmatch(r"\$\{(\w+)\}", st.ref)
            if not m:
                out.append("FROM %s (line %d) is not scratch, an earlier stage or a ${ARG}" % (st.ref, st.line))
            elif m.group(1) not in c.df.globals:
                out.append("FROM %s (line %d): ARG %s is not declared before the first FROM" % (st.ref, st.line, m.group(1)))
            elif not DIGEST_REF.search(c.df.globals[m.group(1)]):
                out.append("FROM %s (line %d): the value of %s is not pinned by digest: %s" % (st.ref, st.line, m.group(1), c.df.globals[m.group(1)]))
        if st.name:
            known.add(st.name.lower())
    return out


def rule_final_base(c):
    out = []
    for img in c.images:
        st = c.df.stage(img["target"])
        if st is None:
            out.append("image %s: no stage %s" % (img["name"], img["target"]))
        elif img["base"] == "scratch":
            if st.ref != "scratch":
                out.append("final %s: base scratch but FROM %s" % (st.name, st.ref))
        elif img["base"] == "distroless-cc":
            if st.ref != "${DISTROLESS_CC}":
                out.append("final %s: base distroless-cc but FROM %s" % (st.name, st.ref))
            v = c.df.globals.get("DISTROLESS_CC", "")
            m = DISTROLESS_SHAPE.fullmatch(v)
            if not m or m.group(1) == "latest" or "debug" in v:
                out.append("DISTROLESS_CC=%s is not a gcr.io/distroless/<name>-debian13 digest reference (no latest, no debug)" % v)
        else:
            out.append("image %s: unknown base %s" % (img["name"], img["base"]))
    return out


def rule_final_shape(c):
    out = []
    for img in c.images:
        st = c.df.stage(img["target"])
        if st is None:
            continue
        n, ins = st.name, st.instrs
        out += ["final %s has a RUN (line %d)" % (n, i.line) for i in ins if i.kw == "RUN"]
        copies = [i for i in ins if i.kw in ("COPY", "ADD")]
        if len(copies) != 1 or copies[0].kw != "COPY" or not re.fullmatch(r"--from=assemble-[a-z0-9-]+ /rootfs/ /", copies[0].args):
            out.append("final %s: want exactly one `COPY --from=assemble-* /rootfs/ /`, got %s" % (n, [(i.kw, i.args) for i in copies]))
        users = [i.args for i in ins if i.kw == "USER"]
        if not users or any(u != "10001:10001" for u in users):
            out.append("final %s: USER must be 10001:10001, got %s" % (n, users))
        for kw in ("ENTRYPOINT", "EXPOSE", "VOLUME", "HEALTHCHECK"):
            out += ["final %s has %s (line %d)" % (n, kw, i.line) for i in ins if i.kw == kw]
        paths = [tok[5:] for i in ins if i.kw == "ENV" for tok in shlex.split(i.args) if tok.startswith("PATH=")]
        if not paths:
            out.append("final %s sets no PATH" % n)
        for p in paths:
            bad = [d for d in p.split(":") if not d.startswith("/opt/")]
            if bad:
                out.append("final %s: PATH holds %s outside /opt" % (n, bad))
    return out


def rule_no_package_manager(c):
    out = []
    for st in c.df.stages:
        for i in st.instrs:
            if re.search(r"\b(apt-get|apt|apt-cache|aptitude|dpkg)\b", i.args) or "snapshot.debian.org" in i.args:
                out.append("stage %s (line %d): apt, dpkg or the Debian snapshot" % (st.name, i.line))
            if i.kw == "RUN" and re.search(r"\bapk\b", i.args) and st.name != "bash-builder":
                out.append("stage %s (line %d): apk outside the stage bash-builder" % (st.name, i.line))
    return out


def rule_no_latest_or_debug(c):
    return ["%s names a latest or debug image: %s" % (where, v) for where, v in image_refs(c)
            if re.search(r"latest|debug", v, re.I)]


def rule_check_stages(c):
    out = []
    for img in c.images:
        t = img["target"]
        chk = c.df.stage("check-" + t)
        if chk is None:
            out.append("no check stage check-%s" % t)
            continue
        if chk.ref.lower() != t.lower():
            out.append("check-%s is FROM %s, not from %s" % (t, chk.ref, t))
        runs = [i for i in chk.instrs if i.kw == "RUN"]
        if not runs:
            out.append("check-%s has no RUN" % t)
        for r in runs:
            try:
                argv = json.loads(r.args)
                ok = isinstance(argv, list) and argv and all(isinstance(a, str) for a in argv)
            except ValueError:
                ok = False
            if not ok:
                out.append("check-%s (line %d): RUN is not in exec form (a JSON list): %s" % (t, r.line, r.args))
    return out


def rule_args(c):
    out, seen = [], {}
    for i in c.df.global_args:
        if i.kw != "ARG":
            out.append("line %d: %s before the first FROM" % (i.line, i.kw))
            continue
        k, eq, v = i.args.partition("=")
        if not eq:
            out.append("line %d: global ARG %s has no value" % (i.line, k))
        seen[k] = seen.get(k, 0) + 1
        if k in c.pins:
            if len(c.pins[k]) != 1:
                out.append("PINS holds %s %d times" % (k, len(c.pins[k])))
            elif v != c.pins[k][0]:
                out.append("ARG %s=%s differs from PINS %s" % (k, v, c.pins[k][0]))
        else:
            out.append("ARG %s is not in PINS" % k)
    out += ["global ARG %s is declared %d times" % (k, n) for k, n in seen.items() if n > 1]
    for st in c.df.stages:
        for i in st.instrs:
            if i.kw != "ARG":
                continue
            k, eq, _ = i.args.partition("=")
            if eq and k != "KEEP_EXTS":
                out.append("stage %s (line %d): ARG %s has a default (only KEEP_EXTS may); the global value is PINS's" % (st.name, i.line, k))
            elif not eq and k not in c.df.globals:
                out.append("stage %s (line %d): ARG %s is not a global ARG" % (st.name, i.line, k))
    return out


def curl_calls(text: str) -> list:
    """The text of every `curl -...` invocation in a script or RUN script (up to the next `;`, `}` or `&&`)."""
    out = []
    for m in re.finditer(r"\bcurl\s+-", text):
        tail = text[m.start():]
        end = re.search(r"[;}]|&&", tail[1:])
        out.append(tail[: end.start() + 1 if end else len(tail)])
    return out


def rule_curl_https(c):
    out = []
    for st in c.df.stages:
        for i in st.instrs:
            if i.kw != "RUN":
                continue
            for call in curl_calls(i.args):
                for flag in ("--proto '=https'", "--proto-redir '=https'"):
                    if flag not in call:
                        out.append("stage %s (line %d): a curl without %s: %s" % (st.name, i.line, flag, call[:80]))
            if re.search(r"\bwget\b", i.args):
                out.append("stage %s (line %d): wget" % (st.name, i.line))
    return out


def tokens_of(statement: str, name: str) -> bool:
    return re.search(r"(?<![\w./-])%s(?![\w.-])" % re.escape(name), statement) is not None


def check_before_use(statements: list, label: str) -> list:
    """Every `get FILE URL` statement is followed by a `sha256sum -c` statement naming FILE before any other statement does."""
    out = []
    for n, s in enumerate(statements):
        m = re.match(r"get (\S+) ", s)
        if not m:
            continue
        f = m.group(1)
        for later in statements[n + 1:]:
            if not tokens_of(later, f):
                continue
            if "sha256sum -c" not in later:
                out.append("%s: %s is used before it is sha256sum -c checked: %s" % (label, f, later[:80]))
            break
        else:
            out.append("%s: %s is downloaded and never checked" % (label, f))
    return out


def rule_fetch_checks_first(c):
    out = []
    for st in c.df.stages:
        for i in st.instrs:
            if i.kw == "RUN" and "get() {" in i.args:
                out += check_before_use([s.strip() for s in re.split(r";", i.args)], "stage %s" % st.name)
    return out


def rule_copy_from(c):
    out, known = [], set()
    for st in c.df.stages:
        for i in st.instrs:
            m = re.search(r"--from=(\S+)", i.args) if i.kw == "COPY" else None
            if m and m.group(1).lower() not in known:
                out.append("stage %s (line %d): COPY --from=%s is no earlier stage" % (st.name, i.line, m.group(1)))
        if st.name:
            known.add(st.name.lower())
    return out


def rule_no_add(c):
    return ["stage %s (line %d): ADD" % (st.name, i.line) for st in c.df.stages for i in st.instrs if i.kw == "ADD"]


RULES = {
    "from": rule_from, "final-base": rule_final_base, "final-shape": rule_final_shape, "no-package-manager": rule_no_package_manager,
    "no-latest-or-debug": rule_no_latest_or_debug, "check-stages": rule_check_stages, "args": rule_args, "curl-https": rule_curl_https,
    "fetch-checks-first": rule_fetch_checks_first, "copy-from": rule_copy_from, "no-add": rule_no_add,
}


# ------------------------------------------------------------------------------------------------------------------ the seeds
def sub(old, new):
    def f(text):
        assert old in text, old
        return text.replace(old, new, 1)
    return f


def rsub(pattern, repl):
    def f(text):
        out, n = re.subn(pattern, repl, text, count=1, flags=re.M)
        assert n == 1, pattern
        return out
    return f


def in_stage(stage, fn):
    """Apply fn to the text of one stage (from its FROM line to the next stage)."""
    def f(text):
        parts = re.split(r"(?m)^(?=FROM )", text)
        for i, part in enumerate(parts):
            if part.split("\n", 1)[0].endswith(" AS %s" % stage):
                parts[i] = fn(part)
                return "".join(parts)
        raise AssertionError(stage)
    return f


def after_from(line):
    return lambda part: part.replace("\n", "\n" + line + "\n", 1)


def swap_with_next(needle):
    def f(text):
        lines = text.split("\n")
        i = next(i for i, ln in enumerate(lines) if needle in ln)
        lines[i], lines[i + 1] = lines[i + 1], lines[i]
        return "\n".join(lines)
    return f


def drop_line(needle):
    def f(text):
        lines = text.split("\n")
        i = next(i for i, ln in enumerate(lines) if needle in ln)
        del lines[i]
        return "\n".join(lines)
    return f


M, T = "Dockerfile.minimal", "Dockerfile.toolchains"
SHA64 = "0" * 64
# (id, file, rule, transform, text a problem must hold)
SEEDS = [
    # every FROM is scratch, an earlier stage or a digest-pinned ${ARG}
    ("from-debian", M, "from", sub("FROM ${BUILDER_IMAGE} AS fetch", "FROM debian:trixie-slim AS fetch"), "FROM debian:trixie-slim"),
    ("from-alpine-tag", M, "from", sub("FROM ${MUSL_BUILDER_IMAGE} AS bash-builder", "FROM alpine:3.24 AS bash-builder"), "FROM alpine:3.24"),
    ("from-arg-without-digest", M, "from", rsub(r"^(ARG BUILDER_IMAGE=[^@\n]*)@sha256:[0-9a-f]{64}$", r"\1"), "is not pinned by digest"),
    ("from-arg-with-a-short-digest", M, "from", rsub(r"^(ARG MUSL_BUILDER_IMAGE=.*@sha256:[0-9a-f]{63})[0-9a-f]$", r"\1"), "is not pinned by digest"),
    ("from-undeclared-arg", M, "from", sub("FROM ${BUILDER_IMAGE} AS prep", "FROM ${NO_SUCH_IMAGE} AS prep"), "is not declared"),
    ("from-a-later-stage", M, "from", sub("FROM mathlib AS leanpath", "FROM assemble-both AS leanpath"), "FROM assemble-both"),
    ("from-ubuntu-in-toolchains", T, "from", sub("FROM ${BUILDER_IMAGE} AS tools-fetch", "FROM ubuntu:24.04 AS tools-fetch"), "FROM ubuntu:24.04"),
    ("from-arg-without-digest-in-toolchains", T, "from", rsub(r"^(ARG DISTROLESS_CC=[^@\n]*)@sha256:[0-9a-f]{64}$", r"\1"),
     "is not pinned by digest"),
    # each final target's FROM matches its base in TOOLS.toml
    ("final-from-debian", M, "final-base", sub("FROM ${DISTROLESS_CC} AS eq-min", "FROM debian:trixie-slim AS eq-min"),
     "final eq-min: base distroless-cc but FROM debian:trixie-slim"),
    ("final-debug-variant", M, "final-base", rsub(r"^(ARG DISTROLESS_CC=gcr\.io/distroless/cc-debian13)@", r"\1:debug-nonroot@"), "is not a gcr.io/distroless"),
    ("final-tag-only", M, "final-base", rsub(r"^(ARG DISTROLESS_CC=[^@\n]*)@sha256:[0-9a-f]{64}$", r"\1:nonroot"), "is not a gcr.io/distroless"),
    ("final-latest", M, "final-base", rsub(r"^(ARG DISTROLESS_CC=gcr\.io/distroless/cc-debian13)@", r"\1:latest@"), "is not a gcr.io/distroless"),
    ("final-wrong-family", M, "final-base", rsub(r"^ARG DISTROLESS_CC=gcr\.io/distroless/cc-debian13@", "ARG DISTROLESS_CC=gcr.io/distroless/cc-debian12@"),
     "is not a gcr.io/distroless"),
    ("final-another-registry", M, "final-base", rsub(r"^ARG DISTROLESS_CC=gcr\.io/", "ARG DISTROLESS_CC=docker.io/"), "is not a gcr.io/distroless"),
    ("scratch-final-from-distroless", T, "final-base", sub("FROM scratch AS eq-go", "FROM ${DISTROLESS_CC} AS eq-go"),
     "final eq-go: base scratch but FROM ${DISTROLESS_CC}"),
    ("distroless-final-from-scratch", T, "final-base", sub("FROM ${DISTROLESS_CC} AS eq-node", "FROM scratch AS eq-node"),
     "final eq-node: base distroless-cc but FROM scratch"),
    ("final-stage-missing", M, "final-base", sub("AS eq-py-min", "AS eq-py-minimal"), "no stage eq-py-min"),
    # finals: no RUN, one COPY of an assemble layer, USER 10001:10001, no ENTRYPOINT/EXPOSE/VOLUME/HEALTHCHECK, PATH under /opt
    ("final-with-a-run", M, "final-shape", in_stage("eq-min", after_from("RUN apt-get install x")), "final eq-min has a RUN"),
    ("final-user-root", M, "final-shape", in_stage("eq-min", lambda p: p.replace("USER 10001:10001", "USER root")), "USER must be 10001:10001"),
    ("final-user-missing", M, "final-shape", in_stage("eq-py-min", lambda p: p.replace("USER 10001:10001\n", "")), "USER must be 10001:10001"),
    ("final-second-copy", M, "final-shape", in_stage("eq-min", after_from("COPY minimal/check.sh /check.sh")), "exactly one `COPY --from=assemble-*"),
    ("final-copy-from-a-fetch-stage", M, "final-shape", in_stage("eq-min", lambda p: p.replace("--from=assemble-both /rootfs/", "--from=fetch /opt/lean")),
     "exactly one `COPY --from=assemble-*"),
    ("final-add", M, "final-shape", in_stage("eq-min", lambda p: p.replace("COPY --from=assemble-both /rootfs/ /", "ADD rootfs.tar /")),
     "exactly one `COPY"),
    ("final-path-with-usr-bin", M, "final-shape", in_stage("eq-min", lambda p: p.replace("PATH=/opt/eq/bin:", "PATH=/usr/bin:/opt/eq/bin:")),
     "outside /opt"),
    ("final-path-prefix-trick", M, "final-shape", in_stage("eq-py-min", lambda p: p.replace("PATH=/opt/eq/bin:", "PATH=/optx/bin:/opt/eq/bin:")),
     "outside /opt"),
    ("final-without-path", T, "final-shape", in_stage("eq-node", lambda p: p.replace("ENV PATH=/opt/node/bin ", "ENV ")), "sets no PATH"),
    ("final-entrypoint", M, "final-shape", in_stage("eq-min", after_from('ENTRYPOINT ["/opt/eq/bin/bash"]')), "has ENTRYPOINT"),
    ("final-expose", T, "final-shape", in_stage("eq-julia", after_from("EXPOSE 8080")), "has EXPOSE"),
    ("final-volume", M, "final-shape", in_stage("eq-lean-min", after_from("VOLUME /data")), "has VOLUME"),
    ("final-healthcheck", T, "final-shape", in_stage("eq-jvm", after_from("HEALTHCHECK CMD true")), "has HEALTHCHECK"),
    # no apt, dpkg or Debian snapshot anywhere, apk only in bash-builder
    ("apt-get-in-a-final", M, "no-package-manager", in_stage("eq-min", after_from("RUN apt-get install x")), "apt, dpkg or the Debian snapshot"),
    ("apt-get-update-in-mathlib", M, "no-package-manager", in_stage("mathlib", after_from("RUN apt-get update")), "apt, dpkg or the Debian snapshot"),
    ("dpkg-in-prep", M, "no-package-manager", in_stage("prep", after_from("RUN dpkg -i /x.deb")), "apt, dpkg or the Debian snapshot"),
    ("apt-in-fetch", M, "no-package-manager", in_stage("fetch", after_from("RUN apt install -y curl")), "apt, dpkg or the Debian snapshot"),
    ("debian-snapshot-url", M, "no-package-manager", sub("get jq ", "get jq-x \"https://snapshot.debian.org/archive/debian/x\"; get jq "),
     "apt, dpkg or the Debian snapshot"),
    ("apk-in-fetch", M, "no-package-manager", in_stage("fetch", after_from("RUN apk add curl")), "apk outside the stage bash-builder"),
    ("apk-in-the-bash-stage", M, "no-package-manager", in_stage("bash", after_from("RUN apk add x")), "apk outside the stage bash-builder"),
    ("apk-in-toolchains", T, "no-package-manager", in_stage("tools-fetch", after_from("RUN apk add xz")), "apk outside the stage bash-builder"),
    ("apt-get-in-toolchains", T, "no-package-manager", in_stage("assemble-go", after_from("RUN apt-get install x")), "apt, dpkg"),
    # no `latest` or `debug` image in any FROM or image ARG
    ("arg-latest", M, "no-latest-or-debug", rsub(r"^(ARG MUSL_BUILDER_IMAGE=alpine):3\.24@", r"\1:latest@"), "names a latest or debug image"),
    ("arg-debug", M, "no-latest-or-debug", rsub(r"^(ARG DISTROLESS_CC=gcr\.io/distroless/cc-debian13)@", r"\1:debug-nonroot@"),
     "names a latest or debug image"),
    ("from-debug", M, "no-latest-or-debug", sub("FROM ${DISTROLESS_CC} AS distroless-cc", "FROM gcr.io/distroless/cc-debian13:debug AS distroless-cc"),
     "names a latest or debug image"),
    ("from-latest-toolchains", T, "no-latest-or-debug", sub("FROM scratch AS eq-go", "FROM golang:latest AS eq-go"), "names a latest or debug image"),
    # every final has a check stage FROM it with an exec-form RUN
    ("check-shell-form", M, "check-stages", sub('RUN ["/opt/eq/bin/busybox", "sh", "/opt/eq-check/check.sh", "both"]',
                                                "RUN /opt/eq/bin/busybox sh /opt/eq-check/check.sh both"), "not in exec form"),
    ("check-stage-missing", M, "check-stages", sub("AS check-eq-lean-min", "AS verify-eq-lean-min"), "no check stage check-eq-lean-min"),
    ("check-from-another-stage", M, "check-stages", sub("FROM eq-py-min AS check-eq-py-min", "FROM eq-min AS check-eq-py-min"),
     "check-eq-py-min is FROM eq-min"),
    ("check-without-run", M, "check-stages", sub('RUN ["/opt/eq/bin/busybox", "sh", "/opt/eq-check/check.sh", "py"]', "WORKDIR /work"),
     "check-eq-py-min has no RUN"),
    ("check-shell-form-toolchains", T, "check-stages", sub('RUN ["/opt/go/bin/go", "version"]', "RUN /opt/go/bin/go version"), "not in exec form"),
    ("check-stage-missing-toolchains", T, "check-stages", sub("AS check-eq-jvm", "AS verify-eq-jvm"), "no check stage check-eq-jvm"),
    # the ARGs: global, one per key, equal to PINS, bare in the stages (KEEP_EXTS apart)
    ("arg-with-a-default-in-a-stage", M, "args", in_stage("fetch", lambda p: p.replace("ARG LEAN_SHA256\n", "ARG LEAN_SHA256=" + SHA64 + "\n")),
     "ARG LEAN_SHA256 has a default"),
    ("arg-global-differs-from-pins", M, "args", sub("ARG UV_VERSION=0.12.22", "ARG UV_VERSION=0.12.23"), "ARG UV_VERSION=0.12.23 differs from PINS"),
    ("arg-global-twice", M, "args", sub("ARG LEAN_VERSION=4.34.1\n", "ARG LEAN_VERSION=4.34.1\nARG LEAN_VERSION=4.34.1\n"),
     "global ARG LEAN_VERSION is declared 2 times"),
    ("arg-bare-but-not-global", M, "args", in_stage("fetch", after_from("ARG NOT_A_GLOBAL")), "ARG NOT_A_GLOBAL is not a global ARG"),
    ("arg-global-not-in-pins", M, "args", sub("ARG LEAN_VERSION=4.34.1\n", "ARG LEAN_VERSION=4.34.1\nARG EXTRA_X=1\n"), "ARG EXTRA_X is not in PINS"),
    ("arg-global-without-a-value", M, "args", sub("ARG LEAN_VERSION=4.34.1\n", "ARG LEAN_VERSION=4.34.1\nARG EXTRA_Y\n"), "global ARG EXTRA_Y has no value"),
    ("arg-keep-exts-default-elsewhere", M, "args", in_stage("assemble-py", after_from('ARG LEAN_VERSION="9"')), "ARG LEAN_VERSION has a default"),
    ("arg-toolchains-differs", T, "args", rsub(r"^ARG DISTROLESS_CC_ARM64=sha256:[0-9a-f]{64}$", "ARG DISTROLESS_CC_ARM64=sha256:" + SHA64),
     "ARG DISTROLESS_CC_ARM64=sha256:%s differs from PINS" % SHA64),
    ("arg-toolchains-stage-default", T, "args", in_stage("assemble-node", lambda p: p.replace("ARG DISTROLESS_CC\n", "ARG DISTROLESS_CC=x\n", 1)),
     "ARG DISTROLESS_CC has a default"),
    # every curl refuses http and non-https redirects
    ("curl-without-proto-redir", M, "curl-https", sub(" --proto-redir '=https'", ""), "a curl without --proto-redir '=https'"),
    ("curl-without-proto", M, "curl-https", sub("curl --proto '=https' ", "curl "), "a curl without --proto '=https'"),
    ("curl-plain-in-another-stage", M, "curl-https", in_stage("mathlib", after_from("RUN curl -fsSL https://example.test/x -o /x")),
     "a curl without --proto"),
    ("wget", M, "curl-https", in_stage("mathlib", after_from("RUN wget https://example.test/x")), "wget"),
    # in the fetch stage a download is checked before anything uses it
    ("fetch-install-before-the-check", M, "fetch-checks-first", swap_with_next('echo "${JQ_SHA256}  jq"'), "jq is used before it is sha256sum -c checked"),
    ("fetch-unpack-before-the-check", M, "fetch-checks-first", swap_with_next('echo "${PYTHON_SHA256}  py.tar.gz"'),
     "py.tar.gz is used before it is sha256sum -c checked"),
    ("fetch-untar-before-the-check", M, "fetch-checks-first", swap_with_next('echo "${LEAN_SHA256}  lean.tar.zst"'),
     "lean.tar.zst is used before it is sha256sum -c checked"),
    ("fetch-check-dropped", M, "fetch-checks-first", drop_line('echo "${UV_SHA256}  uv.tar.gz"'), "uv.tar.gz is used before it is sha256sum -c checked"),
    ("fetch-busybox-check-dropped", M, "fetch-checks-first", drop_line('echo "${BUSYBOX_ROOTFS_SHA256}  busybox-rootfs.tar.gz"'),
     "busybox-rootfs.tar.gz is used before it is sha256sum -c checked"),
    ("fetch-download-never-used-or-checked", M, "fetch-checks-first", sub("    cd /; rm -rf /tmp/dl", '    get stray "https://example.test/stray"; \\\n    cd /; rm -rf /tmp/dl'),
     "stray is downloaded and never checked"),
    # COPY --from names an earlier stage; no ADD
    ("copy-from-an-image", M, "copy-from", in_stage("prep", after_from("COPY --from=nginx /etc/nginx /x")), "COPY --from=nginx is no earlier stage"),
    ("copy-from-a-later-stage", M, "copy-from", in_stage("prep", after_from("COPY --from=assemble-both /rootfs /x")),
     "COPY --from=assemble-both is no earlier stage"),
    ("copy-from-a-later-stage-toolchains", T, "copy-from", in_stage("tools-fetch", after_from("COPY --from=eq-go /opt /x")),
     "COPY --from=eq-go is no earlier stage"),
    ("add-a-url", M, "no-add", in_stage("fetch", after_from("ADD https://example.test/x /x")), "ADD"),
    ("add-in-toolchains", T, "no-add", in_stage("tools-fetch", after_from("ADD x /x")), "ADD"),
]
# changes that must NOT be a problem for the rule named (the rules read instructions, not comments or neighbouring spellings)
CONTROLS = [
    ("comment-mentions-apt-get", M, "no-package-manager", sub("FROM ${BUILDER_IMAGE} AS fetch", "# apt-get and dpkg are gone, apk is only in bash-builder\nFROM ${BUILDER_IMAGE} AS fetch")),
    ("comment-between-continued-lines", M, "fetch-checks-first", sub("    get jq ", "    # a comment inside a continued RUN\n    get jq ")),
    ("keep-exts-default-in-a-stage", M, "args", in_stage("assemble-py", after_from('ARG KEEP_EXTS="olean"'))),
    ("latest-in-a-url-is-not-an-image", M, "no-latest-or-debug", sub("ARG JQ_VERSION=1.8.2", "ARG JQ_VERSION=1.8.2\nARG NOTE_URL=https://example.test/latest/x")),
    ("curl-package-name-in-apk", M, "curl-https", in_stage("bash-builder", after_from("RUN echo curl is a package here"))),
    ("a-stage-name-in-another-case", M, "from", sub("FROM mathlib AS leanpath", "FROM MATHLIB AS leanpath")),
]


def problems(rule: str, name: str, text: str) -> list:
    return RULES[rule](Ctx(name, text))


def real(name: str) -> str:
    return (EQC_LIB / name).read_text()


@pytest.mark.parametrize("name", FILES)
@pytest.mark.parametrize("rule", sorted(RULES))
def test_the_real_dockerfiles_pass_every_rule(rule, name):
    assert problems(rule, name, real(name)) == []


@pytest.mark.parametrize("seed", SEEDS, ids=[s[0] for s in SEEDS])
def test_a_seeded_fault_is_caught_by_its_rule(seed):
    _, name, rule, transform, needle = seed
    got = problems(rule, name, transform(real(name)))
    assert any(needle in p for p in got), (needle, got)


@pytest.mark.parametrize("control", CONTROLS, ids=[c[0] for c in CONTROLS])
def test_a_harmless_change_is_not_a_problem(control):
    _, name, rule, transform = control
    assert problems(rule, name, transform(real(name))) == []


def test_every_rule_has_a_seed_in_each_dockerfile_it_can_break():
    assert {s[2] for s in SEEDS} == set(RULES)
    assert {(s[1], s[2]) for s in SEEDS} >= {(M, r) for r in RULES}


def test_the_parser_joins_continuations_and_skips_comments():
    text = "# c\nARG A=1\nFROM x AS s\nRUN a \\\n  # inside\n  b \\\n\n  c\nENV P=/opt/x \\\n  Q=2\n"
    df = Dockerfile(text)
    assert df.globals == {"A": "1"} and [(s.ref, s.name) for s in df.stages] == [("x", "s")]
    assert [(i.kw, i.args) for i in df.stages[0].instrs] == [("RUN", "a b c"), ("ENV", "P=/opt/x Q=2")]


def test_the_targets_of_tools_toml_are_the_stages_of_the_dockerfiles():
    m = tomllib.loads((EQC_LIB / "TOOLS.toml").read_text())
    for img in m["image"]:
        assert img["dockerfile"] in FILES, img["name"]
        df = Dockerfile(real(img["dockerfile"]))
        assert df.stage(img["target"]) and df.stage("check-" + img["target"]), img["name"]
    assert {i["target"] for i in m["image"] if i["dockerfile"] == M} == {"eq-min", "eq-py-min", "eq-lean-min"}
    assert {i["target"] for i in m["image"] if i["dockerfile"] == T} == {"eq-node", "eq-go", "eq-julia", "eq-jvm"}


def test_pins_hold_every_global_arg_of_the_minimal_dockerfile_once():
    pins = pins_of(EQC_LIB)
    assert all(len(v) == 1 for v in pins.values())
    assert set(pins) == set(Dockerfile(real(M)).globals)
    assert set(Dockerfile(real(T)).globals) <= set(pins)


def test_the_debian_image_and_its_helpers_are_gone():
    for rel in ("Dockerfile", "distro-pins.sh", "tc/apt-closure.sh"):
        assert not (EQC_LIB / rel).exists(), rel
    for k in ("BASE_IMAGE", "APT_SNAPSHOT", "BASE_LAYER_URL", "BASE_LAYER_SHA256"):
        assert k not in pins_of(EQC_LIB), k


# ------------------------------------------------------------------------------------------------------ the shell scripts
def code_of(text: str) -> str:
    """The script without its comment lines and without `-name X` operands (the deny-list of package-manager file names)."""
    lines = [ln for ln in text.split("\n") if not ln.strip().startswith("#")]
    return re.sub(r"-name\s+\S+", "", "\n".join(lines))


def rule_script_no_distro(text: str) -> list:
    return ["calls %s" % m.group(1) for m in re.finditer(r"\b(ldd|dpkg|apt-get|ldconfig)\b", code_of(text))]


SCRIPTS = ("minimal/mkrootfs.sh", "tc/mkrootfs-tc.sh")
SCRIPT_SEEDS = [
    ("ldd-line", "minimal/mkrootfs.sh", lambda t: t + '\nldd "$f"\n', "calls ldd"),
    ("ldd-in-a-pipe", "tc/mkrootfs-tc.sh", sub("is_elf() {", 'ldd /x | head -n1\nis_elf() {'), "calls ldd"),
    ("dpkg-call", "minimal/mkrootfs.sh", lambda t: t + "\ndpkg -i /x.deb\n", "calls dpkg"),
    ("apt-get-call", "tc/mkrootfs-tc.sh", lambda t: t + "\napt-get install -y x\n", "calls apt-get"),
    ("ldconfig-call", "minimal/mkrootfs.sh", lambda t: t + "\nldconfig\n", "calls ldconfig"),
    ("ldd-after-another-find-name", "minimal/mkrootfs.sh", lambda t: t + "\nfind / -name x; ldd y\n", "calls ldd"),
]


@pytest.mark.parametrize("rel", SCRIPTS)
def test_the_assemble_scripts_call_no_distribution_tool(rel):
    assert rule_script_no_distro((EQC_LIB / rel).read_text()) == []


@pytest.mark.parametrize("seed", SCRIPT_SEEDS, ids=[s[0] for s in SCRIPT_SEEDS])
def test_a_distribution_tool_in_an_assemble_script_is_caught(seed):
    _, rel, transform, needle = seed
    assert needle in rule_script_no_distro(transform((EQC_LIB / rel).read_text())), seed[0]


def test_comments_and_the_package_manager_deny_list_are_not_calls():
    t = "# ldd is not used\nfind / -type f \\( -name apt -o -name apt-get -o -name dpkg \\) -print\n"
    assert rule_script_no_distro(t) == []
    assert 'name apt' in (EQC_LIB / "minimal/mkrootfs.sh").read_text()      # the real deny list is what the stripping is for


CURL_SCRIPTS = ("tc/build-bash.sh", "tc/fetch-tool.sh")


def rule_script_curl(text: str) -> list:
    out = []
    for call in curl_calls(code_of(text)):
        out += ["a curl without %s" % f for f in ("--proto '=https'", "--proto-redir '=https'") if f not in call]
    return out


@pytest.mark.parametrize("rel", CURL_SCRIPTS)
def test_the_scripts_curl_refuses_http_and_non_https_redirects(rel):
    text = (EQC_LIB / rel).read_text()
    assert curl_calls(text), rel
    assert rule_script_curl(text) == []
    assert rule_script_curl(text.replace(" --proto-redir '=https'", "")) == ["a curl without --proto-redir '=https'"]
    assert rule_script_curl(text.replace("--proto '=https' ", "")) == ["a curl without --proto '=https'"]
    assert rule_script_curl(text.replace("--proto '=https' --proto-redir '=https' ", "")) != []


def test_fetch_tool_checks_the_archive_before_it_extracts_or_installs_it():
    text = (EQC_LIB / "tc" / "fetch-tool.sh").read_text().split("\n")

    def first(pattern, after=0):
        return next(i for i, ln in enumerate(text) if i >= after and re.search(pattern, ln) and not ln.strip().startswith("#"))
    dl = first(r"\bcurl\b")
    chk = first(r"sha256sum -c", dl)
    unpack = first(r"tar -x|unzip -q|install -D", dl)
    assert dl < chk < unpack, (dl, chk, unpack)
    chk_recipe = first(r"recipe differs from recipe_sha256")
    run_recipe = first(r"SRC=\$target DEST=\$dest bash")
    assert chk_recipe < run_recipe                                            # the recipe's own hash is checked before it runs


def test_build_bash_verifies_every_signature_before_it_unpacks_anything():
    text = (EQC_LIB / "tc" / "build-bash.sh").read_text().split("\n")
    code = [(i, ln) for i, ln in enumerate(text) if not ln.strip().startswith("#")]
    idx = lambda pat: next(i for i, ln in code if re.search(pat, ln))      # noqa: E731
    assert idx(r"--recv-keys") < idx(r'\[ "\$prim" = ') < idx(r"^verify bash\.tar\.gz") < idx(r"SIGNATURES OK") < idx(r"^tar -xzf")
    assert idx(r"^  verify \"\$p\"") < idx(r"SIGNATURES OK")
    assert idx(r"^check BASH_PATCHES_SHA256") < idx(r"^tar -xzf")
