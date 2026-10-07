"""toolsmith_policy - the rules of the stack's dependency installer, shared by its executor
(bin/stack-install) and the guard (agent_guard.py no-push mode), so both judge one argv the same way.

Pure and stdlib-only (Python 3.8+): no network, no subprocess, no file writes. What is here:
  - the executor's argv grammar (parse): subcommands, installers, package specs, options;
  - the installers' argv (install_argv, uninstall_argv) and environment (installer_env), with every
    hardening flag fixed here, never supplied by the agent;
  - the vetting verdicts (vet_brew, vet_pypi, vet_npm, vet_cargo, vet_go) over registry metadata the
    executor fetched;
  - the state layout (state_dir, ticket_name), the ledger fold and safe program resolution.

Installers driven without asking (the user's decision, 2026-10-06): Homebrew formulae, uv tools
(Python only through uv), npm and pnpm global packages, cargo install, go install. Anything else is a
`request` the user approves on a terminal; pip is refused outright.
"""
import hashlib
import json
import os
import re
import time

SCHEMA = 1
INSTALLERS = ("brew", "uv", "npm", "pnpm", "cargo", "go")
# subcommands an agent (toolsmith, through the guard) may run; the user's own on a terminal
READ_SUBS = ("help", "status", "list", "pending", "manifest", "show", "vet")
AGENT_SUBS = READ_SUBS + ("install", "upgrade", "uninstall", "request", "run")
USER_SUBS = READ_SUBS + ("approve", "deny")
HELP_ALIASES = ("-h", "--help")

TICKET_TTL_S = 120            # the guard's ticket for one call: consumed by the executor within this
APPROVAL_TTL_S = 86400        # a user approval: used once within this
MIN_AGE_DAYS = 7              # default of STACK_TOOLSMITH_MIN_AGE_DAYS: a version this old at least
PROJECT_MIN_AGE_DAYS = 90     # a package (project, crate) first published at least this long ago
NPM_MIN_WEEKLY = 1000         # api.npmjs.org last-week downloads
CRATES_MIN_RECENT = 10000     # crates.io recent_downloads (90 days)
BREW_MIN_INSTALLS = 1000      # formulae.brew.sh 365-day installs on request

PYPI_INDEX = "https://pypi.org/simple"
NPM_REGISTRY = "https://registry.npmjs.org/"
GO_PROXY = "https://proxy.golang.org"
GO_SUMDB = "sum.golang.org"

# ---------------------------------------------------------------- field grammar
SEMVER = r"\d{1,9}\.\d{1,9}\.\d{1,9}(?:-[0-9A-Za-z][0-9A-Za-z.-]{0,63})?(?:\+[0-9A-Za-z][0-9A-Za-z.-]{0,63})?"
PEP440 = r"(?:\d{1,4}!)?\d{1,9}(?:\.\d{1,9}){0,5}(?:(?:a|b|rc)\d{1,9})?(?:\.post\d{1,9})?(?:\.dev\d{1,9})?"
BREW_NAME = r"[a-z0-9][a-z0-9+_.@-]{0,99}"
PY_NAME = r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9])?"
NPM_NAME = r"(?:@[a-z0-9][a-z0-9._-]{0,99}/)?[A-Za-z0-9][A-Za-z0-9._-]{0,99}"
CRATE_NAME = r"[A-Za-z][A-Za-z0-9_-]{0,63}"
_GO_ELEM = r"[A-Za-z0-9_~+-](?:[A-Za-z0-9._~+-]{0,126}[A-Za-z0-9_~+-])?"
GO_PATH = r"[a-z0-9](?:[a-z0-9-]{0,62}\.)+[a-z]{2,24}(?:/%s){1,16}" % _GO_ELEM
NAME_RE = {"brew": re.compile(BREW_NAME + r"\Z"), "uv": re.compile(PY_NAME + r"\Z"),
           "npm": re.compile(NPM_NAME + r"\Z"), "pnpm": re.compile(NPM_NAME + r"\Z"),
           "cargo": re.compile(CRATE_NAME + r"\Z"), "go": re.compile(GO_PATH + r"\Z")}
SPEC_RE = {"uv": re.compile(r"(%s)==(%s)\Z" % (PY_NAME, PEP440)),
           "npm": re.compile(r"(%s)@(%s)\Z" % (NPM_NAME, SEMVER)),
           "pnpm": re.compile(r"(%s)@(%s)\Z" % (NPM_NAME, SEMVER)),
           "cargo": re.compile(r"(%s)@(%s)\Z" % (CRATE_NAME, SEMVER)),
           "go": re.compile(r"(%s)@(v%s)\Z" % (GO_PATH, SEMVER))}
SPEC_HINT = {"brew": "<formula> (homebrew/core; Homebrew installs its current stable version)",
             "uv": "<name>==<version>", "npm": "<name>@<x.y.z>", "pnpm": "<name>@<x.y.z>",
             "cargo": "<crate>@<x.y.z>", "go": "<module/path>@v<x.y.z>"}
WHY_RE = re.compile(r"[A-Za-z0-9 .,:/_@+='%-]{3,200}\Z")
FOR_RE = re.compile(r"[a-z][a-z0-9-]{1,40}\Z")
ID_RE = re.compile(r"(?:ts|rq)-[0-9a-f]{12}\Z")
RQ_RE = re.compile(r"rq-[0-9a-f]{12}\Z")
PYVER_RE = re.compile(r"3\.\d{1,2}(?:\.\d{1,2})?\Z")
FEATURES_RE = re.compile(r"[A-Za-z0-9_,/-]{1,200}\Z")
# a requested command's words: plain tokens, no spaces, quotes or shell syntax
REQ_WORD_RE = re.compile(r"[A-Za-z0-9@%+=:,./_^-]{1,200}\Z")
REQ_PROG_RE = re.compile(r"(?:/[A-Za-z0-9._+-]+)+\Z|[A-Za-z0-9][A-Za-z0-9._+-]{0,63}\Z")
REQ_MAX_WORDS = 32
# programs a request may never name, even with the user's approval: privilege, shells and code
# runners (a request runs argv, never a shell), downloaders (no curl | sh), pip (Python only through
# uv), and file tools (a request installs software, it does not edit the machine)
DENIED_PROGRAMS = frozenset("""
sudo doas su pkexec runuser login sh bash zsh dash ksh mksh fish csh tcsh rbash pwsh powershell env
eval exec xargs nohup time timeout gtimeout nice script expect watch screen tmux parallel osascript
open launchctl defaults security curl wget nc ncat netcat socat telnet ssh scp sftp rsync ftp
python python2 python3 pypy pypy3 node nodejs deno bun ruby perl php lua luajit julia Rscript R
java dotnet pip pip2 pip3 pipenv easy_install rm rmdir mv cp dd ln tee chmod chown chflags install
mkdir touch truncate shred ditto tar unzip
""".split())
# options per installer: name -> value regex (None: a flag)
OPTS = {"uv": {"--python": PYVER_RE, "--allow-build": None},
        "npm": {"--allow-scripts": None}, "pnpm": {"--allow-scripts": None},
        "cargo": {"--bin": re.compile(CRATE_NAME + r"\Z"), "--features": FEATURES_RE,
                  "--no-default-features": None},
        "brew": {}, "go": {}}
RELAXERS = ("--allow-scripts", "--allow-build")      # always a request for the user


class PolicyError(ValueError):
    """An argv the installer refuses; str() is the reason."""


def _take_common(rest, need_why):
    """Split --why / --for out of rest; return (why, for, remaining)."""
    why = req = None
    out, k = [], 0
    while k < len(rest):
        w = rest[k]
        if w in ("--why", "--for"):
            if k + 1 >= len(rest):
                raise PolicyError("%s needs a value" % w)
            v = rest[k + 1]
            if w == "--why":
                if why is not None or not WHY_RE.match(v):
                    raise PolicyError("--why: one plain sentence, 3-200 characters of letters, "
                                      "digits, spaces and . , : / _ @ + = ' % -")
                why = v
            else:
                if req is not None or not FOR_RE.match(v):
                    raise PolicyError("--for: the agent type the install is for (e.g. coder)")
                req = v
            k += 2
            continue
        out.append(w)
        k += 1
    if need_why and why is None:
        raise PolicyError("--why \"<reason>\" is required: it goes to the ledger")
    return why, req, out


def _spec(installer, spec, need_version):
    """(name, version or None) of a package spec; raises PolicyError."""
    if installer == "brew":
        if "/" in spec or not NAME_RE["brew"].match(spec):
            raise PolicyError("brew: %s; taps, paths and URLs are refused" % SPEC_HINT["brew"])
        return spec, None
    m = SPEC_RE[installer].match(spec)
    if m:
        return m.group(1), m.group(2)
    if not need_version and NAME_RE[installer].match(spec):
        return spec, None
    raise PolicyError("%s: the spec must be %s, pinned (no ranges, tags, latest, URLs, git, paths "
                      "or local files)" % (installer, SPEC_HINT[installer]))


def _opts(installer, words):
    allowed, opts, relax = OPTS[installer], {}, []
    k = 0
    while k < len(words):
        w = words[k]
        if w not in allowed:
            raise PolicyError("%s: unknown or refused argument %r (allowed: %s)"
                              % (installer, w[:40], ", ".join(sorted(allowed)) or "none"))
        rx = allowed[w]
        if rx is None:
            opts[w] = True
            if w in RELAXERS:
                relax.append(w)
            k += 1
            continue
        if k + 1 >= len(words) or not rx.match(words[k + 1]) or w in opts:
            raise PolicyError("%s: %s needs one valid value" % (installer, w))
        opts[w] = words[k + 1]
        k += 2
    return opts, relax


def parse(args, user=False):
    """The executor's argv (without the program) as a dict, or PolicyError. `user`: the user on a
    terminal (approve/deny; nothing that installs)."""
    if not isinstance(args, (list, tuple)) or not all(isinstance(a, str) for a in args):
        raise PolicyError("argv must be a list of strings")
    if not args or args[0] in HELP_ALIASES:
        args = ["help"] + list(args[1:])
    sub, rest = args[0], list(args[1:])
    allowed = USER_SUBS if user else AGENT_SUBS
    if sub not in allowed:
        if sub in USER_SUBS:
            raise PolicyError("`%s` is the user's own step, on a terminal" % sub)
        if sub in AGENT_SUBS:
            raise PolicyError("`%s` is run by the toolsmith agent, not on a terminal" % sub)
        raise PolicyError("unknown subcommand %r: %s" % (sub[:40], ", ".join(allowed)))
    p = {"sub": sub, "args": [sub] + rest}
    if sub in ("help", "status", "pending", "manifest"):
        if rest:
            raise PolicyError("`%s` takes no arguments" % sub)
        return p
    if sub == "list":
        if rest not in ([], ["--all"]):
            raise PolicyError("usage: list [--all]")
        p["all"] = bool(rest)
        return p
    if sub in ("show", "run", "approve", "deny"):
        rx = ID_RE if sub == "show" else RQ_RE
        if len(rest) != 1 or not rx.match(rest[0]):
            raise PolicyError("usage: %s <%s>" % (sub, "id" if sub == "show" else "rq-id"))
        p["id"] = rest[0]
        return p
    if sub == "request":
        if "--" not in rest:
            raise PolicyError("usage: request --why \"<reason>\" [--for <agent>] -- <program> <args>")
        cut = rest.index("--")
        why, req, left = _take_common(rest[:cut], True)
        if left:
            raise PolicyError("request: unexpected %r before --" % left[0][:40])
        p.update(why=why, req_for=req, command=check_request_command(rest[cut + 1:]))
        return p
    # vet, install, upgrade, uninstall: <installer> <spec> [options]
    why, req, left = _take_common(rest, sub in ("install", "upgrade", "uninstall"))
    if sub == "vet" and (why or req):
        raise PolicyError("vet takes no --why/--for")
    if len(left) < 2 or left[0] not in INSTALLERS:
        raise PolicyError("usage: %s <%s> <spec>" % (sub, "|".join(INSTALLERS)))
    inst = left[0]
    if sub == "uninstall":
        if len(left) != 2 or not NAME_RE[inst].match(left[1]) or (inst == "brew" and "/" in left[1]):
            raise PolicyError("usage: uninstall %s <name> --why \"<reason>\"" % inst)
        name, version, opts, relax = left[1], None, {}, []
    else:
        name, version = _spec(inst, left[1], need_version=sub in ("install", "upgrade"))
        opts, relax = _opts(inst, left[2:])
        if sub == "vet" and relax:
            raise PolicyError("vet takes no %s" % relax[0])
    if inst == "uv":
        name = py_normalize(name)             # what uv, PyPI and the ledger call it (PEP 503)
    p.update(installer=inst, name=name, version=version, opts=opts, relax=relax, why=why,
             req_for=req)
    return p


def py_normalize(name):
    return re.sub(r"[-_.]+", "-", name).lower()


# installers a request may name (any other installer, with the user's approval); the rest of the
# argv may not name pip, a Python interpreter or, by path, a refused program (`arch /bin/sh -c id`)
REQUEST_PROGRAMS = frozenset("""
brew gem pipx mas port rustup cargo go npm pnpm yarn bun deno uv conda mamba micromamba pixi opam ghcup
cabal stack juliaup elan composer luarocks cpanm dotnet sdkmanager gcloud
""".split())


def check_request_command(words):
    """A requested command (any other installer): argv words, refused programs and syntax."""
    if not words:
        raise PolicyError("request: no command after --")
    if len(words) > REQ_MAX_WORDS:
        raise PolicyError("request: at most %d words" % REQ_MAX_WORDS)
    prog = words[0]
    if not REQ_PROG_RE.match(prog) or ".." in prog.split("/"):
        raise PolicyError("request: the program must be a plain name or an absolute path")
    base = prog.rsplit("/", 1)[-1]
    if base in DENIED_PROGRAMS or re.match(r"(?:python|pip|pypy)[\d.]*\Z", base):
        raise PolicyError("request: `%s` is never run by the installer (privilege, shells, code "
                          "runners, downloaders, pip and file tools are refused even with "
                          "approval; Python goes through uv)" % base)
    if base not in REQUEST_PROGRAMS:
        raise PolicyError("request: `%s` is not an installer this executor runs (%s); the user can "
                          "run it themselves" % (base, ", ".join(sorted(REQUEST_PROGRAMS))))
    for w in words[1:]:
        if not REQ_WORD_RE.match(w):
            raise PolicyError("request: argument %r is not a plain token" % w[:40])
        wbase = w.rsplit("/", 1)[-1]
        if w.lower() in ("sudo", "doas") or re.match(r"(?:python|pip|pypy)[\d.]*\Z", wbase) or \
                ("/" in w and wbase in DENIED_PROGRAMS):
            raise PolicyError("request: argument %r names a refused program (sudo, pip, Python, a "
                              "shell or tool by path)" % w[:40])
    return list(words)


# ---------------------------------------------------------------- installer argv and environment
def iso_utc(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def min_age_days(environ):
    raw = (environ.get("STACK_TOOLSMITH_MIN_AGE_DAYS") or "").strip()
    return int(raw) if raw.isdigit() and int(raw) <= 365 else MIN_AGE_DAYS


def go_binary(path):
    """The binary `go install path@v` writes: the last element, or the one before a /vN suffix."""
    elems = path.split("/")
    if len(elems) > 2 and re.match(r"v\d+\Z", elems[-1]):
        return elems[-2]
    return elems[-1]


def install_argv(p, prog, now, age_days, npm_extra=()):
    """The installer argv for an install/upgrade dict `p` (parse), run by absolute path `prog`.
    Every hardening flag is here; the agent supplies only the spec and the allowed options."""
    inst, name, ver, opts = p["installer"], p["name"], p["version"], p["opts"]
    before = iso_utc(now - age_days * 86400)
    scripts = "--allow-scripts" in opts
    if inst == "brew":
        verb = "upgrade" if p["sub"] == "upgrade" else "install"
        return [prog, verb, "--formula", name]
    if inst == "uv":
        argv = [prog, "tool", "install", "--no-config", "--no-sources", "--default-index", PYPI_INDEX]
        if "--allow-build" not in opts:
            argv.append("--no-build")
        if age_days:
            argv += ["--exclude-newer", before]
        if p["sub"] == "upgrade":
            argv.append("--reinstall")
        if opts.get("--python"):
            argv += ["--python", opts["--python"]]
        return argv + ["%s==%s" % (name, ver)]
    if inst == "npm":
        argv = [prog, "install", "--global", "--registry=" + NPM_REGISTRY, "--no-audit", "--no-fund"]
        if not scripts:
            argv.append("--ignore-scripts")
        if age_days:
            argv.append("--before=" + before)
        return argv + list(npm_extra) + ["%s@%s" % (name, ver)]
    if inst == "pnpm":
        argv = [prog, "add", "--global", "--registry=" + NPM_REGISTRY]
        if not scripts:
            argv.append("--ignore-scripts")
        return argv + ["%s@%s" % (name, ver)]
    if inst == "cargo":
        argv = [prog, "install", "--locked"]
        if opts.get("--bin"):
            argv += ["--bin", opts["--bin"]]
        if opts.get("--features"):
            argv += ["--features", opts["--features"]]
        if opts.get("--no-default-features"):
            argv.append("--no-default-features")
        if p["sub"] == "upgrade":
            argv.append("--force")           # the ledger owns the old version; replace it
        return argv + ["%s@%s" % (name, ver)]
    if inst == "go":
        return [prog, "install", "%s@%s" % (name, ver)]
    raise PolicyError("unknown installer %r" % inst)


def uninstall_argv(installer, name, binary_path=None):
    """The uninstall command recorded in the ledger (bare program name; the executor resolves it).
    go has none: the binary is removed (`rm <path>`, done by the executor itself)."""
    if installer == "brew":
        return ["brew", "uninstall", "--formula", name]
    if installer == "uv":
        return ["uv", "tool", "uninstall", name]
    if installer == "npm":
        return ["npm", "uninstall", "--global", name]
    if installer == "pnpm":
        return ["pnpm", "remove", "--global", name]
    if installer == "cargo":
        return ["cargo", "uninstall", name]
    if installer == "go":
        return ["rm", binary_path] if binary_path else None
    return None


def request_package(command):
    """(ledger label, package, uninstall argv) when an approved request is a known install: a brew
    cask, a gem or a pipx package; else None (the ledger records it as a run)."""
    base = command[0].rsplit("/", 1)[-1]
    rest = command[1:]
    names = [w for w in rest[1:] if not w.startswith("-")]
    if base == "brew" and rest[:1] == ["install"] and "--cask" in rest and len(names) == 1:
        return ("brew-cask", names[0], ["brew", "uninstall", "--cask", names[0]])
    if base == "gem" and rest[:1] == ["install"]:
        gems = [w for w in names if not re.match(r"[\d.]+\Z", w)]
        if len(gems) == 1:
            return ("gem", gems[0], ["gem", "uninstall", gems[0]])
    if base == "pipx" and rest[:1] == ["install"] and len(names) == 1:
        pkg = re.split(r"[=<>!~\[]", names[0])[0]
        return ("pipx", pkg, ["pipx", "uninstall", pkg])
    return None


# Environment: an allowlist, never the sandbox's cache variables, tokens or installer config the
# Bash environment carries (session-env exports, HOMEBREW_*, npm_config_*, UV_*, CARGO_*, GO*, PIP_*)
ENV_KEEP = ("HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "LC_MESSAGES", "TERM", "SHELL",
            "TZ", "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS")
INSTALLER_ENV = {
    "brew": {"HOMEBREW_NO_AUTO_UPDATE": "1", "HOMEBREW_NO_ANALYTICS": "1", "HOMEBREW_NO_ENV_HINTS": "1",
             "HOMEBREW_NO_INSTALL_UPGRADE": "1", "HOMEBREW_NO_INSTALL_CLEANUP": "1",
             "HOMEBREW_NO_COLOR": "1"},
    "uv": {"UV_NO_CONFIG": "1", "UV_NO_PROGRESS": "1"},
    "npm": {"npm_config_registry": NPM_REGISTRY, "npm_config_audit": "false", "npm_config_fund": "false",
            "npm_config_update_notifier": "false", "npm_config_color": "false"},
    # pnpm 12 reads PNPM_CONFIG_*, not npm_config_* (probed: `PNPM_CONFIG_REGISTRY=x pnpm config get
    # registry` prints x, `npm_config_minimum_release_age=1 ...` prints undefined; pnpm 12.8.1)
    "pnpm": {"PNPM_CONFIG_REGISTRY": NPM_REGISTRY, "PNPM_CONFIG_UPDATE_NOTIFIER": "false"},
    "cargo": {"CARGO_TERM_COLOR": "never", "CARGO_TERM_PROGRESS_WHEN": "never"},
    "go": {"GOPROXY": GO_PROXY, "GOSUMDB": GO_SUMDB, "GOFLAGS": "", "GONOSUMDB": "", "GONOSUMCHECK": "",
           "GONOPROXY": "", "GOPRIVATE": "", "GOINSECURE": "", "GOTOOLCHAIN": "local", "GOWORK": "off",
           "GO111MODULE": "on", "GOENV": "off"},     # GOENV=off: an empty variable falls back to the env file
}
# per installer: user variables that locate its own install (not code it loads from the project)
ENV_KEEP_BY = {"pnpm": ("PNPM_HOME",)}


def installer_env(environ, installer, path_dirs, tmpdir, allow_scripts=False, age_days=0):
    """The installer's whole environment: ENV_KEEP from `environ`, a fixed PATH, a private TMPDIR
    and the installer's hardening variables; npm/pnpm never run install scripts unless the user
    approved them (allow_scripts); pnpm resolves no dependency younger than age_days (npm and uv
    get --before / --exclude-newer instead)."""
    env = {k: environ[k] for k in ENV_KEEP if environ.get(k)}
    for k in ENV_KEEP_BY.get(installer, ()):
        if environ.get(k):
            env[k] = environ[k]
    env["PATH"] = os.pathsep.join(path_dirs)
    env["TMPDIR"] = tmpdir
    env.update(INSTALLER_ENV.get(installer, {}))
    if installer == "npm":
        env["npm_config_ignore_scripts"] = "false" if allow_scripts else "true"
    if installer == "pnpm":
        env["PNPM_CONFIG_IGNORE_SCRIPTS"] = "false" if allow_scripts else "true"
        if age_days:
            env["PNPM_CONFIG_MINIMUM_RELEASE_AGE"] = str(int(age_days) * 1440)    # minutes, strict
    return env


# ---------------------------------------------------------------- programs: never from writable roots
SYSTEM_DIRS = ("/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin", "/usr/bin", "/bin",
               "/usr/sbin", "/sbin")


def unsafe_roots(environ, cwd):
    """Directories a sandboxed agent can write: a program found there is never run."""
    home = environ.get("HOME") or os.path.expanduser("~")
    roots = [cwd, "/tmp", "/private/tmp", "/var/folders", "/private/var/folders",
             os.path.join(home, ".cache", "claude-sandbox")]
    for k in ("TMPDIR", "CLAUDE_PROJECT_DIR", "CLAUDE_CODE_TMPDIR"):
        if environ.get(k):
            roots.append(environ[k])
    return [os.path.realpath(r) for r in roots if r and os.path.isabs(r)]


def _under(path, roots):
    return any(path == r or path.startswith(r.rstrip("/") + "/") for r in roots)


INSTALLER_PACKAGES = ("npm", "pnpm", "corepack", "yarn")
TOOL_HOME_RE = re.compile(r"/\.local/share/uv/tools/|/lib/node_modules/(?!(?:%s)/)" % "|".join(INSTALLER_PACKAGES))


def resolve_program(name, environ, cwd, extra_dirs=()):
    """Absolute path of program `name`: the first executable on PATH (absolute entries only) or in
    extra_dirs whose real path lies outside every unsafe root and is not a program some package
    installed (a uv tool's or an npm package's own bin: a package named its script `brew`); None if
    there is none."""
    bad = unsafe_roots(environ, cwd)
    dirs = [d for d in (environ.get("PATH") or "").split(os.pathsep) if os.path.isabs(d)]
    dirs += [d for d in list(extra_dirs) + list(SYSTEM_DIRS) if d not in dirs]
    for d in dirs:
        cand = os.path.join(d, name)
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            real = os.path.realpath(cand)
            if not _under(real, bad) and not _under(os.path.realpath(d), bad) and \
                    not TOOL_HOME_RE.search(real):
                return cand
    return None


def safe_path_dirs(prog, environ, cwd):
    """PATH for an installer: its own directory, then the system ones, none of them writable by an
    agent."""
    bad = unsafe_roots(environ, cwd)
    home = environ.get("HOME") or os.path.expanduser("~")
    out = []
    for d in [os.path.dirname(prog)] + list(SYSTEM_DIRS) + [os.path.join(home, ".cargo", "bin"),
                                                             "/usr/local/go/bin"]:
        if d and os.path.isdir(d) and d not in out and not _under(os.path.realpath(d), bad):
            out.append(d)
    return out


# ---------------------------------------------------------------- state
def state_root(environ):
    base = environ.get("XDG_STATE_HOME") or os.path.join(environ.get("HOME") or os.path.expanduser("~"),
                                                         ".local", "state")
    return os.path.join(base, "claude-agent-stack")


def state_dir(environ):
    return os.path.join(state_root(environ), "toolsmith")


def ticket_name(args):
    """The guard's ticket for one executor argv: sha256 of its canonical JSON."""
    blob = json.dumps(list(args), separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest() + ".json"


def fold(events):
    """Active packages from ledger events, in order: (installer, package) -> the last `installed`
    event, dropped by a later `removed`."""
    active = {}
    for e in events:
        if not isinstance(e, dict) or e.get("v") != SCHEMA:
            continue
        key = (e.get("installer"), e.get("package"))
        if e.get("event") == "installed":
            active[key] = e
        elif e.get("event") == "removed":
            active.pop(key, None)
    return active


# ---------------------------------------------------------------- vetting (pure verdicts)
def parse_time(s):
    """Epoch seconds of an RFC 3339 / ISO 8601 UTC stamp (registry formats), else None."""
    if not isinstance(s, str):
        return None
    m = re.match(r"(\d{4})-(\d\d)-(\d\d)[T ](\d\d):(\d\d):(\d\d)(?:\.\d+)?(Z|[+-]00:?00)?\Z", s.strip())
    if not m:
        return None
    import calendar
    y, mo, d, h, mi, se = (int(x) for x in m.groups()[:6])
    try:
        return calendar.timegm((y, mo, d, h, mi, se, 0, 0, 0))
    except (ValueError, OverflowError):
        return None


# C0/C1 controls, bidi and zero-width characters: registry text (a deprecation note, a version) is
# shown on the user's approval screen, where an escape sequence could repaint it
_CONTROL_RE = re.compile("[\x00-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff]")


def clean_text(value, limit=300):
    return _CONTROL_RE.sub("?", str(value))[:limit]


# programs a package may not put on PATH without the user: the installers and the commands the
# stack, the hooks and the user run unsandboxed (a uv tool's `brew` script would run on the next
# `stack-install install brew ...`)
RESERVED_BINS = frozenset(INSTALLERS + (
    "uvx", "npx", "pnpx", "corepack", "node", "nodejs", "rustup", "rustc", "git", "ssh", "scp", "sudo",
    "su", "doas", "login", "sh", "bash", "zsh", "dash", "fish", "env", "python", "python3", "pip", "pip3",
    "claude", "gh", "curl", "wget", "security", "open", "osascript", "make", "cc", "clang", "gcc", "ld",
    "xcrun", "ls", "cat", "rm", "cp", "mv", "ln", "chmod", "install", "launchctl", "defaults", "codesign",
    "stack-install", "awk", "sed", "grep", "find", "xargs", "tar"))
BIN_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,99}\Z")


def check_bins(report, names):
    """The executables a package puts on PATH: a path-like name is refused, a reserved one asks."""
    names = [str(n) for n in names]
    bad = [n for n in names if not BIN_NAME_RE.match(n) or ".." in n]
    report.check("bin-names", not bad, "unsafe executable names: %s" % ", ".join(bad) if bad
                 else "executables: %s" % (", ".join(names) or "none"), hard=True)
    if not bad:
        res = sorted(n for n in names if n in RESERVED_BINS)
        report.check("bin-reserved", not res, "would put %s on PATH (reserved: installers and system "
                     "commands)" % ", ".join(res) if res else "no reserved name")
    report.info["bins"] = names


class Report(object):
    """A vetting result: hard checks refuse, soft checks ask the user, `surfaced` is shown."""

    def __init__(self, installer, name, version=None):
        self.installer, self.name, self.version = installer, name, version
        self.checks, self.surfaced, self.info = [], [], {}

    def check(self, name, ok, detail, hard=False):
        self.checks.append({"check": name, "ok": bool(ok), "hard": bool(hard), "detail": clean_text(detail)})

    def surface(self, text):
        self.surfaced.append(clean_text(text))

    @property
    def verdict(self):
        if any(not c["ok"] and c["hard"] for c in self.checks):
            return "refuse"
        if any(not c["ok"] for c in self.checks):
            return "ask"
        return "pass"

    def failed(self, hard=None):
        return [c["check"] for c in self.checks if not c["ok"] and (hard is None or c["hard"] == hard)]

    def as_dict(self):
        return {"installer": self.installer, "package": self.name, "version": self.version,
                "verdict": self.verdict, "checks": self.checks, "surfaced": self.surfaced,
                "info": self.info}


def _age(report, label, stamp, now, days):
    t = parse_time(stamp)
    if t is None:
        report.check(label, False, "no publish time in the registry metadata")
        return
    age = (now - t) / 86400.0
    report.check(label, age >= days, "%.1f days (minimum %d)" % (age, days))


def vet_brew(meta, name, now):
    r = Report("brew", name)
    if not isinstance(meta, dict) or meta.get("name") != name:
        r.check("exists", False, "no formula %r in homebrew/core (formulae.brew.sh)" % name, hard=True)
        return r
    r.version = ((meta.get("versions") or {}).get("stable"))
    r.check("exists", bool(r.version), "stable %s" % r.version, hard=True)
    r.check("tap", meta.get("tap") == "homebrew/core", "tap %s" % meta.get("tap"), hard=True)
    r.check("disabled", not meta.get("disabled"), "disabled" if meta.get("disabled") else "no",
            hard=True)
    r.check("deprecated", not meta.get("deprecated"),
            "deprecated" if meta.get("deprecated") else "no")
    inst = ((meta.get("analytics") or {}).get("install_on_request") or {}).get("365d") or {}
    n = inst.get(name) if isinstance(inst, dict) else None
    r.check("popularity", isinstance(n, int) and n >= BREW_MIN_INSTALLS,
            "%s installs on request in 365 days (minimum %d)" % (n, BREW_MIN_INSTALLS))
    if meta.get("post_install_defined"):
        r.surface("the formula runs a post_install step (homebrew/core code)")
    if meta.get("caveats"):
        r.surface("the formula has caveats: see `brew info %s`" % name)
    deps = meta.get("dependencies") or []
    r.info.update(source="homebrew/core", dependencies=len(deps) if isinstance(deps, list) else None)
    return r


def vet_pypi(vmeta, pmeta, name, version, now, age_days, allow_build=False):
    r = Report("uv", name, version)
    info = (vmeta or {}).get("info") if isinstance(vmeta, dict) else None
    if not isinstance(info, dict):
        r.check("exists", False, "no %s==%s on pypi.org" % (name, version), hard=True)
        return r
    files = [f for f in vmeta.get("urls") or [] if isinstance(f, dict)]
    r.check("exists", bool(files), "%d files" % len(files), hard=True)
    r.check("yanked", not info.get("yanked"), "yanked" if info.get("yanked") else "no", hard=True)
    wheels = [f for f in files if f.get("packagetype") == "bdist_wheel" and not f.get("yanked")]
    if allow_build:
        r.check("wheel", True, "%d wheels; source builds allowed by the user" % len(wheels))
    else:
        r.check("wheel", bool(wheels), "%d wheels (an sdist-only release runs its build code: "
                "needs --allow-build and the user's approval)" % len(wheels))
    stamps = sorted(f.get("upload_time_iso_8601") for f in files if f.get("upload_time_iso_8601"))
    _age(r, "age", stamps[0] if stamps else None, now, age_days)
    first = None
    for files_ in ((pmeta or {}).get("releases") or {}).values() if isinstance(pmeta, dict) else ():
        for f in files_ or []:
            t = parse_time((f or {}).get("upload_time_iso_8601"))
            if t is not None and (first is None or t < first):
                first = t
    if first is None:
        r.check("project-age", False, "first release unknown")
    else:
        days = (now - first) / 86400.0
        r.check("project-age", days >= PROJECT_MIN_AGE_DAYS,
                "project first released %.0f days ago (minimum %d)" % (days, PROJECT_MIN_AGE_DAYS))
    digests = [((f.get("digests") or {}).get("sha256") or "")[:16] for f in wheels[:1]]
    r.info.update(source=PYPI_INDEX, sha256=digests[0] if digests else None)
    return r


INSTALL_SCRIPTS = ("preinstall", "install", "postinstall")


def vet_npm(full, downloads, name, version, now, age_days, installer="npm", allow_scripts=False):
    r = Report(installer, name, version)
    vers = (full or {}).get("versions") if isinstance(full, dict) else None
    man = vers.get(version) if isinstance(vers, dict) else None
    if not isinstance(man, dict):
        r.check("exists", False, "no %s@%s on registry.npmjs.org" % (name, version), hard=True)
        return r
    r.check("exists", True, "registry.npmjs.org", hard=True)
    dep = man.get("deprecated")
    r.check("deprecated", not dep, ("deprecated: %s" % str(dep)[:80]) if dep else "no")
    times = full.get("time") or {}
    _age(r, "age", times.get(version), now, age_days)
    created = parse_time(times.get("created"))
    if created is None:
        r.check("project-age", False, "creation time unknown")
    else:
        days = (now - created) / 86400.0
        r.check("project-age", days >= PROJECT_MIN_AGE_DAYS,
                "package created %.0f days ago (minimum %d)" % (days, PROJECT_MIN_AGE_DAYS))
    n = downloads.get("downloads") if isinstance(downloads, dict) else None
    r.check("popularity", isinstance(n, int) and n >= NPM_MIN_WEEKLY,
            "%s downloads last week (minimum %d)" % (n, NPM_MIN_WEEKLY))
    scripts = man.get("scripts") if isinstance(man.get("scripts"), dict) else {}
    hooks = [s for s in INSTALL_SCRIPTS if s in scripts]
    if man.get("gypfile") or man.get("hasInstallScript"):
        hooks = hooks or ["install (node-gyp)"]
    if hooks:
        if allow_scripts:
            r.surface("install scripts WILL run (approved): %s" % ", ".join(hooks))
        else:
            r.surface("install scripts present and NOT run (--ignore-scripts): %s; if the "
                              "tool needs them, request --allow-scripts" % ", ".join(hooks))
    b = man.get("bin")
    check_bins(r, sorted(b) if isinstance(b, dict) else [name.rsplit("/", 1)[-1]] if b else [])
    r.info.update(source=NPM_REGISTRY, integrity=clean_text(((man.get("dist") or {}).get("integrity") or ""))[:24],
                  install_scripts=hooks)
    return r


def vet_cargo(vmeta, cmeta, name, version, now, age_days):
    r = Report("cargo", name, version)
    v = (vmeta or {}).get("version") if isinstance(vmeta, dict) else None
    if not isinstance(v, dict) or v.get("num") != version:
        r.check("exists", False, "no %s@%s on crates.io" % (name, version), hard=True)
        return r
    r.check("exists", True, "crates.io", hard=True)
    r.check("yanked", not v.get("yanked"), "yanked" if v.get("yanked") else "no", hard=True)
    bins = v.get("bin_names") or []
    r.check("binaries", bool(bins), "binaries: %s" % (", ".join(bins) or "none (a library crate)"),
            hard=True)
    _age(r, "age", v.get("created_at"), now, age_days)
    c = (cmeta or {}).get("crate") if isinstance(cmeta, dict) else None
    c = c if isinstance(c, dict) else {}
    created = parse_time(c.get("created_at"))
    if created is None:
        r.check("project-age", False, "creation time unknown")
    else:
        days = (now - created) / 86400.0
        r.check("project-age", days >= PROJECT_MIN_AGE_DAYS,
                "crate created %.0f days ago (minimum %d)" % (days, PROJECT_MIN_AGE_DAYS))
    n = c.get("recent_downloads")
    r.check("popularity", isinstance(n, int) and n >= CRATES_MIN_RECENT,
            "%s downloads in 90 days (minimum %d)" % (n, CRATES_MIN_RECENT))
    r.surface("cargo builds from source: the crate's and its dependencies' build scripts run")
    if bins:
        check_bins(r, bins)
    r.info.update(source="crates.io", checksum=clean_text(v.get("checksum") or "")[:16], bins=bins)
    return r


def vet_go(info, path, version, now, age_days, module=None):
    """`info`: the proxy's .info of the module that holds package `path` (`module`, default path)."""
    r = Report("go", path, version)
    if not isinstance(info, dict) or info.get("Version") != version:
        r.check("exists", False, "no %s@%s on proxy.golang.org" % (path, version), hard=True)
        return r
    r.check("exists", True, "proxy.golang.org, module %s (checksums from %s)" % (module or path, GO_SUMDB),
            hard=True)
    _age(r, "age", info.get("Time"), now, age_days)
    check_bins(r, [go_binary(path)])
    r.info.update(source=GO_PROXY, binary=go_binary(path), module=module or path)
    return r


def go_module_candidates(path):
    """Module paths that may hold package `path`, longest first (the proxy serves modules only)."""
    elems = path.split("/")
    return ["/".join(elems[:k]) for k in range(len(elems), 1, -1)]


def go_escape(path):
    """Module path as the proxy protocol spells it: an upper-case letter becomes ! + lower case."""
    return re.sub(r"[A-Z]", lambda m: "!" + m.group(0).lower(), path)
