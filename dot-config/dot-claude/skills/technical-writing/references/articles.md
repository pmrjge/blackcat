# Articles, papers and blog posts

Read from `technical-writing` (reader/purpose/claim, sentences, editing passes, checklist live in its SKILL.md). LaTeX mechanics: `latex-typesetting`; sources: `literature-review`; proofs: `proof-craft`.

## Structure
| Genre | Structure | Notes |
|---|---|---|
| Research paper (empirical) | IMRaD: Introduction, Methods, Results, Discussion (+ abstract, related work, conclusion) | Methods reproducible; Results report, Discussion interprets |
| Mathematics paper | Intro with main theorems stated precisely early → notation/preliminaries → proofs (hardest ideas signposted) → open problems | "Organization of the paper" paragraph at end of intro |
| Blog post / article | Hook (problem or result) → promise → steps → worked example → limits → takeaways | Title states the claim or question |

Abstract formula (papers, research summaries): context (1 sentence) → gap (1) → contribution (1–2) →
method (1) → main result with its number and uncertainty (1) → implication (1). Introduction: end with a
bulleted list of contributions, each pointing to the section/theorem that delivers it.

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

## Blog post outline
```text
Title: the claim or the question (no puns)
Lede (≤ 3 sentences): problem → result/number → why the reader should care
Setup: prerequisites, definitions, notation, what is out of scope
Body: 3–5 sections, each heading an assertion, each one step of the argument
Worked example / figure / runnable code (tested)
What did not work and the limits of the result
Takeaways (≤ 3 bullets) · Further reading (verified links)
```

## Verify
- Main theorem or result stated in the introduction; every symbol defined before use; every computation re-derived independently.
- Every figure and table referenced in the text, caption leads with the takeaway; every citation verified and resolving (DOI/arXiv ID).
