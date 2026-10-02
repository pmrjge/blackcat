---
name: swiftui
description: Load for SwiftUI views — @Observable state, data flow, NavigationStack, lists, previews, UIKit interop; CLI builds are in ios-build-sim.
---
# SwiftUI

Baseline and language rules: `swift-engineering`. Visual design: `ui-design-systems`; accessibility: `a11y-mobile`.

## State and data flow
| need | use |
|---|---|
| view-local value state | `@State` (private) |
| reference model owned by the view | `@State var model = Model()` with `@Observable` class |
| model passed down, read-only use | plain property (Observation tracks reads) |
| two-way binding into a child | `@Binding`, or `@Bindable var model` for an `@Observable` |
| app-wide dependency | `.environment(model)` + `@Environment(Model.self)` |
| persisted small settings | `@AppStorage` / `@SceneStorage` |
| persisted data | SwiftData (`@Model`, `@Query`) or your own store behind a model |
- New code uses the Observation framework (`@Observable`); `ObservableObject`/`@Published`/`@StateObject` only in code that targets OS versions before Observation or already uses them.
- Views are cheap value descriptions: no work in `init` or `body` beyond layout; side effects in `.task {}` (auto-cancelled when the view disappears), `.onChange(of:)`, or model methods.
- One source of truth per piece of state; derived values are computed, not stored.
- `@MainActor` models (or main-actor default isolation); heavy work moves off the main actor and results hop back.

## Navigation and structure
- `NavigationStack(path:)` with a typed path and `.navigationDestination(for:)`; `NavigationSplitView` for sidebars on iPad/macOS. No `NavigationView` in new code.
- Sheets and alerts driven by optional/identifiable state (`.sheet(item:)`).
- Deep links: map URLs into the navigation path in one place.
- Split large views into small subviews with explicit inputs; extract `ViewModifier`s for repeated styling.

## Lists and performance
- `List`/`LazyVStack` with stable `id`s (never array indices for mutable collections).
- Avoid `AnyView`; use `@ViewBuilder` and generics. Avoid recomputing formatters in `body` (static or cached).
- Profile with Instruments' SwiftUI template (view body counts, hitches) before optimizing; `Self._printChanges()` in debug builds to see why a body re-ran.
- Images: `AsyncImage` for simple cases; a caching loader for feeds.

## Layout and adaptivity
- Dynamic Type everywhere (`.font(.body)`, no fixed sizes for text), `ViewThatFits`, `Layout` protocol for custom layouts, size classes for compact/regular.
- Respect safe areas; test dark mode, larger accessibility sizes, right-to-left (`.environment(\.layoutDirection, .rightToLeft)` in previews), and landscape.
- Labels for every icon-only control (`Label`, `.accessibilityLabel`).

## Previews
`#Preview { … }` with sample data from a preview container; previews must not hit the network or real stores. Multiple previews for states (empty, loading, error, long text, RTL, large type).

## UIKit and AppKit interop
`UIViewRepresentable`/`UIViewControllerRepresentable` with a `Coordinator` for delegates; update only what changed in `updateUIView`; `UIHostingController` to embed SwiftUI in UIKit.

## Testing
- Logic lives in models and is unit-tested with Swift Testing.
- UI: XCUITest with accessibility identifiers (`.accessibilityIdentifier`); snapshot tests (e.g. swift-snapshot-testing) for visual regressions, recorded on a fixed simulator and OS.

## Pitfalls
Creating `@Observable` models in `body` or as plain `let` in a view that recreates them; `@State` initialized from a parameter (only the first value sticks — use `.onChange` or identity); `.onAppear` + `Task {}` instead of `.task`; `GeometryReader` everywhere; ids that change on every update (lost state, broken animations).

## Verify
Builds in Swift 6 mode · previews render for all states · UI test or snapshot covering the change passes on the pinned simulator · Dynamic Type XXL, dark mode and RTL checked · no main-thread hitches in Instruments for the changed screen when performance was in scope.
