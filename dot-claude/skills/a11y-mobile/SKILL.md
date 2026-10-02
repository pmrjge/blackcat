---
name: a11y-mobile
description: Use when making an iOS, Android, Flutter or React Native app accessible — platform APIs, Dynamic Type, audits; web UI is a11y-aria-patterns.
---
# Mobile accessibility
Hub: `web-accessibility` (target, legal frame, contrast); report format: `a11y-audit`. The same WCAG 2.2 AA success criteria apply to apps through W3C's WCAG2ICT guidance; the European Accessibility Act covers the apps of covered services (banking, e-commerce, transport, e-books) — scope details unverified here, see the hub's legal frame.

## Baseline for every platform
- Every interactive element has an accessible name, a role/trait and its state (selected, expanded, disabled); decorative images are hidden from assistive tech.
- Touch targets: at least 44×44 pt on iOS and 48×48 dp on Android (also the Flutter test guidelines); spacing so adjacent targets don't overlap.
- Text scales with the system setting (Dynamic Type, Android font scale) up to the largest accessibility sizes without truncation or overlap; layouts reflow rather than clip.
- Contrast and color rules as in the hub (§4), checked in light and dark mode.
- Focus/reading order follows the visual order; custom views group related content (a card reads as one element with one action).
- Every gesture has a simple alternative (custom swipe actions exposed as accessibility actions; no path-based or multi-finger gesture as the only way).
- Respect Reduce Motion / Remove animations, Bold Text, and reduced transparency where the platform exposes them.
- Announce async changes (toasts, errors, loading done) through the platform's announcement API; move focus to new screens' titles and to errors on submit.

## Platform APIs
| Platform | Name / role / state | Grouping and actions | Announce |
|---|---|---|---|
| SwiftUI | `.accessibilityLabel`, `.accessibilityAddTraits`, `.accessibilityValue`, `.accessibilityHint` | `.accessibilityElement(children: .combine)`, `.accessibilityAction` | `AccessibilityNotification.Announcement` |
| UIKit | `accessibilityLabel`, `accessibilityTraits`, `accessibilityValue` | `isAccessibilityElement`, `accessibilityCustomActions` | `UIAccessibility.post(notification: .announcement, …)` |
| Jetpack Compose | `contentDescription`, `Modifier.semantics { role = …; stateDescription = … }` | `Modifier.semantics(mergeDescendants = true)`, `customActions` | `liveRegion` semantics |
| Android Views | `contentDescription`, `importantForAccessibility` | `ViewCompat.addAccessibilityAction` | `accessibilityLiveRegion` |
| Flutter | `Semantics(label:, button:, value:)`, `MergeSemantics`, `ExcludeSemantics` | `Semantics(customSemanticsActions: …)` | `SemanticsService.announce` |
| React Native | `accessibilityLabel`, `accessibilityRole` (or `role`), `accessibilityState`, `accessibilityHint`, `accessible` | `accessibilityActions` + `onAccessibilityAction` | `AccessibilityInfo.announceForAccessibility` |

API names in this table are from general knowledge (unverified as of 2026-10-02): confirm against the platform docs for the SDK version in the project.

## Automated checks
- iOS: XCUITest `try app.performAccessibilityAudit()` (Xcode 15 / iOS 17+; unverified) in UI tests; Accessibility Inspector audits in Xcode.
- Android Compose: `enableAccessibilityChecks()` (Compose 1.8+; `androidx.compose.ui:ui-test-accessibility` for `ComposeUiTest`, API 34, experimental; `ui-test-junit4-accessibility` for the JUnit4 rule). Views/Espresso: `AccessibilityChecks.enable()` from `espresso-accessibility` (unverified). Accessibility Scanner app for manual sweeps.
- Flutter: in widget tests `await expectLater(tester, meetsGuideline(androidTapTargetGuideline))`, plus `iOSTapTargetGuideline`, `labeledTapTargetGuideline`, `textContrastGuideline`.
- React Native: lint rules for missing labels/roles and screen-reader checks in e2e (tooling unverified here).

## Manual pass (always)
1. VoiceOver (iOS) and TalkBack (Android): swipe through every screen, operate each control, complete the main flows, check announcements of errors and loading.
2. Largest text size and display zoom: no clipped or overlapping text, scrolling works.
3. Switch Control / Switch Access and a hardware keyboard: everything reachable, focus visible.
4. Reduce Motion, dark mode, increased contrast / bold text.

## Verify
- [ ] Automated audit runs in CI for the key screens and passes (or each finding has an issue).
- [ ] Manual screen-reader pass recorded per platform with device, OS and assistive-tech versions.
- [ ] Report in the `a11y-audit` format, with platform and OS versions tested.

## Sources
- Verified 2026-10-02 https://developer.android.com/develop/ui/compose/accessibility/testing — `enableAccessibilityChecks()`, Compose 1.8, artifacts, API 34, experimental.
- Verified 2026-10-02 https://docs.flutter.dev/ui/accessibility/accessibility-testing — the four guideline names; Android 48×48, iOS 44×44.
- Verified 2026-10-02 https://www.w3.org/TR/wcag2ict-22/ — "Guidance on Applying WCAG 2 to Non-Web ICT", W3C Group Note, 11 Dec 2025.
- Unverified as of 2026-10-02: Apple HIG 44×44 pt and Android 48×48 dp platform guidance pages (the numbers match Flutter's guidelines above); `performAccessibilityAudit` availability; Espresso `AccessibilityChecks`.
