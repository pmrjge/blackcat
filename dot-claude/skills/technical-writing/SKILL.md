---
name: technical-writing
description: Load before drafting, restructuring or editing technical or scientific prose — articles and blog posts on maths, physics, CS or AI, docs, READMEs, ADRs, reports; style, citations.
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

## Modules
| Module | Load for |
|---|---|
| `write-articles` | papers (IMRaD, maths), blog posts and articles: abstract formula, mathematical exposition, figures and tables, citations, blog outline |
| `write-reports` | reports, memos, status, email, incidents (inverted pyramid); research summaries |
| `write-docs-adr` | documentation (Diátaxis), code in prose, READMEs, ADRs, changelogs and release notes, Vale prose linting |
| `docs-sites` | building a documentation site: Zensical or MkDocs Material, Sphinx, Docusaurus, Starlight, VitePress |

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

## 8. Editing passes (in this order; never polish sentences in a section you may delete)
1. **Structure:** reverse outline — one line per paragraph stating its point; check order, gaps, duplication
   against the purpose; cut or move whole sections.
2. **Paragraphs:** topic sentences, one idea each, transitions by key terms; skim test.
3. **Sentences:** cut 10–20% of words; verbs over nominalizations; hedges; parallelism; term consistency.
4. **Correctness:** numbers and units, recomputed math, code executed, links resolve, cross-references,
   citations verified, figure/table numbering.
5. **Proofreading:** spelling in the chosen variant, typography (en dash for ranges 3–5, non-breaking spaces
   before units and in "Fig. 3", consistent heading capitalization), read aloud or via text-to-speech.

Prose linting with Vale: `write-docs-adr`. LanguageTool (en-US, en-GB, pt-PT) for grammar; `chktex` for LaTeX sources. Linters flag candidates; you decide.

## Verify
- Before delivery run `references/review-checklist.md` (read when reviewing a draft, yours or someone else's).
- Cold read by someone with the target background (or a fresh session given only the document): can they state
  the main claim and perform the task? Note where they stalled.
- Reverse outline matches the intended outline; word count within budget.
- Doctests/snippets run in a clean environment; computations re-run; links and DOIs resolve.

## Deliverables / Report
- The document in the requested format (Markdown by default; LaTeX via `latex-typesetting`; `.docx` via
  Pandoc with a reference document or the `docx` skill).
- For edits of existing text: a diff or tracked changes plus a short log of changes per editing pass.
- A final note listing open issues, assumptions made about the reader, and anything unverified, marked as such.
