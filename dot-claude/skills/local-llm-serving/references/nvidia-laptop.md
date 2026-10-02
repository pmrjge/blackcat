# NVIDIA laptop

Part of `local-llm-serving`.

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
