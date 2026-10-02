# DMG, Sparkle updates, Homebrew and packaging tools

Part of `macos-app-distribution` (rules, bundle layout, build, release checklist). Signing and notarization: `references/sign-notarize.md`.

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

## Packaging tools
- `cargo-bundle` 0.12 (README: early alpha): `[package.metadata.bundle]` → `.app` (and DMG with background), PNG → icon conversion, macOS keys in `[package.metadata.bundle.osx]` (`url_schemes`, `info_plist_exts`, `minimum_system_version`); signs the `.app` and DMG in-process via `apple-codesign` (`apple_signing_p12`, hardened runtime, timestamp) but does not notarize.
- `cargo-packager` 0.11: `.app` + `.dmg` (+ Linux/Windows formats); config in `Packager.toml` or `[package.metadata.packager]`; macOS signing identity, entitlements, custom Info.plist, provisioning profile; notarization credentials only via environment; `cargo packager --release`.
- `rcodesign` (apple-codesign 0.29, pure Rust, last release Nov 2024): sign/notarize/staple from Linux — useful when no Mac runner exists; Apple's tools on macOS remain the reference.
- A scripted `xtask`/Makefile pipeline is the most transparent choice once Sparkle or multiple nested components are involved.
- Ship third-party license notices (Rust crates via `cargo about`, fonts, Sparkle's license) in `Resources/`.

## Verify
- `hdiutil verify` on the DMG; the DMG is signed, notarized and stapled (`references/sign-notarize.md` Verify).
- Sparkle: an update from the previous version installs on a clean account; the appcast item carries `sparkle:edSignature` and the right `sparkle:version`.
- Cask: `brew audit --cask --strict --online` and `brew style` clean; `brew install --cask` works from the tap.
