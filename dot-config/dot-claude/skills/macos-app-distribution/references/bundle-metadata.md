# Bundle metadata: Info.plist, icons, file types and URL schemes

## Info.plist
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

## File types and URL schemes
- `CFBundleDocumentTypes`: `LSItemContentTypes` (UTIs), `CFBundleTypeRole` (`Editor`/`Viewer`), `LSHandlerRank` (`Owner`/`Default`/`Alternate`). Own formats: declare them in `UTExportedTypeDeclarations` (`UTTypeIdentifier`, `UTTypeConformsTo` e.g. `public.plain-text`, `UTTypeTagSpecification` → `public.filename-extension`); formats owned by others go in `UTImportedTypeDeclarations`.
- URL schemes: `CFBundleURLTypes` → `CFBundleURLName` + `CFBundleURLSchemes`.
- Delivery: Apple Events → `application:openURLs:` on the app delegate (files arrive as `file://` URLs). winit (and iced) don't surface these; register your own `NSApplicationDelegate` via `objc2-app-kit` (details in `rust-native-gui`). Works only from a bundled app registered with LaunchServices; inspect registrations with `/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister -dump`.
- URLs and opened files are untrusted input: validate, never execute (`secure-coding`).
