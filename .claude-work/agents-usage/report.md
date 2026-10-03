# Token usage per agent, session 4e2da3ce-e2f4-4971-aac5-a67f2dcf252e

Source: per-agent transcripts under `~/.claude/projects/<project>/<session>/subagents/agent-<id>.jsonl`, main thread `<session>.jsonl`, ledger `delegations.md`. Script: `usage.py`; raw: `usage.csv`. No prompts or transcript text included.

Method: assistant records are deduplicated by `message.id` (a streamed message appears in 2-3 records; per field the maximum is kept, since output_tokens grows while streaming). Tool calls = distinct `tool_use` ids. Wall time = last minus first record timestamp in that transcript, so it includes idle gaps while a resumed agent waited (it is not busy time). `fresh` = input + output + cache creation; `cache read` is re-read context, billed at a fraction of fresh. Ledger times are local (UTC+1); transcript timestamps are UTC.

## Grand total

| scope | input | output | cache creation | cache read | total | fresh (in+out+cc) | cache read share | assistant turns |
|---|---|---|---|---|---|---|---|---|
| Subagents (46) | 4,836 | 2,614,218 | 10,404,333 | 360,538,842 | 373,562,229 | 13,023,387 | 96.5% | 2,373 |
| Main thread | 252 | 73,102 | 173,680 | 14,635,013 | 14,882,047 | 247,034 | 98.3% | 126 |
| Grand total | 5,088 | 2,687,320 | 10,578,013 | 375,173,855 | 388,444,276 | 13,270,421 | 96.6% | 2,499 |


## Per agent type (subagents only; share is of the grand total including main)

| type | runs | total tokens | mean per run | fresh | cache read | output | turns | tool calls | summed wall | share |
|---|---|---|---|---|---|---|---|---|---|---|
| claude-code-engineer | 16 | 301,359,997 | 18,834,999 | 9,571,779 | 291,788,218 | 1,871,023 | 1,722 | 2,030 | 13h33m | 77.6% |
| verifier | 5 | 29,346,106 | 5,869,221 | 769,302 | 28,576,804 | 222,487 | 231 | 262 | 47m46s | 7.6% |
| orchestrator | 1 | 15,888,159 | 15,888,159 | 541,401 | 15,346,758 | 131,714 | 80 | 92 | 6h43m | 4.1% |
| code-reviewer | 3 | 9,546,519 | 3,182,173 | 365,824 | 9,180,695 | 73,392 | 125 | 126 | 22m21s | 2.5% |
| planner | 2 | 6,676,421 | 3,338,210 | 589,329 | 6,087,092 | 183,076 | 54 | 104 | 29m16s | 1.7% |
| researcher | 1 | 6,434,246 | 6,434,246 | 240,345 | 6,193,901 | 55,239 | 52 | 65 | 11m32s | 1.7% |
| claude-code-guide | 6 | 1,797,616 | 299,602 | 436,669 | 1,360,947 | 26,066 | 39 | 65 | 7m57s | 0.5% |
| scout | 10 | 1,488,677 | 148,867 | 383,626 | 1,105,051 | 35,205 | 49 | 153 | 6m46s | 0.4% |
| coder | 2 | 1,024,488 | 512,244 | 125,112 | 899,376 | 16,016 | 21 | 21 | 2m18s | 0.3% |


## Per phase (by task label prefix; children inherit nothing, they fall under their own label, e.g. unlabelled scouts are Other)

| phase | runs | total | fresh | cache read | cache read % | share |
|---|---|---|---|---|---|---|
| Phase 1 (T*) | 8 | 61,917,674 | 2,431,231 | 59,486,443 | 96.1% | 15.9% |
| Phase 2 (P*) | 12 | 159,541,868 | 5,748,639 | 153,793,229 | 96.4% | 41.1% |
| Phase 3 (Q*) | 9 | 108,601,655 | 3,087,155 | 105,514,500 | 97.2% | 28.0% |
| BlackCat main thread | 1 | 14,882,047 | 247,034 | 14,635,013 | 98.3% | 3.8% |
| Other (orchestrator, coder, verifier, unlabelled) | 17 | 43,501,032 | 1,756,362 | 41,744,670 | 96.0% | 11.2% |


## 10 most expensive runs (by total)

| id | task [type] | total | fresh | cache read | turns | tool calls | wall |
|---|---|---|---|---|---|---|---|
| abf61455daf8bf39a | P4 A1 budget tooling overrides [claude-code-engineer] | 50,583,870 | 1,057,241 | 49,526,629 | 283 | 301 | 1h39m |
| aa3cecbac36d6c0d6 | P7 S3 skills cross-cutting [claude-code-engineer] | 30,114,588 | 1,047,312 | 29,067,276 | 168 | 205 | 1h19m |
| a66abc25551ca1e2a | Q6 evaluate skill lookup designs [claude-code-engineer] | 26,378,415 | 706,029 | 25,672,386 | 133 | 140 | 55m00s |
| aa1cdc5f97419bc71 | Set up before/after benchmark harness [verifier] | 23,821,407 | 441,516 | 23,379,891 | 129 | 151 | 21m54s |
| aa28ddfef1cbe8a53 | Q3 tighten skills n-z rules [claude-code-engineer] | 23,541,051 | 380,596 | 23,160,455 | 127 | 127 | 30m50s |
| a739e537b64de1bce | P5 S1 skills languages infra [claude-code-engineer] | 21,520,636 | 1,072,006 | 20,448,630 | 130 | 183 | 1h18m |
| ac736ac036119caf0 | P6 S2 skills domains [claude-code-engineer] | 19,658,210 | 833,638 | 18,824,572 | 89 | 140 | 1h18m |
| a8b5ace94c0276da1 | T6 tighten agents budget script [claude-code-engineer] | 17,737,363 | 475,152 | 17,262,211 | 84 | 165 | 25m58s |
| ac215a9dfa703d3a7 | Q7 Agent SDK integration [claude-code-engineer] | 16,742,904 | 796,737 | 15,946,167 | 98 | 109 | 42m47s |
| a1950e4e0c6d060a5 | Q10 contingency fix kit [claude-code-engineer] | 16,337,944 | 339,767 | 15,998,177 | 96 | 105 | 20m49s |


## All agents

Parent is the ledger parent (`main` = dispatched by the main thread, otherwise the parent agent id). `state` is the ledger state at write time.

| id | type | task | parent | state | input | output | cache creation | cache read | total | turns | tools | wall |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| a4afbd0b705a70625 | orchestrator | Optimize agent stack tokens | main | running | 212 | 131,714 | 409,475 | 15,346,758 | 15,888,159 | 80 | 92 | 6h43m |
| a9bca03300f4b9688 | claude-code-guide | T1 Desktop subagent label field | a4afbd0b705a70625 | finished | 8 | 2,031 | 31,212 | 92,500 | 125,751 | 4 | 5 | 0m30s |
| a62715d46b808a042 | planner | T2 design review/roster/turns | a4afbd0b705a70625 | finished | 70 | 102,805 | 234,239 | 4,251,893 | 4,589,007 | 35 | 71 | 16m17s |
| a1af9f3b83bd73e11 | claude-code-engineer | T3 hook label rewrite tests | a4afbd0b705a70625 | finished | 156 | 55,769 | 383,664 | 10,481,931 | 10,921,520 | 77 | 92 | 43m08s |
| aa557ca5c0a1d0ac7 | claude-code-engineer | T4 review protocol rewrite | a4afbd0b705a70625 | finished | 144 | 73,464 | 448,836 | 11,530,187 | 12,052,631 | 71 | 78 | 53m27s |
| ae6d4de5b111cd591 | claude-code-engineer | T5 draft proof-checker vfx-td | a4afbd0b705a70625 | finished | 170 | 64,082 | 386,730 | 13,042,885 | 13,493,867 | 84 | 86 | 38m45s |
| affd3a872cf8a22d8 | scout | Houdini MCP server lookup | ae6d4de5b111cd591 | finished | 10 | 1,488 | 27,722 | 99,256 | 128,476 | 5 | 7 | 0m31s |
| a8b5ace94c0276da1 | claude-code-engineer | T6 tighten agents budget script | a4afbd0b705a70625 | finished | 168 | 151,536 | 323,448 | 17,262,211 | 17,737,363 | 84 | 165 | 25m58s |
| aaecb17df15af8d05 | code-reviewer | T7 review hook label diff | a4afbd0b705a70625 | finished | 74 | 25,406 | 87,905 | 2,142,327 | 2,255,712 | 37 | 37 | 7m14s |
| afd0a600d153e15fb | verifier | T8 verify integrated stack tree | a4afbd0b705a70625 | finished | 38 | 7,882 | 51,394 | 682,509 | 741,823 | 19 | 21 | 5m13s |
| a9069fd12de7e3c21 | coder | Set uv default Python 3.14 | main | finished | 8 | 960 | 40,591 | 107,467 | 149,026 | 4 | 4 | 0m11s |
| a4268f246e7d0e24d | claude-code-guide | P1 listing scoping mechanisms | a4afbd0b705a70625 | finished | 6 | 2,036 | 34,932 | 54,830 | 91,804 | 3 | 3 | 0m29s |
| aae3c212b84c9801a | planner | P2 design roster skills MCP | a4afbd0b705a70625 | finished | 38 | 80,271 | 171,906 | 1,835,199 | 2,087,414 | 19 | 33 | 12m59s |
| a0df3b5a447aa409e | researcher | P3 vet MCP candidates | a4afbd0b705a70625 | finished | 104 | 55,239 | 185,002 | 6,193,901 | 6,434,246 | 52 | 65 | 11m32s |
| abf61455daf8bf39a | claude-code-engineer | P4 A1 budget tooling overrides | a4afbd0b705a70625 | finished | 570 | 237,918 | 818,753 | 49,526,629 | 50,583,870 | 283 | 301 | 1h39m |
| a739e537b64de1bce | claude-code-engineer | P5 S1 skills languages infra | a4afbd0b705a70625 | finished | 264 | 198,032 | 873,710 | 20,448,630 | 21,520,636 | 130 | 183 | 1h18m |
| ac736ac036119caf0 | claude-code-engineer | P6 S2 skills domains | a4afbd0b705a70625 | finished | 184 | 191,147 | 642,307 | 18,824,572 | 19,658,210 | 89 | 140 | 1h18m |
| aa3cecbac36d6c0d6 | claude-code-engineer | P7 S3 skills cross-cutting | a4afbd0b705a70625 | finished | 338 | 207,054 | 839,920 | 29,067,276 | 30,114,588 | 168 | 205 | 1h19m |
| af7dbf0f1217cc824 | scout | Verify security/supply-chain claims | aa3cecbac36d6c0d6 | finished | 10 | 5,436 | 58,547 | 143,512 | 207,505 | 5 | 24 | 0m54s |
| abaf8d30e02984a5a | scout | Verify testing-tool claims | aa3cecbac36d6c0d6 | finished | 14 | 6,956 | 38,495 | 180,311 | 225,776 | 7 | 34 | 1m06s |
| af5a45dd89f19c51e | scout | Verify db, mobile a11y, numerics claim | aa3cecbac36d6c0d6 | finished | 10 | 4,735 | 34,990 | 112,977 | 152,712 | 5 | 19 | 0m46s |
| a0a1a5d145fe6b44e | scout | Apple platform version facts | ac736ac036119caf0 | finished | 10 | 2,181 | 28,265 | 107,929 | 138,385 | 5 | 8 | 0m41s |
| a373939c99acf370d | scout | Android and cross-platform facts | ac736ac036119caf0 | finished | 8 | 2,347 | 29,038 | 78,053 | 109,446 | 4 | 10 | 0m29s |
| a303d44a79faef2a0 | scout | Game engine, GPU API, subtitle facts | ac736ac036119caf0 | finished | 8 | 2,240 | 29,260 | 76,674 | 108,182 | 4 | 9 | 0m30s |
| ab8150aaf68d5cc2c | scout | Wasm, WASI, audio SDK facts | ac736ac036119caf0 | finished | 8 | 2,088 | 30,130 | 74,118 | 106,344 | 4 | 9 | 0m30s |
| a39c9889197e401ae | scout | Verify GPU, perf, numerics versions | aa3cecbac36d6c0d6 | finished | 10 | 3,270 | 43,318 | 125,139 | 171,737 | 5 | 8 | 0m44s |
| a1bcba3ef72ee7ced | scout | Verify API, search, codemod tool facts | aa3cecbac36d6c0d6 | finished | 10 | 4,464 | 28,558 | 107,082 | 140,114 | 5 | 25 | 0m35s |
| a9d529fdb2383e6a8 | code-reviewer | P9a review hook settings install | a4afbd0b705a70625 | finished | 132 | 34,138 | 135,987 | 5,986,288 | 6,156,545 | 66 | 66 | 9m34s |
| ab11df1d20036d2cd | verifier | P9b verify phase-2 full tree | a4afbd0b705a70625 | finished | 84 | 21,555 | 94,310 | 2,580,772 | 2,696,721 | 42 | 45 | 7m45s |
| afce6a0baa56bc739 | claude-code-guide | P9c plugin skill on-demand mechanisms | a4afbd0b705a70625 | finished | 10 | 3,946 | 97,781 | 200,023 | 301,760 | 5 | 13 | 0m43s |
| abc12cd999d870919 | claude-code-engineer | P9d README rewrite install env | a4afbd0b705a70625 | finished | 130 | 56,496 | 226,112 | 10,062,804 | 10,345,542 | 65 | 68 | 11m30s |
| a9caca4564fd86d74 | claude-code-engineer | P10 write FINAL-REPORT phases 1-2 | a4afbd0b705a70625 | finished | 156 | 58,220 | 479,851 | 9,012,305 | 9,550,532 | 76 | 90 | 2h04m |
| ab9ab9bed862783b0 | claude-code-engineer | Q1 tighten all agent prompts | a4afbd0b705a70625 | finished | 124 | 85,654 | 229,921 | 10,103,563 | 10,419,262 | 62 | 62 | 17m34s |
| a0b43414e418a0784 | claude-code-engineer | Q2 tighten skills a-m | a4afbd0b705a70625 | finished | 158 | 76,216 | 237,248 | 11,648,040 | 11,961,662 | 79 | 79 | 13m32s |
| aa28ddfef1cbe8a53 | claude-code-engineer | Q3 tighten skills n-z rules | a4afbd0b705a70625 | finished | 256 | 100,399 | 279,941 | 23,160,455 | 23,541,051 | 127 | 127 | 30m50s |
| a66abc25551ca1e2a | claude-code-engineer | Q6 evaluate skill lookup designs | a4afbd0b705a70625 | finished | 270 | 134,768 | 570,991 | 25,672,386 | 26,378,415 | 133 | 140 | 55m00s |
| a203d188763a2072f | claude-code-guide | Verify skill listing mechanics | a66abc25551ca1e2a | finished | 18 | 4,723 | 47,454 | 250,844 | 303,039 | 8 | 11 | 3m38s |
| a15e2a987cb5fa1ed | claude-code-guide | Compaction facts lookup | a66abc25551ca1e2a | finished | 16 | 3,455 | 50,640 | 261,761 | 315,872 | 8 | 12 | 0m41s |
| af77a05d79750523a | verifier | Q5 verify phase-3 tree d2bc994 | a4afbd0b705a70625 | finished | 64 | 16,630 | 83,980 | 1,650,126 | 1,750,800 | 32 | 32 | 7m23s |
| ac215a9dfa703d3a7 | claude-code-engineer | Q7 Agent SDK integration | a4afbd0b705a70625 | finished | 200 | 90,279 | 706,258 | 15,946,167 | 16,742,904 | 98 | 109 | 42m47s |
| acdd7814286d93bf5 | claude-code-guide | Agent SDK doc facts | ac215a9dfa703d3a7 | finished | 22 | 9,875 | 148,504 | 500,989 | 659,390 | 11 | 21 | 1m56s |
| a05fd5ceb1f5e63d7 | code-reviewer | Q8 review SDK hook diff | a4afbd0b705a70625 | finished | 44 | 13,848 | 68,290 | 1,052,080 | 1,134,262 | 22 | 23 | 5m33s |
| a58fc76628606a55c | verifier | Q9 final verify before merge | a4afbd0b705a70625 | finished | 18 | 5,335 | 46,496 | 283,506 | 335,355 | 9 | 13 | 5m31s |
| aa1cdc5f97419bc71 | verifier | Set up before/after benchmark harness | main | running | 258 | 171,085 | 270,173 | 23,379,891 | 23,821,407 | 129 | 151 | 21m54s |
| a1950e4e0c6d060a5 | claude-code-engineer | Q10 contingency fix kit | a4afbd0b705a70625 | launching | 192 | 89,989 | 249,586 | 15,998,177 | 16,337,944 | 96 | 105 | 20m49s |
| af67f2b4202f3fe90 | coder | Token usage per agent report | main | running | 34 | 15,056 | 68,463 | 791,909 | 875,462 | 17 | 17 | 2m07s |
| main | BlackCat(main) | main thread | - | live | 252 | 73,102 | 173,680 | 14,635,013 | 14,882,047 | 126 | 40 | 7h03m |


## Comparison with hand-back `subagent_tokens`

16 of 46 subagents have at least one completion notice in the main transcript (finished runs resumed through SendMessage have several; background children whose notices go to the parent agent are not visible in the main transcript). Notices are deduplicated by (tokens, tool_uses, duration).

| id | type | notices | hand-back tokens (last notice) | last-turn context (in+out+cc+cr, transcript) | transcript total | total / hand-back | hand-back tool_uses (sum of notices) | transcript tool calls |
|---|---|---|---|---|---|---|---|---|
| ac736ac036119caf0 | claude-code-engineer | 3 | 348,230 | 348,150 | 19,658,210 | 56.5 | 58 | 140 |
| a4afbd0b705a70625 | orchestrator | 26 | 304,243 | 313,710 | 15,888,159 | 52.2 | 191 | 92 |
| a66abc25551ca1e2a | claude-code-engineer | 2 | 301,120 | 301,120 | 26,378,415 | 87.6 | 99 | 140 |
| aa28ddfef1cbe8a53 | claude-code-engineer | 1 | 288,605 | 287,798 | 23,541,051 | 81.6 | 27 | 127 |
| ac215a9dfa703d3a7 | claude-code-engineer | 2 | 251,891 | 251,361 | 16,742,904 | 66.5 | 15 | 109 |
| aa557ca5c0a1d0ac7 | claude-code-engineer | 1 | 236,596 | 235,846 | 12,052,631 | 50.9 | 9 | 78 |
| ae6d4de5b111cd591 | claude-code-engineer | 1 | 227,680 | 226,732 | 13,493,867 | 59.3 | 39 | 86 |
| abf61455daf8bf39a | claude-code-engineer | 3 | 222,211 | 221,045 | 50,583,870 | 227.6 | 238 | 301 |
| a1af9f3b83bd73e11 | claude-code-engineer | 1 | 205,476 | 204,805 | 10,921,520 | 53.2 | 11 | 92 |
| a9caca4564fd86d74 | claude-code-engineer | 2 | 187,750 | 187,261 | 9,550,532 | 50.9 | 43 | 90 |
| a739e537b64de1bce | claude-code-engineer | 3 | 184,909 | 184,351 | 21,520,636 | 116.4 | 94 | 183 |
| aa3cecbac36d6c0d6 | claude-code-engineer | 3 | 168,268 | 167,504 | 30,114,588 | 179.0 | 137 | 205 |
| acdd7814286d93bf5 | claude-code-guide | 1 | 156,660 | 156,660 | 659,390 | 4.2 | 21 | 21 |
| a203d188763a2072f | claude-code-guide | 1 | 48,790 | 48,213 | 303,039 | 6.2 | 4 | 11 |
| a9069fd12de7e3c21 | coder | 1 | 41,250 | 40,963 | 149,026 | 3.6 | 4 | 4 |
| affd3a872cf8a22d8 | scout | 1 | 28,635 | 28,552 | 128,476 | 4.5 | 7 | 7 |


Observation (empirical, from the columns above; the tool's own definition is unverified): hand-back `subagent_tokens` matches the size of the agent's last-turn context (in+out+cc+cr) within about 0.5% for every compared run, e.g. 348,230 vs 348,150. It is therefore a context-window size at the end of the segment, not cumulative usage; the transcript total (sum over all turns, with the cache re-read each turn) is 4x to 228x larger. Hand-back figures must not be summed to estimate session usage. Hand-back tool_uses are per segment (summed here); they differ from transcript tool calls for resumed agents because not every segment's notice is visible in the main transcript.


## Partial or unverified

- Still running or live when the ledger/transcripts were read, so their totals are partial and grow: orchestrator `a4afbd0b705a70625` (running, 15,888,159), verifier `aa1cdc5f97419bc71` (running, 23,821,407), coder `af67f2b4202f3fe90` (running, 875,462), claude-code-engineer `a1950e4e0c6d060a5` (launching, 16,337,944), BlackCat(main) `main` (live, 14,882,047).
- The main thread total is what was flushed to its transcript at read time; this report-producing run itself is one of the running coders.
- Q10 had no id in the ledger (state `launching`); it was matched to `a1950e4e0c6d060a5` via the unique `description` in that transcript's `.meta.json`.
- Rows with a missing usage field: 0. Transcripts missing for ledger entries: 0.
- Cost in currency and per-model pricing are not computed: model ids per turn were not aggregated, so any price figure would be a guess.
- Nested work done by a subagent through its own sub-agents is in those children's transcripts (counted once, under their own ids), not in the parent's.
- Workflow task ids (`bwo1r15re`, `bqmwphft0`) are not agents with transcripts here and are not included.
