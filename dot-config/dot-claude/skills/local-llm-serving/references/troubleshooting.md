# Troubleshooting

Part of `local-llm-serving`.

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
