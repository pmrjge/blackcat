---
name: macos-app-distribution
description: Use to package, sign, notarize or publish a macOS app — bundles, universal binaries, DMG, Sparkle, Homebrew.
---
# macOS app distribution

## Scope and current rules (Sep 2026)
- Direct distribution = build → assemble `.app` → sign inside-out (Developer ID, hardened runtime, secure timestamp) → DMG (signed) → notarize → staple → publish (+ Sparkle appcast, Homebrew cask). Mac App Store = sandbox + Apple Distribution signing + installer package + upload.
- All Developer ID software must be notarized (since macOS 10.15). macOS 15 removed the Control-click → Open bypass; users must go to System Settings → Privacy & Security → Open Anyway — un-notarized builds are effectively unshippable.
- Homebrew 5 deprecated `--no-quarantine`; homebrew/cask disables casks that fail Gatekeeper checks from September 2026.
- Intel: macOS 26 is the last release for Intel Macs, Rosetta 2 gets restricted after macOS 27, and Rust demoted `x86_64-apple-darwin` to Tier 2 (1.90). Ship arm64-only unless Intel users matter; otherwise universal.
- Requires a paid Apple Developer Program team; Developer ID certificates are created by the Account Holder. Apple references: "Creating distribution-signed code for macOS", "Packaging Mac software for distribution", "Customizing the notarization workflow", "Resolving common notarization issues" — commands below follow them.
- Related: `rust-release` (release profiles, targets), `rust-native-gui` (menus, open-file events), `secure-coding` (secrets).
- Versions: Sparkle 2.10.0 (`git ls-remote --tags https://github.com/sparkle-project/Sparkle`), cargo-bundle 0.12.0, cargo-packager 0.11.8, apple-codesign 0.29.0 (https://crates.io/api/v1/crates/<name>) — Verified 2026-10-02; Homebrew is at 7.0.x now (github.com/Homebrew/brew tags), the Homebrew 5 deprecation above dates from 5.0. macOS-release and Gatekeeper-policy claims: unverified since Sep 2026.

## Modules (load the one the task touches)
| Module | Load for |
|---|---|
| `macos-sign-notarize` | Developer ID signing, entitlements, notarytool and stapling, Gatekeeper troubleshooting, CI signing, sandbox and Mac App Store |
| `macos-dmg-sparkle-brew` | DMG images, Sparkle 2 updates, Homebrew casks and taps, packaging tools (cargo-bundle, cargo-packager, rcodesign) |

Read `references/bundle-metadata.md` when filling Info.plist, making the app icon, or registering document types and URL schemes.

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

Info.plist keys (identifier, versions, `LSMinimumSystemVersion`, icons, purpose strings, `LSUIElement`): `references/bundle-metadata.md`; validate with `plutil -lint MyApp.app/Contents/Info.plist`.

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

