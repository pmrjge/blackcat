---
name: hf-hub
description: Use to find, download or publish Hugging Face models and datasets — licenses, gated repos, cache.
---
# Hugging Face Hub

## Find and vet
- Search with `mcp__huggingface` tools (models, datasets, papers, Spaces; details by repo id) or the website. Prefer the original publisher's repo; for community conversions (MLX, GGUF, quantized), check who made it, the source revision and the recipe.
- Read before downloading: model card, `config.json` (architecture, context length, RoPE settings, MoE layout), `tokenizer_config.json` (chat template, special tokens), license and usage restrictions, gated status, total size of the files you need.

## Download selectively
- CLI: `hf download <repo_id> --include "*.safetensors" --include "*.json" --include "tokenizer*" --local-dir <dir>` (one `--include` per pattern: extra patterns after a single `--include` are read as file names and the filter is dropped with only a warning); `--dry-run` first to see what would be fetched and how much; pin `--revision <commit>` for reproducibility (older installs name the CLI `huggingface-cli`; check `hf --help`, flags change between releases). `hf download hf://datasets/<repo>@<rev>/<path>` also works.
- Know where bytes go: the cache is `$HF_HOME/hub` (default `~/.cache/huggingface/hub`); `--local-dir` writes elsewhere. Check free disk space first (`df -h`) and state the size before multi-GB downloads; never download hundreds of GB without the user's consent (the rules' consent protocol).
- Auth: gated/private repos need a token (`HF_TOKEN` in stack.env or `hf auth login`). Never print or write the token.
- Faster transfers: `HF_XET_HIGH_PERFORMANCE=1` (the legacy `hf_transfer` path no longer applies); re-running an interrupted download skips completed files (details under Large downloads).

## Large downloads (hundreds of GB)
Checked against huggingface_hub 2.0 (`hf` CLI); older 1.x releases lack some commands — `hf --help` tells.
1. Size it: `hf download <repo> --include … --dry-run` prints "Will download N files (out of M) totalling X" plus a per-file table; `hf models ls <repo> -R -h` lists files with sizes; in Python `HfApi().model_info(repo, files_metadata=True).siblings` gives `rfilename`, `size` and `lfs.sha256`. Do not use `model.safetensors.index.json` `metadata.total_size` as the download size — it is whatever the publisher computed (DeepSeek-V3's index says 1.37 TB; its shards total 688.6 GB).
2. Check space where the bytes will land (`df -h` on the cache or `--local-dir` volume): download + any conversion output (`llm-quantization`) + headroom. The library only warns when space runs short. Report the number and get the user's consent through ASK USER.
3. Fetch configs first (`--include "*.json" --include "tokenizer*"`), read `config.json` (layers, experts, dtype, `quantization_config`) to confirm the plan, then the weights.
4. Patterns: one weight format only — `--include "*.safetensors"` and exclude duplicates such as `--exclude "*.bin" --exclude "original/*" --exclude "*.pth"`; GGUF repos: `--include "*Q4_K_M*"` (split files `-00001-of-0000N.gguf` all match). Patterns are globs over repo paths; a trailing-slash positional (`hf download <repo> subdir/`) fetches a folder and cannot be combined with `--include`. Dry-run the exact patterns.
5. Transfer: Xet storage is used automatically when `hf_xet` is installed (a default dependency on x86_64/arm64). Tune with `HF_XET_HIGH_PERFORMANCE=1` (all cores, saturate the link), `--max-workers` (files in parallel, default 8); download concurrency is adaptive (ceiling `HF_XET_CLIENT_AC_MAX_DOWNLOAD_CONCURRENCY`, default 64; `HF_XET_FIXED_DOWNLOAD_CONCURRENCY=N` pins it) — `HF_XET_NUM_CONCURRENT_RANGE_GETS` and `HF_XET_RECONSTRUCT_WRITE_SEQUENTIALLY`, still listed in the HF docs, are ignored since hf_xet 1.3. The Xet chunk cache is off by default (`HF_XET_CHUNK_CACHE_SIZE_BYTES=0`), so there is no hidden second copy. `HF_HUB_ENABLE_HF_TRANSFER` is deprecated.
6. Resume: re-running the same command skips complete files; in 2.x a file interrupted mid-transfer restarts from zero (partial temp files are discarded), and `*.incomplete` leftovers of killed runs in the cache are removed by `hf cache prune` (under `--local-dir`, delete them by hand). Run multi-hour pulls under `tmux`/`nohup` and repeat until the command exits 0.
7. Cache or local dir: the cache (`HF_HOME`/`HF_HUB_CACHE`, or `--cache-dir`) keeps blobs plus per-revision symlinked snapshots that mlx-lm and transformers resolve by repo id; 2.x also deduplicates Xet files across repos in a shared blob store (`HF_HUB_DISABLE_SHARED_BLOBS=1` turns it off). `--local-dir` writes plain files (bookkeeping in `<dir>/.cache/huggingface/`) — use it for a model placed on a specific volume; it cannot be combined with `--cache-dir`. To move the cache, set `HF_HOME` before downloading; moving blobs by hand breaks the symlinks.
8. Verify: `hf cache verify <repo> [--revision <rev>]` (cache) or `hf cache verify <repo> --local-dir <dir>` checks checksums against the Hub; add `--fail-on-missing-files` only for full-repo downloads (selective downloads miss files by design). Then check the index against the shards:
```python
import json, pathlib
from collections import defaultdict
from safetensors import safe_open
d = pathlib.Path("<dir>")
by_file = defaultdict(set)
for name, f in json.loads((d / "model.safetensors.index.json").read_text())["weight_map"].items():
    by_file[f].add(name)
missing = [f for f in by_file if not (d / f).exists()]
absent = {f: sorted(names - set(safe_open(d / f, framework="numpy").keys()))   # header only, works for FP8
          for f, names in by_file.items() if f not in missing}
print(f"{len(by_file)} shards; missing files: {missing}; files with absent tensors: {[f for f, a in absent.items() if a]}")
```
9. License and gating before the first byte: `HfApi().model_info(repo)` → `.gated` (`False`, `"auto"`, `"manual"`) and `.card_data.license` (for `other`, read `license_name`/`license_link` and the LICENSE file), or `hf models info <repo>`. Accept gated terms on the website with the account whose token you use (401/403 otherwise). Note acceptable-use policies, naming rules for derivatives and non-commercial clauses; quantized community conversions inherit the base model's license. Record license and revision next to the download.

## Verify
- License and gating checked before the first byte; size from `--dry-run` reported and disk space checked.
- Downloads verified with `hf cache verify` (step 8 above); the token never printed or written.
- Cleanup ran `--dry-run` first; nothing deleted before the user agreed.

## Inspect without loading
- safetensors headers give tensor names, shapes and dtypes without reading weights (`safetensors` `safe_open(..., framework="numpy")` → `keys()`, `get_slice(name).get_shape()`), which is enough to plan memory and quantization maps.
- Sum tensor sizes to check the parameter count against the card.

## Datasets
`datasets.load_dataset(..., split=..., streaming=True)` for large sets; pin the revision; check the license and the data card's collection method; sample and read examples before training on them.

## Publish (only when asked)
Create the repo private by default, upload with `hf upload` or `huggingface_hub.upload_folder`, include a model card with base model, data, recipe, evaluation (with protocol) and license; never upload secrets, local paths or personal data.

## Cleanup
`hf cache ls` (e.g. `--filter "size>30g" --revisions`) to find large revisions; `hf cache rm model/<org>/<name>` (the type-prefixed id `hf cache ls` prints, or an `hf://` URI — a bare `org/name` deletes nothing) or `hf cache prune` to remove them: `--dry-run` first, `-y` only after the user agrees.
