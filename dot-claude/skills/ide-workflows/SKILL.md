---
name: ide-workflows
description: Use to set up dev tooling — VS Code settings, tasks, launch, dev containers, JetBrains, EditorConfig.
---
# IDE and browser developer tooling

## Scope
- VS Code, JetBrains IDEs (IntelliJ IDEA, PyCharm, CLion, RustRover, GoLand, WebStorm, DataGrip) managed by JetBrains Toolbox, and Chrome as a developer tool. Git itself lives in `git-workflows`; driving Chrome for tasks in `browser-automation`; editor internals (building an editor) in `editor-engineering`.
- Rule: project files that help everyone are committed (EditorConfig, recommended extensions, shared run configurations, code styles); personal state (window layout, local paths, tokens) never is.

## Shared ground: EditorConfig
`.editorconfig` at the repo root (`root = true`; `indent_style`, `indent_size`, `end_of_line = lf`, `charset = utf-8`, `trim_trailing_whitespace`, `insert_final_newline`, per-glob sections). Both VS Code (EditorConfig extension) and JetBrains honor it; language formatters (ruff, rustfmt, prettier, google-java-format, fourmolu) still own formatting.

## VS Code
- CLI (`code` on PATH via Command Palette → "Shell Command: Install 'code' command"): `code .`, `code -r file:line`, `code --diff a b`, `code --wait` (for `GIT_EDITOR`), `code --list-extensions --show-versions`, `code --install-extension <publisher.id>[@version]`, `--profile <name>`.
- Settings precedence: default < user < remote < workspace (`.vscode/settings.json`) < folder (multi-root). Language-scoped blocks: `"[python]": { "editor.defaultFormatter": "charliermarsh.ruff", "editor.formatOnSave": true }`.
- `.vscode/extensions.json` → `"recommendations"` (commit); `.vscode/settings.json` only with project-wide settings (formatter, test framework, interpreter path relative to `${workspaceFolder}`); no absolute personal paths.
- `tasks.json`: build/test commands with `problemMatcher` (`$tsc`, `$gcc`, `$rustc`) so errors land in Problems. `launch.json`: debugpy (`"type": "debugpy"`), `node`, CodeLLDB (`"type": "lldb"`) for Rust/C++, Java (`"type": "java"`), with `preLaunchTask` pointing at a task.
- Language servers: Python (Pylance or basedpyright), rust-analyzer, clangd (reads `compile_commands.json`; disable the Microsoft C++ IntelliSense engine to avoid two servers), Julia (LanguageServer.jl), Haskell (HLS via the Haskell extension and GHCup), Metals (Scala), Java (Red Hat extension on JDT.LS).
- Dev containers: `.devcontainer/devcontainer.json` (image or Dockerfile, `features`, `postCreateCommand`, `customizations.vscode.extensions`); CLI `devcontainer up --workspace-folder .` / `devcontainer exec`. Remote-SSH for remote Linux hosts (the NVIDIA box).
- Profiles separate extension sets (a "Data" profile vs "Rust"); Settings Sync is per user, not per project.
- The Claude Code extension and the integrated terminal share the workspace; the stack's BlackCat runs there like in the CLI.

## JetBrains (Toolbox)
- Toolbox App installs, updates and rolls back IDEs; enable Settings → Tools → "Generate shell scripts" to get launchers (`idea`, `pycharm`, `clion`, `rustrover`, `goland`, `webstorm`, `datagrip`) in the configured scripts folder (add it to PATH).
- Launcher CLI: `idea .`, `idea --line 42 file`, `idea diff a b`, `idea merge local remote base out`, `idea format -s <codestyle.xml> -r src` (headless formatter; the IDE must not be running the same config dir, or use `-allowDefaults`), `idea inspect <project> <profile.xml> <outdir> -v2` (offline inspections).
- Sharing `.idea/`: commit `codeStyles/`, `inspectionProfiles/`, `runConfigurations/` (or run configurations saved as project files under `.run/`), `dictionaries/`; ignore `workspace.xml`, `usage.statistics.xml`, `shelf/`, `dataSources.local.xml`, `httpRequests/`. JetBrains' own `.gitignore` template lists these.
- Build model: let the IDE import the real build (Gradle/Maven/sbt/Cargo/CMake/uv); delegate build and run to Gradle rather than the IDE builder so CLI and IDE agree. CLion: select the CMake preset instead of IDE-only profiles.
- CI inspections: Qodana (`qodana.yaml`, `qodana scan` in Docker or the GitHub Action) runs the same inspections as the IDE.
- Built-in MCP server (2025.2+): Settings → Tools → MCP Server exposes the running IDE (open files, run configurations, inspections, terminal) to MCP clients. Its "Auto-Configure" writes an always-connected user-scope entry into `~/.claude.json`: in this stack don't auto-configure; register it per task (mcp-broker) or project-scoped, and never pre-approve its terminal tools. The Claude Code JetBrains plugin is a separate integration (diff viewer, selection context).
- Remote development: JetBrains Gateway (IDE backend on the Linux host, thin client on the Mac).

## Chrome as a developer tool
- DevTools panels: Performance (record, Insights, long tasks, layout shifts), Lighthouse (performance, accessibility, SEO, best practices), Network (throttling, blocking, HAR export), Coverage (unused JS/CSS), Memory (heap snapshots, allocation timelines), Application (storage, service workers), Recorder (user flows exportable to Puppeteer).
- Automation and remote debugging: Chrome 136+ ignores `--remote-debugging-port` on the default profile, so always pass a separate `--user-data-dir=/tmp/chrome-debug`. Chrome for Testing gives pinned binaries (`npx @puppeteer/browsers install chrome@stable`).
- Agent access in this stack: the `chrome-devtools` catalog server (mcp-broker mounts it: headless, throwaway profile, no usage statistics) for traces, Lighthouse, network and heap work; Playwright for scripted headless flows; Claude in Chrome only when the user's logged-in sessions are needed.
- Profiles: separate Chrome profiles for development vs personal browsing; extensions skew performance measurements — measure in a clean profile or headless.

## Checklist
EditorConfig present · recommended extensions/shared run configs committed, personal state ignored · launchers and language servers match the project's toolchain versions · formatter the same in IDE, CLI and CI · no always-on IDE MCP entries at user scope.
