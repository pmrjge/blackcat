---
name: codemods
description: Use when changing many call sites mechanically — ast-grep, LibCST, jscodeshift, OpenRewrite.
---
# Codemods (automated large-scale edits)

## Scope
Syntax-aware rewrites across a codebase: API migrations, renames, deprecations, pattern fixes. Dependency upgrades that trigger them: `dep-upgrades`. Git mechanics for large branches: `git-workflows`.

## Choose the lightest tool that is syntax-aware
| Change | Tool |
|---|---|
| Rename a symbol in a typed language | the language server's rename (LSP) or IDE refactoring |
| Pattern → replacement across languages | ast-grep (structural patterns with metavariables `$A`, YAML rules for repeatable fixes) |
| Python, preserving formatting and comments | LibCST codemods (Bowler-style matchers on a concrete syntax tree) |
| JavaScript/TypeScript | jscodeshift transforms, or ts-morph for type-aware edits |
| Java/Kotlin framework migrations | OpenRewrite recipes |
| Lint-driven fixes | the linter's autofix (`ruff check --fix`, `cargo clippy --fix`, `eslint --fix`, Semgrep autofix) |
| Rust edition and lint migrations | `cargo fix` |

Regex `sed` is acceptable only for unambiguous text (string constants, config keys) and must be followed by a build and a grep for leftovers.

## Procedure
1. Write down the before/after pattern with 3–5 real examples, including the awkward ones (comments, macros, multi-line calls, aliases, re-exports, dynamic access).
2. Write the transform plus tests on fixtures (input → expected output), including cases it must leave alone.
3. Dry-run on the whole repository; review a sample of the diff and count matches vs expected occurrences (`rg -c`); list the files it skipped or could not parse.
4. Apply in reviewable batches (by directory or package), each with formatter, build, type check and tests green; commit the transform script with the change.
5. Handle the residue by hand and say so; add a lint rule or CI check that prevents the old pattern from coming back.

## Pitfalls
- Text-based tools miss aliased imports and hit matches in strings and comments.
- Formatting churn hides the real change: run the formatter in a separate commit first.
- Generated code and vendored directories: exclude or regenerate, never hand-edit.
- Public APIs: keep a deprecated shim for one release when external users exist (`api-design`).

## Verify
- [ ] Transform tests pass; dry-run match count equals the expected occurrence count (or differences explained).
- [ ] Build, type check and full test suite green after each batch.
- [ ] A grep or lint rule shows zero remaining instances of the old pattern.

## Sources
- Verified 2026-10-02 https://github.com/ast-grep/ast-grep/releases/latest — ast-grep 0.45.3; https://pypi.org/pypi/libcst/json — LibCST 1.9.0; https://registry.npmjs.org/jscodeshift/latest — jscodeshift 17.4.0.
- Unverified as of 2026-10-02: CLI syntax for ast-grep (`ast-grep run -p … -r … -l …`), OpenRewrite goals, ts-morph — check each tool's docs before scripting.
