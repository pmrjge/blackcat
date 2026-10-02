---
name: flutter
description: Load for Flutter apps — Dart, state management, go_router, Pigeon platform channels, widget/golden/integration tests, release builds.
---
# Flutter

Platform release steps: `app-store-release` (iOS) and `android-release` (Android). Device installs and store uploads need the user's consent.

## Baseline
- Flutter 3.47.6 stable with Dart 3.13.5 (2026-10-01) — Verified 2026-10-02 https://storage.googleapis.com/flutter_infra_release/releases/releases_macos.json
- Pin the SDK per project (`fvm` with `.fvmrc`, or `environment: flutter:` constraints in `pubspec.yaml`) and report `flutter --version`.
- `pubspec.lock` committed for apps; dependency upgrades with `flutter pub outdated` then `flutter pub upgrade --major-versions` deliberately, one package family at a time.

## Architecture
- Layers: widgets (UI) → state holders (ViewModels/Notifiers/Blocs) → repositories → services/APIs. Widgets do no I/O.
- State management: one approach per app — Riverpod (`Notifier`/`AsyncNotifier`, code generation optional) or Bloc/Cubit; `ValueNotifier`/`ChangeNotifier` for small apps. Follow what the project uses.
- Immutable state classes (`freezed` or hand-written `copyWith` + `==`); sealed classes with pattern matching for UI states (`switch` exhaustiveness).
- Navigation: `go_router` (declarative, deep links) or the project's existing router.
- Async: `Future`/`Stream` with `async`/`await`; cancel `StreamSubscription`s in `dispose`; check `mounted` (or `context.mounted`) after awaits before using `BuildContext`.

## Widgets and performance
- `const` constructors wherever possible; split large `build` methods into widgets (not helper methods) so rebuilds are scoped.
- Lists: `ListView.builder`/slivers with keys for reorderable or stateful items.
- Expensive work off the UI isolate: `Isolate.run` / `compute`.
- Rendering: Impeller is the default renderer on iOS and on modern Android devices; profile in `--profile` mode with DevTools (frame chart, raster vs UI thread), never in debug.
- Adaptive layouts: `LayoutBuilder`/`MediaQuery.sizeOf`, text scaling respected (no fixed-height text containers), `Semantics` for custom widgets.

## Platform integration
- Platform channels via Pigeon (typed, generated) rather than hand-written `MethodChannel` strings.
- FFI (`dart:ffi`, `ffigen`) for C libraries; plugins federated per platform.
- Permissions, notifications, background work through maintained plugins; check each plugin's platform support and last release before adding it.

## Localization
`flutter_localizations` + `gen-l10n` with ARB files (`l10n.yaml`); ICU plurals and placeholders typed in the ARB metadata; `localization` skill for the catalog work.

## Testing
- `flutter test` for unit and widget tests (`testWidgets`, `pumpWidget`, `pumpAndSettle` sparingly — prefer `pump(duration)`); fakes over mocks; `mocktail` when mocks are needed.
- Golden tests (`matchesGoldenFile`) on a pinned platform and font setup (goldens differ between macOS and Linux); `alchemist` or similar for multi-scenario goldens.
- Integration: `integration_test` package on an emulator/simulator (`flutter test integration_test`); Patrol for native dialogs.
- Analysis: `flutter analyze` with `flutter_lints`/`very_good_analysis`, `dart format --set-exit-if-changed .`, `dart fix --dry-run`.

## Builds
`flutter build appbundle --release` (Android), `flutter build ipa --release` (iOS, needs signing), `--obfuscate --split-debug-info=build/symbols` with the symbols archived per release; flavors via `--flavor` + `--dart-define-from-file=env/prod.json` (no secrets in dart-defines — they ship in the binary).

## Pitfalls
Using `BuildContext` across async gaps; `setState` after `dispose`; rebuilding whole screens from a top-level provider; platform plugins without iOS/Android parity; secrets in Dart code or `--dart-define`; goldens recorded on a different OS than CI.

## Verify
`flutter analyze` clean · `dart format` clean · `flutter test` green (goldens on the pinned platform) · integration test for the changed flow on an emulator · release build succeeds for each target platform · Flutter/Dart versions reported.
