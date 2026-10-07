# Motion graphics: code-based motion

- **Lottie** (Bodymovin or LottieFiles plugin in AE; AE needs "Allow Scripts to Write Files and Access
  Network"). Safe subset on Android, iOS and web: shapes, fills/strokes/gradients, transforms, parenting,
  trim paths, precomps, masks add/subtract, alpha mattes, images (Lottie-Windows also lacks polystar,
  per-shape trim paths, inverted mattes and text). Per the official support matrix:
  expressions and layer effects (fill, stroke, tint, tritone) work only on web; luma mattes are unsupported
  on Android/iOS/Windows; merge paths only on Android and Windows; mask intersect not on web; lighten/darken/
  difference/feather masks nowhere; text path, range selectors and auto-orient web only; time remap not on
  Windows. Convert text to glyphs for fidelity. Embedded raster images bloat the JSON. dotLottie (`.lottie`)
  is LottieFiles' zipped superset (JSON + assets); the Lottie Animation Community (Linux Foundation) is
  formalizing the spec. Test in each target runtime (lottie-web, dotlottie-web, lottie-ios, lottie-android).
- **CSS/SVG**: animate `transform` and `opacity` (compositor-friendly); `cubic-bezier()` curves; `linear()`
  easing encodes springs and bounces (Chrome 113, Firefox 112, Safari 17.2); Web Animations API
  (`el.animate()`); SVG line draw via `stroke-dasharray`/`stroke-dashoffset` from `getTotalLength()`;
  `transform-box: fill-box; transform-origin: center` to spin SVG parts about themselves. Scroll-driven
  animations: Chrome 115+ and Safari 26, not shipped in Firefox (progressive enhancement). View Transitions:
  Chrome 111, Safari 18, Firefox 144. Always honor `@media (prefers-reduced-motion: reduce)`.
- **Remotion** (React → video): `useCurrentFrame()`, `useVideoConfig()`, `interpolate(frame, [0, 20], [0, 1],
  {extrapolateRight: 'clamp'})`, `spring({frame, fps, config: {damping}})`, `<Sequence from durationInFrames>`,
  seeded `random('key')` (never `Math.random()`); render `npx remotion render <entry> <composition-id> out.mp4
  --codec h264` (also `h265`, `av1`, `prores`). Licence: source-available; free for individuals, for-profit
  organizations with up to 3 employees, non-profits and evaluation; larger companies need a paid Company
  License (remotion.pro); terms change in Remotion 5.0. Re-read LICENSE.md before recommending it.
- Rive (MIT runtimes, proprietary editor) suits interactive state-machine UI animation; Lottie suits
  linear playback exported from AE.
