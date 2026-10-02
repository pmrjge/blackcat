---
name: ui-design-systems
description: Load before designing UI screens or a component library — DTCG tokens, spacing and type scales, states, dark mode.
---
# UI design systems and design-to-code handoff

## Scope
Visual design of app and web interfaces and the contract between designer and front-end engineer. Type choice and scales → `typography`; color science and contrast math → `color-management`; accessibility criteria → `web-accessibility`; brand marks → `brand-identity`; motion design → `motion-graphics`; implementing in React/Svelte/Tailwind → `frontend-frameworks`.

## 1. Token architecture
- Three tiers: **primitive** (raw palette and scales: `color.blue.600`, `space.4`) → **semantic** (role: `color.text.primary`, `color.surface.raised`, `color.border.focus`, `space.inset.md`) → **component** (only when a component needs to diverge: `button.primary.bg`). Components consume semantic tokens; themes swap semantic → primitive mappings.
- Modes: light/dark (and high-contrast, density) as alternate semantic sets, never as separate component styles.
- Naming: lowercase, dot/hyphen path, role before variant (`color.text.danger`, not `red-text`); no values in names (`space.4` means step 4, not 4 px).

## 2. DTCG format 2025.10 (first stable version, Oct 2025)
Files `*.tokens` or `*.tokens.json` (`application/design-tokens+json`).
```json
{
  "color": {
    "$type": "color",
    "blue": { "600": { "$value": { "colorSpace": "srgb", "components": [0.145, 0.388, 0.922], "hex": "#2563eb" } } },
    "text": { "link": { "$value": "{color.blue.600}", "$description": "Links on default surfaces" } }
  },
  "space": { "$type": "dimension", "4": { "$value": { "value": 16, "unit": "px" } } },
  "motion": { "fast": { "$type": "duration", "$value": { "value": 150, "unit": "ms" } } }
}
```
- A token has `$value` (required), optional `$type` (inherited from the nearest group; tools must not guess it), `$description`, `$deprecated`, `$extensions` (vendor data, preserved). Names can't start with `$` or contain `{ } .`.
- Aliases: `"{group.token}"` (whole token) or JSON Pointer `{"$ref": "#/color/blue/600/$value/components/0"}`; circular references are errors. Groups can `$extends` another group; `$root` names a group's own default token (`{color.accent.$root}`).
- Types: `color` (object with `colorSpace`, `components`, optional `alpha`/`hex`), `dimension` (`{value, unit: px|rem}`, unit required even for 0), `duration` (`ms|s`), `cubicBezier`, `number`, `fontFamily`, `fontWeight` (1–1000 or names), `strokeStyle`, and composites `border`, `transition`, `shadow`, `gradient`, `typography`.
- Older token files use pre-2025 forms (color as a hex string, dimension as `"16px"`): convert when adopting the spec.
- Build to code with Style Dictionary 5 (5.5.5): DTCG supported since v4, **2025.10 only partially** (work tracked in its issue #1590) — check that color objects and dimension objects convert correctly, or pre-process them. Outputs: CSS custom properties (`--color-text-link`), Tailwind v4 `@theme` variables, iOS/Android resources.

## 3. Scales
- Spacing on a 4 px base (4, 8, 12, 16, 24, 32, 48, 64…); components snap to it; layout gaps use the larger steps.
- Type scale from `typography` (ratio or hand-tuned steps), line-heights on the 4 px grid for UI text; minimum 16 px body on web, 12–14 px only for secondary labels.
- Radius, border width, elevation (shadow + surface tint pairs per level), z-index layers, opacity and motion (durations 100–300 ms UI, easing tokens) all tokenized.

## 4. Component spec sheet (one per component)
- Anatomy with named parts; sizes (sm/md/lg) with exact paddings, heights and icon sizes in tokens.
- **Every state**: default, hover, focus-visible (designed ring, ≥ 3:1 contrast, not obscured), active/pressed, selected, disabled (and why — prefer explaining over disabling), loading, error/invalid, empty, read-only; dark-mode variant of each.
- Behaviour: keyboard interaction (reference the APG pattern), touch target ≥ 24 px (WCAG 2.2 AA minimum; 44 pt Apple HIG, 48 dp Material recommended for touch), responsive behaviour, truncation/wrapping rules, max lengths, content guidelines (labels, microcopy, error text).
- Do/don't examples; accessibility notes (name, role, announced state).

## 5. Layout
- Breakpoints aligned with the front-end verification widths: 375 (mobile), 768 (tablet), 1440 (desktop); define container max-widths, gutters and margins per breakpoint; 4/8/12-column grids.
- Content-first: design the smallest width first, then add columns; specify what reflows, hides or collapses.
- Density and safe areas (notches, home indicators) for mobile apps.

## 6. Dark mode and theming
Semantic colors per mode (not inverted primitives); surfaces get lighter with elevation in dark mode; desaturate saturated brand colors on dark surfaces; re-check every text/UI contrast pair per mode (`color-management`); images and illustrations with dark variants or neutral backgrounds; charts keep categorical colors distinguishable in both.

## 7. Platform conventions
Apple HIG (navigation bars, tab bars, SF Symbols, Dynamic Type, 44 pt targets) vs Material 3 (top app bars, navigation rail/bar, dynamic color, 48 dp targets) vs web conventions. Follow the platform for native apps; for cross-platform web UIs pick one system and apply it consistently.

## 8. Handoff package (what the engineer receives)
1. `tokens.json` (DTCG) + generated CSS/Tailwind theme, versioned.
2. Component spec sheets (above) and page layouts at 375/768/1440 with annotations for spacing tokens, reading/focus order and responsive behaviour.
3. Assets: icons and illustrations as optimized SVG (`svg-vector-craft`), raster at 1×/2× in WebP/AVIF + PNG fallback; fonts with licences (`typography`).
4. Interaction notes: transitions with duration/easing tokens, reduced-motion alternative.
5. Open questions list. The engineer must not invent colors, spacing, states or copy — missing items go back to design.

## Review checklist
Tokens tiered and named by role · every component state designed (focus included) · contrast checked per mode · targets ≥ 24 px (44/48 recommended) · layouts at the three widths · reduced-motion variant · handoff package complete · DTCG file validates and builds.

Sources (checked 2026-09-29): https://www.designtokens.org/TR/2025.10/format/ · https://www.w3.org/community/design-tokens/2025/10/28/design-tokens-specification-reaches-first-stable-version · https://styledictionary.com/info/dtcg/ · https://github.com/style-dictionary/style-dictionary/releases (v5.5.5) · https://developer.apple.com/design/human-interface-guidelines/ · https://m3.material.io/ · https://www.w3.org/TR/WCAG22/
