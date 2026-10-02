---
name: swift-engineering
description: Use for Swift on Apple platforms — Swift 6 concurrency, SwiftPM, Swift Testing; iOS modules.
---
# Swift engineering (hub)

## Scope
Swift on Apple platforms (iOS, iPadOS, macOS, watchOS, visionOS) and server-side Swift basics. UI in `swiftui`, builds/simulators/UI tests in `ios-build-sim`, App Store and TestFlight in `app-store-release`; macOS outside the App Store in `macos-app-distribution`; accessibility in `a11y-mobile`.

## Modules
| module | load when |
|---|---|
| `swiftui`* | views, state and data flow, navigation, Observation, previews, UIKit interop |
| `ios-build-sim`* | `xcodebuild`, schemes, simulators (`simctl`), XCTest/XCUITest, result bundles, devices |
| `app-store-release`* | signing, provisioning, TestFlight, App Store Connect, privacy manifests, review |
| `flutter` / `react-native` | cross-platform apps (Dart / React) |

`*` = not in the skill listing: Read `__CLAUDE_DIR__/skills/<name>/SKILL.md` (the Skill tool won't load it).

## Baseline
- Xcode 27 ships the iOS 27 SDK and Swift 6.4 — Verified 2026-10-02 https://developer.apple.com/support/xcode/ (exact point release unverified; run `xcodebuild -version` and `swift --version`).
- Swift 6.4.0 is the current release — Verified 2026-10-02 https://www.swift.org/install/macos/
- iOS/iPadOS/macOS 27 are the current public majors — Verified 2026-10-02 https://www.apple.com/newsroom/2026/09/major-updates-for-apples-software-platforms-are-now-available/
- Read the installed versions before writing version-specific code; Apple APIs gain `@available` gates every year.

## Language rules
- Swift 6 language mode for new code: data-race safety is checked at compile time. Fix diagnostics by design (actor isolation, `Sendable` value types), not by `@unchecked Sendable` or `nonisolated(unsafe)` — each of those needs a `// SAFETY:`-style comment explaining the invariant.
- Default isolation: app targets may set main-actor default isolation (Swift 6.2+ "approachable concurrency" settings); know which mode the target uses before reasoning about isolation. Background work goes in `@concurrent` functions or actors.
- Structured concurrency first (`async let`, task groups); unstructured `Task {}` only at UI/event boundaries, stored and cancelled when the owner goes away. Check `Task.isCancelled`/`try Task.checkCancellation()` in long loops.
- Value types by default; classes for identity and shared mutable state (prefer actors for the latter); `final` unless designed for subclassing.
- Errors: typed `throws(MyError)` where the error set is closed and part of the API; plain `throws` otherwise; no `try!` outside tests and provably-safe literals; no force-unwraps on external data.
- Access control explicit at module boundaries; `package` for cross-module internals in SwiftPM.
- Codable models separate from view models; dates and decimals with explicit strategies.

## Packages and tooling
- SwiftPM for libraries and app modules (local packages split features); `Package.resolved` committed for apps; dependency versions pinned `.upToNextMinor` for pre-1.0 packages.
- Format and lint: `swift format` (bundled with Swift 6 toolchains) with a committed `.swift-format`; SwiftLint if the project already uses it.
- Tests: Swift Testing (`import Testing`, `@Test`, `#expect`, `#require`, parameterized `@Test(arguments:)`) for new unit tests; XCTest remains for UI tests and performance tests. `swift test` for packages; `xcodebuild test` for app targets (`ios-build-sim`).
- Docs: DocC comments on public API.

## Safety
- Installing on a physical device, sending builds to TestFlight or the App Store, and changing certificates or profiles in the user's Apple Developer account need the user's consent.
- Signing material (`.p12`, `.p8` App Store Connect keys, match passphrases) never enters the repo or logs; it comes from the keychain or the user's secret store.

## Verify
`swift build` / `xcodebuild build` without new warnings in Swift 6 mode · `swift test` or `xcodebuild test` green · `swift format lint --strict` clean · versions of Xcode, Swift and deployment targets reported.
