#!/usr/bin/env bash
# Claude Code multi-agent stack — installer for macOS (Apple Silicon first).
#   ./install.sh                 core install
#   ./install.sh --with-ml       also create the ML venv ($C/venvs/ml: PyTorch, Transformers, PEFT,
#                                 scikit-learn/XGBoost/LightGBM, MLX + mlx-lm on Apple Silicon; several GB)
#   ./install.sh --with-lsp      also install missing language servers (pyright, typescript-language-server,
#                                 rust-analyzer) before enabling the code-intelligence plugins
#   ./install.sh --with-adobe    also build the After Effects MCP + install the Premiere connector (macOS)
#   ./install.sh --with-extra-plugins  also install Anthropic's skill-creator, mcp-server-dev and
#                                 math-olympiad plugins (their skills load on demand)
#   ./install.sh --no-mcp        skip registering user-scope MCP servers
#   ./install.sh --no-plugins    skip plugins (document skills, code-intelligence/LSP plugins)
#   ./install.sh --replace-mcp   re-register exa/jina/wolfram/huggingface/wandb even if you configured them
#   ./install.sh --force         overwrite agent, rules and skill files you edited since the last install
#   ./install.sh --no-deps       skip brew/uv/node/magg/huetension/venv installs and MCP dep prefetch
#                                 (missing tools become warnings instead of installs)
#   ./install.sh --no-profile    leave your shell rc file alone (don't add the stack.env source line)
#   ./install.sh --mcp-plan      print the MCP server add/migrate/replace/keep plan and make no changes
# Re-runnable: the files it replaces are backed up to $C/backup-<timestamp>-*/ first (a run that
# changes nothing keeps no duplicate backup).
# CLAUDE_CONFIG_DIR overrides the install target (default ~/.claude).
# STACK_CLAUDE_JSON overrides which JSON file the MCP plan reads (default: $C/.claude.json when
# CLAUDE_CONFIG_DIR is set — Claude Code then uses only that file —, else ~/.claude.json). The
# installer never writes that file itself: every MCP change goes through `claude mcp`.
set -euo pipefail

WITH_ADOBE=0; WITH_ML=0; WITH_LSP=0; WITH_EXTRA_PLUGINS=0; SKIP_MCP=0; SKIP_PLUGINS=0; REPLACE_MCP=0; FORCE=0; NO_DEPS=0
NO_PROFILE=0; MCP_PLAN=0; ORIG_ARGS="$*"
for a in "$@"; do
  case "$a" in
    --with-adobe) WITH_ADOBE=1 ;;
    --with-ml) WITH_ML=1 ;;
    --with-lsp) WITH_LSP=1 ;;
    --with-extra-plugins) WITH_EXTRA_PLUGINS=1 ;;
    --no-mcp) SKIP_MCP=1 ;;
    --no-plugins) SKIP_PLUGINS=1 ;;
    --replace-mcp) REPLACE_MCP=1 ;;
    --force) FORCE=1 ;;
    --no-deps) NO_DEPS=1 ;;
    --no-profile) NO_PROFILE=1 ;;
    --mcp-plan) MCP_PLAN=1 ;;
    -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
    *) echo "unknown option: $a"; exit 2 ;;
  esac
done
# macOS only. Linux support was dropped; the repo's own tests run the installer on Linux with
# STACK_ALLOW_NON_MACOS=1 (nothing else is supported there).
if [ "$(uname)" != "Darwin" ] && [ "${STACK_ALLOW_NON_MACOS:-0}" != 1 ]; then
  echo "claude-agent-stack installs on macOS only (this is $(uname))."
  exit 1
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/dot-claude"
C="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
mkdir -p "$C"
C="$(cd "$C" && pwd)"
OS="$(uname)"
say(){ printf '\n\033[1m%s\033[0m\n' "$*"; }
note(){ printf '  %s\n' "$*"; }
have(){ command -v "$1" >/dev/null 2>&1; }
# rustup installs a rust-analyzer proxy even without the component: run it, don't just find it
lsp_works(){ case "$1" in rust-analyzer) rust-analyzer --version >/dev/null 2>&1 ;; *) have "$1" ;; esac; }
# ~/.local/bin (uv, magg, huetension, npm --prefix installs) is APPENDED, so tools already on your
# PATH win — including a test double of `claude` — and the uv installer still sees the original PATH.
ORIG_PATH="$PATH"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) export PATH="$PATH:$HOME/.local/bin" ;; esac
MIN_CLAUDE=2.1.271

say "1/11 Prerequisites"
# Run them, don't just look them up: on a Mac without the Command Line Tools /usr/bin/python3 and
# /usr/bin/git exist as stubs that only open the CLT installer.
python3 -c 'import sys; sys.exit(sys.version_info < (3, 8))' >/dev/null 2>&1 \
  || { echo "python3 (3.8+) is required and must run (macOS: xcode-select --install)"; exit 1; }
git --version >/dev/null 2>&1 || { echo "git is required (macOS: xcode-select --install)"; exit 1; }
have claude || { echo "Claude Code is required: curl -fsSL https://claude.ai/install.sh | bash"; exit 1; }
CLAUDE_V="$(claude --version 2>/dev/null </dev/null | awk '{print $1}' || true)"
note "claude ${CLAUDE_V:-unknown}"
if [ -n "$CLAUDE_V" ] && [ "$(printf '%s\n%s\n' "$MIN_CLAUDE" "$CLAUDE_V" | sort -t. -k1,1n -k2,2n -k3,3n | head -n1)" != "$MIN_CLAUDE" ]; then
  note "! claude $CLAUDE_V is older than $MIN_CLAUDE, which this stack is built for — run: claude update"
fi
note "install target: $C"

# The interpreter every hook, the status line and the MCP header helper run with: absolute, stable
# across upgrades and never a version-manager shim (a shim that fails in some project makes every
# hook fail to start, which Claude Code treats as a non-blocking error: every gate silently open).
# (Output goes through a temp file: bash 3.2, macOS's /bin/bash, mis-parses heredocs inside $(...).)
if [ -z "${STACK_PYTHON:-}" ]; then
  pyfile="$(mktemp)"
  python3 - >"$pyfile" <<'PY'
import os, re, shutil, subprocess, sys


def works(py):
    try:
        return subprocess.run([py, "-c", "import fcntl, json, sys; sys.exit(sys.version_info < (3, 8))"],
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def clt_installed():
    try:
        return subprocess.run(["/usr/bin/xcode-select", "-p"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


cands = []
# macOS: /usr/bin/python3 is real only with the Command Line Tools (else a stub that opens an installer)
if sys.platform != "darwin" or clt_installed():
    cands.append("/usr/bin/python3")
cands += ["/opt/homebrew/bin/python3", "/usr/local/bin/python3"]
found = shutil.which("python3")
if found and not re.search(r"/(shims|\.pyenv|\.asdf|mise|\.rye)/", found):
    cands.append(found)
cands.append(os.path.realpath(sys.executable))
print(next((c for c in cands if os.path.isfile(c) and os.access(c, os.X_OK) and works(c)), "python3"))
PY
  STACK_PYTHON="$(cat "$pyfile")"; rm -f "$pyfile"
fi
export STACK_PYTHON
note "hook interpreter: $STACK_PYTHON"

# MCP plan: which user-scope remote servers to add, migrate (plaintext key -> headersHelper),
# replace (--replace-mcp) or keep. Read-only: sets PLAN (action, name, desired JSON, previous
# JSON, reason — tab-separated) and CFG.
compute_mcp_plan() {
  local envfile="$C/stack.env"
  [ -f "$envfile" ] || envfile="$HERE/stack.env.example"
  # stack.env is NOT sourced here: sourcing ran user code under set -u (an unset $VAR aborted the
  # installer, with exit 0 under bash 3.2's EXIT trap) and let an empty KEY= override a key already
  # exported in the environment. The plan parses it with the headersHelper's own parser instead.
  if [ -n "${STACK_CLAUDE_JSON:-}" ]; then
    CFG="$STACK_CLAUDE_JSON"
  elif [ -n "${CLAUDE_CONFIG_DIR:-}" ]; then
    CFG="$C/.claude.json"   # claude reads and creates it there under CLAUDE_CONFIG_DIR, even before it exists
  else
    CFG="$HOME/.claude.json"
  fi
  note "config read for the plan: $CFG (written only through 'claude mcp')"
  # Keys are never embedded: bin/mcp-headers reads them from stack.env at connection time.
  # wandb is registered only when WANDB_API_KEY is set (it has no anonymous access).
  # (Python writes to a temp file: bash 3.2, macOS's /bin/bash, mis-parses heredocs inside $(...).)
  local planfile
  planfile="$(mktemp)"
  ENVFILE="$envfile" PARSER="$SRC/bin/mcp-headers" HELPER="$C/bin/mcp-headers" CFG="$CFG" PY="$STACK_PYTHON" \
    REPLACE_MCP="$REPLACE_MCP" python3 - >"$planfile" <<'PY'
import json, os, re, runpy
from pathlib import Path
from urllib.parse import urlsplit
cfg_path, helper = os.environ["CFG"], os.environ["HELPER"]
replace_all = os.environ.get("REPLACE_MCP") == "1"
mh = runpy.run_path(os.environ["PARSER"], run_name="mcp_headers")
fileenv = mh["read_env_file"](Path(os.environ["ENVFILE"]))
def e(var):
    """Exactly what bin/mcp-headers would send: a non-empty stack.env value, else the environment;
    a value the helper rejects (unexpanded $VAR, spaces) counts as no key."""
    v = (fileenv.get(var) or os.environ.get(var) or "").strip()
    return v if v and "$" not in v and mh["VALUE_RE"].fullmatch(v) else ""
try:
    cfg = json.load(open(cfg_path))
except (OSError, ValueError):
    cfg = {}
existing = (cfg.get("mcpServers") or {}) if isinstance(cfg, dict) else {}
# the helper runs through the same absolute interpreter as the hooks (not `#!/usr/bin/env python3`)
helper_cmd = '"%s" "%s"' % (os.environ["PY"], helper)
# Exa: an explicit tools= list is the only way to get web_search_advanced_exa; agent_run is left out
# because requesting it without a key fails the connection (401), and keys may be added later.
EXA_URL = "https://mcp.exa.ai/mcp?tools=web_search_exa,web_fetch_exa,web_search_advanced_exa"
# URLs earlier stack versions registered: an entry still on one of these follows the stack's URL;
# any other URL on the same host is the user's own choice and is kept.
OLD_URLS = {"exa": {"https://mcp.exa.ai/mcp"}}
rows = [
    ("exa", "mcp.exa.ai", {"type": "http", "url": EXA_URL, "headersHelper": helper_cmd}),
    ("jina", "mcp.jina.ai", {"type": "http", "url": "https://mcp.jina.ai/v1?exclude_tools=search_jina_blog",
                             "headersHelper": helper_cmd}),
    ("wolfram", "agenttools.wolfram.com", {"type": "http", "url": "https://agenttools.wolfram.com/mcp"}),
    ("huggingface", "huggingface.co", {"type": "http", "url": "https://huggingface.co/mcp",
                                       "headersHelper": helper_cmd}),
]
if e("WANDB_API_KEY"):
    rows.append(("wandb", "mcp.withwandb.com", {"type": "http", "url": "https://mcp.withwandb.com/mcp",
                                                "headersHelper": helper_cmd}))
KEYVAR = {"exa": "EXA_API_KEY", "jina": "JINA_API_KEY", "huggingface": "HF_TOKEN", "wandb": "WANDB_API_KEY"}
# the stack's own helper, as any version registered it: [interpreter] <config>/bin/mcp-headers, each
# optionally quoted. Anything else (a wrapper such as `op run … -- …/mcp-headers`) is the user's.
STACK_HELPER = re.compile(r"""(?:(?:(["'])[^"']+\1|[^"'\s]+)\s+)?(["']?)[^"'\s]*/bin/mcp-headers\2""")
for name, host, desired in rows:
    cur = existing.get(name)
    save = "-"   # stack.env variable a literal key must be copied into before the entry is replaced
    if not isinstance(cur, dict):
        action, why = "add", "not configured"
    elif urlsplit(str(cur.get("url", ""))).hostname != host and not replace_all:
        action, why = "keep", "points elsewhere (%s), left alone" % (cur.get("url") or cur.get("command", "?"))
    else:
        literal = mh["key_from_entry"](name, cur)
        if replace_all:
            action, why = "replace", "--replace-mcp"
        elif cur.get("headers") or literal:
            action, why = "migrate", "key in plaintext config, moving it to headersHelper"
        elif "headersHelper" in desired and not cur.get("headersHelper"):
            action, why = "migrate", "no headersHelper yet, keys will come from stack.env"
        elif "headersHelper" in desired and not STACK_HELPER.fullmatch(str(cur.get("headersHelper")).strip()):
            action, why = "keep", "your own headersHelper (%s) kept" % cur.get("headersHelper")
        elif "headersHelper" in desired and cur.get("headersHelper") != desired["headersHelper"]:
            action, why = "migrate", "the stack's headersHelper, now run by %s" % os.environ["PY"]
        elif cur.get("url") != desired["url"] and cur.get("url") in OLD_URLS.get(name, ()):
            action, why = "migrate", "stack URL changed (%s)" % desired["url"]
        elif cur.get("url") != desired["url"]:
            action, why = "keep", "your URL (%s) kept; the stack's is %s" % (cur.get("url"), desired["url"])
        else:
            action, why = "keep", "up to date"
        if action != "keep" and literal and name in KEYVAR and not e(KEYVAR[name]):
            save = KEYVAR[name]
            why += "; its key is copied to stack.env as %s first" % save
    prev = json.dumps(cur) if isinstance(cur, dict) else "null"
    print("\t".join([action, name, json.dumps(desired), prev, save, why]))
PY
  PLAN="$(cat "$planfile")"
  rm -f "$planfile"
}

if [ "$MCP_PLAN" = 1 ]; then
  say "MCP plan (--mcp-plan: nothing is installed or changed)"
  compute_mcp_plan
  printf '%s\n' "$PLAN" | while IFS=$'\t' read -r action name _cfg _prev _save why; do
    [ -n "$name" ] && printf '%s\t%s\t%s\n' "$action" "$name" "$why"
  done
  exit 0
fi

say "2/11 Tools: magg, huetension, science venv"
SCI_PKGS="sympy numpy scipy mpmath pandas polars duckdb pyarrow matplotlib seaborn networkx pint statsmodels scikit-learn pdfplumber pypdf openpyxl python-docx python-pptx nbformat nbclient ipykernel z3-solver hypothesis"
if [ "$NO_DEPS" = 1 ]; then
  note "--no-deps: skipping brew/uv/node/magg/huetension/venv installs"
  have uv || note "! uv missing — install manually: curl -LsSf https://astral.sh/uv/install.sh | sh"
  have node || note "! node missing — install manually (Node.js 22.5+)"
  have magg || note "! magg missing — uv tool install magg"
  have huetension || note "! huetension missing — designer works without color MCP; see README"
  [ -x "$C/venvs/sci/bin/python" ] || note "! science venv missing at $C/venvs/sci"
else
  if ! have uv; then
    if have brew; then brew install uv
    else
      # The uv installer adds ~/.local/bin to your shell profile only when that directory is not on
      # PATH: give it the PATH you started with (this script appended ~/.local/bin to its own), and
      # keep it away from your profile under --no-profile.
      if [ "$NO_PROFILE" = 1 ]; then
        curl -LsSf https://astral.sh/uv/install.sh | env PATH="$ORIG_PATH" UV_NO_MODIFY_PATH=1 sh
      else
        curl -LsSf https://astral.sh/uv/install.sh | env PATH="$ORIG_PATH" sh
      fi
    fi
  fi
  if ! have node; then
    if have brew; then brew install node; else echo "Node.js 22.5+ is required: install Homebrew (https://brew.sh) and rerun, or install Node with nvm"; exit 1; fi
  fi
  # context-mode (researcher, doc-specialist) needs Node >= 22.5, typescript-language-server 6
  # (--with-lsp) >= 22, premiere-pro-mcp >= 20.19.
  node -e 'const [a, b] = process.versions.node.split(".").map(Number); process.exit(a > 22 || (a === 22 && b >= 5) ? 0 : 1)' 2>/dev/null \
    || note "! node $(node --version 2>/dev/null) is older than 22.5 — upgrade (brew upgrade node / nvm install 22); context-mode, some npx MCP servers and the TypeScript language server need it"
  if have brew; then
    for pair in ffmpeg:ffmpeg magick:imagemagick rsvg-convert:librsvg pdftoppm:poppler; do
      have "${pair%%:*}" || brew install "${pair##*:}" || note "optional: brew install ${pair##*:}"
    done
  else
    for b in ffmpeg magick rsvg-convert pdftoppm; do have "$b" || note "optional tool missing: $b (with Homebrew: brew install ffmpeg imagemagick librsvg poppler)"; done
  fi
  # `uv tool install` exits 0 when magg is already installed, so upgrade first, install if absent.
  uv tool upgrade --quiet magg 2>/dev/null || uv tool install --quiet magg || true
  have magg && note "magg $(magg --version 2>/dev/null | awk '{print $2}')"
  if ! have huetension; then
    mkdir -p "$HOME/.local/bin"
    os="$(echo "$OS" | tr '[:upper:]' '[:lower:]')"; arch="$(uname -m)"
    case "$arch" in x86_64|amd64) arch=amd64 ;; arm64|aarch64) arch=arm64 ;; esac
    url="$(curl -fsSL https://api.github.com/repos/leporel/huetension/releases/latest 2>/dev/null \
      | python3 -c "import sys,json;a=[x['browser_download_url'] for x in json.load(sys.stdin).get('assets',[]) if x['name'].endswith('_${os}_${arch}.tar.gz')];print(a[0] if a else '')" 2>/dev/null || true)"
    if [ -n "$url" ]; then
      tmp="$(mktemp -d)"
      if curl -fsSL "$url" | tar -xz -C "$tmp"; then
        bin="$(find "$tmp" -type f -name huetension | head -n1)"
        [ -n "$bin" ] && install -m 755 "$bin" "$HOME/.local/bin/huetension"
      fi
      rm -rf "$tmp"
    fi
    if ! have huetension && have go; then
      gobin="$(go env GOBIN 2>/dev/null)"; [ -n "$gobin" ] || gobin="$(go env GOPATH | cut -d: -f1)/bin"
      go install github.com/leporel/huetension/cmd/huetension@latest \
        && ln -sf "$gobin/huetension" "$HOME/.local/bin/huetension" \
        || note "huetension: go install failed (needs Go >= 1.26; Go >= 1.21 fetches it automatically)"
    fi
  fi
  have huetension && note "huetension ok" || note "! huetension missing — designer works without color MCP; see README"
  if [ ! -x "$C/venvs/sci/bin/python" ]; then uv venv --quiet --python 3.12 "$C/venvs/sci"; fi
  # shellcheck disable=SC2086  # word splitting of the package list is intended
  uv pip install --quiet --python "$C/venvs/sci/bin/python" $SCI_PKGS
  note "science venv: $C/venvs/sci"
fi

say "3/11 ML venv (--with-ml)"
if [ "$WITH_ML" = 0 ]; then
  if [ -x "$C/venvs/ml/bin/python" ]; then note "ML venv present: $C/venvs/ml (rerun with --with-ml to update)"; else note "skipped — ML agents use the project's environment or the science venv; add --with-ml for a shared ML venv"; fi
elif [ "$NO_DEPS" = 1 ] || ! have uv; then
  note "! --with-ml needs uv and is skipped under --no-deps"
else
  ML_PKGS="numpy scipy pandas polars pyarrow scikit-learn statsmodels xgboost lightgbm matplotlib seaborn torch transformers datasets accelerate peft safetensors huggingface_hub evaluate sentencepiece ipykernel nbclient"
  if [ "$OS" = "Darwin" ] && [ "$(uname -m)" = "arm64" ]; then ML_PKGS="$ML_PKGS mlx mlx-lm[evaluate]"; fi
  [ -x "$C/venvs/ml/bin/python" ] || uv venv --quiet --python 3.12 "$C/venvs/ml"
  # shellcheck disable=SC2086
  if uv pip install --quiet --python "$C/venvs/ml/bin/python" $ML_PKGS; then
    note "ML venv: $C/venvs/ml ($("$C/venvs/ml/bin/python" -c 'import torch,transformers;print("torch",torch.__version__,"· transformers",transformers.__version__)' 2>/dev/null || echo 'installed'))"
  else
    note "! ML venv install failed — rerun ./install.sh --with-ml, or use project environments"
  fi
fi

say "4/11 Adobe (--with-adobe)"
# Runs before rendering: motion-designer gets the After Effects server only once its build exists.
AE="$C/mcp/vendor/after-effects-mcp"
if [ "$WITH_ADOBE" = 0 ]; then
  if [ -f "$AE/build/index.js" ]; then note "After Effects MCP present (rerun with --with-adobe to update)"
  elif [ "$OS" = "Darwin" ]; then note "skipped — motion-designer gets the After Effects server once you run --with-adobe"
  else note "skipped (macOS only)"; fi
elif [ "$OS" != "Darwin" ]; then
  note "Adobe apps are macOS/Windows only — skipped"
else
  mkdir -p "$C/mcp/vendor"
  # Optional step: a failed pull/clone must not abort the installer (set -e) before the profile
  # step, and must never sit at a git credential prompt.
  if [ -d "$AE/.git" ]; then
    GIT_TERMINAL_PROMPT=0 git -C "$AE" pull --ff-only -q </dev/null || note "! After Effects MCP: git pull failed — keeping the current checkout"
  else
    GIT_TERMINAL_PROMPT=0 git clone -q --depth 1 https://github.com/Dakkshin/after-effects-mcp "$AE" </dev/null || note "! After Effects MCP: git clone failed"
  fi
  if [ -f "$AE/package.json" ]; then
    if (cd "$AE" && npm install --no-audit --no-fund --silent && npm run -s build); then note "+ After Effects MCP built"
    else note "! After Effects MCP build failed — cd \"$AE\" && npm install && npm run build"; fi
    if (cd "$AE" && npm run -s install-bridge); then note "+ After Effects bridge panel installed"
    else note "! AE bridge: close After Effects and run: cd \"$AE\" && npm run install-bridge  (may need sudo)"; fi
  fi
  if npx -y premiere-pro-mcp@1.18.2 --install-cep; then note "+ Premiere Pro CEP connector installed (restart Premiere; Window > Extensions > MCP for Adobe Premiere Pro)"
  else note "! Premiere connector: npx -y premiere-pro-mcp@1.18.2 --install-cep"; fi
  note "Illustrator: first tool call asks for Automation permission (System Settings > Privacy & Security > Automation)"
fi

say "5/11 Backup"
# mktemp: two runs in the same second must not share (and overwrite) one backup folder.
TS="$(date +%Y%m%d-%H%M%S)"; B="$(mktemp -d "$C/backup-$TS-XXXXXX")"
# (CLAUDE.md is yours now: the installer only ever moves the stack's old unedited copy into $B/retired/)
for f in settings.json magg/config.json; do
  if [ -f "$C/$f" ]; then mkdir -p "$B/$(dirname "$f")"; cp "$C/$f" "$B/$f"; fi
done
for d in agents rules skills hooks bin mcp; do
  [ -d "$SRC/$d" ] || continue
  for x in "$SRC/$d"/*; do
    n="$(basename "$x")"
    [ "$n" = "__pycache__" ] && continue
    if [ -e "$C/$d/$n" ]; then mkdir -p "$B/$d"; cp -R "$C/$d/$n" "$B/$d/"; fi
  done
done
note "backup: $B"

say "6/11 Render & install (agents, rules, skills, scripts, settings.json)"
mkdir -p "$C"/{agents,skills,hooks,mcp/vendor,magg/kit.d,bin,venvs}
cp "$SRC/hooks/agent_guard.py" "$C/hooks/"
chmod +x "$C/hooks/agent_guard.py"
cp "$SRC/bin/statusline.py" "$C/bin/"
chmod +x "$C/bin/statusline.py"
cp "$SRC/mcp/image_studio_mcp.py" "$SRC/mcp/libdocs_mcp.py" "$SRC/mcp/neural_memory_mcp.py" "$C/mcp/"
cp "$SRC/bin/doctor.sh" "$SRC/bin/with-stack-env" "$SRC/bin/mcp-headers" "$SRC/bin/magg-private" "$SRC/bin/claude-ultracode" "$C/bin/"
chmod +x "$C/bin/doctor.sh" "$C/bin/with-stack-env" "$C/bin/mcp-headers" "$C/bin/magg-private" "$C/bin/claude-ultracode"
[ -f "$C/stack.env" ] || cp "$HERE/stack.env.example" "$C/stack.env"
chmod 600 "$C/stack.env"
# Variables stack.env.example gained since your stack.env was created: appended with their comment
# lines, commented out — except the image models, appended set to image-studio's own defaults (the
# same models either way, now named where you change them). A value you wrote is never changed. The
# image lines earlier versions of stack.env.example put in your file are brought up to date: stale
# comments get today's wording, and settings nothing reads any more go while they still hold the
# stack's own default (Lumenfall's empty key, the old Opper model and folder); the previous file is
# kept in the backup folder.
python3 - "$HERE/stack.env.example" "$C/stack.env" "$B" <<'PY'
import os, re, shutil, sys, time
example, target, backup = sys.argv[1], os.path.realpath(sys.argv[2]), sys.argv[3]
VAR = re.compile(r"^\s*(?:#\s?)?(?:export\s+)?([A-Z][A-Z0-9_]*)=")
LIVE = {"IMAGE_STUDIO_SVG_MODEL", "IMAGE_STUDIO_IMAGE_MODEL", "IMAGE_STUDIO_EDIT_MODEL"}
OPENROUTER_LINES = ("# OpenRouter — generate_svg (vector art) and edit_image (edits, retouching, composites).\n"
                    "# https://openrouter.ai/settings/keys — an account limited to some providers must allow the ones your\n"
                    "# models run on: recraft and sourceful for the defaults (https://openrouter.ai/settings/preferences).")
OPPER_LINE = "# Opper — generate_image: photographs and other raster images. https://platform.opper.ai"
# Exact lines of earlier stack.env.example versions → today's wording (None: dropped).
REWORD = {
    # the first versions, up to 26 Sep 2026 (opper-image)
    "# Opper gateway — image generation/editing (image-director). https://platform.opper.ai": OPPER_LINE,
    "# Default image model and output folder (optional)": None,
    "OPPER_IMAGE_MODEL=bytedance:ap/seedream-5-pro": None,
    "OPPER_IMAGE_OUT_DIR=$HOME/Pictures/opper": None,
    # 26 Sep 2026 (openrouter-image: Recraft SVG only)
    "# OpenRouter — the stack's only image model: Recraft V4.1 Pro Vector, SVG output only (designer,":
        OPENROUTER_LINES.split("\n")[0],
    "# image-director; about $0.30 an image from your OpenRouter credits). https://openrouter.ai/settings/keys":
        "\n".join(OPENROUTER_LINES.split("\n")[1:]),
    "# Where generated SVGs go when an agent names no folder (optional)":
        "# Where generated images go when an agent names no folder (optional; IMAGE_STUDIO_OUT_DIR wins when set)",
    # 27 Sep 2026 (image-studio with Lumenfall for SVG)
    "# Images (designer, image-director) come from image-studio, one tool per provider, each billed to its":
        "# Images (designer, image-director) come from image-studio: generate_svg and edit_image through",
    "# own account; a missing key disables only its tool.":
        "# OpenRouter, generate_image through Opper; a missing key disables only the tools that need it.",
    "# Lumenfall — generate_svg: Recraft V4.1 Pro SVG for logos, icons, illustrations and other graphics": None,
    "# (about $0.30 an image). https://lumenfall.ai/app": None,
    "LUMENFALL_API_KEY=": None,
    "#LUMENFALL_API_KEY=": None,
    "# Opper — generate_image: GPT Image 2.5 Sunburst for photographs and other raster images (about": OPPER_LINE,
    "# $0.006-$0.21 an image, by quality). https://platform.opper.ai": None,
    "# OpenRouter — edit_image: Riverflow V2.5 Pro for edits, retouching and composites (from about $0.13).":
        OPENROUTER_LINES.split("\n")[0],
    "# https://openrouter.ai/settings/keys — an account limited to some providers must allow sourceful":
        OPENROUTER_LINES.split("\n")[1],
    "# (https://openrouter.ai/settings/preferences).": OPENROUTER_LINES.split("\n")[2],
}
text = open(target, encoding="utf-8", errors="surrogateescape").read()
before = text.split("\n")
lines = []
for line in before:
    key = line.rstrip()
    if key in REWORD:
        if REWORD[key] is not None:
            lines.extend(REWORD[key].split("\n"))
    else:
        lines.append(line)
reworded = lines != before
have = {m.group(1) for m in map(VAR.match, lines) if m}
out, names, live, comments = [], [], [], []
for line in open(example, encoding="utf-8").read().splitlines():
    m = VAR.match(line)
    if m:
        if m.group(1) not in have:
            if m.group(1) in LIVE:
                out += comments + [line]
                live.append(m.group(1))
            else:
                out += comments + [line if line.lstrip().startswith("#") else "#" + line.lstrip()]
                names.append(m.group(1))
        comments = []
    elif line.lstrip().startswith("#"):
        comments.append(line)
    else:
        comments = []
if out or reworded:
    new_text = "\n".join(lines)
    if out:
        new_text += ("" if new_text.endswith("\n") or not new_text else "\n") + (
            "\n# --- added by install.sh %s: new in stack.env.example (lines starting with # are off: "
            "uncomment to use) ---\n%s\n" % (time.strftime("%Y-%m-%d"), "\n".join(out)))
    if reworded:
        shutil.copy2(target, os.path.join(backup, "stack.env"))
        os.chmod(os.path.join(backup, "stack.env"), 0o600)
    fd = os.open(target + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape") as f:
        f.write(new_text)
    os.replace(target + ".tmp", target)
    if live:
        print("  stack.env: appended the image models, set to the defaults: " + ", ".join(live))
    if names:
        print("  stack.env: appended new variables (commented out): " + ", ".join(names))
    if reworded:
        print("  stack.env: brought the image lines of an earlier version up to date (previous copy: %s/stack.env)"
              % backup)


def value(raw):
    v = raw.strip()
    if v[:1] in ("'", '"') and v[0] in v[1:]:
        return v[1:v.index(v[0], 1)]
    return re.split(r"\s+#", v, maxsplit=1)[0].strip()


set_now = {m.group(1): value(m.group(2)) for m in (re.match(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)=(.*)$", l)
                                                   for l in lines) if m}
for old, now in (("LUMENFALL_API_KEY", "generate_svg runs on OpenRouter now, with OPENROUTER_API_KEY"),
                 ("OPPER_IMAGE_MODEL", "generate_image's model is IMAGE_STUDIO_IMAGE_MODEL"),
                 ("OPPER_IMAGE_OUT_DIR", "the output folder is IMAGE_STUDIO_OUT_DIR")):
    if set_now.get(old):
        print("  note: stack.env sets %s, which image-studio doesn't read (%s): delete that line" % (old, now))
PY

# Researcher's spider mcpServers block is only rewritten (to reuse an already-configured
# 'spider' server) when MCP registration is active and the user already has one.
SPIDER_REWRITE=0
if [ "$SKIP_MCP" = 0 ] && [ "$MCP_PLAN" = 0 ] && claude mcp get spider >/dev/null 2>&1 </dev/null; then SPIDER_REWRITE=1; fi

RENDERED_SETTINGS="$(mktemp)"
trap 'rm -f "$RENDERED_SETTINGS"' EXIT

FORCE="$FORCE" SPIDER_REWRITE="$SPIDER_REWRITE" RENDERED_SETTINGS="$RENDERED_SETTINGS" BACKUP="$B" \
python3 - "$SRC" "$C" "$HERE" <<'PY'
import difflib, glob, hashlib, json, os, re, shutil, subprocess, sys

SRC, C, REPO = sys.argv[1], sys.argv[2], sys.argv[3]
BACKUP = os.environ["BACKUP"]
FORCE = os.environ.get("FORCE") == "1"
SPIDER_REWRITE = os.environ.get("SPIDER_REWRITE") == "1"
home = os.path.expanduser("~")


def which(b, fallback):
    return shutil.which(b) or fallback


def stable_which(b, fallback):
    """Like which(), but prefer a package-manager path that survives upgrades (Homebrew, the
    distro) over nvm's versioned ~/.nvm/versions/node/vX/bin, which `nvm uninstall` deletes."""
    found = shutil.which(b)
    if found and "/.nvm/versions/" not in found:
        return found
    for d in ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"):
        cand = os.path.join(d, b)
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return found or fallback


SUBS = {
    "__CLAUDE_DIR__": C,
    "__HOME__": home,
    "__PYTHON3__": os.environ["STACK_PYTHON"],
    "__UV__": which("uv", home + "/.local/bin/uv"),
    "__UVX__": which("uvx", home + "/.local/bin/uvx"),
    "__NPX__": stable_which("npx", "npx"),
    "__NODE__": stable_which("node", "node"),
    "__MAGG__": which("magg", home + "/.local/bin/magg"),
    "__HUETENSION__": which("huetension", home + "/.local/bin/huetension"),
    "__STACK_REPO__": REPO,
}


def render(text, json_escape=False):
    out = text
    for k, v in SUBS.items():
        rv = json.dumps(v)[1:-1] if json_escape else v
        out = out.replace(k, rv)
    return out


def sha256(path):
    if not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def frontmatter_sets(text):
    """(tools set, mcpServers-name set) parsed loosely from an agent's frontmatter."""
    tools = set()
    m = re.search(r"(?m)^tools:\s*(.*)$", text)
    if m:
        tools = {t.strip() for t in m.group(1).split(",") if t.strip()}
    mcps = set(re.findall(r"(?m)^\s*-\s*([A-Za-z0-9_-]+):\s*$", text.split("mcpServers:", 1)[-1])) \
        if "mcpServers:" in text else set()
    return tools, mcps


def similar(installed_text, rendered_text):
    # old stack versions share >= 59% of their lines with the current render; user files <= 18%
    return difflib.SequenceMatcher(None, installed_text.splitlines(), rendered_text.splitlines(),
                                   autojunk=False).ratio() >= 0.4


def is_legacy_safe_overwrite(installed_text, rendered_text):
    """Heuristic for files installed before the manifest existed: safe to overwrite
    unless the installed copy has tools/mcpServers not present in the new render
    (a sign of a manual mcp-broker edit worth keeping), or is not an older copy of this
    stack's file at all (a same-named agent of the user's own: few shared lines)."""
    it, im = frontmatter_sets(installed_text)
    rt, rm = frontmatter_sets(rendered_text)
    if not (it.issubset(rt) and im.issubset(rm)):
        return False
    return similar(installed_text, rendered_text)


def legacy_renders(rel):
    """Renders of `rel` ("CLAUDE.md", "skills/<name>/SKILL.md") exactly as earlier stack versions
    shipped them (the repo's legacy/<version>/<rel>)."""
    out = []
    for p in sorted(glob.glob(os.path.join(REPO, "legacy", "*", rel))):
        try:
            out.append(render(open(p, encoding="utf-8").read()))
        except (OSError, UnicodeDecodeError):
            pass
    return out


def only_stack_lines(installed_text, renders):
    """True when every non-blank line of a file is a line some stack version shipped: it holds
    nothing of the user's own. A similarity ratio can't tell "the stack's old copy" from "the
    stack's copy plus my notes"."""
    known = {ln.strip() for r in renders for ln in r.splitlines() if ln.strip()}
    return all(ln.strip() in known for ln in installed_text.splitlines() if ln.strip())


def template_copy(installed_text, rel):
    """The file is a legacy/<version>/<rel> template with its placeholders filled in any way (another
    uv or npx path, another config dir than today's render would use): the stack's own, unedited."""
    for p in sorted(glob.glob(os.path.join(REPO, "legacy", "*", rel))):
        try:
            parts = re.split(r"(__[A-Z0-9_]+__)", open(p, encoding="utf-8").read())
        except (OSError, UnicodeDecodeError):
            continue
        rx = "".join(r"[^\n]*" if k % 2 else re.escape(part) for k, part in enumerate(parts))
        if re.fullmatch(rx, installed_text):
            return True
    return False


def pure_stack_copy(installed_text, renders):
    """An untracked file that is exactly some version the stack shipped (line for line, blank lines
    and order aside): nothing added, nothing removed. Replacing it (after the backup) loses nothing;
    a copy the user trimmed is a customization and is kept."""
    have = {ln.strip() for ln in installed_text.splitlines() if ln.strip()}
    return only_stack_lines(installed_text, renders) and any(
        {ln.strip() for ln in r.splitlines() if ln.strip()} <= have for r in renders)


manifest_path = os.path.join(C, ".stack-manifest.json")
try:
    manifest = json.load(open(manifest_path))
except (OSError, ValueError):
    manifest = {}
files_entry = manifest.setdefault("files", {})
offered = manifest.setdefault("offered", {})
manifest["repo"] = REPO     # where the stack's source lives (claude-code-engineer, mcp-broker)


def save_manifest():
    with open(manifest_path + ".tmp", "w") as mf:
        json.dump(manifest, mf, indent=2, sort_keys=True)
    os.replace(manifest_path + ".tmp", manifest_path)


# --- magg catalog: add the servers the shipped catalog has and yours doesn't; update an entry only
# while it is still exactly what an earlier stack version shipped (your edits are never touched).
# Catalog servers are reset to disabled: mcp-broker enables one for a task and disables it after. ---
def fingerprint(entry):
    """Entry minus the state magg itself changes (enabled, kits)."""
    core = {k: v for k, v in entry.items() if k not in ("enabled", "kits")}
    return hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()[:16]


# fingerprints of entries earlier stack versions shipped (before the manifest recorded them)
LEGACY_MAGG = {"docling": {"84d001fc6386deb0"}, "playwright": {"604f97c45597d8e6"},
               "lean": {"ef061039770a7579"}, "docspace": {"d93d837abbebe4ed"},
               "duckdb": {"529df3589fc6a3f6"}, "arxiv": {"484fdabd5d7ac75e"},
               "jupyter": {"4df0d303a3d2f0d2"}, "mlflow": {"4ca92ebdcfb8dd81"}}
magg_dst = os.path.realpath(os.path.join(C, "magg", "config.json"))
shipped_magg = json.loads(render(open(os.path.join(SRC, "magg", "config.json")).read(), json_escape=True))
prev_magg = manifest.get("magg_shipped") or {}
try:
    cur_magg = json.load(open(magg_dst))
    magg_ok = isinstance(cur_magg, dict)
except FileNotFoundError:
    cur_magg, magg_ok = {"servers": {}}, True
except ValueError as exc:
    print("  ! %s is not valid JSON (%s) — left unchanged; the catalog update was skipped" % (magg_dst, exc))
    magg_ok = False
if magg_ok:
    servers = cur_magg.setdefault("servers", {})
    added, updated, kept, disabled = [], [], [], []
    for k, entry in shipped_magg.get("servers", {}).items():
        mine = servers.get(k)
        if mine is None:
            servers[k] = entry
            added.append(k)
            continue
        if not isinstance(mine, dict):
            continue
        if fingerprint(mine) == fingerprint(entry):
            pass
        elif fingerprint(mine) in LEGACY_MAGG.get(k, set()) | ({prev_magg[k]} if k in prev_magg else set()):
            servers[k] = dict(entry, enabled=mine.get("enabled", True))
            updated.append(k)
        else:
            kept.append(k)
            continue
        if servers[k].get("enabled", True):          # magg leaves "enabled" out when true
            servers[k]["enabled"] = False
            disabled.append(k)
    if added or updated or disabled or not os.path.exists(magg_dst):
        os.makedirs(os.path.dirname(magg_dst), exist_ok=True)
        with open(magg_dst + ".tmp", "w") as f:
            json.dump(cur_magg, f, indent=2)
            f.write("\n")
        os.replace(magg_dst + ".tmp", magg_dst)
    manifest["magg_shipped"] = {k: fingerprint(e) for k, e in shipped_magg.get("servers", {}).items()}
    parts = [("added " + ", ".join(added)) if added else "", ("updated " + ", ".join(updated)) if updated else "",
             ("disabled again " + ", ".join(disabled)) if disabled else "",
             ("kept your edited " + ", ".join(kept)) if kept else ""]
    print("  magg catalog: %s" % ("; ".join(x for x in parts if x) or "up to date"))

# --- agents/*.md + rules/claude-agent-stack.md: manifest-guarded, non-destructive install ---
targets = [("agents/" + os.path.basename(p), p) for p in sorted(glob.glob(os.path.join(SRC, "agents", "*.md")))]
targets.append(("rules/claude-agent-stack.md", os.path.join(SRC, "rules", "claude-agent-stack.md")))
AE_BUILT = os.path.isfile(os.path.join(C, "mcp", "vendor", "after-effects-mcp", "build", "index.js"))

installed_count = 0
total_agents = sum(1 for rel, _ in targets if rel.startswith("agents/"))
IN_SYNC = {"installed", "unchanged", "overwritten", "overwritten (legacy)", "overwritten (--force)"}

# Adobe servers exist only on macOS: elsewhere they are left out of the renders, so designer and
# motion-designer don't start servers that can only fail (their prompts fall back to SVG/ffmpeg).
MACOS_ONLY_SERVERS = ("illustrator", "after-effects", "premiere")


def drop_servers(rendered, names):
    for n in names:
        rendered = re.sub(r"(?m)^  - %s:\n(?:      .*\n)+" % re.escape(n), "", rendered)
        rendered = re.sub(r",[ \t]*mcp__%s(?=[,\n])" % re.escape(n), "", rendered)
    return re.sub(r"(?m)^mcpServers:\n(?=[A-Za-z])", "", rendered)   # a block left empty


for rel, src_path in targets:
    text = open(src_path, encoding="utf-8").read()
    rendered = render(text)
    if sys.platform != "darwin" and rel.startswith("agents/"):
        rendered = drop_servers(rendered, MACOS_ONLY_SERVERS)
    elif rel == "agents/motion-designer.md" and not AE_BUILT:
        rendered = drop_servers(rendered, ("after-effects",))    # added once --with-adobe built it
    if rel == "agents/researcher.md" and SPIDER_REWRITE:
        rendered = re.sub(r"mcpServers:\n  - spider:\n(?:      .*\n)+", "mcpServers:\n  - spider\n", rendered)
    dest = os.path.join(C, rel)
    entry = files_entry.get(rel)
    installed_hash = sha256(dest)
    rendered_hash = sha256_text(rendered)

    def write(dest=dest, rendered=rendered, rendered_hash=rendered_hash, rel=rel):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            f.write(rendered)
        files_entry[rel] = rendered_hash
        offered.pop(rel, None)
        stale = dest + ".new"
        if os.path.exists(stale):
            os.remove(stale)

    if installed_hash is None:
        write()
        action = "installed"
    elif installed_hash == rendered_hash:
        write()
        action = "unchanged"
    elif entry is not None and installed_hash == entry:
        write()
        action = "overwritten"
    elif FORCE:
        write()
        action = "overwritten (--force)"
    elif entry is None and is_legacy_safe_overwrite(open(dest, encoding="utf-8", errors="replace").read(), rendered):
        write()
        action = "overwritten (legacy)"
    else:
        # dest was hand-edited since the last install (or a legacy file with extra
        # tools/mcpServers) — keep it, and drop the new render next to it as <name>.new.
        nd = dest + ".new"
        if offered.get(rel) == rendered_hash and not os.path.exists(nd):
            # this exact render was already offered and its .new removed after review: don't nag
            action = "kept (modified) -- this render was already offered; --force to take it"
        else:
            with open(nd, "w", encoding="utf-8") as f:
                f.write(rendered)
            offered[rel] = rendered_hash
            action = "kept (modified) -- new render at %s (diff -u %s %s)" % (nd, dest, nd)
    if action in IN_SYNC and rel.startswith("agents/"):
        installed_count += 1
    print("  %-34s %s" % (rel, action))

# Agent files an earlier stack version installed and this one doesn't ship (senior-coder is now
# main-coder): an unedited copy moves into the backup (retired/agents/), as does a leftover .new of
# it; an edited one stays — Claude Code keeps loading it as an agent of its own — with a note.
RENAMED = {"agents/senior-coder.md": "agents/main-coder.md"}
shipped = {rel for rel, _ in targets}
for rel in sorted((set(RENAMED) | {r for r in list(files_entry) + list(offered) if r.startswith("agents/")}) - shipped):
    dest = os.path.join(C, rel)
    entry = files_entry.get(rel)
    now = (" — it is now %s" % RENAMED[rel]) if rel in RENAMED else ""
    retired_agents = os.path.join(BACKUP, "retired", "agents")
    if os.path.isfile(dest):
        text = open(dest, encoding="utf-8", errors="replace").read()
        if sha256(dest) == entry if entry is not None else (
                template_copy(text, rel) or pure_stack_copy(text, legacy_renders(rel))):
            os.makedirs(retired_agents, exist_ok=True)
            shutil.move(dest, os.path.join(retired_agents, os.path.basename(rel)))
            print("  %-34s retired%s (old copy: %s/)" % (rel, now, retired_agents))
        elif entry is not None or any(similar(text, r) for r in legacy_renders(rel)):
            print("  %-34s kept (it differs from the stack's version): the stack no longer ships it%s."
                  " Move your changes over and delete it" % (rel, now))
    if os.path.isfile(dest + ".new"):
        os.makedirs(retired_agents, exist_ok=True)
        shutil.move(dest + ".new", os.path.join(retired_agents, os.path.basename(rel) + ".new"))
        print("  %-34s retired: a render of an agent the stack no longer ships" % (rel + ".new"))
    files_entry.pop(rel, None)
    offered.pop(rel, None)

# The global rules used to be installed as CLAUDE.md. That file is now yours: on the first run of this
# version the stack's old copy is retired into the backup while still unedited; an edited one, or
# your own, is left alone. The decision is made once — CLAUDE.md is never looked at again.
old_md = os.path.join(C, "CLAUDE.md")
if not manifest.get("claude_md_migrated"):
    rules_render = render(open(os.path.join(SRC, "rules", "claude-agent-stack.md"), encoding="utf-8").read())
    stack_versions = legacy_renders("CLAUDE.md") + [rules_render]
    retired_dir = os.path.join(BACKUP, "retired")
    if os.path.isfile(old_md):
        old_entry = files_entry.get("CLAUDE.md")
        old_text = open(old_md, encoding="utf-8", errors="replace").read()
        # tracked: the hash decides (an edited copy is kept); untracked: only an exact old version goes
        if sha256(old_md) == old_entry if old_entry is not None else pure_stack_copy(old_text, stack_versions):
            os.makedirs(retired_dir, exist_ok=True)
            shutil.move(old_md, os.path.join(retired_dir, "CLAUDE.md"))
            print("  %-34s retired: the stack's rules now live in rules/claude-agent-stack.md (old copy: %s/)"
                  % ("CLAUDE.md", retired_dir))
        elif old_entry is not None or any(similar(old_text, r) for r in stack_versions):
            print("  %-34s kept (it has lines of your own): the stack's rules moved to rules/claude-agent-stack.md —"
                  " delete the stack's old sections from CLAUDE.md so the two versions don't conflict" % "CLAUDE.md")
    # an old render of the rules the previous installer left next to an edited CLAUDE.md
    old_new = old_md + ".new"
    if os.path.isfile(old_new):
        new_text = open(old_new, encoding="utf-8", errors="replace").read()
        if "CLAUDE.md" in offered or only_stack_lines(new_text, stack_versions):
            os.makedirs(retired_dir, exist_ok=True)
            shutil.move(old_new, os.path.join(retired_dir, "CLAUDE.md.new"))
            print("  %-34s retired: an old render of the stack's rules (moved to %s/)" % ("CLAUDE.md.new", retired_dir))
    files_entry.pop("CLAUDE.md", None)
    offered.pop("CLAUDE.md", None)
    manifest["claude_md_migrated"] = True

save_manifest()
print("  %d/%d agents installed" % (installed_count, total_agents))
if installed_count < total_agents:
    print("  ! %d agent file(s) kept with local edits: merge the .new renders (or rerun with --force)"
          % (total_agents - installed_count))

# --- shipped skill files: manifest-guarded like the agents. A file you edited since the last
# install — or a same-named skill of your own — is kept, and the new render goes next to it as
# <file>.new; an untracked file that is an older copy of the stack's is refreshed. ---
def install_tracked(rel, dest, rendered):
    """None when the file is (now) in sync; "refreshed" when an untracked copy made only of lines
    some stack version shipped was replaced (the backup keeps it); "kept" when it is yours."""
    rendered_hash = sha256_text(rendered)
    installed_hash = sha256(dest)
    entry = files_entry.get(rel)
    nd = dest + ".new"
    legacy_ours = entry is None and installed_hash not in (None, rendered_hash) and pure_stack_copy(
        open(dest, encoding="utf-8", errors="replace").read(), [rendered] + legacy_renders(rel))
    if installed_hash is None or installed_hash == rendered_hash or FORCE or installed_hash == entry \
            or legacy_ours:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            f.write(rendered)
        files_entry[rel] = rendered_hash
        offered.pop(rel, None)
        if os.path.exists(nd):
            os.remove(nd)
        return "refreshed" if legacy_ours else None
    if not (offered.get(rel) == rendered_hash and not os.path.exists(nd)):
        with open(nd, "w", encoding="utf-8") as f:
            f.write(rendered)
        offered[rel] = rendered_hash
    return "kept"


skill_names = [os.path.basename(d) for d in glob.glob(os.path.join(SRC, "skills", "*")) if os.path.isdir(d)]
skills_kept, skills_refreshed = [], []
for name in skill_names:
    sdir = os.path.join(SRC, "skills", name)
    ddir = os.path.join(C, "skills", name)
    for root, _dirs, files in os.walk(sdir):
        rel_root = os.path.relpath(root, sdir)
        out_root = ddir if rel_root == "." else os.path.join(ddir, rel_root)
        os.makedirs(out_root, exist_ok=True)
        for fn in files:
            if fn.endswith((".pyc", ".new")) or fn == ".DS_Store":
                continue
            sp = os.path.join(root, fn)
            op = os.path.join(out_root, fn)
            try:
                text = open(sp, encoding="utf-8").read()
            except (UnicodeDecodeError, ValueError):
                shutil.copy2(sp, op)
                continue
            rel = os.path.relpath(op, C)
            state = install_tracked(rel, op, render(text))
            if state == "kept":
                skills_kept.append(rel)
            elif state == "refreshed":
                skills_refreshed.append(rel)
save_manifest()
print("  skills rendered (%d): %s" % (len(skill_names), ", ".join(sorted(skill_names))))
for rel in skills_refreshed:
    print("  %-34s refreshed (an older copy of the stack's; kept in %s)" % (rel, BACKUP))
for rel in skills_kept:
    print("  %-34s kept (yours or edited) -- new render at %s.new" % (rel, os.path.join(C, rel)))

# --- settings.json: JSON-escaped render, written to a temp file for the merge step ---
settings_text = open(os.path.join(SRC, "settings.json")).read()
open(os.environ["RENDERED_SETTINGS"], "w").write(render(settings_text, json_escape=True))

print("  " + ", ".join("%s=%s" % (k.strip("_").lower(), v) for k, v in SUBS.items()))
PY

# Files earlier stack versions installed and this one doesn't: moved into the backup, never deleted.
# (router-guard.sh: router.md now runs agent_guard.py directly with an absolute interpreter.)
if [ -f "$C/hooks/router-guard.sh" ] && ! grep -q 'router-guard.sh' "$C/agents/router.md" 2>/dev/null; then
  mkdir -p "$B/retired/hooks" && mv "$C/hooks/router-guard.sh" "$B/retired/hooks/" \
    && note "retired hooks/router-guard.sh (moved to $B/retired/hooks/)"
fi

say "7/11 Merge settings.json"
[ -f "$C/settings.json" ] || echo '{}' > "$C/settings.json"
python3 - "$RENDERED_SETTINGS" "$C/settings.json" "$C/.stack-manifest.json" <<'PY'
import json, os, re, sys
src, manifest_path = sys.argv[1], sys.argv[3]
# Write through a symlinked settings.json (dotfiles repo) instead of replacing the link.
dst = os.path.realpath(sys.argv[2])


def load_lenient(p):
    """Strict JSON first; then repair // comments, trailing commas and missing end-of-line commas."""
    raw = open(p, encoding="utf-8").read()
    try:
        return json.loads(raw), []
    except json.JSONDecodeError as first:
        err = first
    fixes, text = [], re.sub(r'(?m)^\s*//.*$', '', raw)
    if text != raw:
        fixes.append("removed // comment lines")
    t2 = re.sub(r',(\s*[}\]])', r'\1', text)
    if t2 != text:
        fixes.append("removed trailing commas")
    text = t2
    for _ in range(20):
        try:
            return json.loads(text), fixes
        except json.JSONDecodeError as e:
            err = e
            if e.msg != "Expecting ',' delimiter":
                break
            j = e.pos - 1
            while j >= 0 and text[j] in " \t\r\n":
                j -= 1
            # repair a comma missing after a complete value, before the next "key" (same or next line)
            if j < 0 or text[j] not in '"}]0123456789el' or text[e.pos:e.pos + 1] not in ('"', '{', '['):
                break
            text = text[:j + 1] + "," + text[j + 1:]
            fixes.append("added missing comma on line %d" % (text.count("\n", 0, j) + 1))
    lines = raw.splitlines()
    print("\n  ERROR: %s is not valid JSON — line %d, column %d: %s" % (p, err.lineno, err.colno, err.msg))
    for i in range(max(1, err.lineno - 2), min(len(lines), err.lineno + 1) + 1):
        print("  %5d | %s" % (i, lines[i - 1]))
        if i == err.lineno:
            print("        | " + " " * (err.colno - 1) + "^")
    print("  Fix that spot (often a missing comma or an unescaped \" inside a string), then rerun ./install.sh")
    sys.exit(3)


new = json.load(open(src))
cur, fixes = load_lenient(dst)
for f in fixes:
    print("  repaired your settings.json:", f, "(original kept in the backup folder)")


def uniq(xs):
    out = []
    for x in xs:
        if x not in out:
            out.append(x)
    return out


try:
    manifest = json.load(open(manifest_path))
except (OSError, ValueError):
    manifest = {}
prev_env = manifest.get("settings_env") or {}
prev_perm = manifest.get("settings_permissions") or {}
prev_owned = manifest.get("settings_set_if_absent") or {}
# permission rules earlier stack versions shipped before the manifest recorded them, and no longer
# ship: retracted on upgrade (a stack-shipped "mcp__magg" allowed every tool of every mounted server;
# "Read(**/.env.*)" also blocked agents from writing .env.example / .env.test — Read denies cover Edit)
RETIRED_PERMISSIONS = {"allow": {"mcp__magg"}, "deny": {"Read(**/.env.*)"}}
# env values earlier stack versions shipped before the manifest recorded them, and no longer ship:
# removed while they still hold that value. ENABLE_TOOL_SEARCH=true: tool search is on by default on
# the Anthropic API, and "true" forces it through gateways (ANTHROPIC_BASE_URL) that reject it.
RETIRED_ENV = {"ENABLE_TOOL_SEARCH": {"true"}}
# Both apply once, to an install whose manifest predates "settings_permissions"/"settings_env";
# later retractions come from the manifest itself. A value you add back afterwards stays.
if "settings_permissions" in manifest:
    RETIRED_PERMISSIONS = {}
if "settings_env" in manifest:
    RETIRED_ENV = {}
# top-level keys the stack sets only when you have none (or still have the stack's own value).
# "agent": set "agent": "claude" to keep the plain main thread (then: claude --agent router).
# "skillListingBudgetFraction": share of the context window for the skill listing (Claude Code's
# default 0.01 is 30K characters on a 1M-context model, most of which the stack's own skills take;
# over budget, the least-used skills are listed by name only). tests/lint_agents.py checks the size.
SET_IF_ABSENT = {"statusLine", "agent", "skillListingBudgetFraction"}
# env keys the stack re-asserts on every run; every other shipped env key is a default the user
# may tune (README "knobs"): it follows stack upgrades only while the user has not changed it.
OWNED_ENV = {"STACK_ENV_FILE", "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH",
             "MCP_DISCOVERY_CACHE", "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS"}
# values shipped by stack versions whose manifest predates "settings_env"
OLD_DEFAULTS = {"ROUTER_MAX_DISPATCH": {"1"}}

merged = dict(cur)
for k, v in new.items():
    if k == "hooks":
        h = dict(cur.get("hooks") or {})
        for ev, groups in v.items():
            kept = []
            for g in h.get(ev) or []:
                if isinstance(g, dict) and isinstance(g.get("hooks"), list):
                    mine = [x for x in g["hooks"] if "agent_guard.py" not in json.dumps(x)]
                    if len(mine) < len(g["hooks"]):   # the stack's guard shares this group
                        if not mine:
                            continue
                        g = dict(g, hooks=mine)       # keep the user's own hooks of that group
                        print("  kept %d hook(s) of yours from a %s group shared with the stack's guard" % (len(mine), ev))
                elif "agent_guard.py" in json.dumps(g):
                    continue
                kept.append(g)
            h[ev] = kept + groups
        merged["hooks"] = h
    elif k == "permissions":
        p = dict(cur.get("permissions") or {})
        for pk, pv in v.items():
            if not isinstance(pv, list):
                p[pk] = pv
                continue
            retired = (set(prev_perm.get(pk) or []) | RETIRED_PERMISSIONS.get(pk, set())) - set(pv)
            have = list(p.get(pk) or [])
            dropped = [x for x in have if x in retired]
            if dropped:
                print("  retracted stack permission rule(s) from %s: %s" % (pk, ", ".join(dropped)))
            p[pk] = uniq([x for x in have if x not in retired] + pv)
        merged["permissions"] = p
    elif k in SET_IF_ABSENT:
        if k not in cur or cur.get(k) == prev_owned.get(k) or cur.get(k) == v:
            merged[k] = v
        else:
            print("  kept your %s (the stack's: %s)" % (k, json.dumps(v)))
    elif k == "env":
        e = dict(cur.get("env") or {})
        for ek, sv in v.items():
            mine = e.get(ek)
            if (mine is None or ek in OWNED_ENV or str(mine) == str(sv) or str(mine) == str(prev_env.get(ek))
                    or str(mine) in OLD_DEFAULTS.get(ek, ())):
                e[ek] = sv
            elif ek == "ANTHROPIC_DEFAULT_HAIKU_MODEL" and "haiku" in str(mine).lower():
                # the stack runs no Haiku: the haiku alias and background tasks use Sonnet 5
                print("  replaced env %s=%s with %s (the stack uses Sonnet 5 wherever Haiku ran)" % (ek, mine, sv))
                e[ek] = sv
            else:
                print("  kept your env %s=%s (stack default: %s)" % (ek, mine, sv))
        # keys an earlier stack version shipped and this one doesn't: removed while unchanged
        for ek in sorted((set(prev_env) | set(RETIRED_ENV)) - set(v)):
            shipped = set(RETIRED_ENV.get(ek, ()))
            if ek in prev_env:
                shipped.add(str(prev_env[ek]))
            if ek in e and str(e[ek]) in shipped:
                print("  retracted stack env %s=%s (no longer shipped)" % (ek, e.pop(ek)))
        merged["env"] = e
    else:
        merged[k] = v
env = merged.get("env", {})
for k in ("ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
          "ANTHROPIC_DEFAULT_FABLE_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL"):
    if str(env.get(k, "")).endswith("[1m]"):
        print("  removed stale %s=%s (current models have 1M natively; the pin broke subagent models in Claude Desktop)" % (k, env.pop(k)))
if "CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION" in env:
    print("  removed no-op env CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION=%s (removed from Claude Code in v2.1.224; use CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS)" % env.pop("CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION"))
for bad in ("CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "CLAUDE_CODE_EFFORT_LEVEL"):
    if bad in env:
        print("  WARNING: env %s overrides per-agent model/effort — removed" % bad)
        env.pop(bad)
# Auto-compaction is part of the spec (on, 800K window): drop settings that silently defeat it.
for bad, why in (("DISABLE_AUTO_COMPACT", "turns auto-compaction off"),
                 ("DISABLE_COMPACT", "turns every compaction off"),
                 ("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "overrides autoCompactWindow")):
    if bad in env:
        print("  WARNING: env %s=%s %s — removed (autoCompactWindow=%s is the stack's setting)"
              % (bad, env.pop(bad), why, new.get("autoCompactWindow")))
for warn_only, why in (("CLAUDE_CODE_DISABLE_1M_CONTEXT", "caps every model at 200K, so compaction happens at 200K, not 800K"),
                       ("CLAUDE_AUTOCOMPACT_PCT_OVERRIDE", "makes compaction trigger earlier than the 800K window")):
    if warn_only in env:
        print("  note: env %s=%s %s (kept — remove it if unintended)" % (warn_only, env[warn_only], why))
merged["env"] = env
if "model" in cur:
    print("  note: kept your 'model' setting (%s); the router agent sets the main-thread model" % cur["model"])
order = ["$schema", "agent", "autoCompactEnabled", "autoCompactWindow"]
merged = {**{k: merged[k] for k in order if k in merged}, **{k: v for k, v in merged.items() if k not in order}}
with open(dst + ".tmp", "w", encoding="utf-8") as f:
    json.dump(merged, f, indent=2, ensure_ascii=False)
    f.write("\n")
try:
    os.chmod(dst + ".tmp", os.stat(dst).st_mode & 0o7777)
except OSError:
    pass
os.replace(dst + ".tmp", dst)
manifest["settings_env"] = new.get("env", {})
manifest["settings_permissions"] = {pk: pv for pk, pv in (new.get("permissions") or {}).items()
                                    if isinstance(pv, list)}
manifest["settings_set_if_absent"] = {k: new[k] for k in SET_IF_ABSENT if k in new}
with open(manifest_path + ".tmp", "w") as f:
    json.dump(manifest, f, indent=2, sort_keys=True)
os.replace(manifest_path + ".tmp", manifest_path)
print("  merged into", dst)
PY

say "8/11 MCP dependency prefetch"
if [ "$NO_DEPS" = 1 ]; then
  note "--no-deps: skipping MCP dependency prefetch"
elif ! have uv; then
  note "! uv missing — skipping MCP dependency prefetch"
else
  # First starts of stdio servers otherwise race MCP_TIMEOUT while packages download.
  for f in image_studio_mcp.py libdocs_mcp.py neural_memory_mcp.py; do uv run --quiet --script "$C/mcp/$f" --help >/dev/null 2>&1 </dev/null || true; done
  have uvx && { uvx --quiet markitdown-mcp@0.0.1a7 --help >/dev/null 2>&1 </dev/null || true; }
  # cg-artist's Blender server: download only (it would wait on the Blender add-on's socket)
  have uv && { uv tool run --quiet --from mcp-for-blender==2.1.1 python -c pass >/dev/null 2>&1 </dev/null || true; }
  have npx && { npx -y @playwright/mcp@0.0.82 --help >/dev/null 2>&1 </dev/null || true; }
  have npx && { npx -y context-mode@1.0.169 --help >/dev/null 2>&1 </dev/null || true; }
  note "prefetched libdocs, image-studio, neural-memory, markitdown, mcp-for-blender, playwright, context-mode"
fi

say "9/11 MCP servers (user scope, remote HTTP — lazy connect, tools deferred, keys via headersHelper)"
compute_mcp_plan

if [ "$SKIP_MCP" = 1 ]; then
  note "--no-mcp: skipped registering user-scope MCP servers"
else
  printf '%s\n' "$PLAN" | while IFS=$'\t' read -r action name cfg prev save why; do
    [ -n "$name" ] || continue
    case "$action" in
      keep) note "= $name ($why)"; continue ;;
      add)
        if claude mcp get "$name" >/dev/null 2>&1 </dev/null; then
          note "= $name already configured where claude looks — kept yours (--replace-mcp to overwrite)"; continue
        fi ;;
    esac
    if [ "$save" != "-" ]; then
      # The entry carries a literal key and stack.env has none: copy it there first, or the
      # migration would silently discard the user's key. (Passed via env, not argv.)
      if ! PREV="$prev" python3 - "$C/stack.env" "$name" "$save" "$SRC/bin/mcp-headers" <<'PY'
import json, os, re, runpy, sys
from pathlib import Path
envfile, name, var, parser = sys.argv[1:5]
mh = runpy.run_path(parser, run_name="mcp_headers")
key = mh["key_from_entry"](name, json.loads(os.environ["PREV"]))
if not key:
    sys.exit(1)
envfile = os.path.realpath(envfile)
try:
    lines = open(envfile, encoding="utf-8").read().splitlines(keepends=True)
except FileNotFoundError:
    lines = []
have = mh["read_env_file"](Path(envfile)).get(var, "")
if have and "$" not in have and mh["VALUE_RE"].fullmatch(have):
    sys.exit(0)                         # a usable value is already there: never overwrite it
pat = re.compile(r"^\s*(?:export\s+)?%s\s*=" % re.escape(var))
done = False
if not have:                            # fill the empty KEY= line in place
    for i, l in enumerate(lines):
        if pat.match(l):
            lines[i] = "%s=%s\n" % (var, key)
            done = True
            break
if not done:                            # keep the user's (unusable) line; a later assignment wins
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    lines.append("# copied by install.sh from the %s MCP entry\n%s=%s\n" % (name, var, key))
tmp = envfile + ".tmp"
fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as f:
    f.writelines(lines)
os.replace(tmp, envfile)
PY
      then
        note "! could not copy $name's key into $C/stack.env — left the $name entry unchanged"; continue
      fi
      note "  copied $name's key from $CFG into $C/stack.env ($save)"
    fi
    claude mcp remove -s user "$name" >/dev/null 2>&1 </dev/null || true
    if claude mcp add-json -s user "$name" "$cfg" >/dev/null 2>&1 </dev/null; then
      note "+ $name ($action: $why)"
    else
      note "! failed to add $name — run: claude mcp add-json -s user $name '$cfg'"
      if [ "$prev" != "null" ] && claude mcp add-json -s user "$name" "$prev" >/dev/null 2>&1 </dev/null; then
        note "  restored your previous $name entry"
      fi
    fi
  done
  if [ -f "$CFG" ]; then
    chmod 600 "$CFG" 2>/dev/null || true
    if grep -Eq '"(x-api-key|Authorization)"[[:space:]]*:[[:space:]]*"[^"$]{8,}' "$CFG" 2>/dev/null; then
      note "! $CFG still contains a literal API key in some MCP server's headers — run: ./install.sh --mcp-plan, or move it to stack.env"
    fi
  fi
  # Same services registered under other names won't match the agents' tool allowlists.
  claude mcp list 2>/dev/null </dev/null | while IFS= read -r l; do
    n="${l%%:*}"
    case "$l" in
      *mcp.exa.ai*|*exa-mcp*) [ "$n" = exa ] || note "! '$n' looks like Exa — rename it to 'exa' (agents allow mcp__exa)";;
      *mcp.jina.ai*|*jina-mcp*) [ "$n" = jina ] || note "! '$n' looks like Jina — rename it to 'jina'";;
      *huggingface.co/mcp*) [ "$n" = huggingface ] || note "! '$n' looks like the Hugging Face MCP — rename it to 'huggingface'";;
      *spider-cloud-mcp*|*spider.cloud*) [ "$n" = spider ] || note "! '$n' looks like Spider — rename it to 'spider'";;
      *mcp.context7.com*) note "- '$n' (Context7) is no longer used — libdocs replaces it; remove with: claude mcp remove -s user $n";;
    esac
  done
fi

say "10/11 Plugins and code intelligence"
if [ "$SKIP_PLUGINS" = 0 ] && [ "$MCP_PLAN" = 0 ]; then
  if [ -d "$C/skills/synced/docx" ]; then
    note "docx/xlsx/pptx/pdf skills already synced from claude.ai — skipping document-skills plugin"
  else
    claude plugin marketplace add anthropics/skills >/dev/null 2>&1 </dev/null || true
    claude plugin install document-skills@anthropic-agent-skills --scope user >/dev/null 2>&1 </dev/null \
      && note "+ document-skills (docx, xlsx, pptx, pdf)" \
      || note "! run inside claude: /plugin marketplace add anthropics/skills  then  /plugin install document-skills@anthropic-agent-skills"
  fi
  # Code intelligence: a language server starts only when Claude edits a matching file (on demand).
  if [ "$WITH_LSP" = 1 ] && [ "$NO_DEPS" = 0 ]; then
    # npm -g goes into Node's own prefix when that is writable and outlives Node upgrades (Homebrew);
    # a root-owned distro prefix (/usr: EACCES) or a version manager's per-version prefix under
    # $HOME (nvm, fnm, volta) gets ~/.local instead (bin/ there is on PATH via the profile line).
    npm_g(){
      local pfx; pfx="$(npm prefix -g 2>/dev/null || true)"
      case "$pfx" in
        ""|"$HOME"/*) npm install -g --prefix "$HOME/.local" --silent "$@" ;;
        *) if [ -w "$pfx/lib" ]; then npm install -g --silent "$@"; else npm install -g --prefix "$HOME/.local" --silent "$@"; fi ;;
      esac
    }
    have pyright-langserver || { have npm && npm_g pyright >/dev/null 2>&1; } \
      || note "! pyright install failed — npm install -g --prefix ~/.local pyright"
    # typescript-language-server 6 needs Node >= 22; older Node gets the 5.x line.
    TSLS=typescript-language-server
    node -e 'process.exit(+process.versions.node.split(".")[0] >= 22 ? 0 : 1)' 2>/dev/null || TSLS="typescript-language-server@5"
    have typescript-language-server || { have npm && npm_g "$TSLS" typescript >/dev/null 2>&1; } \
      || note "! typescript-language-server install failed — npm install -g --prefix ~/.local $TSLS typescript"
    lsp_works rust-analyzer || { have rustup && rustup component add rust-analyzer >/dev/null 2>&1; } || note "! rust-analyzer: rustup component add rust-analyzer"
  fi
  claude plugin marketplace add anthropics/claude-plugins-official >/dev/null 2>&1 </dev/null || true
  lsp_added=""; lsp_failed=""; lsp_missing=""
  for pair in pyright-langserver:pyright-lsp typescript-language-server:typescript-lsp rust-analyzer:rust-analyzer-lsp sourcekit-lsp:swift-lsp clangd:clangd-lsp gopls:gopls-lsp jdtls:jdtls-lsp; do
    b="${pair%%:*}"; p="${pair##*:}"
    if lsp_works "$b"; then
      # `claude plugin install` exits 0 when the plugin is already installed, so a failure is real
      if claude plugin install "$p@claude-plugins-official" --scope user >/dev/null 2>&1 </dev/null; then lsp_added="$lsp_added $p"; else lsp_failed="$lsp_failed $p"; fi
    else
      lsp_missing="$lsp_missing $b"
    fi
  done
  [ -n "$lsp_added" ] && note "+ code intelligence:$lsp_added"
  [ -n "$lsp_failed" ] && note "! plugin install failed:$lsp_failed (inside claude: /plugin install <name>@claude-plugins-official)"
  [ -n "$lsp_missing" ] && note "- no language server for:$lsp_missing (./install.sh --with-lsp installs pyright, typescript-language-server, rust-analyzer; Java: brew install jdtls)"
  # Optional Anthropic skill plugins (skill-creator for claude-code-engineer, mcp-server-dev for
  # llm-engineer/mcp-broker, math-olympiad for the mathematician). Only their descriptions sit in
  # context; the skills load when a task matches.
  if [ "$WITH_EXTRA_PLUGINS" = 1 ]; then
    extra_added=""; extra_failed=""
    for p in skill-creator mcp-server-dev math-olympiad; do
      if claude plugin install "$p@claude-plugins-official" --scope user >/dev/null 2>&1 </dev/null; then extra_added="$extra_added $p"; else extra_failed="$extra_failed $p"; fi
    done
    [ -n "$extra_added" ] && note "+ extra skill plugins:$extra_added"
    [ -n "$extra_failed" ] && note "! plugin install failed:$extra_failed (inside claude: /plugin install <name>@claude-plugins-official)"
  fi
else
  note "plugins skipped"
fi

say "11/11 Shell profile"
PROFILE_NOTE=""
if [ "$NO_PROFILE" = 1 ]; then
  note "--no-profile: leaving shell rc files alone"
else
  mkdir -p "$B/rc"
  # The previous profile line ({ set -a; . stack.env; set +a; }) exported EVERY variable of stack.env;
  # the new one exports only STACK_EXPORT. Variables of your own in stack.env stay exported.
  legacy_rc=""
  for rc in "$HOME/.zshrc" "$HOME/.bashrc"; do
    if grep -qE 'set -a.*stack\.env.*# claude-agent-stack[[:space:]]*$' "$rc" 2>/dev/null; then legacy_rc="$rc"; fi
  done
  if [ -n "$legacy_rc" ] && [ -f "$C/stack.env" ]; then
    python3 - "$HERE/stack.env.example" "$C/stack.env" "$SRC/bin/mcp-headers" "$SRC/bin/with-stack-env" <<'PY' || true
import os, re, runpy, sys
from pathlib import Path
example, target, parser, wse = sys.argv[1:5]
mh = runpy.run_path(parser, run_name="mcp_headers")
VAR = re.compile(r"^\s*(?:#\s?)?(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=")
stack_keys = {m.group(1) for m in map(VAR.match, open(example, encoding="utf-8").read().splitlines()) if m}
target = os.path.realpath(target)
text = open(target, encoding="utf-8", errors="surrogateescape").read()
vals = mh["read_env_file"](Path(target))
own = {k: v for k, v in vals.items() if v and k not in stack_keys and not k.startswith(("LUMENFALL_", "OPPER_", "OPENROUTER_", "IMAGE_STUDIO_", "LIBDOCS_"))}
mine = sorted(k for k, v in own.items() if "$" not in v)
expanding = sorted(k for k, v in own.items() if "$" in v)
if expanding:
    print("  note: %s use $VAR expansion, which the profile line doesn't do: set them in your shell rc file"
          % ", ".join(expanding))
if mine and not re.search(r"(?m)^\s*(?:export\s+)?STACK_EXPORT=", text):
    default = re.search(r'(?m)^DEFAULT_EXPORT="([^"]*)"', open(wse, encoding="utf-8").read()).group(1)
    block = ("\n# added by install.sh: your previous profile line exported every variable in this file;\n"
             "# these of your own stay exported (the stack's API keys no longer are)\n"
             'STACK_EXPORT="%s %s"\n' % (default, " ".join(mine)))
    fd = os.open(target + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape") as f:
        f.write(text + ("" if text.endswith("\n") or not text else "\n") + block)
    os.replace(target + ".tmp", target)
    print("  stack.env: STACK_EXPORT keeps exporting your own variables: " + ", ".join(mine))
gone = [k for k in ("OPPER_API_KEY", "OPENROUTER_API_KEY", "EXA_API_KEY", "JINA_API_KEY", "SPIDER_API_KEY")
        if vals.get(k)]
if gone:
    print("  note: no longer exported to your shells: %s (the MCP servers read stack.env themselves)" % ", ".join(gone))
PY
  fi
  # Exports only the NON-EMPTY keys (an empty KEY= must not blank a token exported earlier in the
  # rc file) and parses stack.env exactly like with-stack-env/mcp-headers.
  LINE="[ -x \"$C/bin/with-stack-env\" ] && eval \"\$(\"$C/bin/with-stack-env\" --print-env sh)\"  # claude-agent-stack"
  for rc in "$HOME/.zshrc" "$HOME/.bashrc"; do
    if [ -f "$rc" ] || { [ "$rc" = "$HOME/.zshrc" ] && [ "$OS" = "Darwin" ]; }; then
      [ -f "$rc" ] && cp -p "$rc" "$B/rc/$(basename "$rc")"
      # Only the line this installer wrote (it ENDS with the marker) is replaced — never other lines
      # that merely mention claude-agent-stack (an alias or PATH entry for this repo, say).
      set +e
      python3 - "$rc" "$LINE" <<'PY'
import os, sys
rc, line = sys.argv[1], sys.argv[2]
try:
    text = open(rc, encoding="utf-8", errors="surrogateescape").read()
except FileNotFoundError:
    text = ""
def ours(l):
    s = l.rstrip("\r\n").rstrip()
    return s.endswith("# claude-agent-stack") and ("stack.env" in s or "with-stack-env" in s)
out, placed = [], False
for l in text.splitlines(keepends=True):
    if ours(l):
        if not placed:
            out.append(line + "\n")
            placed = True
        continue
    out.append(l)
if not placed:
    if text and not text.endswith("\n"):
        out.append("\n")
    out.append("\n" + line + "\n")
new = "".join(out)
if new == text:
    sys.exit(3)
with open(os.path.realpath(rc), "w", encoding="utf-8", errors="surrogateescape") as f:
    f.write(new)
PY
      st=$?
      set -e
      case "$st" in
        0) note "+ $rc sources stack.env (previous copy: $B/rc/)" ;;
        3) note "= $rc already sources stack.env" ;;
        *) note "! could not update $rc — add this line yourself: $LINE" ;;
      esac
    fi
  done
  # claude-ninja / claude-god: ninja-coder or god-coder as the main thread at ultracode, the only
  # place ultracode runs (an agent file's effort reaches subagents only, and they can't run workflows).
  mkdir -p "$HOME/.local/bin"
  for n in claude-ninja claude-god; do
    l="$HOME/.local/bin/$n"
    if [ "$(readlink "$l" 2>/dev/null)" = "$C/bin/claude-ultracode" ]; then
      note "= $n (ultracode launcher)"
    elif [ ! -e "$l" ] && [ ! -L "$l" ]; then
      ln -s "$C/bin/claude-ultracode" "$l" && note "+ $l: ${n#claude-}-coder as the main thread at ultracode"
    else
      note "! $l exists and isn't the stack's: left alone ($C/bin/claude-ultracode ${n#claude-}-coder does the same)"
    fi
  done
  case "$(basename "${SHELL:-}")" in
    zsh|bash|"") ;;
    *) PROFILE_NOTE="your login shell is $SHELL: export the keys of $C/stack.env there yourself" ;;
  esac
fi

# Earlier image servers are retired: images now come from image-studio (SVG and edits through
# OpenRouter, photos and rasters through Opper). An old server stays while an agent file you edited
# (kept, the stack's version waiting as .new) still starts it.
for old in opper_image_mcp.py openrouter_image_mcp.py; do
  [ -f "$C/mcp/$old" ] || continue
  if grep -lq "$old" "$C"/agents/*.md 2>/dev/null; then
    note "! kept mcp/$old: $(grep -l "$old" "$C"/agents/*.md | xargs -n1 basename | tr '\n' ' ')still use it — merge their .new versions"
  else
    mkdir -p "$B/retired/mcp" && mv "$C/mcp/$old" "$B/retired/mcp/" \
      && note "retired mcp/$old: images now come from image-studio (old copy: $B/retired/mcp/)"
  fi
done

# A run that changed nothing leaves a backup identical to an earlier one: keep just that one.
same_b=""; n_b=0
for d in "$C"/backup-*; do
  [ -d "$d" ] || continue
  n_b=$((n_b + 1))
  if [ -z "$same_b" ] && [ "$d" != "$B" ] && diff -r "$B" "$d" >/dev/null 2>&1; then same_b="$d"; fi
done
if [ -n "$same_b" ]; then
  case "$B" in "$C"/backup-*) rm -rf "$B"; n_b=$((n_b - 1)); note "backup: identical to $same_b (nothing changed; no duplicate kept)"; B="$same_b" ;; esac
fi
if rmdir "$B" 2>/dev/null; then n_b=$((n_b - 1)); note "backup: nothing existed to back up (first install)"; fi
[ "$n_b" -gt 10 ] && note "$n_b backup folders in $C (backup-*): delete the old ones you no longer need"
case ":$ORIG_PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) [ "$NO_PROFILE" = 1 ] && note "! ~/.local/bin is not on your PATH (uv, magg, huetension, language servers): add it to your shell profile" ;;
esac

say "Done. Next:"
[ -n "$PROFILE_NOTE" ] && note "! $PROFILE_NOTE"
pending="$( (cd "$C" && find agents rules skills -name '*.new' -type f 2>/dev/null) | sort || true)"
if [ -n "$pending" ]; then
  note "! You edited these files, so they were kept; the stack's new versions wait next to them."
  note "  Merge each (diff -u <file> <file>.new), then delete the .new — or rerun with --force:"
  printf '%s\n' "$pending" | sed "s|^|      $C/|"
fi
cat <<EOF
  1. Put your API keys in $C/stack.env: OPENROUTER (SVG and image edits), OPPER (photos and
     raster images) — uncomment the lines an upgrade appended; EXA (keyless works, rate-limited),
     JINA (needed for read_url/search_arxiv/PDF tools), SPIDER (crawls), HF_TOKEN and WANDB
     (optional). The image model of each tool is set there too (IMAGE_STUDIO_SVG_MODEL, _IMAGE_MODEL,
     _EDIT_MODEL; /stack-doctor checks them).
     MCP servers read that file at connect time — no reinstall needed (except the first time you add
     WANDB_API_KEY: rerun ./install.sh $ORIG_ARGS). Open a new terminal so CLI tools see them too.
  2. Start: claude        (main thread = router; the status line shows context vs the 800K window —
     auto-compact fires at ≈767K). Claude Desktop's Code tab, Conductor, VS Code and Zed load the same
     setup (README → Apps). A plain session without the router: claude --agent claude.
     Inside: /stack-doctor   (health check)   /mcp   (server status; no sign-in needed with keys)
     Once, in that first session: /effort low — the router runs at the session's level (saved for
     Sonnet 5); an agent file's effort applies only to subagents.
     Hardest problems at ultracode, as a session of their own: claude-ninja, or claude-god
     (dispatched by the router they run at max: ultracode exists only on a main thread).
EOF
cat <<EOF
  3. macOS computer use (designer, motion-designer, doc-specialist, verifier):
     /mcp → computer-use → Enable  (once per project), then grant Accessibility + Screen Recording.
  4. Browser agent with your logins: start with  claude --chrome  (or /chrome → Enabled by default).
  5. Optional: ./install.sh --with-ml (shared ML venv) · --with-lsp (language servers) · --with-adobe
     · --with-extra-plugins (skill-creator, mcp-server-dev, math-olympiad skills)
EOF
