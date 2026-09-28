---
name: macos-app-distribution
description: Load before packaging, signing, notarizing or publishing a macOS app — .app bundle, universal binaries, Developer ID and entitlements, notarytool, DMG, Sparkle, Homebrew casks.
---
# macOS app distribution

## Scope and current rules (Sep 2026)
- Direct distribution = build → assemble `.app` → sign inside-out (Developer ID, hardened runtime, secure timestamp) → DMG (signed) → notarize → staple → publish (+ Sparkle appcast, Homebrew cask). Mac App Store = sandbox + Apple Distribution signing + installer package + upload.
- All Developer ID software must be notarized (since macOS 10.15). macOS 15 removed the Control-click → Open bypass; users must go to System Settings → Privacy & Security → Open Anyway — un-notarized builds are effectively unshippable.
- Homebrew 5 deprecated `--no-quarantine`; homebrew/cask disables casks that fail Gatekeeper checks from September 2026.
- Intel: macOS 26 is the last release for Intel Macs, Rosetta 2 gets restricted after macOS 27, and Rust demoted `x86_64-apple-darwin` to Tier 2 (1.90). Ship arm64-only unless Intel users matter; otherwise universal.
- Requires a paid Apple Developer Program team; Developer ID certificates are created by the Account Holder. Apple references: "Creating distribution-signed code for macOS", "Packaging Mac software for distribution", "Customizing the notarization workflow", "Resolving common notarization issues" — commands below follow them.
- Related: `rust-engineering` (release profiles, targets), `rust-native-gui` (menus, open-file events), `secure-coding` (secrets).

## Bundle structure
```
MyApp.app/Contents/
  Info.plist
  MacOS/myapp                    # CFBundleExecutable
  Resources/AppIcon.icns  Assets.car  fonts/  data/
  Frameworks/Sparkle.framework   # nested code: MacOS/, Frameworks/, PlugIns/, Helpers/, XPCServices/, Library/…
  _CodeSignature/                # written by codesign
  embedded.provisionprofile      # only for restricted entitlements / App Store
```
- Non-code files go in `Resources/` (code-signing locations slow notarization and break signatures). Copy with `ditto`, never `cp` (framework symlinks). Locate resources from the executable path (`std::env::current_exe()` → `../Resources`), never the working directory.
- Never write into the bundle: it breaks the signature, and on first launch from the download location (unmoved ZIP extract or DMG) Gatekeeper *translocates* the app to a random read-only path. User data goes to `~/Library/Application Support/<bundle id>` (`directories`/`dirs` crates).

| Info.plist key | Notes |
|---|---|
| `CFBundleIdentifier` | Reverse DNS, never changes (permissions, Sparkle, keychain depend on it) |
| `CFBundleName`, `CFBundleDisplayName` | Menu/Finder name |
| `CFBundleExecutable` | Exact binary name in `MacOS/` |
| `CFBundlePackageType` | `APPL` |
| `CFBundleShortVersionString` / `CFBundleVersion` | Marketing version / build number (monotonic; Sparkle compares it) |
| `LSMinimumSystemVersion` | Equal to the `MACOSX_DEPLOYMENT_TARGET` used to build (rustc defaults: 11.0 arm64, 10.12 x86_64) |
| `CFBundleIconFile` / `CFBundleIconName` | `.icns` name / asset-catalog icon (macOS 26 layered icon) |
| `NSHighResolutionCapable` | `true` |
| `LSApplicationCategoryType` | e.g. `public.app-category.developer-tools` (App Store needs it) |
| `NSHumanReadableCopyright` | Shown in About |
| `CFBundleDocumentTypes`, `UTExportedTypeDeclarations`, `CFBundleURLTypes` | File types and URL schemes (below) |
| `NS*UsageDescription` | Purpose strings (microphone, camera, Apple Events…); accessing the resource without one fails |
| `LSUIElement` | `true` for menu-bar/agent apps without a Dock icon |
Validate with `plutil -lint MyApp.app/Contents/Info.plist`.

## Icons
- Classic `.icns`: from a 1024×1024 master, build `AppIcon.iconset/` containing `icon_16x16.png`, `icon_16x16@2x.png`, `icon_32x32.png`, `icon_32x32@2x.png`, `icon_128x128.png`, `icon_128x128@2x.png`, `icon_256x256.png`, `icon_256x256@2x.png`, `icon_512x512.png`, `icon_512x512@2x.png` (e.g. `sips -z 64 64 master.png --out AppIcon.iconset/icon_32x32@2x.png`), then `iconutil -c icns AppIcon.iconset` → `CFBundleIconFile`.
- macOS 26 draws legacy `.icns` icons smaller inside a system squircle. For the native look, author a layered `.icon` in Icon Composer and compile it with Xcode 26+ `actool` into `Assets.car` (`CFBundleIconName`), keeping the `.icns` as fallback for older systems. `actool` flags change between Xcode releases — copy them from an Xcode build log or `xcrun actool --help`.
- No third-party logos or trademarks in the icon without permission.

## Build: per-architecture or universal
```sh
rustup target add aarch64-apple-darwin x86_64-apple-darwin
export MACOSX_DEPLOYMENT_TARGET=12.0            # = LSMinimumSystemVersion
cargo build --release --locked --target aarch64-apple-darwin
cargo build --release --locked --target x86_64-apple-darwin
mkdir -p target/universal
lipo -create -output target/universal/myapp \
  target/aarch64-apple-darwin/release/myapp target/x86_64-apple-darwin/release/myapp
lipo -archs target/universal/myapp              # expect: x86_64 arm64
otool -l target/x86_64-apple-darwin/release/myapp | grep -A4 LC_BUILD_VERSION   # minos of each thin slice
```
- Every bundled dylib/framework must contain the same architectures (`lipo -archs`); C dependencies built by `cc`/cmake must be built per target.
- Keep symbols: `split-debuginfo = "packed"` with `debug = "line-tables-only"` or higher in the release profile yields a `.dSYM` per binary (no debuginfo, no dSYM); archive dSYMs per release to symbolicate crash reports (`atos`).

## Code signing (Developer ID)
- Identity: `security find-identity -p codesigning -v` → `"Developer ID Application: Team Name (TEAMID)"` (use the SHA-1 hash if names collide).
- Sign **inside-out**: nested frameworks, helpers and XPC services first, then the app. Don't pass `--deep` when signing (it applies one set of options/entitlements everywhere and misses code in non-standard places); `--deep` is fine for *verifying*. Never run `codesign` with `sudo`.
```sh
ID="Developer ID Application: Example Corp (TEAMID1234)"
codesign --force --timestamp --options runtime \
  --entitlements packaging/myapp.entitlements --sign "$ID" MyApp.app   # after all nested code
codesign --verify --deep --strict --verbose=2 MyApp.app
codesign -dvvv MyApp.app      # Authority=Developer ID Application…, TeamIdentifier, Timestamp=…, flags=0x10000(runtime)
```
- Entitlements: a typical Rust GUI app (Metal/wgpu, network, file access outside the sandbox) needs **none** — omit `--entitlements`. Add only what is required; each is a hardened-runtime exception:
  - `com.apple.security.cs.allow-jit` (JIT via `MAP_JIT`), `com.apple.security.cs.allow-unsigned-executable-memory` (JIT without `MAP_JIT`; weaker), `com.apple.security.cs.disable-library-validation` (loading plugins signed by other teams), `com.apple.security.cs.allow-dyld-environment-variables`;
  - resources: `com.apple.security.device.audio-input`, `com.apple.security.device.camera`, `com.apple.security.automation.apple-events` (each with its `NS*UsageDescription`).
  - Never ship `com.apple.security.get-task-allow` (debugging; notarization rejects it). Entitlements go on main executables only, not on libraries.
  - File format: XML plist, LF endings, no comments/BOM — `plutil -lint file.entitlements`; inspect a signed binary with `codesign -d --entitlements - --xml MyApp.app`.
- Nested command-line tools: sign with `-i <bundle-id>.<tool>` (code-signing identifier) plus `--options runtime --timestamp`.

## Notarization and stapling
```sh
# once per machine/CI secret: App Store Connect API key (preferred) or Apple ID + app-specific password
xcrun notarytool store-credentials notary --key AuthKey_ABC123XYZ.p8 --key-id ABC123XYZ --issuer <issuer-uuid>
xcrun notarytool submit dist/MyApp-1.4.2.dmg --keychain-profile notary --wait
xcrun notarytool log <submission-id> --keychain-profile notary notary-log.json   # read it even when Accepted
xcrun stapler staple dist/MyApp-1.4.2.dmg
xcrun stapler validate dist/MyApp-1.4.2.dmg
```
- Accepted containers: ZIP (`ditto -c -k --keepParent MyApp.app MyApp.zip`), UDIF disk images, signed flat packages. ZIPs cannot be stapled — staple the `.app` and re-zip.
- Nested containers: sign every level, notarize only the outermost (app inside a signed DMG → notarize the DMG). The service issues tickets for nested items; for fully offline first launches notarize and staple the app first (ZIP round), then build, sign, notarize and staple the DMG.
- Typical turnaround: minutes (98% within 15 min). Limits and speed: minimize file count, no large non-code data in code locations, 75 submissions/day. `notarytool` uploads via S3 Transfer Acceleration (`--no-s3-acceleration` if blocked).
- Rejections and fixes: "signature of the binary is invalid" (modified after signing → sign last), "not signed with a valid Developer ID certificate", "does not include a secure timestamp" (`--timestamp`), "requests the com.apple.security.get-task-allow entitlement", "does not have the hardened runtime enabled" (`--options runtime`), SDK older than 10.9, invalid (binary plist) embedded entitlements.

## DMG
```sh
rm -rf dist/dmg && mkdir -p dist/dmg
ditto MyApp.app dist/dmg/MyApp.app && ln -s /Applications dist/dmg/Applications
hdiutil create -volname "MyApp" -srcfolder dist/dmg -ov -format UDZO dist/MyApp-1.4.2.dmg
codesign --sign "$ID" --timestamp -i com.example.myapp.dmg dist/MyApp-1.4.2.dmg
hdiutil verify dist/MyApp-1.4.2.dmg
```
- Custom backgrounds/icon layout: `create-dmg` (Homebrew) or `dmgbuild` (Python) — the result must still be a read-only compressed UDIF image (`UDZO`, Apple's stated requirement for third-party DMG tools) signed with the Developer ID Application identity. Avoid heavily compressed images (they slow notarization).

## Auto-updates with Sparkle 2
- Sparkle 2.x (2.10 since Sep 2026, which requires macOS 12+; older deployment targets stay on 2.9.x). It is an Objective-C framework: embed `Sparkle.framework` in `Contents/Frameworks` (`ditto`), link from Rust in `build.rs` (`cargo::rustc-link-search=framework=<dir>`, `cargo::rustc-link-lib=framework=Sparkle`, `cargo::rustc-link-arg=-Wl,-rpath,@loader_path/../Frameworks`), and start `SPUStandardUpdaterController` on the main thread through `objc2` or a small Objective-C/Swift shim; wire a "Check for Updates…" menu item to it.
- Keys: run `./bin/generate_keys` once — private key goes to the login Keychain (`-x <file>` exports, `-f <file>` imports on another machine/CI); put the printed public key in `SUPublicEDKey` and the HTTPS appcast URL in `SUFeedURL`.
- Each release: sign → notarize → staple → archive → `./bin/generate_appcast <updates-dir>` (signs with EdDSA and writes the appcast) or `./bin/sign_update <archive>` for a hand-written `<item>` (`sparkle:version` = `CFBundleVersion`, `sparkle:shortVersionString`, `sparkle:minimumSystemVersion`, enclosure `sparkle:edSignature` + `length`). CI can read the key from a file instead of the Keychain — check `--help` of both tools for the key-file option.
- Sign Sparkle's nested code before the app (Sparkle's documented order, plus `--timestamp` for Developer ID); non-sandboxed apps may delete the XPC services instead:
```sh
F=MyApp.app/Contents/Frameworks/Sparkle.framework
codesign -f -s "$ID" --timestamp -o runtime "$F/Versions/B/XPCServices/Installer.xpc"
codesign -f -s "$ID" --timestamp -o runtime --preserve-metadata=entitlements "$F/Versions/B/XPCServices/Downloader.xpc"
codesign -f -s "$ID" --timestamp -o runtime "$F/Versions/B/Autoupdate"
codesign -f -s "$ID" --timestamp -o runtime "$F/Versions/B/Updater.app"
codesign -f -s "$ID" --timestamp -o runtime "$F"
```
- Losing the EdDSA private key means existing installs can't verify future updates: keep an offline backup; never commit it.
- Rust-native alternative: `cargo-packager-updater`. Any self-updater must verify signatures before replacing the app.

## Homebrew
```ruby
cask "myapp" do
  arch arm: "arm64", intel: "x86_64"

  version "1.4.2"
  sha256 arm:   "<sha256 of the arm64 dmg>",
         intel: "<sha256 of the x86_64 dmg>"

  url "https://github.com/example/myapp/releases/download/v#{version}/MyApp-#{version}-#{arch}.dmg"
  name "MyApp"
  desc "One-line description"
  homepage "https://example.com/myapp"

  auto_updates true              # only if the app updates itself (Sparkle)

  app "MyApp.app"

  zap trash: [
    "~/Library/Application Support/com.example.myapp",
    "~/Library/Caches/com.example.myapp",
    "~/Library/Preferences/com.example.myapp.plist",
  ]
end
```
- Universal DMG: drop `arch` and use a single `sha256` (`shasum -a 256 file.dmg`).
- Own tap: `brew tap-new you/tap`; `brew create --cask <url> --tap you/tap`; check with `brew audit --cask --strict --online you/tap/myapp` and `brew style you/tap`; test `brew install --cask you/tap/myapp`. homebrew/cask proper requires apps that pass Gatekeeper (signed and notarized) and prefers stable versioned URLs. CLI tools ship as formulae, not casks.

## File types and URL schemes
- `CFBundleDocumentTypes`: `LSItemContentTypes` (UTIs), `CFBundleTypeRole` (`Editor`/`Viewer`), `LSHandlerRank` (`Owner`/`Default`/`Alternate`). Own formats: declare them in `UTExportedTypeDeclarations` (`UTTypeIdentifier`, `UTTypeConformsTo` e.g. `public.plain-text`, `UTTypeTagSpecification` → `public.filename-extension`); formats owned by others go in `UTImportedTypeDeclarations`.
- URL schemes: `CFBundleURLTypes` → `CFBundleURLName` + `CFBundleURLSchemes`.
- Delivery: Apple Events → `application:openURLs:` on the app delegate (files arrive as `file://` URLs). winit (and iced) don't surface these; register your own `NSApplicationDelegate` via `objc2-app-kit` (details in `rust-native-gui`). Works only from a bundled app registered with LaunchServices; inspect registrations with `/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister -dump`.
- URLs and opened files are untrusted input: validate, never execute (`secure-coding`).

## Sandbox and Mac App Store
| | Developer ID | Mac App Store |
|---|---|---|
| Sandbox | Optional | Required (`com.apple.security.app-sandbox`) |
| Certificates | Developer ID Application (+ Developer ID Installer for pkg) | Apple Distribution + Mac Installer Distribution ("3rd Party Mac Developer Installer") |
| Review | Notarization | App Review |
| Updates | Sparkle or own | App Store only |
| Package | DMG / ZIP / pkg | `productbuild --sign "<installer identity>" --component MyApp.app /Applications MyApp.pkg`, upload with Transporter or `xcrun altool` |
| Profile | Only for restricted entitlements | Always (`embedded.provisionprofile`) |
- Sandbox consequences: files via user selection (`com.apple.security.files.user-selected.read-write`) persisted with security-scoped bookmarks (`com.apple.security.files.bookmarks.app-scope`); outgoing network needs `com.apple.security.network.client`; data lives in `~/Library/Containers/<bundle id>`; child processes inherit the sandbox, so shells in a PTY, user toolchains and language servers from the user's PATH generally don't work — IDE-like apps ship with Developer ID.
- Shipping both variants: their default designated requirements differ, so privacy permissions aren't shared unless you craft compatible requirements (Apple TN3127).

## Packaging tools
- `cargo-bundle` 0.12 (README: early alpha): `[package.metadata.bundle]` → `.app` (and DMG with background), PNG → icon conversion, macOS keys in `[package.metadata.bundle.osx]` (`url_schemes`, `info_plist_exts`, `minimum_system_version`); signs the `.app` and DMG in-process via `apple-codesign` (`apple_signing_p12`, hardened runtime, timestamp) but does not notarize.
- `cargo-packager` 0.11: `.app` + `.dmg` (+ Linux/Windows formats); config in `Packager.toml` or `[package.metadata.packager]`; macOS signing identity, entitlements, custom Info.plist, provisioning profile; notarization credentials only via environment; `cargo packager --release`.
- `rcodesign` (apple-codesign 0.29, pure Rust, last release Nov 2024): sign/notarize/staple from Linux — useful when no Mac runner exists; Apple's tools on macOS remain the reference.
- A scripted `xtask`/Makefile pipeline is the most transparent choice once Sparkle or multiple nested components are involved.
- Ship third-party license notices (Rust crates via `cargo about`, fonts, Sparkle's license) in `Resources/`.

## Gatekeeper troubleshooting
| Symptom | Check | Fix |
|---|---|---|
| "MyApp is damaged and can't be opened" | `codesign --verify --deep --strict -vv MyApp.app` | Something changed after signing (Info.plist edit, strip, added file) → re-sign last |
| "Apple could not verify … is free of malware" | `spctl -a -vvv -t exec MyApp.app` should say `source=Notarized Developer ID`; `xcrun stapler validate` | Notarize and staple; check the notary log |
| DMG rejected on open | `spctl -a -t open --context context:primary-signature -v MyApp.dmg` | Sign the DMG with Developer ID Application; notarize/staple it |
| Fine on the build Mac, blocked for users | `xattr -l MyApp.app` shows `com.apple.quarantine` only on downloaded copies | Test with a browser download (curl/scp don't set quarantine) on a second Mac or user |
| Crash at launch, "Code Signature Invalid" / library validation | Crash report termination reason; `codesign -dvvv` on each dylib | Re-sign nested code with your team ID, or (plugins only) `disable-library-validation` |
| Crash only with hardened runtime | Which exception is needed (JIT, DYLD variables) | Add the single required entitlement |
| Odd `/AppTranslocation/` paths | App launched from the download location | Ask users to move it to /Applications; never rely on paths outside the bundle |
- Pre-flight on macOS 14+: `syspolicy_check notary-submission MyApp.app` (the notary service's checks, before uploading) and `syspolicy_check distribution MyApp.app` (the launch-time checks, after stapling); add `--verbose`. Gatekeeper decisions: `log show --last 10m --predicate 'process == "syspolicyd"'`.
- `xattr -dr com.apple.quarantine` is for local debugging only — never tell users to bypass Gatekeeper.

## CI signing (GitHub Actions, macOS runner)
```sh
CERT="$RUNNER_TEMP/cert.p12"; KC="$RUNNER_TEMP/signing.keychain-db"
echo -n "$MACOS_CERT_P12_BASE64" | base64 --decode -o "$CERT"
security create-keychain -p "$KEYCHAIN_PASSWORD" "$KC"
security set-keychain-settings -lut 21600 "$KC"
security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KC"
security import "$CERT" -P "$MACOS_CERT_PASSWORD" -A -t cert -f pkcs12 -k "$KC"   # tighter: -T /usr/bin/codesign instead of -A
security set-key-partition-list -S apple-tool:,apple: -k "$KEYCHAIN_PASSWORD" "$KC"
security list-keychain -d user -s "$KC"
# notarize with the API key decoded to $RUNNER_TEMP: notarytool submit … --key "$KEY_P8" --key-id "$ASC_KEY_ID" --issuer "$ASC_ISSUER_ID" --wait
```
- Secrets only from the secret store via env; never `set -x`/echo in signing steps; mask derived values (`echo "::add-mask::$VALUE"`); run signing jobs only for protected tags/branches (environment with required reviewers); self-hosted runners: `security delete-keychain "$KC"` in an `if: always()` cleanup step and remove temp key files; rotate API keys and app-specific passwords; the Sparkle private key is a secret too.

## Release checklist
1. Bump `CFBundleShortVersionString` and `CFBundleVersion`; changelog.
2. Build per target with `MACOSX_DEPLOYMENT_TARGET` = `LSMinimumSystemVersion`; `lipo` if universal; confirm `lipo -archs` for every Mach-O.
3. Assemble the `.app` (`plutil -lint`, icon, resources, frameworks via `ditto`, license notices).
4. Sign inside-out (hardened runtime + timestamp); `codesign --verify --deep --strict`.
5. Build the DMG (UDZO), sign it, `hdiutil verify`.
6. Notarize (`--wait`), read the log, staple, `stapler validate`, `spctl` checks for app and DMG.
7. Test on a clean Mac or user account: browser download, open from DMG, move to /Applications, first launch offline and online, file types/URL schemes, update from the previous version via Sparkle.
8. Publish: release assets + SHA-256 sums, appcast, cask bump, archived dSYMs.

## Deliverables / Report
- Signed, notarized, stapled DMG (and ZIP if offered) with SHA-256 sums; appcast entry; cask diff.
- Notarization submission ID and log; verification transcript (`codesign -dvvv`, `spctl`, `stapler validate` outputs).
- Entitlements used and why; minimum macOS and architectures; dSYM archive location.
