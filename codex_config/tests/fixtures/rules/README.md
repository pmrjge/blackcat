# Vendored Codex sources for the rules, permissions and requirements part

Read-only copies from [openai/codex](https://github.com/openai/codex) at tag `rust-v0.160.1`, fetched
2026-10-06 from `https://raw.githubusercontent.com/openai/codex/rust-v0.160.1/<upstream path>`. They are
what `lib/convert_rules.py`, `lib/permissions.py`, `lib/requirements.py` and
`tests/fake-codex/execpolicy_mirror.py` rely on; the tests read some of them (marked *test input*).
When the pinned Codex version moves, re-fetch, compare the sha256 values and re-run the suite.

Full copies are byte-identical to upstream. Extracts are contiguous line ranges of the upstream file
(several ranges are joined by one blank line); the sha256 is that of the whole upstream file.

| File | Upstream path (lines) | sha256 of the upstream file | Used for |
|---|---|---|---|
| `execpolicy_README.md` | `codex-rs/execpolicy/README.md` | `1e0a4fdbf9d9de143c140bda551213712f7ac227a62c155f33354b761869f66b` | rule syntax, CLI, JSON response shape |
| `execpolicycheck.rs` | `codex-rs/execpolicy/src/execpolicycheck.rs` | `ca0fd263be42e0ee7dab450912c409b8874dd2ec5f74e2650ba5de2deb8b1955` | `check` argv (`-r/--rules` repeatable, `--pretty`, `--resolve-host-executables`, trailing command), output struct |
| `parser.rs` | `codex-rs/execpolicy/src/parser.rs` | `58b89a789c394cffa2412189b5acadf2110ab23229c91db5878b72d5aeb9fee8` | `prefix_rule` builtin, first-token alternatives, load-time example validation (`not_match` then `match`) |
| `rule.rs` | `codex-rs/execpolicy/src/rule.rs` | `f18a712fa2c7c9700d5bda076dcdb151fb62393898429fddbc28922285645fd1` | exact-token prefix matching, `RuleMatch` serialization |
| `policy.rs` | `codex-rs/execpolicy/src/policy.rs` | `dbac4c7b1cc4efd2859538a8b9348aa5969118476f1e79f1fe7928d8d24a1f09` | exact match first, then basename fallback with `host_executable` gating |
| `decision.rs` | `codex-rs/execpolicy/src/decision.rs` | `9a706dbee5301bb81b2c89a69380dab15b68abafad4e102521d81b6009de2e03` | `allow < prompt < forbidden` |
| `cli_tests_execpolicy.rs` | `codex-rs/cli/tests/execpolicy.rs` | `98edf7cc70dfa79ae25ed688b590c323a826bcdd6f2c3cfc37969a0f4018936c` | *test input*: the exact JSON of `codex execpolicy check` |
| `example.codexpolicy` | `codex-rs/execpolicy/examples/example.codexpolicy` | `f0fc4c5c81e8a9f18d951a6e118eba448c92a0f6ff9f68f92f15721a61562457` | *test input*: upstream's example policy must load in the mirror |
| `requirements_exec_policy.rs` | `codex-rs/config/src/requirements_exec_policy.rs` | `cd1666263ca9f3fd7c52f692fe653f0ab0e7e1b97ed54ec3acd6429ad9b723fc` | `[rules] prefix_rules` TOML shape (`token`/`any_of`), `allow` refused |
| `config_requirements.ConfigRequirementsToml.extract.rs` | `codex-rs/config/src/config_requirements.rs` (1026–1077) | `7263d270276fa7098d3a51b7e7e0c65406b7b14e0266ac3594ff79c6ab433745` | *test input*: every top-level `requirements.toml` key |
| `config_requirements.permissions.extract.rs` | same file (630–700) | same | `[permissions.filesystem] deny_read` |
| `config_requirements.enums.extract.rs` | same file (826–835, 1458–1476) | same | `allowed_web_search_modes`, `allowed_sandbox_modes` values |
| `hook_config.extract.rs` | `codex-rs/config/src/hook_config.rs` (35–61, 153–225) | `b7ac42b2a895a00b6aa491eee1d3eb04d8a147ba0e77e016bde42381e067d1c0` | managed `[hooks]` (`managed_dir`, event groups, command handler) |
| `protocol_models.builtin_profiles.extract.rs` | `codex-rs/protocol/src/models.rs` (409–416) | `916a595e136f4d7e32ce259f50678ffe818af2ea6a92f54d8628f57bfd4d43e7` | *test input*: built-in profile ids `:read-only`, `:workspace`, `:danger-full-access` |
| `core_config_mod.is_permission_allowed.extract.rs` | `codex-rs/core/src/config/mod.rs` (4913–4921) | `854f5a6b184714740500b8d3eae2bb04cb88172efccf11d38a74f2f6189c0341` | ids missing from `allowed_permission_profiles` are denied |
| `core_config_permissions.compile.extract.rs` | `codex-rs/core/src/config/permissions.rs` (557–800) | `cda9109f6a5405dbf2abbe7d53883b755419c5b6d0b3e7f5834c65710db3479a` | filesystem keys: absolute, `~/`, `:special`; globs only with `deny` (or a trailing `/**`); `:workspace_roots` scoped globs |
| `core_exec_policy.extract.rs` | `codex-rs/core/src/exec_policy.rs` (370–380, 662–700) | `e31fa19073d5d9c2f89b12f743f24abd06966ed58e07e3a4f3d61ad275d91836` | runtime uses `resolve_host_executables: true`; `rules/*.rules` per config folder |
| `features.extract.rs` | `codex-rs/features/src/lib.rs` (1224–1229, 1302–1310) | `124c76d1fbad7b05fd78a62b89a28282c7ecab1de7426ac18696987024ddeae0` | feature keys `hooks` (stable, on) and `network_proxy` (experimental, off) |

The tag's `codex-rs/execpolicy/tests/basic.rs` (sha256
`5a26d154b4b1e448e6e358c2e19c9245cfe15d295f7519f77e5dc75a78eb0569`) is the source of the
expectations ported into `tests/test_execpolicy_mirror.py` (multiple files, first-token aliases,
tail aliases, strictest decision); it is not copied.

Not verified here (the docs site `learn.chatgpt.com` is not reachable from the build sandbox): the
docs pages for rules and permissions. Everything above is from the source at the tag.

License: openai/codex is Apache License 2.0 (https://github.com/openai/codex/blob/rust-v0.160.1/LICENSE).
These files are reproduced unmodified, or as unmodified line ranges, for interoperability testing.
