---
name: react-native
description: Use for React Native and Expo apps — New Architecture, native modules, tests, EAS builds.
---
# React Native and Expo

TypeScript rules: `typescript-engineering`. Platform release: `app-store-release`, `android-release`. Device installs, EAS Submit and store uploads need the user's consent.

## Baseline
- react-native 0.87.1 — Verified 2026-10-02 https://www.npmjs.com/package/react-native
- The New Architecture (Fabric, TurboModules, JSI) is the only architecture from 0.82; the opt-out flags are ignored — Verified 2026-10-02 https://reactnative.dev/blog/2025/10/08/react-native-0.82
- Expo SDK 57 stable (2026-06-30), SDK 58 in beta — Verified 2026-10-02 https://expo.dev/changelog
- Each Expo SDK pins one React Native version: upgrade with `npx expo install --fix` and the SDK's upgrade guide, never by bumping `react-native` alone.

## Project choice
- New apps: Expo (managed workflow with Continuous Native Generation — `npx expo prebuild` generates `ios/` and `android/`; config plugins hold native changes). Bare React Native only when a requirement rules Expo out.
- Libraries must support the New Architecture: check the package's docs or React Native Directory before adding it.
- Routing: Expo Router (file-based) or React Navigation, as the project already does.

## Code rules
- TypeScript strict; components as functions with hooks; state close to where it is used; server state with TanStack Query; global client state small (Zustand/Context).
- Lists: `FlatList`/`FlashList` with `keyExtractor` and memoized `renderItem`; never `ScrollView` + `map` for long lists.
- Animations and gestures on the UI thread: Reanimated + Gesture Handler (worklets), not JS-driven `Animated` loops.
- Platform differences via `Platform.select` or `.ios.tsx`/`.android.tsx` files; safe areas with `react-native-safe-area-context`.
- Native code: Expo Modules API (Swift/Kotlin) for new native modules; TurboModules with Codegen specs in bare apps.
- Secrets never in the JS bundle or `app.config` extra fields (both ship to devices); public config through `EXPO_PUBLIC_*` only for non-secrets.
- Accessibility props (`accessibilityLabel`, `accessibilityRole`) on custom touchables; respect font scaling.

## Running and debugging
- `npx expo start` (dev server), development builds with `expo-dev-client` when native modules are involved (Expo Go only runs the SDK's built-in modules).
- `npx expo run:ios` / `run:android` build locally on simulators/emulators (fine); on physical devices after consent.
- Debugging: React Native DevTools (Hermes); Flipper is gone. Performance: the Perf Monitor, Hermes sampling profiler, React Profiler; measure in release builds.

## Testing
- Jest (`jest-expo` preset) + React Native Testing Library (`render`, `screen.getByRole`, `userEvent`) for components; mock native modules at the boundary.
- E2E: Maestro (YAML flows) or Detox on simulators/emulators.
- Type check `npx tsc --noEmit`; lint with the project's ESLint config.

## Builds and release
- EAS Build (`eas build --profile production --platform all`) or local `expo run` / Xcode / Gradle builds; credentials managed by EAS or the user's store — never committed.
- `eas submit` and store uploads: consent gates. OTA updates (`eas update`) change what users run immediately: also a consent gate; keep `runtimeVersion` policy correct so updates only reach compatible binaries.

## Pitfalls
Upgrading React Native outside the Expo SDK; libraries without New Architecture support; heavy work on the JS thread during animations; inline functions and objects re-rendering list rows; forgetting `prebuild --clean` after config plugin changes; OTA update shipped to binaries with a different native layer.

## Verify
`npx tsc --noEmit` and lint clean · Jest green · `npx expo-doctor` clean (Expo projects) · E2E flow for the change passes on iOS simulator and Android emulator · release build succeeds · RN/Expo SDK versions reported.
