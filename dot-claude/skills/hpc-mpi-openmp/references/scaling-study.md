# Scaling studies

## Design
- Strong scaling: fixed total problem, increase resources (1, 2, 4, … nodes). Efficiency E(p) = T(p₀)·p₀ / (T(p)·p). Stop when E < ~0.5 or the per-rank problem is too small to be meaningful.
- Weak scaling: fixed problem per rank/GPU, increase both. Efficiency E(p) = T(p₀) / T(p).
- Baseline p₀: one full node (intra-node effects differ from inter-node); also report single-core time when claiming parallel speedup over serial.
- Time the solver region, not setup and I/O (report those separately); warm-up iteration excluded; ≥ 3 repeats per point with min/median and spread; same node type and exclusive nodes (`--exclusive`).
- Estimate the total core-hours of the study before submitting and get the user's consent (`hpc-computing`).

## Report
| nodes | ranks × threads | problem size | time (median, s) | spread | speedup | efficiency |
Include: hardware (CPU model, cores/node, memory, interconnect), compiler and MPI versions, binding, input, commit. Plot log-log time vs resources with the ideal line.

## When it doesn't scale
1. Profile at two scales (e.g. 1 and 16 nodes): which region grows? Tools: the MPI profiling interface via mpiP or Score-P + Cube/Vampir, TAU, HPCToolkit, Linaro/Arm MAP, Intel VTune/ITAC; `perf` per rank for compute.
2. Communication share rising → check message sizes and counts, use nonblocking overlap, aggregate small messages, topology-aware decomposition.
3. Load imbalance (max/mean compute time per rank > 1.1) → better partitioning (ParMETIS/Scotch, space-filling curves), dynamic balancing.
4. Serial fractions (Amdahl) → parallelize setup and I/O (`hpc-io`).
5. Memory bandwidth saturation within a node → fewer ranks per socket, cache blocking, data layout (SoA).
6. Collective-heavy solvers (dot products in Krylov methods) → pipelined/communication-avoiding variants, fewer global reductions.
