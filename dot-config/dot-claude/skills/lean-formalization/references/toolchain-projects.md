# Lean formalization: toolchain and projects

1. Install elan, the toolchain manager: `brew install elan-init` on macOS, or
   `curl https://elan.lean-lang.org/elan-init.sh -sSf | sh -s -- -y --default-toolchain none`.
   Each project's `lean-toolchain` then selects its own Lean.
2. New project depending on Mathlib: `lake +stable new my_project math`, then `cd my_project`.
   - The `math` template writes `lean-toolchain` (e.g. `leanprover/lean4:v4.34.1`) and a
     `lakefile.toml` that requires Mathlib's tag for that toolchain:
     ```toml
     [[require]]
     name = "mathlib"
     scope = "leanprover-community"
     rev = "v4.34.1"
     ```
   - It then clones Mathlib; Mathlib's post-update hook downloads the prebuilt cache.
   - Expect about 8 GB on disk.
3. After cloning an existing project, or after any manifest change: `lake exe cache get`. It is
   idempotent; `lake exe cache get!` re-downloads every linked file.
   - If Lake starts compiling thousands of `Mathlib.*` files, stop: the toolchain does not match
     Mathlib's, or the cache is missing.
4. Commit `lean-toolchain`, `lakefile.toml` and `lake-manifest.json` together; the manifest pins exact
   commits.
5. Add `autoImplicit = false` under `[leanOptions]`, as Mathlib itself does. With the default (true), a
   typo in a signature silently becomes a universally quantified variable.
6. Check one file: `lake env lean MyProject/Foo.lean` (or `lake lean MyProject/Foo.lean`). Build the
   default targets: `lake build`.
   - In scratch files import specific modules (`import Mathlib.Analysis.SpecialFunctions.Exp`): a bare
     `import Mathlib` costs memory and load time.
   - `object file … does not exist` means the module path is wrong (or renamed), or the cache is
     incomplete.
7. Update Mathlib safely:
   1. Start from a clean git tree and note the current `lean-toolchain` and Mathlib `rev`.
   2. Set `rev` to the target tag, e.g. `"v4.35.0"`. To track master, drop `rev` and fetch the
      toolchain:
      `curl -L https://raw.githubusercontent.com/leanprover-community/mathlib4/master/lean-toolchain -o lean-toolchain`.
   3. `lake update mathlib`. Lake rewrites the manifest and bumps `lean-toolchain` to Mathlib's if that
      is newer, restarting itself through elan; Mathlib's hook then fetches the new cache.
   4. `lake build`, then fix fallout: follow the deprecation warnings, and search renamed lemmas (§3).
      Projects with an all-imports root file: `lake exe mk_all && lake build`.
   5. Commit the three files together, or `git checkout` them back if the fallout is too large.
   - Projects using leanblueprint or doc-gen update with `lake -R -Kenv=dev update`.
