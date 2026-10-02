---
name: prompt-and-brief-design
description: Load before writing a system prompt, agent definition, CLAUDE.md, research prompt, schema or few-shots.
---
# Prompt and brief design

## Scope
Text prompts that steer models and agents: system prompts, agent definitions, project briefs for coding agents (CLAUDE.md + first task), research prompts, structured outputs, few-shot examples, injection-resistant designs, prompt testing, cross-provider porting. Image prompts → `image-prompting`. Claude Code file formats (agent frontmatter, skills, settings) → `claude-code-extensions`. Loop, tools and memory mechanics → `agent-harness-design`. Scoring and statistics → `llm-evals`. Guidance marked "Anthropic" comes from the current Claude prompting best-practices and Claude Code memory docs (September 2026).

## 1. Principles
- Write for a brilliant colleague with no context (Anthropic's "golden rule"): goal, audience, constraints, output format, and the reason behind each rule — models generalize from reasons ("read aloud by TTS, so no ellipses" beats "NEVER use ellipses").
- Specific and checkable: "run `uv run pytest -q` before reporting" instead of "test your changes"; "API handlers live in `src/api/handlers/`" instead of "keep files organized".
- One rule per concern and no contradictions: with conflicting rules the model picks one arbitrarily. Re-read the whole prompt (plus CLAUDE.md, rules files, tool descriptions) for conflicts after every edit.
- Say what to do rather than what not to do; when a prohibition is needed, give the alternative.
- Calm wording: current Claude models follow the system prompt closely; "CRITICAL: you MUST…" or "if in doubt, use the tool" now causes over-triggering (Anthropic). Reserve emphasis for the one or two rules whose violation is costly.
- Explicit action verbs: "Change this function…" gets edits; "Can you suggest changes…" gets suggestions.
- Structure with Markdown headings or XML tags (`<instructions>`, `<context>`, `<examples>`, `<documents>`), consistent names, referenced by name in the text. The prompt's own formatting style bleeds into the output's.
- Long inputs (20k+ tokens): documents first, each in `<document>` with `<source>` metadata, the question and instructions last (Anthropic reports up to 30% better answers).
- Examples outweigh prose: 3–5 diverse, exactly-correct examples in `<example>` tags.

## 2. System prompts for agents
Order: stable, cacheable material first (role, rules, tool guidance, examples), volatile material last (task data, retrieved documents, user state).
```
<role>You are <function> for <users>. Success means <observable outcome>.</role>
<context>Environment (repo, data, tools available), what is already true, what the user cares about.</context>
<instructions>Numbered steps where order or completeness matters; defaults for common forks.</instructions>
<tools>
- search_docs: first choice for questions about the product docs; not for general web facts.
- run_tests: after every edit under src/; quote failures verbatim.
</tools>
<constraints>Scope limits and rules, each with its reason.</constraints>
<stop_and_escalate>Done when <criteria>. Ask before <irreversible or external actions>. After <N> failed attempts, stop and report what was tried.</stop_and_escalate>
<output_format>Exact shape: template or schema, length, what to omit.</output_format>
<examples><example>…</example></examples>
```
- Tool guidance covers when to use each tool, when not, and preferences between overlapping tools; the tool's own description (in its schema) carries the what and the parameters (3–4+ sentences each, per Anthropic).
- Stop rules are part of the prompt and enforced again in the harness (budgets, step caps) — prompts alone are not controls.
- Autonomy guidance (Anthropic's pattern): local, reversible actions freely; ask before destructive, hard-to-reverse or externally visible actions; never use destructive shortcuts (`--no-verify`, deleting unfamiliar files) to get unblocked.
- For long-running agents say whether context is compacted and where state lives (progress file, test status JSON, git), so the model neither stops early nor loses state.
- Grounding line for code agents: "Do not make claims about code you have not opened; read the referenced files first."
- Keep delegation rules explicit where subagents exist: spawn for parallel or isolated work, work directly for sequential or single-file tasks.

## 3. Project briefs for coding agents
**CLAUDE.md** — loaded every session as a user message after the system prompt; target < 200 lines (Anthropic); facts needed in every session only. Multi-step procedures belong in skills, path-specific rules in `.claude/rules/`, must-happen actions in hooks; `@path` imports (max depth 4) still load at launch. `/init` drafts one; `/context` shows what loaded.
Templates — a CLAUDE.md skeleton (Commands, Architecture, Conventions, Non-goals, Workflow, Gotchas) and the one-milestone initial task prompt (goal, context, requirements, acceptance criteria, verification loop, report, stop rules): `references/project-briefs.md`.

- Milestones in the brief: M1…Mn, each with acceptance tests and a demo command; keep a `PROGRESS.md` (or structured test-status file) the agent updates, so a fresh session can resume from files and git history.
- Write requirements as observable behavior plus the tests that prove it; include non-functional ones (performance budgets, platforms, accessibility) with a measurement method.
- Ask for general solutions: "implement the logic for all valid inputs; do not special-case test inputs" (Anthropic's anti-hardcoding pattern).

## 4. Research-task prompts
Template (question and decision, scope, primary sources, method, citation fidelity, answer-first output, budget): `references/research-prompts.md`.

Tool ladder and source-quality rules: `web-research`; paper searches and citation audits: `literature-review`. For long investigations ask for competing hypotheses and a notes file with confidence levels (Anthropic's structured-research pattern).

## 6. Few-shot examples
- Cover the decision boundary and the hard cases, not the easy middle; vary length, topic and surface form so incidental features are not copied; balance labels and positions.
- Match the exact target format; wrap in `<example>` (several in `<examples>`); keep them consistent with the prose rules — when they disagree the examples win.
- Never reuse evaluation items as examples; for classification include an `unsure` case.
- Dynamic few-shot (nearest labeled examples per input) only after it beats a fixed set on the test set.

## 7. Injection-resistant patterns for tool-using agents
Instructions can arrive inside tool results, web pages, documents, emails, MCP outputs, file names and code comments. The dangerous combination is private data + untrusted content + a channel to send data out.
- Prompt level (necessary, not sufficient): mark provenance and wrap untrusted content (`<untrusted source="...">…</untrusted>`), state that such content is data and never instructions, restate the task after it; spotlighting (delimiting, datamarking, encoding — Hines et al., 2024); no secrets in context.
- Architecture is what actually holds. The patterns from "Design Patterns for Securing LLM Agents against Prompt Injections" (Beurer-Kellner et al., 2025):

| Pattern | Constraint |
|---|---|
| Action-Selector | the model only maps requests to predefined actions; tool outputs never flow back into its decisions |
| Plan-Then-Execute | the action sequence is fixed before untrusted data is read; data cannot change control flow |
| LLM Map-Reduce | isolated sub-calls process each untrusted item with constrained outputs |
| Dual LLM | a privileged model plans with symbolic references; a quarantined model reads untrusted data |
| Code-Then-Execute | the model writes a program that calls tools; the program, not the model, touches the data |
| Context-Minimization | untrusted or no-longer-needed text is removed from context before later steps |

- Capability tracking (CaMeL, Debenedetti et al., 2025) extends this: values derived from untrusted data cannot reach sensitive tool arguments without a policy check.
- Add least-privilege tools, confirmation for side effects, egress allowlists, and stripping model-generated URLs or Markdown images that could exfiltrate data. Put planted-injection cases in the test set (§8). Threat modeling and code-level defenses: `secure-coding`.

## 8. Testing prompts
- Before editing, build a test set: 20–50 cases — typical, edge, ambiguous, out-of-scope and adversarial (injection) — each with expected properties (exact answer, schema-valid, must include, must not do).
- Graders: deterministic first (schema, regex, contains, exact match, executing generated code); rubric-based LLM judge for open-ended outputs, calibrated on a few human-graded cases (`llm-evals`).
- A/B: same cases and parameters, several samples per case for stochastic settings, paired comparison, position-swapped pairwise judging, CIs. Across models: the same suite per model; port prompts (§9 in `references/porting.md`) before comparing.
- Regression: prompts live in git next to their suite; every edit reruns it and diffs outputs; each production failure becomes a new case; pin model ids and sampling in the test config.
- Tooling: a small pytest harness, or promptfoo (`promptfooconfig.yaml` with `prompts`, `providers`, `tests` → `vars` + `assert` types such as `is-json`, `contains`, `regex`, `javascript`, `llm-rubric`; run `npx promptfoo@latest eval`).

## References
- `references/structured-outputs.md` — read when asking a model for JSON or schema-bound output.
- `references/porting.md` — read when porting a prompt to another provider or model.

## Verify
The test suite passes at or above the previous version with the same model settings; no contradictions across system prompt, CLAUDE.md, rules and tool descriptions (read them together); planted injections fail; outputs validate against the schema; a fresh session following only the brief reaches the first milestone's acceptance criteria; CLAUDE.md stays under 200 lines.

## Deliverables
The prompt or brief (versioned), its test suite and grader config, a results table (`| version | model | cases | pass rate (95% CI) | schema-valid % | injection cases failed | cost/case |`), and a changelog entry stating what changed and why.
