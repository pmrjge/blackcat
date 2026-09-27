---
name: technical-writing
description: Load before drafting, restructuring or editing technical or scientific prose — articles and blog posts on mathematics, physics, CS or AI, documentation, READMEs, ADRs, changelogs, reports, research summaries. Covers reader and purpose, structures (inverted pyramid, IMRaD, Diátaxis), sentence craft, mathematical exposition, code and figures in prose, citations, editing passes and a review checklist.
---
# Technical and scientific writing

## Scope
- Covers: planning (reader, purpose, claim), document structures, paragraph and sentence craft, mathematical
  exposition, code/figures/tables in prose, citation practice, editing passes, templates, review checklist.
- Not here: European Portuguese specifics (`portuguese-pt-writing`), LaTeX mechanics (`latex-typesetting`),
  finding and verifying sources (`literature-review`), print/EPUB production (`book-production`),
  statistical reporting details (`data-analysis`), ML evidence standards (`ml-experiment`, `llm-evals`),
  constructing and checking proofs (`proof-craft`), chart design (`data-visualization`).
- Same method in English and Portuguese; the language only changes the conventions pass.

## 1. Before drafting: reader, purpose, claim
Write these four lines at the top of the draft and delete them only at the end:
1. **Reader** — who, what they already know, what they lack, what they will *do* after reading.
2. **Purpose** — decide / act / learn a skill / understand / look something up / be persuaded.
3. **Main claim** — one sentence, ≤ 30 words, containing the result (with its number if there is one). If you
   cannot write it, you are not ready to draft; outline or compute first.
4. **Constraints** — venue, length, register, language variant (en-US/en-GB/pt-PT), format, deadline.
Then outline as a list of *assertions* (each heading is a claim, not a topic: "Caching halves p95 latency", not
"Caching").

## 2. Pick the structure from the genre
| Genre | Structure | Notes |
|---|---|---|
| Report, memo, status, email, incident | Inverted pyramid: answer/decision → key evidence → details → background | Reader may stop after paragraph 1; it must stand alone |
| Research paper (empirical) | IMRaD: Introduction, Methods, Results, Discussion (+ abstract, related work, conclusion) | Methods reproducible; Results report, Discussion interprets |
| Mathematics paper | Intro with main theorems stated precisely early → notation/preliminaries → proofs (hardest ideas signposted) → open problems | "Organization of the paper" paragraph at end of intro |
| Documentation | Diátaxis: tutorial / how-to / reference / explanation, never mixed on one page | See table below |
| Blog post / article | Hook (problem or result) → promise → steps → worked example → limits → takeaways | Title states the claim or question |
| Decision record | ADR (Nygard): context → decision → consequences | §9 template |
| Release notes | Keep a Changelog categories, newest first | §9 template |

Diátaxis (Daniele Procida, diataxis.fr) — the compass asks *action or cognition?* and *acquisition (study) or
application (work)?*:
| | Acquisition (study) | Application (work) |
|---|---|---|
| **Action** (doing) | Tutorial — a lesson; guaranteed success path, no choices, no explanation detours | How-to guide — steps to a goal for a competent user; assumes context, handles real variations |
| **Cognition** (knowing) | Explanation — why and how it fits; alternatives, history, design rationale | Reference — dry, complete, structured like the thing described (API, CLI flags, config keys) |
Symptoms of mixing: tutorials that explain theory mid-step, reference pages with opinions, how-tos that teach
basics. Fix by splitting and cross-linking.

Abstract formula (papers, research summaries): context (1 sentence) → gap (1) → contribution (1–2) →
method (1) → main result with its number and uncertainty (1) → implication (1). Introduction: end with a
bulleted list of contributions, each pointing to the section/theorem that delivers it.

## 3. Paragraphs and sentences
- **One idea per paragraph; topic sentence first.** Skim test: reading only first sentences must reproduce the
  argument. If not, restructure before polishing sentences.
- **Old → new.** Start sentences with what the reader already has; put the new, important element at the end
  (stress position). Link paragraphs by repeating the key term, not by "Moreover,".
- **Active voice when the agent matters** ("We prove…", "The scheduler evicts the oldest page"); passive when the
  agent is irrelevant or the object is the topic ("Samples were drawn uniformly").
- **Precise verbs over nominalizations:** "perform an analysis of" → "analyze"; "make a decision" → "decide";
  "is dependent on" → "depends on"; "has the ability to" → "can".
- **Cut filler:** "in order to" → "to"; "due to the fact that" → "because"; "it is important to note that" →
  delete; "a number of" → "several" or the number; "very/quite/basically/actually/really" → delete or quantify.
- **Hedge once, where uncertainty is real, and name its source:** "under assumption (A2)", "in 3 of 5 seeds",
  "we did not test on non-English data". Never stack hedges ("may possibly suggest").
- **Parallel structure** in lists, headings and comparisons (all verbs, or all noun phrases; same grammatical form).
- **Sentence length:** vary; split anything over ~35 words; one main clause carrying the point.
- **One term per concept.** Define on first use; never switch synonyms for variety ("model", "network",
  "architecture" must not alternate for the same object). Keep a glossary for long documents.
- **Numbers:** units always; significant figures matching the uncertainty ("3.2 ± 0.4 ms, mean ± s.d., n = 5");
  "significant" only for a stated statistical test; percentages vs percentage points distinguished.
- **Banned without proof:** "clearly", "obviously", "trivially", "it is easy to see". Show it or cite it.
- Lists for parallel discrete items; prose for reasoning (arguments die in bullet points).

## 4. Mathematical exposition
- **Define before use.** Every symbol introduced once, in words ("Let $G=(V,E)$ be a finite simple graph"), never
  reused for a second meaning. Over ~10 symbols: a notation table (symbol | meaning | where defined).
- **Order:** motivation → intuition or informal statement → precise statement → proof or proof sketch → example →
  non-example showing each hypothesis is needed ("a continuous function on a compact set is bounded": true on
  $[0,1]$, false on $(0,1)$ for $x\mapsto 1/x$). Put the main theorem early; readers decide from it whether to
  continue.
- **Self-contained statements:** all quantifiers explicit and in the right order ("for every ε > 0 there exists
  δ > 0 such that…"), domains of all variables, standing assumptions restated or referenced by name.
- **Conventions declared once:** whether ℕ contains 0; log base; inner product linear in which argument; index
  origin (0- or 1-based, matters for CS/AI readers); sign conventions and metric signature (physics); bold vs arrow
  for vectors; row vs column vectors.
- **Typography of formulas in prose:** do not start a sentence with a symbol ("$p$ divides $n$." → "The prime
  $p$ divides $n$."); separate adjacent formulas with words ("for $x \in A$, $y \in B$" → "for $x \in A$ and
  $y \in B$"); punctuate displayed equations as part of the sentence; number only equations you reference; refer
  by name + number ("the energy bound (3.2)").
- **Proofs:** announce the strategy first ("by induction on $n$", "by contradiction; the key is Lemma 2.3");
  for long arguments use hierarchically numbered steps (Lamport-style structured proofs); isolate reusable
  pieces as lemmas; mark the end.
- **Worked computations:** show the non-obvious intermediate steps; check every computation independently —
  symbolically (sympy in `__CLAUDE_DIR__/venvs/sci/bin/python`, or `mcp__wolfram`), numerically at random points,
  by dimensional analysis (pint), limiting and symmetric cases. Write the check, not "one verifies".
- **Physics:** state the regime of every approximation (e.g. "valid for $kr \ll 1$"), units system (SI vs
  Gaussian vs natural), and what is measured vs derived.
- **CS/AI:** algorithms as pseudocode with inputs, outputs, invariants and complexity; empirical claims with
  dataset, metric, baseline, seeds/variance and compute budget.
- Classic references worth following: Halmos, "How to write mathematics" (L'Enseignement Math. 16, 1970);
  Knuth, Larrabee & Roberts, *Mathematical Writing* (MAA, 1989); Higham, *Handbook of Writing for the Mathematical
  Sciences* (3rd ed., SIAM, 2020); Lamport, "How to write a 21st century proof" (J. Fixed Point Theory Appl. 11,
  2012).

## 5. Code in prose
- Every snippet is **runnable as shown** or visibly marked as a fragment (`...`); minimal; no dead parameters;
  versions pinned where behaviour depends on them; show the actual output you claim.
- Test documentation code: `pytest --doctest-glob="*.md"` (default glob is `test*.txt`; the flag may repeat),
  `pytest --doctest-modules` for docstrings; Rust doc tests run with `cargo test`; otherwise extract fenced
  blocks and execute them in CI.
- Fences carry a language tag; commands copy-pasteable (either no prompts, or `$ ` prompts with output shown —
  be consistent); placeholders as `<like-this>`; never real secrets, tokens or personal paths.
- Before the block: what it does and why; after it: what to notice in the output.
- No screenshots of code or terminal text.

## 6. Figures and tables
- One question per figure. **Caption = takeaway sentence first**, then what is shown: axes and units, n,
  what error bars mean (s.d., s.e.m., 95% CI), data source.
- Tables for exact values, figures for patterns. Units in headers, aligned decimals, consistent significant
  figures, no vertical rules (booktabs style), best result marked only if the comparison is fair.
- Reference every figure/table in the text before it appears; the text states the finding, the figure supports it.
- Accessibility: alt text states the takeaway, not "a chart"; colour-blind-safe palettes; never encode only by
  colour; direct labels over legends where possible.

## 7. Citations and attribution
- Cite the primary source you actually read; if you only saw it quoted, write "cited in". Every non-obvious
  factual claim gets a citation; every citation is verified before delivery (`literature-review` audit).
- Quotations exact, with page/section; otherwise paraphrase in your own structure (no close paraphrase).
- Reused figures, code and text follow their licence: CC BY needs attribution, CC BY-SA also share-alike
  (Stack Overflow snippets are CC BY-SA); publisher figures usually need permission — redraw from data and
  credit ("adapted from …") when allowed. Trademarks: use names, not logos, unless permitted.
- Match the venue's style (numeric, author–year); LaTeX via biblatex/BibTeX, Markdown via Pandoc `--citeproc` + CSL.
- Disclose AI assistance where the venue or client requires it.

## 8. Editing passes (in this order; never polish sentences in a section you may delete)
1. **Structure:** reverse outline — one line per paragraph stating its point; check order, gaps, duplication
   against the purpose; cut or move whole sections.
2. **Paragraphs:** topic sentences, one idea each, transitions by key terms; skim test.
3. **Sentences:** cut 10–20% of words; verbs over nominalizations; hedges; parallelism; term consistency.
4. **Correctness:** numbers and units, recomputed math, code executed, links resolve, cross-references,
   citations verified, figure/table numbering.
5. **Proofreading:** spelling in the chosen variant, typography (en dash for ranges 3–5, non-breaking spaces
   before units and in "Fig. 3", consistent heading capitalization), read aloud or via text-to-speech.

Prose linting with Vale (`brew install vale`): `.vale.ini` at the repo root, then `vale sync` and `vale docs/`
(only `error` alerts give a non-zero exit, so CI can gate on them):
```ini
StylesPath = styles
MinAlertLevel = suggestion
Packages = Microsoft, write-good
Vocab = Project

[*.md]
BasedOnStyles = Vale, Microsoft, write-good
```
Project terms go one regex per line in `styles/config/vocabularies/Project/accept.txt` (Vale ≥ 3; older versions
used `styles/Vocab/`); commit the vocabulary, ignore the synced packages (`styles/*` plus `!styles/config/` in
`.gitignore`). House style for software docs: the Google developer documentation style guide or the Microsoft
Writing Style Guide (both exist as Vale packages). LanguageTool (en-US, en-GB, pt-PT) for grammar; `chktex` for
LaTeX sources. Linters flag candidates; you decide.

## 9. Templates
**README**
```markdown
# <name> — <what it does, one line>
<2–4 sentences: the problem, who it is for, what makes it different>
## Quick start      <install + smallest runnable example + expected output>
## Usage            <common tasks; link to how-to guides>
## Configuration    <table: option | default | meaning>
## How it works     <short; link to explanation docs>
## Development      <setup, tests, lint, release>
## Limitations      <known issues, non-goals>
## License · Citation (CITATION.cff) · Acknowledgements
```
**ADR** (Nygard: numbered sequentially, numbers never reused, superseded records kept, stored e.g. `doc/adr/`)
```markdown
# ADR-007: <short noun phrase>
Status: proposed | accepted | deprecated | superseded by ADR-012 · Date: YYYY-MM-DD
## Context        <forces at play, value-neutral: technical, organizational, constraints>
## Decision       <"We will …" — full sentences, active voice>
## Consequences   <all of them: positive, negative, neutral; what becomes easier/harder>
## Alternatives considered (optional) <option → why not>
```
**Changelog entry** (Keep a Changelog 1.1.0 + Semantic Versioning; ISO dates; user-visible effects, not commits)
```markdown
## [Unreleased]
## [1.4.0] - 2026-09-26
### Added
- `--dry-run` flag for `sync` (#123).
### Changed / Deprecated / Removed / Fixed / Security
[1.4.0]: https://github.com/<org>/<repo>/compare/v1.3.0...v1.4.0
```
**Blog post outline**
```text
Title: the claim or the question (no puns)
Lede (≤ 3 sentences): problem → result/number → why the reader should care
Setup: prerequisites, definitions, notation, what is out of scope
Body: 3–5 sections, each heading an assertion, each one step of the argument
Worked example / figure / runnable code (tested)
What did not work and the limits of the result
Takeaways (≤ 3 bullets) · Further reading (verified links)
```
**Research summary** (one paper or a small set; one row per claim)
| Field | Content |
|---|---|
| Citation | verified (DOI/arXiv ID, version) |
| Question / claim | what exactly is asserted, in their terms and in yours |
| Method | setting, data, assumptions, proof technique or experimental design |
| Evidence | theorems (refereed? formalized?), datasets, n, metrics, baselines, seeds, variance |
| Strength | strong / moderate / weak + one-line reason |
| Limitations | stated by authors; found by you |
| Relevance | how it bears on our question; what to do next |

## 10. Review checklist
- [ ] Reader, purpose and one-sentence claim are explicit; the opening states the claim.
- [ ] Structure matches the genre; documentation pages each have a single Diátaxis type.
- [ ] Skim test passes (topic sentences carry the argument); every heading is an assertion or a task.
- [ ] Every term and symbol defined before use; conventions declared; notation consistent throughout.
- [ ] Every number has units, uncertainty and source; every computation re-derived independently.
- [ ] Every code block executed; outputs match; versions pinned.
- [ ] Figures/tables referenced in text; captions state the takeaway; axes labelled with units.
- [ ] Citations verified; quotations exact; licences and attribution respected.
- [ ] Hedges only where uncertainty is real; no "clearly/obviously"; no stacked qualifiers.
- [ ] Language variant consistent; Vale shows no errors; remaining warnings reviewed.

## Verify
- Cold read by someone with the target background (or a fresh session given only the document): can they state
  the main claim and perform the task? Note where they stalled.
- Reverse outline matches the intended outline; word count within budget.
- Doctests/snippets run in a clean environment; computations re-run; links and DOIs resolve.

## Deliverables / Report
- The document in the requested format (Markdown by default; LaTeX via `latex-typesetting`; `.docx` via
  Pandoc with a reference document or the `docx` skill).
- For edits of existing text: a diff or tracked changes plus a short log of changes per editing pass.
- A final note listing open issues, assumptions made about the reader, and anything unverified, marked as such.
