# RS pool: closed-book claim verification over a frozen corpus of graded runs

**Interpretation of the user's directive "ranking items and claims from graded runs"** (stated once, applied to RS, DS,
OE): DS and OE are *ranking* items (blinded pairwise preference, both orders, COMPARE_eq §2/§9); RS items are *claims
with answer keys drawn from graded runs*. The graded runs are the agents-baseline campaign (100 prompts with rubrics,
77 grade records from batches T8a, T8b and b0v2, 45 run-metric rows), read-only from
`claude-local-work/campaign/agents-baseline/` (SOURCES.sha256 lists the source hashes; `.claude-work/grade-b0v2/` and
`agents-b0b3/b1/data/` hold byte-identical copies, checked with `cmp`).

**Built** by `gen/extract_src.py` (copies only the needed columns into `gen/src/`; drops session and agent ids,
timestamps and descriptions; redacts the prompt-injection sentence of P06; aborts on any path, e-mail, id or key
pattern) and `gen/gen_rs.py` (content seed `20261004 ^ int(sha256("eq|items|RS|gen")[:8],16)` = 2090810305; segment
order `default_rng(3725927731)`, one permutation per item in manifest order).
- Corpus `fixtures/corpus/` (217 files: `prompts/` 100, `grades/<batch>/` 77, `runs/` 40), shared by every item; every
  item's `segments` are all 217 files in that item's shuffled order (a k-cover view = copy only the member's subset).
- Claims, one item each: A grade label per grade record (75 non-dev); B grader-evidence facts hand-extracted from the
  graders' evidence lines (88; each true value asserted against the record text); C run metrics (agent type actually
  used, model, turns, tool calls, tokens; 40); D NOT_IN_CORPUS (35 outcome claims about prompts with no grade or run
  record, 16 wall-time claims; wall time is in no record). Each A/B/C claim is SUPPORTED or REFUTED (perturbed value,
  often the other variant's value) with p = 0.5; 40% name the run by a paraphrased task description instead of its id
  (one extra hop through `prompts/`).
- Counts: **254 non-dev** (SUPPORTED 116, REFUTED 87, NOT_IN_CORPUS 51) + 3 dev (one per label).

**Answer** (`schema.json`): `{label, value, rationale}`. Plurality key for the reducer: `label`, plus the normalised
`value` when the label is REFUTED. **Score** = 1 iff label = key, the REFUTED correction matches the key (numbers with
k/M/million suffixes and thousands separators, relative tolerance 1e-6; strings by alias equality or whole-word match
without the claimed false value), and the blinded grader passes the rationale against the item rubric
(`graders/grader_brief_RS.md`); else 0. `oracle.py` exit codes: 0 scored, 3 needs grade, 2 malformed input or unknown
item. Grader input: label, value and rationale only (evidence stripped, whitespace normalised, arm/member/head-line and
id tokens redacted, then a blind check that fails with exit 2 if any remains).

**Self-test** `selftest.sh`: 23 checks (reference vs seeded wrong label / wrong correction value under stub pass and
fail grades written from each record's rid; missing, schema-invalid and malformed input; blinding; determinism; pool
audit of ids, segments, decisive index, key discrimination and blinding of all 257 grader inputs).

**Known weaknesses.** (1) Records are short, so many items are one-hop look-ups; ceiling effects are likely and RS may
show few discordant pairs (it was predicted neutral; PROPOSAL §6). Hard items are the variant confusers (T8a/T8b vs
b0v2 records of P10-P12, P14, P25, P30-P36, P39) and descriptor references. (2) A and B items share 77 records
(clustered). (3) NOT_IN_CORPUS relies on the prompt's closed-world sentence. (4) The corpus is the stack's own, local
campaign (contamination unlikely). (5) Grader and arms are Claude models (COMPARE_eq §9 caveat).
