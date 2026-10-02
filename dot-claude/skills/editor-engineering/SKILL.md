---
name: editor-engineering
description: Use for editor internals or IDE features — ropes, undo, tree-sitter, LSP/DAP, terminals.
---
# Editor engineering

## Scope
- Engine-level design for code/text editors and IDE features, Rust-first. UI toolkit wiring is in `rust-native-gui`, general Rust practice in `rust-engineering`, profiling method in `cpu-performance`.
- Versions checked (Sep 2026): ropey 1.6 (2.0 in beta), tree-sitter 0.27, LSP spec 3.18 (current), lsp-types 0.97, portable-pty 0.9, alacritty_terminal 0.26, vte 0.15, notify 8.2 (9.0 in RC), notify-debouncer-full 0.7, ignore 0.4, grep-searcher 0.1, pulldown-cmark 0.13. The Rust snippets below compiled and ran against these. Check docs.rs (or `mcp__libdocs`) before relying on other APIs.

## Architecture
Buffer (text + history) → Document (path, encoding, line ending, syntax tree, diagnostics, LSP version) → View (scroll, selections, wrap cache) → Renderer. Services run on their own tasks: syntax, one LSP client per server, DAP, watcher, search, terminals. Every edit is a **transaction** applied in one place, which then notifies listeners (syntax `tree.edit`, LSP `didChange`, decoration/diagnostic position mapping, undo history) — no component mutates text directly.

## Text storage, positions, editing model
Read `references/text-model.md` when choosing the buffer structure (rope, piece table), converting between byte, UTF-16 and grapheme columns, or designing selections, transactions and undo.

## Syntax: tree-sitter
Read `references/tree-sitter.md` when implementing syntax highlighting, folding or structure with tree-sitter.

## LSP and DAP clients
Read `references/lsp-dap.md` when writing an LSP or DAP client (framing, lifecycle, position encodings, sessions, breakpoints).

## Integrated terminal
Read `references/terminal.md` when building the integrated terminal.

## Rendering
- Pipeline: shape visible lines (cosmic-text / harfrust / rustybuzz) → cache shaped runs keyed by (line text hash, style spans, font size, wrap width) → rasterize glyphs into a GPU atlas (glyphon/cryoglyph for wgpu, swash) → instanced quads.
- Damage tracking: redraw changed lines; scroll by offsetting and drawing only revealed lines; a blinking caret redraws one rect.
- Smooth scrolling: fractional pixel offsets; use the OS momentum phases on macOS trackpads, don't add a second inertia.
- Soft wrap computed lazily for the visible region, cached per (line, width); estimate total height for the scrollbar until lines are measured.
- Text quality: advanced shaping for ligatures, font fallback chain for emoji/CJK, subpixel positioning; macOS has no subpixel (LCD) antialiasing — use grayscale AA.

## Files, watching and search
Read `references/files-search.md` when implementing file loading, watching or search.

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
