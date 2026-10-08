# B1 v2 reference copies

The design, fit report, prototype and output tables of the B1 v2 Bayesian fit (data-scientist, 2026-10-03), frozen
here on 2026-10-08 (WP0a of the Bayesian-tuning program, `docs/BAYES.md`). Before this they existed only in ignored
work directories. They are reference material: the current design is `docs/BAYES.md` (v3), which supersedes v2 where
they differ. The data they were fitted on is `tests/fixtures/bayes/b1v2/` (sanitized; see its `EVIDENCE.json`).

| file | what | changed from the original |
|---|---|---|
| `design.md` | v2 design (models, censoring, decision rule, integration contract) | ids, paths (below) |
| `fit_report.md` | v2 fit report | ids; section 1 "soft.agent" bullets replaced (below) |
| `fit_prototype.py`, `fit_prototype.py.lock` | the PyMC/nutpie prototype and its uv lock | `fit_prototype.py`: paths (below); the lock is byte-identical |
| `bayes_grid.py` | the stdlib grid tier (Python 3.9, imports `math` only) | none |
| `out_v2/` | the main run's tables, the supplementary clustered backtest (`out_v2/backtest_clustered/`) | session ids in `tables.md`, `backtest_rows.csv`, `backtest_summary.json` (both runs) |
| `out_v2_scope2/` | the scope-2 (graded quality) fit | none |

Not copied: the run logs (absolute paths), `fit_prototype_used.py` (the same script as run, with the same paths),
the v1 files and the failed v2 attempts.

## Edits

1. **Ids.** Every session id is replaced by the first 16 hex of its sha256, and every 8-hex session prefix in prose
   and tables by the first 8 of that hash; agent ids likewise (16 hex). The fixture uses the same map, so
   `backtest_rows.csv`'s `test_session` is the 8-char prefix of the fixture's `session`.
2. **Paths.** `fit_prototype.py:49`: the absolute path of the worktree the v2 fit read (`_W`) is replaced by `""`
   (so the default `B1_REPO` falls back to the repository three levels up). `fit_prototype.py:51, 95` and
   `design.md` section 9.1 name the hooks and agents at their place after the 2026-10-07 restructure
   (`dot-config/dot-claude/...`). To rerun the prototype, set `B1_REPO` to a checkout and pass `--data` the fixture.
3. **T4a fix 3 (HIGH), `fit_report.md` section 1.** The plan-review T4a of 2026-10-03 found the report's explanation
   of the soft.agent overshoot wrong. Its six lines (34-39 of the original) are replaced, marked `EDITED` in place, by
   T4a's text. The original lines, verbatim:

   > **soft.agent runs hot, borderline.**
   > - 4 of the 15 hits are uncensored rows: 4/54 = 7.4 %, on target.
   > - The other 11 are censored rows (open, or partial near a limit) whose recorded ctx already exceeds T. These are real hits. 5 of them are main-coder and 3 security-auditor: large builder runs.
   > - The iid Jeffreys interval excludes 10 %. That interval treats 65 rows of one session as independent, but they share one new-session effect.
   > - The session-clustered predictive puts 15 hits at its 5th–9th percentile. So: hotter than the target, but not decisively outside what the model expects from one new session.
   > - §4 hits less often (15.6 %) because it holds higher values. Its ceiling-based rule is not a 10 % quantile.

   The replacement's numbers (sparse 10/21, PIT mean 0.65 and KS p 0.003; supported 5/44, KS p 0.42) are re-derived
   from `out_v2/backtest_clustered/backtest_rows.csv` in `docs/BAYES.md` §A.10.

Every other finding of T4a is applied in `docs/BAYES.md` §A, not in these copies.

## Hashes of the originals (sha256, before the edits)

```
2ed4c6d3709409cd3305b76d730c4a8498fe84b6c99cba513e7cae4cd15f6480  design.md
9adca36a9772320af15d35ccc58a80f80fa18a04e30689510e57ce092b6c4946  fit_report.md
28b862062a8b9ac7e4f54398e5315c50802afcf09b3e99a4ca73a2a77afe5fad  fit_prototype.py
a31676b5183d425e4f3b8205d5373031bc07fb125599babda60eb869236eea76  fit_prototype.py.lock
d0be5f7bcf4b94b29fc992c0c62ca27a727aeaabc4a95478d4d6b90c5c3c947d  bayes_grid.py
14a9f0f562ef648ee72fd89acfcde2df4a631304c4a75e63e19606e1a63479d2  out_v2/tables.md
adca6b0ba09b832273d8ef62835dce6c2b7a58d09f0c5915526cc7dfdf9c8f1d  out_v2/backtest_rows.csv
03eecb2231d6a87175c2dcc5857d12f3f80c69b80b05c5728dee4e8b0e9f67b1  out_v2/backtest_clustered/backtest_rows.csv
06e1190437d87bf22d25e81048f33d512f7aeddd94e237a4936f3cb8aeddb86f  out_v2/backtest_clustered/backtest_summary.json
```
