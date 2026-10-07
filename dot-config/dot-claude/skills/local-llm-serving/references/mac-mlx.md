# Mac: MLX first

Part of `local-llm-serving`.

## 3. Mac: MLX first
```bash
mlx_lm.generate --model <repo-or-dir> --prompt "..." --max-tokens 256        # greedy by default (temp 0)
mlx_lm.chat --model <repo-or-dir>
mlx_lm.server --model <repo-or-dir> --host 127.0.0.1 --port 8080 --max-tokens 4096 \
  --prompt-cache-size 10 --prompt-cache-bytes 32GB --decode-concurrency 32 --prompt-concurrency 8
```
- Endpoints: `/v1/chat/completions`, `/v1/completions`, `/v1/models`, `/health` (OpenAI-style; no Anthropic endpoint, no auth: keep it on 127.0.0.1 — its docs say it is not for production). A request's `model` field can name another local path or repo, which the server loads.
- Chat template: the tokenizer's own; `--chat-template-args '{"enable_thinking":false}'` passes template kwargs; `--chat-template` overrides. Tool calls work only when the tokenizer's template supports tools.
- Batching is continuous for batchable requests; `--kv-bits 4|8` (with `--kv-group-size`, `--quantized-kv-start`, default 5000), `--draft-model` (with `--num-draft-tokens`, default 3), a request that sets `seed`, or a model whose cache type cannot merge make the server serve one request at a time. Quantized-KV attention is not fused: it keeps a prefill_step × context score matrix, so lower `--prefill-step-size` with `--kv-bits`.
- Fixed long prefix: `mlx_lm.cache_prompt --model M --prompt - --prompt-cache-file p.safetensors < prefix.txt`, then `mlx_lm.generate --prompt-cache-file p.safetensors --prompt "..."`. `--max-kv-size N` (generate/chat) is a rotating cache: bounded memory, degraded long-range recall.
- Benchmark: `mlx_lm.benchmark --model M -p 4096 -g 128 -b 1 -n 5` prints prompt_tps, generation_tps, peak_memory per trial and averages.

**oMLX** (github.com/jundot/omlx, Apache-2.0; checked against its README): a macOS menu-bar app plus server built on mlx-lm — continuous batching through mlx-lm's BatchGenerator, a paged KV cache with a hot RAM tier and a cold SSD tier that survives restarts, several models at once (LRU eviction, pinning, per-model TTL and settings), OpenAI and Anthropic endpoints (`/v1/chat/completions`, `/v1/completions`, `/v1/messages`, `/v1/embeddings`, `/v1/rerank`, `/v1/models`), admin UI at `/admin`. Needs macOS 15+, Python 3.11–3.13. Install from the DMG, `brew tap jundot/omlx https://github.com/jundot/omlx && brew install jundot/omlx/omlx`, or from source. `omlx serve --model-dir ~/models` (default port 8000; one MLX model per subdirectory); options include `--api-key`, `--paged-ssd-cache-dir`, `--paged-ssd-cache-max-size`, `--hot-cache-max-size`, `--max-concurrent-requests` (default 8), `--memory-guard`. It refuses non-loopback binds without an API key. Young project: re-read `omlx serve --help`.

**LM Studio**: GUI plus `lms` CLI, MLX and llama.cpp engines. `lms load <key> --context-length 32768 --gpu max --identifier <api-name>` (`--estimate-only` prints memory needs), `lms server start --port 1234`; OpenAI-compatible `/v1/...` and Anthropic-compatible `POST /v1/messages`; optional "Require Authentication" (accepts `x-api-key` or Bearer).

**llama.cpp on Metal** (Metal is on by default on macOS; `brew install llama.cpp` or a CMake build): same `llama-server` as §4, for GGUF-only models or grammar-constrained output.
