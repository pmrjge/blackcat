# rust-native-gui — skeleton (reference)
Read when starting a new project layout. Parent: `rust-native-gui` SKILL.md.

## Project skeleton
```
app/
  Cargo.toml        # iced = { version = "0.14", features = ["tokio", "advanced", "canvas", "lazy"] } — only what is used
  src/main.rs       # iced::application(...) wiring only
  src/app.rs        # State, Message, update, view, subscription
  src/screen/*.rs   # per-screen State/Message; update returns an Action enum the parent interprets
  src/widget/*.rs   # custom widgets (advanced feature)
  src/worker/*.rs   # subscription workers: pty.rs, lsp.rs, watch.rs
  src/model/*.rs    # pure logic, no iced imports -> fast unit tests
  assets/fonts/  assets/icons/  tests/snapshots/
```
Compose screens by mapping: `self.editor.view().map(Message::Editor)` and `task.map(Message::Editor)`; the child returns an action (`None`, `Run(Task)`, `Navigate(..)`) instead of mutating the parent.
