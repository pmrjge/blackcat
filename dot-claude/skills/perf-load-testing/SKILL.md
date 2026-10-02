---
name: perf-load-testing
description: Use when measuring a service's latency or throughput under load — k6, vegeta, oha, percentiles.
---
# Load testing services
Hub: `cpu-performance` (workflow, environment block, report). Profiling the server while it is under load: `perf-profilers`, `perf-memory`.

## Ground rules
- Load-test only systems you own, on an environment meant for it (local, staging). Load against production, shared infrastructure or third-party APIs is the user's decision: name target, rate and duration, then wait.
- Write the objective first as a service-level target: "p99 < 200 ms and error rate < 0.1 % at 500 req/s for 10 min".
- One variable per run (code, config, instance size, rate). Record the environment of both the load generator and the system under test.

## Open vs closed models
- **Closed model** (N virtual users, each waits for its response before the next request): throughput drops when the server slows, which hides latency — the coordinated-omission problem.
- **Open model** (requests arrive at a fixed rate regardless of responses): matches real traffic from many independent clients; use it for latency targets. In k6 use an arrival-rate executor (`constant-arrival-rate`, `ramping-arrival-rate`); vegeta attacks at a fixed `-rate`.
- Report the rate that was *offered* and the rate that was *achieved*; if the generator could not keep up, the run is invalid.

## Tools
- **k6** (JavaScript scenarios, thresholds that fail the run): `k6 run script.js`; thresholds such as `http_req_duration: ['p(99)<200']`, `http_req_failed: ['rate<0.001']`.
- **vegeta** (constant-rate HTTP attacks): `echo "GET http://127.0.0.1:8080/x" | vegeta attack -rate=500/s -duration=60s | tee r.bin | vegeta report`; `vegeta report -type=hist[0,10ms,50ms,100ms,500ms]` and `vegeta plot`.
- **oha** (quick interactive runs, live TUI): `oha -z 30s -q 500 http://127.0.0.1:8080/x`.
- Exact flag spellings: check `--help` of the installed version (unverified as of 2026-10-02).

## Running a test
1. Smoke: a few requests to confirm correctness and that the generator reaches the target.
2. Ramp: increase the offered rate stepwise until a limit (latency target broken, errors, saturation); note the knee.
3. Soak: the target rate for long enough to expose leaks, GC pauses, connection or file-descriptor exhaustion (`perf-memory`).
4. Spike: sudden bursts to check queues, timeouts and recovery.
- Warm up caches and JITs, then measure; discard the warm-up window.
- Run the generator on a separate machine (or pinned cores) so it does not compete with the server; watch its own CPU.
- Monitor the server during the run: CPU, memory, GC, connection pools, database (`db-design` modules), and error logs.

## Reading results
- Latency is a distribution: report p50, p90, p99, p99.9 and max with the request count; never the mean alone. Histograms (HdrHistogram-style) over percentile-of-percentiles averaging.
- Errors and timeouts count against the result: a fast error is not a fast success.
- Throughput at the latency target is the number that matters, not peak throughput with unbounded latency.

## Verify
- [ ] Objective, workload mix, data set and rates written down; open model used for latency claims.
- [ ] Offered vs achieved rate reported; generator not saturated.
- [ ] Percentiles with counts and error rates for each step; server-side metrics captured for the same window.
- [ ] Result reproduced by a second run within the stated noise.

## Sources
- Verified 2026-10-02 https://api.github.com/repos/grafana/k6/releases/latest — k6 v2.3.0 (2026-09-21); https://api.github.com/repos/tsenart/vegeta/releases/latest — vegeta v12.13.0; https://api.github.com/repos/hatoo/oha/releases/latest — oha v1.16.0.
- Unverified as of 2026-10-02: k6 executor and threshold syntax, vegeta and oha flags (general knowledge — check the docs for the installed version).
