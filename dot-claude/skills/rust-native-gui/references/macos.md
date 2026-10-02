# macOS specifics
Read from `rust-native-gui` (core rules in its SKILL.md).

## macOS specifics
- **Menu bar**: iced has no native menus (winit installs a minimal default). Use `muda`: create menus on the main thread (it panics elsewhere), call `menu.init_for_nsapp()` once the NSApplication exists, and forward `MenuEvent::receiver()` events into a Subscription worker. Menu accelerators come from the same keymap table.
- **Open file / custom URL events** (Finder double-click, `myapp://`): not exposed by winit or iced. winit documents that it never registers an application delegate, so register your own `NSApplicationDelegate` implementing `application:openURLs:` via `objc2`/`objc2-app-kit`; it only fires for a real `.app` with `CFBundleDocumentTypes`/`CFBundleURLTypes` (see `macos-app-distribution`).
- **IME**: 0.14 supports input methods (preedit, candidate window placement) in built-in text widgets. Custom text widgets must request IME through `Shell` and render preedit text; test with Japanese/Chinese input and dead keys (Option-e then e → é).
- **Retina**: iced works in logical pixels. Allocate canvas/shader textures at physical size, handle `window::Event::Rescaled` when moving between displays, keep 1-px lines crisp (the default `crisp` feature snaps quads).
- Window chrome (macOS-only fields, so gate with `#[cfg(target_os = "macos")]`): `window::Settings { platform_specific: window::settings::PlatformSpecific { title_hidden: true, titlebar_transparent: true, fullsize_content_view: true }, .. }` for a unified title bar.
- A bare binary has no icon, bundle id or proper app name, and may be treated differently by the system — test anything user-facing as a `.app`.
