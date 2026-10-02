---
name: local-llm-serving
description: Use to run, size or benchmark local LLMs — mlx-lm, oMLX, llama.cpp, vLLM, SGLang.
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
Read `references/mac-mlx.md` when serving on the Mac (mlx-lm, oMLX, LM Studio, memory limits).

## 4. NVIDIA laptop
Read `references/nvidia-laptop.md` when serving on the RTX laptop (llama.cpp, vLLM, SGLang, 12 GB VRAM limits).

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
Read `references/troubleshooting.md` when a server fails to load, runs out of memory or is slow.

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
