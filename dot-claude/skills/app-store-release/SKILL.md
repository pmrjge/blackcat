---
name: app-store-release
description: Use to sign and ship Apple apps — certificates, profiles, archives, TestFlight, App Store Connect, privacy manifests, upload rules.
---
# Signing and App Store release

Baseline: `swift-engineering`. macOS outside the App Store (Developer ID, notarization, DMG): `macos-app-distribution`.

## Consent gates
Uploading a build (TestFlight or App Store), submitting for review, releasing, creating or revoking certificates, registering devices or editing App Store Connect metadata are externally visible: stop and ask the user with the exact action. Building and exporting an `.ipa` locally is fine.

## Current requirements
- Uploads must be built with Xcode 26 or later against the 26 SDKs (since 2026-04-28) — Verified 2026-10-02 https://developer.apple.com/news/upcoming-requirements/
- Minimum deployment target iOS/iPadOS 13 for uploads (since 2026-09-09), per the same page (read via summary — re-check before relying on it).
- Required-reason API declarations in privacy manifests (`PrivacyInfo.xcprivacy`, including third-party SDKs') are enforced at upload since 2024-05-01 — Verified 2026-10-02 https://developer.apple.com/news/upcoming-requirements/
- Requirements change yearly (usually each spring for the previous autumn's SDK): re-read that page before every release.

## Signing model
- Development vs distribution certificates; provisioning profiles bind bundle ID + certificate + entitlements (+ devices for development/ad hoc).
- Automatic signing for local work; manual or fastlane `match` (encrypted git or cloud storage) for teams and CI. One source of truth for profiles.
- Entitlements are the source of capability bugs: compare the target's `.entitlements` with the App ID capabilities in the developer portal.
- Secrets: App Store Connect API keys (`.p8`, key ID, issuer ID), `.p12` passwords and match passphrases come from the keychain or CI secret store; never in the repo, scripts, logs or prompts. If one leaks, tell the user to revoke it.

## Build and export
```bash
xcodebuild -workspace App.xcworkspace -scheme App -configuration Release \
  -destination 'generic/platform=iOS' -archivePath build/App.xcarchive archive
xcodebuild -exportArchive -archivePath build/App.xcarchive \
  -exportOptionsPlist ExportOptions.plist -exportPath build/export     # method: app-store-connect, signingStyle, teamID
```
- Version (`CFBundleShortVersionString`, marketing) and build number (`CFBundleVersion`, strictly increasing per version) set by the release script (`agvtool` or build settings), never by hand-editing in several places.
- dSYMs kept with each archive and uploaded to the crash reporter.

## Upload and review (each step after the user's consent)
- Tools: Xcode Organizer, Transporter, `fastlane pilot` (TestFlight) / `fastlane deliver` (metadata, screenshots, submission) with an App Store Connect API key, or the App Store Connect API. fastlane 2.240.1 — Verified 2026-10-02 https://github.com/fastlane/fastlane/releases/latest
- Export compliance: set `ITSAppUsesNonExemptEncryption` in Info.plist so uploads don't stall on the question.
- TestFlight: internal testers first; external groups need beta review.
- App Review: check the App Review Guidelines for anything touching payments (in-app purchase rules differ by region), login (Sign in with Apple when third-party login is offered), account deletion, user-generated content, tracking (ATT prompt before IDFA).
- Phased release for updates; keep the previous build's dSYMs and notes for rollback decisions (the App Store cannot roll back — ship a fix).

## Privacy and metadata
Privacy manifest per target and per bundled SDK; App Privacy "nutrition labels" consistent with the manifest and actual data collection; screenshots per required device size; localized metadata (`localization` skill for strings).

## Pitfalls
Wrong export method; missing entitlements in the distribution profile (push, iCloud, associated domains); build number reused; bitcode/dSYM confusion with old instructions; third-party SDK without its privacy manifest; testing only Debug builds (Release optimizations, stripped symbols, different entitlements).

## Verify
Archive and export succeed with the intended team and profile (`codesign -dv --entitlements - Payload/App.app`) · version and build number reported · privacy manifest present and valid · Release build smoke-tested on a simulator · upload/submission only after the user said so, with the processing status reported.
