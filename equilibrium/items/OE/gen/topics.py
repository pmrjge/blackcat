"""OE topics (authored 2026-10-04 by data-scientist). src = "baseline Pxx" marks a topic adapted from a graded prompt
of the agents-baseline campaign. Each topic yields three items: explain, compare, critique.
`facts` are hidden grader criteria: each states the correct fact and, in brackets, the error the critique passage makes.
"""

T = []


def tp(key, concept, audience, a, b, ctx, passage, facts, src="authored"):
    assert len(facts) >= 3
    T.append(dict(key=key, concept=concept, audience=audience, a=a, b=b, ctx=ctx, passage=passage, facts=facts,
                  src=src))


DEV = dict(
    key="recursion", src="authored", concept="what recursion is and how the call stack makes it work",
    audience="a beginner programmer", a="recursion", b="iteration with an explicit stack",
    ctx="for traversing a directory tree that may be 10,000 levels deep",
    passage="Recursion is always slower than loops and should be avoided. A recursive function without a base case "
            "simply returns zero. Python optimises tail calls automatically, so deep recursion is safe.",
    facts=["Recursion is a trade-off (clarity vs call overhead and stack depth), not always slower or to be avoided "
           "[passage: always slower].",
           "Without a base case recursion does not terminate: it exhausts the stack (RecursionError in Python) "
           "[passage: returns zero].",
           "CPython has no tail-call optimisation and a default recursion limit of about 1000 frames, so deep "
           "recursion fails [passage: optimises tail calls]."])

tp("l1-sparsity", "why L1 regularisation tends to give sparse solutions while L2 does not",
   "a second-year undergraduate who knows calculus and linear algebra", "L1 (lasso) regularisation",
   "L2 (ridge) regularisation", "for a linear regression with 500 features, many of them correlated",
   "L1 regularisation produces sparse models because the absolute value is not differentiable at zero, so gradient "
   "descent cannot move small weights and they stay at exactly zero. L2 regularisation pushes all weights towards "
   "zero at the same constant rate, which is why ridge regression also selects features when the penalty is large. "
   "With correlated features, lasso keeps all of them with equal weights.",
   ["Sparsity comes from the geometry of the L1 ball (corners on the axes) or, equivalently, the constant-magnitude "
    "penalty gradient that soft-thresholds small coefficients to exactly zero [passage: non-differentiability freezes "
    "weights].",
    "The L2 penalty's pull is proportional to the weight (2λw), so ridge shrinks but essentially never sets weights "
    "exactly to zero and does not select features [passage: constant rate, ridge selects].",
    "With correlated features lasso tends to keep one and drop the others somewhat arbitrarily; ridge (or elastic net) "
    "spreads weight across them [passage: lasso keeps all equally]."], src="baseline P04")
tp("noether", "what Noether's theorem says and why symmetries give conservation laws",
   "a first-year physics student who knows Newtonian mechanics and has just met the Lagrangian",
   "the Lagrangian (Noether) view of conservation laws", "the Newtonian view based on forces and the third law",
   "for explaining why momentum and energy are conserved",
   "Noether's theorem says that every symmetry of the equations of motion gives a conserved quantity. Symmetry under "
   "shifts in time gives conservation of momentum, and symmetry under shifts in space gives conservation of energy. "
   "The theorem applies to any physical system, including systems with friction.",
   ["The theorem concerns continuous symmetries of the action (the Lagrangian up to a total time derivative); "
    "discrete symmetries do not yield conserved quantities this way [passage: any symmetry of the equations].",
    "Time-translation symmetry gives energy conservation and space-translation symmetry gives momentum conservation "
    "[passage: swapped].",
    "Dissipative systems with friction have no standard time-independent Lagrangian, and their mechanical energy is "
    "not conserved [passage: applies with friction]."], src="baseline P05")
tp("induction", "how proof by induction works and what makes an induction step valid",
   "a first-year computer science student", "ordinary (weak) induction", "strong induction",
   "for proving properties of recursive algorithms",
   "Claim: 2^n > n^2 for all n >= 1. Base case: n = 1 gives 2 > 1. Step: assume 2^k > k^2; then 2^(k+1) = 2*2^k > "
   "2k^2 >= (k+1)^2. Hence the claim holds for all n >= 1.",
   ["The claim is false for n = 2, 3, 4 (4 = 4, 8 < 9, 16 = 16) [passage: holds for all n >= 1].",
    "The inequality 2k^2 >= (k+1)^2 holds only for k >= 3 (k >= 1 + sqrt 2); it fails for k = 1, 2, so the step "
    "does not chain from the base case [passage: step valid for all k].",
    "The true statement is 2^n > n^2 for n = 1 and all n >= 5; a correct proof uses base case n = 5 [passage: base "
    "case n = 1 suffices]."], src="baseline P10")
tp("redos", "why some regular expressions take exponential time on certain inputs (catastrophic backtracking)",
   "a web developer who writes regular expressions but has not studied automata",
   "backtracking regex engines such as Python's re or PCRE", "automaton-based engines such as RE2 or Rust's regex",
   "for validating untrusted user input on a server",
   "The regex ^(\\w+\\s?)*$ is safe because it only contains simple character classes; ReDoS only happens with "
   "lookaheads or backreferences. A timeout is unnecessary if the input is limited to 10,000 characters. Switching "
   "to an engine like RE2 fixes the problem without changing behaviour for any regex.",
   ["Nested quantifiers whose alternatives overlap, as in (\\w+\\s?)*, cause exponential backtracking on a "
    "non-matching input even without lookarounds [passage: safe].",
    "Exponential blow-up makes inputs of a few dozen characters hang, so a 10,000-character limit gives no "
    "protection [passage: limit makes timeout unnecessary].",
    "RE2-style engines guarantee linear time but do not support backreferences or lookarounds, so not every regex "
    "ports unchanged [passage: no behaviour change for any regex]."], src="baseline P07")
tp("benchmarking", "how to benchmark a short piece of code reliably", "a Python developer who has only used "
   "time.time() around a loop", "timeit", "pyperf", "for comparing two ways of concatenating 100,000 strings",
   "To compare two implementations, run each once with time.time() and report the faster one; computers are "
   "deterministic, so one run is enough. To be thorough, average 10 runs: the mean is the best statistic because "
   "outliers cancel out. A 3% difference is always meaningful if you can reproduce it on your laptop.",
   ["Single timings are noisy (timer resolution, scheduling, caches, frequency scaling): use a monotonic "
    "high-resolution clock, warm-up and many repeats [passage: one run is enough].",
    "Timing noise is one-sided (interference only adds time), so the minimum or median with a spread is more robust "
    "than the mean [passage: mean, outliers cancel].",
    "A 3% gap can be within run-to-run and machine variance; it needs an interval or repeated processes before it "
    "counts [passage: always meaningful]."], src="baseline P16")
tp("repetition-code", "how a repetition code protects a qubit against bit-flip errors and why its logical error "
   "rate scales like p^2 at distance 3", "a software engineer new to quantum computing", "majority-vote decoding",
   "minimum-weight perfect matching decoding", "for a distance-3 repetition code over several noisy measurement "
   "rounds",
   "A distance-3 repetition code corrects any number of bit-flip errors as long as they hit different qubits. Its "
   "logical error rate is about 3p for physical error rate p, so it only helps when p is above 1/3. Because it "
   "encodes one logical qubit in three physical ones, it also protects against phase flips.",
   ["Distance 3 corrects exactly one bit flip; two flips cause a logical error [passage: any number].",
    "The logical error rate is about 3p^2 (two of three qubits flip), so the code helps for small p, below p = 1/2 "
    "for the ideal code [passage: 3p, helps above 1/3].",
    "The bit-flip repetition code gives no protection against phase flips; a phase flip on any qubit flips the "
    "logical phase [passage: protects against phase flips]."], src="baseline P27")
tp("twfe", "why two-way fixed-effects regression can be biased when units adopt a treatment at different times",
   "an applied economist who knows OLS and two-period difference-in-differences", "two-way fixed effects",
   "Callaway and Sant'Anna group-time estimators", "for a panel where regions adopt a policy in different years and "
   "effects grow over time",
   "Two-way fixed effects is unbiased for the average treatment effect whenever parallel trends hold, regardless of "
   "when units are treated. Problems arise only when the treatment effect is constant over time. Negative weights "
   "cannot occur in a regression with a binary treatment indicator.",
   ["With staggered adoption and heterogeneous effects, TWFE uses already-treated units as controls and is biased "
    "even under parallel trends [passage: unbiased regardless of timing].",
    "The problem arises when effects vary over time or across cohorts; with constant effects TWFE is fine [passage: "
    "only when constant].",
    "TWFE can put negative weights on some group-time effects (Goodman-Bacon; de Chaisemartin and D'Haultfoeuille) "
    "[passage: cannot occur]."], src="baseline P49")
tp("kv-cache", "how much memory a transformer's key-value cache needs and which model choices change it",
   "an ML engineer deploying language models locally", "grouped-query attention", "multi-head attention",
   "for serving a 70B-parameter model with a 32k-token context on one machine",
   "The KV cache size is 2 x layers x hidden size x context length bytes, so it does not depend on the attention "
   "heads. With grouped-query attention the cache is the same size, only computation is faster. Quantising the "
   "weights to 4 bits also shrinks the KV cache by four times.",
   ["KV cache = 2 x layers x KV heads x head dimension x tokens x bytes per element (x batch) [passage: hidden "
    "size, no bytes per element].",
    "Grouped-query attention shrinks the cache by the ratio of query heads to KV heads (e.g. 8x for 64 vs 8) "
    "[passage: same size].",
    "Weight quantisation does not change the KV cache; cache quantisation is a separate setting [passage: 4x "
    "smaller]."], src="baseline P84")
tp("p-values", "what a p-value is and what it is not", "a product manager who reads A/B test reports",
   "p-values with a fixed 0.05 threshold", "confidence intervals for the effect size",
   "for deciding whether to ship a product change",
   "A p-value of 0.03 means there is a 3% chance that the null hypothesis is true. If p is above 0.05, the test has "
   "shown that the change has no effect. Checking the p-value every day and stopping as soon as it drops below 0.05 "
   "is fine, because the threshold stays the same.",
   ["A p-value is the probability, under the null hypothesis, of data at least as extreme as observed; it is not "
    "the probability that the null is true [passage: 3% chance null true].",
    "p > 0.05 is absence of evidence, not evidence of no effect; the test may be underpowered [passage: shows no "
    "effect].",
    "Peeking and stopping at the first p < 0.05 inflates the false-positive rate well above 5%; sequential designs "
    "are needed [passage: fine]."])
tp("simpson", "Simpson's paradox", "a journalist covering medical studies", "a pooled comparison",
   "a comparison stratified by patient risk", "for comparing two hospitals' surgery success rates",
   "Simpson's paradox shows that statistics can prove anything. When pooled and stratified results disagree, the "
   "pooled result is right because it uses more data. The paradox only happens with small samples.",
   ["The paradox arises when a third variable (e.g. case mix) is distributed differently between groups; it is "
    "explained by composition, not arbitrariness [passage: can prove anything].",
    "Which comparison is right depends on the causal role of the stratifier: for a confounder such as case "
    "severity, the stratified comparison is the relevant one [passage: pooled is right].",
    "It occurs at any sample size, because it is about weights, not noise [passage: small samples only]."])
tp("bias-variance", "the bias-variance trade-off", "a data analyst starting with machine learning",
   "a high-capacity model with strong regularisation", "a low-capacity model without regularisation",
   "for a tabular dataset with 5,000 rows and 40 features",
   "Bias is the error on the training set and variance is the error on the test set. Adding more training data "
   "reduces bias. Deep neural networks always have high variance, so they should never be used on small datasets.",
   ["Bias and variance describe the estimator across possible training sets (systematic error vs sensitivity to "
    "the sample), not training and test error [passage: definitions].",
    "More data mainly reduces variance; bias is a property of the model class [passage: reduces bias].",
    "Large models can generalise well with regularisation, augmentation or pre-training (and show double descent); "
    "'never' is wrong [passage: never use]."])
tp("cv-leakage", "data leakage in cross-validation", "a junior data scientist", "k-fold cross-validation",
   "a single train, validation and test split", "for a dataset of 3,000 patients with several visits each",
   "Standardising features on the whole dataset before cross-validation is fine because scaling does not use the "
   "labels. With repeated visits per patient, ordinary k-fold is correct because the rows are shuffled. The CV score "
   "of the best of 200 hyper-parameter settings is an unbiased estimate of the final model's accuracy.",
   ["Any preprocessing fitted on all rows leaks test-fold information; fit it inside each fold (a pipeline) "
    "[passage: fine without labels].",
    "Visits of one patient are correlated, so folds must be grouped by patient (GroupKFold) [passage: ordinary "
    "k-fold correct].",
    "The best of many configurations is optimistically biased; use nested CV or an untouched test set [passage: "
    "unbiased]."], src="baseline P46")
tp("calibration", "probability calibration of a classifier", "a software engineer integrating a fraud model",
   "Platt scaling", "isotonic regression",
   "for a model whose scores feed an expected-cost decision rule",
   "A classifier with 95% accuracy is well calibrated. AUC measures calibration: a model with an AUC of 0.9 gives "
   "probabilities that are right 90% of the time. Isotonic regression is always better than Platt scaling because "
   "it is non-parametric.",
   ["Accuracy says nothing about whether predicted probabilities match observed frequencies [passage: 95% accuracy "
    "implies calibration].",
    "AUC depends only on ranking and is unchanged by any monotone transform of the scores, so it cannot measure "
    "calibration [passage: AUC measures calibration].",
    "Isotonic regression overfits small calibration sets; Platt scaling is often better with little data [passage: "
    "always better]."])
tp("big-o", "what Big-O notation does and does not tell you", "a self-taught programmer preparing for interviews",
   "a hash table", "a balanced binary search tree", "for an in-memory index of 10 million keys that also needs range "
   "queries",
   "An O(n log n) algorithm is always faster than an O(n^2) one. Big-O describes the average running time. Hash "
   "table lookups are O(1), so they beat every other data structure in every case.",
   ["Big-O is asymptotic: constants and small n can make the O(n^2) algorithm faster [passage: always faster].",
    "Big-O is an upper bound that can describe worst, average or best case; it is not inherently the average "
    "[passage: average].",
    "Hash lookups are O(1) expected but O(n) worst case, and hash tables do not support ordered or range queries "
    "[passage: beats everything]."])
tp("cap", "the CAP theorem", "a backend developer designing a replicated service",
   "a leader-based, strongly consistent store", "a leaderless, eventually consistent store",
   "for a shopping-cart service across three regions",
   "CAP says a distributed database can have only two of consistency, availability and partition tolerance, so you "
   "pick the two you want. A CA system is the best choice for most applications. Consistency in CAP means the same "
   "as the C in ACID.",
   ["Partitions cannot be opted out of in a networked system; the real choice is between consistency and "
    "availability during a partition [passage: pick any two].",
    "A 'CA' distributed system is not a meaningful option across a network [passage: CA best].",
    "CAP consistency means linearisability; ACID consistency means preserving integrity constraints [passage: same "
    "C]."])
tp("idempotency", "idempotency in HTTP APIs and why retries need it", "a mobile developer calling a payments API",
   "idempotency keys", "relying on HTTP method semantics alone", "for a POST request that charges a card",
   "GET, PUT and POST are idempotent by definition, so retrying any of them is safe. An idempotent request always "
   "returns the same response. Idempotency keys are only needed when the network is unreliable, which is rare in "
   "data centres.",
   ["POST is not idempotent; GET, PUT and DELETE are by specification [passage: POST idempotent].",
    "Idempotent means repeated requests have the same effect on server state; the responses may differ (e.g. a "
    "second DELETE returns 404) [passage: same response].",
    "Timeouts and retries are routine, and a client cannot know whether a timed-out request was applied [passage: "
    "rare]."])
tp("floating-point", "why 0.1 + 0.2 is not exactly 0.3 in binary floating point", "a beginner programmer",
   "binary floating point (IEEE 754 doubles)", "decimal arithmetic", "for storing and summing money amounts",
   "0.1 + 0.2 != 0.3 because computers make rounding errors when they add. Using double instead of single precision "
   "fixes the problem. Comparing floats with == is fine as long as both values are mathematically equal.",
   ["0.1 and 0.2 have no exact binary representation, so the error exists before the addition (which rounds "
    "again) [passage: errors when adding].",
    "Double precision reduces the error but cannot represent 0.1 exactly either [passage: fixes it].",
    "Mathematically equal expressions can round differently; compare with a tolerance, or use decimal or integer "
    "cents for money [passage: == fine]."])
tp("utf8", "how UTF-8 encodes text and why 'string length' is ambiguous",
   "a developer who assumes one character is one byte", "UTF-8", "UTF-16",
   "for storing multilingual user names", "UTF-8 uses one byte per character for Latin scripts and two bytes for "
   "every other script. The length of a Python string is its number of bytes. Emoji count as one character in every "
   "programming language.",
   ["UTF-8 uses 1 to 4 bytes per code point: ASCII 1, accented Latin, Greek or Cyrillic 2, most CJK 3, emoji 4 "
    "[passage: two bytes for every other script].",
    "Python's len counts code points, not bytes [passage: bytes].",
    "Many emoji are several code points (modifiers, ZWJ sequences), and JavaScript counts UTF-16 code units, so "
    "lengths differ by language [passage: always one]."])
tp("rebase", "what git rebase does compared with merge", "a developer who has only used git merge", "rebase",
   "merge", "for integrating feature branches into main in a team of eight",
   "Rebase moves your commits to the top of the target branch without changing them, so their hashes stay the same. "
   "Rebasing a branch others have pulled is safe because git detects the duplicates. Merge commits make history "
   "incorrect and should always be avoided.",
   ["Rebase creates new commits with new hashes [passage: hashes unchanged].",
    "Rebasing a shared branch rewrites history others built on, causing duplicate commits and conflicts for them "
    "[passage: safe].",
    "Merge commits record what actually happened; avoiding them is a team policy choice, not a correctness issue "
    "[passage: incorrect]."])
tp("tls", "what a TLS certificate proves and what it does not", "a small-business owner setting up a website",
   "domain-validated certificates", "organisation-validated certificates", "for an online shop",
   "The padlock means the website is safe and trustworthy. The certificate encrypts the data with its private key, "
   "which the browser also receives. A self-signed certificate gives the same protection as one from a public "
   "certificate authority.",
   ["The padlock means an encrypted connection to a server that controls that domain name; it says nothing about "
    "the business's honesty [passage: trustworthy].",
    "The private key never leaves the server; the certificate carries the public key, and session keys come from a "
    "key exchange [passage: browser receives the private key].",
    "A self-signed certificate is not vouched for by a trusted third party, so an attacker in the middle cannot be "
    "detected unless the certificate is pinned or trusted out of band [passage: same protection]."])
tp("password-hashing", "why passwords are stored with slow, salted hashes", "a junior backend developer",
   "argon2id", "bcrypt", "for a web app with 200,000 users",
   "SHA-256 is a good choice for passwords because it is a secure cryptographic hash. Salts must be kept secret, "
   "otherwise they are useless. Encrypting passwords with AES is better than hashing because you can recover them "
   "when needed.",
   ["Fast hashes allow billions of guesses per second; passwords need a slow, memory-hard function such as argon2id "
    "or bcrypt [passage: SHA-256 good].",
    "Salts need not be secret; they defeat precomputed tables and stop equal passwords hashing alike [passage: "
    "secret].",
    "Reversible encryption is worse: one key leak exposes every password [passage: AES better]."],
   src="baseline P70")
tp("btree-index", "how a B-tree index speeds up queries and when it does not", "an analyst who writes SQL",
   "a composite index on (customer_id, created_at)", "two separate indexes on customer_id and created_at",
   "for a query that filters by customer and sorts by date",
   "Indexes always make queries faster, so you should index every column. A composite index on (a, b) serves a query "
   "that filters only on b just as well. Indexes cost nothing apart from disk space.",
   ["For low-selectivity predicates or small tables a sequential scan can be faster, and the planner may ignore an "
    "index [passage: always faster].",
    "A composite index is ordered by its leading column, so a filter on b alone cannot use (a, b) efficiently "
    "(skip scans aside) [passage: just as well].",
    "Every index slows writes and uses memory and maintenance time [passage: only disk space]."], src="baseline P51")
tp("isolation", "transaction isolation levels and the anomalies they allow",
   "a developer who thinks transactions make everything safe", "READ COMMITTED", "SERIALIZABLE",
   "for a booking system that must never double-book",
   "Inside a transaction nothing else can change the data you read, so check-then-insert is always safe. All "
   "databases default to SERIALIZABLE. Snapshot isolation prevents all anomalies.",
   ["What others can change depends on the isolation level; under READ COMMITTED a concurrent transaction can "
    "insert between the check and the insert [passage: always safe].",
    "Common defaults are READ COMMITTED (PostgreSQL, Oracle, SQL Server) or REPEATABLE READ (MySQL InnoDB) "
    "[passage: SERIALIZABLE default].",
    "Snapshot isolation still allows write skew [passage: prevents all anomalies]."])
tp("cache-invalidation", "cache invalidation strategies", "a developer adding a cache to a slow service",
   "time-to-live expiry", "explicit invalidation on every write", "for product prices shown in an online shop",
   "Adding a cache can only make a system faster. With a TTL cache, users never see stale data. A 50% hit rate "
   "halves both the database load and every user's latency.",
   ["A cache adds failure modes: stampedes on expiry, cold starts, stale reads and memory pressure [passage: can only "
    "help].",
    "A TTL bounds staleness to the TTL; it does not remove it [passage: never stale].",
    "A 50% hit rate roughly halves database reads, but only hits get faster: misses keep their latency and tail "
    "latency may not improve [passage: halves every latency]."])
tp("backpressure", "backpressure in streaming systems", "a developer building a log pipeline",
   "dropping or sampling messages under load", "blocking producers (backpressure)",
   "for a pipeline from 2,000 servers into a search index",
   "If a consumer is slower than the producer, an unbounded queue between them solves the problem. Backpressure "
   "means the consumer works harder when the queue grows. Dropping messages is never acceptable.",
   ["An unbounded queue only postpones the problem: memory and latency grow without limit [passage: solves it].",
    "Backpressure means signalling upstream so producers slow down or stop [passage: consumer works harder].",
    "Dropping or sampling with accounting is often acceptable for logs and metrics [passage: never acceptable]."])
tp("consistent-hashing", "consistent hashing", "a developer sharding a cache across servers",
   "consistent hashing with virtual nodes", "modulo hashing (hash mod N)", "for a cache cluster growing from 10 to "
   "12 nodes",
   "With hash(key) mod N, adding a server moves only the keys that belong to the new server. Consistent hashing "
   "guarantees that every node gets exactly the same number of keys. Virtual nodes are only needed for fault "
   "tolerance.",
   ["With mod N, changing N remaps most keys (from 10 to 12 nodes, about 5 in 6 move) [passage: only the new "
    "server's keys].",
    "Consistent hashing balances only in expectation; without virtual nodes the load can be quite uneven [passage: "
    "exactly equal].",
    "Virtual nodes mainly even out load and spread a departed node's keys across many nodes [passage: only fault "
    "tolerance]."])
tp("quorum", "why distributed consensus needs a majority quorum", "a backend developer running a 3-node etcd cluster",
   "a 3-node cluster", "a 4-node cluster", "for a configuration store that must survive one node failure",
   "A 4-node cluster tolerates more failures than a 3-node cluster because it has more nodes. Quorums need a "
   "majority so that the cluster is faster. When the leader fails, the follower with the most recent timestamp "
   "automatically becomes leader.",
   ["A 4-node cluster needs 3 for a majority and so tolerates one failure, like a 3-node cluster [passage: more "
    "failures].",
    "Majorities guarantee that any two quorums intersect, which is what makes decisions safe; it is not about speed "
    "[passage: faster].",
    "Raft elects a leader by vote, and votes go only to candidates whose log is at least as up to date (term, index); "
    "clocks play no part [passage: timestamp]."])
tp("learning-rate", "how the learning rate affects gradient descent", "a student training a first neural network",
   "a constant learning rate", "linear warm-up followed by cosine decay", "for training a small transformer from "
   "scratch",
   "A larger learning rate always trains faster. If the loss becomes NaN, the learning rate is too small. Adam needs "
   "no learning rate because it adapts it automatically.",
   ["Too large a learning rate oscillates or diverges [passage: always faster].",
    "NaN losses usually come from too large a rate or numerical overflow, not too small a rate [passage: too small].",
    "Adam rescales per parameter but still needs a global learning rate, and it matters [passage: none needed]."])
tp("batchnorm", "what batch normalisation does during training and inference", "a deep-learning practitioner",
   "batch normalisation", "layer normalisation", "for a transformer language model",
   "BatchNorm normalises each sample with its own mean and variance. At inference it uses the statistics of the "
   "current batch, so outputs depend on the batch. It works equally well with batch size 1.",
   ["BatchNorm normalises each feature across the batch; per-sample normalisation is LayerNorm [passage: each "
    "sample].",
    "At inference BatchNorm uses running averages collected in training [passage: current batch].",
    "With batch size 1 the batch statistics degenerate; LayerNorm avoids this, which is why transformers use it "
    "[passage: works with size 1]."])
tp("contamination", "benchmark contamination in language-model evaluation",
   "a team lead choosing a model from leaderboard scores", "public static benchmarks",
   "a private held-out evaluation set", "for choosing a model for internal document extraction",
   "If a model scores 90% on a public benchmark, it will score about 90% on our internal task of the same type. "
   "Contamination is impossible if the benchmark was released after the model's training cut-off. Averaging over "
   "many benchmarks removes contamination effects.",
   ["Benchmark scores do not transfer one to one to a different distribution and task format [passage: 90% "
    "transfers].",
    "Items often predate a benchmark's release (reused sources), and cut-off claims are imprecise, so release dates "
    "do not settle contamination [passage: impossible].",
    "Averaging does not remove a systematic bias shared by many benchmarks [passage: averaging removes it]."])
tp("cosine", "what cosine similarity between text embeddings measures", "a developer building semantic search",
   "cosine similarity", "the raw dot product", "for ranking passages with an embedding model",
   "A cosine similarity of 0.8 means the texts are 80% the same. Cosine similarity and dot product always give the "
   "same ranking. Embeddings from two different models can be compared directly.",
   ["Cosine is the cosine of the angle between vectors; its scale is model-specific and not a percentage of shared "
    "content [passage: 80% the same].",
    "The rankings agree only when vectors are normalised to equal length [passage: always the same].",
    "Different models' embedding spaces are not aligned, so cross-model similarities are meaningless [passage: "
    "comparable]."], src="baseline P55")
tp("tokenisation", "how subword tokenisation works in language models", "a linguist curious about LLMs",
   "byte-pair encoding", "character-level tokenisation", "for a model that must handle European Portuguese and code",
   "A token is a word. Models see the letters of every word, so they can always count characters correctly. Every "
   "language needs about the same number of tokens for the same content.",
   ["Tokens are subword pieces (often word fragments, sometimes several words or bytes) [passage: a word].",
    "The model receives token ids, not letters, which is why character counting is unreliable [passage: sees "
    "letters].",
    "Tokeniser efficiency varies widely: languages under-represented in the tokeniser's training data need more "
    "tokens for the same content [passage: same count]."])
tp("attention", "self-attention in transformers", "a software engineer with basic linear algebra",
   "full self-attention", "sliding-window attention", "for documents of 100,000 tokens",
   "Self-attention's cost grows linearly with sequence length. Attention weights show which words the model thinks "
   "are important, so they explain its predictions. Positional information is unnecessary because attention "
   "already knows word order.",
   ["Naive self-attention costs time and memory quadratic in sequence length [passage: linear].",
    "Attention weights are not a reliable explanation of predictions [passage: they explain].",
    "Attention is permutation-equivariant, so positional encodings are needed to represent order [passage: knows "
    "order]."])
tp("diffusion", "how diffusion models generate images", "a graphic designer who uses image generators",
   "diffusion models", "generative adversarial networks", "for generating brand illustrations in a consistent style",
   "Diffusion models search a database of training images and blend the closest matches. Each denoising step adds "
   "detail by copying patches from training images. More sampling steps always give a better image.",
   ["A diffusion model learns to denoise; it generates by iteratively denoising random noise, with no database "
    "lookup (memorisation can still happen) [passage: searches a database].",
    "There is no patch-copying mechanism in the sampling steps [passage: copies patches].",
    "Quality saturates with steps and depends on the sampler; more steps are not always better [passage: always "
    "better]."])
tp("colour-spaces", "the difference between sRGB, Display P3 and CMYK", "a junior graphic designer",
   "designing in sRGB", "designing in Display P3", "for a brand palette used on the web, on phones and in print",
   "CMYK has more colours than RGB, which is why print looks more vivid. Converting a design from RGB to CMYK is "
   "lossless if you use a good profile. Display P3 is just sRGB with higher brightness.",
   ["Typical CMYK print gamuts are smaller than RGB display gamuts, especially for saturated blues and greens "
    "[passage: more colours].",
    "Out-of-gamut colours are clipped or compressed when converting, so the conversion is lossy [passage: "
    "lossless].",
    "Display P3 has wider primaries than sRGB with the same D65 white point and transfer curve; it is not about "
    "brightness [passage: brighter sRGB]."])
tp("typography-spacing", "the difference between kerning, tracking and leading", "a developer styling a website",
   "a variable font", "several static font files", "for a website that needs four weights and italics",
   "Kerning and tracking are the same thing: both change the space between all letters. Leading is the space "
   "between paragraphs. Line height should always be 1.0 so that text is compact and easy to read.",
   ["Kerning adjusts specific letter pairs; tracking changes spacing uniformly across a run of text [passage: same "
    "thing].",
    "Leading is the distance between lines (baseline to baseline), not between paragraphs [passage: paragraphs].",
    "Body text usually reads best at a line height around 1.4 to 1.6; 1.0 crowds lines [passage: 1.0]."])
tp("contrast", "colour-contrast requirements for accessible text", "a visual designer", "the WCAG 2 contrast ratio",
   "the APCA contrast method", "for a dark-mode interface",
   "WCAG requires a contrast ratio of 3:1 for all body text. Contrast is the same as difference in hue, so red text "
   "on green is fine for everyone. If text passes contrast in light mode, it also passes in dark mode.",
   ["WCAG 2 AA needs 4.5:1 for normal text and 3:1 for large text and UI components [passage: 3:1 for body].",
    "Contrast is computed from relative luminance, not hue; red on green can fail and is hard for people with "
    "colour-vision deficiency [passage: hue].",
    "Dark mode uses different colour pairs, which must be checked separately [passage: carries over]."])
tp("halftone", "how halftone screening reproduces tones in print", "a designer preparing a screen print",
   "halftone screening", "solid spot colours", "for a three-colour T-shirt print",
   "Higher LPI is always better for screen printing because it gives more detail. A halftone makes grey by printing "
   "a lighter ink. All halftone colours should use the same screen angle so they stay aligned.",
   ["Screen printing uses low line screens (roughly 35 to 65 LPI) because mesh and ink cannot hold fine dots "
    "[passage: higher always better].",
    "A halftone varies dot size or coverage of the same ink to simulate tones [passage: lighter ink].",
    "Identical screen angles produce moire between colours; angles are offset [passage: same angle]."],
   src="baseline P61")
tp("subtitles", "subtitle reading-speed and line-length conventions", "a translator new to subtitling",
   "condensing the translation", "splitting the dialogue into more subtitles", "for fast dialogue in an action film",
   "Subtitles should translate every word of the dialogue, because viewers want the full text. A reading speed of "
   "25 characters per second is comfortable for most viewers. Line breaks can go anywhere as long as lines stay under "
   "42 characters.",
   ["Condensing is standard practice because viewers must read and watch at once [passage: every word].",
    "Common maxima are about 15 to 20 characters per second; 25 is too fast for most viewers [passage: 25 "
    "comfortable].",
    "Lines should break at linguistic units (not between article and noun) and be balanced [passage: anywhere]."],
   src="baseline P14")
tp("littles-law", "Little's law and what it says about latency and throughput", "an SRE sizing a service",
   "adding more workers", "reducing the service time per request", "for a service whose p99 latency explodes at 80% "
   "utilisation",
   "Little's law says latency equals throughput times the number of requests in the system. Latency grows linearly "
   "with utilisation, so 90% utilisation is only slightly worse than 80%. Doubling the number of servers halves "
   "latency at any load.",
   ["Little's law is L = lambda x W, so latency W = L / lambda [passage: latency = throughput x number].",
    "Queueing delay grows like 1/(1 - utilisation): in an M/M/1 queue the waiting time doubles from 80% to 90% "
    "[passage: linear].",
    "At low load latency is dominated by service time, which more servers do not shorten [passage: halves at any "
    "load]."])
tp("tail-latency", "why tail latency matters in fan-out services", "a backend engineer", "hedged requests",
   "tighter timeouts", "for a service that fans out each request to 100 shards",
   "If each shard has a p99 of 10 ms, the whole request has a p99 of 10 ms as well. Average latency is the best "
   "measure of user experience. Retrying slow requests can never make things worse.",
   ["With 100 shards, 1 - 0.99^100 = 63% of requests wait for at least one shard slower than its p99 [passage: "
    "p99 unchanged].",
    "Averages hide the tail that users of fan-out requests actually feel [passage: average best].",
    "Retries add load and can cause retry storms; they need budgets or hedging limits [passage: never worse]."])
tp("rust-ownership", "how Rust's ownership and borrowing prevent memory errors", "a C++ programmer",
   "Rust's borrow checker", "C++ smart pointers", "for a multithreaded network server",
   "Rust prevents all bugs at compile time, including logic errors and deadlocks. The borrow checker works by adding "
   "a garbage collector at run time. Writing unsafe switches off all of Rust's checks in the whole program.",
   ["Safe Rust rules out memory-safety errors and data races, not logic errors or deadlocks [passage: all bugs].",
    "Ownership and borrowing are checked at compile time; there is no garbage collector [passage: run-time GC].",
    "unsafe only permits a few extra operations inside the block; the borrow checker still runs [passage: switches "
    "everything off]."])
tp("async", "what async/await does and does not do", "a Python developer", "asyncio", "threads",
   "for a crawler that makes 10,000 HTTP requests",
   "Async functions run in parallel on several CPU cores. Marking a CPU-heavy function async makes it non-blocking. "
   "asyncio is always faster than threads.",
   ["asyncio gives concurrency on one thread through an event loop, not multi-core parallelism [passage: parallel "
    "on cores].",
    "CPU-bound code inside a coroutine blocks the event loop; it needs an executor or processes [passage: "
    "non-blocking].",
    "For moderate I/O threads perform comparably; asyncio wins mainly at very high concurrency [passage: always "
    "faster]."])
tp("gc", "how tracing garbage collection works", "a developer debugging memory growth in a Java service",
   "generational garbage collection", "reference counting", "for a service with many short-lived objects and some "
   "caches",
   "A garbage-collected program cannot leak memory. Reference counting collects cycles automatically. Calling "
   "System.gc() often is the best way to reduce pause times.",
   ["Objects that stay reachable but unused (caches, listeners, static maps) leak even with a GC [passage: cannot "
    "leak].",
    "Plain reference counting cannot reclaim cycles without an extra cycle detector [passage: collects cycles].",
    "Explicit collection calls usually add pauses and cost throughput [passage: reduces pauses]."])
tp("dns", "how DNS resolution and record TTLs work", "a developer migrating a website to a new server",
   "lowering the TTL ahead of the migration", "keeping the TTL and waiting it out",
   "for moving a domain whose records have a 24-hour TTL",
   "When you change a DNS record, every user sees the change within a minute. Lowering the TTL right before the "
   "change makes it propagate immediately. DNS only maps names to IPv4 addresses.",
   ["Resolvers cache records for up to the TTL, so users can see the old record for up to the old TTL [passage: "
    "within a minute].",
    "The TTL must be lowered at least one old TTL before the change, so caches pick up the short TTL [passage: right "
    "before].",
    "DNS has many record types (AAAA, CNAME, MX, TXT, ...) [passage: IPv4 only]."])
tp("crdt", "what CRDTs are and why local-first apps use them", "a product designer of a note-taking app",
   "CRDT-based sync", "server-authoritative sync with conflict prompts",
   "for a notes app that must work offline on several devices",
   "CRDTs prevent conflicts from ever happening, so users' intentions are always preserved. They need a central "
   "server to decide the order of edits. CRDT documents never grow, because deleted text is removed immediately.",
   ["CRDTs guarantee that replicas converge; the merged result can still differ from what users intended "
    "[passage: intentions preserved].",
    "No central coordinator is needed; replicas merge in any order [passage: central server].",
    "Tombstones and metadata accumulate, and garbage-collecting them is a known difficulty [passage: never grow]."],
   src="baseline P100")
tp("priors", "what a prior does in Bayesian inference", "an analyst trained in frequentist statistics",
   "weakly informative priors", "flat priors", "for a hierarchical model of eight schools' test results",
   "A flat prior is always non-informative, whatever parameterisation you use. With enough data the prior never "
   "matters, even in hierarchical models with few groups. If the sampler reports divergences, just run more "
   "iterations.",
   ["Flatness is not invariant under reparameterisation: flat in sigma is not flat in log sigma [passage: always "
    "non-informative].",
    "With few groups the prior on the group-level scale strongly affects the posterior [passage: never matters].",
    "Divergences signal difficult geometry (e.g. a funnel); the fix is reparameterisation (non-centred) or a higher "
    "target acceptance, not more iterations [passage: run longer]."], src="baseline P50")
tp("bootstrap", "the bootstrap for confidence intervals", "an engineer analysing benchmark results",
   "the percentile bootstrap", "a t-interval", "for the median latency of 30 runs",
   "The bootstrap creates new data, so it increases the sample size. Ten resamples are enough for a 95% interval. "
   "The bootstrap works for any statistic, including the maximum.",
   ["Resampling adds no information; it approximates the sampling distribution from the same n [passage: larger "
    "sample].",
    "Percentile intervals need on the order of thousands of resamples [passage: ten].",
    "The bootstrap is known to fail for extremes such as the maximum [passage: any statistic]."])
tp("multiple-comparisons", "the multiple-comparisons problem", "a marketing analyst running many A/B tests",
   "Bonferroni or Holm correction", "false-discovery-rate control (Benjamini-Hochberg)",
   "for 40 metrics tracked in one experiment",
   "If you test 20 metrics at alpha = 0.05 and one comes out significant, it is very likely a real effect. "
   "Bonferroni controls the false discovery rate. Pre-registering a primary metric is unnecessary if you correct for "
   "multiplicity.",
   ["With 20 null metrics, P(at least one p < 0.05) = 1 - 0.95^20 = 64%, so one hit is weak evidence [passage: "
    "likely real].",
    "Bonferroni controls the family-wise error rate; Benjamini-Hochberg controls the false discovery rate [passage: "
    "Bonferroni controls FDR].",
    "Pre-registration still fixes the decision metric and limits analytic flexibility beyond the corrected family "
    "[passage: unnecessary]."])
tp("regression-causation", "why a regression coefficient is not automatically a causal effect", "a policy analyst",
   "controlling for covariates in a regression", "a randomised experiment",
   "for estimating the effect of tutoring on grades",
   "Adding more control variables always reduces bias. If a coefficient is statistically significant, it is causal. "
   "Controlling for a variable that the treatment causes helps isolate the effect.",
   ["Controlling for colliders or bad controls can increase bias [passage: always reduces].",
    "Statistical significance says nothing about causation [passage: significant means causal].",
    "Controlling for a post-treatment variable (a mediator) removes part of the effect and can bias it [passage: "
    "helps]."])
tp("survivorship", "survivorship bias", "a startup founder reading success stories",
   "studying successful companies", "studying a full cohort including the failures",
   "for deciding which practices predict startup success",
   "If most successful startups share a feature, that feature causes success. Survivorship bias only affects "
   "historical data, not current surveys. Studying more successful companies removes the bias.",
   ["Without the feature's frequency among failures, its presence among successes says nothing about its effect "
    "[passage: causes success].",
    "Any selection on the outcome causes it, including current surveys of survivors [passage: historical only].",
    "A larger biased sample stays biased [passage: more companies remove it]."])
tp("eigen", "what eigenvalues and eigenvectors are", "a first-year student who knows matrix multiplication",
   "the eigendecomposition", "the singular value decomposition",
   "for analysing a non-square data matrix in principal component analysis",
   "Every square matrix has a full set of eigenvectors. The eigenvalues of a matrix are its diagonal entries. The "
   "eigendecomposition works for rectangular matrices too.",
   ["Defective matrices (e.g. [[1, 1], [0, 1]]) lack a full set of eigenvectors, and real matrices may need complex "
    "eigenvalues [passage: every square matrix].",
    "Eigenvalues equal the diagonal only for triangular (or diagonal) matrices [passage: diagonal entries].",
    "Eigenvalues are defined for square matrices only; rectangular matrices use the SVD [passage: rectangular]."])
tp("fourier", "what the Fourier transform tells you about a signal", "an audio hobbyist",
   "the short-time Fourier transform", "one FFT of the whole recording",
   "for finding when a whistle starts in a 10-minute recording",
   "The FFT of a recording tells you exactly when each frequency occurs. A longer window improves both time and "
   "frequency resolution. Sampling at 44.1 kHz captures frequencies up to 44.1 kHz.",
   ["A single FFT of the whole signal has no time localisation [passage: tells when].",
    "Longer windows improve frequency resolution at the cost of time resolution [passage: both improve].",
    "The Nyquist limit at 44.1 kHz sampling is 22.05 kHz [passage: 44.1 kHz]."])
tp("entropy", "Shannon entropy", "a programmer interested in compression", "Huffman coding", "arithmetic coding",
   "for compressing text with a skewed symbol distribution",
   "Entropy measures how disordered a file looks, so random-looking files have low entropy. A good compressor can "
   "shrink any file. Huffman coding always reaches the entropy exactly.",
   ["Uniformly random data has maximal entropy and is incompressible [passage: low entropy].",
    "By counting (pigeonhole), no lossless compressor shrinks every file [passage: any file].",
    "Huffman coding is within one bit per symbol of the entropy and exact only for dyadic probabilities [passage: "
    "always exact]."])
tp("np-complete", "what NP-complete means", "a software engineer",
   "exact methods such as integer programming", "heuristics and approximation algorithms",
   "for a delivery-route planner with 200 stops",
   "NP stands for non-polynomial, so NP problems cannot be solved in polynomial time. NP-complete problems are "
   "impossible to solve exactly for large inputs. If a problem is NP-complete, every instance of it is hard.",
   ["NP means nondeterministic polynomial time; it contains P, and whether P = NP is open [passage: "
    "non-polynomial].",
    "Exact solvers routinely handle large practical instances; NP-completeness is about worst-case growth "
    "[passage: impossible].",
    "Hardness is a worst-case notion; many instances are easy [passage: every instance hard]."])
tp("birthday", "the birthday paradox and hash collisions", "a developer choosing identifier lengths",
   "random 64-bit identifiers", "random 128-bit identifiers (UUIDv4)", "for one billion records",
   "With 64-bit random IDs you need about 2^64 records before a collision becomes likely. Collisions in a hash table "
   "mean the hash function is broken. Truncating SHA-256 to 32 bits keeps it collision-resistant.",
   ["Collisions become likely around 2^32 values (birthday bound); at 10^9 random 64-bit IDs P(collision) is "
    "about n^2 / 2^65, roughly 3% [passage: 2^64].",
    "Hash tables expect collisions and resolve them by design [passage: broken].",
    "A 32-bit truncation collides after about 2^16 = 65,000 inputs [passage: still collision-resistant]."])
tp("memory-locality", "why memory access patterns affect performance",
   "a scientist writing numerical code in C or NumPy", "row-major traversal", "column-major traversal",
   "for summing a 10,000 x 10,000 matrix stored in C order",
   "Memory access time is the same for every address, so loop order does not matter. CPU caches only help if the "
   "same element is read twice. More threads always speed up a memory-bound loop linearly.",
   ["Caches, cache lines and prefetching make sequential access much faster than strided access [passage: same "
    "for every address].",
    "Spatial locality matters: a cache line brings neighbouring elements, so reading them is nearly free [passage: "
    "only repeated reads].",
    "A memory-bound loop saturates memory bandwidth, so extra threads stop helping [passage: linear speed-up]."])
tp("screen-readers", "how screen readers use semantic HTML", "a front-end developer", "native HTML elements",
   "custom elements with ARIA roles", "for a modal dialog and a custom drop-down",
   "ARIA attributes make any div fully accessible, including keyboard support. Screen readers read the visual layout "
   "from left to right. Adding aria-label to every element improves accessibility.",
   ["ARIA only conveys semantics; focus handling and keyboard behaviour must be implemented [passage: includes "
    "keyboard].",
    "Screen readers follow the DOM and accessibility tree order, not the visual layout [passage: visual order].",
    "aria-label overrides visible text and adds noise when overused; native semantics come first [passage: label "
    "everything]."], src="baseline P43")
tp("responsive-images", "how browsers choose responsive images", "a web designer",
   "srcset with width descriptors", "CSS background images", "for a photo-heavy portfolio site",
   "The browser downloads every image listed in srcset and shows the best one. The sizes attribute is optional and "
   "has no effect on which file is chosen. A 4000-pixel image scaled down with CSS loads as fast as a 1000-pixel one.",
   ["The browser picks and downloads one candidate [passage: every image].",
    "Without sizes the browser assumes the image fills the viewport width (100vw), so it often picks a larger file "
    "than needed [passage: no effect].",
    "A larger file costs bandwidth and decoding time regardless of display size [passage: as fast]."],
   src="baseline P44")
tp("semver", "semantic versioning", "a library maintainer", "semantic versioning", "calendar versioning",
   "for a library used by 300 internal services",
   "In semver any change requires a major version bump. Releases 0.x.y follow the same compatibility rules as 1.x.y. "
   "A patch release may add new public functions.",
   ["Major versions are for breaking changes; minor for compatible features; patch for compatible fixes [passage: "
    "any change].",
    "Under 0.y.z anything may change at any time [passage: same rules].",
    "New public functionality belongs in a minor release [passage: patch]."])
tp("llm-judge", "biases of LLM-as-judge evaluation", "an ML team adopting automatic evaluation",
   "pairwise comparison by a judge model", "absolute scoring against a rubric",
   "for ranking two prompt variants on 200 test questions",
   "An LLM judge is unbiased because it has no personal preferences. Showing the two answers in a fixed order is fine "
   "as long as the same order is used for every question. Longer answers score higher because they contain more "
   "information, so length bias is not a problem.",
   ["LLM judges show documented position, verbosity and self-preference biases [passage: unbiased].",
    "A fixed order confounds the comparison with position bias; judge both orders or randomise [passage: fixed order "
    "fine].",
    "Length bias rewards verbosity independent of quality and must be controlled [passage: not a problem]."])
tp("rag-eval", "how to evaluate retrieval in a retrieval-augmented generation system",
   "a developer who built a chatbot over company documents", "recall@k on a labelled question set",
   "end-to-end answer grading by a judge model", "for choosing between BM25, embeddings and a hybrid retriever",
   "If the final answers look good on a few questions, retrieval must be working. Recall@3 measures the fraction of "
   "the three retrieved chunks that are relevant. Tuning the retriever on the same 10 questions you report gives an "
   "unbiased estimate.",
   ["A handful of good-looking answers is anecdotal, and the generator can mask retrieval failures [passage: must be "
    "working].",
    "Recall@3 is the share of relevant chunks (or questions whose answer chunk) found in the top 3; the passage "
    "describes precision@3 [passage: definition].",
    "Tuning and reporting on the same questions overfits; hold out a test set [passage: unbiased]."],
   src="baseline P55")
tp("seeds", "random seeds and reproducibility in data analysis", "a researcher sharing analysis code",
   "fixing a single seed", "reporting variation across several seeds", "for comparing two model-training recipes",
   "Setting a random seed makes results correct. If two methods differ on one seed, the better one is better in "
   "general. GPU training is fully deterministic once the seed is fixed.",
   ["A seed makes a run repeatable, not correct [passage: correct].",
    "Seed-to-seed variance can exceed the difference; compare over several seeds with intervals [passage: one seed "
    "decides].",
    "Many GPU kernels are non-deterministic (e.g. atomic adds) unless deterministic modes are enabled [passage: fully "
    "deterministic]."], src="baseline P91")
tp("rounding-money", "how to represent and round money in software", "a developer building an invoicing feature",
   "integer minor units (cents)", "a decimal type with explicit rounding", "for invoices with VAT in several currencies",
   "Store amounts as floats, since they have plenty of precision. Round each line item up, so that customers are "
   "never undercharged. All currencies have two decimal places.",
   ["Binary floats cannot represent most decimal amounts exactly; use integer minor units or a decimal type "
    "[passage: floats fine].",
    "Rounding rules (half-even or half-up, per line or per total) must follow the tax rules; always rounding up "
    "overcharges and breaks totals [passage: round up].",
    "Currencies differ in minor units (JPY has 0, KWD has 3) [passage: always two]."])
