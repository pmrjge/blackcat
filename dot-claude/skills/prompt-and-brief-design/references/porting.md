# prompt-and-brief-design — porting (reference)
Read when porting a prompt to another provider or model. Parent: `prompt-and-brief-design` SKILL.md.

## 9. Porting across providers

| Aspect | Claude (Messages API) | OpenAI-compatible server | Local open-weight model |
|---|---|---|---|
| System prompt | `system` parameter | `system` message | template-dependent: some chat templates lack a system role and merge it into the first user turn — render and check |
| Structured output | `output_config.format`, strict tools | `response_format` (enforcement varies) | grammar/JSON-schema constrained decoding, else validate + retry |
| Prefill | not supported from the Claude 4.6 generation on (400 error): use structured outputs or instructions | server-dependent (llama-server `--prefill-assistant`) | template-dependent |
| Reasoning | adaptive thinking; `output_config.effort` | server-specific fields | template kwargs (`enable_thinking`), llama-server `--reasoning-budget` / `--reasoning-effort` |
| Tools | native `tools` | `tools` + server-side parser | parser + template; fewer tools, flatter schemas |

- Smaller models need shorter prompts, fewer simultaneous constraints, more examples and an explicit output format; check that rules stated early in a long prompt still hold in the outputs.
- Verbosity and formatting defaults differ between models, even Claude generations: set length and format explicitly and re-test.
- Set sampling explicitly (temperature, top_p) from the model card; server defaults differ.
- Re-run the full suite after porting; do not carry prompt workarounds tuned for another model without evidence.
