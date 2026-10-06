<!-- markdownlint-disable MD013 MD033 MD060 -->
# Agents

57 agent files in `dot-claude/agents/`: BlackCat, the main thread, and 56 specialists. The tables below were
generated from each file's frontmatter (`model`, `effort`, `maxTurns`, `tools`, `mcpServers`, `description`) and
from the guard's spawn table (`agent_guard.py --print-policy`) on `main` at `6ecb003`; regenerate them rather
than editing them by hand when an agent changes.

| Fact | Value | Where it is set |
|---|---|---|
| Model aliases | 43 `opus`, 14 `sonnet` | `model:`; `tests/lint_agents.py` rejects any other value; the IDs come from `stack.env` |
| Effort | binds only when the agent runs as a subagent; the main thread uses the session's level | `effort:` |
| `maxTurns` | at most 350; under 200 except orchestrator, main-coder and ninja-coder | `maxTurns:`; lint caps |
| Permission mode | 46 `acceptEdits` (every agent with Write, Edit or NotebookEdit except BlackCat, plus toolsmith), 11 none | `permissionMode:`; lint's `permission_mode_problem` |
| Leaves | 16 agents with no Agent tool | `POLICY` rows that are empty |
| Read-only Bash | code-reviewer, security-auditor, verifier, plan-reviewer, claude-code-guide, proof-checker | `READONLY_TYPES` in `agent_guard.py` |
| Running children | 3 per agent unless named in `STACK_MAX_FANOUT_BY_TYPE` | `settings.json` `env` |

How to read the tables:

- **Built-in tools** is the agent's `tools:` line without its MCP entries; an agent cannot use a tool it was not
  given. **MCP servers** are the `mcp__<server>` entries of the same line; bold ones are declared inline in the
  agent's `mcpServers` and start and stop with it; the others are user-scope (exa, jina, wolfram, huggingface,
  wandb) or built into Claude Code (computer-use, claude-in-chrome).
- **May spawn** is the agent's `POLICY` row: the only types it may start. A leaf has no Agent tool. BlackCat may
  dispatch every specialist; the orchestrator every specialist but itself.
- **Running children** is the hook's fan-out cap for that agent. The model column shows the alias family; the
  effective model ID is whatever `stack.env` pins.

## Roster

### Role agents (19)

| Agent | Model · effort · maxTurns | Built-in tools | MCP servers (tools line; **inline**) | May spawn (`POLICY`) | Running children |
|---|---|---|---|---|---|
| `blackcat`<br>BlackCat, main thread: only delegates. Classifies each ask, dispatches specialists or the orchestrator, relays results; runs no commands, edits nothing. | Sonnet · medium · — | Agent(56 types), SendMessage, AskUserQuestion, ExitPlanMode, TaskStop, ListAgents, ToolSearch, Skill, Workflow, CronCreate, CronDelete, CronList, ScheduleWakeup, RemoteTrigger, PushNotification, SendUserFile, Read | — | every specialist (56) | 24 tool calls per prompt (`BLACKCAT_MAX_STEPS`) |
| `orchestrator`<br>Multi-specialist coordination: decomposes dependent work, dispatches in parallel, verifies, integrates. | Opus · high · 200 | Agent, SendMessage, TaskStop, Read, Write, Edit, Bash, Skill | **neural-memory** | every specialist but itself (55) | 32 |
| `planner`<br>Plans before building: requirements, options and trade-offs, steps with owners, risks, verification. Read-only. | Opus · xhigh · 60 | Read, Glob, Grep, WebSearch, WebFetch, ToolSearch, Skill, SendMessage, Agent | exa, jina, **libdocs** | scout, explore, claude-code-guide | 8 |
| `plan-reviewer`<br>Plan critique against the goal, code and current docs: wrong assumptions, missing steps, risks. Read-only. | Opus · high · 60 | Read, Bash, WebSearch, WebFetch, ToolSearch, Skill | **libdocs**, exa, jina | leaf (no Agent tool) | — |
| `oracle`<br>Timeless knowledge from expertise: concepts, definitions, history, how things work. No web; current facts go to scout. | Opus · low · 12 | Read, Skill | — | leaf (no Agent tool) | — |
| `scout`<br>Fast lookup of one current fact: price, version, release, date, role holder, status; short cited answer. | Sonnet · low · 11 | WebSearch, WebFetch, Read, ToolSearch, Skill | exa, jina | leaf (no Agent tool) | — |
| `explore`<br>Read-only codebase search: files, symbols, call sites, configs, conventions, with path:line; quick to thorough. | Sonnet · low · 40 | Read, Grep, Glob, LSP, Skill | — | leaf (no Agent tool) | — |
| `researcher`<br>Deep research: multi-source investigations, comparisons, literature, market and technical reviews; cited synthesis. | Opus · high · 130 | WebSearch, WebFetch, Read, Write, Bash, ToolSearch, Skill, SendMessage, Agent, Artifact | exa, jina, **spider**, huggingface, **neural-memory**, **context-mode** | scout, doc-specialist, mathematician, data-engineer, data-scientist, mcp-broker | 4 |
| `coder`<br>Small/medium code tasks: scripts, fixes, features in known areas, configs, tests; a leaf. Language-heavy work goes to <lang>-engineer. | Sonnet · medium · 170 | Read, Write, Edit, Bash, LSP, NotebookEdit, WebSearch, WebFetch, ToolSearch, Skill, Monitor, TaskStop | **libdocs**, exa | leaf (no Agent tool) | — |
| `main-coder`<br>Serious code: large or unfamiliar codebases, architecture, systems, performance, hard bugs, merges that won't fast-forward. | Opus · xhigh · 350 | Read, Write, Edit, Bash, LSP, NotebookEdit, WebSearch, WebFetch, ToolSearch, Skill, Monitor, TaskStop, SendMessage, Agent, EnterWorktree, ExitWorktree | **libdocs**, exa, jina, **neural-memory** | coder, explore, scout, verifier, code-reviewer, security-auditor, plan-reviewer, mlx-engineer, cuda-engineer, ml-engineer, dl-engineer, llm-engineer, mcp-broker, claude-code-guide, ninja-coder, test-engineer, build-fixer, security-engineer, toolsmith, rust-engineer, haskell-engineer, julia-engineer, go-engineer, python-engineer, jvm-engineer, node-engineer | 6 |
| `ninja-coder`<br>Hardest code: novel algorithms, correctness proofs, complexity, numerical stability, concurrency, kernels; after main-coder fails. | Opus · max · 300 | Read, Write, Edit, Bash, LSP, NotebookEdit, WebSearch, WebFetch, ToolSearch, Skill, Monitor, TaskStop, SendMessage, Agent, EnterWorktree, ExitWorktree, Workflow | **libdocs**, exa, jina, wolfram, **neural-memory** | main-coder, coder, mathematician, explore, scout, verifier, code-reviewer, security-auditor, researcher, mlx-engineer, cuda-engineer, ml-engineer, dl-engineer, llm-engineer, mcp-broker, quantum-engineer, proof-checker, test-engineer, build-fixer, toolsmith, rust-engineer, haskell-engineer, julia-engineer, go-engineer, python-engineer, jvm-engineer, node-engineer | 5 |
| `code-reviewer`<br>Code review of diffs, PRs or codebases: correctness, design, tests, performance; patch-ready findings. Read-only. | Opus · high · 80 | Read, Bash, LSP, WebSearch, WebFetch, ToolSearch, Skill | **libdocs** | leaf (no Agent tool) | — |
| `verifier`<br>Independent verification: runs tests and builds, reproduces bugs, re-checks facts, numbers and files. Never fixes. | Sonnet · high · 140 | Read, Bash, LSP, WebSearch, WebFetch, ToolSearch, Skill | exa, jina, **playwright**, computer-use | leaf (no Agent tool) | — |
| `security-auditor`<br>Security review: threat models, vulnerable code, authN/authZ, injection, secrets, CVEs, supply chain. Read-only. | Opus · xhigh · 100 | Read, Bash, LSP, WebSearch, WebFetch, ToolSearch, Skill | exa | leaf (no Agent tool) | — |
| `proof-checker`<br>Proof refereeing: proofs, derivations, correctness and complexity arguments; counterexamples, Lean 4 checks. Read-only. | Opus · xhigh · 80 | Read, Bash, WebFetch, ToolSearch, Skill | wolfram, **lean** | leaf (no Agent tool) | — |
| `browser-operator`<br>Web page actions: logged-in sites via Claude in Chrome, headless Playwright; forms, flows, downloads, screenshots, JS pages. | Sonnet · medium · 120 | Read, Write, WebFetch, ToolSearch, Skill | claude-in-chrome, **playwright** | leaf (no Agent tool) | — |
| `mcp-broker`<br>MCP servers on demand through magg: finds, vets, mounts and runs a tool no agent has; permanent adds and audits on request. | Sonnet · medium · 60 | Read, Write, Edit, Bash, WebSearch, WebFetch, ToolSearch, Skill | **magg** | leaf (no Agent tool) | — |
| `claude-code-engineer`<br>Claude Code configuration: skills, subagents, hooks, plugins, MCP entries, permissions, settings, CLAUDE.md and rules. | Opus · high · 150 | Read, Write, Edit, Bash, WebSearch, WebFetch, ToolSearch, Skill, SendMessage, Agent | — | claude-code-guide, scout, explore, verifier, code-reviewer, mcp-broker | 3 |
| `claude-code-guide`<br>Claude Code, Agent SDK and Claude API answers from the official docs: setup, hooks, skills, MCP, tools, agents. Read-only. | Sonnet · low · 30 | Read, Bash, WebFetch, WebSearch, ToolSearch, Skill | — | leaf (no Agent tool) | — |

### Language engineers (7)

| Agent | Model · effort · maxTurns | Built-in tools | MCP servers (tools line; **inline**) | May spawn (`POLICY`) | Running children |
|---|---|---|---|---|---|
| `rust-engineer`<br>Rust: idiomatic crates and workspaces, async, unsafe/FFI, cargo, clippy, nextest, releases; self-checked. | Opus · high · 170 | Read, Write, Edit, Bash, LSP, WebFetch, ToolSearch, Skill, Monitor, TaskStop, SendMessage, Agent | **libdocs** | coder, explore, scout, verifier, code-reviewer, test-engineer, build-fixer, mcp-broker | 3 |
| `haskell-engineer`<br>Haskell: GHCup, cabal or stack, types and laziness, space leaks, hspec/QuickCheck, hlint, ormolu; self-checked. | Opus · high · 170 | Read, Write, Edit, Bash, LSP, WebFetch, ToolSearch, Skill, Monitor, TaskStop, SendMessage, Agent | **libdocs** | coder, explore, scout, verifier, code-reviewer, test-engineer, build-fixer, mcp-broker | 3 |
| `julia-engineer`<br>Julia: juliaup, Pkg environments, type-stable code, Test, JET, Aqua, BenchmarkTools, GPU arrays; self-checked. | Opus · high · 170 | Read, Write, Edit, Bash, LSP, NotebookEdit, WebFetch, ToolSearch, Skill, Monitor, TaskStop, SendMessage, Agent | **libdocs** | coder, explore, scout, verifier, code-reviewer, test-engineer, build-fixer, mcp-broker | 3 |
| `go-engineer`<br>Go: modules, concurrency, the go toolchain, golangci-lint, race-tested suites, govulncheck; self-checked. | Opus · high · 170 | Read, Write, Edit, Bash, LSP, WebFetch, ToolSearch, Skill, Monitor, TaskStop, SendMessage, Agent | **libdocs** | coder, explore, scout, verifier, code-reviewer, test-engineer, build-fixer, mcp-broker | 3 |
| `python-engineer`<br>Python on uv: packaging, typing, pytest, asyncio, profiling, ruff, pyright or mypy; self-checked. | Opus · high · 170 | Read, Write, Edit, Bash, LSP, NotebookEdit, WebFetch, ToolSearch, Skill, Monitor, TaskStop, SendMessage, Agent | **libdocs** | coder, explore, scout, verifier, code-reviewer, test-engineer, build-fixer, mcp-broker, data-engineer | 3 |
| `jvm-engineer`<br>JVM, Java first, plus Kotlin and Scala: Gradle or Maven, JUnit, JMH, JFR, GC tuning; self-checked. | Opus · high · 170 | Read, Write, Edit, Bash, LSP, WebFetch, ToolSearch, Skill, Monitor, TaskStop, SendMessage, Agent | **libdocs** | coder, explore, scout, verifier, code-reviewer, test-engineer, build-fixer, mcp-broker | 3 |
| `node-engineer`<br>Node.js and TypeScript backends and CLIs: pnpm, tsc, ESLint or Biome, Vitest, ESM. Browser UI goes to frontend-engineer. | Opus · high · 170 | Read, Write, Edit, Bash, LSP, WebFetch, ToolSearch, Skill, Monitor, TaskStop, SendMessage, Agent | **libdocs** | coder, explore, scout, verifier, code-reviewer, test-engineer, build-fixer, mcp-broker | 3 |

### Domain experts (28)

| Agent | Model · effort · maxTurns | Built-in tools | MCP servers (tools line; **inline**) | May spawn (`POLICY`) | Running children |
|---|---|---|---|---|---|
| `biochem-engineer`<br>Computational biology and chemistry: Nextflow/Snakemake, genomics, single-cell, protein structures, RDKit, MD, QM. | Opus · high · 170 | Read, Write, Edit, Bash, LSP, WebFetch, ToolSearch, Skill, Monitor, TaskStop, SendMessage, Agent | **libdocs** | coder, explore, scout, researcher, verifier, data-scientist, dl-engineer, cuda-engineer, mcp-broker, python-engineer | 3 |
| `cg-artist`<br>3D generalist: Blender modeling, hard surface, UVs, baking, PBR texturing, rendering, 3D printing. Houdini goes to vfx-td. | Opus · medium · 150 | Read, Write, Edit, Bash, WebSearch, WebFetch, ToolSearch, Skill, Monitor, TaskStop, SendMessage, Agent | **blender**, **libdocs**, jina, computer-use | image-director, coder, scout, verifier, mcp-broker, vfx-td, rigger-animator, sculptor-painter, procedural-3d-ui | 3 |
| `cuda-engineer`<br>NVIDIA GPU systems: CUDA and Triton kernels, PyTorch CUDA performance, NCCL, multi-GPU, Nsight, remote hosts, Kaggle. | Opus · high · 190 | Read, Write, Edit, Bash, LSP, NotebookEdit, WebSearch, WebFetch, ToolSearch, Skill, Monitor, TaskStop, SendMessage, Agent, EnterWorktree, ExitWorktree | **libdocs**, exa, jina | coder, explore, scout, verifier, code-reviewer, mathematician, mcp-broker, ninja-coder | 3 |
| `data-engineer`<br>Data and databases: SQL, schemas, safe migrations, query plans, indexes, ETL, DuckDB, pandas/polars. | Sonnet · high · 150 | Read, Write, Edit, Bash, LSP, NotebookEdit, WebSearch, WebFetch, ToolSearch, Skill, Monitor, TaskStop, SendMessage, Agent | **libdocs**, exa, **postgres**, **mongodb** | coder, explore, scout, verifier, mathematician, data-scientist, doc-specialist, mcp-broker, test-engineer | 3 |
| `data-scientist`<br>Statistics for decisions: EDA, tests, effect sizes, A/B tests, regression, causal inference, forecasting, Bayesian models. | Opus · high · 150 | Read, Write, Edit, Bash, NotebookEdit, WebSearch, WebFetch, ToolSearch, Skill, Monitor, TaskStop, SendMessage, Agent, Artifact | **libdocs**, exa, jina, huggingface, **neural-memory** | data-engineer, ml-engineer, mathematician, coder, explore, scout, verifier, doc-specialist, writer, mcp-broker | 3 |
| `designer`<br>Visual design: logos, brand identity, illustration, layout, print, packaging, UI visuals, type and color; Adobe apps. | Opus · high · 150 | Read, Write, Edit, Bash, WebSearch, WebFetch, ToolSearch, Skill, SendMessage, Agent | **image-studio**, **illustrator**, **huetension**, jina, computer-use | image-director, scout, mcp-broker, cg-artist | 3 |
| `devops-engineer`<br>Infrastructure and delivery: CI/CD, containers, Kubernetes, Terraform, cloud, sysadmin, deploys, observability; dry-runs first. | Sonnet · high · 140 | Read, Write, Edit, Bash, LSP, WebSearch, WebFetch, ToolSearch, Skill, Monitor, TaskStop, SendMessage, Agent | **libdocs**, exa | coder, explore, scout, verifier, security-auditor, mcp-broker, security-engineer, build-fixer, toolsmith | 3 |
| `dl-engineer`<br>Deep learning: architectures, diffusion and flow models, image-model pipelines, PyTorch/JAX/MLX training, NaN debugging. | Opus · high · 190 | Read, Write, Edit, Bash, LSP, NotebookEdit, WebSearch, WebFetch, ToolSearch, Skill, Monitor, TaskStop, SendMessage, Agent, EnterWorktree, ExitWorktree | **libdocs**, exa, jina, huggingface, wandb, **neural-memory** | mlx-engineer, cuda-engineer, data-engineer, coder, explore, scout, researcher, verifier, code-reviewer, mathematician, mcp-broker, ninja-coder | 3 |
| `doc-specialist`<br>Office documents and PDFs: reads, extracts, interprets, creates and edits .docx/.xlsx/.pptx/.pdf, scans, tables, forms. | Sonnet · medium · 100 | Read, Write, Edit, Bash, WebFetch, ToolSearch, Skill, SendMessage, Agent | **markitdown**, computer-use, **context-mode** | scout, mcp-broker | 3 |
| `embedded-engineer`<br>Firmware: MCUs in C/Rust (Zephyr, ESP-IDF, embassy), RTOS, drivers, probes, FPGA/HDL, KiCad; simulates before flashing. | Opus · high · 170 | Read, Write, Edit, Bash, LSP, WebFetch, ToolSearch, Skill, Monitor, TaskStop, SendMessage, Agent | **libdocs** | coder, explore, scout, verifier, code-reviewer, test-engineer, build-fixer, mcp-broker, rust-engineer | 3 |
| `frontend-engineer`<br>Web front end: HTML/CSS, TypeScript, React/Vue/Svelte/Astro, design-to-code, responsive layout, accessibility, performance. | Opus · medium · 170 | Read, Write, Edit, Bash, LSP, WebSearch, WebFetch, ToolSearch, Skill, Monitor, TaskStop, SendMessage, Agent, Artifact | **libdocs**, exa, **playwright** | coder, explore, scout, verifier, code-reviewer, designer, image-director, mcp-broker, test-engineer, build-fixer, node-engineer | 3 |
| `game-engineer`<br>Games and real-time graphics: Godot, Unity, Unreal, Bevy; Vulkan/Metal/WebGPU, shaders, frame time, netcode. | Opus · high · 170 | Read, Write, Edit, Bash, LSP, WebFetch, ToolSearch, Skill, Monitor, TaskStop, SendMessage, Agent | **libdocs**, computer-use | coder, explore, scout, verifier, code-reviewer, cg-artist, test-engineer, build-fixer, mcp-broker, rust-engineer, rigger-animator | 3 |
| `hpc-engineer`<br>HPC and scientific code: PDE/FEM/CFD solvers, MPI/OpenMP, Fortran, SLURM, HDF5, convergence and scaling studies. | Opus · high · 170 | Read, Write, Edit, Bash, LSP, WebFetch, ToolSearch, Skill, Monitor, TaskStop, SendMessage, Agent | **libdocs** | coder, explore, scout, verifier, mathematician, ninja-coder, cuda-engineer, build-fixer, mcp-broker, julia-engineer | 3 |
| `image-director`<br>Image generation and editing via image-studio: SVG logos, icons, illustrations, photos, raster, composites, series. | Opus · medium · 80 | Read, Write, Edit, Bash, WebSearch, WebFetch, ToolSearch, Skill | **image-studio**, jina | leaf (no Agent tool) | — |
| `llm-engineer`<br>LLMs: local serving, quantization, fine-tuning, evals, RAG, embeddings, agents and tool use, chat templates. | Opus · high · 190 | Read, Write, Edit, Bash, LSP, NotebookEdit, WebSearch, WebFetch, ToolSearch, Skill, Monitor, TaskStop, SendMessage, Agent, EnterWorktree, ExitWorktree | **libdocs**, exa, jina, huggingface, wandb, **neural-memory** | mlx-engineer, cuda-engineer, dl-engineer, data-scientist, coder, explore, scout, researcher, verifier, code-reviewer, mathematician, mcp-broker, claude-code-guide, ninja-coder | 3 |
| `mathematician`<br>Maths and physics, quick to research-level: proofs, derivations, symbolic and numeric computation, mechanics, QM. | Opus · xhigh · 100 | Read, Write, Edit, Bash, WebSearch, WebFetch, ToolSearch, Skill, SendMessage, Agent | jina, wolfram, **neural-memory** | scout, mcp-broker, quantum-engineer, proof-checker | 3 |
| `ml-engineer`<br>Classical ML: tabular, time-series and NLP models, gradient boosting, features, validation, tuning, calibration, MLOps. | Opus · high · 190 | Read, Write, Edit, Bash, LSP, NotebookEdit, WebSearch, WebFetch, ToolSearch, Skill, Monitor, TaskStop, SendMessage, Agent, EnterWorktree, ExitWorktree | **libdocs**, exa, jina, huggingface, wandb, **neural-memory** | data-scientist, data-engineer, coder, explore, scout, verifier, code-reviewer, mathematician, mcp-broker | 3 |
| `mlx-engineer`<br>Apple Silicon ML performance: MLX and mlx-lm internals, Metal kernels, Core ML/ANE, memory tuning, MPS, ports to MLX. | Opus · high · 190 | Read, Write, Edit, Bash, LSP, NotebookEdit, WebSearch, WebFetch, ToolSearch, Skill, Monitor, TaskStop, SendMessage, Agent, EnterWorktree, ExitWorktree | **libdocs**, exa, jina | coder, explore, scout, verifier, code-reviewer, mathematician, mcp-broker, ninja-coder | 3 |
| `mobile-engineer`<br>Mobile apps: Swift/SwiftUI, Kotlin/Compose, Flutter, React Native; builds, simulators, UI tests, signing, releases. | Opus · medium · 170 | Read, Write, Edit, Bash, LSP, WebFetch, ToolSearch, Skill, Monitor, TaskStop, SendMessage, Agent | **libdocs**, **mobilebuild** | coder, explore, scout, verifier, code-reviewer, designer, test-engineer, build-fixer, mcp-broker | 3 |
| `motion-designer`<br>Motion graphics and video: After Effects, animation, expressions, kinetic type, Premiere edits and exports, timing. | Opus · medium · 150 | Read, Write, Edit, Bash, WebSearch, WebFetch, ToolSearch, Skill, SendMessage, Agent | **after-effects**, **premiere**, computer-use | image-director, designer, scout, mcp-broker, cg-artist, vfx-td, rigger-animator | 3 |
| `procedural-3d-ui`<br>Procedural 3D and 3D interfaces: Geometry Nodes, Unreal PCG, three.js/WebGPU viewports, gizmos, spatial UI/UX, XR. Houdini goes to vfx-td. | Opus · high · 150 | Read, Write, Edit, Bash, WebSearch, WebFetch, ToolSearch, Skill, Monitor, TaskStop, SendMessage, Agent | **blender**, **libdocs**, jina | coder, explore, scout, verifier, code-reviewer, mcp-broker, vfx-td, frontend-engineer, game-engineer, designer | 3 |
| `quantum-engineer`<br>Quantum computing and physics in code: Qiskit, PennyLane, Cirq, stim, QuTiP, tensor networks, noise, QEC, IBM Quantum. | Opus · high · 160 | Read, Write, Edit, Bash, LSP, NotebookEdit, WebSearch, WebFetch, ToolSearch, Skill, Monitor, TaskStop, SendMessage, Agent | **libdocs**, exa, jina, wolfram, **neural-memory** | mathematician, coder, explore, scout, researcher, verifier, code-reviewer, cuda-engineer, mlx-engineer, mcp-broker, ninja-coder, proof-checker | 3 |
| `rigger-animator`<br>3D character rigging and animation: skeletons, IK/FK, skin weights, shape keys, facial rigs, keyframe and mocap, engine export. | Opus · medium · 150 | Read, Write, Edit, Bash, WebSearch, WebFetch, ToolSearch, Skill, Monitor, TaskStop, SendMessage, Agent | **blender**, **libdocs**, jina, computer-use | coder, scout, verifier, mcp-broker, cg-artist, vfx-td | 3 |
| `robotics-engineer`<br>Robotics: ROS 2, Nav2, MoveIt 2, ros2_control, kinematics, control, estimation, SLAM, simulation, robot learning, bring-up. | Opus · high · 190 | Read, Write, Edit, Bash, LSP, NotebookEdit, WebSearch, WebFetch, ToolSearch, Skill, Monitor, TaskStop, SendMessage, Agent, EnterWorktree, ExitWorktree | **libdocs**, exa, jina, huggingface, wandb, **neural-memory** | coder, explore, scout, researcher, verifier, code-reviewer, mathematician, dl-engineer, cuda-engineer, mlx-engineer, cg-artist, mcp-broker, ninja-coder, embedded-engineer | 3 |
| `sculptor-painter`<br>Organic sculpting and 3D painting: anatomy, creatures, ZBrush and Blender sculpt, retopology, UDIM texturing in Substance, Mari, Blender. | Opus · medium · 150 | Read, Write, Edit, Bash, WebSearch, WebFetch, ToolSearch, Skill, Monitor, TaskStop, SendMessage, Agent | **blender**, **libdocs**, jina, computer-use | image-director, coder, scout, verifier, mcp-broker, cg-artist | 3 |
| `security-engineer`<br>Security builds: audit fixes with proofs, hardening, fuzzing, detection rules, dependency fixes. Reviews go to security-auditor. | Opus · high · 150 | Read, Write, Edit, Bash, LSP, WebFetch, ToolSearch, Skill, Monitor, TaskStop, SendMessage, Agent | **libdocs** | coder, explore, scout, verifier, security-auditor, test-engineer, mcp-broker | 3 |
| `vfx-td`<br>Houdini FX: SOP/DOP/LOP, VEX, HDAs, Pyro/FLIP/Vellum/RBD sims, caching, Solaris/Karma, PDG; hython and husk. | Opus · high · 170 | Read, Write, Edit, Bash, Monitor, TaskStop, WebSearch, WebFetch, ToolSearch, Skill, SendMessage, Agent | jina, computer-use | coder, scout, verifier, mcp-broker | 3 |
| `writer`<br>Prose writing and editing: articles, Markdown with LaTeX and Mermaid, explanations, emails, copy, pt-PT/EN translation. | Opus · medium · 80 | Read, Write, Edit, Glob, Grep, WebSearch, WebFetch, ToolSearch, Skill, SendMessage, Agent, Artifact | jina | scout, researcher, mathematician | 3 |

### Helpers (3)

| Agent | Model · effort · maxTurns | Built-in tools | MCP servers (tools line; **inline**) | May spawn (`POLICY`) | Running children |
|---|---|---|---|---|---|
| `test-engineer`<br>Tests: writes and repairs unit, property, fuzz and e2e tests, each proven on a seeded bug; never changes product code. | Sonnet · medium · 100 | Read, Write, Edit, Bash, LSP, ToolSearch, Skill, Monitor, TaskStop | — | leaf (no Agent tool) | — |
| `build-fixer`<br>Red builds to green: format, lint, type and compile errors, behaviour-neutral edits proven by the failing command. | Sonnet · low · 60 | Read, Edit, Bash, LSP, ToolSearch, Skill | — | leaf (no Agent tool) | — |
| `toolsmith`<br>Installs and manages CLI tools and packages for other agents (brew, uv, npm, pnpm, cargo, go): vetted, pinned, ledgered. | Sonnet · medium · 60 | Read, Bash, Skill | — | leaf (no Agent tool) | — |

## Newest agents

| Agent | Added | Why |
|---|---|---|
| `rigger-animator` | 2026-10-05 | Character rigging and 3D animation; same tools and inline servers (blender, libdocs) as cg-artist; spawned by BlackCat, the orchestrator, cg-artist, game-engineer and motion-designer |
| `sculptor-painter` | 2026-10-05 | Organic sculpting and UDIM texture painting; cg-artist's tools; spawned by BlackCat, the orchestrator and cg-artist |
| `procedural-3d-ui` | 2026-10-05 | Procedural 3D (Geometry Nodes, PCG) and 3D app UI/UX; no computer use, editor GUI work goes to game-engineer; spawned by BlackCat, the orchestrator and cg-artist |
| `toolsmith` | 2026-10-06 | The dependency installer: a Sonnet leaf with Read, Bash and Skill whose Bash runs only `bin/stack-install` ([Toolsmith](Toolsmith.md)); spawned by BlackCat, the orchestrator, main-coder, ninja-coder and devops-engineer |

The three 3D agents also brought skills: the hub `3d-animation` (module `character-rigging`), and modules under
`sculpting-texturing`, `blender-3d`, `ui-design-systems` and `game-graphics` ([Skills](Skills.md)). They are not
in the read gate's visual exemption list (`READ_GATE_EXEMPT_VISUAL`).

## Retired agents

Kept here so old names are recognisable in history and reports: `supreme-coder` (retired 2026-10-04; ninja-coder
is the top tier), `db-engineer` (folded into data-engineer) and `localizer` (into coder and writer), both
2026-10-04, and the copy types `researcher-copy` and `coder-copy` (2026-10-04). A spawn of any of them is an
unknown type and is refused.

## Routing in one paragraph

BlackCat answers greetings and setup questions, reads the ledger, and dispatches everything else in one burst per
prompt. Knowledge goes oracle (timeless, no web) < scout (one current fact) < researcher (synthesis); code goes
coder (a leaf) < main-coder < ninja-coder; codebase questions go to explore; language-heavy work to the language
engineer; domain builds to the domain expert; checks to code-reviewer, verifier, security-auditor or
proof-checker; installs to toolsmith; Claude Code configuration to claude-code-engineer and questions about it to
claude-code-guide; a tool nobody has to mcp-broker. Dependent multi-specialist work goes to the orchestrator.

Sources: `dot-claude/agents/*.md` (frontmatter and "May spawn" sentences), `agent_guard.py --print-policy`,
`dot-claude/settings.json` (`env`), `tests/lint_agents.py`, `README.md` ("Roster", "Agent tiers and routing"),
`CONFIG.md` §3, §4 and §9 (2026-10-04, 2026-10-05, 2026-10-06 entries).
