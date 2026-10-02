# Lean formalization: larger projects

- Blueprint:
  - Install with `uv tool install leanblueprint`; needs graphviz and libgraphviz-dev for pygraphviz.
  - Commands: `leanblueprint new`, then `pdf` | `web` | `checkdecls` | `all` | `serve`.
  - In the LaTeX, tag each node with `\lean{Decl.name}`, `\leanok`, `\uses{label}`, `\notready`,
    `\mathlibok`. The dependency graph tracks progress.
- CI: the `math` template already writes `.github/workflows/lean_action_ci.yml` (`actions/checkout`,
  then `leanprover/lean-action@v1`). It auto-detects Mathlib and its cache; inputs include `build`,
  `test`, `lint`, `mk_all-check`, `leanchecker`.
- Hygiene: `lake shake` reports unused imports (`--fix` applies the changes), `#min_imports` gives the
  minimal imports for a file, and one concept per file.
