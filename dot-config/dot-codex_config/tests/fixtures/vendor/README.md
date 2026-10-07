# Vendored Codex contract fixtures

Read-only copies from [openai/codex](https://github.com/openai/codex) at tag `rust-v0.160.1`
(fetched 2026-10-06), used only by the contract tests in `codex_config/tests`. They pin the facts
DESIGN.md §1 relies on; when the pinned Codex version moves, re-fetch them and re-run the probes.

| File | Upstream path | sha256 of the upstream file |
|---|---|---|
| `config.schema.json` | `codex-rs/core/config.schema.json` (unchanged copy) | `7ce31bde1ed6ef15c53a96ba460bb1d0fb7b99fd9ab719b567c94c474f62b023` |
| `hooks_schema.rs` | `codex-rs/hooks/src/schema.rs` (unchanged copy) | `162735b4d0c021c911cb3939b6130d2aad90cf5f865069a17b97c0cf02c53e14` |
| `hook_names.rs` | `codex-rs/core/src/tools/hook_names.rs` (unchanged copy; identical on `main` 2026-10-06) | `ab0f235f27bc063feb6468d8d0d57201a08538798cfe45dd8008eab60d991553` |
| `models.gpt6.json` | extract of `codex-rs/models-manager/models.json`: `slug`, `default_reasoning_level` and the effort names of `supported_reasoning_levels` for the `gpt-6*` models | `fd219bd9f061278275f528939f82f54d2eb97df4b25c23b022adbe48813d920b` |

License: openai/codex is Apache License 2.0 (https://github.com/openai/codex/blob/rust-v0.160.1/LICENSE).
These files are reproduced unmodified (bar the extract, which is a derived subset) for interoperability testing.
