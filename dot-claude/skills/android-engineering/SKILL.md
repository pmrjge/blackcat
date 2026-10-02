---
name: android-engineering
description: Load before writing, building or testing Android apps — Kotlin, Gradle/AGP, Jetpack Compose, testing, adb; the Android and cross-platform module map.
---
# Android engineering (hub)

## Scope
Native Android in Kotlin with Jetpack Compose, Gradle builds, tests and emulators. JVM language and Gradle depth: `jvm-engineering`; accessibility: `a11y-mobile`; strings: `localization`.

## Modules
| module | load when |
|---|---|
| `kotlin-coroutines` | coroutines, Flow, StateFlow, lifecycle scopes, coroutine tests |
| `android-release` | signing, AAB, R8, Play Console tracks, target API and policy checks |
| `flutter` | Flutter/Dart apps for Android and iOS |
| `react-native` | React Native / Expo apps |

## Baseline
- Kotlin 2.4.20 — Verified 2026-10-02 https://github.com/JetBrains/kotlin/releases/latest
- AGP 9.4.0 needs Gradle 9.6.0 and JDK 17 — Verified 2026-10-02 https://developer.android.com/build/releases/gradle-plugin (stable label unverified; check the page's compatibility table before bumping)
- Compose BOM 2026.09.00 — Verified 2026-10-02 https://developer.android.com/develop/ui/compose/bom
- Play requires targetSdk 36 for new apps and updates (since 2026-08-31) — Verified 2026-10-02 https://support.google.com/googleplay/android-developer/answer/11926878
- Android 17 is API 37 (whether it is released to devices: unverified) — https://developer.android.com/about/versions/17

## Project rules
- Version catalog (`gradle/libs.versions.toml`) for every dependency and plugin; Compose libraries through the BOM; no dynamic versions (`+`).
- Gradle: configuration cache and build cache on; KSP instead of kapt; convention plugins (`build-logic/`) for shared module setup; the wrapper checked in with its checksum (`distributionSha256Sum`).
- Architecture: UI (Compose) → ViewModel (exposes `StateFlow<UiState>`, takes events) → domain/use cases (optional) → repositories → data sources. Unidirectional data flow; UI state is immutable data classes.
- DI with Hilt or Koin as the project already does; constructor injection.
- Compose: state hoisting, `remember`/`rememberSaveable`, stable/immutable parameters (strong skipping is the default), `collectAsStateWithLifecycle()` for flows, side effects in `LaunchedEffect`/`DisposableEffect` keyed correctly, `Modifier` as the first optional parameter.
- Resources: strings in `strings.xml` (no hard-coded UI text), plurals via `<plurals>`, dimensions in dp/sp, dark theme and dynamic color handled.
- Background work: WorkManager for deferrable guaranteed work; foreground services only with the right type and permission.
- Permissions requested in context with rationale; handle denial and "don't ask again".

## Testing
- Unit: JUnit (4 or 5 per project) + `kotlinx-coroutines-test`; Robolectric for Android-framework logic on the JVM.
- Compose UI: `createComposeRule()`, semantics matchers (`onNodeWithTag`, `onNodeWithText`), screenshot tests (Roborazzi or Compose Preview Screenshot Testing) on a pinned configuration.
- Instrumented/E2E: Espresso or Compose tests on an emulator; Gradle Managed Devices for reproducible CI emulators.
- Commands: `./gradlew testDebugUnitTest`, `./gradlew connectedDebugAndroidTest`, `./gradlew lint`, `./gradlew :app:assembleDebug`.

## Devices and emulators
- Emulators (`emulator -avd <name>`, `adb -e`) are local and fine. `adb devices` is read-only.
- Installing on or wiping a physical device (`adb -d install`, `adb uninstall`, `pm clear`) needs the user's consent; name the device serial first.
- Useful: `adb logcat --pid=$(adb shell pidof -s <pkg>)`, `adb shell am start -W -n <pkg>/.MainActivity` (startup time), `adb exec-out screencap -p > shot.png` (Read it before claiming visual results).

## Verify
`./gradlew build` (assemble + unit tests + lint) green with no new lint errors · Compose UI/screenshot tests for changed screens · release variant builds with R8 · targetSdk/minSdk and AGP/Kotlin versions reported.
