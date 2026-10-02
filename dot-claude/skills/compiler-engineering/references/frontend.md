# Compiler front ends

Baseline: `compiler-engineering`.

## Tools
- tree-sitter 0.27.0 (incremental parsing for editors and tooling) — Verified 2026-10-02 https://github.com/tree-sitter/tree-sitter/releases/latest
- ANTLR 4.13.2 (LL(*) parser generator, many target languages) — Verified 2026-10-02 https://github.com/antlr/antlr4/releases/latest
- Rust: logos (lexers), chumsky/winnow/nom (combinators), lalrpop (LR(1)), rowan (lossless syntax trees à la rust-analyzer); Python: lark; Haskell: megaparsec; OCaml: menhir. Versions per project lockfile.

## Choosing a parsing approach
| need | approach |
|---|---|
| production language with great errors | hand-written recursive descent + Pratt (precedence climbing) for expressions |
| IDE features (incremental, error-tolerant, syntax highlighting) | tree-sitter grammar or a lossless CST (rowan-style) with an incremental reparse strategy |
| DSL or config language, quick | combinator library or lark |
| existing formal grammar, many target languages | ANTLR or an LR generator |

## Lexing
- Tokens carry kind + span (byte offsets), not copies of text; keep trivia (whitespace, comments) when a formatter or IDE needs it.
- Unicode: identifiers per UAX #31 (XID_Start/XID_Continue) if allowed; normalize (NFC) or reject confusables deliberately; source is UTF-8 with errors reported, not panicked on.
- Literals: numeric overflow and escape validation reported as diagnostics with spans.
- Modes for string interpolation, nested comments, heredocs.

## Parsing rules
- Grammar written down (EBNF) and kept in sync with tests; ambiguity resolved explicitly (dangling else, generics vs comparison `a < b > c`).
- Pratt parser: binding powers table for prefix/infix/postfix operators; associativity encoded in the right binding power; precedence documented in one place.
- Error recovery: synchronize at statement/item boundaries (`;`, `}`, keywords), insert missing tokens when unambiguous, produce `Error` nodes so later phases continue; cap cascades (one error per span).
- Never recurse unbounded on user input: depth limits or explicit stacks (deeply nested parentheses are a classic crash/DoS).
- AST vs CST: CST (lossless) for formatters/IDEs, AST (semantic) for compilation; lower CST → AST in one place.
- Interning identifiers (symbol tables with IDs) and arena-allocating nodes for speed and stable references.

## Diagnostics
- Primary span + secondary labels + notes + suggestion (machine-applicable when safe); codes for each error kind with docs.
- Libraries: ariadne/codespan-reporting/miette (Rust), or the LSP `Diagnostic` shape for editors.
- Test diagnostics as golden files from small bad inputs; one test per error code.

## tree-sitter specifics
`tree-sitter generate`, `tree-sitter test` (corpus tests in `test/corpus/*.txt`), `tree-sitter parse file --debug`; external scanners (C) for context-sensitive tokens; queries (`highlights.scm`, `locals.scm`, `tags.scm`) tested with `tree-sitter query`; conflicts declared explicitly with `conflicts` and precedence (`prec.left/right/dynamic`).

## Pitfalls
Byte vs char vs UTF-16 offsets mixed (LSP uses UTF-16 by default unless negotiated); spans lost during desugaring; recursion limits missing; error recovery that loops without consuming input; grammar changes without updating golden tests; keywords that break existing identifiers.

## Verify
Parser golden tests and round-trip tests (parse → print → parse equals) pass · fuzzing the parser finds no panics, hangs or stack overflows · error-recovery tests show a useful first diagnostic and no cascade · tree-sitter corpus tests green where used.
