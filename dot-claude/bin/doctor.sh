#!/usr/bin/env bash
# Health check for the Claude Code multi-agent stack. Read-only: never prints key values.
C="$(cd "$(dirname "$0")/.." && pwd)"
SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
# /stack-doctor runs this as a hook, outside the sandbox, in the session's directory (any project an
# agent can write): nothing below may load code from there (security audit, CWE-427). So: it runs
# in the config dir (agents can't write it; `"$HPY" -` puts the cwd on sys.path), and every python3
# is isolated (-I: no cwd or script dir on sys.path, no PYTHON* variables; no bytecode read or
# written). The stack-python calls run hooks from $C/hooks, which agents can't write either.
cd "$C" || exit 2
python3(){ command python3 -I -B -X pycache_prefix=/dev/null/claude-agent-stack-no-bytecode "$@"; }
ok(){ printf '  ok    %s\n' "$*"; }
warn(){ printf '  WARN  %s\n' "$*"; }
fail(){ printf '  FAIL  %s\n' "$*"; }
have(){ command -v "$1" >/dev/null 2>&1; }
if have timeout; then T="timeout 90"; elif have gtimeout; then T="gtimeout 90"; else T=""; fi
MIN=2.1.271
# The models the soft token limits (hooks/agent_guard.py SOFT_LIMITS, SOFT_PROMPT_CTX) and the agents'
# maxTurns were measured on, per alias: the transcripts of 2026-10-02 (tests/derive_thresholds.py in
# the stack repo). "== Settings" warns when an alias resolves to another model: re-derive, then update.
MEASURED_MODELS="opus=claude-opus-5-5 sonnet=claude-sonnet-5-5"
# portable "a <= b" for dotted versions (BSD sort on older macOS has no -V)
version_ge(){ [ "$(printf '%s\n%s\n' "$2" "$1" | sort -t. -k1,1n -k2,2n -k3,3n | head -n1)" = "$2" ]; }

# /stack-doctor = `doctor.sh --hook`, settings.json's UserPromptExpansion hook (matcher stack-doctor).
# A hook runs outside the Bash sandbox, so stack.env, ~/.claude.json, the state dir and the network
# read as they are (an agent's sandboxed Bash gets false FAILs there), and BlackCat needs no Bash.
# The report is the block reason the user sees: FAIL lines, WARN lines, the ok count; no model turn.
# Claude Code drops a hook's output at its timeout (180 s) and stock macOS has no timeout(1), so the
# run is stopped after STACK_DOCTOR_HOOK_BUDGET seconds (default 150) and reported as unfinished.
if [ "${1:-}" = "--hook" ]; then
  [ -t 0 ] || cat >/dev/null    # the event on stdin; the matcher already chose the command
  budget="${STACK_DOCTOR_HOOK_BUDGET:-150}"; case "$budget" in ''|*[!0-9]*) budget=150 ;; esac
  out=$(mktemp "${TMPDIR:-/tmp}/stack-doctor.XXXXXX") || { echo "stack-doctor: mktemp failed — run: bash \"$SELF\"" >&2; exit 2; }
  bash "$SELF" </dev/null >"$out" 2>&1 & pid=$!
  n=0; while kill -0 "$pid" 2>/dev/null && [ "$n" -lt "$budget" ]; do sleep 1; n=$((n + 1)); done
  stopped=0
  if kill -0 "$pid" 2>/dev/null; then    # wait reaps it quietly (no "Terminated" job line in the reason)
    stopped=1; { pkill -TERM -P "$pid"; kill -TERM "$pid" && wait "$pid"; } 2>/dev/null
  fi
  awk -v full="bash \"$SELF\"" -v stopped="$stopped" -v budget="$budget" '
    /^== / { sec = substr($0, 4); sub(/ \(.*/, "", sec); seen[++ns] = sec; next }
    /^  FAIL  / { f[++nf] = "FAIL  [" (sec == "" ? "Setup" : sec) "] " substr($0, 9); bad[sec] = 1; next }
    /^  WARN  / { w[++nw] = "WARN  [" (sec == "" ? "Setup" : sec) "] " substr($0, 9); bad[sec] = 1; next }
    /^  ok    / { ok++; next }
    /^done\.$/ { done = 1 }
    END {
      if (!done) { f[++nf] = "FAIL  [" (sec == "" ? "Setup" : sec) "] doctor.sh did not finish (" \
                     (stopped ? "stopped after " budget " s: a check hung" : "it exited early") "): run " full; bad[sec] = 1 }
      printf "stack-doctor: %d FAIL, %d WARN, %d ok (doctor.sh, run outside the sandbox)\n", nf, nw, ok
      for (i = 1; i <= nf; i++) print f[i]
      for (i = 1; i <= nw; i++) print w[i]
      clean = ""; for (i = 1; i <= ns; i++) if (!(seen[i] in bad)) clean = clean (clean == "" ? "" : ", ") seen[i]
      print "healthy: " (clean == "" ? "no section without findings" : clean)
      print "full report: " full
    }' "$out" >&2
  rm -f "$out"
  exit 2                       # UserPromptExpansion: exit 2 blocks the expansion, stderr is the reason
fi

if [ -n "${CLAUDE_CONFIG_DIR:-}" ] && [ "$(cd "$CLAUDE_CONFIG_DIR" 2>/dev/null && pwd)" != "$C" ]; then
  warn "CLAUDE_CONFIG_DIR=$CLAUDE_CONFIG_DIR differs from this script's install dir ($C) — checking $C"
elif [ -z "${CLAUDE_CONFIG_DIR:-}" ] && [ "$(cd "$C" && pwd -P)" != "$(cd "$HOME/.claude" 2>/dev/null && pwd -P)" ]; then
  # an install made with ./install.sh --config-dir: Claude Code reads it only with the variable exported
  warn "this install is in $C, not ~/.claude, and CLAUDE_CONFIG_DIR is unset: Claude Code won't read it — export CLAUDE_CONFIG_DIR='$C' in your shell profile (~/.zshrc; bash: ~/.bash_profile)"
fi

echo "== Claude Code"
if have claude; then
  v=$(claude --version 2>/dev/null </dev/null | awk '{print $1}')
  if [ -n "$v" ] && version_ge "$v" "$MIN"; then ok "claude $v"; else warn "claude ${v:-?} < $MIN — run: claude update"; fi
else fail "claude not found — install: curl -fsSL https://claude.ai/install.sh | bash"; fi

echo "== Binaries"
# Agents' Bash calls use bare names (uv run, uvx semgrep, node, git): those must be on this PATH —
# run from /stack-doctor (a hook) it is the PATH of Claude Code's process. MCP commands are the absolute paths
# rendered at install time (often ~/.local/bin), so magg and huetension only need to exist.
found(){ have "$1" || [ -x "$HOME/.local/bin/$1" ]; }
for b in python3 uv uvx node npx git; do
  if have "$b"; then ok "$b"
  elif [ -x "$HOME/.local/bin/$b" ]; then
    warn "$b is only in ~/.local/bin, which is not on PATH: agents' Bash can't run it — open a new terminal (the stack's profile line adds it) or add ~/.local/bin to PATH"
  else fail "$b missing"; fi
done
found magg && ok "magg" || fail "magg missing — uv tool install magg"
found huetension && ok "huetension" || warn "huetension missing (designer color tools) — rerun install.sh"
for b in ffmpeg magick rsvg-convert pdftoppm; do have "$b" && ok "$b" || warn "$b missing (optional; brew install ffmpeg imagemagick librsvg poppler)"; done
[ -x "$C/venvs/sci/bin/python" ] && ok "sci venv" || fail "sci venv missing — rerun install.sh"
if [ ! -x "$C/venvs/tools/bin/python" ]; then fail "tools venv missing — rerun install.sh"
elif "$C/venvs/tools/bin/python" -c 'import pytest, numpy, pandas, httpx, mcp, PIL, neural_memory' >/dev/null 2>&1; then ok "tools venv (imports ok; full suite: $C/venvs/tools/bin/python -m pytest -q tests/)"
else fail "tools venv imports fail — rerun install.sh"; fi
[ -x "$C/venvs/ml/bin/python" ] && ok "ML venv ($C/venvs/ml)" || ok "ML venv not installed (optional: ./install.sh --with-ml)"
for f in with-stack-env mcp-headers magg-private claude-ultracode; do [ -x "$C/bin/$f" ] && ok "bin/$f" || fail "bin/$f missing or not executable — rerun install.sh"; done
for n in claude-ninja; do
  if [ "$(readlink "$HOME/.local/bin/$n" 2>/dev/null)" = "$C/bin/claude-ultracode" ]; then
    have "$n" && ok "$n (${n#claude-}-coder at ultracode)" || warn "$n is in ~/.local/bin, which isn't on PATH — open a new terminal"
  else
    warn "$n missing: rerun install.sh (without --no-profile), or use $C/bin/claude-ultracode ${n#claude-}-coder"
  fi
done
[ "$(readlink "$HOME/.local/bin/claude-supreme" 2>/dev/null)" = "$C/bin/claude-ultracode" ] \
  && warn "~/.local/bin/claude-supreme starts a retired agent: rm ~/.local/bin/claude-supreme (ninja-coder is the top tier: claude-ninja)"
for f in image_studio_mcp.py libdocs_mcp.py neural_memory_mcp.py; do [ -f "$C/mcp/$f" ] && ok "mcp/$f" || fail "mcp/$f missing — rerun install.sh"; done
if have node; then
  node -e 'const [a, b] = process.versions.node.split(".").map(Number); process.exit(a > 22 || (a === 22 && b >= 5) ? 0 : 1)' 2>/dev/null \
    && ok "node $(node --version) (context-mode needs >= 22.5)" \
    || warn "node $(node --version) < 22.5: context-mode (researcher, doc-specialist) won't start — brew upgrade node / nvm install 22"
fi
# The agents' and the magg catalog's MCP commands are absolute paths frozen at install time (e.g.
# nvm's ~/.nvm/versions/node/vXX/bin/npx): they break silently after `nvm install/uninstall`.
# Scripts and config files in the args (a server's index.js, magg's config) must exist too.
python3 - "$C/agents" "$C/magg/config.json" <<'PY'
import glob, json, os, re, sys
bad = {}


def need(path, agent, executable):
    if path and path.startswith("/") and not (os.access(path, os.X_OK) if executable else os.path.exists(path)):
        bad.setdefault(path, []).append(agent)


for f in sorted(glob.glob(os.path.join(sys.argv[1], "*.md"))):
    fm = open(f, encoding="utf-8", errors="replace").read().split("---", 2)
    if len(fm) < 3:
        continue
    agent = os.path.basename(f)[:-3]
    for m in re.finditer(r'(?m)^\s+command:\s*"([^"]+)"\s*\n(?:\s+args:\s*(\[.*\])\s*$)?', fm[1]):
        cmd = m.group(1)
        try:
            args = [a for a in json.loads(m.group(2) or "[]") if isinstance(a, str)]
        except ValueError:
            args = []
        if cmd.endswith("/with-stack-env"):            # with-stack-env [--only KEYS] CMD ARGS...
            need(cmd, agent, True)
            if args[:1] == ["--only"]:
                args = args[2:]
            cmd, args = (args[0], args[1:]) if args else ("", [])
        if cmd.endswith("/magg-private"):              # magg-private MAGG ARGS...
            need(cmd, agent, True)
            cmd, args = (args[0], args[1:]) if args else ("", [])
        need(cmd, agent, True)
        for a in args:
            need(a, agent, False)
try:
    catalog = json.load(open(sys.argv[2])).get("servers", {})
except (OSError, ValueError):
    catalog = {}
cargo_cmd = {}      # catalog command path -> the pinned "cargo install X@V --locked" in its notes
for name, entry in sorted(catalog.items()):
    if isinstance(entry, dict) and isinstance(entry.get("command"), str):
        need(entry["command"], "magg catalog: " + name, True)
        m = re.search(r"cargo install \S+@\S+ --locked", str(entry.get("notes", "")))
        if m:
            cargo_cmd[entry["command"]] = m.group(0)
for path, agents in sorted(bad.items()):
    # designer works without huetension; a path only magg catalog entries use is disabled until
    # mcp-broker mounts it (serial: install.sh builds it only when cargo is present)
    catalog_only = all(a.startswith("magg catalog: ") for a in agents)
    level = "WARN" if path.endswith("/huetension") or catalog_only else "FAIL"
    if catalog_only and path in cargo_cmd:
        hint = "rerun ./install.sh with cargo on PATH, or run: %s" % cargo_cmd[path]
    elif catalog_only:
        hint = "install it per its notes in magg/config.json, or rerun ./install.sh if the path is stale"
    else:
        hint = "rerun ./install.sh to re-render"
    print("  %s  %s missing — MCP server of %s won't start (%s)"
          % (level, path, ", ".join(agents) if len(agents) <= 3 else "%d agents" % len(agents), hint))
if not bad:
    print("  ok    agent MCP command paths and scripts exist")
PY

echo "== Keys ($C/stack.env)"
if [ -f "$C/stack.env" ]; then
  perm=$(stat -L -c %a "$C/stack.env" 2>/dev/null || stat -L -f %Lp "$C/stack.env" 2>/dev/null)
  [ "$perm" = "600" ] && ok "permissions 600" || warn "permissions $perm — chmod 600 $C/stack.env"
  # Parse the file the way the MCP side does (with-stack-env, every key), so "set" means usable.
  parsed=$(STACK_EXPORT=all "$C/bin/with-stack-env" --print-env sh 2>/dev/null)
  for k in OPENROUTER_API_KEY OPPER_API_KEY EXA_API_KEY JINA_API_KEY SPIDER_API_KEY HF_TOKEN WANDB_API_KEY; do
    raw=$(grep -E "^[[:space:]]*(export[[:space:]]+)?$k=" "$C/stack.env" | tail -n1 | cut -d= -f2-)
    case "$k" in EXA_API_KEY) srv=exa;; JINA_API_KEY) srv=jina;; HF_TOKEN) srv=huggingface;; WANDB_API_KEY) srv=wandb;; *) srv="";; esac
    usable=0
    if [ -n "$srv" ]; then   # remote servers: what the headersHelper would really send
      [ "$("$C/bin/mcp-headers" "$srv" 2>/dev/null)" != "{}" ] && usable=1
    elif printf '%s\n' "$parsed" | grep -q "^export $k="; then
      usable=1
    fi
    if [ "$usable" = 1 ]; then
      ok "$k set"
    elif [ -n "$raw" ]; then
      warn "$k has a value the MCP helpers cannot use (quotes, spaces or an unexpanded \$VAR?) — fix it in $C/stack.env"
    else
      case "$k" in
        OPENROUTER_API_KEY) warn "$k empty — generate_svg and edit_image (image-studio: SVG, image edits and composites) fail until it is set" ;;
        OPPER_API_KEY) warn "$k empty — generate_image (image-studio: photos and raster images) fails until it is set" ;;
        JINA_API_KEY) warn "$k empty — jina's read_url, search_arxiv, extract_pdf and screenshots refuse without it (agents fall back to WebFetch)" ;;
        EXA_API_KEY) ok "$k empty (optional: exa works keyless, rate-limited)" ;;
        SPIDER_API_KEY) ok "$k empty (optional: only researcher's spider crawler needs it)" ;;
        *) ok "$k empty (optional)" ;;
      esac
    fi
  done
  # The profile line exports only the STACK_EXPORT keys, for CLI tools (hf, wandb, gh, mlflow);
  # MCP servers read stack.env themselves.
  unexported=""
  exported=$("$C/bin/with-stack-env" --print-env sh 2>/dev/null)
  for k in $(printf '%s\n' "$exported" | sed -n 's/^export \([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p'); do
    [ "$k" = PATH ] && continue
    eval "cur=\${$k:-}"; [ -n "$cur" ] || unexported="$unexported $k"
  done
  [ -z "$unexported" ] && ok "CLI keys (STACK_EXPORT) exported in this shell" \
    || warn "not exported in this shell:$unexported — open a new terminal (only CLI tools need these; MCP servers read stack.env)"
  own=""
  for k in $(printf '%s\n' "$parsed" | sed -n 's/^export \([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p'); do
    case "$k" in
      PATH|STACK_EXPORT|OPPER_*|OPENROUTER_*|IMAGE_STUDIO_*|LIBDOCS_*|EXA_API_KEY|JINA_API_KEY|SPIDER_API_KEY|GITHUB_TOKEN|HF_TOKEN|WANDB_API_KEY) ;;
      LUMENFALL_*) ;;  # image-studio's check below flags it
      JUPYTER_URL|JUPYTER_TOKEN|MLFLOW_TRACKING_URI|MOTHERDUCK_TOKEN|LEAN_PROJECT_PATH|MDB_MCP_CONNECTION_STRING|DATABASE_URI|QISKIT_IBM_TOKEN|GODOT_PATH|SEC_EDGAR_USER_AGENT|GRAFANA_URL|GRAFANA_SERVICE_ACCOUNT_TOKEN|NCBI_API_KEY) ;;
      *) printf '%s\n' "$exported" | grep -q "^export $k=" || own="$own $k" ;;
    esac
  done
  [ -z "$own" ] || ok "your own stack.env variables not exported to shells:$own (add them to STACK_EXPORT if a CLI tool needs them)"
  expanding=""
  for k in $(grep -E '^[[:space:]]*(export[[:space:]]+)?[A-Za-z_][A-Za-z0-9_]*=.*[$]' "$C/stack.env" 2>/dev/null \
      | sed -E 's/^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)=.*/\2/'); do
    case "$k" in
      LUMENFALL_*|OPPER_*|OPENROUTER_*|IMAGE_STUDIO_*|LIBDOCS_*|GITHUB_TOKEN|EXA_API_KEY|JINA_API_KEY|SPIDER_API_KEY|HF_TOKEN|WANDB_API_KEY) ;;  # expanded by the stack's Python servers, or checked above
      JUPYTER_URL|JUPYTER_TOKEN|MLFLOW_TRACKING_URI|MOTHERDUCK_TOKEN|LEAN_PROJECT_PATH|MDB_MCP_CONNECTION_STRING|DATABASE_URI|QISKIT_IBM_TOKEN|GODOT_PATH|SEC_EDGAR_USER_AGENT|GRAFANA_URL|GRAFANA_SERVICE_ACCOUNT_TOKEN|NCBI_API_KEY)
        warn "$k uses \$VAR, which with-stack-env doesn't expand, so magg never gets it: write the value out in $C/stack.env" ;;
      *) expanding="$expanding $k" ;;
    esac
  done
  [ -z "$expanding" ] || ok "never exported to shells (values with \$VAR aren't expanded):$expanding — set them in your shell rc file if a CLI tool needs them"
else fail "missing $C/stack.env — cp <stack repo>/lib/stack.env.example $C/stack.env && chmod 600"; fi
if [ -x "$C/bin/mcp-headers" ]; then
  for s in exa jina huggingface wandb; do
    out=$("$C/bin/mcp-headers" "$s" 2>/dev/null)
    if printf '%s' "$out" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert isinstance(d, dict); sys.exit(0 if d else 3)' 2>/dev/null; then
      ok "mcp-headers $s: key header provided"
    elif [ $? -eq 3 ]; then
      ok "mcp-headers $s: no key (anonymous access, or not used)"
    else
      fail "mcp-headers $s: output is not a JSON object"
    fi
  done
fi

CJ="${STACK_CLAUDE_JSON:-}"
if [ -z "$CJ" ]; then
  if [ -n "${CLAUDE_CONFIG_DIR:-}" ]; then CJ="$C/.claude.json"; else CJ="$HOME/.claude.json"; fi
fi
if [ -f "$CJ" ]; then
  perm=$(stat -L -c %a "$CJ" 2>/dev/null || stat -L -f %Lp "$CJ" 2>/dev/null)
  [ "$perm" = "600" ] && ok "$CJ permissions 600" || warn "$CJ permissions $perm — chmod 600 $CJ"
  python3 - "$CJ" <<'PY'
import json, sys
try:
    servers = json.load(open(sys.argv[1])).get("mcpServers", {})
except (OSError, ValueError):
    servers = {}
leaky = [n for n in ("exa", "jina", "huggingface", "wandb")
         if isinstance(servers.get(n), dict) and servers[n].get("headers")]
if leaky:
    print("  WARN  plaintext key headers in %s for: %s — rerun ./install.sh to move them to headersHelper"
          % (sys.argv[1], ", ".join(leaky)))
else:
    print("  ok    no plaintext keys in the stack's MCP entries")
PY
else
  warn "$CJ not found — MCP servers not yet registered (run ./install.sh)"
fi
# Sandboxed Bash gets its caches and the git credential reset from the session-env SessionStart
# hook ($CLAUDE_ENV_FILE, Bash only). In settings env they would reach MCP servers, hooks and
# language servers, which run outside the sandbox (R3-CACHES, R3-GITENV).
python3 - "$C/settings.json" <<'PY' | while IFS= read -r l; do case "$l" in "ok "*) ok "${l#ok }" ;; *) warn "$l" ;; esac; done
import glob, json, os, re, shlex, shutil, subprocess, sys, tempfile, time
try:
    s = json.load(open(sys.argv[1]))
except (OSError, ValueError):
    s = {}
MARK = "claude-agent-stack: sandboxed Bash caches"
env = s.get("env") if isinstance(s.get("env"), dict) else {}
moved = sorted(k for k in env if k in ("UV_CACHE_DIR", "npm_config_cache", "PRE_COMMIT_HOME",
                                       "XDG_CACHE_HOME", "CARGO_HOME", "GIT_CONFIG_COUNT",
                                       "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0", "GIT_CONFIG_PARAMETERS"))
if moved:
    print("settings.json env sets %s: that reaches unsandboxed processes; the session-env hook "
          "sets them for Bash only (rerun ./install.sh)" % ", ".join(moved))
hooks = s.get("hooks") if isinstance(s.get("hooks"), dict) else {}
wired = any(isinstance(g, dict) and not g.get("matcher") and any(
    isinstance(h, dict) and re.search(r'agent_guard(\.py")? session-env$', str(h.get("command", "")))
    for h in g.get("hooks") or []) for g in hooks.get("SessionStart") or [])
allow = ((s.get("sandbox") or {}).get("filesystem") or {}).get("allowWrite") or []
if wired:
    print("ok sandboxed Bash env: session-env SessionStart hook wired (every source)")
    # run it as Claude Code would, against a throwaway CLAUDE_ENV_FILE, HOME and state dir
    cmd = next(str(h.get("command")) for g in hooks.get("SessionStart") or [] if isinstance(g, dict)
               and not g.get("matcher") for h in g.get("hooks") or [] if isinstance(h, dict)
               and re.search(r'agent_guard(\.py")? session-env$', str(h.get("command", ""))))
    tmp = tempfile.mkdtemp(prefix="stack-doctor-env-")
    try:
        envf = os.path.join(tmp, "env.sh")
        env = dict(os.environ, HOME=tmp, CLAUDE_ENV_FILE=envf, XDG_STATE_HOME=os.path.join(tmp, "st"))
        r = subprocess.run(shlex.split(cmd), input='{"session_id": "doctor-probe", "source": "startup"}',
                           env=env, capture_output=True, text=True, timeout=20)
        got = open(envf).read() if os.path.exists(envf) else ""
        if r.returncode == 0 and MARK in got:
            print("ok session-env hook writes the sandbox env (probe in a temp dir)")
        else:
            print("the session-env hook fails (probe in a temp dir, rc %d): %s"
                  % (r.returncode, (r.stderr.strip().splitlines() or ["no output"])[-1][:200]))
    except (OSError, ValueError, subprocess.SubprocessError, StopIteration) as exc:
        print("couldn't probe the session-env hook (%s)" % type(exc).__name__)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    # what it did in the latest sessions (agent_guard.py records it in each session's state dir)
    root = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                        "claude-agent-stack")
    seen = []
    for f in glob.glob(os.path.join(root, "*", "session-env.json")):
        try:
            st = json.load(open(f))
        except (OSError, ValueError):
            continue
        if isinstance(st, dict) and isinstance(st.get("ts"), (int, float)):
            seen.append((st["ts"], os.path.basename(os.path.dirname(f)), st))
    seen.sort(reverse=True)
    bad = [(sid, st) for ts, sid, st in seen[:10] if st.get("state") == "failed"
           or (st.get("state") == "running" and time.time() - ts > 30)]
    if bad:
        sid, st = bad[0]
        print("session-env failed in %d of the last %d sessions (latest %s: %s): their Bash had no "
              "sandbox caches and git credential helpers on" % (len(bad), min(len(seen), 10), sid[:8],
                                                                st.get("reason") or "did not finish"))
    elif seen:
        print("ok session-env set the sandbox env in the last %d sessions" % min(len(seen), 10))
    else:
        print("ok session-env: no session has recorded it yet (sessions since this install do)")
else:
    print("no session-env SessionStart hook for every source: sandboxed Bash has no writable caches "
          "and git credential helpers stay on (rerun ./install.sh)")
wide = [p for p in ("~/.cache", "~/Library/Caches") if p in allow]
if wide:
    print("sandbox.filesystem.allowWrite has %s: unsandboxed tools load code from there"
          % ", ".join(wide))
PY

echo "== Image models (image-studio; set in $C/stack.env)"
# The server's own check: each tool's model looked up in its provider's catalog (no paid call).
uvb=$(command -v uv 2>/dev/null || { [ -x "$HOME/.local/bin/uv" ] && echo "$HOME/.local/bin/uv"; })
if [ -z "$uvb" ] || [ ! -f "$C/mcp/image_studio_mcp.py" ]; then
  warn "image models not checked (needs uv and $C/mcp/image_studio_mcp.py)"
else
  out=$($T "$uvb" run --quiet --script "$C/mcp/image_studio_mcp.py" --check 2>&1 </dev/null)
  if printf '%s\n' "$out" | grep -qE '^  (ok|WARN|FAIL)  '; then
    printf '%s\n' "$out" | grep -E '^  (ok|WARN|FAIL)  '
  else
    warn "image models not checked: image-studio didn't start ($(printf '%s\n' "$out" | tail -n1 | cut -c1-160))"
  fi
fi

# the hook scripts run on bin/stack-python (Python >= 3.13); checked under == Hooks
HPY="$C/bin/stack-python"
"$HPY" -c 'import sys; sys.exit(sys.version_info < (3, 13))' >/dev/null 2>&1 </dev/null || HPY=python3
echo "== Agents"
policy_json=$("$HPY" "$C/hooks/agent_guard.py" --print-policy 2>/dev/null || true)
if [ -z "$policy_json" ]; then
  fail "agent_guard.py --print-policy failed — rerun install.sh"
else
  python3 - "$policy_json" "$C/agents" <<'PY'
import json, os, sys
p = json.loads(sys.argv[1])
d = sys.argv[2]
agents = p.get("agents", [])
missing = [a for a in agents if not os.path.isfile(os.path.join(d, a + ".md"))]
extra = sorted(f[:-3] for f in os.listdir(d) if f.endswith(".md") and f[:-3] not in agents) if os.path.isdir(d) else []
if missing:
    print("  FAIL  missing agent files: " + " ".join(missing))
else:
    print("  ok    %d/%d agent files present (BlackCat + %d specialists)"
          % (len(agents), len(agents), len(agents) - 1))
if extra:
    print("  WARN  your own agents, unreachable from BlackCat and the stack's agents (the spawn policy"
          " lists only the stack's): %s — run one with `claude --agent <name>`" % " ".join(extra))
PY
fi
[ -f "$C/rules/claude-agent-stack.md" ] && ok "global rules: rules/claude-agent-stack.md" \
  || fail "rules/claude-agent-stack.md missing — the agents run without the stack's rules: rerun install.sh"

echo "== Hooks"
# The hooks' interpreter: every hook runs /bin/sh bin/stack-hook, which runs hooks/stack_hook.py on
# $STACK_PYTHON, bin/stack-python (installer's link to uv's managed 3.13) or `uv python find 3.13`;
# the PreToolUse guard entries fail closed when none starts (every tool call denied).
SP="$C/bin/stack-python"
if [ ! -L "$SP" ] && [ ! -e "$SP" ]; then
  fail "bin/stack-python missing: each hook call searches uv for Python 3.13 (slow) or blocks — rerun install.sh"
elif ! spv=$("$SP" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3]); sys.exit(sys.version_info < (3, 13))' 2>/dev/null </dev/null); then
  fail "bin/stack-python -> $(readlink "$SP" 2>/dev/null || echo '?') is not a working Python >= 3.13${spv:+ (it runs $spv)} — rerun install.sh (it installs 3.13 with uv)"
else
  ok "bin/stack-python -> $(readlink "$SP" 2>/dev/null || echo "$SP") (Python $spv)"
fi
if [ -n "${STACK_PYTHON:-}" ] && ! "$STACK_PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 13))' >/dev/null 2>&1 </dev/null; then
  fail "STACK_PYTHON=$STACK_PYTHON in this environment wins over bin/stack-python but is not a working Python >= 3.13: the fail-closed hooks deny every tool call — unset it"
fi
# bytecode (checked before the smoke test below, which rewrites a stale pyc): install.sh compiles
# the hook modules (timestamp pycs in hooks/__pycache__); missing or stale costs a recompile per
# call until the stub rewrites it (it does on the first call that can write there)
"$HPY" - "$C/hooks" <<'PY' | while IFS= read -r l; do case "$l" in "ok "*) ok "${l#ok }" ;; *) warn "$l" ;; esac; done
import importlib.util, os, sys
sys.pycache_prefix = None
h, stale = sys.argv[1], []
for m in ("agent_guard", "stack_hook", "stack_usage", "stack_limits", "stack_report", "read_gate", "web_caps"):
    src = os.path.join(h, m + ".py")
    if not os.path.isfile(src):
        continue
    try:
        with open(importlib.util.cache_from_source(src), "rb") as f:
            head = f.read(16)
        st = os.stat(src)
        fresh = (head[:4] == importlib.util.MAGIC_NUMBER and int.from_bytes(head[4:8], "little") == 0
                 and int.from_bytes(head[8:12], "little") == int(st.st_mtime) & 0xFFFFFFFF
                 and int.from_bytes(head[12:16], "little") == st.st_size & 0xFFFFFFFF)
    except OSError:
        fresh = False
    if not fresh:
        stale.append(m)
if stale:
    print("hook bytecode missing or stale for %s (%s): the hooks recompile until it is rewritten — rerun install.sh"
          % (", ".join(stale), sys.implementation.cache_tag))
else:
    print("ok hook bytecode fresh (timestamp pycs, %s) for the guard and the hook modules" % sys.implementation.cache_tag)
PY
if [ -f "$C/bin/stack-hook" ] && [ -f "$C/hooks/stack_hook.py" ]; then
  ok "bin/stack-hook and hooks/stack_hook.py (the hook launcher and entry)"
  # smoke test, as a session runs it: a Read through the fail-closed budget entry must be allowed (a
  # broken interpreter or stub denies everything, which the deny probes below cannot tell apart)
  sm_dir="$(mktemp -d "${TMPDIR:-/tmp}/stack-doctor-smoke.XXXXXX")"
  sm_out=$(cd "$sm_dir" && printf '{"hook_event_name":"PreToolUse","session_id":"doctor-smoke","tool_name":"Read","tool_input":{"file_path":"%s/a.py"},"tool_use_id":"tu-doctor-smoke","cwd":"%s"}' "$sm_dir" "$sm_dir" \
    | env -u STACK_POLICY CLAUDE_CONFIG_DIR="$C" XDG_STATE_HOME="$sm_dir/state" STACK_USAGE_COLLECT=0 \
      /bin/sh "$C/bin/stack-hook" --fail-closed agent_guard budget 2>"$sm_dir/err") && sm_rc=0 || sm_rc=$?
  if [ "$sm_rc" = 0 ] && ! printf '%s' "$sm_out" | grep -qE '"permissionDecision": *"(deny|ask)"'; then
    ok "hook launcher smoke test: a Read through stack-hook --fail-closed agent_guard budget is allowed"
  else
    fail "hook launcher smoke test failed (exit $sm_rc): $(printf '%s %s' "$sm_out" "$(cat "$sm_dir/err")" | tr '\n' ' ' | cut -c1-200) — rerun install.sh"
  fi
  rm -rf "$sm_dir"
else
  fail "bin/stack-hook or hooks/stack_hook.py missing: every hook command fails — rerun install.sh"
fi
[ -f "$C/hooks/agent_guard.py" ] && ok "hooks/agent_guard.py" || fail "hooks/agent_guard.py missing — rerun install.sh"
if [ -f "$C/hooks/agent_guard.py" ]; then
  if out=$("$HPY" "$C/hooks/agent_guard.py" --self-test 2>&1); then
    ok "agent_guard.py --self-test: $out"
  else
    fail "agent_guard.py --self-test failed: $out"
  fi
  # the token budgets read the session transcripts: FAIL when the newest one yields no usage
  if out=$(CLAUDE_CONFIG_DIR="$C" "$HPY" "$C/hooks/agent_guard.py" --check-budget 2>&1); then
    ok "token budgets: $out"
  else
    fail "token budgets count nothing — the transcript format changed: $out"
  fi
fi
# the usage collector and the scheduler model it refreshes (one line; it never blocks a session)
if [ -f "$C/hooks/stack_usage.py" ]; then
  if out=$("$HPY" "$C/hooks/stack_usage.py" status 2>&1); then ok "$out"; else warn "stack_usage.py status failed: $out"; fi
else
  warn "hooks/stack_usage.py missing (usage collector, scheduler model refresh) — rerun install.sh"
fi
# the learned limits (stack_limits.py; each session snapshots them at its start), the env overrides
# that pin one (origin env: it stops learning) and the scheduler policy recorded in the snapshots
if [ -f "$C/hooks/stack_limits.py" ]; then
  if out=$("$HPY" "$C/hooks/stack_limits.py" status 2>&1); then ok "$out"; else warn "stack_limits.py status failed: $out"; fi
  "$HPY" - "$C/hooks" "$C/settings.json" <<'PY' | while IFS= read -r l; do case "$l" in "ok "*) ok "${l#ok }" ;; *) warn "$l" ;; esac; done
import json, os, sys
sys.path.insert(0, sys.argv[1])
try:
    import stack_limits as L
    seed = L.load_seed()
except Exception as exc:  # noqa: BLE001 - one line, never a crash
    print(f"learned limits: stack_limits.py or its seed unusable ({type(exc).__name__}: {exc})")
    sys.exit(0)
try:
    env = json.load(open(sys.argv[2])).get("env") or {}
except (OSError, ValueError, AttributeError):
    env = {}
env = {k: str(v) for k, v in env.items()} if isinstance(env, dict) else {}
seen = []
for var in sorted(seed["vars"]):
    name = L.env_var(var)
    for where, src in (("settings.json env", env), ("this shell", os.environ)):
        if (src.get(name) or "").strip():
            seen.append(f"{name}={src[name].strip()[:20]} ({where}) pins {var}")
            break
if seen:
    print("learned limits: env overrides pin %d limit(s) at origin env, so they never learn: %s — remove "
          "them to let stack_limits.py learn (stack_limits.py show)" % (len(seen), "; ".join(seen[:6])
                                                                         + (" …" if len(seen) > 6 else "")))
else:
    print("ok learned limits: no env override pins a limit")
raw = (env.get("STACK_SCHED_POLICY") or os.environ.get("STACK_SCHED_POLICY") or "").strip().lower()
policy = raw if raw in L.SCHED_POLICIES else L.SCHED_POLICY_DEFAULT
note = "" if not raw or raw in L.SCHED_POLICIES else f" ({raw[:20]!r} is not one of {', '.join(L.SCHED_POLICIES)})"
print(f"ok scheduler policy: {policy}{note} (STACK_SCHED_POLICY; report = the scheduler only reports (default), "
      "fresh_fixer = opt-in, `stack_sched.py next` also advises a fresh fixer after a long resume gap)")
PY
else
  warn "hooks/stack_limits.py missing (learned limits: the guard uses its built-in values) — rerun install.sh"
fi
# /override-agent (list, reset): the user skill and the UserPromptExpansion hook, probed with a
# read-only `list` in a temp state dir (the hook command run as settings.json has it)
python3 - "$C" <<'PY' | while IFS= read -r l; do case "$l" in "ok "*) ok "${l#ok }" ;; *) warn "$l" ;; esac; done
import json, os, shutil, subprocess, sys, tempfile
c = sys.argv[1]
miss = [n for n in ("override-agent",) if not os.path.isfile(os.path.join(c, "skills", n, "SKILL.md"))]
if not os.path.isfile(os.path.join(c, "hooks", "agent_effort.json")):
    miss.append("hooks/agent_effort.json")
try:
    groups = json.load(open(os.path.join(c, "settings.json"))).get("hooks", {}).get("UserPromptExpansion") or []
except (OSError, ValueError):
    groups = []
cmds = [h.get("command") for g in groups if isinstance(g, dict) and "override-agent" in str(g.get("matcher"))
        for h in g.get("hooks") or [] if isinstance(h, dict) and "override-agent" in str(h.get("command"))]
if miss or not cmds:
    print("/override-agent not usable (%s) — rerun install.sh" % ", ".join(
        ["%s missing" % (n if "/" in n else "skills/" + n) for n in miss] + ([] if cmds else ["no UserPromptExpansion hook"])))
    sys.exit(0)
tmp = tempfile.mkdtemp(prefix="stack-doctor-override-")
ev = {"session_id": "doctor", "hook_event_name": "UserPromptExpansion", "expansion_type": "slash_command",
      "command_name": "override-agent", "command_args": "list", "command_source": "userSettings"}
try:
    p = subprocess.run(cmds[0], shell=True, input=json.dumps(ev), capture_output=True, text=True, timeout=20,
                       env=dict(os.environ, XDG_STATE_HOME=tmp))
    out = json.loads(p.stdout or "{}")
    if out.get("decision") == "block" and "defaults (model/effort)" in str(out.get("reason")):
        print("ok /override-agent: skill installed, UserPromptExpansion hook answers")
    else:
        print("/override-agent hook gave no answer (rc %d): %s" % (p.returncode, (p.stderr or p.stdout)[:200]))
except (OSError, ValueError, subprocess.SubprocessError) as exc:
    print("/override-agent hook probe failed: %s" % type(exc).__name__)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
PY
# /stack-doctor: the skill and its UserPromptExpansion hook (this script with --hook; not run here)
if [ -f "$C/skills/stack-doctor/SKILL.md" ] && python3 -c '
import json, sys
gs = json.load(open(sys.argv[1])).get("hooks", {}).get("UserPromptExpansion") or []
sys.exit(not any(isinstance(g, dict) and g.get("matcher") == "stack-doctor" and any(isinstance(h, dict)
    and str(h.get("command", "")).endswith("doctor.sh\" --hook") for h in g.get("hooks") or []) for g in gs))
' "$C/settings.json" 2>/dev/null; then ok "/stack-doctor: skill installed, UserPromptExpansion hook runs doctor.sh --hook"
else warn "/stack-doctor not wired (skills/stack-doctor or its UserPromptExpansion hook missing) — rerun install.sh"; fi
# /stack-tree: the skill and its UserPromptExpansion hook (bin/stack-tree --hook)
if [ -f "$C/skills/stack-tree/SKILL.md" ] && [ -x "$C/bin/stack-tree" ] && python3 -c '
import json, sys
gs = json.load(open(sys.argv[1])).get("hooks", {}).get("UserPromptExpansion") or []
sys.exit(not any(isinstance(g, dict) and g.get("matcher") == "stack-tree" and any(isinstance(h, dict)
    and str(h.get("command", "")).endswith("stack-tree\" --hook") for h in g.get("hooks") or []) for g in gs))
' "$C/settings.json" 2>/dev/null; then ok "/stack-tree: skill installed, UserPromptExpansion hook runs bin/stack-tree --hook"
else warn "/stack-tree not wired (skills/stack-tree, bin/stack-tree or its UserPromptExpansion hook missing) — rerun install.sh"; fi
# Run the hook commands exactly as Claude Code will (from settings.json and blackcat.md), on events that
# must be denied. A hook that cannot start is a non-blocking error in Claude Code: every gate open.
if [ -f "$C/settings.json" ] && [ -f "$C/hooks/agent_guard.py" ]; then
  python3 - "$C/settings.json" "$C/agents/blackcat.md" <<'PY'
import json, os, re, subprocess, sys, tempfile
settings, blackcat_md = sys.argv[1], sys.argv[2]
try:
    hooks = json.load(open(settings)).get("hooks", {})
except (OSError, ValueError):
    hooks = {}
# the guard's hook commands: through the launcher (`/bin/sh .../bin/stack-hook [--fail-closed]
# agent_guard <mode>`) or, from an install before it, `<python> .../hooks/agent_guard.py <mode>`
GUARD_RE = re.compile(r'(?:/bin/stack-hook"? (?:--fail-closed )?agent_guard|agent_guard\.py"?)(?=\s|$)')
def is_guard(c):
    return bool(GUARD_RE.search(str(c)))
def mode(h):
    found = list(GUARD_RE.finditer(str(h.get("command"))))
    return str(h.get("command"))[found[-1].end():].split() if found else []
# policy probe: the default-mode commands only (budget mode leaves Agent calls to the main hook)
cmds = sorted({h.get("command") for g in hooks.get("PreToolUse", []) if isinstance(g, dict)
               for h in g.get("hooks", []) if is_guard(h.get("command"))
               and not set(mode(h)) & {"image-limit", "no-push", "budget", "blackcat-guard"}})
# blackcat's gate, also wired in settings.json (acts only on events naming agent_type "blackcat")
bcmds = sorted({h.get("command") for g in hooks.get("PreToolUse", []) if isinstance(g, dict)
                for h in g.get("hooks", []) if is_guard(h.get("command"))
                and "blackcat-guard" in mode(h)})
# the token budgets gate every tool call: a PreToolUse group matching "*" runs `agent_guard.py budget`
if any(isinstance(g, dict) and g.get("matcher") == "*" and "budget" in mode(h)
       for g in hooks.get("PreToolUse", []) for h in (g.get("hooks", []) if isinstance(g, dict) else [])
       if is_guard(h.get("command"))):
    print("  ok    token budgets wired: PreToolUse \"*\" runs agent_guard.py budget")
else:
    print("  FAIL  no PreToolUse \"*\" group runs agent_guard.py budget: the token budgets are off — rerun install.sh")
pcmds = sorted({h.get("command") for g in hooks.get("PreToolUse", []) if isinstance(g, dict)
                for h in g.get("hooks", []) if "no-push" in str(h.get("command"))})
icmds = sorted({h.get("command") for g in hooks.get("PostToolUse", []) if isinstance(g, dict)
                for h in g.get("hooks", []) if "image-limit" in str(h.get("command"))})
rcmd = None
try:
    m = re.search(r'(?m)^\s+command:\s*"(.*agent_guard.*)"\s*$', open(blackcat_md).read())
    rcmd = json.loads('"%s"' % m.group(1)) if m else None
except (OSError, ValueError):
    pass
state = tempfile.mkdtemp(prefix="stack-doctor-")
import atexit, shutil
atexit.register(shutil.rmtree, state, True)     # the probes' guard state goes with this process
env = dict(os.environ, XDG_STATE_HOME=state, STACK_POLICY="on")
probes = [("settings.json PreToolUse(Agent)", cmds,
           {"session_id": "doctor", "hook_event_name": "PreToolUse", "tool_name": "Agent",
            "agent_id": "doctor-scout", "agent_type": "scout", "tool_use_id": "toolu_doctor",
            "tool_input": {"subagent_type": "coder", "prompt": "x", "description": "x"}}),
          ("blackcat.md blackcat-guard", [rcmd] if rcmd else [],
           {"session_id": "doctor", "hook_event_name": "PreToolUse", "tool_name": "WebFetch",
            "agent_type": "blackcat", "prompt_id": "doctor", "tool_input": {"url": "https://example.com"}}),
          ("settings.json PreToolUse blackcat-guard --settings", bcmds,
           {"session_id": "doctor", "hook_event_name": "PreToolUse", "tool_name": "WebFetch",
            "agent_type": "blackcat", "prompt_id": "doctor", "tool_input": {"url": "https://example.com"}}),
          ("settings.json PreToolUse(Bash) read-only reviewers", pcmds,
           {"session_id": "doctor", "hook_event_name": "PreToolUse", "tool_name": "Bash",
            "agent_id": "doctor-reviewer", "agent_type": "code-reviewer",
            "tool_input": {"command": "git commit -qm doctor-probe"}}),
          ("settings.json PreToolUse(Bash) no-push", pcmds,
           {"session_id": "doctor", "hook_event_name": "PreToolUse", "tool_name": "Bash",
            "tool_input": {"command": "git -C . push origin main"}}),
          ("settings.json PreToolUse(Bash) no-push inside bash -c", pcmds,
           {"session_id": "doctor", "hook_event_name": "PreToolUse", "tool_name": "Bash",
            "tool_input": {"command": "bash -c 'git push origin main'"}}),
          ("settings.json PreToolUse(Monitor) no forge write", pcmds,
           {"session_id": "doctor", "hook_event_name": "PreToolUse", "tool_name": "Monitor",
            "tool_input": {"command": "eval 'gh pr merge 1 --squash'"}})]
# The no-push hook must see every shell command: `if: "Bash(git *)"` skips `bash -c 'git push'`,
# `eval` and `/usr/bin/git` (tested on Claude Code 2.1.283), and Monitor runs commands too.
for g in hooks.get("PreToolUse", []):
    if isinstance(g, dict) and any("no-push" in str(h.get("command")) for h in g.get("hooks", [])):
        tools = set(str(g.get("matcher") or "").split("|"))
        filtered = [h.get("if") for h in g.get("hooks", []) if "no-push" in str(h.get("command")) and h.get("if")]
        if filtered or not {"Bash", "Monitor"} <= tools:
            print("  FAIL  no-push hook is filtered (matcher %r, if %r): nested pushes pass — rerun install.sh"
                  % (g.get("matcher"), filtered))
        else:
            print("  ok    no-push hook sees every Bash and Monitor command (no `if` filter)")
for label, commands, ev in probes:
    if not commands:
        print("  FAIL  %s: no agent_guard hook command found — rerun install.sh" % label)
        continue
    for cmd in commands:
        try:
            p = subprocess.run(["/bin/sh", "-c", cmd], input=json.dumps(ev), capture_output=True,
                               text=True, env=env, timeout=30, cwd=state)
            denied = '"deny"' in p.stdout
            detail = (p.stderr or p.stdout).strip().splitlines()[-1:] or [""]
        except (OSError, subprocess.SubprocessError) as exc:
            denied, detail = False, [str(exc)]
        if denied:
            print("  ok    %s enforces the policy (%s)" % (label, cmd.split('"')[1] if '"' in cmd else cmd.split()[0]))
        else:
            print("  FAIL  %s did not deny a forbidden call — the hook can't run: %s (%s)"
                  % (label, cmd, detail[0][:160]))
# The image limit, run as Claude Code runs it: a 2400x1300 Read result must come back within 1919 px.
import base64, struct, zlib
def _png(w, h):
    raw = b"".join(b"\x00" + bytes(3 * w) for _ in range(h))
    ck = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + ck(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + ck(b"IDAT", zlib.compress(raw)) + ck(b"IEND", b""))
ev = {"session_id": "doctor", "hook_event_name": "PostToolUse", "tool_name": "Read",
      "tool_response": {"type": "image", "file": {"base64": base64.b64encode(_png(2400, 1300)).decode(),
                                                  "type": "image/png", "dimensions": {}}}}
for cmd in icmds[:1]:
    try:
        p = subprocess.run(["/bin/sh", "-c", cmd], input=json.dumps(ev), capture_output=True, text=True,
                           env=dict(env, XDG_CACHE_HOME=state), timeout=60, cwd=state)
        out = json.loads(p.stdout)["hookSpecificOutput"]["updatedToolOutput"]["file"]["base64"]
        w, h = struct.unpack(">II", base64.b64decode(out)[16:24])
        print("  ok    image limit scales a 2400x1300 image to %dx%d" % (w, h) if max(w, h) < 1920 else
              "  FAIL  image limit returned %dx%d" % (w, h))
    except Exception as exc:   # noqa: BLE001
        print("  WARN  image limit didn't scale a test image (%s) — is sips (macOS) available?" % type(exc).__name__)

PY
fi
state_root="${XDG_STATE_HOME:-$HOME/.local/state}/claude-agent-stack"
if mkdir -p "$state_root" 2>/dev/null && [ -w "$state_root" ]; then
  ok "state dir writable ($state_root)"
else
  fail "state dir not writable ($state_root)"
fi

echo "== Settings"
if [ -f "$C/settings.json" ]; then
  MEASURED_MODELS="$MEASURED_MODELS" python3 - "$C/settings.json" "$C/skills" <<'PY'
import json, os, re, sys
p, skills_dir = sys.argv[1], sys.argv[2]
try:
    s = json.load(open(p))
except (OSError, ValueError) as e:
    print("  FAIL  settings.json is not valid JSON: %s" % e)
    sys.exit(0)
def ok(m): print("  ok    " + m)
def warn(m): print("  WARN  " + m)
def fail(m): print("  FAIL  " + m)
# What each alias the agents name resolves to: ANTHROPIC_DEFAULT_<FAMILY>_MODEL. Claude Code writes a
# settings file's env over the inherited environment (code.claude.com/docs/en/env-vars, "In settings
# files"), so settings.json's env comes first, then the process environment; stack.env is the source
# install.sh copies into settings.json. Unset: Claude Code's own target for the provider.
def stack_env_models(path):
    vals = {}
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except (OSError, UnicodeDecodeError):
        return vals
    for line in lines:
        m = re.match(r"\s*(?:export\s+)?(ANTHROPIC_DEFAULT_[A-Z]+_MODEL)=(.*)$", line)
        if m:
            v = m.group(2).strip()
            vals[m.group(1)] = (v[1:v.index(v[0], 1)] if v[:1] in ("'", '"') and v[0] in v[1:]
                                else re.split(r"\s+#", v, maxsplit=1)[0].strip())
    return vals
_senv = s.get("env") if isinstance(s.get("env"), dict) else {}
_stack_models = stack_env_models(os.path.join(os.path.dirname(p), "stack.env"))
resolved = {}
for fam in ("opus", "sonnet", "haiku"):
    k = "ANTHROPIC_DEFAULT_%s_MODEL" % fam.upper()
    if str(_senv.get(k) or ""):
        resolved[fam] = (str(_senv[k]), "settings.json env")
    elif os.environ.get(k):
        resolved[fam] = (os.environ[k], "process environment")
    else:
        resolved[fam] = (None, None)
agent = s.get("agent")
if agent == "blackcat":
    ok("main thread agent: BlackCat")
    # an agent file's effort applies only to subagents: BlackCat runs at the session's level
    sonnet = resolved["sonnet"][0]
    saved = {k: v for k, v in (s.get("modelSettings") or {}).items() if isinstance(v, dict)}
    lvl = (saved.get(sonnet) or {}).get("effortLevel") if sonnet else next(
        (v.get("effortLevel") for k, v in saved.items() if "sonnet" in k), None)
    if lvl in (None, "medium"):
        ok("BlackCat effort: %s" % (lvl and "medium (saved for %s)" % (sonnet or "Sonnet") or "Sonnet's default, medium"))
    else:
        warn("BlackCat effort: %s — BlackCat's file says medium (at low it skips clarifying questions, above "
             "medium it spends on routing), but a main-thread agent runs at the session's level: run "
             "/effort medium once in a BlackCat session (saved for %s)" % (lvl, sonnet or "Sonnet"))
elif agent:
    ok("main thread agent: %s (your choice; the stack's BlackCat: claude --agent blackcat)" % agent)
else:
    warn("no main thread agent — rerun install.sh for the stack's BlackCat, or set \"agent\": \"claude\" to opt out")
(ok if s.get("autoCompactEnabled", True) is True else fail)("autoCompactEnabled=%s" % s.get("autoCompactEnabled", "default(true)"))
(ok if s.get("autoCompactWindow") == 629000 else warn)("autoCompactWindow=%s (stack: 629000)" % s.get("autoCompactWindow"))
env = s.get("env", {})
want = {"CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "8", "MCP_DISCOVERY_CACHE": "1"}
for k, v in want.items():
    (ok if env.get(k) == v else warn)("%s=%s (stack: %s)" % (k, env.get(k), v))
# Tool search (MCP schemas deferred until needed) is on by default on the Anthropic API and off
# behind a gateway; ENABLE_TOOL_SEARCH=true forces it through gateways that may reject it.
ts = str(env.get("ENABLE_TOOL_SEARCH", os.environ.get("ENABLE_TOOL_SEARCH", ""))).strip().lower()
base = str(env.get("ANTHROPIC_BASE_URL") or os.environ.get("ANTHROPIC_BASE_URL") or "")
gateway = bool(base) and "api.anthropic.com" not in base
betas_off = str(env.get("CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS", os.environ.get("CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS", ""))).strip()
if betas_off and betas_off.lower() not in ("0", "false"):
    warn("CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS is set: tool search is off, every MCP tool schema loads up front")
elif ts == "false":
    warn("ENABLE_TOOL_SEARCH=false: every MCP tool schema loads up front in every session")
elif ts.startswith("auto"):
    ok("ENABLE_TOOL_SEARCH=%s: MCP tools load up front while their schemas are small, deferred above the threshold" % ts)
elif ts == "true" and gateway:
    warn("ENABLE_TOOL_SEARCH=true with ANTHROPIC_BASE_URL=%s: requests fail unless that gateway forwards tool_reference blocks" % base)
elif not ts and gateway:
    ok("tool search off behind your gateway (%s): MCP tools load up front" % base)
else:
    ok("tool search: %s (MCP tools deferred until needed)" % ("ENABLE_TOOL_SEARCH=" + ts if ts else "default"))
try:
    conc = int(env.get("CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS", "20"))
except ValueError:
    conc = None
(ok if conc and conc >= 128 else warn)("CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS=%s%s" % (
    env.get("CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS", "20 (default)"),
    "" if conc and conc >= 128 else " — the stack ships 128 (room for several full orchestrator fan-outs of 32)"))
for key in ("CLAUDE_CODE_DISABLE_BACKGROUND_TASKS", "CLAUDE_CODE_FORK_SUBAGENT"):
    val = env.get(key, os.environ.get(key))
    if val not in (None, ""):
        warn("%s=%s — it changes subagent scheduling (foreground/background); the stack expects it unset" % (key, val))
if str(env.get("BLACKCAT_BACKGROUND", "1")).strip() == "0":
    warn("BLACKCAT_BACKGROUND=0 — BlackCat may run children in the foreground and block the app (Claude Desktop)")
for bad in ("DISABLE_AUTO_COMPACT", "DISABLE_COMPACT", "CLAUDE_CODE_AUTO_COMPACT_WINDOW", "CLAUDE_CODE_DISABLE_1M_CONTEXT",
            "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE", "CLAUDE_CODE_BLOCKING_LIMIT_OVERRIDE",
            "CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "CLAUDE_CODE_EFFORT_LEVEL"):
    if bad in env:
        warn("settings env sets %s=%s — it overrides the stack's compaction/model/effort settings" % (bad, env[bad]))
    if os.environ.get(bad):
        warn("your shell exports %s=%s — it overrides the stack's compaction/model/effort settings" % (bad, os.environ[bad]))
hooks = s.get("hooks", {})
events = ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "SubagentStart", "SubagentStop",
          "PostToolUseFailure", "PermissionDenied", "StopFailure", "PreCompact"]
GUARD_RE = re.compile(r'(?:/bin/stack-hook"? (?:--fail-closed )?agent_guard|agent_guard\.py"?)(?=\s|$)')
is_guard = lambda c: bool(GUARD_RE.search(str(c)))
in_group = lambda g: isinstance(g, dict) and any(isinstance(h, dict) and is_guard(h.get("command"))
                                                 for h in g.get("hooks") or [])
missing_ev = [ev for ev in events if not any(in_group(g) for g in hooks.get(ev, []))]
(fail if missing_ev else ok)("guard hooks wired for all %d events" % len(events) if not missing_ev else "guard hooks missing for: " + ", ".join(missing_ev))
# SessionStart: startup and resume clear stale locks and leases; fork starts a forked session's
# token count at the end of the history it copied (without it, the fork inherits its parent's usage);
# compact re-injects the compaction digest (the PreCompact snapshot's running and unrelayed children)
starts = [str(g.get("matcher") or "*") for g in hooks.get("SessionStart", [])
          if isinstance(g, dict) and any(
              isinstance(h, dict) and is_guard(h.get("command", ""))
              and not str(h.get("command", "")).rstrip().endswith(" session-env")
              for h in g.get("hooks") or [])]
def _matches(m, source):
    if m == "*":
        return True
    try:
        return re.fullmatch(m, source) is not None
    except re.error:
        return source in m.split("|")
lost = [src for src in ("startup", "resume", "fork", "compact") if not any(_matches(m, src) for m in starts)]
(fail if lost else ok)("SessionStart guard matcher covers startup, resume, fork and compact" if not lost
                       else "SessionStart guard matcher %s misses %s — rerun install.sh"
                       % (" / ".join(starts) or "(none)", ", ".join(lost)))
post = {g.get("matcher") for g in hooks.get("PostToolUse", []) if in_group(g)}
(ok if any("TaskStop" in (m or "") for m in post) else warn)(
    "PostToolUse also watches TaskStop (a stopped agent releases its locks)" if any("TaskStop" in (m or "") for m in post)
    else "PostToolUse guard matcher lacks TaskStop — rerun install.sh")
cmds = {h.get("command", "") for gs in hooks.values() for g in gs if isinstance(g, dict) for h in g.get("hooks", [])
        if is_guard(h.get("command"))}
bare = sorted(c for c in cmds if c.split()[0].strip('"') in ("python3", "python"))
(warn if bare else ok)("guard hooks call an absolute interpreter" if not bare
                       else "guard hooks call a bare python3 (a broken pyenv/asdf shim would disable them) — rerun install.sh")
matchers = {g.get("matcher") for g in hooks.get("PreToolUse", []) if isinstance(g, dict)}
# exact-name matchers are |-lists: the Agent tool's aliases (Task, SubAgent) and Workflow's
# (RunWorkflow) must reach the spawn and workflow gates too
names = {p.strip() for m in matchers if m and re.fullmatch(r"[\w|, -]+", m) for p in re.split(r"[|,]", m)}
exp = {"Agent", "Task", "SubAgent", "Workflow", "RunWorkflow", "SendMessage"}
got = names | ({"mcp__computer-use__.*"} & matchers)
exp.add("mcp__computer-use__.*")
(ok if exp <= got else fail)("PreToolUse matchers: " + ("Agent and its aliases, Workflow, SendMessage, computer use present" if exp <= got else "missing " + ", ".join(sorted(exp - got)) + " — rerun install.sh"))
(ok if any("ctx_index" in (m or "") for m in matchers) else fail)(
    "local-file MCP tools (context-mode ctx_index, markitdown, docling, playwright) held to the Read deny rules"
    if any("ctx_index" in (m or "") for m in matchers) else
    "no PreToolUse guard for local-file MCP tools: ctx_index/markitdown could read stack.env or ~/.ssh — rerun install.sh")
lim_post = any("image-limit" in json.dumps(g) for g in hooks.get("PostToolUse", []))
lim_pre = any("image-limit" in json.dumps(g) for g in hooks.get("PreToolUse", []))
mx = str(env.get("STACK_IMAGE_MAX_PX", os.environ.get("STACK_IMAGE_MAX_PX", "1919")))
if lim_post and lim_pre:
    (ok if mx != "0" else warn)("image limit: images agents read or upload stay within %s px per side" % mx
                                if mx != "0" else "image limit off (STACK_IMAGE_MAX_PX=0)")
else:
    warn("image limit hooks missing (PostToolUse Read|mcp__.*, PreToolUse mcp__.*) — rerun install.sh")
# one line per alias; a warning when it differs from stack.env (not re-installed) or from the model
# the soft token limits and maxTurns were measured on (MEASURED_MODELS at the top of doctor.sh)
measured = dict(x.split("=", 1) for x in os.environ.get("MEASURED_MODELS", "").split() if "=" in x)
for fam in ("opus", "sonnet", "haiku"):
    k = "ANTHROPIC_DEFAULT_%s_MODEL" % fam.upper()
    val, src = resolved[fam]
    want = _stack_models.get(k) or ""
    what = "the haiku alias and background tasks" if fam == "haiku" else "alias %s" % fam
    if not val:
        warn("%s → Claude Code's own target for your provider (%s unset)%s" % (
            what, k, " — stack.env sets %s: re-run install.sh" % want if want else
            " — set it in stack.env and re-run install.sh"))
        continue
    msg = "%s → %s (%s)" % (what, val, src)
    if src == "settings.json env" and os.environ.get(k) and os.environ[k] != val:
        warn("%s exported as %s in this environment: settings.json's value applies in most sessions "
             "(docs), the exceptions are unverified — unexport it" % (k, os.environ[k]))
    if fam == "haiku" and "haiku" in val.lower():
        warn(msg + " — the stack runs no Haiku: stack.env.example sets this slot to the Sonnet ID")
    elif want and want != val:
        warn(msg + " — stack.env sets %s: re-run install.sh%s" % (
            want, "" if src == "process environment" else " (or delete your settings.json entry)"))
    elif fam in measured and val.replace("[1m]", "") != measured[fam]:
        warn(msg + " — the soft token limits and maxTurns were measured on %s: re-derive them "
             "(uv run --script tests/derive_thresholds.py in the stack repo), then update MEASURED_MODELS "
             "in bin/doctor.sh" % measured[fam])
    else:
        ok(msg)
if "nmem-hook-" in json.dumps(hooks):
    warn("settings.json runs neural-memory hooks (nmem-hook-*) on every session and tool call — the stack's agents "
         "recall on demand and don't need them: remove them unless you set them up yourself")
deny = set((s.get("permissions") or {}).get("deny") or [])
cm_exec = {"mcp__context-mode__ctx_execute", "mcp__context-mode__ctx_execute_file", "mcp__context-mode__ctx_batch_execute"}
(ok if cm_exec <= deny else warn)("context-mode: code execution tools denied (agents run code through Bash)" if cm_exec <= deny
                                  else "context-mode code execution tools not denied: %s — rerun install.sh" % ", ".join(sorted(cm_exec - deny)))
allow = set((s.get("permissions") or {}).get("allow") or [])
(ok if "mcp__huggingface" in allow else warn)("mcp__huggingface %s permissions.allow" % ("in" if "mcp__huggingface" in allow else "not in"))
if "mcp__magg" in allow:
    warn("permissions.allow has a blanket mcp__magg: mcp-broker can add and run any MCP server without asking — remove it from settings.json (the stack pre-approves only the catalog tools)")
else:
    (ok if "mcp__magg__magg_list_servers" in allow else warn)("magg: catalog tools pre-approved, new servers and proxy calls ask first")
sl = s.get("statusLine") or {}
ok("status line: %s" % ("stack (context vs auto-compact window, rate limits)" if "statusline.py" in str(sl.get("command")) else (sl.get("command") or "none")))
missing_skills = []
if os.path.isdir(skills_dir):
    for name in sorted(os.listdir(skills_dir)):
        f = os.path.join(skills_dir, name, "SKILL.md")
        if name == "synced" or not os.path.isfile(f):
            continue
        head = open(f).read().split("---", 2)
        if len(head) >= 3 and re.search(r"(?m)^disable-model-invocation:\s*true", head[1]):
            continue
        if "Skill" not in allow and "Skill(%s)" % name not in allow:
            missing_skills.append(name)
(warn if missing_skills else ok)(("every skill pre-approved (one Skill rule: skills added later work too)" if "Skill" in allow
                                   else "on-demand skills pre-approved") if not missing_skills else
                                  "skills without a Skill(...) allow rule (subagents will prompt): " + ", ".join(missing_skills))
# Every agent sees one line per skill (name + description). Claude Code caps that listing at
# skillListingBudgetFraction (default 0.01) of the context window, at ~3 characters per token on
# current models; over the cap, the least-used skills lose their description and show by name only.
try:
    frac = float(s.get("skillListingBudgetFraction", 0.01))
except (TypeError, ValueError):
    frac = 0.01
try:
    cap = int(s.get("skillListingMaxDescChars", 1536))   # each description is cut at this length
except (TypeError, ValueError):
    cap = 1536
budget = int(1000000 * 3 * frac)
# skillOverrides: "name-only" lists the name alone, "user-invocable-only" and "off" nothing
overrides = s.get("skillOverrides") if isinstance(s.get("skillOverrides"), dict) else {}
n_sk, chars = 0, 0
for root, _dirs, files in os.walk(skills_dir):
    if "SKILL.md" not in files:
        continue
    head = open(os.path.join(root, "SKILL.md"), encoding="utf-8", errors="replace").read().split("---", 2)
    if len(head) < 3 or re.search(r"(?m)^disable-model-invocation:\s*true", head[1]):
        continue
    state = overrides.get(os.path.basename(root), "on")
    if state in ("user-invocable-only", "off"):
        continue
    m = re.search(r"(?m)^description:\s*(.*)$", head[1])
    n_sk += 1
    # "- name: description" plus a newline; "- name" for name-only (Claude Code 2.1.287)
    chars += len(os.path.basename(root)) + (3 if state == "name-only" else 5 + min(len(m.group(1).strip()) if m else 0, cap))
(ok if chars <= budget else warn)(
    "skill listing: %d skills, ~%d of %d characters (skillListingBudgetFraction=%s, 1M-context models; plugin skills add to it)"
    % (n_sk, chars, budget, frac) if chars <= budget else
    "skill listing: %d skills, ~%d characters > %d budget: the least-used skills show by name only — raise "
    "skillListingBudgetFraction in settings.json or turn skills off in /skills" % (n_sk, chars, budget))
PY
else
  fail "settings.json missing"
fi

echo "== Placeholders"
# only the installer's own placeholders (a user file may legitimately contain __CUDA_ARCH__, __FILE__...)
PH='__(CLAUDE_DIR|HOME|PYTHON3|UV|UVX|NPX|NODE|MAGG|HUETENSION|STACK_REPO)__'
leftover=""
for f in "$C"/agents/*.md "$C/rules/claude-agent-stack.md" "$C/settings.json" "$C/magg/config.json"; do
  [ -f "$f" ] || continue
  grep -qE "$PH" "$f" 2>/dev/null && leftover="$leftover $(basename "$f")"
done
for f in "$C"/skills/*/SKILL.md; do
  [ -f "$f" ] || continue
  grep -qE "$PH" "$f" 2>/dev/null && leftover="$leftover skills/$(basename "$(dirname "$f")")"
done
[ -z "$leftover" ] && ok "no unresolved placeholders" || fail "unresolved placeholders in:$leftover"

echo "== Frontmatter lint"
python3 - "$C/agents" <<'PY'
import glob, os, re, sys
d = sys.argv[1]
valid_colors = {"red", "blue", "green", "yellow", "purple", "orange", "pink", "cyan"}
bad_tasks = re.compile(r"Task(Create|Get|Update|List|Output)")
problems = []
for f in sorted(glob.glob(os.path.join(d, "*.md"))):
    text = open(f).read()
    name = os.path.basename(f)
    fm = text.split("---", 2)
    body = fm[1] if len(fm) >= 3 else text
    model = re.search(r"(?m)^model:\s*(\S+)", body)
    effort = re.search(r"(?m)^effort:\s*(\S+)", body)
    color = re.search(r"(?m)^color:\s*(\S+)", body)
    tools = re.search(r"(?m)^tools:\s*(.*)$", body)
    memory = re.search(r"(?m)^memory:\s*(\S+)", body)
    if model and "haiku" in model.group(1).lower():
        problems.append("%s: model %s — the stack runs no Haiku: name opus or sonnet" % (name, model.group(1)))
    if color and color.group(1) not in valid_colors:
        problems.append("%s: invalid color '%s'" % (name, color.group(1)))
    if tools and bad_tasks.search(tools.group(1)):
        problems.append("%s: tools: still lists a deprecated Task* tool" % name)
    if memory and memory.group(1) not in ("user", "project", "local"):
        problems.append("%s: invalid memory '%s'" % (name, memory.group(1)))
if problems:
    for p in problems:
        print("  FAIL  " + p)
else:
    print("  ok    frontmatter lint clean (no Haiku models, color, memory, deprecated Task tools)")
PY

echo "== GitHub credentials agents could use (presence only: no value is printed)"
# R3-N1-P2. Sandboxed Bash turns git's credential helpers off (session-env: credential.helper=), but a
# token in the environment, gh's own login and a plain-text credential file are what an agent's gh, or
# git over HTTPS, would still authenticate with. Least privilege: none, or a read-only fine-grained
# token in a GH_CONFIG_DIR of its own; push over SSH from your own terminal.
creds=0
for v in GH_TOKEN GITHUB_TOKEN GH_ENTERPRISE_TOKEN GITHUB_ENTERPRISE_TOKEN; do
  if [ -n "${!v:+x}" ]; then
    creds=1
    warn "$v is set in this environment: sandboxed Bash doesn't get it (sandbox.credentials), but hooks, MCP servers and other unsandboxed processes Claude Code starts do; use a read-only fine-grained token, or unset it before starting claude"
  fi
done
ghdir="${GH_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/gh}"
if grep -qsE '^[[:space:]]*oauth_token:[[:space:]]*[^[:space:]]' "$ghdir/hosts.yml"; then
  creds=1
  warn "gh keeps a token in plain text in $ghdir/hosts.yml: unsandboxed processes can read it (sandboxed Bash is denied only ~/.config/gh/hosts.yml); log gh in with a read-only fine-grained token"
fi
for f in "$HOME/.git-credentials" "${XDG_CONFIG_HOME:-$HOME/.config}/git/credentials"; do
  if grep -qs 'github\.com' "$f"; then
    creds=1
    warn "$f holds a github.com credential in plain text (credential-store): sandboxed Bash is denied ~/.git-credentials and ~/.config/git/credentials, git outside the sandbox uses it; prefer SSH for pushes"
  fi
done
if [ "$(uname)" = "Darwin" ] && have security; then
  # attribute searches only (no -g/-w): the secret is never read and no keychain prompt appears
  for q in "generic-password gh:github.com gh's github.com login (keychain service gh:github.com): an agent's gh can use it wherever the keychain is reachable; log gh in with a read-only fine-grained token" \
           "internet-password github.com a github.com password in the keychain (git's osxkeychain helper): off in sandboxed Bash, used by git outside it; keep write-capable HTTPS credentials out of it"; do
    kind="${q%% *}"; rest="${q#* }"; svc="${rest%% *}"; what="${rest#* }"
    security "find-$kind" -s "$svc" >/dev/null 2>&1; rc=$?
    case "$rc" in
      0) creds=1; warn "$what" ;;
      44) ;;                                              # errSecItemNotFound
      *) warn "couldn't check the keychain for $svc (security exit $rc)" ;;
    esac
  done
fi
[ "$creds" = 0 ] && ok "no GitHub token in the environment, gh's hosts.yml, git's credential-store files or the keychain"

echo "== Platform"
if [ "$(uname)" = "Darwin" ]; then
  if [ -f "$C/mcp/vendor/after-effects-mcp/build/index.js" ]; then ok "After Effects MCP built"
  elif grep -q 'after-effects-mcp/build/index.js' "$C/agents/motion-designer.md" 2>/dev/null; then
    fail "motion-designer declares the After Effects MCP but it is not built — ./install.sh --with-adobe (or rerun ./install.sh to drop it)"
  else ok "After Effects MCP not built (optional, motion-designer's AE tools: ./install.sh --with-adobe)"; fi
  ok "computer use possible (macOS) — enable once per project: /mcp → computer-use → Enable"
else
  ok "computer use in the CLI is macOS-only; GUI agents fall back to MCP/scripts here"
fi
lsp=""; for b in pyright-langserver typescript-language-server rust-analyzer sourcekit-lsp clangd gopls jdtls kotlin-lsp haskell-language-server-wrapper lake metals julia; do
  case "$b" in
    rust-analyzer) rust-analyzer --version >/dev/null 2>&1 && lsp="$lsp $b" ;;
    julia) have julia && julia --startup-file=no --history-file=no --project=@claude-lsp \
      -e 'exit(Base.find_package("LanguageServer") === nothing ? 1 : 0)' >/dev/null 2>&1 && lsp="$lsp LanguageServer.jl" ;;
    *) have "$b" && lsp="$lsp $b" ;;
  esac
done
[ -n "$lsp" ] && ok "language servers on PATH:$lsp (code-intelligence plugins start them on demand)" || warn "no language servers on PATH — ./install.sh --with-lsp"
# The Playwright MCP (browser-operator, frontend-engineer, verifier) drives Google Chrome by default.
[ -d "/Applications/Google Chrome.app" ] && ok "Google Chrome found (Playwright MCP)" \
  || warn "Google Chrome not found — the Playwright MCP of browser-operator, frontend-engineer and verifier drives it: npx @playwright/mcp@0.0.82 install-browser chrome"

echo "== Container isolation (eq-container)"
# install.sh --with-eq-container (lib/eq-container, Apple container): the state files are read line by
# line (never sourced) and the container CLI is asked only for the recorded images' digests (bounded by
# $T). No code from the repo runs here: the digest is read from `container image inspect` inline.
EQS="${XDG_STATE_HOME:-$HOME/.local/state}/claude-agent-stack/eq-container"
eqkv(){ [ -f "$1" ] || return 0; awk -v k="$2=" 'index($0, k) == 1 { print substr($0, length(k) + 1); exit }' "$1" 2>/dev/null; }
# envkv KEY: the value in force in stack.env (the last uncommented KEY=, unquoted; empty when none)
envkv(){ [ -f "$C/stack.env" ] || return 0; awk -v k="$1" '
  { l = $0; sub(/^[ \t]+/, "", l); sub(/^export[ \t]+/, "", l)
    if (substr(l, 1, length(k)) != k) next
    r = substr(l, length(k) + 1); sub(/^[ \t]*/, "", r)
    if (substr(r, 1, 1) != "=") next
    v = substr(r, 2); sub(/^[ \t]+/, "", v); sub(/[ \t]+$/, "", v)
    if (v ~ /^".*"$/ || v ~ /^'\''.*'\''$/) v = substr(v, 2, length(v) - 2); else sub(/[ \t]+#.*$/, "", v)
    last = v }
  END { print last }' "$C/stack.env" 2>/dev/null; }
# the signed .pkg installs the CLI at /usr/local/bin/container; PATH only when it is not there.
# EQ_CONTAINER_BIN (as lib/eq-container honours it) names another one; it is only asked read-only questions
eqc_bin=""
if [ -n "${EQ_CONTAINER_BIN:-}" ]; then [ ! -x "$EQ_CONTAINER_BIN" ] || eqc_bin=$EQ_CONTAINER_BIN
elif [ -x /usr/local/bin/container ]; then eqc_bin=/usr/local/bin/container; elif have container; then eqc_bin="$(command -v container)"; fi
# the image digest in `container image inspect` JSON: .configuration.descriptor.digest and/or .id (its hex,
# without "sha256:"), which must agree (the same reading as lib/eq-container/eqc_json.py; CLI source at tag 1.5.0)
eqc_digest(){ python3 -I -c 'import json, re, sys
try:
    d = json.load(sys.stdin)
except ValueError:
    sys.exit(1)
if not (isinstance(d, list) and len(d) == 1 and isinstance(d[0], dict)):
    sys.exit(1)
c = d[0].get("configuration")
desc = c.get("descriptor") if isinstance(c, dict) else None
i = d[0].get("id")
if isinstance(i, str) and re.fullmatch(r"[0-9a-f]{64}", i):
    i = "sha256:" + i
vals = {v for v in (desc.get("digest") if isinstance(desc, dict) else None, i)
        if isinstance(v, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", v)}
if len(vals) != 1:
    sys.exit(1)
print(vals.pop())'; }
eq_want=0; [ "$(envkv EQ_ISOLATION)" = container ] && eq_want=1
eq_st=$(eqkv "$EQS/status.env" EQ_CONTAINER_STATUS); eq_at=$(eqkv "$EQS/status.env" EQ_CONTAINER_STATUS_AT)
eq_why=$(eqkv "$EQS/status.env" EQ_CONTAINER_STATUS_WHY)
if [ ! -f "$EQS/status.env" ]; then
  ok "eq-container: not installed (optional: ./install.sh --with-eq-container)"
  [ "$eq_want" = 1 ] && warn "EQ_ISOLATION=container is set in stack.env but eq-container is not installed"
else
  case "$eq_st" in
    ok)
      ok "eq-container: verified $eq_at (set $(eqkv "$EQS/status.env" EQ_CONTAINER_STATUS_SET), probe $(eqkv "$EQS/status.env" EQ_CONTAINER_STATUS_PROBE))"
      eq_prof=$(eqkv "$EQS/status.env" EQ_CONTAINER_STATUS_PROFILES)
      [ -n "$eq_prof" ] && ok "eq-container profiles: $eq_prof"
      [ -n "$(eqkv "$EQS/image.env" EQ_CONTAINER_IMAGE_PF)" ] || warn "eq-container: image.env has no EQ_CONTAINER_IMAGE_PF (rerun the install)"
      # every distinct recorded ref: the PF/CP/CR refs and each image's EQ_<NAME>_TAG + EQ_<NAME>_DIGEST
      eq_refs=$(awk -F= '
        $1 ~ /^EQ_CONTAINER_IMAGE_(PF|CP|CR)$/ { r[$2] = 1; next }
        $1 ~ /^EQ_[A-Z0-9_]+_TAG$/ { t[substr($1, 1, length($1) - 4)] = $2; next }
        $1 ~ /^EQ_[A-Z0-9_]+_DIGEST$/ { d[substr($1, 1, length($1) - 7)] = $2 }
        END { for (k in t) if (k in d) r[t[k] "@" d[k]] = 1; for (x in r) print x }' "$EQS/image.env" 2>/dev/null | LC_ALL=C sort -u)
      if [ -z "$eqc_bin" ]; then
        warn "eq-container: the container CLI is not installed, images not checked (Apple container: https://github.com/apple/container/releases)"
      elif ! $T "$eqc_bin" system status >/dev/null 2>&1 </dev/null; then
        warn "eq-container: the container services are not running, images not checked (run: container system start)"
      else
        set -f   # the refs are data: split on blanks, never globbed
        for eq_ref in $eq_refs; do
          eq_tag=${eq_ref%@*}; eq_dig=${eq_ref##*@}
          case "$eq_tag" in eq.invalid/*) ;; *) fail "eq-container: recorded image $eq_tag is not under eq.invalid/: rerun ./install.sh --with-eq-container"; continue ;; esac
          eq_got=$($T "$eqc_bin" image inspect "$eq_tag" 2>/dev/null </dev/null | eqc_digest)
          eq_s=${eq_dig#sha256:}; eq_s=${eq_s%"${eq_s#????????????}"}
          if [ -n "$eq_got" ] && [ "$eq_got" = "$eq_dig" ]; then ok "eq-container image $eq_tag ($eq_s) present"
          else fail "eq-container image $eq_tag is not the recorded $eq_s (missing, rebuilt or retagged): run ./install.sh --with-eq-container"; fi
        done
        set +f
      fi ;;
    skipped)
      if [ "$eq_want" = 1 ]; then warn "eq-container: skipped at $eq_at ($eq_why), but EQ_ISOLATION=container is set in stack.env"
      else ok "eq-container: skipped at $eq_at ($eq_why)"; fi ;;
    failed) warn "eq-container: install failed at $eq_at: $eq_why (logs: $EQS/logs)" ;;
    *) warn "eq-container: $EQS/status.env holds no known EQ_CONTAINER_STATUS: rerun ./install.sh --with-eq-container" ;;
  esac
  for eq_f in "$EQS"/results/probe.*.env "$EQS"/results/tunnel.*.env; do
    [ -f "$eq_f" ] || continue
    eq_k=$(basename "$eq_f"); eq_k=${eq_k%%.*}; eq_K=$(printf '%s' "$eq_k" | tr '[:lower:]' '[:upper:]')
    [ "$(eqkv "$eq_f" "${eq_K}_RESULT")" = FAIL ] || continue
    warn "eq-container: $eq_k FAIL at $(eqkv "$eq_f" "${eq_K}_AT") ($(eqkv "$eq_f" "${eq_K}_FAILS") rows) for $(eqkv "$eq_f" "${eq_K}_IMAGE"): see $EQS/logs/probe.log"
  done
fi

echo "== WALL (eq-wall)"
# install.sh --with-eq-container's step 10c (lib/eq-wall): the host-access broker's state dir and its ONE
# tunnel root. The broker's own checks run on bin/stack-python (never python3 from PATH: it needs 3.11+),
# and only on the bytes of eq_wall.py the install recorded (.stack-manifest.json eq_wall.broker_sha256):
# the repo is writable by agents, so the file is read once, hash-checked and run from that read.
WS="$(envkv EQ_WALL_STATE_DIR)"; [ -n "$WS" ] || WS="${XDG_STATE_HOME:-$HOME/.local/state}/claude-agent-stack/eq-wall"
WT="$(envkv EQ_TUNNEL_DIR)"; [ -n "$WT" ] || WT="${XDG_CACHE_HOME:-$HOME/.cache}/claude-agent-stack/eq-tunnel"
w_st=$(eqkv "$WS/status.env" EQ_WALL_STATUS); w_at=$(eqkv "$WS/status.env" EQ_WALL_STATUS_AT)
w_why=$(eqkv "$WS/status.env" EQ_WALL_STATUS_WHY)
if [ ! -f "$WS/status.env" ]; then
  ok "WALL: not set up (optional: ./install.sh --with-eq-container [--with-eq-broker])"
else
  case "$w_st" in
    off) ok "WALL: off ($w_why)" ;;
    skipped) ok "WALL: skipped at $w_at ($w_why)" ;;
    failed) warn "WALL: setup failed at $w_at: $w_why" ;;
    on)
      for w_d in "$WT:tunnel root" "$WS:state dir"; do
        w_p=${w_d%%:*}; w_n=${w_d#*:}
        w_m=$(ls -ld "$w_p" 2>/dev/null | cut -c1-10)
        if [ -L "$w_p" ]; then fail "WALL $w_n $w_p is a symlink: remove it (install.sh makes a real 0700 directory)"
        elif [ ! -d "$w_p" ]; then fail "WALL $w_n $w_p is missing: rerun ./install.sh --with-eq-container"
        elif [ ! -O "$w_p" ]; then fail "WALL $w_n $w_p is not owned by you: remove it"
        elif [ "$w_m" != drwx------ ]; then fail "WALL $w_n $w_p is $w_m: chmod 700 or remove it"
        else ok "WALL $w_n $w_p 0700"; fi
      done
      w_bad=$(find "$WT" "$WS" -type f ! -perm 600 2>/dev/null | head -n 3 | tr '\n' ' ')
      [ -z "$w_bad" ] && ok "WALL files 0600" || fail "WALL files not 0600: $w_bad"
      w_sp=$(find "$WT" ! -type d ! -type f 2>/dev/null | head -n 5 | tr '\n' ' ')
      [ -z "$w_sp" ] && ok "WALL tunnel holds no special files" \
        || warn "stale special file(s) in the tunnel: $w_sp(the broker removes them unread; remove stale run dirs by hand)"
      # the broker, from the bytes the install recorded
      W_PY="$C/bin/stack-python"
      w_dir="$(envkv EQ_WALL_DIR)"
      w_meta=$(python3 -c 'import json, sys
try:
    r = json.load(open(sys.argv[1])).get("eq_wall") or {}
except Exception:
    r = {}
for k in ("broker_sha256", "wall_dir"):
    v = r.get(k) if isinstance(r, dict) else ""
    print(v if isinstance(v, str) and v.isprintable() else "")' "$C/.stack-manifest.json" 2>/dev/null)
      w_sha=$(printf '%s\n' "$w_meta" | sed -n 1p); [ -n "$w_dir" ] || w_dir=$(printf '%s\n' "$w_meta" | sed -n 2p)
      w_pol="$(envkv EQ_WALL_POLICY)"; [ -n "$w_pol" ] || w_pol="$w_dir/policy.default.toml"
      wall_py(){ "$W_PY" -I -c 'import hashlib, sys, types
p, want = sys.argv[1], sys.argv[2]
src = open(p, "rb").read()
got = hashlib.sha256(src).hexdigest()
if got != want:
    print("eq_wall.py differs from the installed bytes (sha256 %s..., recorded %s...)" % (got[:12], want[:12]))
    sys.exit(97)
mod = types.ModuleType("eq_wall")
mod.__file__ = p
sys.modules["eq_wall"] = mod
exec(compile(src, p, "exec"), mod.__dict__)
sys.exit(mod.main(sys.argv[3:]))' "$w_dir/eq_wall.py" "$w_sha" "$@" </dev/null 2>&1; }
      if ! "$W_PY" -I -c 'import tomllib' >/dev/null 2>&1 </dev/null; then
        warn "WALL checks skipped: $W_PY cannot import tomllib (the broker needs Python 3.11+): rerun ./install.sh"
      elif [ -z "$w_sha" ] || [ ! -f "$w_dir/eq_wall.py" ]; then
        warn "WALL checks skipped: no recorded broker (.stack-manifest.json eq_wall) or no $w_dir/eq_wall.py: rerun ./install.sh --with-eq-container"
      else
        w_rc=0; w_out=$(wall_py check --tunnel-root "$WT" --state "$WS" --policy "$w_pol" --verdicts "$WS/verdicts.jsonl" \
          --consents "$WS/consents.jsonl") || w_rc=$?
        if [ "$w_rc" = 97 ]; then
          warn "WALL config changed since install (policy or broker edited): re-run ./install.sh --with-eq-container; a frozen flags.json will refuse runs ($w_out)"
        else
          if [ "$w_rc" = 0 ]; then
            w_k=$(printf '%s\n' "$w_out" | sed -n 's/^policy  *PASS .*; kinds \(.*\)$/\1/p')
            case "$w_k" in none|"") w_k="default deny" ;; esac
            ok "WALL up: roots, policy ($w_k), stores intact"
          else
            fail "WALL check: $(printf '%s\n' "$w_out" | awk '$2 == "FAIL" { print; exit }' | tr -s ' ' | cut -c1-200)"
          fi
          w_cfg=$(wall_py config-hash --policy "$w_pol"); w_want=$(eqkv "$WS/status.env" EQ_WALL_CONFIG_SHA256)
          if [ -n "$w_want" ] && [ "$w_cfg" = "$w_want" ]; then ok "WALL config $(printf '%s' "$w_cfg" | cut -c1-12)"
          else warn "WALL config changed since install (policy or broker edited): re-run ./install.sh --with-eq-container; a frozen flags.json will refuse runs"; fi
        fi
      fi
      # the harness's own receipt (eq_harness.py isolation-probe), else the install-time probe of eq-container
      w_r=$(python3 -c 'import json, sys
try:
    r = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
v, a = r.get("result"), r.get("at_utc")
print("%s %s" % (v if v in ("PASS", "FAIL") else "?", a if isinstance(a, str) and a.isprintable() else "?"))' "$WS/tunnel_probe.json" 2>/dev/null)
      w_i=""; for eq_f in "$EQS"/results/tunnel.*.env; do
        [ -f "$eq_f" ] || continue
        case "$(eqkv "$eq_f" TUNNEL_RESULT)" in PASS) [ -n "$w_i" ] || w_i="PASS $(eqkv "$eq_f" TUNNEL_AT)" ;; *) w_i="FAIL $(eqkv "$eq_f" TUNNEL_AT)" ;; esac
      done
      case "$w_r" in
        "PASS "*) ok "WALL tunnel probe PASS (${w_r#PASS })" ;;
        "") case "$w_i" in
              "PASS "*) ok "WALL tunnel probe PASS at install (${w_i#PASS }); the harness writes its own receipt: eq_harness.py isolation-probe" ;;
              *) warn "WALL tunnel probe FAIL or missing: eq_harness.py isolation-probe" ;;
            esac ;;
        *) warn "WALL tunnel probe FAIL or missing: eq_harness.py isolation-probe" ;;
      esac
      # a broker left running with no harness run
      if have pgrep && w_pid=$(pgrep -f "eq_wall.py serve" 2>/dev/null | head -n 1) && [ -n "$w_pid" ] \
         && ! pgrep -f "eq_harness.py" >/dev/null 2>&1; then
        warn "WALL broker still running: pid $w_pid"
      fi
      # Claude's file tools are kept out of the stores, the receipt and the audit logs (settings.json deny)
      w_root="${XDG_STATE_HOME:-$HOME/.local/state}/claude-agent-stack"
      if grep -qF "\"Read(/$w_root/eq-wall/**)\"" "$C/settings.json" 2>/dev/null \
         && grep -qF "\"Edit(/$w_root/eq-wall/**)\"" "$C/settings.json" 2>/dev/null; then
        ok "WALL stores denied to agent file tools"
      else
        warn "WALL stores not denied to agent file tools (settings.json permissions.deny Read/Edit($w_root/eq-wall/**)): rerun ./install.sh"
      fi
      # ... and out of the tunnel root (each channel's token); a root moved by EQ_TUNNEL_DIR is not covered
      if grep -qF "\"Read(/$WT/**)\"" "$C/settings.json" 2>/dev/null \
         && grep -qF "\"Edit(/$WT/**)\"" "$C/settings.json" 2>/dev/null; then
        ok "WALL tunnel root denied to agent file tools"
      else
        warn "WALL tunnel root $WT not denied to agent file tools (the settings.json deny rules name ${XDG_CACHE_HOME:-$HOME/.cache}/claude-agent-stack/eq-tunnel only): rerun ./install.sh, or keep EQ_TUNNEL_DIR at that default"
      fi ;;
    *) warn "WALL: $WS/status.env holds no known EQ_WALL_STATUS: rerun ./install.sh --with-eq-container" ;;
  esac
fi

echo "== Anthropic plugins"
# install.sh step 10 records the Anthropic skill plugins it installed or found (plugins_installed) and
# the ones whose install failed (plugins_missing: offline, or the marketplace unreachable); read here
# with settings.json's enabledPlugins, no network and no claude call
python3 - "$C/.stack-manifest.json" "$C/settings.json" <<'PY'
import json, sys
def load(p):
    try:
        v = json.load(open(p))
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}
m, s = load(sys.argv[1]), load(sys.argv[2])
if "plugins_installed" not in m and "plugins_missing" not in m:
    print("  ok    no Anthropic plugin list in the manifest (installed with --no-plugins, or before 2026-10-04)")
    sys.exit(0)
on = s.get("enabledPlugins") if isinstance(s.get("enabledPlugins"), dict) else {}
ids = lambda k: [x for x in (m.get(k) or []) if isinstance(x, str)]
# one you installed by hand since (/plugin install) is no longer missing
missing = [x for x in ids("plugins_missing") if on.get(x) is not True]
# `claude plugin uninstall` drops the enabledPlugins entry; install.sh then leaves the plugin out
gone = [x for x in ids("plugins_installed") if x not in on]
off = [x for x in ids("plugins_installed") if on.get(x) is False]
ok = sorted({x for x in ids("plugins_installed") + ids("plugins_missing") if on.get(x) is True})
if missing:
    print("  WARN  not installed: %s (the installer was offline or the install failed) — rerun ./install.sh, "
          "or inside claude: /plugin install <name>@claude-plugins-official" % " ".join(missing))
if gone:
    print("  ok    uninstalled by you (./install.sh leaves them out): %s — to add one back: "
          "claude plugin install <id> --scope user" % " ".join(gone))
if ok or off:
    print("  ok    enabled: %s%s" % (" ".join(ok) or "none",
                                     "; disabled by you: " + " ".join(off) if off else ""))
if not (missing or gone or ok or off):
    print("  ok    none recorded (installed with --no-anthropic-plugins)")
PY

echo "== User-scope MCP servers"
if have claude; then
  out=$($T claude mcp list 2>&1 </dev/null || true)
  servers="exa jina wolfram huggingface"
  # wandb is registered only when it has a key (as in install.sh)
  [ "$("$C/bin/mcp-headers" wandb 2>/dev/null || echo '{}')" != "{}" ] && servers="$servers wandb"
  for s in $servers; do
    line=$(printf '%s\n' "$out" | grep -E "^$s:" | head -n1)
    # strip any query string from the URL claude mcp list echoes back (e.g. exa's ?tools=...,
    # or a plaintext key someone still has on a URL) before it reaches this terminal or a log
    line=$(printf '%s' "$line" | sed -E 's/\?[^[:space:]]*//')
    case "$line" in
      "") warn "$s not registered — rerun install.sh (or claude mcp add …)" ;;
      *"Needs authentication"*|*"needs auth"*) warn "$line — sign in with /mcp" ;;
      *"✘"*|*"✗"*|*"Failed"*) warn "$line" ;;
      *) ok "$line" ;;
    esac
  done
fi

echo "== Hardware"
if [ "$(uname)" = "Darwin" ]; then
  have sips && ok "sips present (the image limit scales images with it)" \
    || warn "sips not found — the image limit can't scale images"
fi
if [ "$(uname)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ]; then
  mem=$(sysctl -n hw.memsize 2>/dev/null); memgb=$(( ${mem:-0} / 1073741824 ))
  ok "Apple Silicon: $(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo unknown), ${memgb} GB unified memory — mlx-engineer runs locally"
else
  ok "not Apple Silicon — mlx-engineer needs a Mac with Apple Silicon"
fi
echo "done."
