---
name: local-llm-serving
description: Load to run, size or benchmark an LLM locally — mlx-lm, oMLX, LM Studio, llama.cpp, vLLM, SGLang; memory math, KV cache, endpoints.
---
# Local LLM serving

## Scope
Running and serving open-weight LLMs on the Mac Studio (M3 Ultra, 512 GB unified memory, 819 GB/s) and the Linux laptop (RTX 5070 Ti Laptop GPU: Blackwell, compute capability 12.0 / `sm_120`, 12 GB GDDR7, 672 GB/s). Not here: making a quantized model (`llm-quantization`), exporting non-LLM models (ONNX, Core ML, ExecuTorch: `model-export`), downloading it (`hf-hub`), measuring its quality (`llm-evals`), profiling method (`accelerator-perf`), laptop driver/CUDA/PyTorch setup (`linux-workstation`), exposing a server beyond localhost or running LibreChat as a service (`self-hosting-ops`). Flags below were checked against mlx-lm, llama.cpp and vLLM sources of September 2026; these projects rename flags often, so confirm with `--help` before scripting.

## 1. Pick the runtime

| Situation | Default | Alternatives |
|---|---|---|
| Mac, any model that fits in memory | `mlx_lm.server` (MLX weights) | oMLX (multi-model, SSD KV tier, Anthropic API), LM Studio (GUI, MLX + llama.cpp engines), llama.cpp Metal (GGUF-only models, grammars) |
| Mac, client speaks the Anthropic Messages API | oMLX or `llama-server` | LM Studio (`POST /v1/messages`) |
| Laptop, one user | `llama-server` (CUDA, GGUF) | ExLlamaV3 + TabbyAPI when a dense model fits entirely in VRAM |
| Laptop, many concurrent requests, model + KV fit in VRAM | vLLM | SGLang |
| MoE larger than 12 GB on the laptop | `llama-server --n-cpu-moe N` | `-ot` tensor overrides |

## 2. Size it before downloading
- Weights ≈ params × bits-per-weight / 8. Real bpw includes scale overhead: MLX affine b bits with group g stores a bf16 scale and bias per group → b + 32/g (4-bit g64 = 4.5); `mxfp4` 4.25, `nvfp4` 4.5, `mxfp8` 8.25. GGUF (llama.cpp's Llama-3.1-8B table; model-dependent): Q4_K_M 4.89, IQ4_XS 4.46, Q5_K_M 5.70, Q6_K 6.56, Q8_0 8.50, IQ3_M 3.76.
- KV cache bytes = 2 × layers × kv_heads × head_dim × bytes/elem × tokens × sequences. Llama-3.1-8B (32 × 8 × 128) at f16 = 128 KiB/token → 32K tokens = 4 GiB; q8_0 ≈ half. MLA models cache (kv_lora_rank + rope_dim) per layer when the runtime keeps the latent. Sliding-window layers stop growing at the window; recurrent/SSM layers hold a fixed state; only global-attention layers scale with context.
- Compute buffers scale with the prefill chunk (`-ub` in llama.cpp, `--prefill-step-size` in MLX) and, without fused attention, with chunk × context. Add runtime overhead and, on the laptop, whatever the desktop already uses (`nvidia-smi`).
- Decode ceiling ≈ bandwidth / bytes read per token (active weights + KV read). An MoE reads only its active experts, so a 37B-active model at 4.5 bpw (~21 GB/token) tops out near 39 tok/s on 819 GB/s. Use it to sanity-check measurements, not as a promise.
- Mac GPU memory is wired memory. `uv run --with mlx python -c "import mlx.core as mx; print(mx.device_info())"` shows `max_recommended_working_set_size`; mlx-lm raises the wired limit to it and warns when the model exceeds ~90% of it. To go further: `sudo sysctl iogpu.wired_limit_mb=N` (N above the model's MB, below RAM; lasts until reboot). Leave tens of GB for macOS and other apps.
- Laptop budget: 12 GB minus display use minus ~1 GiB margin. Dense 8B at Q4_K_M/Q6_K with 16–32K context fits; 12–14B at Q4_K_M fits with 8–16K context and q8_0 KV; anything larger is MoE-with-offload territory.

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

## 4. NVIDIA laptop (RTX 5070 Ti Laptop, 12 GB)
Prerequisites: a current driver with NVIDIA's open kernel modules (Blackwell requires them; R570 or newer), software built with CUDA ≥ 12.8 (the first toolkit with `sm_120`). Check `nvidia-smi --query-gpu=name,memory.total,memory.used,compute_cap --format=csv`.

**llama.cpp (default)**
```bash
cmake -B build -DGGML_CUDA=ON && cmake --build build --config Release -j   # -DCMAKE_CUDA_ARCHITECTURES=120 if nvcc cannot see the GPU
build/bin/llama-server -m model-Q4_K_M.gguf -c 16384 -fa on -ctk q8_0 -ctv q8_0 --jinja \
  --host 127.0.0.1 --port 8080 --api-key "$LLAMA_API_KEY" --metrics
```
- `-ngl` defaults to `auto` and `--fit on` (default) sizes unset options to free VRAM with a 1024 MiB margin (`--fit-target`, `--fit-ctx`); set `-ngl all` and `-c` explicitly once you know the budget.
- Quantized V cache requires flash attention (`-fa on`, or `auto` turns it on); `-fa off` with `-ctv q8_0` is an error.
- `-np N` sets parallel slots; the KV pool is unified (`-kvu`) by default only when the slot count is auto, otherwise each slot gets `-c`/N — read `n_ctx_slot` in the startup log (`--kv-unified-per-slot N` caps it explicitly); `-cb` continuous batching is on by default; `--cache-prompt` (on), `--cache-reuse N` (reuse shifted chunks), `-cram MiB` host-RAM prompt cache (default 8192); `--sse-ping-interval` (default 30 s) keeps streams alive during long prefill.
- `-a name` sets the API model id; `--jinja` (default on) uses the GGUF's template; `--chat-template-file` overrides; `--reasoning-format deepseek` puts thinking into `reasoning_content`; `--reasoning-budget N` caps it.
- Endpoints: `/v1/chat/completions`, `/v1/completions`, `/v1/responses`, `/v1/embeddings`, `/v1/messages` (+ `/v1/messages/count_tokens`), `/apply-template` (renders the prompt — use it to debug templates), `/health`, `/metrics`, `/slots`. No model argument = router mode (`--models-dir`, load/unload by request).
- Quant choice for 12 GB: ≤8B → Q6_K/Q8_0; 12–14B → Q4_K_M or IQ4_XS; below 4 bits use imatrix quants (`llama-quantize --imatrix`; see `llm-quantization`); MXFP4/NVFP4 GGUF run on Blackwell's FP4 paths (`GGML_CUDA_MMQ_PREC` picks W4A4 vs W4A8).
- Offload trade-offs: every dense layer left on the CPU is read from system RAM each token, so partial dense offload drops decode speed steeply; MoE experts offload well because only the routed experts are read per token. Use `--n-cpu-moe N` (experts of the first N layers stay in RAM) or `--cpu-moe` (all), raising N until the rest fits; `-ot "<regex>=CPU"` for custom placement (expert tensors are named `blk.<i>.ffn_{gate,up,down}_exps`). `-nkvo` (KV in RAM) is a last resort.
- Speculation: `-md draft.gguf --spec-type draft-simple --spec-draft-n-max 8` (same tokenizer as the target); `--spec-type ngram-mod` (or `--spec-default`) needs no draft and helps code-editing workloads that copy text.

**vLLM** (model and KV must fit in VRAM; HF-format weights, quantized AWQ/GPTQ/FP8/compressed-tensors checkpoints for 12 GB):
```bash
uv venv && uv pip install vllm --torch-backend=auto
vllm serve <repo-or-dir> --host 127.0.0.1 --port 8000 --max-model-len 16384 \
  --gpu-memory-utilization 0.85 --kv-cache-dtype fp8 --max-num-seqs 8 --api-key "$VLLM_API_KEY"
```
Default `--gpu-memory-utilization` is 0.92 of the whole GPU — lower it when the desktop uses VRAM. Prefix caching is on by default; `--enforce-eager` saves CUDA-graph memory; `--cpu-offload-gb` (weights over UVA) and `--kv-offloading-size` (GiB of CPU KV) trade speed for capacity; `--speculative-config '{"method":"draft_model","model":"<draft>","num_speculative_tokens":5}'`; tools need `--enable-auto-tool-choice --tool-call-parser <parser>`; `--reasoning-parser` splits thinking. Serves OpenAI routes and Anthropic `/v1/messages`. vLLM warns that `--api-key` does not cover every route: keep it on loopback.

**SGLang**: `uv pip install --prerelease=allow sglang` (CUDA 13 wheels only since the cu129 line was retired); `.venv/bin/python -m sglang.launch_server --model-path <m> --port 30000 --context-length 16384 --mem-fraction-static 0.8 --kv-cache-dtype fp8_e4m3`. RadixAttention prefix sharing is its strength (many requests with shared prefixes, structured generation). Confirm `sm_120` works with a small model before planning around it.

**ExLlamaV3 / TabbyAPI**: EXL3 is a streamlined QTIP (trellis) variant, 2–8 bpw including fractional rates, best quality per bit for dense models that fit entirely in VRAM; convert with `uv run python convert.py -i <in> -o <out> -w <work> -b <bpw>`, serve through TabbyAPI (OpenAI-compatible). EXL2 (ExLlamaV2) is the older format. Plan for the whole model plus cache in VRAM.

## 5. Caching, batching, speculation

| | mlx_lm.server | llama-server | vLLM | SGLang |
|---|---|---|---|---|
| Continuous batching | yes (off with `--kv-bits`/draft) | `-np` slots, `-cb` | yes | yes |
| Prefix cache | LRU, `--prompt-cache-size/-bytes` | `--cache-prompt`, `--cache-reuse`, `-cram` | automatic prefix caching | RadixAttention |
| KV quantization | `--kv-bits 4/8` | `-ctk/-ctv q8_0…` (V needs FA) | `--kv-cache-dtype fp8` | `--kv-cache-dtype fp8_e4m3` |
| Speculative | `--draft-model` | `-md`, `--spec-type` | `--speculative-config` | see `--help` |

- Prefix caches hit only on byte-identical prefixes: keep system prompt and tool definitions stable and first, volatile content last; a timestamp or request id at the top defeats them.
- KV at 8 bits is usually close to lossless; 4-bit KV hurts long-context retrieval first — test it on a long-context task before adopting.
- Speculative decoding pays at batch 1 on memory-bound decode when acceptance is high (greedy/low temperature, predictable text); it shrinks as concurrency rises. Measure with and without on the same prompts.
- Concurrency: per-request speed falls while aggregate throughput rises; size slots/`--max-num-seqs` so that KV per sequence × concurrency fits.

## 6. Endpoints and clients
Read `references/endpoints-clients.md` when starting a server, wiring a client (OpenAI-compatible endpoints, ports, keys) or connecting an app to a local model.

## 7. Benchmark protocol
1. Environment block (see `accelerator-perf`): machine, OS/driver, runtime and version/commit, model repo@revision, quant, context, all flags.
2. Fixed grid: prompt lengths 512 / 4K / 16K, generation 128 and 512, greedy, EOS ignored for throughput runs; warm-up run discarded; ≥5 repetitions; report median and spread.
3. Measure separately: prefill tok/s, decode tok/s, TTFT (cold and prefix-cache hit), ITL/TPOT p50/p90, aggregate tok/s at concurrency 1/4/8, peak memory.
4. Tools: `mlx_lm.benchmark` (above); `llama-bench -m m.gguf -p 512,4096 -n 128 -d 0,16384 -fa on -ctk q8_0 -ctv q8_0 -r 5 -o md` (`-d` = context depth); any OpenAI-compatible server: `vllm bench serve --backend openai-chat --base-url http://127.0.0.1:8080 --endpoint /v1/chat/completions --model <id> --tokenizer <hf-id> --dataset-name random --random-input-len 2048 --random-output-len 256 --num-prompts 64 --max-concurrency 8 --ignore-eos --save-result` from any machine with vLLM installed (GuideLLM is the tool vLLM's docs recommend for serving benchmarks); repeat runs reuse the prefix cache — change `--seed` or restart the server.
5. Memory: MLX `peak_memory` / `mx.get_peak_memory()`; `nvidia-smi --query-gpu=memory.used --format=csv -lms 500` during the run.
6. Thermals (laptop): AC power, fixed power profile, log `nvidia-smi dmon -s puc` and `nvidia-smi -q -d PERFORMANCE` (clock-event reasons); rerun after 10 minutes of sustained load. Mac: `sudo powermetrics --samplers gpu_power,thermal -i 1000` (sampler names: `powermetrics --help`).
7. Compare decode tok/s with the bandwidth ceiling (§2); far below it means a config problem (CPU layers, swap, throttling, wrong kernel).

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Role tags or `<\|im_end\|>` in output, never stops | wrong chat template / missing stop token | use the model's template (`--jinja`, tokenizer template), render it (`/apply-template`, `apply_chat_template(..., tokenize=False)`), add EOS (`--extra-eos-token` in mlx_lm.generate) |
| Tool calls arrive as plain text | template or parser mismatch | tool-capable template; vLLM `--tool-call-parser`; llama.cpp `--jinja` |
| Thinking leaks into content, or empty answers | reasoning parsing | `--reasoning-format` / `--reasoning-parser`; disable thinking via template kwargs |
| Context-length errors, cut-off answers | prompt + max_tokens > context | raise `-c`/`--max-model-len` if memory allows; cap `max_tokens`; client context setting |
| OOM at load or on long prompts | weights + KV + buffers > budget | shorter context, KV quantization, smaller prefill chunk, fewer slots, lower memory fraction |
| Fast start, then slow | thermal throttling; Mac over the wired limit (warning printed) | check clocks/temps; raise wired limit or shrink the model |
| Speculation slower | low acceptance, oversized draft, batching disabled | smaller aligned draft, fewer draft tokens, measure |
| Gibberish after conversion | quantization or conversion bug | `llm-quantization` failure signatures |
| 401/404 from a client | key in wrong header, wrong `/v1` suffix | Bearer vs `x-api-key`; OpenAI base ends in `/v1`, Anthropic base does not |

## Verify
- `curl -s http://127.0.0.1:<port>/v1/models` lists the id; one greedy request matches `mlx_lm.generate`/`llama-cli` output for the same rendered prompt.
- A streamed request and a tool-call round trip work from the real client.
- Peak memory stays under budget at the target context and concurrency, with no swap (`vm_stat`/`sysctl vm.swapusage` on macOS).
- Two benchmark runs agree within noise.
- `lsof -nP -iTCP -sTCP:LISTEN | grep <port>` shows 127.0.0.1 unless exposure (with a key) was intended.

## Report
Environment block, then:
```
| runtime@version | model@rev | quant | ctx | KV dtype | conc | pp tok/s | tg tok/s | TTFT p50 cold/hit | peak mem | notes |
|---|---|---|---|---|---|---|---|---|---|---|
```
Plus exact launch commands, client configuration (keys as env var names only), and the known limitations of the setup.
