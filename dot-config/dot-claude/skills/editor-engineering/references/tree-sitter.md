# Editor engineering: tree sitter

Read when implementing syntax highlighting, folding or structure with tree-sitter (moved from `editor-engineering` SKILL.md).

## Syntax: tree-sitter
- Grammar crates export `LANGUAGE: LanguageFn` and bundled queries (`HIGHLIGHTS_QUERY`, `INJECTIONS_QUERY`): `parser.set_language(&tree_sitter_rust::LANGUAGE.into())?`. `LanguageError` means the grammar's ABI is outside the runtime's range — align crate versions and load every grammar in a test.
- Editor query sets (`folds.scm`, `indents.scm`, `textobjects.scm`, extra highlights) come from editor projects (nvim-treesitter, Helix `runtime/queries`, Zed); capture names and predicates differ between them — pick one convention, and respect their licenses.
- Incremental re-parse (edit the tree with the old coordinates, then parse from rope chunks):
```rust
fn point_at(rope: &Rope, byte: usize) -> Point {
    let row = rope.byte_to_line(byte);
    Point { row, column: byte - rope.line_to_byte(row) }       // column is in bytes
}
fn apply_edit(rope: &mut Rope, tree: &mut Tree, start: usize, end: usize, text: &str) {
    let (start_byte, old_end_byte) = (rope.char_to_byte(start), rope.char_to_byte(end));
    let (start_position, old_end_position) = (point_at(rope, start_byte), point_at(rope, old_end_byte));
    rope.remove(start..end);
    rope.insert(start, text);
    let new_end_byte = start_byte + text.len();
    tree.edit(&InputEdit { start_byte, old_end_byte, new_end_byte, start_position, old_end_position,
                           new_end_position: point_at(rope, new_end_byte) });
}
fn parse(parser: &mut Parser, rope: &Rope, old: Option<&Tree>) -> Option<Tree> {
    parser.parse_with_options(&mut |byte: usize, _: Point| -> &[u8] {
        if byte >= rope.len_bytes() { return &[]; }
        let (chunk, chunk_start, _, _) = rope.chunk_at_byte(byte);
        &chunk.as_bytes()[byte - chunk_start..]
    }, old, None)
}
// after parsing: for r in old_tree.changed_ranges(&new_tree) { invalidate highlight cache in r }
```
- Parse off the UI thread on a rope snapshot. Cancel stale parses with `ParseOptions::new().progress_callback(&mut |_: &ParseState| if stale() { ControlFlow::Break(()) } else { ControlFlow::Continue(()) })` passed as the third argument. A cancelled parse returns `None`, and the next `parse` call resumes it — call `parser.reset()` first when the text has changed since.
- Queries: `Query::new(&language, source)?`; `QueryCursor::captures`/`matches` return *streaming* iterators — bring `streaming_iterator::StreamingIterator` into scope and loop with `while let Some((m, idx)) = captures.next()`; in 0.27 `QueryMatch::captures()` is a method (older versions exposed a field). Limit work with `cursor.set_byte_range(visible_bytes)`. Built-in text predicates (`#eq?`, `#match?`, `#any-of?` and their `not-` forms) are evaluated by the cursor given a text provider; everything else is yours to apply: `#set!` directives via `query.property_settings(pattern)`, `#is?`/`#is-not?` via `property_predicates`, other predicates via `general_predicates`.
- Highlighting: map capture names (`keyword.function`, `string.special`) to theme scopes with fallback by dropping trailing segments.
- Injections (Markdown code fences, math, JS in HTML): `injections.scm` yields `@injection.content` plus `@injection.language` (or `#set! injection.language "..."`). Parse each injected language as a layer with `parser.set_included_ranges(&ranges)`; re-parse only layers whose ranges changed. Markdown in tree-sitter-md is two grammars: block `LANGUAGE` and `INLINE_LANGUAGE` (its `MarkdownParser` wraps both).
- Trees contain `ERROR`/`MISSING` nodes while the user types — highlighters, folding and indentation must tolerate them.
