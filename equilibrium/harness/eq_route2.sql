-- eq_route2.sql : analysis route 2 of the agent-equilibrium experiment (COMPARE_eq.md section 6, MEDIATOR.md section 6).
-- Written from harness/LEDGER_SCHEMA.md alone. Run by harness/eq_route2.py, which first creates three tables:
--   raw_ledger(ord BIGINT, rec JSON)            one row per valid line of <run dir>/ledger.jsonl (canonical JSON)
--   raw_grading(cls VARCHAR, ord BIGINT, rec JSON)  lines of <run dir>/grading_results/<CLS>.jsonl (cls = file stem)
--   raw_mediator(ord BIGINT, rec JSON)          lines of every mediator.jsonl found
-- and runs this file as one script. Output tables read back by the runner:
--   res(quantity, cls, arm, stat, value)   everything computed in SQL
--   boot_in(quantity, cls, arm, item, x, y, kind, ci_prefix)   input of the runner-side percentile bootstrap (the one
--                                           thing computed in Python: resampling with a seeded generator)
--   catalog(quantity, section)             the implemented quantities
-- Conventions: score = oracle score of the item-arm (ES: e = |ln(estimate/true)|, lower is better, inf allowed);
-- a status=partial item-arm scores 0 (ES: inf) whether or not a grading line exists (COMPARE_eq section 2).
-- Never writes the semicolon character inside a string or a comment (the runner executes this file as one script).
-- cfg(exclude_wall_used) is created by the runner (--exclude-wall-used). Standalone runs default to false.
-- Shared contract rows (also emitted by route 1, long CSV, stat n, per class x arm over the analysed item-arms):
--   n_unscored    item-arms with no numeric score (no grading line, or the latest line is non-numeric). DS and OE are not counted
--   n_missing     the part of n_unscored that has no grading line at all (a partial item-arm scores by rule and is never missing)
--   n_dup_item_arm item-arms (item, arm, label) written more than once to the ledger (the latest record is used)
--   n_wall_used   item-arms with wall_used true (0 under --exclude-wall-used, which drops them: the runner reports the dropped count)
-- Grading: the latest line per (class file, item, label) by (ts_utc, line number) wins. Infinity (ES only) comes only from
-- score_inf true or the exact string inf. NaN, other non-finite or non-numeric values leave the unit unscored.
CREATE TABLE IF NOT EXISTS cfg (exclude_wall_used BOOLEAN);
INSERT INTO cfg SELECT false WHERE NOT EXISTS (SELECT 1 FROM cfg);

-- ---------------------------------------------------------------------------------------------------------------
-- 0. helpers
-- ---------------------------------------------------------------------------------------------------------------
-- exact median of a list (mean of the two middle values), inf-safe, no interpolation of the engine
CREATE OR REPLACE MACRO med(l) AS (list_sort(l)[(len(l) + 1) // 2] + list_sort(l)[(len(l) + 2) // 2]) / 2.0;
-- binomial log pmf and cdf
CREATE OR REPLACE MACRO lpmf(k, n, p) AS lgamma(n + 1) - lgamma(k + 1) - lgamma(n - k + 1) + k * ln(p) + (n - k) * ln(1 - p);
CREATE OR REPLACE MACRO bcdf(k, n, p) AS
  CASE WHEN k < 0 THEN 0.0 WHEN k >= n THEN 1.0
       ELSE list_sum(list_transform(range(0, CAST(k + 1 AS BIGINT)), j -> exp(lpmf(j, n, p)))) END;
-- exact two-sided sign test with p = 0.5 on w wins and l losses (ties already dropped)
CREATE OR REPLACE MACRO sign_p(w, l) AS
  CASE WHEN w + l = 0 THEN 1.0 ELSE least(1.0, 2.0 * bcdf(least(w, l), w + l, 0.5)) END;
-- Wilson 95 % interval (z = 1.959963984540054)
CREATE OR REPLACE MACRO wilson_lo(k, n) AS
  (k / n + 1.959963984540054 ^ 2 / (2 * n) - 1.959963984540054 * sqrt(k / n * (1 - k / n) / n + 1.959963984540054 ^ 2 / (4 * n * n)))
  / (1 + 1.959963984540054 ^ 2 / n);
CREATE OR REPLACE MACRO wilson_hi(k, n) AS
  (k / n + 1.959963984540054 ^ 2 / (2 * n) + 1.959963984540054 * sqrt(k / n * (1 - k / n) / n + 1.959963984540054 ^ 2 / (4 * n * n)))
  / (1 + 1.959963984540054 ^ 2 / n);

-- ---------------------------------------------------------------------------------------------------------------
-- 1. ledger views
-- ---------------------------------------------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_led AS
SELECT ord, rec, rec->>'record' AS rtype, try_cast(rec->>'seq' AS BIGINT) AS seq, rec->>'ts_utc' AS ts
FROM raw_ledger;

-- one row per call (call_id is unique within a ledger, the latest line wins if a line was duplicated)
CREATE OR REPLACE TABLE v_call AS
SELECT item, cls, label, arm, role, node, member, rnd, cap_usd, cost_usd, tokens, cap_stop, charged_to, call_id
FROM (
  SELECT rec->>'call_id' AS call_id, rec->>'item' AS item, coalesce(rec->>'cls', '?') AS cls,
         rec->>'label' AS label, rec->>'arm' AS arm, rec->>'role' AS role, rec->>'node' AS node,
         try_cast(rec->>'member' AS INTEGER) AS member, try_cast(rec->>'round' AS INTEGER) AS rnd,
         try_cast(rec->>'cap_usd' AS DOUBLE) AS cap_usd, try_cast(rec->>'total_cost_usd' AS DOUBLE) AS cost_usd,
         coalesce(try_cast(rec->'usage'->>'input_tokens' AS BIGINT), 0)
           + coalesce(try_cast(rec->'usage'->>'cache_creation_input_tokens' AS BIGINT), 0)
           + coalesce(try_cast(rec->'usage'->>'cache_read_input_tokens' AS BIGINT), 0)
           + coalesce(try_cast(rec->'usage'->>'output_tokens' AS BIGINT), 0) AS tokens,
         coalesce(try_cast(rec->>'cap_stop' AS BOOLEAN), false) AS cap_stop,
         coalesce(from_json(rec->'charged_to', '["VARCHAR"]'), [rec->>'label']) AS charged_to,
         row_number() OVER (PARTITION BY coalesce(rec->>'call_id', 'seq' || seq::VARCHAR) ORDER BY seq DESC, ord DESC) AS rn
  FROM v_led WHERE rtype = 'call'
) WHERE rn = 1;

-- per item-arm call sums: tokens, USD and cap-stop over the calls whose charged_to contains the label (LEDGER_SCHEMA call.charged_to)
CREATE OR REPLACE TABLE ia_calls AS
SELECT item, label, sum(tokens) AS tokens, sum(coalesce(cost_usd, 0.0)) AS usd, bool_or(cap_stop) AS cap_hit, count(*) AS n_calls
FROM (SELECT item, unnest(charged_to) AS label, tokens, cost_usd, cap_stop FROM v_call)
GROUP BY item, label;

-- item-arm records. Only labels p1-p4, q1-q4 and the declared re-runs p9, q9 are analysed arms (p5 = optional S* screening cell).
-- Per (item, arm) a re-run label (ending in 9) replaces the failed run, otherwise the latest record wins.
-- An E_rt item-arm whose chosen record carries bundle_mismatch (A6 note (d)) is reported only: it leaves the analysis.
CREATE OR REPLACE TABLE ia_base AS
SELECT item, cls, label, arm, status, B, t0, t1, kappa0, kappa, rounds, seq, wall_used, n_same
FROM (
  SELECT rec->>'item' AS item, coalesce(rec->>'cls', '?') AS cls, rec->>'label' AS label, rec->>'arm' AS arm,
         coalesce(rec->>'status', 'ok') AS status, try_cast(rec->>'B_usd' AS DOUBLE) AS B,
         try_cast(rec->>'started_utc' AS TIMESTAMPTZ) AS t0, try_cast(rec->>'ended_utc' AS TIMESTAMPTZ) AS t1,
         try_cast(rec->>'kappa0' AS DOUBLE) AS kappa0, try_cast(rec->>'kappa' AS DOUBLE) AS kappa,
         try_cast(rec->>'rounds' AS INTEGER) AS rounds, seq,
         coalesce(try_cast(rec->>'wall_used' AS BOOLEAN), false) AS wall_used,
         count(*) OVER (PARTITION BY rec->>'item', rec->>'arm', rec->>'label') AS n_same,
         (rec->>'bundle_mismatch') IS NOT NULL AS bundle_mismatch,
         row_number() OVER (PARTITION BY rec->>'item', rec->>'arm'
                            ORDER BY ((rec->>'label') LIKE '%9') DESC, seq DESC, ord DESC) AS rn
  FROM v_led
  WHERE rtype = 'item_arm' AND regexp_matches(coalesce(rec->>'label', ''), '^[pq][1-49]$')
) WHERE rn = 1 AND item IS NOT NULL AND arm IS NOT NULL AND NOT bundle_mismatch;

-- latest grading line per (class file, item, label), item-arm answers only (CR also has per-unit lines with node or member).
-- Order: ts_utc (parsed, else NULL last), then the raw ts_utc string, then the line number. A grading line that is not numeric
-- (the oracle failed: score null) is the latest line like any other and leaves the unit unscored (score NULL, has_grade true).
CREATE OR REPLACE TABLE g_latest AS
SELECT cls, item, label,
       CASE WHEN cls = 'ES' AND (coalesce(try_cast(rec->>'score_inf' AS BOOLEAN), false) OR lower(trim(rec->>'score')) = 'inf')
              THEN 'inf'::DOUBLE
            ELSE CASE WHEN isfinite(v) THEN v END END AS score
FROM (
  SELECT cls, item, label, rec,
         CASE WHEN (rec->>'score_num') IS NOT NULL THEN try_cast(rec->>'score_num' AS DOUBLE)
              WHEN lower(rec->>'score') = 'true' THEN 1.0
              WHEN lower(rec->>'score') = 'false' THEN 0.0
              ELSE try_cast(rec->>'score' AS DOUBLE) END AS v
  FROM (
    SELECT cls, rec->>'item' AS item, rec->>'label' AS label, rec,
           row_number() OVER (PARTITION BY cls, rec->>'item', rec->>'label'
                              ORDER BY try_cast(rec->>'ts_utc' AS TIMESTAMPTZ) DESC NULLS LAST, rec->>'ts_utc' DESC NULLS LAST, ord DESC) AS rn
    FROM raw_grading WHERE (rec->>'node') IS NULL AND (rec->>'member') IS NULL
  ) WHERE rn = 1
);

-- every item-arm with tokens, USD, wall time, cap-hit and the score (before the optional wall_used filter)
CREATE OR REPLACE TABLE ia_all AS
SELECT b.item, b.cls, b.label, b.arm, b.status, b.B, b.kappa0, b.kappa, b.rounds, b.wall_used, b.n_same,
       g.item IS NOT NULL AS has_grade,
       coalesce(c.tokens, 0) AS tokens, coalesce(c.usd, 0.0) AS usd, coalesce(c.cap_hit, false) AS cap_hit,
       coalesce(c.n_calls, 0) AS n_calls,
       CASE WHEN b.t0 IS NOT NULL AND b.t1 IS NOT NULL THEN date_diff('microsecond', b.t0, b.t1) / 1e6 END AS wall_s,
       CASE WHEN b.status = 'partial' THEN (CASE WHEN b.cls = 'ES' THEN 'inf'::DOUBLE ELSE 0.0 END)
            ELSE g.score END AS score
FROM ia_base b
LEFT JOIN ia_calls c ON c.item = b.item AND c.label = b.label
LEFT JOIN g_latest g ON g.item = b.item AND g.label = b.label;

-- the analysed unit: ia_all without the item-arms that used the WALL when --exclude-wall-used is set (X6.6 sensitivity)
CREATE OR REPLACE TABLE ia AS
SELECT * FROM ia_all WHERE NOT wall_used OR NOT (SELECT exclude_wall_used FROM cfg);

CREATE OR REPLACE TABLE res (quantity VARCHAR, cls VARCHAR, arm VARCHAR, stat VARCHAR, value DOUBLE);

-- shared contract rows: data-quality counts per class x arm (zeros are written)
INSERT INTO res
SELECT 'n_unscored', cls, arm, 'n', sum((score IS NULL)::INTEGER)::DOUBLE FROM ia WHERE cls NOT IN ('DS', 'OE') GROUP BY cls, arm
UNION ALL
SELECT 'n_missing', cls, arm, 'n', sum((score IS NULL AND NOT has_grade)::INTEGER)::DOUBLE FROM ia WHERE cls NOT IN ('DS', 'OE') GROUP BY cls, arm
UNION ALL
SELECT 'n_dup_item_arm', cls, arm, 'n', sum((n_same > 1)::INTEGER)::DOUBLE FROM ia GROUP BY cls, arm
UNION ALL
SELECT 'n_wall_used', cls, arm, 'n', sum(wall_used::INTEGER)::DOUBLE FROM ia GROUP BY cls, arm;

-- ---------------------------------------------------------------------------------------------------------------
-- 2. H1 / H2 / H3 (and descriptive EG-S*): win-tie-loss, sign test, Clopper-Pearson, Holm   (COMPARE_eq 2, 6)
-- ---------------------------------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE contrast AS
SELECT * FROM (VALUES ('E-S*', 'E', 'S*', 'H1'), ('E-G', 'E', 'G', 'H2'), ('EG-G', 'EG', 'G', 'H3'), ('EG-S*', 'EG', 'S*', 'H_desc'))
  AS t(name, a, b, hq);

CREATE OR REPLACE TABLE pair AS
SELECT c.name AS contrast, c.hq, a.item, a.cls, a.score AS sa, b.score AS sb,
       a.tokens AS ta, b.tokens AS tb, a.usd AS ua, b.usd AS ub, a.wall_s AS wa, b.wall_s AS wb,
       (a.cap_hit OR b.cap_hit) AS any_cap
FROM contrast c JOIN ia a ON a.arm = c.a JOIN ia b ON b.item = a.item AND b.arm = c.b;

-- comparison set = items with a scored result in both arms. DS and OE (pairwise judge) have no per-item-arm score in the ledger contract.
CREATE OR REPLACE TABLE h_pair AS
SELECT *,
  CASE WHEN cls = 'ES' THEN
         (CASE WHEN sa < sb - ln(1.1) THEN 'w' WHEN sa > sb + ln(1.1) THEN 'l' ELSE 't' END)
       ELSE (CASE WHEN sa > sb THEN 'w' WHEN sa < sb THEN 'l' ELSE 't' END) END AS wtl
FROM pair WHERE sa IS NOT NULL AND sb IS NOT NULL AND cls NOT IN ('DS', 'OE');

CREATE OR REPLACE TABLE h_cnt AS
SELECT hq, contrast, coalesce(cls, 'all') AS cls,
       sum((wtl = 'w')::INTEGER) AS w, sum((wtl = 'l')::INTEGER) AS l, sum((wtl = 't')::INTEGER) AS t, count(*) AS n
FROM h_pair GROUP BY GROUPING SETS ((hq, contrast, cls), (hq, contrast));

-- Clopper-Pearson 95 % by bisection on the exact binomial cdf (48 halvings of [0,1], width 3.6e-15, kept clear of the double spacing at 1)
CREATE OR REPLACE TABLE cp_in AS SELECT DISTINCT w, w + l AS d FROM h_cnt WHERE w + l > 0;
CREATE OR REPLACE TABLE cp_out AS
WITH RECURSIVE lowb(w, d, lo, hi, i) AS (
  SELECT w, d, 0.0::DOUBLE, 1.0::DOUBLE, 0 FROM cp_in WHERE w > 0
  UNION ALL
  SELECT w, d,
         CASE WHEN 1.0 - bcdf(w - 1, d, (lo + hi) / 2) < 0.025 THEN (lo + hi) / 2 ELSE lo END,
         CASE WHEN 1.0 - bcdf(w - 1, d, (lo + hi) / 2) < 0.025 THEN hi ELSE (lo + hi) / 2 END, i + 1
  FROM lowb WHERE i < 48),
upb(w, d, lo, hi, i) AS (
  SELECT w, d, 0.0::DOUBLE, 1.0::DOUBLE, 0 FROM cp_in WHERE w < d
  UNION ALL
  SELECT w, d,
         CASE WHEN bcdf(w, d, (lo + hi) / 2) > 0.025 THEN (lo + hi) / 2 ELSE lo END,
         CASE WHEN bcdf(w, d, (lo + hi) / 2) > 0.025 THEN hi ELSE (lo + hi) / 2 END, i + 1
  FROM upb WHERE i < 48)
SELECT c.w, c.d,
       CASE WHEN c.w = 0 THEN 0.0 ELSE (SELECT (lo + hi) / 2 FROM lowb x WHERE x.w = c.w AND x.d = c.d AND x.i = 48) END AS ci_lo,
       CASE WHEN c.w = c.d THEN 1.0 ELSE (SELECT (lo + hi) / 2 FROM upb x WHERE x.w = c.w AND x.d = c.d AND x.i = 48) END AS ci_hi
FROM cp_in c;

CREATE OR REPLACE TABLE h_stats AS
SELECT h.hq, h.contrast, h.cls, h.w, h.l, h.t, h.n, h.w + h.l AS d,
       (h.w + h.l)::DOUBLE / h.n AS delta_hat,
       CASE WHEN h.w + h.l > 0 THEN h.w::DOUBLE / (h.w + h.l) END AS pi_hat,
       sign_p(h.w, h.l) AS p, o.ci_lo, o.ci_hi
FROM h_cnt h LEFT JOIN cp_out o ON o.w = h.w AND o.d = h.w + h.l;

-- Holm over the primary family {H1_k, H2_k : all classes with a comparison set} and over {H3_k} (pooled 'all' rows excluded).
-- The pre-registered family is the primary classes of the confirmation. Here every class with data is in the family.
CREATE OR REPLACE TABLE h_holm AS
SELECT hq, contrast, cls, least(1.0, max(adj) OVER (PARTITION BY fam ORDER BY rk ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)) AS p_holm
FROM (
  SELECT hq, contrast, cls, fam, rk, (m - rk + 1) * p AS adj
  FROM (
    SELECT hq, contrast, cls, p, CASE WHEN hq IN ('H1', 'H2') THEN 'primary' ELSE hq END AS fam,
           count(*) OVER (PARTITION BY CASE WHEN hq IN ('H1', 'H2') THEN 'primary' ELSE hq END) AS m,
           row_number() OVER (PARTITION BY CASE WHEN hq IN ('H1', 'H2') THEN 'primary' ELSE hq END ORDER BY p, hq, cls) AS rk
    FROM h_stats WHERE cls <> 'all' AND hq IN ('H1', 'H2', 'H3')
  )
);

INSERT INTO res
SELECT hq, cls, contrast, stat, value FROM (
  SELECT s.hq, s.cls, s.contrast, s.w::DOUBLE AS wins, s.l::DOUBLE AS losses, s.t::DOUBLE AS ties, s.n::DOUBLE AS n_comparison,
         s.d::DOUBLE AS n_discordant, s.delta_hat, s.pi_hat, s.p, s.ci_lo, s.ci_hi, h.p_holm
  FROM h_stats s LEFT JOIN h_holm h ON h.hq = s.hq AND h.contrast = s.contrast AND h.cls = s.cls
) UNPIVOT (value FOR stat IN (wins, losses, ties, n_comparison, n_discordant, delta_hat, pi_hat, p, ci_lo, ci_hi, p_holm));

-- ---------------------------------------------------------------------------------------------------------------
-- 3. P1 tokens, P4 wall time, P5 USD: median paired log2 ratio (first-named arm / second)   (COMPARE_eq 6)
--    pairing set = items with an item-arm in both arms and a positive value in both (a grade is not needed for these)
-- ---------------------------------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE p_x AS
SELECT contrast, item, cls, 'P1' AS q, any_cap, CASE WHEN ta > 0 AND tb > 0 THEN log2(ta::DOUBLE / tb) END AS x FROM pair
UNION ALL
SELECT contrast, item, cls, 'P4', any_cap, CASE WHEN wa > 0 AND wb > 0 THEN log2(wa / wb) END FROM pair
UNION ALL
SELECT contrast, item, cls, 'P5', any_cap, CASE WHEN ua > 0 AND ub > 0 THEN log2(ua / ub) END FROM pair;

CREATE OR REPLACE TABLE p_x2 AS
SELECT q AS quantity, contrast AS arm, cls, item, x FROM p_x WHERE x IS NOT NULL
UNION ALL
SELECT q || '_sens', contrast, cls, item, x FROM p_x WHERE x IS NOT NULL AND NOT any_cap AND q IN ('P1', 'P5');

CREATE OR REPLACE TABLE boot_in AS
SELECT quantity, cls, arm, item, x, NULL::DOUBLE AS y, 'median' AS kind, '' AS ci_prefix FROM p_x2
UNION ALL
SELECT quantity, 'all', arm, item, x, NULL::DOUBLE, 'median', '' FROM p_x2;

INSERT INTO res
SELECT quantity, cls, arm, stat, value FROM (
  SELECT quantity, cls, arm, count(*)::DOUBLE AS n, med(list(x)) AS estimate, pow(2.0, med(list(x))) AS ratio
  FROM boot_in WHERE kind = 'median' GROUP BY quantity, cls, arm
) UNPIVOT (value FOR stat IN (n, estimate, ratio));

-- ---------------------------------------------------------------------------------------------------------------
-- 4. P2 score rate / mean score / median e; P3 cap-hit rate; over-cap list (COMPARE_eq 4, 6)
-- ---------------------------------------------------------------------------------------------------------------
-- binary classes PF CP RS: k/n with Wilson. CR: mean score. ES: median e (inf-safe). DS and OE: no per-item-arm score.
INSERT INTO res
SELECT 'P2', cls, arm, stat, value FROM (
  SELECT cls, arm, count(*)::DOUBLE AS n,
         CASE WHEN cls IN ('PF', 'CP', 'RS') THEN sum((score > 0)::INTEGER)::DOUBLE END AS k,
         CASE WHEN cls IN ('PF', 'CP', 'RS') THEN sum((score > 0)::INTEGER)::DOUBLE / count(*)
              WHEN cls = 'CR' THEN avg(score)
              WHEN cls = 'ES' THEN med(list(score)) END AS estimate,
         CASE WHEN cls IN ('PF', 'CP', 'RS') THEN wilson_lo(sum((score > 0)::INTEGER)::DOUBLE, count(*)::DOUBLE) END AS ci_lo,
         CASE WHEN cls IN ('PF', 'CP', 'RS') THEN wilson_hi(sum((score > 0)::INTEGER)::DOUBLE, count(*)::DOUBLE) END AS ci_hi
  FROM ia WHERE score IS NOT NULL AND cls IN ('PF', 'CP', 'RS', 'CR', 'ES') GROUP BY cls, arm
) UNPIVOT (value FOR stat IN (n, k, estimate, ci_lo, ci_hi));

INSERT INTO res
SELECT 'P3', coalesce(cls, 'all'), arm, stat, value FROM (
  SELECT cls, arm, count(*)::DOUBLE AS n, sum(cap_hit::INTEGER)::DOUBLE AS k,
         sum(cap_hit::INTEGER)::DOUBLE / count(*) AS estimate,
         wilson_lo(sum(cap_hit::INTEGER)::DOUBLE, count(*)::DOUBLE) AS ci_lo,
         wilson_hi(sum(cap_hit::INTEGER)::DOUBLE, count(*)::DOUBLE) AS ci_hi
  FROM ia GROUP BY GROUPING SETS ((cls, arm), (arm))
) UNPIVOT (value FOR stat IN (n, k, estimate, ci_lo, ci_hi));

-- item-arms whose summed total_cost_usd exceeds B by more than 10 percent (stay in, listed by count here)
INSERT INTO res
SELECT 'over_cap', coalesce(cls, 'all'), arm, stat, value FROM (
  SELECT cls, arm, count(*)::DOUBLE AS n, sum((usd > 1.1 * B)::INTEGER)::DOUBLE AS k
  FROM ia WHERE B IS NOT NULL GROUP BY GROUPING SETS ((cls, arm), (arm))
) UNPIVOT (value FOR stat IN (n, k));

-- ---------------------------------------------------------------------------------------------------------------
-- 5. M10 cap overshoot per call = total_cost_usd / cap_usd (calls with a cost and a positive cap)
-- ---------------------------------------------------------------------------------------------------------------
INSERT INTO res
SELECT 'M10', coalesce(cls, 'all'), coalesce(arm, 'all'), stat, value FROM (
  SELECT cls, arm, count(*)::DOUBLE AS n, med(list(cost_usd / cap_usd)) AS median, max(cost_usd / cap_usd) AS max
  FROM v_call c WHERE cost_usd IS NOT NULL AND cap_usd > 0
    AND NOT EXISTS (SELECT 1 FROM ia_all w WHERE w.item = c.item AND w.label = c.label AND w.wall_used
                    AND (SELECT exclude_wall_used FROM cfg))   -- the calls of wall_used item-arms leave with them
  GROUP BY GROUPING SETS ((cls, arm), (arm), ()) HAVING count(*) > 0
) UNPIVOT (value FOR stat IN (n, median, max));

-- ---------------------------------------------------------------------------------------------------------------
-- 6. M4 reconcile: changes, evidence-accepted changes, conformity rate (reconcile records; item, label, arm via call_id)
-- ---------------------------------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE m_rec AS
SELECT coalesce(r.rec->>'item', c.item) AS item, coalesce(r.rec->>'label', c.label) AS label, coalesce(r.rec->>'arm', c.arm) AS arm,
       coalesce(try_cast(r.rec->>'changed' AS BOOLEAN), false) AS changed,
       coalesce(try_cast(r.rec->>'accepted' AS BOOLEAN), false) AS accepted,
       coalesce(try_cast(r.rec->>'conformity' AS BOOLEAN), false) AS conformity
FROM v_led r LEFT JOIN v_call c ON c.call_id = (r.rec->>'call_id') WHERE r.rtype = 'reconcile';

INSERT INTO res
SELECT 'M4', coalesce(cls, 'all'), arm, stat, value FROM (
  SELECT i.cls, m.arm, count(*)::DOUBLE AS n_reconciles, sum(changed::INTEGER)::DOUBLE AS changed,
         sum(accepted::INTEGER)::DOUBLE AS accepted, sum(conformity::INTEGER)::DOUBLE AS conformity,
         sum(conformity::INTEGER)::DOUBLE / nullif(sum(changed::INTEGER), 0) AS conformity_rate
  FROM m_rec m JOIN ia i ON i.item = m.item AND i.label = m.label AND i.arm = m.arm
  GROUP BY GROUPING SETS ((i.cls, m.arm), (m.arm))
) UNPIVOT (value FOR stat IN (n_reconciles, changed, accepted, conformity, conformity_rate));

-- ---------------------------------------------------------------------------------------------------------------
-- 7. M5 / M8 (E arm, binary classes PF CP RS, round-0 agreement kappa0), M2 / M3 (public check of round-0 members)
-- ---------------------------------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE e_bin AS
SELECT item, label, cls, kappa0, 1.0 - kappa0 AS unc, (score <= 0)::DOUBLE AS err, score
FROM ia WHERE arm = 'E' AND cls IN ('PF', 'CP', 'RS') AND score IS NOT NULL AND kappa0 IS NOT NULL;

-- AUROC of x for predicting y = 1, ties count half (equals the rank formula with average ranks)
CREATE OR REPLACE TABLE auc_in AS
SELECT 'M5' AS quantity, cls, item, unc AS x, err AS y, '' AS ci_prefix FROM e_bin
UNION ALL SELECT 'M5', 'all', item, unc, err, '' FROM e_bin;

-- M15 inputs (E arm: reducer disagreement) are added in section 9 once the mediator tables exist.

-- M8 accuracy by kappa0 bin (upper edges 0.2 0.4 0.6 0.8 1.0)
CREATE OR REPLACE TABLE m8 AS
SELECT coalesce(cls, 'all') AS cls, bin,
       count(*)::DOUBLE AS n, sum((score > 0)::INTEGER)::DOUBLE AS k, avg((score > 0)::INTEGER) AS rate
FROM (SELECT cls, score, CASE WHEN kappa0 <= 0.2 + 1e-9 THEN '0.2' WHEN kappa0 <= 0.4 + 1e-9 THEN '0.4'
                              WHEN kappa0 <= 0.6 + 1e-9 THEN '0.6' WHEN kappa0 <= 0.8 + 1e-9 THEN '0.8' ELSE '1.0' END AS bin
      FROM e_bin)
GROUP BY GROUPING SETS ((cls, bin), (bin));
INSERT INTO res
SELECT 'M8', cls, 'E', 'n_bin_' || bin, n FROM m8
UNION ALL SELECT 'M8', cls, 'E', 'k_bin_' || bin, k FROM m8
UNION ALL SELECT 'M8', cls, 'E', 'rate_bin_' || bin, rate FROM m8;

-- round-0 public check per member (E arm, checkable classes): who passed
CREATE OR REPLACE TABLE chk0 AS
SELECT item, label, member, passed FROM (
  SELECT rec->>'item' AS item, rec->>'label' AS label, try_cast(rec->>'member' AS INTEGER) AS member,
         coalesce(try_cast(rec->>'passed' AS BOOLEAN), false) AS passed,
         row_number() OVER (PARTITION BY rec->>'item', rec->>'label', rec->>'member' ORDER BY seq DESC, ord DESC) AS rn
  FROM v_led WHERE rtype = 'check' AND coalesce(try_cast(rec->>'round' AS INTEGER), 0) = 0 AND (rec->>'arm') = 'E'
) WHERE rn = 1;

CREATE OR REPLACE TABLE chk_item AS
SELECT i.item, i.cls, count(*) AS n_members, sum(c.passed::INTEGER) AS y, i.score
FROM chk0 c JOIN ia i ON i.item = c.item AND i.label = c.label AND i.arm = 'E'
GROUP BY i.item, i.cls, i.score;

-- M3: oracle@N proxied by the public check (any round-0 member passes) vs the reducer's graded score
INSERT INTO res
SELECT 'M3', cls, 'E', stat, value FROM (
  SELECT cls, count(*)::DOUBLE AS n, avg((y > 0)::INTEGER) AS public_check_at_N, avg(score) AS reducer_score,
         avg((y > 0)::INTEGER) - avg(score) AS selection_loss
  FROM chk_item WHERE score IS NOT NULL GROUP BY cls
) UNPIVOT (value FOR stat IN (n, public_check_at_N, reducer_score, selection_loss));

-- M2: moment estimator of rho (members of an item are exchangeable), N = modal member count, items with that N
INSERT INTO res
SELECT 'M2', cls, 'E', stat, value FROM (
  SELECT cls, nn::DOUBLE AS N, count(*)::DOUBLE AS n_items, p_hat,
         CASE WHEN nn > 1 AND p_hat > 0 AND p_hat < 1
              THEN (avg((y - nn * p_hat) ^ 2) / (nn * p_hat * (1 - p_hat)) - 1) / (nn - 1) END AS rho_hat,
         CASE WHEN nn > 1 AND p_hat > 0 AND p_hat < 1
              THEN nn / (1 + (nn - 1) * ((avg((y - nn * p_hat) ^ 2) / (nn * p_hat * (1 - p_hat)) - 1) / (nn - 1))) END AS n_eff
  FROM (
    SELECT c.cls, c.y, m.nn, sum(c.y) OVER (PARTITION BY c.cls)::DOUBLE / (m.nn * count(*) OVER (PARTITION BY c.cls)) AS p_hat
    FROM chk_item c JOIN (SELECT cls, max(n_members) AS nn FROM chk_item GROUP BY cls) m ON m.cls = c.cls AND c.n_members = m.nn
  ) GROUP BY cls, nn, p_hat
) UNPIVOT (value FOR stat IN (N, n_items, p_hat, rho_hat, n_eff));

-- ---------------------------------------------------------------------------------------------------------------
-- 8. mediator ledger tables (MEDIATOR.md, LEDGER_SCHEMA "Mediator ledger"). item-arm identity joins to ia (arm, class)
-- ---------------------------------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE m_all AS
SELECT ord, rec, rec->>'record' AS rtype, rec->>'item' AS item, rec->>'label' AS label, rec->>'node' AS node,
       rec->>'ts_utc' AS ts, try_cast(rec->>'seq' AS BIGINT) AS seq
FROM raw_mediator;

-- distinct facts per item-arm (latest line per fact_key wins)
CREATE OR REPLACE TABLE m_fact AS
SELECT item, label, fact_key, status FROM (
  SELECT item, label, rec->>'fact_key' AS fact_key, rec->>'status' AS status,
         row_number() OVER (PARTITION BY item, label, rec->>'fact_key' ORDER BY ts DESC, ord DESC) AS rn
  FROM m_all WHERE rtype = 'fact'
) WHERE rn = 1;

CREATE OR REPLACE TABLE m_result AS
SELECT item, label, node, rec FROM (
  SELECT item, label, node, rec, row_number() OVER (PARTITION BY item, label, coalesce(node, '') ORDER BY ts DESC, ord DESC) AS rn
  FROM m_all WHERE rtype = 'result'
) WHERE rn = 1;

CREATE OR REPLACE TABLE m_attr AS
SELECT item, label, node, rec FROM (
  SELECT item, label, node, rec, row_number() OVER (PARTITION BY item, label, coalesce(node, '') ORDER BY ts DESC, ord DESC) AS rn
  FROM m_all WHERE rtype = 'attribution' AND (rec->>'round') IS NULL  -- per-round jackknife lines (A6) are not nodes
) WHERE rn = 1;

CREATE OR REPLACE TABLE m_change AS
SELECT item, label, rec->>'gate' AS gate FROM m_all WHERE rtype = 'change';

-- M12 fact status rates per arm and class (distinct facts per item-arm)
-- denominator of facts_per_item_arm = item-arms that have at least one mediator record
CREATE OR REPLACE TABLE ia_med AS
SELECT coalesce(cls, 'all') AS cls, arm, count(*)::DOUBLE AS n_item_arms
FROM ia WHERE EXISTS (SELECT 1 FROM m_all m WHERE m.item = ia.item AND m.label = ia.label)
GROUP BY GROUPING SETS ((cls, arm), (arm));

INSERT INTO res
SELECT 'M12', cls, arm, stat, value FROM (
  SELECT g.cls, g.arm, g.n_facts, g.verified, g.refuted, g.unverifiable, g.verified_rate, g.refuted_rate, g.unverifiable_rate,
         g.n_facts / d.n_item_arms AS facts_per_item_arm
  FROM (
    SELECT coalesce(i.cls, 'all') AS cls, i.arm, count(*)::DOUBLE AS n_facts,
           sum((f.status = 'verified')::INTEGER)::DOUBLE AS verified, sum((f.status = 'refuted')::INTEGER)::DOUBLE AS refuted,
           sum((f.status = 'unverifiable')::INTEGER)::DOUBLE AS unverifiable,
           avg((f.status = 'verified')::INTEGER) AS verified_rate, avg((f.status = 'refuted')::INTEGER) AS refuted_rate,
           avg((f.status = 'unverifiable')::INTEGER) AS unverifiable_rate
    FROM m_fact f JOIN ia i ON i.item = f.item AND i.label = f.label
    GROUP BY GROUPING SETS ((i.cls, i.arm), (i.arm))
  ) g JOIN ia_med d ON d.cls = g.cls AND d.arm = g.arm
) UNPIVOT (value FOR stat IN (n_facts, verified, refuted, unverifiable, verified_rate, refuted_rate, unverifiable_rate, facts_per_item_arm));

-- M11 influence concentration: HHI of the stored agreement-game shares, share of "dictator" nodes (max share >= 0.5)
CREATE OR REPLACE TABLE m11_node AS
SELECT a.item, a.label, a.node,
       coalesce(try_cast(a.rec->'hhi'->>'float' AS DOUBLE), try_cast(a.rec->>'hhi' AS DOUBLE)) AS hhi,
       max(coalesce(try_cast(je.value->>'float' AS DOUBLE), try_cast(je.value::VARCHAR AS DOUBLE))) AS max_phi
FROM m_attr a LEFT JOIN LATERAL json_each(a.rec->'shapley') je ON true
GROUP BY a.item, a.label, a.node, a.rec;

INSERT INTO res
SELECT 'M11', coalesce(cls, 'all'), arm, stat, value FROM (
  SELECT i.cls, i.arm, count(m.hhi)::DOUBLE AS n, avg(m.hhi) AS mean_hhi,
         avg((m.max_phi >= 0.5)::INTEGER) AS dictator_share, sum((m.max_phi >= 0.5)::INTEGER)::DOUBLE AS n_dictator
  FROM m11_node m JOIN ia i ON i.item = m.item AND i.label = m.label
  GROUP BY GROUPING SETS ((i.cls, i.arm), (i.arm))
) UNPIVOT (value FOR stat IN (n, mean_hhi, dictator_share, n_dictator));

-- M13 leave-one-out stability: share of nodes whose every stored final-round LOO result equals the node's end answer
CREATE OR REPLACE TABLE m13_node AS
SELECT a.item, a.label, a.node, bool_and(je.value::VARCHAR = coalesce((r.rec->'answer')::VARCHAR, 'null')) AS stable
FROM m_attr a JOIN m_result r ON r.item = a.item AND r.label = a.label AND coalesce(r.node, '') = coalesce(a.node, ''),
     json_each(a.rec->'loo_final') je
GROUP BY a.item, a.label, a.node;

INSERT INTO res
SELECT 'M13', coalesce(cls, 'all'), arm, stat, value FROM (
  SELECT i.cls, i.arm, count(*)::DOUBLE AS n, sum(m.stable::INTEGER)::DOUBLE AS k, avg(m.stable::INTEGER) AS estimate
  FROM m13_node m JOIN ia i ON i.item = m.item AND i.label = m.label
  GROUP BY GROUPING SETS ((i.cls, i.arm), (i.arm))
) UNPIVOT (value FOR stat IN (n, k, estimate));

-- M14 decisive facts (share of nodes with at least one) and reconcile flips (evidence-gated vs conformity)
INSERT INTO res
SELECT 'M14', coalesce(cls, 'all'), arm, stat, value FROM (
  SELECT i.cls, i.arm, count(*)::DOUBLE AS n,
         sum(((coalesce(json_array_length(a.rec->'decisive_facts'->'reconcile'), 0)
             + coalesce(json_array_length(a.rec->'decisive_facts'->'R1'), 0)
             + coalesce(json_array_length(a.rec->'decisive_facts'->'R3'), 0)) > 0)::INTEGER)::DOUBLE AS n_with_decisive,
         avg(((coalesce(json_array_length(a.rec->'decisive_facts'->'reconcile'), 0)
             + coalesce(json_array_length(a.rec->'decisive_facts'->'R1'), 0)
             + coalesce(json_array_length(a.rec->'decisive_facts'->'R3'), 0)) > 0)::INTEGER) AS decisive_share
  FROM m_attr a JOIN ia i ON i.item = a.item AND i.label = a.label
  GROUP BY GROUPING SETS ((i.cls, i.arm), (i.arm))
) UNPIVOT (value FOR stat IN (n, n_with_decisive, decisive_share));

INSERT INTO res
SELECT 'M14', coalesce(cls, 'all'), arm, stat, value FROM (
  SELECT i.cls, i.arm, count(*)::DOUBLE AS n_changes, sum((c.gate = 'evidence')::INTEGER)::DOUBLE AS flips_evidence,
         sum((c.gate = 'conformity')::INTEGER)::DOUBLE AS flips_conformity,
         avg((c.gate = 'conformity')::INTEGER) AS conformity_share
  FROM m_change c JOIN ia i ON i.item = c.item AND i.label = c.label
  GROUP BY GROUPING SETS ((i.cls, i.arm), (i.arm))
) UNPIVOT (value FOR stat IN (n_changes, flips_evidence, flips_conformity, conformity_share));

-- M18 reducer and attribution CPU time per node, USD of the RS equivalence call
INSERT INTO res
SELECT 'M18', coalesce(cls, 'all'), arm, stat, value FROM (
  SELECT i.cls, i.arm, count(*)::DOUBLE AS n, med(list(try_cast(a.rec->>'cpu_s' AS DOUBLE))) AS cpu_s_median,
         sum(try_cast(a.rec->>'cpu_s' AS DOUBLE)) AS cpu_s_sum
  FROM m_attr a JOIN ia i ON i.item = a.item AND i.label = a.label WHERE try_cast(a.rec->>'cpu_s' AS DOUBLE) IS NOT NULL
  GROUP BY GROUPING SETS ((i.cls, i.arm), (i.arm))
) UNPIVOT (value FOR stat IN (n, cpu_s_median, cpu_s_sum));

INSERT INTO res
SELECT 'M18', coalesce(cls, 'all'), arm, stat, value FROM (
  SELECT i.cls, i.arm, count(*)::DOUBLE AS equivalence_calls, sum(coalesce(c.cost_usd, 0.0)) AS equivalence_usd
  FROM v_led r JOIN v_call c ON c.call_id = (r.rec->>'call_id') JOIN ia i ON i.item = c.item AND i.label = c.label AND i.arm = c.arm
  WHERE r.rtype = 'reduce' AND (r.rec->>'reducer') = 'equivalence'
  GROUP BY GROUPING SETS ((i.cls, i.arm), (i.arm))
) UNPIVOT (value FOR stat IN (equivalence_calls, equivalence_usd));

-- ---------------------------------------------------------------------------------------------------------------
-- 9. M15 reducer disagreement over {R0 R1 R2 R3 ENS} of the stored results, AUROC of disagreement vs 1 - kappa0
-- ---------------------------------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE m_red AS
SELECT r.item, r.label, r.node, count(*) AS n_red, count(DISTINCT je.value::VARCHAR) AS n_distinct
FROM m_result r, json_each(r.rec->'reducers') je
WHERE je.key IN ('R0', 'R1', 'R2', 'R3', 'ENS') GROUP BY r.item, r.label, r.node;

INSERT INTO res
SELECT 'M15', coalesce(cls, 'all'), arm, stat, value FROM (
  SELECT i.cls, i.arm, count(*)::DOUBLE AS n, sum((m.n_distinct > 1)::INTEGER)::DOUBLE AS n_disagree,
         avg((m.n_distinct > 1)::INTEGER) AS disagreement_rate
  FROM m_red m JOIN ia i ON i.item = m.item AND i.label = m.label WHERE m.n_red >= 2
  GROUP BY GROUPING SETS ((i.cls, i.arm), (i.arm))
) UNPIVOT (value FOR stat IN (n, n_disagree, disagreement_rate));

CREATE OR REPLACE TABLE e_red AS
SELECT b.item, b.cls, (m.n_distinct > 1)::DOUBLE AS disagree, b.unc, b.err
FROM e_bin b JOIN m_red m ON m.item = b.item AND m.label = b.label AND coalesce(m.node, '') = '' AND m.n_red >= 2;

INSERT INTO auc_in
SELECT 'M15', cls, item, disagree, err, 'auroc_disagreement_' FROM e_red
UNION ALL SELECT 'M15', 'all', item, disagree, err, 'auroc_disagreement_' FROM e_red
UNION ALL SELECT 'M15', cls, item, unc, err, 'auroc_kappa_' FROM e_red
UNION ALL SELECT 'M15', 'all', item, unc, err, 'auroc_kappa_' FROM e_red;

-- AUROC point estimates (M5 and M15)
INSERT INTO res
SELECT p.quantity, p.cls, 'E', CASE WHEN p.quantity = 'M5' THEN 'auroc' ELSE rtrim(p.ci_prefix, '_') END,
       sum(CASE WHEN p.x > q.x THEN 1.0 WHEN p.x = q.x THEN 0.5 ELSE 0.0 END) / count(*)
FROM auc_in p JOIN auc_in q ON q.quantity = p.quantity AND q.cls = p.cls AND q.ci_prefix = p.ci_prefix
WHERE p.y = 1 AND q.y = 0 GROUP BY p.quantity, p.cls, p.ci_prefix;

INSERT INTO res
SELECT quantity, cls, 'E', stat, value FROM (
  SELECT quantity, cls, count(*)::DOUBLE AS n, sum(y)::DOUBLE AS n_error, (count(*) - sum(y))::DOUBLE AS n_ok
  FROM auc_in WHERE ci_prefix IN ('', 'auroc_kappa_') GROUP BY quantity, cls
) UNPIVOT (value FOR stat IN (n, n_error, n_ok));

INSERT INTO boot_in
SELECT quantity, cls, 'E', item, x, y, 'auc', ci_prefix FROM auc_in;

-- ---------------------------------------------------------------------------------------------------------------
-- 10. catalog of the implemented quantities (the runner writes it to quantities.txt)
-- ---------------------------------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE catalog AS
SELECT * FROM (VALUES
  ('H1', 'COMPARE_eq.md section 6 Primary (E vs S*)'), ('H2', 'COMPARE_eq.md section 6 Primary (E vs G)'),
  ('H3', 'COMPARE_eq.md section 6 Secondary (EG vs G)'), ('H_desc', 'COMPARE_eq.md section 6 (descriptive EG vs S*)'),
  ('P1', 'COMPARE_eq.md section 6 Primary'), ('P1_sens', 'COMPARE_eq.md section 4 Censoring (P1 without cap-hit item-arms)'),
  ('P2', 'COMPARE_eq.md section 6 Secondary'), ('P3', 'COMPARE_eq.md section 6 Secondary'),
  ('P4', 'COMPARE_eq.md section 6 Secondary'), ('P5', 'COMPARE_eq.md section 6 Secondary'),
  ('P5_sens', 'COMPARE_eq.md section 4 Censoring (P5 without cap-hit item-arms)'),
  ('over_cap', 'COMPARE_eq.md section 4 Over-cap'),
  ('M2', 'COMPARE_eq.md section 6 Mechanistic (moment estimator, public-check proxy)'),
  ('M3', 'COMPARE_eq.md section 6 Mechanistic (public-check proxy)'),
  ('M4', 'COMPARE_eq.md section 6 Mechanistic (conformity counts only)'),
  ('M5', 'COMPARE_eq.md section 6 Mechanistic'), ('M8', 'COMPARE_eq.md section 6 Mechanistic'),
  ('M10', 'COMPARE_eq.md section 6 Mechanistic'),
  ('M11', 'COMPARE_eq.md section 12 A0.5 / MEDIATOR.md section 6'), ('M12', 'COMPARE_eq.md section 12 A0.5 / MEDIATOR.md section 6'),
  ('M13', 'COMPARE_eq.md section 12 A0.5 / MEDIATOR.md section 6 (stability only)'),
  ('M14', 'COMPARE_eq.md section 12 A0.5 / MEDIATOR.md section 6'),
  ('M15', 'COMPARE_eq.md section 12 A0.5 / MEDIATOR.md section 6'),
  ('M18', 'COMPARE_eq.md section 12 A0.5 / MEDIATOR.md section 6'),
  ('n_unscored', 'shared contract row: item-arms without a numeric score (DS and OE not counted)'),
  ('n_missing', 'shared contract row: item-arms with no grading line at all'),
  ('n_dup_item_arm', 'shared contract row: item-arms written more than once to the ledger'),
  ('n_wall_used', 'shared contract row: item-arms with wall_used true (0 under --exclude-wall-used)')) AS t(quantity, section);
