---
name: ios-build-sim
description: Use for Apple builds and tests from the CLI — xcodebuild, simctl, XCUITest, xcresult.
---
# Building and testing Apple apps from the command line

Baseline: `swift-engineering`. When an XcodeBuildMCP server is available to you, prefer its tools for build, run, test, logs and screenshots; the commands below are the fallback and the ground truth.

## Discover before building
```bash
xcodebuild -version
xcodebuild -list -workspace App.xcworkspace          # schemes, configurations (or -project App.xcodeproj)
xcrun simctl list devices available --json | jq '.devices | to_entries[] | select(.value|length>0) | .key'
xcodebuild -showdestinations -scheme App -workspace App.xcworkspace
```
Simulator device names and runtimes change with each Xcode: pick from the list, never hard-code a name you did not see.

## Build and test
```bash
xcodebuild -workspace App.xcworkspace -scheme App -configuration Debug \
  -destination 'platform=iOS Simulator,name=<device from the list>,OS=latest' \
  -derivedDataPath build/dd -resultBundlePath build/test.xcresult \
  test | xcbeautify                                   # xcbeautify optional; keep the raw log on failure
```
- `build-for-testing` once, then `test-without-building -only-testing:AppTests/FooTests` for fast loops.
- `-skipPackagePluginValidation -skipMacroValidation` only in CI where the user already trusts the packages.
- Code signing for simulator builds is not needed: `CODE_SIGNING_ALLOWED=NO` for CI simulator builds.
- Test plans (`.xctestplan`) hold configurations (sanitizers, languages, regions); run with `-testPlan`.
- Results: `xcrun xcresulttool get test-results summary --path build/test.xcresult` (subcommands changed across Xcode versions — check `xcrun xcresulttool help`); attachments and screenshots are in the bundle.

## Simulator control (`xcrun simctl`)
`boot <udid>`, `install booted App.app`, `launch --console-pty booted <bundle-id>`, `terminate`, `uninstall`, `io booted screenshot shot.png`, `io booted recordVideo out.mp4`, `openurl booted <url>`, `push booted <bundle-id> payload.apns`, `privacy booted grant photos <bundle-id>`, `status_bar booted override --time 9:41 --batteryLevel 100`, `ui booted appearance dark`, `spawn booted log stream --predicate 'subsystem == "<id>"'`, `erase <udid>` (wipes that simulator only — say so first). Simulators are the default target; they are local and reversible.

## UI tests (XCUITest)
- Query by accessibility identifier, not by label text (labels are localized).
- Launch arguments/environment to put the app in a test mode (`app.launchArguments += ["-uitest", "-reset"]`) with stubbed network.
- Wait with `waitForExistence(timeout:)` / expectations, never `sleep`.
- Screenshots via `XCTAttachment` for review; Read them before claiming visual results.

## Sanitizers and diagnostics
Address/Thread/Undefined Behavior sanitizers via scheme or `-enableAddressSanitizer YES`, `-enableThreadSanitizer YES` (not together); Main Thread Checker on by default in debug; `-enableCodeCoverage YES` for coverage in the result bundle.

## Physical devices
`xcrun devicectl list devices` is read-only. Installing or launching on a device (`xcrun devicectl device install app …`, `xcodebuild … -destination 'id=<udid>'`) needs the user's consent and a signed build (`app-store-release` for signing).

## Pitfalls
Building the `.xcodeproj` when the project uses a workspace (CocoaPods/SPM plugins missing); stale DerivedData (use a per-task `-derivedDataPath` instead of deleting the shared one); simulator runtime not installed (`xcodebuild -downloadPlatform iOS` is a large download — ask first); flaky UI tests from animations (disable via launch argument); tests depending on the host's locale or time zone.

## Verify
Exact command and destination recorded · build and tests green with the result bundle path reported · screenshots of changed UI Read · failures quoted from the xcresult summary, not paraphrased.
