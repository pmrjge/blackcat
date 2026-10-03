#!/usr/bin/env python3
"""read_gate.py: a token gate on reads of generated, vendored, data, media and binary files.

PreToolUse hook (settings.json matcher Read|Grep|Glob|Bash). The first Read, Grep, Glob or Bash
reader (cat, grep, rg, find, sed, awk, jq, xxd, ...) of a gated target is refused with a message
naming a cheaper alternative; the identical call repeated by the same agent passes (the agent has
decided it really needs it). Not a guard: nothing here is a security boundary, and every error
fails open (the call proceeds).

Gated targets (CONFIG.md, "Read gate"):
  build   generated output: .next .nuxt .output .svelte-kit .astro .docusaurus _site htmlcov
          .nyc_output DerivedData .build dist-newstyle _build zig-out .zig-cache .stack-work
          resources/_gen (Hugo) .lake/build (only: .lake/packages holds Mathlib's sources);
          public dist build out target coverage only when git ignores and does not track them, or public/ beside a
          Hugo config; *.min.js *.min.css *.map
  deps    dependencies and tool caches: node_modules .venv venv .tox .nox __pycache__ .mypy_cache
          .pytest_cache .ruff_cache .hypothesis .ipynb_checkpoints .gradle Pods .terraform
          .terragrunt-cache .pixi .direnv .eggs .parcel-cache .turbo .angular .dart_tool
          elm-stuff bower_components jspm_packages .yarn/cache; vendor when git-ignored;
          lockfiles over READ_GATE_LOCK_BYTES
  data    model weights and binary data (.parquet .db .sqlite .npy .pt .safetensors .gguf ...);
          text data (.csv .tsv .jsonl .json .xml .log .sql ...) over READ_GATE_DATA_BYTES
  visual  video, audio, 3D and layered design files; images over READ_GATE_IMAGE_BYTES
  binary  objects, libraries, archives, fonts, bytecode
Never gated: anything under a .claude-work/ directory; Read with 0 < limit <= READ_GATE_LIMIT;
Grep unless output_mode is content without head_limit <= READ_GATE_LIMIT; Bash readers whose output is cut
(| head, | tail, | wc, grep -l/-c/-q, > file) or capped (head, tail, find -maxdepth <= 2).
Exemptions: READ_GATE_EXEMPT_<CATEGORY> agent types (a `<type>-copy` counts as its base).

Retry state: ${XDG_STATE_HOME:-~/.local/state}/claude-agent-stack/<session_id>/read-gate.json,
{key: [ts, hits]} with key = sha256(agent_id, tool, the call's input), at most
READ_GATE_MAX_KEYS entries (oldest dropped), written under flock; agent_guard's SessionStart
deletes session folders idle for 3 days. A state that cannot be read or written lets the call pass
(refusing without memory would make the retry impossible).

Knobs: KNOBS below, overridden by the same names in stack.env ($STACK_ENV_FILE, else ../stack.env);
READ_GATE=0 there or in the environment turns the gate off.

  /usr/bin/python3 read_gate.py < event.json     hook mode
  /usr/bin/python3 read_gate.py --self-test      built-in cases
  /usr/bin/python3 read_gate.py --print          effective knob values
"""
import fcntl
import glob
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time

# name: (default, meaning). The single source of these values; stack.env.example documents them.
KNOBS = {
    "READ_GATE": ("1", "0 turns the read gate off (also as an environment variable)"),
    "READ_GATE_LIMIT": (200, "Read limit / Grep head_limit at or under which a call passes"),
    "READ_GATE_DATA_BYTES": (262144, "text data files (.csv .tsv .jsonl .json .xml .log .sql) gated above this size"),
    "READ_GATE_LOCK_BYTES": (65536, "lockfiles gated above this size"),
    "READ_GATE_IMAGE_BYTES": (2097152, "images gated above this size"),
    "READ_GATE_MAX_KEYS": (512, "refused calls remembered per session for the retry (oldest dropped)"),
    "READ_GATE_EXEMPT_BUILD": ("verifier,frontend-engineer,browser-operator",
                               "agent types that read build output without the gate"),
    "READ_GATE_EXEMPT_DEPS": ("", "agent types that read dependency and cache dirs without the gate"),
    "READ_GATE_EXEMPT_DATA": (("data-engineer,data-scientist,db-engineer,ml-engineer,dl-engineer,"
                               "llm-engineer,mlx-engineer"), "agent types that read data files without the gate"),
    "READ_GATE_EXEMPT_VISUAL": ("designer,motion-designer,image-director,cg-artist,doc-specialist",
                                "agent types that read media files without the gate"),
    "READ_GATE_EXEMPT_BINARY": ("", "agent types that read binary files without the gate"),
}
KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

BUILD_DIRS = {".next", ".nuxt", ".output", ".svelte-kit", ".astro", ".docusaurus", "_site", "htmlcov",
              ".nyc_output", "DerivedData", ".build", "dist-newstyle", "_build", "zig-out", ".zig-cache",
              "zig-cache", ".stack-work"}
BUILD_PAIRS = {("resources", "_gen"), (".lake", "build")}
AMBIG_BUILD = {"public", "dist", "build", "out", "target", "coverage"}
DEPS_DIRS = {"node_modules", ".venv", "venv", ".tox", ".nox", "__pycache__", ".mypy_cache", ".pytest_cache",
             ".ruff_cache", ".hypothesis", ".ipynb_checkpoints", ".gradle", "Pods", ".terraform",
             ".terragrunt-cache", ".pixi", ".direnv", ".eggs", ".parcel-cache", ".turbo", ".angular",
             ".dart_tool", "elm-stuff", "bower_components", "jspm_packages"}
DEPS_PAIRS = {(".yarn", "cache")}
AMBIG_DEPS = {"vendor"}
HUGO_CONFIGS = ("hugo.toml", "hugo.yaml", "hugo.yml", "hugo.json")
LOCKFILES = {"package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lock", "bun.lockb",
             "Cargo.lock", "poetry.lock", "uv.lock", "Pipfile.lock", "pdm.lock", "Gemfile.lock",
             "composer.lock", "go.sum", "Podfile.lock", "Package.resolved", "flake.lock", "mix.lock",
             "pubspec.lock", "gradle.lockfile", "packages.lock.json", "pixi.lock", "deno.lock",
             "Manifest.toml", "stack.yaml.lock", "conda-lock.yml"}
GENERATED_SUFFIXES = (".min.js", ".min.css", ".js.map", ".css.map", ".mjs.map")
TEXT_DATA = {".csv", ".tsv", ".psv", ".jsonl", ".ndjson", ".json", ".geojson", ".xml", ".log", ".sql"}
BIN_DATA = {".parquet", ".feather", ".arrow", ".ipc", ".orc", ".avro", ".db", ".sqlite", ".sqlite3",
            ".duckdb", ".h5", ".hdf5", ".nc", ".npy", ".npz", ".pkl", ".pickle", ".joblib", ".pt", ".pth",
            ".ckpt", ".safetensors", ".onnx", ".gguf", ".ggml", ".tflite", ".mlmodel", ".bin", ".tfrecord",
            ".lance", ".mat", ".sav", ".dta", ".rds", ".rdata"}
IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".tif", ".tiff", ".bmp", ".heic", ".heif", ".avif", ".ico"}
MEDIA = {".psd", ".psb", ".ai", ".eps", ".indd", ".sketch", ".fig", ".xcf", ".kra", ".exr", ".hdr", ".dds",
         ".ktx", ".ktx2", ".tga", ".cr2", ".nef", ".arw", ".dng",
         ".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".mpg", ".mpeg", ".wmv", ".flv", ".aep", ".prproj",
         ".wav", ".mp3", ".flac", ".aac", ".m4a", ".ogg", ".oga", ".opus", ".aif", ".aiff", ".wma",
         ".blend", ".blend1", ".fbx", ".obj", ".glb", ".gltf", ".usd", ".usda", ".usdc", ".usdz", ".abc",
         ".vdb", ".stl", ".3mf", ".ply", ".ztl", ".zpr", ".spp", ".sbsar", ".sbs", ".c4d", ".ma", ".mb",
         ".max", ".hip", ".hipnc", ".bgeo"}
BINARY = {".so", ".dylib", ".dll", ".o", ".a", ".lib", ".class", ".jar", ".war", ".ear", ".wasm", ".exe",
          ".pyc", ".pyo", ".pyd", ".whl", ".egg", ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".zst",
          ".lz4", ".7z", ".rar", ".dmg", ".iso", ".pkg", ".deb", ".rpm", ".apk", ".aab", ".ipa", ".ttf",
          ".otf", ".woff", ".woff2", ".node", ".rlib", ".rmeta", ".pdb"}

HINTS = {
    "build": ("generated build output",
              ("read the sources it is built from (content/, layouts/, src/, the build config); to check "
               "the result, build it and look at it in a browser (verifier, frontend-engineer)")),
    "deps": ("a dependency or tool-cache directory",
             ("read the package's docs (libdocs, WebFetch) or locate the one file first with "
              "`rg -l <symbol> <dir>` and Read it with a limit")),
    "lock": ("a large lockfile",
             ("`rg -n '<package>' <file>` for the entry you need, or the package manager (`npm ls`, "
              "`uv tree`, `cargo tree`)")),
    "data": ("a data file",
             ("profile it: `head -n 20`, `wc -l`, `duckdb -c \"DESCRIBE '<file>'\"`, or Read with a "
              "limit; data agents (data-engineer, data-scientist, ml-engineer) are exempt")),
    "visual": ("a heavy media file",
               ("inspect metadata with `file`, `sips -g all`, `ffprobe`; designer or image-director "
                "judge visuals")),
    "binary": ("a binary file", "use `file`, `ls -l` or `strings <file> | head`"),
}
EXEMPT_KNOB = {"build": "READ_GATE_EXEMPT_BUILD", "deps": "READ_GATE_EXEMPT_DEPS", "lock": "READ_GATE_EXEMPT_DEPS",
               "data": "READ_GATE_EXEMPT_DATA", "visual": "READ_GATE_EXEMPT_VISUAL",
               "binary": "READ_GATE_EXEMPT_BINARY"}


# ---------------------------------------------------------------- knobs

def env_path():
    explicit = os.environ.get("STACK_ENV_FILE")
    if explicit:
        return os.path.expanduser(explicit)
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "stack.env")


def read_knobs(path=None):
    """KNOBS defaults overridden by stack.env lines for the same names (shell-style KEY=value)."""
    vals = {k: v[0] for k, v in KNOBS.items()}
    try:
        with open(path or env_path(), encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError):
        text = ""
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("export "):
            s = s[7:].lstrip()
        key, sep, value = s.partition("=")
        key = key.strip()
        if not sep or key not in KNOBS or not KEY_RE.fullmatch(key):
            continue
        value = value.strip()
        if value[:1] in ("'", '"') and value[0] in value[1:]:
            value = value[1:value.index(value[0], 1)]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        if isinstance(KNOBS[key][0], int):
            try:
                vals[key] = max(0, int(value))
            except ValueError:
                pass                     # a malformed number keeps the default
        else:
            vals[key] = value
    if os.environ.get("READ_GATE", "").strip() != "":
        vals["READ_GATE"] = os.environ["READ_GATE"].strip()
    return vals


def agent_type(ev):
    """The calling agent's type, lowercased, a `<type>-copy` and a `plugin:type` mapped to type."""
    t = str(ev.get("agent_type") or "").strip().lower()
    t = t.rsplit(":", 1)[-1]
    t = re.sub(r"[\s_]+", "-", t)
    return t.removesuffix("-copy")


def exempt(knobs, category, atype):
    names = {n.strip().lower() for n in str(knobs.get(EXEMPT_KNOB[category], "")).split(",")}
    return bool(atype) and atype in names


# ---------------------------------------------------------------- classification

class Ctx:
    """Per-call caches for the git and filesystem probes."""

    def __init__(self):
        self.ignored = {}

    def git_ignored(self, dirpath):
        """True when git ignores directory dirpath (probed through a child path, which also works
        for a directory that does not exist yet). Not in a repository, or git failing: False."""
        if dirpath in self.ignored:
            return self.ignored[dirpath]
        anc = dirpath
        while anc and not os.path.isdir(anc):
            parent = os.path.dirname(anc)
            if parent == anc:
                break
            anc = parent
        res = False
        try:
            r = subprocess.run(["git", "-C", anc or "/", "check-ignore", "-q",
                                os.path.join(dirpath, "read-gate-probe")],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"), timeout=3, check=False)
            res = r.returncode == 0
            if res:                      # ignored by a pattern but tracked (src/build/ under `build/`): source
                t = subprocess.run(["git", "-C", anc or "/", "ls-files", "--error-unmatch", "--", dirpath],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"), timeout=3, check=False)
                res = t.returncode != 0
        except (OSError, subprocess.SubprocessError):
            res = False
        self.ignored[dirpath] = res
        return res


def hugo_site(parent):
    if any(os.path.isfile(os.path.join(parent, c)) for c in HUGO_CONFIGS):
        return True
    if os.path.isdir(os.path.join(parent, "config", "_default")):
        return True
    has_cfg = any(os.path.isfile(os.path.join(parent, "config." + e)) for e in ("toml", "yaml", "yml", "json"))
    return has_cfg and any(os.path.isdir(os.path.join(parent, d)) for d in ("layouts", "archetypes", "themes"))


def dir_category(path, ctx):
    """('build'|'deps', the gated directory) for the first gated directory on path, else None.
    path is absolute and normalized; its last component counts too (a search root)."""
    parts = path.split(os.sep)
    for i in range(1, len(parts)):
        name = parts[i]
        if not name:
            continue
        prefix = os.sep.join(parts[:i + 1]) or os.sep
        prev = parts[i - 1]
        if name in BUILD_DIRS or (prev, name) in BUILD_PAIRS:
            return "build", prefix
        if name in DEPS_DIRS or (prev, name) in DEPS_PAIRS:
            return "deps", prefix
        if name in AMBIG_BUILD or name in AMBIG_DEPS:
            parent = os.sep.join(parts[:i]) or os.sep
            if (name == "public" and hugo_site(parent)) or ctx.git_ignored(prefix):
                return ("deps" if name in AMBIG_DEPS else "build"), prefix
    return None


def size_of(path):
    try:
        return os.stat(path).st_size
    except OSError:
        return -1


def file_category(path, knobs):
    base = os.path.basename(path)
    low = base.lower()
    ext = os.path.splitext(low)[1]
    if low.endswith(GENERATED_SUFFIXES):
        return "build"
    if base in LOCKFILES:
        lim = knobs["READ_GATE_LOCK_BYTES"]
        return "lock" if lim and size_of(path) > lim else None
    if ext in BIN_DATA:
        return "data"
    if ext in TEXT_DATA:
        lim = knobs["READ_GATE_DATA_BYTES"]
        return "data" if lim and size_of(path) > lim else None
    if ext in MEDIA:
        return "visual"
    if ext in IMAGES:
        lim = knobs["READ_GATE_IMAGE_BYTES"]
        return "visual" if lim and size_of(path) > lim else None
    if ext in BINARY:
        return "binary"
    return None


def under_claude_work(path):
    return ".claude-work" in path.split(os.sep)


def gated(path, knobs, atype, ctx, is_file=True):
    """(category, shown path) when path is gated for this agent, else None."""
    if not path or under_claude_work(path):
        return None
    hits = []
    d = dir_category(path, ctx)
    if d:
        hits.append(d)
    if is_file:
        c = file_category(path, knobs)
        if c:
            hits.append((c, path))
    for cat, shown in hits:
        if not exempt(knobs, cat, atype):
            return cat, shown
    return None


def absolute(p, cwd):
    p = os.path.expanduser(str(p))
    if not os.path.isabs(p):
        p = os.path.join(cwd or os.getcwd(), p)
    return os.path.normpath(p)


# ---------------------------------------------------------------- tools

def small(v, knobs):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return False
    lim = knobs["READ_GATE_LIMIT"]
    return 0 < n <= lim if lim else False


def check_read(inp, cwd, knobs, atype, ctx):
    if small(inp.get("limit"), knobs):
        return None
    fp = inp.get("file_path")
    if not isinstance(fp, str) or not fp:
        return None
    return gated(absolute(fp, cwd), knobs, atype, ctx)


def literal_prefix(pattern):
    """Leading path components of a glob pattern that hold no glob characters."""
    out = []
    for comp in str(pattern).split("/"):
        if re.search(r"[*?\[\]{}]", comp):
            break
        out.append(comp)
    return "/".join(out)


def check_grep(inp, cwd, knobs, atype, ctx):
    # Grep's default output_mode is files_with_matches: paths only, like `rg -l`
    if inp.get("output_mode", "files_with_matches") != "content" or small(inp.get("head_limit"), knobs):
        return None
    p = absolute(inp.get("path") or cwd or ".", cwd)
    if os.path.isdir(p):
        g = inp.get("glob")
        if isinstance(g, str) and literal_prefix(g):
            return gated(absolute(os.path.join(p, literal_prefix(g)), cwd), knobs, atype, ctx, is_file=False)
        return gated(p, knobs, atype, ctx, is_file=False)
    return gated(p, knobs, atype, ctx)


def check_glob(inp, cwd, knobs, atype, ctx):
    base = absolute(inp.get("path") or cwd or ".", cwd)
    pat = str(inp.get("pattern") or "")
    hit = gated(base, knobs, atype, ctx, is_file=False)
    if hit or not pat:
        return hit
    if pat.startswith("/"):
        target = os.path.normpath(literal_prefix(pat) or "/")
    else:
        target = os.path.normpath(os.path.join(base, literal_prefix(pat))) if literal_prefix(pat) else base
    hit = gated(target, knobs, atype, ctx, is_file=False)
    if hit:
        return hit
    # a literal gated directory name further down the pattern: **/node_modules/**
    for comp in pat.split("/"):
        cat = "build" if comp in BUILD_DIRS else "deps" if comp in DEPS_DIRS else None
        if cat and not exempt(knobs, cat, atype):
            return cat, pat
    return None


# Bash readers: name -> kind. Metadata and capped commands (head, tail, wc, file, stat, du, ls,
# sips, ffprobe, duckdb, sqlite3) are the cheaper alternatives and never gated.
READERS = {"cat": "cat", "bat": "cat", "batcat": "cat", "less": "cat", "more": "cat", "nl": "cat", "tac": "cat",
           "xxd": "dump", "hexdump": "dump", "od": "dump", "strings": "cat",
           "grep": "grep", "egrep": "grep", "fgrep": "grep", "ugrep": "grep", "rg": "rg", "ag": "grep",
           "ack": "grep", "find": "find", "bfs": "find", "fd": "fd", "fdfind": "fd", "tree": "tree",
           "ls": "ls", "sed": "sed", "awk": "awk", "gawk": "awk", "mawk": "awk", "jq": "jq"}
_READER_ALT = "|".join(sorted(READERS, key=len, reverse=True))
READER_RE = re.compile(r"(?:^|[\s;&|(`/])(?:" + _READER_ALT + r")(?=$|[\s;&|)])")
CUTTERS = {"head", "tail", "wc"}
WRAPPERS = {"command", "builtin", "exec", "nice", "time", "nohup", "stdbuf", "timeout"}
GREP_VALUE_OPTS = {"-e", "-f", "-m", "-A", "-B", "-C", "-d", "-D", "-g", "-t", "-T", "-j", "-M", "-E", "-r",
                   "--regexp", "--file", "--max-count", "--after-context", "--before-context", "--context",
                   "--glob", "--iglob", "--type", "--type-not", "--threads", "--max-columns", "--max-depth",
                   "--maxdepth", "--ignore-file", "--pre", "--sort", "--sortr", "--color", "--colors",
                   "--encoding", "--include", "--exclude", "--exclude-dir", "--replace", "--devices",
                   "--directories", "--max-filesize", "--path-separator"}
GREP_CHEAP = {"-l", "-L", "-c", "-q", "--files-with-matches", "--files-without-match", "--count", "--quiet",
              "--silent", "--count-matches"}
FD_VALUE_OPTS = {"-e", "-t", "-E", "-d", "-x", "-X", "-j", "-S", "-c", "--extension", "--type", "--exclude",
                 "--max-depth", "--min-depth", "--exec", "--exec-batch", "--threads", "--size", "--color",
                 "--changed-within", "--changed-before", "--owner", "--base-directory", "--search-path"}
TREE_VALUE_OPTS = {"-L", "-I", "-P", "-o", "-H", "-T", "--filelimit", "--charset", "--sort", "--timefmt",
                   "--gitfile", "--fromfile"}
# a heredoc body is data, not commands: replaced by its delimiter before tokenizing
HEREDOC_RE = re.compile(r"<<-?[ \t]*(['\"]?)([A-Za-z_]\w*)\1([^\n]*)\n.*?^\t*\2[ \t]*$", re.DOTALL | re.MULTILINE)
SEPARATORS = {"|", "|&", ";", "&&", "||", "&", "\n", "(", ")", ";;", ";&", "{", "}"}


def tokenize(cmd):
    lex = shlex.shlex(cmd, posix=True, punctuation_chars="();<>|&\n")
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    lex.commenters = ""
    return list(lex)


def pipelines(tokens):
    """[[segment, ...], ...]: segments are word lists with their redirections pulled out as
    (words, inputs, stdout_to_file)."""
    out, pipe, words, inputs, redirected = [], [], [], [], False
    i = 0

    def close_seg():
        nonlocal words, inputs, redirected
        pipe.append((words, inputs, redirected))
        words, inputs, redirected = [], [], False

    while i < len(tokens):
        t = tokens[i]
        if t in SEPARATORS:
            close_seg()
            if t not in ("|", "|&"):
                out.append(pipe[:])
                pipe.clear()
            i += 1
            continue
        if re.fullmatch(r"[<>&|]+", t) and ("<" in t or ">" in t):
            fd = words.pop() if words and words[-1].isdigit() else None
            target = tokens[i + 1] if i + 1 < len(tokens) else ""
            i += 2
            if t in ("<<", "<<<", "<<-"):
                continue
            if t == "<":
                inputs.append(target)
            elif ">" in t and fd in (None, "1") and not t.endswith("&") and target not in (
                    "/dev/stdout", "/dev/stderr", "/dev/tty"):
                redirected = True
            continue
        words.append(t)
        i += 1
    close_seg()
    out.append(pipe)
    return [[s for s in p if s[0] or s[1]] for p in out]


def strip_prefix(words):
    i = 0
    while i < len(words):
        w = words[i]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", w):
            i += 1
        elif os.path.basename(w) in WRAPPERS:
            i += 1
            while i < len(words) and (words[i].startswith("-") or re.fullmatch(r"[\d.]+[smhd]?", words[i])):
                i += 1
        elif os.path.basename(w) == "env":
            i += 1
            while i < len(words) and (words[i].startswith("-") or "=" in words[i]):
                i += 1
        else:
            break
    return words[i:]


def int_after(args, opts):
    for j, a in enumerate(args):
        for o in opts:
            if a == o and j + 1 < len(args):
                v = args[j + 1]
            elif a.startswith(o + "=") or (len(o) == 2 and a.startswith(o) and a[2:].isdigit()):
                v = a[len(o) + (1 if a.startswith(o + "=") else 0):]
            else:
                continue
            try:
                return int(v)
            except ValueError:
                return None
    return None


def reader_paths(kind, args):
    """(paths, recursive_default, cheap) for one reader command's arguments."""
    if kind in ("cat", "dump"):
        if kind == "dump" and any(a in ("-l", "-n", "-N", "-len") or re.fullmatch(r"-[lnN]\d+", a) for a in args):
            return [], False, True
        return [a for a in args if not a.startswith("-") or a == "-"], False, False
    if kind in ("grep", "rg"):
        pos, has_e, cheap, rec, j = [], False, False, kind == "rg", 0
        while j < len(args):
            a = args[j]
            if a == "--":
                pos += args[j + 1:]
                break
            if a.startswith("--"):
                name = a.split("=", 1)[0]
                cheap |= name in GREP_CHEAP
                rec |= name in ("--recursive", "--dereference-recursive", "--files")
                has_e |= name in ("--regexp", "--file")
                if name in GREP_VALUE_OPTS and "=" not in a:
                    j += 1
            elif a.startswith("-") and len(a) > 1:
                flags = a[1:]
                for k, ch in enumerate(flags):
                    opt = "-" + ch
                    if kind == "grep" and opt in ("-r", "-R"):
                        rec = True
                        continue
                    if opt in GREP_CHEAP:
                        cheap = True
                    if opt in ("-e", "-f"):
                        has_e = True
                    if opt in GREP_VALUE_OPTS and not (kind == "grep" and opt in ("-E", "-T")):
                        if k == len(flags) - 1:
                            j += 1
                        break
            else:
                pos.append(a)
            j += 1
        if not has_e and pos:
            pos = pos[1:]                # the pattern
        return pos, rec, cheap
    if kind == "find":
        paths = []
        for a in args:
            if a.startswith("-") or a in ("(", "!", "\\("):
                break
            paths.append(a)
        md = int_after(args, ("-maxdepth",))
        return paths or ["."], False, md is not None and md <= 2
    if kind == "fd":
        pos, j = [], 0
        while j < len(args):
            a = args[j]
            if a.startswith("-"):
                if a.split("=", 1)[0] in FD_VALUE_OPTS and "=" not in a:
                    j += 1
            else:
                pos.append(a)
            j += 1
        md = int_after(args, ("-d", "--max-depth"))
        return (pos[1:] or ["."]), False, md is not None and md <= 2
    if kind == "tree":
        md = int_after(args, ("-L",))
        pos, j = [], 0
        while j < len(args):
            if args[j] in TREE_VALUE_OPTS:
                j += 2
                continue
            if not args[j].startswith("-"):
                pos.append(args[j])
            j += 1
        return pos or ["."], False, md is not None and md <= 2
    if kind == "ls":
        rec = any(a == "--recursive" or (a.startswith("-") and not a.startswith("--") and "R" in a) for a in args)
        if not rec:
            return [], False, True
        return [a for a in args if not a.startswith("-")] or ["."], False, False
    if kind in ("sed", "awk", "jq"):
        if kind == "sed" and any(a.startswith("-") and not a.startswith("--") and ("n" in a or "i" in a)
                                 or a in ("--quiet", "--silent") or a.startswith("--in-place") for a in args):
            return [], False, True
        pos, has_prog, j = [], False, 0
        value_opts = {"sed": ("-e", "-f", "--expression", "--file"), "awk": ("-f", "-v", "-F"),
                      "jq": ("-f", "--from-file", "--arg", "--argjson", "--slurpfile", "--rawfile", "--indent")}
        while j < len(args):
            a = args[j]
            if a.startswith("-") and len(a) > 1:
                if a in value_opts[kind]:
                    has_prog |= a in ("-e", "-f", "--expression", "--file", "--from-file")
                    j += 2 if a not in ("--arg", "--argjson", "--slurpfile", "--rawfile") else 3
                    continue
                if kind == "jq" and a in ("-n", "--null-input"):
                    return [], False, True
            elif not (kind == "awk" and re.fullmatch(r"[A-Za-z_]\w*=.*", a)):
                pos.append(a)
            j += 1
        return (pos if has_prog else pos[1:]), False, False
    return [], False, True


def expand(word, cwd):
    """Absolute paths for one shell word: globs expanded (at most 50), $-words skipped."""
    if "$" in word or "`" in word:
        return []
    p = absolute(word, cwd)
    if re.search(r"[*?\[]", word):
        return sorted(glob.glob(p))[:50]
    return [p]


def check_bash(inp, cwd, knobs, atype, ctx):
    cmd = inp.get("command")
    if not isinstance(cmd, str) or not READER_RE.search(cmd):
        return None
    try:
        pipes = pipelines(tokenize(HEREDOC_RE.sub(lambda m: "<< " + m.group(2) + m.group(3), cmd)))
    except ValueError:
        return None                      # unbalanced quotes: Claude Code's shell will say so
    for pipe in pipes:
        for idx, (words, inputs, redirected) in enumerate(pipe):
            words = strip_prefix(words)
            if not words:
                continue
            name = os.path.basename(words[0])
            if name == "cd" and len(words) > 1 and "$" not in words[1]:
                cwd = absolute(words[1], cwd)
                continue
            kind = READERS.get(name)
            if not kind:
                continue
            if redirected:
                continue
            later = [strip_prefix(w) for w, _, _ in pipe[idx + 1:]]
            if any(w and (os.path.basename(w[0]) in CUTTERS
                          or READERS.get(os.path.basename(w[0])) in ("grep", "rg")) for w in later):
                continue                 # cut or filtered before it reaches the context
            if idx + 1 < len(pipe) and pipe[-1][2]:
                continue                 # the pipeline's output goes to a file
            paths, recursive, cheap = reader_paths(kind, words[1:])
            if cheap:
                continue
            if not paths and recursive:
                paths = ["."]
            if idx > 0 and not paths:
                continue                 # reads its stdin
            for word in list(paths) + inputs:
                if word == "-":
                    continue
                for p in expand(word, cwd):
                    if os.path.isdir(p) and (kind in ("cat", "dump", "sed", "awk", "jq")
                                             or (kind == "grep" and not recursive)):
                        continue         # a directory these readers skip (grep -n x *)
                    hit = gated(p, knobs, atype, ctx, is_file=not os.path.isdir(p))
                    if hit:
                        return hit
    return None


CHECKS = {"Read": check_read, "Grep": check_grep, "Glob": check_glob, "Bash": check_bash}
KEY_FIELDS = {"Read": ("file_path", "offset", "limit", "pages"), "Bash": ("command",)}


# ---------------------------------------------------------------- retry state

def state_file(ev):
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    sid = re.sub(r"[^A-Za-z0-9._-]", "_", str(ev.get("session_id") or "nosession"))[:128].strip(".") or "nosession"
    return os.path.join(base, "claude-agent-stack", sid, "read-gate.json")


def call_key(ev):
    tool = ev.get("tool_name")
    inp = ev.get("tool_input") or {}
    fields = KEY_FIELDS.get(tool)
    body = {k: inp.get(k) for k in fields} if fields else inp
    raw = json.dumps([ev.get("agent_id") or "main", tool, body], sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def seen_before(path, key, max_keys):
    """Record key; True when it was already recorded (the retry). Raises OSError/ValueError when the
    state cannot be kept, which the caller treats as a pass."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".lock", "a") as lk:
        fcntl.flock(lk.fileno(), fcntl.LOCK_EX)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                data = {}
        except FileNotFoundError:
            data = {}
        except ValueError:
            data = {}                    # a torn or foreign file starts over
        now = time.time()
        hit = key in data
        prev = data.get(key) if isinstance(data.get(key), list) else [now, 0]
        data[key] = [now, (prev[1] if len(prev) > 1 and isinstance(prev[1], int) else 0) + 1]
        if max_keys and len(data) > max_keys:
            def ts(k):
                v = data[k]
                return v[0] if isinstance(v, list) and v and isinstance(v[0], (int, float)) else 0
            for k in sorted(data, key=ts)[:len(data) - max_keys]:
                del data[k]
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".read-gate.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, separators=(",", ":"))
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return hit


# ---------------------------------------------------------------- decision

def reason(tool, cat, shown, knobs):
    what, alt = HINTS[cat]
    lim = knobs["READ_GATE_LIMIT"]
    tail = f" (or Read with limit <= {lim})" if tool == "Read" and lim else ""
    return (f"Read gate: {shown} is {what}, which costs many tokens and is rarely needed. Cheaper: {alt}{tail}. "
            "If you do need it, repeat this exact call once and it will pass. This is a token gate, "
            "not a failure to report.")


def classify(ev, knobs=None, ctx=None):
    """(category, shown path) when the call targets a gated path for this agent, else None. Pure
    apart from filesystem and git probes."""
    if not isinstance(ev, dict) or ev.get("hook_event_name", "PreToolUse") != "PreToolUse":
        return None
    check = CHECKS.get(ev.get("tool_name"))
    inp = ev.get("tool_input")
    if not check or not isinstance(inp, dict):
        return None
    knobs = knobs or read_knobs()
    if str(knobs.get("READ_GATE", "1")).strip().lower() in ("0", "off", "false", "no"):
        return None
    return check(inp, ev.get("cwd") or "", knobs, agent_type(ev), ctx or Ctx())


def decide(ev, knobs=None, remember=None):
    """The hook output for one PreToolUse event, or None to let the call through."""
    knobs = knobs or read_knobs()
    hit = classify(ev, knobs)
    if not hit:
        return None
    try:
        if remember is not None:
            again = remember(call_key(ev))
        else:
            again = seen_before(state_file(ev), call_key(ev), knobs["READ_GATE_MAX_KEYS"])
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"read_gate: no retry state ({exc}), call passes\n")
        return None
    if again:
        return None
    cat, shown = hit
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason(ev.get("tool_name"), cat, shown, knobs)}}


# ---------------------------------------------------------------- self-test

def self_test():
    import shutil
    k = {n: v[0] for n, v in KNOBS.items()}
    fails = []
    root = tempfile.mkdtemp(prefix="read-gate-test.")
    try:
        def mk(rel, data=b"x"):
            p = os.path.join(root, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(data)
            return p

        site = os.path.join(root, "site")
        mk("site/hugo.toml")
        mk("site/public/index.html")
        mk("site/content/post.md")
        mk("app/node_modules/x/index.js")
        mk("app/public/favicon.svg")         # Vite's public/: a source folder
        mk("app/src/main.ts")
        mk("app/data/big.csv", b"a,b\n" * 70000)
        mk("app/data/small.csv", b"a,b\n")
        mk("app/.claude-work/job/out.csv", b"a,b\n" * 70000)
        mk("app/model.safetensors")
        mk("app/clip.mov")
        mk("app/vendor.min.js")
        mk("proof/.lake/build/lib/A.olean")
        mk("proof/.lake/packages/mathlib/Mathlib/X.lean")
        mem = set()

        def remember(key):
            hit = key in mem
            mem.add(key)
            return hit

        def run(tool, inp, atype=None, aid="a1", cwd=root, knobs=None):
            ev = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": inp, "cwd": cwd,
                  "session_id": "s", "agent_id": aid}
            if atype:
                ev["agent_type"] = atype
            out = decide(ev, knobs or k, remember)
            return (out or {}).get("hookSpecificOutput", {}).get("permissionDecision")

        def check(name, cond):
            if not cond:
                fails.append(name)

        hugo = os.path.join(site, "public", "index.html")
        check("hugo public refused", run("Read", {"file_path": hugo}) == "deny")
        check("identical retry passes", run("Read", {"file_path": hugo}) is None)
        check("other agent refused", run("Read", {"file_path": hugo}, aid="a2") == "deny")
        check("verifier exempt", run("Read", {"file_path": hugo}, "verifier", aid="a3") is None)
        check("copy type exempt", run("Read", {"file_path": hugo}, "verifier-copy", aid="a4") is None)
        check("small limit passes", run("Read", {"file_path": hugo, "limit": 50}, aid="a5") is None)
        check("hugo source passes", run("Read", {"file_path": os.path.join(site, "content/post.md")}) is None)
        check("vite public passes", run("Read", {"file_path": os.path.join(root, "app/public/favicon.svg")}) is None)
        check("node_modules", run("Read", {"file_path": "node_modules/x/index.js"},
                                  cwd=os.path.join(root, "app")) == "deny")
        check("big csv", run("Read", {"file_path": os.path.join(root, "app/data/big.csv")}) == "deny")
        check("big csv data agent", run("Read", {"file_path": os.path.join(root, "app/data/big.csv")},
                                        "data-scientist", aid="d") is None)
        check("small csv passes", run("Read", {"file_path": os.path.join(root, "app/data/small.csv")}) is None)
        check(".claude-work never", run("Read", {"file_path": os.path.join(root, "app/.claude-work/job/out.csv")})
              is None)
        check("weights", run("Read", {"file_path": os.path.join(root, "app/model.safetensors")}) == "deny")
        check("video designer", run("Read", {"file_path": os.path.join(root, "app/clip.mov")}, "designer",
                                    aid="g") is None)
        check("minified", run("Read", {"file_path": os.path.join(root, "app/vendor.min.js")}) == "deny")
        check("lake build", run("Read", {"file_path": os.path.join(root, "proof/.lake/build/lib/A.olean")})
              == "deny")
        check("lake packages", run("Read", {"file_path": os.path.join(
            root, "proof/.lake/packages/mathlib/Mathlib/X.lean")}) is None)
        check("grep tool dir", run("Grep", {"pattern": "x", "path": os.path.join(root, "app/node_modules"),
                                            "output_mode": "content"})
              == "deny")
        check("grep tool count", run("Grep", {"pattern": "x", "path": os.path.join(root, "app/node_modules"),
                                              "output_mode": "count"}) is None)
        check("glob pattern", run("Glob", {"pattern": "**/node_modules/**/*.js"}) == "deny")
        check("glob src", run("Glob", {"pattern": "src/**/*.ts"}, cwd=os.path.join(root, "app")) is None)
        b = os.path.join(root, "app")
        check("bash grep", run("Bash", {"command": "grep -rn foo node_modules/"}, cwd=b) == "deny")
        check("bash grep -l", run("Bash", {"command": "grep -rl foo node_modules/"}, cwd=b) is None)
        check("bash rg | head", run("Bash", {"command": "rg foo node_modules | head -20"}, cwd=b) is None)
        check("bash cat csv", run("Bash", {"command": "cd data && cat big.csv"}, cwd=b) == "deny")
        check("bash head csv", run("Bash", {"command": "head -n 5 data/big.csv"}, cwd=b) is None)
        check("bash find", run("Bash", {"command": "find node_modules -name '*.js'"}, cwd=b) == "deny")
        check("bash find src", run("Bash", {"command": "find src -name '*.ts'"}, cwd=b) is None)
        check("bash redirect", run("Bash", {"command": "cat data/big.csv > /dev/null"}, cwd=b) is None)
        check("bash git", run("Bash", {"command": "git status"}, cwd=b) is None)
        check("gate off", run("Read", {"file_path": hugo}, aid="z", knobs=dict(k, READ_GATE="0")) is None)
        check("other tool", run("Edit", {"file_path": hugo}, aid="z") is None)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    if fails:
        print("read_gate self-test FAILED: " + ", ".join(fails))
        return 1
    print("read_gate self-test ok")
    return 0


def main(argv):
    if "--self-test" in argv:
        return self_test()
    if "--print" in argv:
        for name, val in read_knobs().items():
            print(f"{name}={val}  # {KNOBS[name][1]}")
        return 0
    try:
        out = decide(json.loads(sys.stdin.read() or "{}"))
    except Exception as exc:  # noqa: BLE001 - fail open: a token gate never blocks over its own bug
        sys.stderr.write(f"read_gate: not applied ({type(exc).__name__}: {exc})\n")
        return 0
    if out:
        sys.stdout.write(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
