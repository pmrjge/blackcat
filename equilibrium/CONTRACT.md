# Item-pool / harness interface contract (L1 coordinator, 2026-10-04; binding for E1-E8)
STAGE=equilibrium
Design: STAGE/PROPOSAL.md; measurement: STAGE/COMPARE_eq.md (wins over PROPOSAL). Classes CLS in {PF, CP, CR, RS, ES, DS, OE}.

## Per class folder STAGE/items/<CLS>/
- `manifest.jsonl` one JSON object per item:
  `id` ("<CLS>-0001".., dev items "<CLS>-DEV1".."<CLS>-DEV3"), `class`, `dev` (bool),
  `answer_kind` (discrete | checkable | finding_set | numeric | long_form),
  `prompt` (text shown to every arm; never contains oracle material),
  `segments` (list of {"id", "path"} relative to the fixture, or {"id", "text"}; canonical order already shuffled once with
  seed `eq|items` = numpy.random.default_rng(3725927731) per COMPARE_eq §3), `decisive_segment` (index into segments or null),
  `fixture` (path relative to the class folder, copied fresh per call; null if none),
  `public_check` (argv list arms and the reducer may run, e.g. public tests or the Lean check; null if none),
  `allowed_tools` (the class's frozen --allowedTools list).
- `schema.json` JSON Schema of the arm output (PROPOSAL §2): `answer` (canonical per class), `evidence[]` (kind in
  command | file_line | quote | counterexample | test, each with `ref`, `detail`), `confidence` in [0,1].
- `oracle/` hidden material (hidden tests, keys, bug manifests, true values with source URL and access date). Never
  referenced by `prompt`, `fixture` or `public_check`.
- `oracle.py` uv PEP 723 script: `uv run oracle.py --item <id> --answer <answer.json> [--workdir <patched fixture copy>]`
  prints one JSON line {"item","score","detail"} using the COMPARE_eq §2 score. Grader-scored classes (RS, DS, OE; CR false-
  finding marks) also support `--grader-input <out.json>` (writes the blinded grader input: no arm label, no member ids)
  and `--grade <grader.json>` (finalises the score). Exit 0 when scored, 2 on malformed input.
- `selftest.sh` runs the oracle on every dev item with a reference answer (must score as correct) and a seeded wrong
  answer (must score as wrong); prints one PASS/FAIL line per check and exits non-zero on any FAIL.
- `pool.sha256` `shasum -a 256` lines over manifest.jsonl, schema.json, oracle.py, selftest.sh, oracle/**, fixtures/**
  and the generator (if the pool is generated: generator script + frozen seed; its hash is in this file).
- Size: >= 180 non-dev items (or a seeded generator with a frozen hash that emits >= 180) plus 3 dev items. If the
  budget does not allow 180, deliver what is proven and report the count (a class below its confirmation n cannot be
  primary, COMPARE_eq §3).
- `README.md` <= 40 lines: how the items were made, counts, known weaknesses.

## Shared files
- `STAGE/items/lenses.json` (owner E3): {"<CLS>": [5 lens sentences]} per PROPOSAL §2 table.
- `STAGE/items/graders/` (owner E3): grader briefs for RS, DS, OE and the CR false-finding grader.

## Harness STAGE/harness/ (owner E4) consumes only the above; it never reads `oracle/` except through `oracle.py`.
