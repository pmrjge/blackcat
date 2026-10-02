# Reading efficiently and extracting claims

Part of `literature-review`.

## 6. Read efficiently and extract claims
Keshav's three passes (ACM SIGCOMM CCR 37(3), 2007, doi:10.1145/1273445.1273458): (1) 5–10 min — title,
abstract, introduction, headings, conclusions, glance at references; answer the five Cs: Category, Context,
Correctness, Contributions, Clarity; drop or continue. (2) Up to an hour — figures, tables, theorem statements,
experimental set-up; mark references to snowball. (3) Several hours — re-derive or virtually re-implement;
hunt hidden assumptions.
- Mathematics: read definitions and hypotheses exactly and compare them with your setting; note the proof technique;
  check whether the result was later strengthened, corrected, refuted or formalized (e.g. in Lean/mathlib).
- Extraction row per claim: claim (verbatim or exact paraphrase) | pinpoint | type (theorem, empirical,
  conjecture, survey statement) | evidence | strength | caveats.
- **Evidence strength.** Mathematics: refereed journal proof > refereed conference with full proof > preprint with
  full proof (weigh follow-ups and known errata) > sketch/announcement; a formal proof certifies exactly the
  formalized statement. Empirical/ML: independent replication > several datasets, tuned strong baselines, ≥ 3 seeds
  with variance, ablations, released code and data > single run or dataset without variance > anecdote; check
  leakage, contamination and compute parity. Surveys orient; cite primary sources for specific claims. Citation
  counts measure attention, not correctness.
