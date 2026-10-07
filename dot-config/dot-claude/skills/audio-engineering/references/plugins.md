# Audio plugins

Baseline (real-time rules, ear safety): `audio-engineering`. DSP: `references/dsp.md`. macOS signing and notarization: `macos-app-distribution`.

## Frameworks and SDKs
- JUCE 9.0.3 (C++; tiered commercial EULA with a free Starter tier up to a revenue cap — whether an AGPL option remains is unverified; check the license before shipping) — Verified 2026-10-02 https://github.com/juce-framework/JUCE/releases/latest https://juce.com/legal/juce-9-licence/
- VST 3 SDK 3.8.1 (MIT-licensed from 3.8) — Verified 2026-10-02 https://github.com/steinbergmedia/vst3sdk
- CLAP 1.2.10 (MIT, open plugin ABI) — Verified 2026-10-02 https://github.com/free-audio/clap (tags)
- nih-plug (Rust; VST3 + CLAP; no crate releases — pin a git commit) — https://github.com/robbert-vdh/nih-plug
- Faust 2.88.0 (DSP language compiling to C++/Rust/WASM and plugin architectures) — Verified 2026-10-02 https://github.com/grame-cncm/faust/releases/latest
- pluginval v1.0.4 (plugin validator) — Verified 2026-10-02 https://github.com/Tracktion/pluginval/releases/latest
- Audio Units (AUv2/AUv3) on Apple platforms only; AUv3 ships inside an app extension.

## Architecture rules
- Separate DSP core (pure, testable, no framework types) from the plugin wrapper and from the GUI.
- Parameters: stable IDs that never change between versions (hosts store automation by ID); ranges, skew and units declared; values smoothed in the DSP; parameter changes from the host arrive on the audio thread — no allocation in handlers.
- State save/restore: versioned format (JUCE `ValueTree`/XML, nih-plug `#[persist]` + serde), backward compatible; test loading presets from every previous release.
- GUI ↔ audio communication only through atomics/lock-free queues; GUI never touches DSP objects directly; meters read values published by the audio thread.
- Bus layouts: declare supported layouts; handle mono, stereo and sidechain; process in place safely.
- Latency and tail reported to the host (`setLatencySamples`, tail time) and updated when they change.
- Sample-rate and block-size changes handled in `prepareToPlay`/`initialize`; never assume a fixed block size (hosts send variable sizes, including 0 and 1).

## Build and test
- CMake for JUCE (`juce_add_plugin` with `FORMATS VST3 AU CLAP Standalone` — CLAP via the clap-juce-extensions project or JUCE's own support if the version has it; check the docs), `cargo xtask bundle <plugin> --release` for nih-plug.
- Validate every build with pluginval at high strictness (`pluginval --strictness-level 10 --validate <path>`), Steinberg's `validator` for VST3, `auval -v aufx <code> <manu>` for AU, clap-validator for CLAP.
- Offline render tests of the DSP core in CI; a host smoke test (REAPER, Bitwig, Logic, Ableton) recorded by the user or via computer use (`computer-use-apps`) as a last step.
- Real-time safety checks: RealtimeSanitizer (`-fsanitize=realtime`, Clang 20+) or allocation hooks in tests; `assert_no_alloc` in Rust.

## Distribution
- macOS: universal binaries (arm64 + x86_64), Developer ID signing and notarization of each bundle and the installer (consent before signing with the user's identity or submitting to Apple); install paths `~/Library/Audio/Plug-Ins/{VST3,Components,CLAP}`.
- Windows: VST3 in `C:\Program Files\Common Files\VST3`, code-signed installers; CLAP in `Common Files\CLAP`.
- Publishing releases or uploading to stores/marketplaces is the user's step.

## Pitfalls
Changing parameter IDs (breaks saved sessions); allocation or locks in `processBlock`; GUI timers reading DSP state unsafely; ignoring host sample-rate changes; reporting wrong latency; forgetting the AU's component code/manufacturer uniqueness; shipping without pluginval at high strictness.

## Verify
pluginval (strictness 10) and format validators pass · state from previous versions loads · offline render tests green at several rates and block sizes · real-time sanitizer clean · bundles signed and notarized when shipping (with consent) · SDK/framework versions and licenses reported.
