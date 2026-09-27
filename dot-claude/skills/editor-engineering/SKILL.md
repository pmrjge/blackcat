---
name: editor-engineering
description: Load before building text or code editor internals or IDE features — rope and piece-table storage, UTF-8/UTF-16/grapheme column conversion, selections, multi-cursor, undo and transactions, tree-sitter incremental parsing and queries, LSP and DAP clients, integrated terminal (PTY, VT parsing), GPU text rendering, file watching, project search, keymaps, Markdown/LaTeX preview, WASM plugins and latency budgets.
---
# Editor engineering

## Scope
- Engine-level design for code/text editors and IDE features, Rust-first. UI toolkit wiring is in `rust-native-gui`, general Rust practice in `rust-engineering`, profiling method in `cpu-performance`.
- Versions checked (Sep 2026): ropey 1.6 (2.0 in beta), tree-sitter 0.27, LSP spec 3.18 (current), lsp-types 0.97, portable-pty 0.9, alacritty_terminal 0.26, vte 0.15, notify 8.2 (9.0 in RC), notify-debouncer-full 0.7, ignore 0.4, grep-searcher 0.1, pulldown-cmark 0.13. The Rust snippets below compiled and ran against these. Check docs.rs (or `mcp__libdocs`) before relying on other APIs.

## Architecture
Buffer (text + history) → Document (path, encoding, line ending, syntax tree, diagnostics, LSP version) → View (scroll, selections, wrap cache) → Renderer. Services run on their own tasks: syntax, one LSP client per server, DAP, watcher, search, terminals. Every edit is a **transaction** applied in one place, which then notifies listeners (syntax `tree.edit`, LSP `didChange`, decoration/diagnostic position mapping, undo history) — no component mutates text directly.

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

## LSP client
- Transport: spawn the server with piped stdin/stdout (stderr → log); frames are `Content-Length: <bytes>\r\n\r\n<UTF-8 JSON>`; JSON-RPC 2.0 requests, responses, notifications.
- Lifecycle: `initialize` (processId, workspaceFolders, client capabilities incl. `general.positionEncodings`) → `initialized` → `textDocument/didOpen` per open document → ... → `shutdown` → `exit`; kill after a timeout. On crash: restart with backoff and re-send `didOpen` for open documents.
- Answer server→client requests or the server stalls: `workspace/configuration`, `client/registerCapability`, `window/workDoneProgress/create`, `workspace/applyEdit`, `window/showMessageRequest`.
- Sync per `textDocumentSync.change`: Incremental → ordered range edits in the negotiated encoding; Full → whole text (debounce). Increment the version on every change; send `didSave`/`didClose`.
- Features: completion (+ `completionItem/resolve`, snippets, `textEdit` over `insertText`, re-query when `isIncomplete`), hover (Markdown `MarkupContent`), signature help, diagnostics (push `publishDiagnostics` and pull `textDocument/diagnostic`), code actions (+ resolve, `WorkspaceEdit`, `workspace/executeCommand`), rename (`prepareRename`), formatting, semantic tokens (decode the relative 5-integer groups with the server's legend; full/delta/range), inlay hints (+ refresh requests), definition/references, document/workspace symbols, folding ranges.
- Cancellation and staleness: send `$/cancelRequest` for superseded requests (completion per keystroke, hover on mouse move); drop replies with `RequestCancelled` (-32800) or `ContentModified` (-32801); tag each response with the document version it answers and discard stale ones.
- Rust crates: `lsp-types` (check it covers the 3.18 features you need), `async-lsp` (tower-based client/server), `lsp-server` (rust-analyzer's transport). `tower-lsp` has had no release since 0.20 (2023) — new servers use the community `tower-lsp-server` fork.
| Language | Server (launch) |
|---|---|
| Rust | rust-analyzer (`rustup component add rust-analyzer`) |
| Python | basedpyright (`basedpyright-langserver --stdio`), pyright (`pyright-langserver --stdio`), ty (`ty server`, beta), pyrefly (`pyrefly lsp`); `ruff server` for lint/format |
| TypeScript/JS | TS 7 native `tsc --lsp --stdio`; `typescript-language-server --stdio` or vtsls (TS 6 tsserver) — Vue/Svelte/Astro tooling still needs TS 6 |
| C/C++ | clangd (needs `compile_commands.json`: CMake `-DCMAKE_EXPORT_COMPILE_COMMANDS=ON`, or `bear -- make`) |
| Java | jdtls (Eclipse JDT LS; Java 21+ runtime; unique `-data <dir>` per workspace) |
| Haskell | haskell-language-server (`haskell-language-server-wrapper --lsp`; via ghcup, must match GHC) |
| Zig | zls (version must match the Zig toolchain) |
| Julia | LanguageServer.jl (`using LanguageServer; runserver()` in a dedicated environment) |
| Others | gopls, lua-language-server, texlab (LaTeX), marksman (Markdown), tinymist (Typst), taplo (TOML), yaml-language-server, bash-language-server |

## DAP client
- Same `Content-Length` framing; messages carry `seq`; request/response/event.
- Session: `initialize` → `launch` or `attach` → wait for the `initialized` event → `setBreakpoints` (per source, full list each time), `setFunctionBreakpoints`, `setExceptionBreakpoints` → `configurationDone`. Don't block on the `launch` response before configuring; some adapters reply only after `configurationDone`.
- Stopped: `stopped` event → `threads` → `stackTrace` → `scopes` → `variables` (lazy via `variablesReference`) → `continue`/`next`/`stepIn`/`stepOut` → `terminated`/`exited` → `disconnect`.
- Reverse requests: `runInTerminal` (run the debuggee in your terminal panel), `startDebugging` (child sessions).
- Adapters: CodeLLDB (`codelldb`, TCP port argument), lldb-dap (LLVM, stdio), debugpy (`python -m debugpy.adapter`, stdio), Delve (`dlv dap` listening on a TCP address). Launch-config fields are adapter-specific — read each adapter's docs.

## Integrated terminal
```rust
let pair = native_pty_system().openpty(PtySize { rows: 24, cols: 80, pixel_width: 0, pixel_height: 0 })?;
let mut cmd = CommandBuilder::new_default_prog();     // user's login shell
cmd.env("TERM", "xterm-256color");
let mut child = pair.slave.spawn_command(cmd)?;
drop(pair.slave);                                      // parent keeps only the master side
let reader = pair.master.try_clone_reader()?;          // blocking Read: own thread -> channel
let writer = pair.master.take_writer()?;               // keystrokes / pastes
pair.master.resize(PtySize { rows: 40, cols: 120, pixel_width: 0, pixel_height: 0 })?; // on view resize
```
- Terminal state: `alacritty_terminal` (grid + VT handling + tty/event loop; Zed's terminal builds on it) or the lower-level `vte` parser (implement `Perform`: `print`, `execute`, `csi_dispatch`, `esc_dispatch`, `osc_dispatch`) over your own grid.
- Must handle: alternate screen, scrollback cap, bracketed paste, mouse reporting modes, wide/combining characters, true color, OSC 8 hyperlinks, OSC 133 prompt marks; treat OSC 52 clipboard writes as a permission.
- Flood control: read continuously, but cap bytes parsed per frame and redraw at display rate (`yes`, `cat bigfile`); render damaged lines only.
- Keys: map to escape sequences per mode (application cursor keys); Option-as-Meta setting on macOS.

## Rendering
- Pipeline: shape visible lines (cosmic-text / harfrust / rustybuzz) → cache shaped runs keyed by (line text hash, style spans, font size, wrap width) → rasterize glyphs into a GPU atlas (glyphon/cryoglyph for wgpu, swash) → instanced quads.
- Damage tracking: redraw changed lines; scroll by offsetting and drawing only revealed lines; a blinking caret redraws one rect.
- Smooth scrolling: fractional pixel offsets; use the OS momentum phases on macOS trackpads, don't add a second inertia.
- Soft wrap computed lazily for the visible region, cached per (line, width); estimate total height for the scrollbar until lines are measured.
- Text quality: advanced shaping for ligatures, font fallback chain for emoji/CJK, subpixel positioning; macOS has no subpixel (LCD) antialiasing — use grayscale AA.

## Files, watching and search
- Watching: `notify::recommended_watcher` (FSEvents on macOS, inotify on Linux) + `notify-debouncer-full` (coalesces bursts, tracks renames). Editors save via rename or truncate, so treat every event as "maybe changed" and compare mtime/size/hash before reloading. Skip ignored dirs (`target/`, `node_modules/`, `.git/objects`); Linux inotify limits (`fs.inotify.max_user_watches`); `PollWatcher` for network filesystems.
- External change: clean buffer → reload and keep cursors by diff-mapping (`imara-diff`, `similar`); dirty buffer → conflict prompt.
- Project search (ripgrep's crates):
```rust
let matcher = RegexMatcher::new_line_matcher(r"fn\s+main")?;
WalkBuilder::new(root).build_parallel().run(|| {             // honors .gitignore/.ignore, hidden files
    let (tx, matcher, cancelled) = (tx.clone(), matcher.clone(), cancelled.clone()); // cancelled: Arc<AtomicBool>
    let mut searcher = SearcherBuilder::new()
        .binary_detection(BinaryDetection::quit(b'\x00')).line_number(true).build();
    Box::new(move |entry| {
        let Ok(entry) = entry else { return WalkState::Continue };
        if !entry.file_type().is_some_and(|t| t.is_file()) { return WalkState::Continue; }
        let path = entry.path().to_path_buf();
        let _ = searcher.search_path(&matcher, &path, UTF8(|lnum, line| {
            let _ = tx.send((path.clone(), lnum, line.to_string()));
            Ok(true)
        }));
        if cancelled.load(Ordering::Relaxed) { WalkState::Quit } else { WalkState::Continue }
    })
});
```
  Stream hits to the UI in batches; cancel on a new query via the shared flag; cap results.

## Keybindings, commands, configuration
- Command registry: `CommandId` → handler + title + context predicate + default keys. Keymaps are layered (defaults → mode → view → user); support chords with timeouts; letters bind to logical keys, positional bindings to physical keys; Cmd is primary on macOS. Report conflicts. The command palette fuzzy-matches registry titles.
- Config: TOML via serde with `deny_unknown_fields`, a schema version, and a JSON Schema (`schemars`) for completion in the config file; hot-reload on change. Themes map scope names to styles.

## Markdown and LaTeX preview
- Parse with `pulldown-cmark` (enable `Options::ENABLE_MATH`, tables, task lists; math arrives as `Event::InlineMath`/`Event::DisplayMath`; `into_offset_iter()` gives source ranges for editor↔preview scroll sync) or `comrak` (full GFM, AST).
| Math rendering | Trade-off |
|---|---|
| Webview preview (wry/Tauri) + KaTeX or MathJax | Best fidelity, least code; costs a webview |
| MathJax → SVG (out of process) → `resvg` → texture cache keyed by (TeX, size, color) | Native look, full LaTeX math; needs a JS runtime |
| Typst math (`typst-svg`/`typst-render`) | Pure Rust, high quality; Typst syntax — LaTeX converters are partial |
| `pulldown-latex` → MathML | Lightweight; needs a MathML renderer |
- LaTeX documents: texlab (LSP + build via latexmk) and a PDF viewer with SyncTeX forward/inverse search; engine and build choices are in `latex-typesetting`.
- Preview renders untrusted content: sanitize HTML (`ammonia`) or disable raw HTML; no remote loads without consent.

## Plugins (WASM)
- `wasmtime` with the component model/WIT (Zed's approach) or `extism` (simpler host SDK). Expose a narrow, versioned capability API (read buffer, register command, add decorations); no ambient filesystem/network; bound runaway guests with epoch interruption or fuel; call plugins off the UI thread with timeouts.
- Prefer language support as data (grammar + queries + LSP config) over code.
- A JIT runtime inside a hardened-runtime macOS app needs a runtime exception entitlement — see `macos-app-distribution`, and test the signed build.

## Performance budgets and measurement
- Sensible targets: keystroke → pixels within one frame at the display rate (16.7 ms at 60 Hz, 8.3 ms at 120 Hz), no dropped frames while scrolling, first paint of a 1 MB file well under 100 ms with syntax arriving asynchronously, LSP/search/parse never on the input path.
- Instrument with `tracing` spans: key event received → transaction applied → layout → frame submitted → frame presented (use the platform's presentation timestamp when available). Report p50/p95/p99 over ≥ 1000 keystrokes per scenario.
- End-to-end: screen-capture latency tools (e.g. Typometer) or a high-speed camera; Instruments (Time Profiler, Metal System Trace) on macOS; `perf`/samply/Tracy on Linux (`cpu-performance`).
- Stress corpus: 100k-line source file, 10 MB single-line minified JSON, mixed RTL/CJK/emoji text, 5k-file repository search, terminal flood (`yes | head -n 1000000`).

## Verify
- Property tests (proptest): random edit sequences → apply then undo all == original; ChangeSet compose/invert round-trips; selection mapping invariants; UTF-16 ↔ char round-trips on generated Unicode.
- Incremental parse equals a fresh parse: after random edits, compare `root_node().to_sexp()` of the incremental tree with a full re-parse.
- LSP: record/replay JSON-RPC transcripts in tests; smoke-test real servers (rust-analyzer, basedpyright) in CI.
- Latency table on the stress corpus, before and after changes.

## Deliverables / Report
- Module layout and data-flow sketch; test results (property, parser-equivalence, LSP replay); latency table (p50/p95/p99 per scenario with hardware and display rate); language support matrix (grammar, queries, LSP server, DAP adapter); known limitations.
