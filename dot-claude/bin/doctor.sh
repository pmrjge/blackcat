#!/usr/bin/env bash
# Health check for the Claude Code multi-agent stack. Read-only: never prints key values.
C="$(cd "$(dirname "$0")/.." && pwd)"
ok(){ printf '  ok    %s\n' "$*"; }
warn(){ printf '  WARN  %s\n' "$*"; }
fail(){ printf '  FAIL  %s\n' "$*"; }
have(){ command -v "$1" >/dev/null 2>&1; }
if have timeout; then T="timeout 90"; elif have gtimeout; then T="gtimeout 90"; else T=""; fi
MIN=2.1.271
# portable "a <= b" for dotted versions (BSD sort on older macOS has no -V)
version_ge(){ [ "$(printf '%s\n%s\n' "$2" "$1" | sort -t. -k1,1n -k2,2n -k3,3n | head -n1)" = "$2" ]; }

if [ -n "${CLAUDE_CONFIG_DIR:-}" ] && [ "$(cd "$CLAUDE_CONFIG_DIR" 2>/dev/null && pwd)" != "$C" ]; then
  warn "CLAUDE_CONFIG_DIR=$CLAUDE_CONFIG_DIR differs from this script's install dir ($C) — checking $C"
fi

echo "== Claude Code"
if have claude; then
  v=$(claude --version 2>/dev/null </dev/null | awk '{print $1}')
  if [ -n "$v" ] && version_ge "$v" "$MIN"; then ok "claude $v"; else warn "claude ${v:-?} < $MIN — run: claude update"; fi
else fail "claude not found — install: curl -fsSL https://claude.ai/install.sh | bash"; fi

echo "== Binaries"
# Agents' Bash calls use bare names (uv run, uvx semgrep, node, git): those must be on this PATH —
# run from /stack-doctor it is the PATH every agent gets. MCP commands are the absolute paths
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
[ -x "$C/venvs/ml/bin/python" ] && ok "ML venv ($C/venvs/ml)" || ok "ML venv not installed (optional: ./install.sh --with-ml)"
for f in with-stack-env mcp-headers magg-private claude-ultracode; do [ -x "$C/bin/$f" ] && ok "bin/$f" || fail "bin/$f missing or not executable — rerun install.sh"; done
for n in claude-ninja claude-god; do
  if [ "$(readlink "$HOME/.local/bin/$n" 2>/dev/null)" = "$C/bin/claude-ultracode" ]; then
    have "$n" && ok "$n (${n#claude-}-coder at ultracode)" || warn "$n is in ~/.local/bin, which isn't on PATH — open a new terminal"
  else
    warn "$n missing: rerun install.sh (without --no-profile), or use $C/bin/claude-ultracode ${n#claude-}-coder"
  fi
done
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
for name, entry in sorted(catalog.items()):
    if isinstance(entry, dict) and isinstance(entry.get("command"), str):
        need(entry["command"], "magg catalog: " + name, True)
for path, agents in sorted(bad.items()):
    level = "WARN" if path.endswith("/huetension") else "FAIL"   # designer works without huetension
    print("  %s  %s missing — MCP server of %s won't start (rerun ./install.sh to re-render)"
          % (level, path, ", ".join(agents) if len(agents) <= 3 else "%d agents" % len(agents)))
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
      JUPYTER_URL|JUPYTER_TOKEN|MLFLOW_TRACKING_URI|MOTHERDUCK_TOKEN|LEAN_PROJECT_PATH) ;;
      *) printf '%s\n' "$exported" | grep -q "^export $k=" || own="$own $k" ;;
    esac
  done
  [ -z "$own" ] || ok "your own stack.env variables not exported to shells:$own (add them to STACK_EXPORT if a CLI tool needs them)"
  expanding=""
  for k in $(grep -E '^[[:space:]]*(export[[:space:]]+)?[A-Za-z_][A-Za-z0-9_]*=.*[$]' "$C/stack.env" 2>/dev/null \
      | sed -E 's/^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)=.*/\2/'); do
    case "$k" in
      LUMENFALL_*|OPPER_*|OPENROUTER_*|IMAGE_STUDIO_*|LIBDOCS_*|GITHUB_TOKEN|EXA_API_KEY|JINA_API_KEY|SPIDER_API_KEY|HF_TOKEN|WANDB_API_KEY) ;;  # expanded by the stack's Python servers, or checked above
      JUPYTER_URL|JUPYTER_TOKEN|MLFLOW_TRACKING_URI|MOTHERDUCK_TOKEN|LEAN_PROJECT_PATH)
        warn "$k uses \$VAR, which with-stack-env doesn't expand, so magg never gets it: write the value out in $C/stack.env" ;;
      *) expanding="$expanding $k" ;;
    esac
  done
  [ -z "$expanding" ] || ok "never exported to shells (values with \$VAR aren't expanded):$expanding — set them in your shell rc file if a CLI tool needs them"
else fail "missing $C/stack.env — cp stack.env.example $C/stack.env && chmod 600"; fi
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

echo "== Agents"
policy_json=$(python3 "$C/hooks/agent_guard.py" --print-policy 2>/dev/null || true)
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
    print("  ok    %d/%d agent files present (router + %d specialists)" % (len(agents), len(agents), len(agents) - 1))
if "senior-coder" in extra:
    extra.remove("senior-coder")
    print("  WARN  agents/senior-coder.md is the stack's old name for main-coder, kept because you edited it:"
          " move your changes into main-coder.md and delete it")
if extra:
    print("  WARN  your own agents, unreachable from the router and the stack's agents (the spawn policy"
          " lists only the stack's): %s — run one with `claude --agent <name>`" % " ".join(extra))
print("  ok    copies allowed for: " + ", ".join(p.get("self_spawn", [])))
PY
fi
[ -f "$C/rules/claude-agent-stack.md" ] && ok "global rules: rules/claude-agent-stack.md" \
  || fail "rules/claude-agent-stack.md missing — the agents run without the stack's rules: rerun install.sh"
[ -f "$C/CLAUDE.md.new" ] && warn "CLAUDE.md.new is an old render of the stack's global rules (they now load from rules/claude-agent-stack.md): delete it"
if [ -f "$C/CLAUDE.md" ] && grep -qE '^# (Global rules — every agent reads this|claude-agent-stack — global rules)' "$C/CLAUDE.md"; then
  warn "CLAUDE.md still holds the stack's old global rules, which now load from rules/claude-agent-stack.md: delete that part of CLAUDE.md"
fi
# Files you edited are kept; the stack's newer render waits next to each as <file>.new.
pending="$( (cd "$C" && find agents rules skills -name '*.new' -type f 2>/dev/null) | sort | tr '\n' ' ')"
[ -z "$pending" ] && ok "no pending .new renders" \
  || warn "pending .new renders (your edited files were kept; merge them, then delete the .new): $pending"

echo "== Hooks"
[ -f "$C/hooks/agent_guard.py" ] && ok "hooks/agent_guard.py" || fail "hooks/agent_guard.py missing — rerun install.sh"
if [ -f "$C/hooks/agent_guard.py" ]; then
  if out=$(python3 "$C/hooks/agent_guard.py" --self-test 2>&1); then
    ok "agent_guard.py --self-test: $out"
  else
    fail "agent_guard.py --self-test failed: $out"
  fi
fi
# Run the hook commands exactly as Claude Code will (from settings.json and router.md), on events that
# must be denied. A hook that cannot start is a non-blocking error in Claude Code: every gate open.
if [ -f "$C/settings.json" ] && [ -f "$C/hooks/agent_guard.py" ]; then
  python3 - "$C/settings.json" "$C/agents/router.md" <<'PY'
import json, os, re, subprocess, sys, tempfile
settings, router = sys.argv[1], sys.argv[2]
try:
    hooks = json.load(open(settings)).get("hooks", {})
except (OSError, ValueError):
    hooks = {}
cmds = sorted({h.get("command") for g in hooks.get("PreToolUse", []) if isinstance(g, dict)
               for h in g.get("hooks", []) if "agent_guard.py" in str(h.get("command"))
               and "image-limit" not in str(h.get("command"))})
icmds = sorted({h.get("command") for g in hooks.get("PostToolUse", []) if isinstance(g, dict)
                for h in g.get("hooks", []) if "image-limit" in str(h.get("command"))})
rcmd = None
try:
    m = re.search(r'(?m)^\s+command:\s*"(.*agent_guard\.py.*)"\s*$', open(router).read())
    rcmd = json.loads('"%s"' % m.group(1)) if m else None
except (OSError, ValueError):
    pass
state = tempfile.mkdtemp(prefix="stack-doctor-")
env = dict(os.environ, XDG_STATE_HOME=state, STACK_POLICY="on")
probes = [("settings.json PreToolUse(Agent)", cmds,
           {"session_id": "doctor", "hook_event_name": "PreToolUse", "tool_name": "Agent",
            "agent_id": "doctor-scout", "agent_type": "scout", "tool_use_id": "toolu_doctor",
            "tool_input": {"subagent_type": "god-coder", "prompt": "x", "description": "x"}}),
          ("router.md router-guard", [rcmd] if rcmd else [],
           {"session_id": "doctor", "hook_event_name": "PreToolUse", "tool_name": "Bash",
            "agent_type": "router", "prompt_id": "doctor", "tool_input": {"command": "true"}})]
for label, commands, ev in probes:
    if not commands:
        print("  FAIL  %s: no agent_guard.py hook command found — rerun install.sh" % label)
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
  python3 - "$C/settings.json" "$C/skills" <<'PY'
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
agent = s.get("agent")
if agent == "router":
    ok("main thread agent: router")
    # an agent file's effort applies only to subagents: the router runs at the session's level
    lvl = ((s.get("modelSettings") or {}).get("claude-sonnet-5") or {}).get("effortLevel")
    if lvl in ("low", "medium"):
        ok("router effort: %s (saved for Sonnet 5)" % lvl)
    else:
        warn("router effort: %s — the router's file says low, but a main-thread agent runs at the session's "
             "level: run /effort low once in a router session (saved for Sonnet 5)"
             % (lvl or "Sonnet 5's default, high"))
elif agent:
    ok("main thread agent: %s (your choice; the stack's router: claude --agent router)" % agent)
else:
    warn("no main thread agent — rerun install.sh for the stack's router, or set \"agent\": \"claude\" to opt out")
(ok if s.get("autoCompactEnabled", True) is True else fail)("autoCompactEnabled=%s" % s.get("autoCompactEnabled", "default(true)"))
(ok if s.get("autoCompactWindow") == 800000 else warn)("autoCompactWindow=%s (stack: 800000)" % s.get("autoCompactWindow"))
env = s.get("env", {})
want = {"CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "3", "MCP_DISCOVERY_CACHE": "1"}
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
(ok if conc and conc >= 20 else warn)("CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS=%s" % env.get("CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS", "20 (default)"))
for bad in ("DISABLE_AUTO_COMPACT", "DISABLE_COMPACT", "CLAUDE_CODE_AUTO_COMPACT_WINDOW", "CLAUDE_CODE_DISABLE_1M_CONTEXT",
            "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE", "CLAUDE_CODE_BLOCKING_LIMIT_OVERRIDE",
            "CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "CLAUDE_CODE_EFFORT_LEVEL"):
    if bad in env:
        warn("settings env sets %s=%s — it overrides the stack's compaction/model/effort settings" % (bad, env[bad]))
    if os.environ.get(bad):
        warn("your shell exports %s=%s — it overrides the stack's compaction/model/effort settings" % (bad, os.environ[bad]))
hooks = s.get("hooks", {})
events = ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "SubagentStart", "SubagentStop",
          "PostToolUseFailure", "PermissionDenied", "StopFailure"]
missing_ev = [ev for ev in events if not any("agent_guard.py" in json.dumps(g) for g in hooks.get(ev, []))]
(fail if missing_ev else ok)("guard hooks wired for all %d events" % len(events) if not missing_ev else "guard hooks missing for: " + ", ".join(missing_ev))
post = {g.get("matcher") for g in hooks.get("PostToolUse", []) if isinstance(g, dict) and "agent_guard.py" in json.dumps(g)}
(ok if any("TaskStop" in (m or "") for m in post) else warn)(
    "PostToolUse also watches TaskStop (a stopped agent releases its locks)" if any("TaskStop" in (m or "") for m in post)
    else "PostToolUse guard matcher lacks TaskStop — rerun install.sh")
cmds = {h.get("command", "") for gs in hooks.values() for g in gs if isinstance(g, dict) for h in g.get("hooks", [])
        if "agent_guard.py" in str(h.get("command"))}
bare = sorted(c for c in cmds if c.split()[0].strip('"') in ("python3", "python"))
(warn if bare else ok)("guard hooks call an absolute interpreter" if not bare
                       else "guard hooks call a bare python3 (a broken pyenv/asdf shim would disable them) — rerun install.sh")
matchers = {g.get("matcher") for g in hooks.get("PreToolUse", []) if isinstance(g, dict)}
exp = {"Agent", "SendMessage", "mcp__computer-use__.*"}
(ok if exp <= matchers else fail)("PreToolUse matchers: " + ("all 3 present" if exp <= matchers else "missing " + ", ".join(sorted(exp - matchers))))
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
hk = str(env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL", os.environ.get("ANTHROPIC_DEFAULT_HAIKU_MODEL", "")))
(ok if hk and "haiku" not in hk.lower() else warn)(
    "haiku alias and background tasks: %s" % hk if hk and "haiku" not in hk.lower() else
    "background tasks and the haiku alias run on Haiku (ANTHROPIC_DEFAULT_HAIKU_MODEL=%s) — the stack sets claude-sonnet-5" % (hk or "unset"))
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
budget = int(1000000 * 3 * frac)
n_sk, chars = 0, 0
for root, _dirs, files in os.walk(skills_dir):
    if "SKILL.md" not in files:
        continue
    head = open(os.path.join(root, "SKILL.md"), encoding="utf-8", errors="replace").read().split("---", 2)
    if len(head) < 3 or re.search(r"(?m)^disable-model-invocation:\s*true", head[1]):
        continue
    m = re.search(r"(?m)^description:\s*(.*)$", head[1])
    n_sk += 1
    chars += len(os.path.basename(root)) + 5 + min(len(m.group(1).strip()) if m else 0, 1536)
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
        problems.append("%s: model %s — the stack uses claude-sonnet-5 instead of Haiku" % (name, model.group(1)))
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
lsp=""; for b in pyright-langserver typescript-language-server rust-analyzer sourcekit-lsp clangd gopls; do
  case "$b" in rust-analyzer) rust-analyzer --version >/dev/null 2>&1 && lsp="$lsp $b" ;; *) have "$b" && lsp="$lsp $b" ;; esac
done
[ -n "$lsp" ] && ok "language servers on PATH:$lsp (code-intelligence plugins start them on demand)" || warn "no language servers on PATH — ./install.sh --with-lsp"
# The Playwright MCP (browser-operator, frontend-engineer, verifier) drives Google Chrome by default.
[ -d "/Applications/Google Chrome.app" ] && ok "Google Chrome found (Playwright MCP)" \
  || warn "Google Chrome not found — the Playwright MCP of browser-operator, frontend-engineer and verifier drives it: npx @playwright/mcp@0.0.82 install-browser chrome"

echo "== User-scope MCP servers"
if have claude; then
  out=$($T claude mcp list 2>&1 </dev/null || true)
  servers="exa jina wolfram huggingface"
  # wandb is registered only when it has a key (as in install.sh)
  [ "$("$C/bin/mcp-headers" wandb 2>/dev/null || echo '{}')" != "{}" ] && servers="$servers wandb"
  for s in $servers; do
    line=$(printf '%s\n' "$out" | grep -E "^$s:" | head -n1)
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
