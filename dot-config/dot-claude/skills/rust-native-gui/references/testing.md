# rust-native-gui — testing (reference)
Read when testing the GUI. Parent: `rust-native-gui` SKILL.md.

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
