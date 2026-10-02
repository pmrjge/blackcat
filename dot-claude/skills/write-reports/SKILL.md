---
name: write-reports
description: Use for reports, memos, status updates, incident write-ups and research summaries.
---
# Reports, memos and research summaries

Part of `technical-writing` (reader/purpose/claim, sentences, editing passes, checklist). Statistical reporting: `data-analysis`; ML evidence: `ml-experiment`, `llm-evals`.

## Structure
| Genre | Structure | Notes |
|---|---|---|
| Report, memo, status, email, incident | Inverted pyramid: answer/decision → key evidence → details → background | Reader may stop after paragraph 1; it must stand alone |

- Numbers carry units, uncertainty and source (`technical-writing` §3).

## Research summary template
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

## Verify
- Paragraph 1 alone states the answer/decision; each summary row cites a verified source and a strength rating with its reason.
