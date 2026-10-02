---
name: android-release
description: Use to sign and ship Android apps — keystores, AAB, R8, Play tracks, targetSdk, 16 KB pages.
---
# Android release

Baseline: `android-engineering`.

## Consent gates
Uploading to Google Play (any track), promoting a release, changing rollout percentage, editing the store listing or Data safety form, and generating or rotating the upload key are externally visible or hard to undo: stop and ask the user with the exact action. Local release builds are fine.

## Current requirements
- targetSdk 36 for new apps and updates since 2026-08-31 (Wear OS/Automotive 35, TV/XR 34; extensions until 2026-11-01) — Verified 2026-10-02 https://support.google.com/googleplay/android-developer/answer/11926878
- 16 KB memory page size: apps targeting API 35+ that ship native code (NDK or native SDKs) must be 16 KB aligned; non-compliant updates are blocked from 2027-02-01. AGP 8.5.1+ packages aligned; NDK r28+ aligns by default — Verified 2026-10-02 https://developer.android.com/guide/practices/page-sizes
- Re-read the Play policy pages before each release; deadlines move yearly (usually August).

## Signing
- Play App Signing: Google holds the app signing key; you sign uploads with the upload key. Losing the upload key is recoverable through Play support; leaking it requires a reset (tell the user).
- Keystore files and passwords come from the user's secret store or CI secrets (environment variables / Gradle properties outside the repo); `signingConfigs` read them, the repo never contains them. `.jks`/`.keystore` in `.gitignore`.
- Check signatures: `apksigner verify --print-certs app.apk`; for AABs `jarsigner -verify -verbose app.aab` (upload signature).

## Build
- `./gradlew :app:bundleRelease` → AAB (required for Play); APKs only for side-loading or other stores.
- `versionCode` strictly increasing (derive from CI build number or a release script), `versionName` human-readable.
- R8: `isMinifyEnabled = true`, `isShrinkResources = true`; keep rules for reflection/serialization (`@Keep`, library consumer rules); keep `mapping.txt` per release and upload it with the bundle (deobfuscated crash reports).
- Baseline profiles (`androidx.baselineprofile` plugin + Macrobenchmark) for startup and scrolling; measure startup before/after.
- Test the actual release artifact: `bundletool build-apks --bundle=app.aab --output=app.apks --local-testing` then `bundletool install-apks` on an emulator.
- Native libraries: check 16 KB alignment (`zipalign -c -P 16 -v 4 app.apk`, or the APK Analyzer) for every `.so`.

## Play Console
- Tracks: internal → closed → open → production; staged rollout percentage with halt available; new personal developer accounts may need a closed test with testers before production access (check the current rule).
- Data safety form consistent with actual data collection (SDKs included); permissions declarations for sensitive permissions (SMS, call log, location in background, all-files access, exact alarms).
- Automation: Gradle Play Publisher or `fastlane supply` with a service account JSON from the secret store; each upload is a consent gate.

## Pitfalls
Debuggable or test-only flags in release; missing keep rules crashing only in release; versionCode collisions between flavors; uploading an APK instead of an AAB; forgetting the mapping file; foreground service types missing on newer targetSdk; native SDK not 16 KB aligned.

## Verify
`bundleRelease` succeeds with R8 · release build installed from the AAB on an emulator and smoke-tested · versionCode/versionName, targetSdk and minSdk reported · mapping file archived · signature verified · upload done only after the user's consent, with track and rollout reported.
