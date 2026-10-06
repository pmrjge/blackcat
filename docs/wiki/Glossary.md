<!-- markdownlint-disable MD013 MD060 -->
# Glossary

| Term | Meaning |
|---|---|
| **BlackCat** | the stack's main-thread agent (`dot-claude/agents/blackcat.md`); it only delegates. `claude` starts as BlackCat because `settings.json` sets `"agent": "blackcat"` |
| **Specialist** | any of the 56 agents BlackCat can dispatch |
| **L1 … L8** | delegation depth below the main thread; L8 cannot spawn (`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=8`) |
| **Leaf** | an agent without the Agent tool, so it never spawns (16 agents) |
| **`POLICY` row** | the list of agent types an agent may spawn, in `agent_guard.py`; the agent's "May spawn" sentence must match it |
| **Fan-out** | the number of running children an agent may have at once (3 by default; `STACK_MAX_FANOUT_BY_TYPE`) |
| **Guard** | `dot-claude/hooks/agent_guard.py`, the single policy hook, wired to most Claude Code hook events |
| **`no-push` mode** | the guard's PreToolUse Bash hook: no push, no forge write, protected paths, the installer rule, credential reads, read-only Bash for reviewers; `STACK_POLICY=off` does not lift its refusals |
| **Fail closed / fail open** | a fail-closed hook denies the call when it errors or cannot start (the guard's PreToolUse entries); a fail-open one lets it pass (read gate, web caps, output shrink, token budgets on unreadable input) |
| **Protected paths** | paths no Bash command may write, delete or rename: the installed stack, backups, hook state, `tools/instructor` |
| **Read-only types** | code-reviewer, security-auditor, verifier, plan-reviewer, claude-code-guide, proof-checker: Bash limited to read-only commands (`READONLY_TYPES`) |
| **Delegation ledger** | the guard's record of every Agent call, per session: `spawns/`, `agents/`, rendered to `delegations.md` |
| **Brief** | the prompt a parent gives a child: goal, inputs, constraints, done-when, output |
| **Hand-back** | a child's final report: a one-line clean finish, or a `STATUS / RESULT / EVIDENCE / FILES / NEXT` block |
| **Clean finish** | `<input> · <YYYY-MM-DD HH:MM> · <agent type>` plus the result: everything done, nothing unverified |
| **`SubagentHandback`** | the tool nested subagents use to deliver their final report; the hand-back check reads its `message` |
| **`ASK USER`** | `NEXT: ASK USER: <question>` in a hand-back; relayed up to BlackCat, which asks you |
| **`USER:` relay** | a parent's message to its own child carrying your answer; the only form of consent an agent accepts from another agent |
| **Web taint** | the mark on an agent that read web content, or is linked to one that did; a tainted agent cannot write neural-memory |
| **Hard budget** | context tokens per human prompt and per session, whole tree; past it every call but reporting is refused |
| **Soft limit** | a per-type token level past which the next tool call carries one wrap-up warning; nothing is refused |
| **Learned limits** | turn and token limits proposed from the usage collector's rows and frozen per session (`stack_limits.py`) |
| **Read gate** | `read_gate.py`: refuses the first read of build output, dependencies, big data, media or binaries; the identical retry passes |
| **Output shrink** | `output_shrink.py`: cuts large Bash or Read results to their decisive lines; shadow mode by default |
| **Observe / shadow mode** | a mechanism that logs what it would do and changes nothing |
| **Hub, module, standalone** | the three skill shapes: a hub has a `## Modules` table; a module is named in one (89 of them hidden and read by path); a standalone skill is neither |
| **`LISTED_CORE`** | the 32 skills whose description appears in every spawn's skill listing (`tests/test_skill_modules.py`) |
| **Name-only** | a skill listed by name without its description (`skillOverrides`), loaded by the Skill tool |
| **toolsmith** | the dependency installer agent; its only command is `bin/stack-install` |
| **Ticket** | the one-use record the guard writes for an allowed toolsmith call; the executor runs nothing without it |
| **Ledger (toolsmith)** | `toolsmith/ledger.jsonl`: every install with its uninstall command |
| **Instructor** | `tools/instructor/`: fixed `just` recipes `check-suite`, `ff-merge`, `worktree-audit` |
| **C10** | the full check suite: `bash -n`, the guard's self-test, `lint_agents`, `prompt_budget --check`, pytest, `install_smoke.sh`; run on `main` after every merge |
| **C1–C13** | the rows of `hand_off/R3_CONTAINER_CHECKLIST.md`: real `container` CLI behaviour for you to confirm (its C10 row is unrelated to the check suite) |
| **INTEG** | in hand-off notes, the step that merges `main` into a branch, fast-forwards `main` and runs C10 there |
| **Stage 4 levers (L1, L2, L5, L7, L10)** | in the changelog and hand-off notes, named items ("levers") of the project's Stage 4 work plan (for example L2 the output shrink, L5 brief budgets, L7 the hand-back mechanisms, L10 prompt trims); unrelated to depth levels L1–L8 |
| **R3** | in hand-off notes, the port of the isolation backend to Apple `container` |
| **eq-container** | `lib/eq-container`: the equilibrium harness's isolation images, run with Apple `container` |
| **WALL** | `lib/eq-wall`: the default-deny host-access broker and its one tunnel directory |
| **Equilibrium harness, EQ-T** | the evaluation harness the isolation images serve, and its working copy; not in this repository |
| **c0** | the pre-registered baseline arm of the context-diet campaign (`hand_off/RUNBOOK_c0.md`) |
| **A4 probe** | one paid `claude -p` call that settles how an agent's tools combine with `--tools` (`hand_off/A4_FOLD.md`) |
| **Manifest** | `.stack-manifest.json` in the config dir: every stack file's sha256 and the install's state |
| **`stack.env`** | your keys and model IDs, mode 0600, unreadable to agents |
| **`STACK_POLICY=off`** | the escape hatch that lifts the spawn, budget, lock and read-only guards; never the no-push refusals or BlackCat's delegate-only gate |
| **Codex port** | planned, not shipped: a port of the stack with a `codex_config/` installer (not in this repository) |

Sources: the pages of this wiki and the files they cite; `hand_off/HANDOFF_STATE.md` (§1, §4, §6) for the
hand-off terms.
