# claude-agent-stack optimisation: phases 1–3

Phases 1–2 as of 2026-10-02 18:34; phase 3 as of the date in its section. Repo `/Users/pmrj/ZDone/claude-agent-stack`: local `main` fast-forwarded to `6622116`, the tip of the worktree branch `golden/agents-workflow-token-optimization-573fd0`. Nothing is pushed.
- Phase 1: `75dfdfc..1a38c77` (7 commits).
- Phase 2: `1a38c77..ad22962` (19 commits; review fixes `24beb76`, name-only removal `96d3a52`, README `ad22962`).
- Phase 3: `ad22962..6622116` (11 commits).

Facts marked *(builder report)* come from agent reports and can't be re-derived from files. Sections 1–10 describe the state at ad22962; where phase 3 changed something, the note "→ P3" points to the current value.

## 1. Subagent labels (5a4a01a, fixes 345854f)

| Item | Behaviour |
|---|---|
| Rewrite | PreToolUse on `Agent` sets `description` to `<subagent_type>: <task>` through `updatedInput`, once per call. A caller's own label is kept. Costs 0 prompt tokens. |
| Mode | `STACK_AGENT_LABEL` = `description` (default), `name` (an unnamed child becomes `<type>-<n>`, which SendMessage can address) or `off` |
| Ledger | Strips the label, so ledger rows read the same in every mode |
| Start time | `STACK_AGENT_STARTED=1`: SubagentStart `additionalContext` gives "Started YYYY-MM-DD HH:MM (local)", which the clean-finish line uses |
| Review | 3 LOW ledger bugs (full ledger task, caller names kept, bare label), fixed in 345854f *(builder report)* |

## 2. Review loop rules (18b8da1, 1a38c77)

In the global rules ("Self-check and review", "Reporting"):

| Rule | Content |
|---|---|
| Self-check | Once: tests, linters, types on what changed, diff vs done-when, ends with `date '+%F %R'` |
| Review triggers | Security, data loss, concurrency, public API/schema, diff > ~300 lines or 8 files, untested numeric/proof core, no tests, CI/IaC/hooks/permissions, published output. One reviewer per class. |
| Round trips | Only with evidence: failing command with output, reproduced bug, verified discrepancy (file:line or quote), or a missing required item. Nothing verifiably wrong = PASS, no follow-up (also orchestrator step 7). Ambiguity: state the assumption once and proceed. |
| Escalation | Two evidence-backed failing rounds → one tier up, or STATUS: partial with a dossier |
| Clean finish | `<input ≤10 words> · <YYYY-MM-DD HH:MM> · <agent type>`, then a result of ≤5 lines. Otherwise the STATUS block. A report with no STATUS line is relayed unchanged. |

## 3. Agent roster: 37 (75dfdfc) → 39 (1a38c77) → 56 (ad22962)

Final families from the README: role 20, language engineers 7, domain experts 25, helpers 4. No agent was removed, and no existing agent's model or effort changed.

| New agent | Phase | Family | Model · effort | maxTurns | Inline MCP |
|---|---|---|---|---:|---|
| proof-checker | 1 | role (read-only) | Opus 5.5 · xhigh | 80 | lean |
| vfx-td | 1 | domain | Opus 5.5 · high | 170 | — |
| security-engineer | 2 | domain | Opus 5.5 · high | 150 | libdocs |
| biochem-, embedded-, game-, hpc-engineer | 2 | domain | Opus 5.5 · high | 170 | libdocs |
| mobile-engineer | 2 | domain | Opus 5.5 · medium | 170 | libdocs, mobilebuild |
| rust-, haskell-, julia-, go-, python-, jvm-, node-engineer | 2 | language | Opus 5.5 · high | 170 | libdocs |
| db-engineer | 2 | helper | Sonnet 5.5 · high | 120 | postgres, mongodb |
| test-engineer | 2 | helper | Sonnet 5.5 · medium | 100 | — |
| localizer | 2 | helper | Sonnet 5.5 · medium | 80 | — |
| build-fixer | 2 | helper | Sonnet 5.5 · low | 60 | — |

db-engineer and localizer are reached through their family heads; BlackCat's allowlist names 51 agents.

**maxTurns changes in phase 1.** New values are max(target, 1.5 × p90), with p90 measured over 23 local transcripts: cg-artist 170→150, claude-code-engineer 180→190, code-reviewer 120→80, data-engineer 190→150, devops-engineer 160→140, doc-specialist 120→100, frontend-engineer 190→170, main-coder 300→240, mcp-broker 80→60, orchestrator 250→200, plan-reviewer 80→60, planner 80→60, quantum-engineer 180→160, researcher 150→130, scout 30→20, security-auditor 120→100, verifier 150→140, writer 120→80. Phase 2 left all existing values alone. → P3: claude-code-engineer 120, coder 150, scout 11.

## 4. Skills

Counts come from `git ls-tree -r <rev> dot-claude/skills` (`/SKILL.md$`, `/references/`), with hubs and modules from `test_skill_modules.hubs_and_modules()` (run on a `git archive` copy for 24beb76).

| | 75dfdfc | 1a38c77 | 24beb76 | ad22962 | P3 (6622116) |
|---|---:|---:|---:|---:|---:|
| Skills | 93 | 93 | 256 | 248 | 212 |
| Hubs (`## Modules` table) | 0 | 0 | 33 | 33 | 24 |
| Modules | 0 | 0 | 141 | 133 | 98 |
| Standalone | 93 | 93 | 82 | 82 | 90 |
| `references/*.md` files | 0 | 0 | 92 | 99 | 185 |
| Listed with description | all | all | 40 (216 name-only) | all 248 | 128 (83 modules hidden, 1 user command) |

**Merged skills.** Eight skills were folded into others (4b6beac, 3622a52, ffaf597): l10n-qa → `l10n-catalogs/references/qa-checks.md`, geo-crs-gdal → `geo-raster-vector/references/crs-gdal.md`, write-reports → `technical-writing/references/reports.md`, net-protocols → `self-hosting-ops/references/net-protocols.md`, mcp-ts-server → `mcp-server-craft/references/typescript-server.md`, viz-interactive → `data-visualization/references/interactive.md`, test-mutation → `test-strategy/references/mutation.md`, sec-local-servers → `sec-hardening/SKILL.md` (§ Local servers).

**Descriptions.** Every skill has an explanatory description of at most 140 characters that starts with its trigger. No skill is preloaded through `skills:` frontmatter. Agents carry one-line "load X when Y" pointers.

## 5. MCP servers and plugins

| Category | Servers |
|---|---|
| Inline, starting with their agent | **Phase 1:** proof-checker → `lean` (lean-lsp-mcp 0.30.0). **Phase 2:** db-engineer → `postgres` (postgres-mcp 0.3.0, `--access-mode=restricted`) and `mongodb` (3.0.5, `--readOnly`, telemetry off); mobile-engineer → `mobilebuild` (MobileBuildMCP 2.7.1, telemetry off); `libdocs` on 13 new engineers |
| magg catalog, 13 → 23, every call asks first | New: android, biomcp, gis, godot, grafana (`--disable-write`), kubernetes (read-only, Secrets denied, `magg/k8s-mcp.toml`), mobile, pubchem, sec-edgar, serial |
| Documented only | unity-mcp, Unreal_mcp, AWS aws-api-mcp-server, Azure MCP, gcloud-mcp, Alpha Vantage, KiCAD-MCP-Server, embedded-debugger-mcp, slurm-mcp-server, lara-mcp, houdini-mcp, `gopls mcp` |
| Rejected | lamaalrajih/kicad-mcp, qgis_mcp, whisper-mcp, local-stt-mcp, mcp-music-analysis, runreal/unreal-mcp, tandemai mcp-rdkit, Flux159 mcp-server-kubernetes, unlicensed SLURM servers |
| User scope | Unchanged: exa, jina, wolfram, huggingface, wandb |
| LSP plugins | Unchanged: 8 official (pyright, typescript, rust-analyzer, swift, clangd, gopls, jdtls, kotlin) and 4 from the stack marketplace (haskell, julia, lean, metals), each enabled when its binary works; 0 listing chars |
| Skill plugins | document-skills, math-olympiad, skill-creator: enabled and named by pointers (2,919 listing chars). Duplicates of claude.ai skills are disabled. On demand: `/plugin enable <id>` or a project's `enabledPlugins`. |

`mcp__lean` was intentionally left out of `permissions.allow`. Vetting details are in `agents-p2/mcp-vetting.md`, with the user-facing table in `mcp_servers.md` § Engineering domains.

## 6. On-demand and automatic loading

Full matrix: [CONFIG.md §5, "On demand and automatic"](../../CONFIG.md). Only skill descriptions and the tool names of user-scope MCP servers cost context while idle.
- Skills (248): loaded by a description or a "load X when Y" pointer, or by name. The listing is paid on every spawn. → P3: 212 skills, of which 83 hub modules are Read by path.
- Inline MCP (17 servers): starts and stops with its agent; costs 0 elsewhere.
- magg catalog (23): mcp-broker mounts a server when an agent's pointer applies; 0 until mounted.
- LSP plugins: start on a matching file; 0 listing. Skill plugins: enabled and named by pointers.

## 7. Prompt budget

Regenerated with `uv run --script tests/prompt_budget.py --head <rev> --json` (current script). Units are chars, tokens ≈ chars / 3. Two figures differ from the budget files: BlackCat per spawn at 75dfdfc is 53,920, not 54,472 (its listing now comes from its allowlist), and bodies at 1a38c77 are 67,539, not 67,446 (step 7 landed after that measurement).

| Quantity | 75dfdfc | 1a38c77 | Δ P1 | 24beb76 (name-only) | ad22962 | Δ P2 |
|---|---:|---:|---:|---:|---:|---:|
| Descriptions | 11,291 | 5,806 | −48.6% | 7,325 | 7,325 | +26.2% |
| Bodies | 85,151 | 67,539 | −20.7% | 93,012 | 93,839 | +38.9% |
| Rules | 11,630 | 12,198 | +4.9% | 12,198 | 12,198 | 0 |
| Skill listing | 17,645 | 17,647 | 0 | 10,693 | 30,782 | +74.4% |
| Agent listing | 16,892 | 11,665 | −30.9% | 15,330 | 15,330 | +31.4% |
| BlackCat listing | 16,340 | 11,259 | −31.1% | 14,550 | 14,550 | +29.2% |
| BlackCat body | 8,305 | 5,195 | −37.4% | 5,190 | 5,190 | −0.1% |
| BlackCat per spawn | 53,920 | 46,299 | −14.1% | 42,631 | 62,720 | +35.5% |
| Per-spawn mean | 42,817 | 39,146 | −8.6% | 35,136 | 55,240 | +41.1% |
| Mean, agents with the Agent tool | 48,557 | 43,270 | −10.9% | 39,944 | 60,053 | +38.8% |
| Leaf mean | 29,772 | 30,211 | +1.5% | 23,419 | 43,510 | +44.0% |

Base agents at ad22962 have a per-spawn mean of 54,874 (1.402×) and bodies of 70,762 (1.048×, gate 1.05) (`agents-p2/budget-final.md`). The gates were reset to the measured value + 2%: agent listing 1.34×, BlackCat listing 1.31×, skill listing 1.77×, per-spawn mean 1.42×.

**The name-only decision and its cost.** The user decided that no skill is name-only and that every description is explanatory (cap 140). Measured cost: the skill listing went from 10,693 to 30,782 chars, and the per-spawn mean from 35,136 to 55,240 (+20,104 chars, ≈ +6,700 tokens on every spawn). Phase 3 is meant to recover this.

`skillListingBudgetFraction` went from 0.012 to 0.0156 because the listing budget is shared with other skill sources: stack 31,028 + plugins 2,919 + bundled ~3,950 + claude.ai ~7,300 = 45,197, against a budget of 46,800 (3.5% margin). Over the budget, the least-used skills lose their descriptions silently. → P3: d2bc994 set it back to **0.012** (36,000 chars) for stack 14,564 + non-stack 14,169, with 25% margin (`dot-claude/settings.json`).

## 8. Tests and lint per merge

| Merge | Lint | Self-test | prompt_budget --check | pytest |
|---|---|---|---|---|
| 1a38c77 (phase 1) | ok | ok | — | 2496 passed, 2 sandbox-only failures *(builder report)* |
| 24beb76 (phase 2 + review fixes) | ok | ok | ok | verifier pass, 2506 passed *(builder report)*. `agents-p2/plan.md` records 2508 passed / 2 sandbox failures. |
| 96d3a52 (step 2) | ok | ok | ok | 2508 passed, 2 failed: image_studio's `stack.env` read was denied by the sandbox, and test_protected_paths f4 (`cd /tmp`) also fails at 1a38c77 *(builder report)* |
| ad22962 (README) | ok (re-run today) | — | exit 0 (re-run today) | not run (docs-only commit) |

Review findings, all fixed:
- Phase 1: a `lake env` read-only bypass (`lake env rm -rf …` passed), fixed in 5a4a01a with tests; 3 LOW ledger bugs, fixed in 345854f.
- Phase 2: HIGH, `k8s-mcp.toml` was never installed; LOW, the npm prefetch cached only the top-level package. Both fixed in 24beb76.

README went from 196,720 to 45,580 chars.

## 9. Unverified

- Desktop tasks-pane title showing `type: task`; only the transcript row `type(description)` is documented.
- `tests/install_smoke.sh` never ran (the sandbox blocks `mktemp`); the name-only live probe never ran (now moot).
- The bundled (~3,950) and claude.ai (~7,300) listing sizes are estimates.
- SubagentStart re-injection on a resumed subagent comes from a search summary, not a quote from the docs.
- MCP: telemetry of godot, sec-edgar and gis is unaudited beyond their READMEs; whether the sandbox `~/.kube`/`~/.aws` read-deny reaches MCP children; what changed in mongodb 3.0.5.
- maxTurns rests on 23 transcripts; the 2 pytest failures weren't re-run outside the sandbox.
- Known gap, left unchanged: read-only agents don't inspect scratch `.lean` contents (`#eval`, `run_cmd`, `lean --run`); `mcp__lean__*` calls are outside the Bash read-only check.

## 10. User steps

1. Outside the sandbox, in the repo: `bash tests/install_smoke.sh`, then `./install.sh`, then restart Claude Code.
2. Lean: install elan, build a Lean 4 + Mathlib Lake project, and set `LEAN_PROJECT_PATH` in `~/.claude/stack.env`. Optionally add `mcp__lean` to `permissions.allow`; that loosens a guard and is your decision.
3. Set these in `stack.env` as needed: `DATABASE_URI` and `MDB_MCP_CONNECTION_STRING` (db-engineer), `GODOT_PATH`, `GRAFANA_URL` and `GRAFANA_SERVICE_ACCOUNT_TOKEN` (a Viewer token), `SEC_EDGAR_USER_AGENT`, `NCBI_API_KEY` (optional), `QISKIT_IBM_TOKEN`, `JUPYTER_URL`/`JUPYTER_TOKEN`, `MLFLOW_TRACKING_URI`, `MOTHERDUCK_TOKEN`. Kubernetes uses your kubeconfig. For serial: `cargo install serial-mcp@0.9.3 --locked`.
4. Check the Desktop label: spawn any subagent and see whether the tasks pane shows `type: task`.
5. Push `main` (ad22962) yourself. Agents never push.

## Phase 3

As of 2026-10-02. Commits:
- ff4ed6e: Q1, agents.
- 68c229b, 8402e76, 3cd7f08: Q2, skills a–m.
- 3f526c3: Q3, skills n–z and rules.
- 364cc6a: Q4, gates and stale references.
- d2bc994: skill routing B1x+C.
- 558fb10: reviewer gate restored.
- e696833: Q7, Agent SDK.
- 66c6d8c: README counts.
- 6622116: stack_sdk.py review fixes. `main` is here.

### P3.1 Budget

`uv run --script tests/prompt_budget.py --base ad22962` (and `--json`), run at HEAD. Units are chars. 558fb10 and HEAD measure the same, since Q7, the README and the SDK fixes don't touch the budget inputs.

| Quantity | 75dfdfc | ad22962 | HEAD | ≈ tokens | Δ vs ad22962 | Δ vs 75dfdfc |
|---|---:|---:|---:|---:|---:|---:|
| Descriptions | 11,291 | 7,325 | 6,520 | 2,174 | −11.0% | −42.3% |
| Bodies (56 agents) | 85,151 | 93,839 | 79,616 | 26,539 | −15.2% | −6.5% |
| Rules | 11,630 | 12,198 | 11,559 | 3,853 | −5.2% | −0.6% |
| Skill listing | 17,645 | 30,782 | 14,437 | 4,813 | −53.1% | −18.2% |
| Agent listing | 16,892 | 15,330 | 14,593 | 4,865 | −4.8% | −13.6% |
| BlackCat listing | 16,340 | 14,550 | 13,828 | 4,610 | −5.0% | −15.4% |
| BlackCat body | 8,305 | 5,190 | 5,004 | 1,668 | −3.6% | −39.7% |
| BlackCat per spawn | 53,920 | 62,720 | 44,828 | 14,943 | −28.5% | −16.9% |
| **Per-spawn mean** | 42,817 | 55,240 | **37,490** | 12,497 | **−32.1%** | −12.4% |
| Mean, agents with the Agent tool | 48,557 | 60,053 | 42,047 | 14,016 | −30.0% | −13.4% |
| **Leaf mean** | 29,772 | 43,510 | **26,384** | 8,795 | **−39.4%** | −11.4% |

The cost of the name-only reversal is recovered: the per-spawn mean is now below both 24beb76 (35,136) and 75dfdfc. The gates, re-based on ad22962 at the measured value × 1.02, are:

| Gate (× ad22962) | Bodies | Agent listing | BlackCat listing | Skill listing | Rules | Mean per spawn |
|---|---:|---:|---:|---:|---:|---:|
| Value | 0.85 | 0.97 | 0.96 | 0.478 | 0.95 | 0.691 |

The bodies gate went from 0.84 to 0.85 in 558fb10, with the reason recorded.

### P3.2 What was cut and merged

- **Agents (Q1, builder report).**
  - Σ bodies went from 93,839 to 77,964; procedures moved into 7 `references/from-<agent>.md` files, and 12 pointer lines were added.
  - maxTurns was cut where transcripts gave evidence: claude-code-engineer 190→120 (13 runs, p90 79), coder 190→150 (6 runs, p90 98, max 149), scout 20→11 (21 runs, p90 7).
  - No model or effort changed, for lack of evidence.
  - After d2bc994 and 558fb10, Σ bodies is 79,616.
- **Skills a–m (Q2).** 27 hub-only modules folded into hub references, among them the git, diagram, ffmpeg, mcp, macos, compiler, geo, audio and fm modules and linux-desktop-btrfs. The a–m listing went from 17,977 to 12,673 and the mean description from 107 to 90 chars (builder report).
- **Skills n–z and rules (Q3).**
  - 9 merges: write-articles and write-docs-adr into technical-writing; num-optimization into opt-modeling; ops-runbooks and net-vpn-firewall into self-hosting-ops; sec-threat-model into secure-coding; quant-backtesting, quant-risk and quant-pricing into quant-finance.
  - Rules went from 12,198 to 11,370, with a new "## Briefs and hand-backs" section; 11,559 after d2bc994 (builder report).
- **Q4.** Fixed stale references to merged names, added a `RETIRED_SKILLS` lint, and set the gates to the measured value × 1.02. The full merge log is in `.claude-work/agents-p3/merged-skills.txt` (`old → target`).

### P3.3 Skill routing (B1x+C, d2bc994)

The evaluation covered 52 tasks and 47 agents (`agents-p3/lookup/lookup-eval.md`). Of 67 transcript runs, 63% loaded no skill. The user chose option (a), B1x+C:
- 24 hubs and 15 key modules (database engines, cloud, k8s, obs, flutter/react-native and a few others) stay listed.
- 83 modules are `user-invocable-only` and are Read at `~/.claude/skills/<m>/SKILL.md`; the Skill tool refuses them.
- Each agent has an optional `## Skills, if needed` lookup line.

Measured result: −8,705 chars per spawn compared with the status quo. 3% of needed skills are cross-domain misses; added pointers cover them (biochem-engineer → hpc-slurm, a11y-docs-pdf for doc-specialist and writer, sec-* for security-engineer).

Rejected options:
- Hashmap and hook rows (D): save about 0, because the listing stays in context.
- B2/F1: −17K, but 11% hops and 8 new index skills.
- Description cap 60 (G1): −6.8K, but weaker triggers.

Constraint: SubagentStart `additionalContext` is capped at 10,000 chars per string. The 558fb10 fix restored the reviewer evidence gate (every review loads review-protocol).

### P3.4 Compaction (`agents-p3/compaction-facts.md`, docs via claude-code-guide; no live run)

| Verified in the docs | Unverified |
|---|---|
| Skills invoked with the Skill tool are re-attached: the latest invocation of each, first 5,000 tokens, 25,000 in total, oldest dropped first | Whether a module opened with Read survives. Only the generic recent-file re-read (≤5 files × 5,000) applies. |
| The skill listing is **not** re-injected | MCP schemas loaded through ToolSearch after compaction |
| CLAUDE.md, unscoped rules, memory and the plan are re-injected from disk; `paths:` rules come back on the next matching read | Whether SubagentStart re-runs after a subagent compacts |
| Subagents compact with the same logic as the main thread | — |

Consequence: the rules file and each agent's `## Skills` line survive compaction and carry the module names.

### P3.5 Agent SDK (Q7, e696833, builder report)

- `setting_sources` loads agents, skills, rules, CLAUDE.md, hooks and permissions.
- In Python, omitting `system_prompt` sends an empty prompt, so the helper uses the `claude_code` preset and passes `--agent` through `extra_args`.
- Hooks behave the same without a TTY.
- `STACK_REPORT_FORMAT=json` turns the label and report into a one-line injection that `parse_report()` reads.
- No cache-busting was found.
- New files: `dot-claude/bin/stack_sdk.py` (`claude-agent-sdk==0.2.163`), `references/agent-sdk.md` in claude-code-extensions, and `tests/sdk_smoke.py`. The smoke test was not run because the API is blocked from the sandbox.
- 6622116 applied the review fixes to `stack_sdk.py`, bringing it to 120 lines (it was 118 at e696833):
  - the agent type is taken only from a `<type>: ` label, otherwise None;
  - `TaskUpdatedMessage` status is mapped through `task_id`;
  - the caller's `env` and `extra_args` are merged into the defaults.
- test_sdk_integration: 14/14 passed with SDK 0.2.163 *(builder report)*.

**Contingency kit:** `.claude-work/agents-bench/FIXES.md`, still being built at the time of writing; I have not checked it.

### P3.6 Tests

| Revision | Result |
|---|---|
| d2bc994 (verifier) | Pass with fixes: the reviewer gate was restored in 558fb10. pytest 2517 passed, plus the 2 known sandbox failures. install_smoke with a local mktemp stand-in: 248 passed, 4 failed, the same 4 as before; not yet investigated. *(builder report)* |
| e696833 | pytest 2529 passed *(builder report)* |
| 66c6d8c | `lint_agents.py` ok; `prompt_budget.py --check` ok (run by me) |
| 6622116 | test_sdk_integration 14/14 with SDK 0.2.163 *(builder report)* |

### P3.7 Unverified

- How hidden modules behave live: L1 (Skill refused, Read works), L2 (hub routing), L4 (`paths:` keeps a skill out of the listing).
- Compaction: whether a Read-loaded module survives; ToolSearch schemas after compaction.
- Under the SDK: `enabledPlugins`, `agent`, `skillOverrides` and `env`; `exclude_dynamic_sections` with `--agent`; `output_format` for subagents; nested task messages.
- `sdk_smoke.py` has never run.
- The cause of the 4 install_smoke failures is unknown.
- The skill listing sizes for bundled and claude.ai skills are still estimates.

### P3.8 User steps

1. In the stack repo, outside the sandbox: run `bash tests/install_smoke.sh` and look at the 4 failures, then `./install.sh`, then restart Claude Code. `main` is at 6622116.
2. Live checks (lookup-eval.md §9):
   - **L1:** spawn rust-engineer with "Invoke Skill rust-async, then Read ~/.claude/skills/rust-async/SKILL.md". Expect the Skill call refused, the Read working, and `rust-async` absent from the `/context` listing.
   - **L2:** run tasks 2, 29, 42 and 48, then check that the hidden modules were Read.
   - **L4:** in a scratch project, give a copy of one module `paths: ["**/*.rs"]` and see whether it stays out of the listing until a matching file is read.
3. Compaction checks:
   - (a) Read a hidden module, run `/compact`, and check `/context` for the module text.
   - (b) After `/compact`, call a tool loaded earlier through ToolSearch without searching again.
4. `uv run --script tests/sdk_smoke.py` makes billed API calls.
5. After the session: `git worktree remove` the worktree and `git branch -d` its branch.
6. Pushing is yours.
