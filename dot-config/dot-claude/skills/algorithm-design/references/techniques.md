# Technique catalog (cue → technique → pitfalls)

Part of `algorithm-design`.

### 2.1 Greedy
Cue: sort-then-scan, earliest deadline/finish time, "take the best available" with no regret; exchange structure. Prove it (exchange argument or greedy-stays-ahead; for weighted independent sets greedy is optimal exactly on matroids). Classic traps: arbitrary coin systems, 0/1 knapsack by ratio (fractional knapsack is fine). Never ship a greedy that has not survived a brute-force comparison on thousands of random small instances.

### 2.2 Dynamic programming
Cue: optimal substructure over prefixes, intervals, subsets, trees, digits or DAG states; counting. The state is the minimal sufficient statistic of the past; cost = #states × transition cost; evaluate in any topological order of the dependency DAG (memoized recursion when reachable states are sparse); reconstruct with argmin pointers; roll layers to save memory (Hirschberg for linear-space LCS/edit-distance reconstruction). Optimizations:
- Sliding-window min/max transitions → monotone deque, O(n).
- dp[i] = min_j (a_j·x_i + b_j) → convex hull trick: deque O(n) when slopes and queries are monotone, Li Chao tree O(log C) per operation otherwise.
- Layered dp[k][i] = min_{j<i} dp[k−1][j] + C(j,i) with monotone argmin (holds when C satisfies the quadrangle inequality) → divide-and-conquer optimization, O(k·n log n).
- Interval dp[i][j] = min_k dp[i][k] + dp[k+1][j] + C(i,j) with opt[i][j−1] ≤ opt[i][j] ≤ opt[i+1][j] → Knuth, O(n^2).
- "Exactly k parts" with the optimum convex in k → Lagrangian relaxation ("aliens trick"): binary-search a per-part penalty, solve the unconstrained DP.
- Bitmask DP for ≤ 20–25 items; submasks of m by `s = m; while s: ...; s = (s - 1) & m` (then s = 0; all masks together O(3^n)); sum over subsets (zeta transform) O(n·2^n).
- Trees: post-order DP; rerooting gives the answer for every root in O(n).
- Linear recurrences: matrix power O(k^3 log n); Berlekamp–Massey recovers the recurrence from 2k terms modulo a prime.

### 2.3 Divide and conquer
Cue: independent halves with a combine cheaper than the naive solution; solve T(n) = aT(n/b) + f(n) with the master theorem. Examples: inversion counting by merge sort, closest pair O(n log n), offline CDQ divide and conquer for dominance/dynamic problems. Convolutions → FFT/NTT O(n log n); a floating FFT is exact only while rounding error stays below 0.5 (check the max rounding residue), otherwise use NTT modulo primes with CRT, or split coefficients.

### 2.4 Graphs
- Shortest paths: BFS (unit weights), 0-1 BFS with a deque, Dijkstra (non-negative weights; binary heap with lazy deletion, O((V+E) log V)), Bellman–Ford O(VE) (negative edges, detects negative cycles), relaxation in topological order for DAGs O(V+E), Floyd–Warshall O(V^3) dense all-pairs, Johnson (potentials + V Dijkstras) sparse all-pairs with negative edges, A* with an admissible (ideally consistent) heuristic. SPFA's worst case equals Bellman–Ford and is easy to trigger: do not rely on it.
- Many problems are shortest paths in a derived state graph (node, mask, time mod k, remaining budget): count the states first.
- MST: Kruskal (sort + union-find) O(E log E); Prim O(E log V), or the O(V^2) array version for dense graphs. The cut property proves both. The MST path between two nodes is a minimax (bottleneck) path.
- SCC (Tarjan/Kosaraju, O(V+E)) → condensation DAG. 2-SAT = SCC of the implication graph (x and ¬x in one SCC ⇒ unsatisfiable). Bridges and articulation points by low-link; Euler paths by Hierholzer; topological order by Kahn (also detects cycles; min-heap for the lexicographically smallest order).
- Matching: bipartite Hopcroft–Karp O(E√V); König: in bipartite graphs max matching = min vertex cover; assignment (min-cost perfect bipartite) Hungarian or Jonker–Volgenant O(n^3) (`scipy.optimize.linear_sum_assignment` implements JV); general graphs: Edmonds' blossom (`networkx.max_weight_matching`).
- Max-flow: Dinic O(V^2 E) in general, O(E·min(V^{2/3}, √E)) with unit capacities, O(E√V) on unit networks (bipartite matching); push-relabel for dense graphs. The min cut (vertices reachable from s in the residual graph) certifies optimality. Standard reductions: edge-disjoint paths; vertex-disjoint paths (split v into v_in → v_out with capacity 1); b-matching; maximum-weight closure / project selection (sum of positive weights − min cut); circulations with lower bounds (demand transformation); binary labeling with submodular pairwise costs; assignment with capacities and time windows.
- Min-cost flow: successive shortest paths with Johnson potentials (Dijkstra), O(F·E log V) for integral flow F; network simplex or cost scaling for large instances (OR-Tools `SimpleMinCostFlow`, `networkx.network_simplex`).
- Union-find: path compression + union by size → O(α(n)) amortized. Rollback DSU (union by size, no compression) for offline divide and conquer over time; weighted DSU for parity/offset constraints.

### 2.5 Ranges and data structures
- Static: prefix sums (also 2D), difference arrays, sparse table (O(1) idempotent range-min after O(n log n)).
- Dynamic: Fenwick tree (point update + prefix query; two trees for range add + range sum); segment tree for any associative combine, lazy propagation for range updates, "segment tree beats" for chmin/chmax; merge-sort or wavelet trees for order statistics in ranges.
- Offline: coordinate compression; sweep line + Fenwick for 2D dominance counting; Mo's algorithm O((n+q)√n) when add/remove are O(1).
- Heaps: lazy deletion (store a version, skip stale entries on pop) usually beats decrease-key; an indexed heap when true decrease-key is required.
- Ordered maps: B-trees/balanced BSTs (`BTreeMap`, `sortedcontainers.SortedList`); treap or order-statistics tree for rank queries.
- Tries: prefix counts; binary trie for maximum XOR pairs in O(n·bits). Persistent segment trees (path copying, O(log n) new nodes per update) for k-th smallest in a subarray and versioned queries. Monotonic stack for next-greater and largest-rectangle problems, O(n).

### 2.6 Strings
- Matching, periods, borders: KMP prefix function or Z-function, O(n+m); many patterns: Aho–Corasick; palindromes: Manacher O(n).
- Suffix array by SA-IS O(n) or prefix doubling O(n log n), Kasai LCP O(n), LCP + sparse table → LCP of any two suffixes in O(1). Suffix automaton: ≤ 2n−1 states and ≤ 3n−4 transitions (n ≥ 3); online; distinct substrings, occurrence counts, longest common substring.
- Rolling hashes: polynomial hash modulo p = 2^61−1 with a base drawn at runtime; for two distinct strings of length L, P[collision] ≤ (L−1)/p per comparison — union-bound over all comparisons. Never hash with natural 2^64 overflow (Thue–Morse strings collide for every odd base; an even base keeps only the last 64 characters) or with a fixed published base on adversarial input. When a false match is unacceptable, verify candidates directly or use two independent moduli.

### 2.7 Computational geometry
- Prefer integer coordinates and exact predicates. orient(a,b,c) = sign((b−a)×(c−a)); with |coordinates| ≤ 1e9 the cross product is ≤ 8e18 < 2^63 — it barely fits i64. Degree-4 predicates (in-circle) need i128 or big integers.
- With floats, use exact adaptive predicates (Shewchuk's orient2d/incircle, e.g. the `robust` crate) for combinatorial decisions. An epsilon inside a predicate gives inconsistent answers that crash hull and triangulation code; tolerances belong in reporting only.
- Workhorses: Andrew's monotone chain hull (decide whether collinear boundary points are kept), sweep lines, rotating calipers, half-plane intersection, shoelace area as twice-area integers, winding-number point-in-polygon with explicit boundary handling. Delaunay/Voronoi/higher-dimensional hulls: `scipy.spatial` (Qhull) rather than hand-rolled code.
- Test degeneracies: duplicates, collinear triples, vertical segments, zero-area polygons, touching vs crossing segments.

### 2.8 Randomized algorithms and hashing
- Las Vegas (always correct, random time): randomized quicksort/quickselect, treaps, randomized incremental geometry. Monte Carlo (bounded error): Miller–Rabin, Freivalds (checks A·B = C in O(n^2), error ≤ 1/2 per trial), Schwartz–Zippel identity testing, Karger min cut. k independent trials → error ≤ 2^−k.
- Deterministic Miller–Rabin for n < 2^64: bases {2, 325, 9375, 28178, 450775, 9780504, 1795265022}, with 128-bit mulmod.
- Adversarial keys: Python's integer hash is deterministic (`hash(n) == n` for small non-negative n) and common C++ standard libraries hash integers by identity, so crafted keys degrade hash tables — mix keys with a random 64-bit salt (splitmix64). Rust's default `HashMap` hasher is randomized SipHash-1-3 (DoS-resistant, slower); `rustc-hash`/`foldhash` are faster but only for trusted keys.
- Sketches when exact answers are not required: Bloom filter (false-positive rate ≈ (1 − e^{−kn/m})^k, best k = (m/n)·ln 2), count-min, HyperLogLog, reservoir sampling, MinHash/LSH. Log seeds; fix them in tests.

### 2.9 Approximation and heuristics
- Known guarantees: vertex cover 2 (maximal matching), set cover ≈ ln n by greedy (beating (1−ε)·ln n is NP-hard), metric TSP 1.5 (Christofides), knapsack FPTAS, LP relaxation + (randomized) rounding, primal–dual. General TSP admits no constant-factor approximation unless P = NP.
- No guarantee: local search (2-opt, Or-opt, swap/move neighborhoods), simulated annealing, tabu search, beam search, large-neighborhood search (destroy part of a solution, re-optimize it with CP-SAT), evolutionary methods. Always report the gap to a valid lower bound (LP relaxation, Lagrangian bound, solver best bound).
- Structural rescue: FPT algorithms in a small parameter, DP over tree decompositions for small treewidth, kernelization, meet-in-the-middle (n ≤ 40), branch and bound with a strong bound.
