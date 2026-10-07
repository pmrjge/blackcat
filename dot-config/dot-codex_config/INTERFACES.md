# dot-config/dot-codex_config (codex_config): internal interfaces

The contracts between the installer's modules: who writes which file, the staged CODEX_HOME layout,
each module's entry points, and the JSON files that pass between them. DESIGN.md is the spec; this
file only fixes the seams so the parts can be built separately and fit together. A change to a
contract here is made by the build lead, never by one module alone.

Conventions for every module:
- Stdlib only, Python ≥ 3.11 for the installer side (tomllib); the guard (`hooks/`) stays 3.9-compatible.
- Loaded **by path** (`importlib.util.spec_from_file_location`), never via `sys.path` (CWE-427).
  A module that needs a sibling loads it by path relative to its own `__file__`. The guard and its
  stub use `importlib.machinery.SourceFileLoader` (still by path): `importlib.util` pulls in
  `typing`, about 15 ms per hook call on Python 3.9.
- Paths written into generated files are absolute target paths (`<CODEX_HOME>/stack/...`), never
  stage paths. `ctx` below is a dict: `codex_home`, `home`, `stack` (= `<codex_home>/stack`),
  `state_dir` (guard state, default `${XDG_STATE_HOME:-$HOME/.local/state}/codex-agent-stack`),
  `profile_name` (default `codex`), `uv` (absolute path of uv, or `"uv"`), `skills_root`
  (`$HOME/.agents/skills`, or `None` for `--skills-root none`).
- Errors a user must fix are raised as `BuildError(message)` (each module defines its own
  `class BuildError(Exception)`) or, for CLIs, printed to stderr with exit 1. Usage errors exit 2.
  Unmapped or unknown input is an error, never a guess.
- Every module's docstring lists its seeded-bug proofs; `tests/mutations/<module>.json` holds them
  in the format of `tests/mutate.py`.
- Tests live in `dot-config/dot-codex_config/tests/test_<module>.py` and use `conftest.py` (owned by the lead:
  `load_lib`, `scratch_home`, the fake `codex` first on PATH). Shared helpers of one area go in
  `tests/_<area>_helpers.py`.

## 1. Files and owners

| Path under `dot-config/dot-codex_config/` | Owner (build part) |
|---|---|
| `lib/toml_emit.py`, `tests/conftest.py`, `tests/mutate.py`, `tests/run.sh`, `tests/fake-codex/codex`, `tests/fixtures/vendor/`, this file | lead (done) |
| `lib/codex_home.py`, `lib/codex_state.py`, `lib/source_snapshot.py`, `lib/skill_links.py`, `lib/config_region.py` | A foundation |
| `models.toml`, `lib/translate.py`, `lib/convert_agents.py`, `lib/convert_skills.py`, `lib/render_profile.py`, `templates/profile.base.toml` | B converters |
| `hooks/codex_guard.py`, `hooks/codex-hook`, `hooks/SUPPORT_FILES`, `lib/hook_defs.py`, `templates/guard.base.json` | C guard |
| `lib/convert_rules.py`, `lib/permissions.py`, `lib/requirements.py`, `tests/fake-codex/execpolicy_mirror.py` | F rules and permissions |
| `templates/AGENTS.block.md` (G), `templates/rules.md` (R), `templates/blackcat.md` | D texts |
| `probes/` | E probe kit |
| `lib/render.py`, `lib/doctor.py` | wave 2 (render) |
| `install.sh`, `tests/smoke.sh` | wave 2 (installer) |
| `README.md`, repository `README.md`/`CONFIG.md` pointers | wave 3 |

Nothing outside `dot-config/dot-codex_config/` changes, except the docs pointers in wave 3 and `.gitignore` if
needed. `install.sh`, `lib/`, `dot-config/dot-claude/` and `tests/` of the Claude installer are read-only inputs.

## 2. Staged CODEX_HOME (what one install produces)

```
codex.config.toml                 profile `codex` (whole file; §7.4 hooks.state carry-over)
codex-astra.config.toml           opt-in Astra profile (absent with --no-astra-profile)
config.toml                       user's file; only the two marked regions under --ide-default
rules/claude-agent-stack.rules    prefix rules (global)
AGENTS.md                         user's file; the stack's marked block (claude_md_block, NAME="AGENTS.md")
stack.env                         seeded 0600 from lib/stack.env.example only when missing
.stack-manifest.json              written by `codex_state.py manifest`
stack/agents/<role>.toml          one per agent but blackcat
stack/agents-astra/<role>.toml    the models.toml astra.agents roles
stack/skills/<skill>/...          listed skills (real files); never the 4 EXCLUDED_SKILLS (B2)
stack/skill-modules/<module>/...  hub modules (never in a scanned root)
stack/hooks/codex_guard.py        + the dot-config/dot-claude/hooks files named in hooks/SUPPORT_FILES
stack/bin/codex-hook              POSIX sh stub; stack/bin/stack-python is a link made after apply
stack/bin/with-stack-env, stack/bin/mcp-headers   adapted from dot-config/dot-claude/bin
stack/bin/codex-mcp-headers       dot-config/dot-codex_config/bin/codex-mcp-headers (Codex http_headers_helper)
stack/bin/magg-private, stack/magg/config.json    from dot-config/dot-claude (the magg
stack/mcp/...                     MCP server scripts from dot-config/dot-claude/mcp
stack/policy/agents.json          §4 (B)
stack/policy/guard.json           §5 (render, from C's template + F's credential set)
```
After apply (install.sh, outside the engine's scope): `stack/bin/stack-python` links to a REAL
interpreter binary (the uv-managed 3.13's realpath, or `sys.executable` of `/usr/bin/python3`; never
the `/usr/bin/python3` shim itself: it dispatches on argv[0] and exits 72, which denies every gated
call), then the guard and its support files are precompiled into `stack/hooks/__pycache__` once per
interpreter (stack-python, `/usr/bin/python3` when present):
`<py> -I -c 'import py_compile,sys; [py_compile.compile(f, doraise=True, invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH) for f in sys.argv[1:]]' <stack>/hooks/*.py`.

Role file names and `[agents.<role>]` keys use the agent's name. `models.toml` `[roles] name_style`
is `"hyphen"` (default) or `"underscore"` (`-` → `_` in role names, files and spawn text, for probe
P4/U2). Policy keys are always the canonical hyphenated names; the guard canonicalizes an incoming
`agent_type` by lowercasing and mapping `_` to `-` before any lookup.

## 3. Module entry points

### A foundation
- `codex_home.resolve(flag: str|None, env: dict, home: str, cwd: str, repos: list[str]) -> dict`
  with keys `path`, `real`, `source` (`flag|env|default`), `created` (bool, default only), `warn`
  (list). Raises `CodexHomeError` for every refusal of DESIGN §7.2 (`/`, `$HOME`, system dirs, inside
  `~/.claude` or a repo, the backup roots, `BAD_PATH_CHARS` or `'`; an explicit path that does not
  exist). Reuses install_state's `HOME_INSIDE`, `SYSTEM_INSIDE`, `HOME_EQUAL`, `_inside`.
- `codex_state.py` CLI (one process per call; loads `install_state.py` by path from
  `<this file>/../../lib/install_state.py`, i.e. from the snapshot, and sets SCOPE_DIRS, SCOPE_FILES,
  EXCLUDED, WRITE_THROUGH per DESIGN §7.2):
  - `home <flag-set 0|1> <flag> [repo...]` → `key<TAB>value` lines: `path`, `real`, `source`,
    `created` (0|1), `warn` (repeated). Exit 2 with the reason on refusal.
  - `stage <codex_home> <stage> [snap.json]`
  - `plan <codex_home> <stage> <report> <plan.json> [snap.json]` (prints the plan, Codex wording,
    `stack/agents/` and `stack/skills/` entries summarized)
  - `apply <codex_home> <stage> <plan.json> <backup_root> <commit> <out-file> [snap.json]` (writes
    the backup dir path to out-file)
  - `restore <codex_home> <which> <backup_root> <work> <commit> <home> [--dry-run] [--force]
    [--force-config]` (refuses when live `config.toml` sha256 differs from the manifest's
    `config_toml_sha256` unless `--force-config`; names `--no-ide-default`)
  - `validate <stage>` (TOML parses, required role keys, no `__PLACEHOLDER__`/`{{...}}`, policy JSON
    schemas §4 §5; exit 1 listing problems)
  - `manifest <stage> <commit> <work>` reads `<work>/links.json`, `<work>/hook-keys.json`,
    `<work>/regions.json`, `<work>/options.json` and writes `<stage>/.stack-manifest.json` (§6)
  - `retrust <old-manifest|-> <new-manifest>` prints one changed or new hook key per line (exit 0)
  - `latest <codex_home> <backup_root>`, `new-backup <codex_home> <backup_root> <commit>`
  - backup root: `${XDG_STATE_HOME:-$HOME/.local/state}/codex-agent-stack-backups`
- `source_snapshot.py <repo> <dest>` → copies the HEAD-tracked files of `dot-config/dot-codex_config/`,
  `lib/install_state.py`, `lib/claude_md_block.py`, `lib/stack.env.example`, `dot-config/dot-claude/` into
  `<dest>` (O_NOFOLLOW reads, the Claude installer's git hardening); prints the commit SHA. Exit 1 on
  a dirty or unreadable tracked file the same way `install.sh` does.
- `skill_links.py`:
  - `plan <links.json> <old-manifest|->` → exit 1 naming any foreign entry in the root (not in the
    old manifest's links, or not a symlink into `<codex_home>/stack/skills`); prints add/keep/remove.
  - `apply <links.json> <old-manifest|-> <backup-dir>` → creates/updates/removes only stack links,
    records previous state in `<backup-dir>/skill-links.json`.
  - `restore <backup-dir>` → undoes exactly what `apply` recorded.
- `config_region` (library): `find(data: bytes) -> dict` (`{"A": (start, end)|None, "B": ...}`,
  raises `RegionError` on duplicate or unbalanced markers), `splice(data: bytes, a_text: str,
  b_text: str) -> bytes` (A at the very start, B at the end; bytes outside unchanged),
  `remove(data: bytes) -> bytes`, `region_sha(data) -> {"A": hex|None, "B": hex|None}`,
  `conflicts(user_doc: dict, stack_doc: dict) -> list[str]` (dotted keys defined on both sides),
  `BEGIN_A, END_A, BEGIN_B, END_B` marker lines (DESIGN §7.6).

### B converters
- `models.toml`: `[tiers] opus = "gpt-6.1-sol"`, `sonnet = "gpt-6-luna"`; `[effort] luna_effort_offset
  = 1`, `levels = ["low","medium","high","xhigh","max"]`; `[accepted] "<model>" = [...]` (from the
  vendored catalog, `ultra` removed); `[astra] model = "gpt-6-astra"`, `agents = [...]` (six);
  `[blackcat] ...` if needed; `[roles] name_style = "hyphen"`.
- `translate.translate_text(text: str, label: str, ctx: dict, stats=None) -> tuple[str, list[str]]`
  → the translated text and problems (`"<label>:<line>: <token>"`); empty problems = clean. Extra ctx
  keys: `skill_modules` (frozenset of hub-module names; required when a text names
  `__CLAUDE_DIR__/skills/<x>`; convert_agents derives it from `convert_skills.classify(src)` when
  absent), `stack_repo` (optional; else "the claude-agent-stack repository"). No Codex text names the
  Claude stack's venvs (USER decision: `uv run --with ...` instead).
- `convert_skills.EXCLUDED_SKILLS` = claude-code-extensions, override-agent, stack-doctor, stack-tree
  (subject: Claude Code itself; USER decision): never staged, linked or listed. 127 listed, 89 modules.
  `convert_skills.SKILLS_MAX_CONTEXT_TOKENS` (6000) = the profile's `skills.max_context_tokens`.
- `convert_agents.convert(...)["mcp_servers"]` holds the agents' frontmatter servers only; the
  user-scope HTTP servers the Claude installer registers (exa, jina, wolfram, huggingface; wandb only
  when `WANDB_API_KEY` is set; `install.sh` `EXA_URL`/rows) are added by
  `convert_agents.user_scope_servers(ctx, with_wandb: bool) -> {id: table}` (url +
  `http_headers_helper = "<stack>/bin/codex-mcp-headers <id>"` where a key exists), pinned to
  install.sh's URLs by a contract test; render merges both (same id twice → BuildError).
- `render_profile.merge_hooks_state(*tables, owners=()) -> dict`: the union of the live
  `[hooks.state]` tables of `codex.config.toml` and `codex-astra.config.toml` (each key embeds its own
  file's path). `owners` pairs each table with its file's key prefix `"<codex_home>/<rel>:"`: on a
  clash the record from the file the key names wins; a clash no file owns stops the build. It is
  carried into every written profile file, including the comment-only `codex_ide` form (U1: Codex may
  write trust into the active profile file).
- render's foreign check (§7.4) is deep: any dotted path under a stack-written root of a live profile
  file (e.g. `mcp_servers.mine`, `hooks.PreToolUse[2]`) that this run would drop stops the build,
  naming it; `hooks.state` is exempt; a file whose semantic digest equals the old manifest's
  `options.profile_digests[rel]` (exactly what the last install wrote) is never foreign.
- `convert_agents.convert(src: str, ctx: dict, models: dict) -> dict` with keys `roles`
  (`{role: role_toml_dict}`), `astra_roles`, `agents_entries` (`{role: {"description",
  "config_file"}}`), `astra_entries`, `policy` (agents.json, §4), `mcp_servers` (`{id: table}` merged
  from frontmatter; `__UV__`/`__CLAUDE_DIR__` rendered from `ctx`), `blackcat` (`{"model", "effort",
  "instructions"}`), `report`. `src` is the snapshot root (holds `dot-config/dot-claude/`).
- `convert_skills.convert(src: str, stage_stack: str, ctx: dict) -> dict` writes
  `stage_stack/skills/` and `stage_stack/skill-modules/`; returns `listed`, `modules`,
  `budget_chars`, `budget_tokens`, `report`, `links` (`{skill: "<codex_home>/stack/skills/<skill>"}`).
- `render_profile.build(parts: dict, opts: dict) -> dict` with keys `codex` (profile dict),
  `codex_astra` (dict or None), `region_a` (root-keys dict), `region_b` (tables dict),
  `codex_ide` (comment-only profile text), `codex_astra_ide` (overlay dict). `parts`: `blackcat`,
  `rules_text` (R), `agents_entries`, `astra_entries`, `mcp_servers`, `permissions` (F),
  `hooks` (C `hooks_table`), `hooks_state` (carried over), `skills_max_context_tokens`.
  `opts`: the installer flags (`legacy_sandbox`, `no_escalation`, `no_mcp`, `with_rollout_budget`,
  `ide_default`, `no_astra_profile`). Serialization is toml_emit's.

### C guard
- `hooks/codex-hook <mode> [--scope global]`: finds Python (`<dir>/stack-python`, else
  `/usr/bin/python3`; none → stderr reason, exit 2) and execs `codex_guard.py` found at
  `<dir>/codex_guard.py` (flat managed layout) or `<dir>/../hooks/codex_guard.py`.
- `codex_guard.py <mode> [--scope global]`, modes `pre_tool_use`, `permission_request`,
  `post_tool_use`, `subagent_start`, `subagent_stop`, `user_prompt_submit`, `session_start`,
  `session_end`; `codex_guard.py --self-test` (exit 0/1). Reads the event JSON on stdin; reads
  `<guard dir>/../policy/{agents,guard}.json` or, flat, `<guard dir>/{agents,guard}.json`. Output
  exactly per the vendored `hooks_schema.rs` wire structs (`deny_unknown_fields`).
- `hooks/SUPPORT_FILES`: one `dot-config/dot-claude/hooks/<name>` per line that render copies next to the guard.
- `hook_defs.hooks_table(stub: str, scope: str = "profile") -> dict` → the `hooks` table (no
  `state`): one group per event (`PreToolUse`, `PermissionRequest`, `PostToolUse`, `SubagentStart`,
  `SubagentStop`, `UserPromptSubmit`, `SessionStart`, `SessionEnd`); command
  `/bin/sh '<stub>' <mode>` (+ ` --scope global`), timeout 10 (SessionEnd 3); matcher `".*"` on the
  three tool events. `hook_defs.hook_keys(source_file: str, table: dict) -> list[dict]` →
  `{"key": "<source_file>:<snake_event>:<group>:<handler>", "event", "fingerprint"}`; the
  fingerprint is sha256 of the canonical JSON of the event, matcher and handler.
- `templates/guard.base.json`: the caps and constants of §5 with their default values.

### F rules and permissions
- `permissions.credential_set(settings: dict, ctx: dict) -> {"paths": [...], "globs": [...]}` (abs
  paths and fnmatch globs; always includes `<codex_home>/auth.json` and `<codex_home>/stack.env`).
- `permissions.permission_profile(settings: dict, ctx: dict) -> dict` → the
  `[permissions.claude-agent-stack]` table (DESIGN §4.1 L1), `permissions.network_domains(settings)`.
- `convert_rules.render_rules(settings: dict, ctx: dict, opts: dict) -> tuple[str, list[dict]]` →
  the `.rules` text and its examples (`{"pattern", "decision", "match": [...], "not_match": [...]}`);
  `convert_rules.check_examples(rules_path: str, codex: str) -> list[str]` runs
  `codex execpolicy check` per example and returns disagreements.
- `requirements.py --codex-home CH --home H --src SRC --out DIR` → `DIR/requirements.toml` and
  `DIR/managed-hooks/`; prints the root commands; never writes outside DIR; never runs sudo.
- `tests/fake-codex/execpolicy_mirror.py`: the in-repo evaluator behind the fake `codex execpolicy
  check`, same argv and output shape as the real command (shape marked unverified if undocumented).

### wave 2
- `render.py --src SRC --stage STAGE --work WORK --codex-home CH --home H [--state-dir D]
  [--profile-name N] [--skills-root P|none] [--uv PATH] [--codex PATH|none] [--with-wandb]
  [--no-agents-md] [--no-mcp] [--legacy-sandbox] [--git-allow-rules] [--no-escalation]
  [--with-rollout-budget] [--ide-default|--no-ide-default] [--no-astra-profile] [--force]` → runs
  on a stage already made by `codex_state.py stage` (the live CODEX_HOME's in-scope files copied);
  clears and rewrites `STAGE/stack/`, writes the owned files (§2), seeds `stack.env` 0600 from
  `SRC/lib/stack.env.example` only when the stage has none, splices or removes the `config.toml`
  regions (refuses `--ide-default` on a symlinked `config.toml`; a region whose sha differs from the
  old manifest's stops the run with a diff unless `--force`; conflict check of DESIGN §7.6), carries
  `[hooks.state]` over and stops on any other foreign table in the live profile files (§7.4), runs
  `convert_rules.check_examples` with `--codex` (skipped with a warning under `none`), and writes
  `WORK/{build-report.json,links.json,hook-keys.json,regions.json,options.json}`. Exit 1 on any
  build error, 2 on usage. Never writes outside STAGE and WORK.
- `doctor.py --codex-home CH [--home H]` → hook trust state from `config.toml` and the profile files
  (tomllib, read-only), manifest hash drift, links; exit 1 if any stack hook key is untrusted.
- `install.sh` never passes `source_snapshot.py --allow-dirty`; `changes_since` diffs against the
  snapshot's commit, not `HEAD`.

## 4. `stack/policy/agents.json` (B writes, C reads)

```json
{
  "schema": 1,
  "agents": {
    "<role>": {
      "spawn": ["<role>", "..."],
      "apply_patch": true,
      "shell": true,
      "spawn_tool": true,
      "mcp": ["libdocs", "exa"],
      "readonly": false,
      "web_ingesting": false,
      "installer": false,
      "max_tool_calls": 170
    }
  },
  "blackcat": {"spawn": ["..."], "mcp": [], "max_shell_reads_per_prompt": 3},
  "builtin_types": ["default", "worker", "explorer"]
}
```
`apply_patch` = the Claude tools hold Write, Edit or NotebookEdit; `shell` = Bash; `spawn_tool` =
Agent; `mcp` = the `mcp__<server>` entries of `tools:`; `spawn` = the agent_guard POLICY row
(LEAVES → `[]`); `readonly` = READONLY_TYPES; `web_ingesting` = WEB_INGESTING_TYPES; `installer` =
INSTALLER_TYPES; `max_tool_calls` = `maxTurns` or null. A contract test asserts equality with
agent_guard's tables (imported by path in the test only).

## 5. `stack/policy/guard.json` (render writes from C's template + F + ctx, C reads)

```json
{
  "schema": 1,
  "codex_home": "/abs", "home": "/abs", "state_dir": "/abs", "stack": "/abs/stack",
  "protected_roots": ["<codex_home>", "<home>/.agents", "<state_dir>", "<backup_root>"],
  "credentials": {"paths": [], "globs": []},
  "toolsmith_wrapper": "<stack>/bin/stack-install",
  "caps": {"...": "C's template keys and defaults"},
  "image_max_px": 1920,
  "non_web_mcp_servers": [], "memory_write_tools": [], "computer_use_server": "..."
}
```
`<backup_root>` = `${XDG_STATE_HOME:-$HOME/.local/state}/codex-agent-stack-backups` (security review:
a forged `skill-links.json` there could plant links on restore). render emits exactly the template's
keys (`templates/guard.base.json`) plus the ctx and credential keys above. In `--scope global` the guard reads the `guard.json` beside
itself first and never `agents.json`.

## 6. Work files and the manifest

- `links.json`: `{"root": "<abs>|null", "links": {"<skill>": "<abs target>"}}`.
- `hook-keys.json`: `[{"key", "event", "fingerprint", "source"}]` for every profile and region source.
- `regions.json`: `{"ide_default": bool, "A": hex|null, "B": hex|null, "config_toml_sha256": hex}`.
- `options.json`: the resolved flags and ctx.
- `.stack-manifest.json`: `{"format": 1, "installer": "codex_config", "commit", "files": {rel:
  sha256}, "hooks": [...hook-keys], "links": {...}, "ide_default", "regions", "config_toml_sha256",
  "profile_name", "astra": bool, "options": {...}}` plus whatever keys install_state's engine reads
  from a manifest (A keeps them compatible).
