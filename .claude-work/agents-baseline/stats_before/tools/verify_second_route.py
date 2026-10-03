# /// script
# requires-python = ">=3.12"
# dependencies = ["duckdb>=1.4"]
# [tool.uv]
# exclude-newer = "2026-10-01T00:00:00Z"
# ///
"""Independent recomputation (SQL, DuckDB) of the headline numbers in stats_before.json, from inputs/ only.

  uv run --script tools/verify_second_route.py     # exit 1 on any mismatch

Shares no code with compute_stats.py: runs are rebuilt in SQL from the collector CSVs, grades joined in SQL,
quantiles by quantile_cont (type 7, same definition as numpy 'linear').
"""
import json
import os
import sys

import duckdb

SB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
I = os.path.join(SB, "inputs")
J = json.load(open(os.path.join(SB, "stats_before.json"), encoding="utf-8"))

con = duckdb.connect()
con.execute(f"""
create view seg as
  select 'old_install' inst, * from read_csv('{I}/baseline/runs.csv', header=true, all_varchar=true)
  union all by name
  select 'new_install' inst, * from read_csv('{I}/collected_fae82d02/runs.csv', header=true, all_varchar=true);
create view gr as
  select id, check_result from read_csv('{I}/baseline/grades.csv', header=true, all_varchar=true)
  union all select id, check_result from read_csv('{I}/baseline/grades_T8b.csv', header=true, all_varchar=true);
create view runs as
  with p as (select * from seg where kind = 'prompt'),
  v as (select inst, prompt_id,
               coalesce(max(regexp_extract(description, '^\\s*P\\d+\\s+([vr]\\d+)\\b', 1)) filter (where is_root='1'
                        and regexp_matches(description, '^\\s*P\\d+\\s+[vr]\\d+\\b')), 'v1') variant
        from p group by all)
  select p.inst, p.prompt_id, v.variant,
         sum(tokens_total::bigint) tok, sum(tokens_total::bigint - tokens_cache_read::bigint) fresh,
         sum(tool_calls::int) tc, sum(turns::int) turns,
         round(epoch(max(("end")::timestamptz)) - epoch(min(start::timestamptz)), 1) dur,
         case when count(distinct agent_type) filter (where is_root='1') > 1 then 'orchestrated'
              else max(agent_type) filter (where is_root='1') end atype
  from p join v using (inst, prompt_id) group by all;
create view rg as
  select r.*, case when r.inst='old_install' and r.variant='v1' then g.check_result end grade
  from runs r left join gr g on g.id = r.prompt_id;
""")

bad = []


def cmp(label, a, b, tol=0.0):
    ok = (a is None and b is None) or (a is not None and b is not None and abs(float(a) - float(b)) <= tol)
    if not ok:
        bad.append(f"{label}: sql={a} json={b}")
    return ok


n_checks = 0
for inst, var, n, npass, npart, nfail, nta, ng, mtok, mfresh, mtc, mdur in con.execute("""
    select inst, variant, count(*), count(*) filter (where grade='pass'), count(*) filter (where grade='partial'),
           count(*) filter (where grade='fail'), count(*) filter (where grade='tool-absent'), count(grade),
           quantile_cont(tok, 0.5), quantile_cont(fresh, 0.5), quantile_cont(tc, 0.5), quantile_cont(dur, 0.5)
    from rg group by all order by all""").fetchall():
    g = J["groups"]["by_install_variant"][f"{inst}|{var}"]
    for lab, a, b in [("n", n, g["n_runs"]), ("pass", npass, g["grades"]["counts"]["pass"]),
                      ("partial", npart, g["grades"]["counts"]["partial"]), ("fail", nfail, g["grades"]["counts"]["fail"]),
                      ("tool-absent", nta, g["grades"]["counts"]["tool-absent"]), ("n_graded", ng, g["grades"]["n_graded"])]:
        cmp(f"{inst}|{var} {lab}", a, b); n_checks += 1
    for lab, a, m in [("median tokens_total", mtok, "tokens_total"), ("median tokens_fresh", mfresh, "tokens_fresh"),
                      ("median tool_calls", mtc, "tool_calls"), ("median duration_s", mdur, "duration_s")]:
        cmp(f"{inst}|{var} {lab}", a, g["metrics"][m]["median"], tol=0.01); n_checks += 1

for inst, at, n, npass in con.execute("""select inst, atype, count(*), count(*) filter (where grade='pass')
                                          from rg group by all order by all""").fetchall():
    g = J["groups"]["by_install_agent_type"][f"{inst}|{at}"]
    cmp(f"{inst}|{at} n", n, g["n_runs"]); cmp(f"{inst}|{at} pass", npass, g["grades"]["counts"]["pass"]); n_checks += 2

for m, col in [("tokens_total", "tok"), ("duration_s", "dur"), ("turns", "turns")]:
    (med,) = con.execute(f"""select quantile_cont(log2(b.{col}/a.{col}), 0.5) from rg a join rg b using (prompt_id)
                             where a.inst='old_install' and a.variant='v1' and b.inst='new_install' and b.variant='v2'
                               and a.{col} > 0 and b.{col} > 0""").fetchone()
    cmp(f"paired median log2 {m}", round(med, 2), J["paired_v1_v2"]["metrics"][m]["median"], tol=0.006); n_checks += 1

(ntot,) = con.execute("select count(*) from rg").fetchone()
cmp("total runs", ntot, J["n"]["runs"]); n_checks += 1
print(f"{n_checks} checks, {len(bad)} mismatches")
for b in bad:
    print("MISMATCH", b)
sys.exit(1 if bad else 0)
