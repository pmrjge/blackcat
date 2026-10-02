---
name: git-large-repos
description: Use for big git repos and binaries — LFS, model weights, partial/sparse clones, submodules.
---
# Large files, big repositories, submodules and attributes

Part of `git-workflows` (safety rules: history rewrites need consent; publishing is the user's step). Model downloads and uploads: `hf-hub`.

## Large files and model weights
| Content | Where |
|---|---|
| Model weights, checkpoints, datasets | Not in git. Hugging Face Hub (Xet storage; `hf upload`) or object storage; pin repo revision + sha256 in config |
| Binary assets that must version with code (design sources, fixtures) | Git LFS: `git lfs install`, `git lfs track "*.psd"`, commit `.gitattributes` |
| Build outputs, caches | not versioned; `.gitignore` |
- Existing binaries: `git lfs migrate info --everything --top=20`, then `git lfs migrate import --include="*.psd"
  --everything` (rewrites history: needs consent; publishing it is the user's step). Guard with `check-added-large-files`.
- Hub repos: prefer `hf download`/`hf upload`; plain git + git-lfs still works through the Hub's LFS bridge, and
  git-xet (`git xet install`) adds Xet-native transfers.

## Big repositories
- Blobless clone for development: `git clone --filter=blob:none <url>` (blobs fetched on demand).
  Treeless (`--filter=tree:0`) only for one-shot builds; shallow (`--depth 1`) breaks bisect and merge-base.
- Sparse checkout (cone mode is the default; tested): `git clone --filter=blob:none --sparse <url>`, then
  `git sparse-checkout set src/pkg docs`, `add <dir>`, `list`, `disable`.
- `git maintenance start` schedules background prefetch and repacks; `git backfill` (experimental) batch-fetches
  missing blobs of a blobless clone.

## Submodules vs subtrees
| | Submodule | Subtree |
|---|---|---|
| Stores | a pointer to a commit of another repo | the other repo's content (optionally squashed) |
| Clone/update | `git clone --recurse-submodules`; `git submodule update --init --recursive`; bump with `git submodule update --remote <path>` and commit the pointer | nothing extra; `git subtree pull --prefix=<dir> <repo> <ref> --squash` |
| Use for | large or independently released deps | small vendored code; consumers never see it |
- Prefer a package manager when the dependency is published. Submodule pitfalls: detached HEAD inside it,
  forgetting to commit the new pointer, CI clones without `--recurse-submodules`.

## .gitattributes
```gitattributes
* text=auto eol=lf
*.bat text eol=crlf
*.png binary
*.safetensors binary
*.py diff=python
*.json diff=json
uv.lock -diff linguist-generated
vendor/** linguist-vendored
docs/** linguist-documentation
.github/** export-ignore
```
- `diff=json` needs a driver: `git config diff.json.textconv "python3 -m json.tool --sort-keys"` (tested);
  built-in hunk-header drivers include python, rust, golang, markdown, tex, cpp. No brace globs (`*.{a,b}`).
- `linguist-*` shape language stats and collapse generated diffs on GitHub; `export-ignore` affects `git archive`.
- After adding eol rules to an existing repo: `git add --renormalize .` and commit. Inspect: `git check-attr -a <file>`.

## Verify
- `git lfs ls-files` lists the tracked binaries; `git check-attr -a <file>` shows the intended attributes.
- After a renormalize or LFS migration: `git status` clean and the build reads the files as before.
