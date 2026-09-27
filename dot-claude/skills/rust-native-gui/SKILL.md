---
name: rust-native-gui
description: Load before building or changing a native desktop GUI in Rust — Iced 0.14 first (Elm architecture, Task and Subscription, background workers for PTY/LSP, custom, canvas and shader widgets, theming, fonts, large-content performance, shortcuts, multi-window, headless tests), macOS specifics, and when egui, Slint, Tauri or gpui fit better.
---
# Native desktop GUI in Rust (Iced first)

## Scope and version
- Code here is verified against **iced 0.14.0** (released 2025-12-07; still the latest on crates.io in Sep 2026; edition 2024, MSRV 1.88; wgpu renderer with tiny-skia software fallback; text via cosmic-text; winit 0.30). The samples below compiled and the tests ran with it.
- The API changed a lot between releases: 0.13 replaced the `Application`/`Sandbox` traits with the `iced::application(...)` builder (Program API); 0.14 made the boot function the first argument of `iced::application` (no `run_with`), replaced `keyboard::on_key_press` with `keyboard::listen()`, renamed `Widget::on_event` to `Widget::update` (returns `()`, uses `Shell`), and made `canvas::Program::update` return `Option<canvas::Action>`. If a project pins another version, read that version's docs.rs pages and the `examples/` directory at the matching git tag before writing code; never mix APIs across versions.
- Not here: editor internals (`editor-engineering`), general Rust practice (`rust-engineering`), bundling/signing/notarizing (`macos-app-distribution`).

## Choosing the toolkit
| Need | Pick | Trade-offs |
|---|---|---|
| Custom-drawn app with rich state (editor, IDE-like tool, data viewer) | **Iced** | Pure Rust, Elm architecture, reactive redraws, headless test harness. Pre-1.0 (breaking releases), no native menus/dialogs (use `muda`, `rfd`), thin docs — the examples are the documentation |
| Internal tools, debug panels, quick visualizers | **egui/eframe** (0.36) | Immediate mode: fastest to write; UI code runs every frame and layout is decided while drawing (some layouts need extra passes); custom look and advanced text editing take work |
| Declarative UI language, designer-friendly, embedded + desktop | **Slint** (1.x) | `.slint` DSL with live preview; licensing is GPL-3.0 **or** royalty-free license (conditions) **or** commercial — check before shipping closed source |
| Existing web UI/components, HTML/CSS skills | **Tauri 2** | System webview (WKWebView/WebView2/WebKitGTK): small binaries but rendering differs per OS; UI in JS/TS + IPC to Rust |
| Zed-class GPU performance, willing to track upstream | **gpui** (Apache-2.0) | crates.io releases (0.2.x) lag the Zed repo, so projects pin a git revision; sparse docs, API churn; macOS backend is the most mature |
Also: Dioxus (React-like; webview desktop, native renderer still maturing), Xilem/Masonry (experimental), Makepad.

## Elm architecture in Iced 0.14
- `State` (plain struct), `Message` (`Clone + Debug` enum), `update(&mut self, Message) -> Task<Message>` (may return `()`), `view(&self) -> Element<'_, Message>` (pure, cheap, no I/O), `subscription(&self) -> Subscription<Message>` (declarative: return what should be running now; identity decides start/stop).
```rust
use iced::widget::{column, scrollable, text, text_editor};
use iced::{Element, Fill, Font, Subscription, Task, Theme, keyboard, window};

fn main() -> iced::Result {
    iced::application(App::boot, App::update, App::view) // boot: Fn() -> State or -> (State, Task)
        .title(App::title)                                 // &'static str or Fn(&State) -> String
        .subscription(App::subscription)
        .theme(App::theme)                                 // Fn(&State) -> Theme / Option<Theme> (None = follow system)
        .default_font(Font::MONOSPACE)
        .window_size((1200.0, 800.0))
        .run()
}

#[derive(Default)]
struct App { content: text_editor::Content, log: Vec<String>, dirty: bool }

#[derive(Debug, Clone)]
enum Message { Edit(text_editor::Action), Save, Saved(Result<(), String>), Worker(WorkerEvent) }

impl App {
    fn boot() -> (Self, Task<Message>) { (Self::default(), Task::none()) }
    fn title(&self) -> String { format!("editor{}", if self.dirty { " *" } else { "" }) }
    fn theme(&self) -> Theme { Theme::TokyoNight }

    fn update(&mut self, message: Message) -> Task<Message> {
        match message {
            Message::Edit(action) => { self.dirty |= action.is_edit(); self.content.perform(action); Task::none() }
            Message::Save => Task::perform(save(self.content.text()), Message::Saved),
            Message::Saved(result) => { if result.is_ok() { self.dirty = false; } Task::none() }
            Message::Worker(event) => { self.on_worker(event); Task::none() }
        }
    }

    fn view(&self) -> Element<'_, Message> {
        let editor = text_editor(&self.content).on_action(Message::Edit).height(Fill);
        let log = scrollable(column(self.log.iter().map(|l| text(l).into())));
        column![editor, log.height(200)].into()
    }

    fn subscription(&self) -> Subscription<Message> {
        Subscription::batch([
            keyboard::listen().filter_map(shortcut),                 // fn item: closures here must not capture
            Subscription::run(worker).map(Message::Worker),
            window::close_requests().map(|_id| Message::Save),
        ])
    }
}

fn shortcut(event: keyboard::Event) -> Option<Message> {
    match event {
        keyboard::Event::KeyPressed { key, modifiers, .. }
            if modifiers.command() && key.as_ref() == keyboard::Key::Character("s") => Some(Message::Save),
        _ => None,
    }
}
```
- Tasks: `Task::perform(future, Message::X)`, `Task::future`, `Task::run(stream, f)`, `Task::batch`, `.chain`, `.then`, `.map`, `.discard()`, `.abortable()` (returns a handle to cancel), `iced::exit()`. Widget operations are tasks too: `iced::widget::operation::{focus, focus_next, snap_to_end}` with string ids (`.id("log")`).
- Executor: the default is a thread pool. Enable the `tokio` feature when tasks/workers use tokio APIs (process, net, time) or `iced::time::every` (it needs `tokio` or `smol`); otherwise they panic with "there is no reactor running".

## Long-running workers (PTY, LSP, file watcher)
A worker is a `Subscription::run(fn)` stream that hands the app a command `Sender` first, then streams events:
```rust
use iced::futures::{SinkExt, StreamExt, channel::mpsc};

#[derive(Debug, Clone)]
enum WorkerEvent { Ready(mpsc::Sender<Command>), Line(String), Exited(Option<i32>) }
#[derive(Debug, Clone)]
enum Command { Run(String) }

fn worker() -> impl iced::futures::Stream<Item = WorkerEvent> {
    iced::stream::channel(100, async |mut output: mpsc::Sender<WorkerEvent>| {
        use tokio::io::{AsyncBufReadExt, BufReader};
        let (tx, mut rx) = mpsc::channel::<Command>(32);
        let _ = output.send(WorkerEvent::Ready(tx)).await;       // app stores the Sender in its state
        while let Some(Command::Run(cmd)) = rx.next().await {
            let Ok(mut child) = tokio::process::Command::new("sh").arg("-c").arg(&cmd)
                .stdout(std::process::Stdio::piped()).kill_on_drop(true).spawn() else { continue };
            if let Some(out) = child.stdout.take() {
                let mut lines = BufReader::new(out).lines();
                while let Ok(Some(line)) = lines.next_line().await {
                    let _ = output.send(WorkerEvent::Line(line)).await;
                }
            }
            let code = child.wait().await.ok().and_then(|s| s.code());
            let _ = output.send(WorkerEvent::Exited(code)).await;
        }
    })
}
```
- `Subscription::run` takes a non-capturing fn; when the worker depends on data (project root, server command) use `Subscription::run_with(data, fn)` — `data: Hash` becomes part of the identity, so changing it restarts the worker and keeping it stable keeps the worker alive. `.with(value)` adds context without capturing.
- Blocking readers (e.g. `portable-pty`'s reader is `std::io::Read`) live on a dedicated thread that forwards bytes over a channel. Coalesce output (per ~8–16 ms or per chunk) — one `Message` per byte will swamp `update`.
- When a subscription is no longer returned, iced drops its stream mid-`.await`, so no cleanup code after the loop runs: rely on drop-based cleanup (`kill_on_drop(true)`, RAII guards) and send explicit shutdown commands (e.g. LSP `shutdown`/`exit`) before you stop returning the subscription.

## Views and large content
- `view` runs after every update; keep it proportional to what is visible.
- `scrollable(column(...))` with tens of thousands of children lays out all of them. Virtualize: track the viewport with `scrollable(..).on_scroll(|v: scrollable::Viewport| ..)` (`absolute_offset()`, `bounds()`, `content_bounds()`), render only visible rows (fixed row height) plus spacers that preserve total height — or draw rows yourself in a custom widget/canvas.
- `lazy(dep, |dep| ..)` (feature `lazy`) caches a subtree until `dep: Hash` changes; the closure must build an owned `Element<'static>` (it cannot borrow state).
- `sensor` (0.14) emits `on_show`/`on_resize`/`on_hide` as content scrolls into view — use for lazy loading; `responsive(|size| ..)` for size-dependent layouts.
- The built-in `text_editor` stores text in cosmic-text buffers: fine for notes, config and commit messages; for a code editor with very large files keep your own rope and draw the visible lines in a custom widget (`editor-engineering`).
- Feature `debug` adds the F12 metrics overlay — use it to check frame and update times.

## Custom, canvas and shader widgets
- **Canvas** (feature `canvas`): implement `canvas::Program<Message>`; cache static layers and clear a `Cache` only when its data changes.
```rust
impl<Message> canvas::Program<Message> for Minimap<'_> {
    type State = ();
    fn draw(&self, _s: &(), renderer: &Renderer, theme: &Theme, bounds: Rectangle, _c: mouse::Cursor)
        -> Vec<canvas::Geometry> {
        let color = theme.palette().text.scale_alpha(0.4);
        vec![self.cache.draw(renderer, bounds.size(), |frame| {
            for (i, len) in self.line_lengths.iter().enumerate() {
                frame.fill_rectangle(Point::new(0.0, i as f32 * 2.0), Size::new(*len as f32, 1.5), color);
            }
        })]
    }
}
// view: canvas(Minimap { line_lengths: &self.line_lengths, cache: &self.minimap }).width(80).height(Fill)
```
  Interaction: `fn update(&self, state, event: &canvas::Event, bounds, cursor) -> Option<canvas::Action<Message>>` returning `canvas::Action::publish(msg)`, `canvas::Action::request_redraw()`, optionally `.and_capture()`; plus `mouse_interaction` for cursors.
- **Custom widget** (feature `advanced`): `impl<Message> advanced::Widget<Message, Theme, Renderer> for Gutter` with `size`, `layout(&mut self, tree, renderer, limits)`, `draw(..)`, optional `tag`/`state` (per-instance state in the widget tree), `children`/`diff`, `operate` (focus/scroll ids), `update(&mut self, tree, event, layout, cursor, renderer, clipboard, shell, viewport)` → `shell.publish(msg)`, `shell.capture_event()`, `shell.request_redraw()`, `shell.invalidate_layout()`; `mouse_interaction`; `overlay`. Provide `impl From<Gutter> for Element<'_, Message>` via `Element::new`. Draw quads with `renderer::Renderer::fill_quad(renderer, renderer::Quad { bounds, .. }, color)`.
- **Shader** widget: `shader::Program` + custom primitives with raw wgpu (0.14 adds a `shader::Pipeline` trait for resource management) for GPU-heavy views (huge plots, image viewers); needs the wgpu renderer.

## Theming, styling, fonts
- Built-in themes (`Theme::Light`, `Dark`, `TokyoNight`, `CatppuccinMocha`, ...) or `Theme::custom("Name", Palette { background, text, primary, success, warning, danger })`. Returning `None` from the theme function follows the system appearance and reacts to changes.
- Per-widget styles are closures: `button("Run").style(|theme: &Theme, status: button::Status| button::Style { .. })` or built-ins (`button::primary`, `container::rounded_box`); read colors from `theme.extended_palette()` instead of hard-coding.
- Fonts: load bytes with `.font(include_bytes!("../assets/fonts/X.ttf").as_slice())`, select with `Font::with_name("Family Name")` (the family inside the file, not the file name); `Font::MONOSPACE`. Use advanced shaping (`text::Shaping::Advanced`) for ligatures, complex scripts and emoji fallback; basic shaping is cheaper for plain ASCII. Embed only fonts whose license permits it (OFL/Apache are fine) and ship their license texts.

## Keyboard shortcuts, focus, multi-window
- `keyboard::listen()` only sees events no widget captured; a focused text input/editor captures typing. `modifiers.command()` is Cmd on macOS and Ctrl elsewhere.
- Editor-scoped shortcuts: `text_editor(..).key_binding(|kp| ...)` returning `Option<text_editor::Binding<Message>>` — `Binding::Custom(msg)` for your commands, `text_editor::Binding::from_key_press(kp)` for defaults.
- Keep one keymap table (chord → command) in state; drive dispatch, menus and the command palette from it so hints never drift.
- Focus: `operation::focus(id)`, `operation::focus_next()`.
- Multi-window: `iced::daemon(boot, update, view)` where `view(&self, window::Id)` and title/theme/scale_factor also take the id; `let (id, open) = window::open(window::Settings::default());` then `open.map(Message::WindowOpened)`; keep `BTreeMap<window::Id, WindowState>`; subscribe to `window::close_events()`; call `iced::exit()` after the last window closes.

## macOS specifics
- **Menu bar**: iced has no native menus (winit installs a minimal default). Use `muda`: create menus on the main thread (it panics elsewhere), call `menu.init_for_nsapp()` once the NSApplication exists, and forward `MenuEvent::receiver()` events into a Subscription worker. Menu accelerators come from the same keymap table.
- **Open file / custom URL events** (Finder double-click, `myapp://`): not exposed by winit or iced. winit documents that it never registers an application delegate, so register your own `NSApplicationDelegate` implementing `application:openURLs:` via `objc2`/`objc2-app-kit`; it only fires for a real `.app` with `CFBundleDocumentTypes`/`CFBundleURLTypes` (see `macos-app-distribution`).
- **IME**: 0.14 supports input methods (preedit, candidate window placement) in built-in text widgets. Custom text widgets must request IME through `Shell` and render preedit text; test with Japanese/Chinese input and dead keys (Option-e then e → é).
- **Retina**: iced works in logical pixels. Allocate canvas/shader textures at physical size, handle `window::Event::Rescaled` when moving between displays, keep 1-px lines crisp (the default `crisp` feature snaps quads).
- Window chrome (macOS-only fields, so gate with `#[cfg(target_os = "macos")]`): `window::Settings { platform_specific: window::settings::PlatformSpecific { title_hidden: true, titlebar_transparent: true, fullsize_content_view: true }, .. }` for a unified title bar.
- A bare binary has no icon, bundle id or proper app name, and may be treated differently by the system — test anything user-facing as a `.app`.

## Testing
- Keep logic in plain modules (no iced types) and unit-test `update` by feeding messages and asserting state.
- `iced_test` 0.14 (dev-dependency) drives views headlessly (ran on Linux with tiny-skia):
```rust
use iced_test::simulator;
#[test]
fn save_button_saves() -> Result<(), iced_test::Error> {
    let mut app = App::default();
    let mut ui = simulator(app.view());
    let _ = ui.click("Save")?;                         // selector: visible text; also find/tap_key/typewrite
    for message in ui.into_messages() { let _ = app.update(message); }
    let mut ui = simulator(app.view());
    let snapshot = ui.snapshot(&Theme::TokyoNight)?;
    assert!(snapshot.matches_hash("tests/snapshots/editor")?, "UI changed"); // or matches_image(...) for PNG
    Ok(())
}
```
- The first snapshot run writes the baseline and passes; files are suffixed per renderer (`editor-tiny-skia.sha256`). Commit baselines; hashes depend on fonts and platform, so embed fonts and run snapshot tests on one OS in CI.
- 0.14 also has an `Emulator` and `.ice` test scripts (recorded with the `tester` feature) that run the real program — side effects happen for real, so sandbox them.

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

## Pitfalls
| Symptom | Cause → fix |
|---|---|
| Worker restarts constantly | Subscription identity changes every update (new `run_with` data, fresh ids) → keep identity data stable |
| `cargo build` fails with E0080 "closure provided is not non-capturing" (`cargo check` passes) | Closure passed to `Subscription::map`/`filter_map` captures → use a fn item or `.with(value)` (`run` takes a fn pointer, so capturing closures don't even compile) |
| "there is no reactor running" | tokio APIs without iced's `tokio` feature |
| UI freezes | Blocking work in `update`/`view` → `Task::perform` or a worker |
| Canvas stale / CPU pegged | Forgot `cache.clear()` / clearing every frame → clear only when that layer's data changes |
| Shortcut ignored while typing | A focused widget captured the key → `key_binding` on the editor |
| Blurry on the other monitor | Physical-size textures not rebuilt on scale change |
| Upgrade breaks everything | Expected pre-1.0 → port using the CHANGELOG and examples at the new tag |

## Verify
- `cargo clippy --all-targets -- -D warnings`; `cargo test` (simulator + snapshot tests) in CI.
- Run the `.app` on the Mac at 1x and 2x scale, light and dark appearance; try IME and keyboard-only navigation.
- Stress: 100k-line document or 100k-row list; check frame/update times in the F12 overlay (`debug` feature) and input latency (method in `editor-engineering`).

## Deliverables / Report
- Iced version and enabled features; module layout; screenshots at 2x (light/dark); test and snapshot results; frame-time p50/p95 on the stress case; known gaps (accessibility, menus, IME in custom widgets).
