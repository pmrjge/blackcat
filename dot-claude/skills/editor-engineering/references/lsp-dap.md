# LSP and DAP clients

Part of `editor-engineering`.

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
- Adapters: CodeLLDB (`codelldb`, TCP port argument), lldb-dap (LLVM, stdio), debugpy (`uv run python -m debugpy.adapter`, stdio), Delve (`dlv dap` listening on a TCP address). Launch-config fields are adapter-specific — read each adapter's docs.
