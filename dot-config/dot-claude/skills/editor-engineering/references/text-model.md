# Text storage, positions and the editing model

Part of `editor-engineering`.

## Text storage
| Structure | Strengths | Weaknesses | Use |
|---|---|---|---|
| Rope (`ropey`) | O(log n) edits and index conversions, O(1) clone for snapshots, line/char/UTF-16 metrics | Pointer-chasing reads; chunk boundaries | Default for code editors |
| Piece table / piece tree | Edits never copy text; append-only buffers; easy mmap of the original | Needs its own line index; fragmentation | Huge files, append-heavy logs (VS Code uses a piece tree) |
| Gap buffer | Simple, fast local typing | Far-apart multi-cursor edits, snapshots | Small single-cursor widgets |
| `String` | Trivial | O(n) edits | Inputs under ~1 MB with rare edits |
- ropey 1.x indexes by `char` (Unicode scalar values): `char_to_byte`, `byte_to_char`, `line_to_char`, `char_to_line`, `char_to_utf16_cu`, `utf16_cu_to_char`, `chunk_at_byte`. `rope.clone()` is O(1) — hand snapshots to background parsing, saving and search.
- **Line breaks must match LSP.** ropey's default feature `unicode_lines` also breaks on VT, FF, NEL, U+2028, U+2029; LSP counts only `\n`, `\r\n`, `\r`. Build with `ropey = { version = "1.6", default-features = false, features = ["cr_lines", "simd"] }` or line numbers diverge from every language server.
- Loading: `Rope::from_reader` streams; detect binary (NUL in the first 8 KB); detect encoding (BOM, `chardetng`), decode with `encoding_rs` to UTF-8 internally, remember encoding and line ending (LF/CRLF) and write them back unchanged.
- Huge files (tens of MB, or a single multi-MB line): open read-only or lazily, disable syntax/LSP/soft-wrap past thresholds, never compute whole-document layout.
- Saving: write a temp file in the same directory → `fsync` → atomic `rename`; preserve permissions; resolve symlinks and write the target.

## Positions and columns
Three column spaces coexist: **bytes** (tree-sitter `Point.column`, regex offsets), **UTF-16 code units** (LSP default), **graphemes/display cells** (cursor motion, rendering).
- Position encoding negotiation: the client sends `general.positionEncodings` (e.g. `["utf-8", "utf-16"]`); the server answers `capabilities.positionEncoding`. UTF-16 is the default and every server must support it; use UTF-8 when the server picks it.
```rust
/// LSP (line, UTF-16 column) -> char index, clamped to the line content (spec: past-the-end = end of line).
fn lsp_to_char(rope: &Rope, line: u32, character: u32) -> usize {
    let line = (line as usize).min(rope.len_lines() - 1);
    let start = rope.line_to_char(line);
    let slice = rope.line(line);
    let mut len = slice.len_chars();
    while len > 0 && matches!(slice.char(len - 1), '\n' | '\r') { len -= 1; }
    let base = rope.char_to_utf16_cu(start);
    let max = rope.char_to_utf16_cu(start + len);
    rope.utf16_cu_to_char((base + character as usize).min(max))
}
fn char_to_lsp(rope: &Rope, idx: usize) -> (u32, u32) {
    let line = rope.char_to_line(idx);
    let col = rope.char_to_utf16_cu(idx) - rope.char_to_utf16_cu(rope.line_to_char(line));
    (line as u32, col as u32)
}
```
- Cursor motion by grapheme cluster (`unicode-segmentation`): `é` as e + combining accent, flags and ZWJ emoji are one step. Terminal cell width via `unicode-width` (CJK = 2, combining = 0); in a GUI measure shaped glyph advances instead.
- Tabs: keep visual column (tab stops) separate from char column; store tab width per document.
- Test fixtures: ASCII, `é` (1 UTF-16 unit), 🦀 (2 units — a surrogate pair), CRLF files, empty last line, positions past line end.

## Editing model
- Selection = `(anchor, head)` char offsets; multi-cursor = sorted `Vec<Selection>` + primary index; merge overlaps after every transaction.
- Transaction = ChangeSet (retain/delete/insert over the old text) + resulting selections + metadata (time, origin: typing, paste, LSP edit, formatter, undo). Apply atomically; map every stored position (selections, marks, diagnostics, inlay hints, breakpoints) through the ChangeSet with an explicit bias for inserts at the same offset.
- Multi-cursor edits form one ChangeSet (build it over the original text); applying separate edits front-to-back shifts offsets.
- Undo: store inverse ChangeSets; group typing bursts (time gap or cursor jump ends a group). Linear stacks lose redo branches; an undo tree keeps them (support "earlier/later" by time).
- LSP edits: all `TextEdit`s in one array refer to the document *before* any of them — convert them into one ChangeSet (or apply in descending position order). Check the document version on `WorkspaceEdit`s and drop edits computed against an older version.
- Collaboration only: CRDTs (`yrs`, `automerge`, `loro`); single-user editors don't need them.
