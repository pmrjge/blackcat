<!-- markdownlint-disable MD013 MD060 -->
# Skills

220 skills in `dot-claude/skills/`, each a folder with a `SKILL.md` and, where needed, `references/*.md` (182
reference files). None is preloaded: a skill's body enters an agent's context only when the agent loads it.

## Three shapes

| Shape | Count | What it is | Caps (`tests/test_skill_modules.py`) |
|---|---:|---|---|
| Hub | 28 | a `SKILL.md` with a `## Modules` table naming its modules | ≤ 80 lines |
| Module | 104 | a skill named in a hub's table; 89 are hidden and read by path, 15 stay listed | ≤ 150 lines, description ≤ 140 characters |
| Standalone | 88 | neither hub nor module | ≤ 500 lines |
| `references/*.md` | 182 files | detail a skill links to and reads only when needed | must exist where named |

Counts from `hubs_and_modules()` in `tests/test_skill_modules.py` and `ls dot-claude/skills/*/references/*.md`.
Two modules, `flutter` and `react-native`, sit in two hubs each (`android-engineering`, `swift-engineering`).

## How agents find and load a skill

Every agent's spawn carries the skill listing, so the stack keeps it small (`settings.json` → `skillOverrides`):

| Listing state | Skills | What the agent sees | How it loads one |
|---|---:|---|---|
| Described | 32 (`LISTED_CORE` in `tests/test_skill_modules.py`) | name and description | the Skill tool, by name |
| Name only (`"name-only"`) | 96 | `- <name>` only | the Skill tool, by name; description and body arrive with the call |
| Hidden (`"user-invocable-only"`) | 89 hub modules | nothing; the Skill tool refuses them | Read `~/.claude/skills/<name>/SKILL.md`, found through the hub's table or the agent's `## Skills` line, where they are marked `name`* |
| User commands (`disable-model-invocation`) | 3: `stack-doctor`, `stack-tree`, `override-agent` | nothing; you type them | answered by hooks ([Hooks and the guard](Hooks-and-Guard.md)) |

- **Pointers, not preloads.** Agent bodies carry a `## Skills` section of one-line "load X when Y" pointers; every
  module is reachable through its hub's table, and every hub is named by an agent of its family. Lint checks every
  name. The section is a lookup, not a checklist: a task that needs no skill reads none.
- **A new skill is name-only** unless it joins `LISTED_CORE`; the test enforces it.
- **Listing budget.** `skillListingBudgetFraction` 0.012 caps the listing (shared with plugin, bundled and claude.ai
  skills) and `skillListingMaxDescChars` 250 cuts each description; `tests/lint_agents.py` fails when the stack's
  listing plus the estimated others pass the budget.
- **Non-stack skills hidden** (still runnable as `/name`): Claude Code's code-review, security-review, simplify,
  fewer-permission-prompts, keybindings-help, init and dataviz, and the claude.ai skills `anthropic-skills:`
  deep-research, morning, import-memory, consolidate-memory, setup-claude, explain-usage, google-workspace and
  schedule. Plugin skills ignore `skillOverrides`.
- **One allow rule**, `Skill`, pre-approves every skill. If you open repositories you don't trust, replace it with
  `Skill(<name>)` rules: it also approves a repository's own `.claude/skills`.

## Catalogue

The domain headings below are an editorial grouping for this page, not a field in the repository. Every hub and
standalone skill appears once; modules appear under their hub (`*` marks a hidden module, read by path). "Use"
is the skill's own frontmatter description.

### Stack, Claude Code and agents

| Skill | Shape · listing | Use | Modules (`*` = read by path) |
|---|---|---|---|
| `agent-harness-design` | standalone · name only | Use to build an agent runtime — loop, stop rules, tool schemas, sandboxes, memory, multi-agent, evals. | — |
| `claude-code-extensions` | standalone · described | Load before changing Claude Code config — agents, skills, hooks, settings, MCP, plugins; stack conventions. | — |
| `code-standards` | standalone · described | Load before writing or changing code or infra config — workflow, minimal diffs, tests, escalation. | — |
| `override-agent` | standalone · described | Use to run a delegated agent type on another model for this session only; `list` shows overrides, `reset` undoes them. | — |
| `prompt-and-brief-design` | standalone · described | Load before writing a system prompt, agent definition, CLAUDE.md, research prompt, schema or few-shots. | — |
| `review-protocol` | standalone · described | Load before reviewing code, a plan or security, or verifying work — evidence-gated findings, severity. | — |
| `stack-doctor` | standalone · described | Check the multi-agent stack installation — binaries, API keys, MCP servers, agents, hooks, settings. | — |
| `stack-tree` | standalone · described | Show this session's tree of agents and subagents with the commands each ran; `table` for a markdown table, `static` for the design. | — |

### Programming languages

| Skill | Shape · listing | Use | Modules (`*` = read by path) |
|---|---|---|---|
| `android-engineering` | hub · name only | Use for Android or cross-platform mobile apps — Kotlin, Gradle/AGP, Compose, tests, adb. | `android-release`*, `flutter`, `kotlin-coroutines`*, `react-native` |
| `compiler-engineering` | hub · name only | Use for compilers and interpreters — parsing, type checking, IR/LLVM, codegen, JITs, Wasm. | `wasm` |
| `cpp-engineering` | standalone · described | Use for C or C++ — UB traps, RAII and lifetimes, concurrency, sanitizers, clang-tidy, ABI. | — |
| `go-engineering` | hub · described | Use for any Go work — modules, errors, context, generics, slog, linters, tests. | `go-concurrency`*, `go-modules-release`*, `go-testing`* |
| `haskell-engineering` | standalone · name only | Use for Haskell — GHCup, cabal/stack, testing, laziness and space leaks, profiling, STM. | — |
| `julia-engineering` | standalone · name only | Use for Julia — juliaup, Pkg, Test/Aqua/JET, type stability, benchmarks, GPU, SciML. | — |
| `jvm-engineering` | standalone · described | Use for JVM code — Java 21+, Scala 3, Gradle/Maven/sbt, JUnit, JMH, GC tuning, GraalVM. | — |
| `python-engineering` | hub · described | Use for any Python work — uv, PEP 723 scripts, typing, ruff, pytest, asyncio, profiling, wheels. | `py-async`*, `py-perf`*, `py-testing`*, `py-typing`*, `py-uv-packaging`* |
| `rust-engineering` | hub · described | Use for any Rust work — workspaces, edition 2024, errors, async, unsafe, tests, clippy, releases. | `rust-async`*, `rust-errors-ownership`*, `rust-release`*, `rust-testing`*, `rust-unsafe-ffi`* |
| `shell-scripting` | standalone · described | Load before writing a shell script or tricky one-liner — bash 3.2 vs zsh, BSD vs GNU, quoting. | — |
| `swift-engineering` | hub · name only | Use for Swift on Apple platforms — Swift 6 concurrency, SwiftPM, Swift Testing; iOS modules. | `app-store-release`*, `flutter`, `ios-build-sim`*, `react-native`, `swiftui`* |
| `typescript-engineering` | hub · described | Use for TypeScript or JavaScript — TS 7 vs 6, tsconfig, ESM/CJS, Node, pnpm, Vite, linting, tests, zod. | `ts-node-cli`*, `ts-testing`*, `ts-tooling`*, `ts-types-validation`* |

### Engineering practice

| Skill | Shape · listing | Use | Modules (`*` = read by path) |
|---|---|---|---|
| `algorithm-design` | standalone · described | Use for non-trivial algorithms and data structures — techniques, solvers, proofs, stress tests. | — |
| `api-design` | standalone · described | Use to design or change HTTP, gRPC or event APIs — errors, pagination, idempotency, versioning. | — |
| `cmake-ninja-builds` | standalone · name only | Use for CMake/Ninja builds of C, C++ or CUDA — targets, presets, vcpkg/Conan, ccache, CTest. | — |
| `codemods` | standalone · name only | Use for mechanical edits across many call sites — ast-grep, LibCST, jscodeshift, OpenRewrite. | — |
| `cpu-performance` | hub · name only | Use to measure or speed up CPU-bound code — benchmark method, profilers, flags (macOS, Linux). | `perf-load-testing`*, `perf-memory`*, `perf-profilers`* |
| `debug-bisect-minimize` | standalone · name only | Use to find a bug's first bad commit or smallest failing input — git bisect run, delta debugging. | — |
| `debug-native` | standalone · name only | Use for crashes, hangs or memory corruption in native code — sanitizers, lldb/gdb, rr. | — |
| `dep-upgrades` | standalone · name only | Use to upgrade dependencies or toolchains — changelogs, batching, semver checks, bots, rollback. | — |
| `dist-systems` | standalone · name only | Use for designs spanning services — timeouts, retries, idempotency, consistency, queues. | — |
| `editor-engineering` | standalone · name only | Use for editor internals or IDE features — ropes, undo, tree-sitter, LSP/DAP, terminals. | — |
| `formal-methods` | standalone · name only | Use when code or a protocol needs machine-checked assurance — z3/SMT, TLA+, Kani, Miri. | — |
| `git-workflows` | standalone · described | Use for git beyond a plain commit — worktrees, rebase, history edits, conflicts, recovery, LFS. | — |
| `ide-workflows` | standalone · name only | Use to set up dev tooling — VS Code settings, tasks, launch, dev containers, JetBrains. | — |
| `test-strategy` | hub · described | Load before deciding what and how to test or fixing a weak suite — levels, oracles, flakiness, mutation. | `test-contract-snapshot`*, `test-e2e-playwright`*, `test-fuzzing`*, `test-property-based`* |

### Security

| Skill | Shape · listing | Use | Modules (`*` = read by path) |
|---|---|---|---|
| `secure-coding` | hub · described | Load before writing or reviewing code with untrusted input, secrets, auth, crypto, deps or LLM tools. | `sec-authn-authz`*, `sec-crypto`*, `sec-detection`*, `sec-hardening`*, `sec-incident-response`*, `sec-llm-apps`*, `sec-secrets`*, `sec-supply-chain`*, `sec-web-vulns`* |

### Web, UI and apps

| Skill | Shape · listing | Use | Modules (`*` = read by path) |
|---|---|---|---|
| `browser-automation` | standalone · described | Use before a multi-step browser task — Chrome vs built-in browser vs Playwright, forms, downloads. | — |
| `frontend-frameworks` | standalone · name only | Use for web front ends — React 19, Next.js 16, Svelte 5, Vue, Astro, Tailwind v4, Web Vitals. | — |
| `macos-app-distribution` | standalone · name only | Use to ship a macOS app — bundles, signing, notarization, DMG, Sparkle, Homebrew casks. | — |
| `rust-native-gui` | standalone · name only | Load before building a native Rust desktop GUI — Iced 0.14 first; egui, Slint, Tauri. | — |
| `ui-design-systems` | hub · name only | Load before designing UI screens or a component library — DTCG tokens, scales, states, dark mode. | `3d-ux-design`* |
| `web-accessibility` | hub · name only | Load before building or auditing UI for accessibility — WCAG 2.2 AA, keyboard, focus, screen readers. | `a11y-aria-patterns`*, `a11y-audit`*, `a11y-docs-pdf`*, `a11y-mobile`* |

### Data, databases and statistics

| Skill | Shape · listing | Use | Modules (`*` = read by path) |
|---|---|---|---|
| `bayesian-modeling` | standalone · name only | Use for Bayesian models — PyMC, NumPyro, Stan; prior checks, R-hat/ESS, divergences, LOO. | — |
| `causal-inference` | standalone · name only | Use to estimate causal effects from observational data — DiD, event studies, IV, RD, synthetic control. | — |
| `data-analysis` | standalone · name only | Use for dataset analysis — profiling, exploratory plots, tests, effect sizes, A/B tests, power. | — |
| `data-visualization` | hub · name only | Use before making a data figure in code — chart choice, perception, palettes, labels, uncertainty. | `viz-dashboards`*, `viz-matplotlib`* |
| `dataframes-duckdb` | standalone · name only | Use to transform tabular data — pandas, polars, DuckDB, Parquet/Arrow; dtypes, joins, big files. | — |
| `db-design` | hub · described | Use to choose a database or design a schema — engines, keys, constraints, indexes from queries. | `db-migrations`*, `mongodb`, `mysql`, `postgresql`, `redis`, `sqlite` |
| `geospatial` | standalone · name only | Use for geospatial data — CRS, GDAL, GeoPandas, rasterio, PostGIS, PMTiles, MapLibre maps. | — |
| `quant-finance` | standalone · name only | Use for quant finance research — backtests, risk, portfolios, derivative and bond pricing; no orders. | — |
| `search-engines` | standalone · name only | Use for full-text or hybrid search — Elasticsearch, OpenSearch, Meilisearch, Typesense, BM25, relevance. | — |
| `time-series-forecasting` | standalone · name only | Load before forecasting a time series — rolling-origin backtests, naive baselines, ETS/ARIMA. | — |

### Machine learning and LLMs

| Skill | Shape · listing | Use | Modules (`*` = read by path) |
|---|---|---|---|
| `accelerator-perf` | standalone · name only | Load before a GPU benchmark, kernel port or speed/memory claim — environment, method, parity, profilers. | — |
| `dataset-curation` | standalone · name only | Use to build or audit training and eval datasets — licenses, PII, dedup, decontamination, splits. | — |
| `diffusion-flow-models` | standalone · name only | Use for diffusion or flow-matching models — DDPM/DDIM, rectified flow, guidance, samplers. | — |
| `distributed-training` | standalone · name only | Use to train on several GPUs or nodes — torchrun, DDP vs FSDP2, mixed precision, NCCL, JAX. | — |
| `gpu-kernel-dev` | hub · name only | Use for custom GPU kernels — Metal/MLX vs CUDA vs Triton, roofline, correctness, profiling. | `gpu-cuda`*, `gpu-metal-mlx`*, `gpu-triton`* |
| `graph-rag` | standalone · name only | Use when retrieval needs relations or multi-hop facts — Graphiti, Neo4j, LightRAG, GraphRAG. | — |
| `hf-hub` | standalone · name only | Use to find, download or publish Hugging Face models and datasets — licenses, gated repos, cache. | — |
| `image-model-pipelines` | standalone · name only | Use to run, fine-tune or evaluate open image models — diffusers, mflux, ComfyUI, LoRA. | — |
| `llm-evals` | standalone · name only | Use before reporting an LLM quality number — perplexity, harnesses, LLM-as-judge, RAG/agent evals. | — |
| `llm-finetuning` | standalone · name only | Use to plan or run an LLM fine-tune — LoRA/QLoRA, DPO, chat templates, mlx-lm, PEFT/TRL. | — |
| `llm-quantization` | standalone · name only | Use for LLM quantization — MLX mixed precision, GPTQ/AWQ, sensitivity, memory, perplexity. | — |
| `local-llm-serving` | standalone · name only | Use to run, size or benchmark local LLMs — mlx-lm, oMLX, llama.cpp, vLLM, SGLang. | — |
| `ml-experiment` | standalone · name only | Use before running or comparing models — leakage-safe splits, baselines, seeds, ablations. | — |
| `model-export` | standalone · name only | Use to export trained models — torch.export, ONNX, Core ML, ExecuTorch, TensorRT, parity. | — |
| `rag-agents` | standalone · name only | Use for RAG pipelines — chunking, embeddings, hybrid search, reranking, grounding, retrieval evals. | — |
| `tabular-ml` | standalone · name only | Load before modeling tabular data — gradient boosting, categoricals, early stopping, calibration. | — |
| `training-debug` | standalone · name only | Load when a training run misbehaves — NaN loss, divergence, no learning, plateaus, overfitting. | — |

### Science, maths and HPC

| Skill | Shape · listing | Use | Modules (`*` = read by path) |
|---|---|---|---|
| `bio-chem-computing` | hub · name only | Use for computational biology or chemistry — biosecurity rules; genomics to quantum chemistry. | `bio-genomics`*, `bio-pipelines`*, `bio-single-cell`*, `bio-structures`*, `chem-informatics`*, `chem-md`*, `chem-qm`* |
| `category-theory` | standalone · name only | Use for categorical constructions and proofs — limits, adjoints, Yoneda, monads, monoidal categories. | — |
| `hpc-computing` | hub · name only | Use for scientific and HPC code — cluster cost rules, reproducibility, MPI, SLURM, Fortran, I/O. | `hpc-fortran`*, `hpc-io`*, `hpc-mpi-openmp`*, `hpc-slurm`*, `sci-pde-fem`* |
| `lean-formalization` | standalone · name only | Use for Lean 4 and Mathlib — lake, the LSP goal loop, lemma search, tactics, soundness. | — |
| `numerical-methods` | hub · name only | Load before writing or trusting numerical code — conditioning, stability, verification, reproducibility. | `num-floating-point`*, `num-linear-algebra`*, `num-ode-sde`*, `num-quadrature-autodiff`*, `opt-modeling`* |
| `proof-craft` | standalone · name only | Load before proving, disproving or refereeing a math claim — counterexamples, strategy catalog. | — |
| `quantum-computing` | standalone · name only | Load before quantum-circuit work — derivations, simulation, hardware runs, Qiskit, Cirq, stim, QEC. | — |
| `quantum-physics-numerics` | standalone · name only | Load before simulating quantum systems beyond circuits — exact diag, Lindblad, DMRG/TEBD, QuTiP. | — |

### Infrastructure and operations

| Skill | Shape · listing | Use | Modules (`*` = read by path) |
|---|---|---|---|
| `ci-cd-pipelines` | standalone · described | Use for CI/CD workflows — GitHub/Forgejo Actions, permissions, SHA pinning, OIDC, caching, zizmor. | — |
| `container-images` | standalone · described | Use for Dockerfiles and images — multi-stage, digests, non-root, multi-arch, SBOM, hadolint, trivy. | — |
| `linux-kernel-ebpf` | standalone · name only | Use for kernel tracing and eBPF — bpftrace, bcc, libbpf CO-RE, perf, ftrace. | — |
| `linux-workstation` | hub · name only | Use for a Linux ML/dev workstation (CachyOS, Ubuntu, RTX 50) — NVIDIA, CUDA, desktop, btrfs. | `linux-nvidia-cuda` |
| `self-hosting-ops` | hub · name only | Use for personal services on a Linux box — Tailscale, Forgejo, systemd, Caddy, backups, firewalls. | `cloud-aws`, `cloud-gcp`, `k8s-ops`, `net-diagnostics`, `obs-otel`, `ops-backups`*, `ops-forgejo`*, `ops-systemd-caddy`*, `ops-tailscale`* |
| `terraform-opentofu` | standalone · name only | Load before writing or reviewing Terraform/OpenTofu — state, locking, plan/apply, modules, moved/import. | — |

### Hardware, robotics, games and audio

| Skill | Shape · listing | Use | Modules (`*` = read by path) |
|---|---|---|---|
| `3d-printing` | standalone · name only | Use for anything 3D printed (FDM, resin) — design rules, mesh repair, STL/3MF/STEP, OpenSCAD, slicers, materials. | — |
| `audio-engineering` | standalone · name only | Use for audio software — real-time DSP, plugins (JUCE, CLAP, VST3, AU), Python analysis, ear safety. | — |
| `embedded-firmware` | hub · name only | Use for firmware and hardware-near work — MCUs, RTOS, drivers, flashing safety, FPGA, PCB. | `emb-c-rtos`*, `emb-debug-flash`*, `emb-rust`*, `fpga-hdl`*, `pcb-kicad`* |
| `game-graphics` | hub · name only | Use for games and real-time graphics — frame budgets, profiling, engines, GPU APIs, netcode. | `3d-interface-engineering`*, `game-engines`*, `game-netcode`*, `gfx-apis`*, `gfx-shaders`* |
| `robot-learning` | standalone · name only | Load before training or evaluating robot policies — MuJoCo, Isaac Lab, RL, VLAs, sim-to-real. | — |
| `robotics-engineering` | standalone · name only | Load before building or debugging robot software — ROS 2, tf2, URDF, ros2_control, Nav2, MoveIt 2. | — |

### Design, images, video and 3D

| Skill | Shape · listing | Use | Modules (`*` = read by path) |
|---|---|---|---|
| `3d-animation` | hub · name only | Use for 3D character and object animation — keyframes, actions and slots, NLA, mocap retargeting, cycles, animation export. | `character-rigging`* |
| `adobe-creative-cloud` | standalone · name only | Use to script or run Photoshop, InDesign or Acrobat — UXP, ExtendScript, batchPlay, data merge, preflight. | — |
| `apparel-merch-print` | standalone · name only | Use for garment and merch art — screen print, DTG, DTF, sublimation, vinyl, embroidery. | — |
| `blender-3d` | hub · name only | Use for Blender — headless bpy, bmesh, geometry nodes, Cycles/EEVEE, exports, the Blender MCP server. | `procedural-3d-workflows`* |
| `brand-identity` | standalone · name only | Use for logos and brand identities — concepts, wordmarks, color and type systems, guidelines. | — |
| `color-management` | standalone · name only | Use to choose, convert or check colors — ICC profiles, CMYK, spot colors, ΔE2000, OKLCH, contrast. | — |
| `computer-use-apps` | standalone · described | Use before driving Adobe, ONLYOFFICE or a native app by screen — routing, screen lock, shortcuts. | — |
| `houdini-fx` | standalone · name only | Use for Houdini — VEX, HDAs, Pyro/FLIP/Vellum/RBD, caching, Solaris/Karma, hython, PDG. | — |
| `image-prompting` | standalone · described | Use before generating or editing images via image-studio — SVG and raster prompts, edits, QA, costs. | — |
| `media-ffmpeg` | standalone · described | Use before running ffmpeg or ffprobe — encodes, trims, concat, scaling, GIFs, loudnorm, subtitles. | — |
| `motion-graphics` | standalone · name only | Use for motion design — easing, timing, kinetic type, After Effects, Premiere, Lottie, Remotion. | — |
| `presentation-design` | standalone · name only | Load before designing a slide deck — narrative, one message per slide, grids, type sizes, charts. | — |
| `print-production` | standalone · name only | Load before building or checking a print file — bleed, dielines, ppi, CMYK, ink limits, spot, PDF/X. | — |
| `raster-imaging` | standalone · described | Load before resizing, converting, compositing or compressing images in code — magick, vips, Pillow. | — |
| `sculpting-texturing` | hub · name only | Load before sculpting, retopology, UVs, baking or texture painting — ZBrush, Blender, Substance. | `organic-sculpting`*, `udim-texture-painting`* |
| `svg-vector-craft` | standalone · name only | Load before creating or delivering vector files — SVG as code, svgo, tracing, plotters, cutters. | — |
| `tattoo-design` | standalone · name only | Load before drawing a tattoo — placement, ageing of detail, line weight, lettering, stencils, mockups. | — |
| `typography` | standalone · name only | Load before choosing or setting type — pairing, scale, measure, leading, kerning, OpenType, web fonts. | — |

### Writing, documents and research

| Skill | Shape · listing | Use | Modules (`*` = read by path) |
|---|---|---|---|
| `book-production` | standalone · name only | Use to make a book from a manuscript — print PDF, EPUB, DOCX, KDP/IngramSpark, cover, ISBN. | — |
| `diagrams-as-code` | standalone · described | Use for diagrams as text — Mermaid, Graphviz, D2, PlantUML, TikZ/tikz-cd; rendering, embedding. | — |
| `latex-typesetting` | hub · name only | Use for LaTeX (papers, theses, beamer, arXiv) or Typst — engines, math, biblatex, errors. | `tex-build-debug`*, `tex-math-bib`*, `typst`* |
| `literature-review` | standalone · name only | Use for paper search, bibliographies and reviews — arXiv, Semantic Scholar, OpenAlex, BibTeX. | — |
| `localization` | hub · name only | Use for i18n and translation — plurals, locales, machine-translation review, catalogs, subtitles. | `l10n-catalogs`*, `subtitles`* |
| `markdown-publishing` | standalone · name only | Use for Markdown publishing — GFM, math, Mermaid, MDX, Astro, Pandoc, link checks. | — |
| `oss-licensing` | standalone · name only | Use to choose, apply or audit open-source licences — compatibility, SPDX, REUSE, notices. | — |
| `portuguese-pt-writing` | standalone · described | Load before writing, translating or proofreading European Portuguese (pt-PT) — AO1990, PT vs BR, clitics. | — |
| `technical-writing` | hub · described | Use to draft or edit technical prose — papers, blog posts, docs, READMEs, ADRs, changelogs, reports. | `docs-sites` |
| `web-research` | standalone · described | Use before web work beyond one WebSearch — tool ladder, crawling, budgets, source quality, citations. | — |

Sources: `dot-claude/skills/*/SKILL.md` (frontmatter descriptions), `dot-claude/settings.json` (`skillOverrides`,
`skillListingBudgetFraction`, `skillListingMaxDescChars`), `tests/test_skill_modules.py` (`hubs_and_modules`,
`LISTED_CORE`, caps), `README.md` ("Skills: hubs, modules, references", "Prompt budget"), `CONFIG.md` §5 "On demand
and automatic".
