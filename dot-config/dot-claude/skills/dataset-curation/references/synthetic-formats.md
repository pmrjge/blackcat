# Synthetic data and formats

Part of `dataset-curation`.

## 8. Synthetic data
1. Diversity by design: a taxonomy grid (topic × task type × difficulty × persona/format), real seed examples, varied instructions; sampling temperature adds surface variety, not coverage.
2. Structured generation; store generator model, prompt version, seed and parameters on every record; mark `source: synthetic`.
3. Verify: programmatic checks first, then an LLM judge with a rubric from a different model family than the generator, then human spot checks. Reject rather than repair.
4. Dedup (exact, near, semantic) and decontaminate — generators reproduce benchmark items.
5. Model collapse: training recursively on model outputs erodes the tails of the distribution (Shumailov et al., Nature 2024); keeping real data and accumulating rather than replacing data across generations avoids the collapse in controlled studies (Gerstgrasser et al., 2024). Track diversity (distinct-n, embedding coverage, topic entropy) per generation.
6. Check the generator's license and terms before using outputs for training.

## 9. Formats
- JSONL or Parquet with an explicit schema, UTF-8, a stable `id` and metadata columns (source, license, language, created_at, generator, filters passed, split).
- TRL conventions: standard (`text`; `prompt` + `completion`; `prompt` + `chosen` + `rejected`; unpaired `prompt` + `completion` + `label`) or conversational (`messages` as `{role, content}` lists; the same keys holding message lists). Tool-calling datasets add a `tools` column of JSON schemas typed `Json()` in `datasets.Features`. SFTTrainer takes language-modeling or prompt-completion data, DPOTrainer preference, GRPOTrainer and RLOOTrainer prompt-only, KTOTrainer unpaired preference.
- Keep conversations unrendered; render with the target model's template at training time (`tokenizer.apply_chat_template(messages, tokenize=False)`), inspect rendered samples and the assistant-only loss mask (`llm-finetuning`).
- Multimodal: media as files or URIs plus content hashes (or `datasets` `Image`/`Audio` features in Parquet), with per-asset license, resolution/duration and captions in separate fields.
