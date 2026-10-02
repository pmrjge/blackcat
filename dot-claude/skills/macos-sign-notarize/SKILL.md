---
name: macos-sign-notarize
description: Load to sign and notarize a macOS app — Developer ID, entitlements, notarytool, Gatekeeper, CI.
---
# Signing and notarizing a macOS app

Part of `macos-app-distribution` (rules, bundle layout, build, release checklist). DMG and updates: `macos-dmg-sparkle-brew`.

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

## Verify
- `codesign --verify --deep --strict --verbose=2 MyApp.app` passes; `codesign -dvvv` shows Developer ID authority, timestamp and `flags=0x10000(runtime)`.
- Notary log read (even when Accepted); `xcrun stapler validate` and `spctl -a -vvv -t exec MyApp.app` report `source=Notarized Developer ID`.
