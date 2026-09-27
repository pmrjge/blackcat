---
name: julia-engineering
description: Load before writing, reviewing, testing or speeding up Julia — juliaup and versions, Pkg environments and Manifest pinning, package layout, Test/Aqua/JET, type stability and allocations, BenchmarkTools, threads and GPUs (CUDA.jl, Metal.jl), SciML, Makie, PythonCall, precompilation and PackageCompiler, pitfalls.
---
# Julia engineering

## Scope and baseline
- Covers Julia projects, packages and scripts. Numerical method choice lives in `numerical-methods`; quantum-physics packages in `quantum-physics-numerics`; profiling method in `cpu-performance`.
- Versions (endoflife.date, Sep 2026): 1.13 is current (Sep 2026), 1.12 the previous release, **1.10 the LTS**. Re-check with `juliaup status` and https://julialang.org/downloads before pinning a `[compat] julia` bound.
- Install and switch with **juliaup** (`brew install juliaup` or `curl -fsSL https://install.julialang.org | sh`): `juliaup add lts`, `juliaup default release`, `julia +lts --version`, `juliaup update`. Never mix a Homebrew `julia` formula with juliaup.

## Environments (Pkg)
| Task | Command |
|---|---|
| New package | `julia -e 'using Pkg; Pkg.generate("MyPkg")'`, or PkgTemplates.jl for CI, docs and formatter config |
| Activate project | `julia --project=.` (or `--project=@.` to search upward); in the REPL `] activate .` |
| Add / remove | `] add DataFrames`, `] add Foo@1.2`, `] rm Foo`, `] dev ../Local` |
| Reproduce | `julia --project=. -e 'using Pkg; Pkg.instantiate()'` (installs exactly what Manifest.toml lists) |
| Test | `julia --project=. -e 'using Pkg; Pkg.test()'` (runs `test/runtests.jl` in a sandbox with `[extras]`/test deps) |
| Update | `] up` (within `[compat]`), `] status --outdated` |
- Commit `Manifest.toml` for applications and analyses (exact reproduction); for registered packages commit only `Project.toml` with `[compat]` entries for every dependency (the General registry requires them).
- Keep the global environment (`@v1.x`) almost empty: only dev tools (Revise, BenchmarkTools, JET). Project deps go in the project.
- Workspaces (`[workspace]` in Project.toml, 1.12+) share one manifest across a package and its test/docs environments; check the Pkg docs of your version before relying on it.

## Layout and tooling
- `src/MyPkg.jl` (module), `test/runtests.jl`, `docs/` (Documenter.jl), `benchmark/` (BenchmarkTools suite or AirspeedVelocity.jl).
- Revise.jl in `~/.julia/config/startup.jl` for interactive work; never in package code.
- Format with JuliaFormatter.jl (`format(".")`, `.JuliaFormatter.toml`) or Runic.jl — follow what the repo already uses.
- Quality: Aqua.jl (ambiguities, unbound type parameters, piracy, stale deps), JET.jl (`@report_call`, `@report_opt` for type instabilities), ExplicitImports.jl.
- CI: `julia-actions/setup-julia`, `julia-actions/cache`, `julia-actions/julia-buildpkg`, `julia-actions/julia-runtest`; test on `lts`, `1` and `pre` if the package promises support.
- Editor: the VS Code Julia extension (LanguageServer.jl); see `ide-workflows`.

## Performance rules (in order)
1. **No untyped globals** in hot code: pass arguments, or `const`. Put work in functions — top-level code is not compiled the same way.
2. **Type stability**: `@code_warntype f(x)` (red `Any`/`Union` = problem) or `JET.@report_opt f(x)`. Common causes: a variable that changes type, abstract container eltypes (`Vector{Any}`, `Vector{Real}`), abstract struct fields (parametrize: `struct S{T<:Real}; x::T; end`), closures capturing reassigned variables (Core.Box).
3. **Allocations**: `@time` / `@allocated`; preallocate and mutate (`mul!`, `ldiv!`, `.=`), `@views` for slices (slices copy by default), fuse broadcasts (`@. y = a*x + b`), StaticArrays.jl for small fixed-size vectors.
4. **Measure properly**: BenchmarkTools `@btime f($x)` / `@benchmark` — interpolate globals with `$`, the first call includes compilation.
5. Column-major memory: loop the first index innermost. `@inbounds` only after the indexing is proven correct (`--check-bounds=yes` in tests); `@simd` for reductions you accept reassociating.
6. Threads: start with `julia -t auto`; `Threads.@threads` for loops, `Threads.@spawn` for tasks; avoid shared mutable state (per-task buffers, not `threadid()`-indexed buffers — task migration makes those wrong). Distributed.jl for multi-process.
7. GPUs: KernelAbstractions.jl for portable kernels; Metal.jl on Apple Silicon (Float32 only, no Float64), CUDA.jl on NVIDIA. Disallow scalar indexing (`CUDA.allowscalar(false)`) to catch slow paths.

## Ecosystem picks (check activity on JuliaHub/GitHub before adopting)
- Scientific ML and ODE/SDE/DAE: DifferentialEquations.jl / OrdinaryDiffEq.jl, ModelingToolkit.jl, Optimization.jl; stiff problems need a stiff solver (Rodas5P, FBDF, KenCarp4) — see `numerical-methods`.
- Optimization modeling: JuMP.jl (+ HiGHS, Ipopt, Gurobi). Autodiff: ForwardDiff.jl (few inputs), Enzyme.jl and Zygote.jl (reverse), DifferentiationInterface.jl to switch backends.
- Deep learning: Lux.jl (explicit parameters) or Flux.jl; for serious DL training prefer the Python/MLX stack unless the project is Julia.
- Data: DataFrames.jl, CSV.jl, Arrow.jl, Tables.jl. Plots: Makie (CairoMakie for vector PDF/SVG output, GLMakie interactive), Plots.jl.
- Linear algebra: LinearAlgebra (BLAS threads: `BLAS.set_num_threads`; avoid oversubscription with Julia threads), SparseArrays, KrylovKit.jl, Arpack.jl. AppleAccelerate.jl can swap in Accelerate's BLAS on macOS.
- Tensor networks and quantum: ITensors.jl/ITensorMPS.jl, QuantumOptics.jl, QuantumToolbox.jl.
- Python interop: PythonCall.jl / juliacall (preferred over PyCall.jl); CondaPkg.jl manages Python deps per project.

## Latency and deployment
- Time-to-first-X: PrecompileTools.jl `@compile_workload` in packages; watch invalidations (SnoopCompile.jl).
- Apps and sysimages: PackageCompiler.jl (`create_app`, `create_sysimage`). Small standalone binaries via `juliac`/`--trim` are experimental (1.12+) — verify on your version.
- Scripts: `#!/usr/bin/env -S julia --project=@. --startup-file=no`.

## Pitfalls
- 1-based indexing; use `eachindex`, `axes`, `firstindex`/`lastindex` so OffsetArrays work.
- `Int` overflow wraps silently (`2^64 == 0`); use `BigInt`, `Int128` or checked arithmetic (`Base.checked_mul`). `/` on integers returns Float64; `÷` is integer division.
- `b = a` aliases arrays; `copy`/`deepcopy` when you mean a copy. Mutating functions end in `!` by convention — keep it.
- Global-scope soft-scope rules differ between the REPL and files; wrap scripts in `function main() … end; main()`.
- Type piracy (adding methods to Base functions for Base types) and method ambiguities break other packages — Aqua catches both.
- Floating-point reductions under `@simd`/threads are not bit-reproducible; compare with `isapprox` and a tolerance you can justify.
- `Pkg.update()` in a shared environment silently changes others' results — update in the project, commit the Manifest.

## Review checklist
Manifest committed (apps) or `[compat]` complete (packages) · tests run with `Pkg.test()` · JET/Aqua clean · hot paths type-stable and allocation-free as claimed (show `@btime` numbers) · no globals in hot code · threads safe · versions and Julia channel reported.
