---
name: llm-evals
description: Load before reporting an LLM quality number — perplexity protocol, harnesses, task sets, LLM-as-judge bias controls, RAG/agent evals.
---
# LLM evaluation protocol

## Choose the evaluation by the claim
| Claim | Evaluation |
|---|---|
| Compression/quantization/fine-tune kept general quality | perplexity on a fixed corpus + a small benchmark suite, both vs baseline |
| Model is better at task X | a held-out task set with exact-match/F1/pass@k or a rubric, vs baseline |
| System (RAG, agent) answers correctly | end-to-end set with references; retrieval metrics separately |
| Output style/helpfulness | pairwise LLM-as-judge with controls, spot-checked by a human |

## Perplexity
Fixed tokenizer, dataset and split, context length, stride (sliding window), BOS handling and token count; report the protocol with the number. Perplexity is only comparable between models that share a tokenizer.
`mlx_lm.perplexity` samples random chunks of an HF dataset (no split or stride options): fine for a quick relative check, not for this protocol — write a short sliding-window script for reportable numbers.

## Benchmarks
- Pin the harness and its version (e.g. lm-evaluation-harness; `mlx_lm.evaluate` wraps it and needs `mlx-lm[evaluate]` — check `--help`), the task versions, the number of few-shot examples, the prompt format/chat template and generation settings (greedy, max tokens).
- Run baseline and candidate with the same settings in the same session; report the harness's stderr where it provides one.
- Use a subset only when you say so and keep it fixed across candidates.

## LLM-as-judge
- Pairwise comparison beats absolute scores. Randomize/swap the A/B position and count a win only if it survives the swap; blind the judge to model names; fix the judge model and prompt; give a rubric.
- Calibrate: agreement of the judge with a small human-labeled sample; report it.
- Known biases: position, verbosity/length, self-preference, style over substance.

## RAG and agents
- Retrieval: recall@k / MRR on queries with known relevant documents. Generation: faithfulness to retrieved context and answer correctness, measured separately.
- Agents: task success rate on a fixed task set, tool-call errors, cost and latency per task; several trials per task when the agent is stochastic.

## Contamination and leakage
Check whether test items (or near-duplicates) appear in training/fine-tuning data or in retrieval corpora; prefer sets published after the model's training cutoff or private sets.

## Statistics
Report n and a confidence interval (bootstrap over items; paired when both systems answer the same items). A difference inside the interval is "no detectable difference". Multiple comparisons across many tasks → say how many you ran.

## Report
```
| system | settings | metric | value (95% CI) | n | Δ vs baseline | cost/latency |
|---|---|---|---|---|---|---|
```
With harness/tool versions, the judge prompt if used, and 3–5 representative failures.

Related skills: `dataset-curation` (building and decontaminating eval sets), `local-llm-serving` (serving the model under test), `data-visualization` (plots).
