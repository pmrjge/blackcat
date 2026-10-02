---
name: frontend-frameworks
description: Use for web front ends — React 19, Next.js 16, Svelte 5, Vue, Astro, Tailwind v4, Web Vitals.
---
# Front-end frameworks and web performance

## Scope
Framework, styling and performance decisions for web UIs. Language, tsconfig, bundlers, linting and tests → `typescript-engineering`; accessibility → `web-accessibility`; tokens and component specs from design → `ui-design-systems`; Markdown/MDX sites and Astro content → `markdown-publishing`; browser checks → `browser-automation`.

## Detect, then follow the project
Read the lockfile, `package.json`, framework config (`next.config.*`, `svelte.config.*`, `astro.config.*`, `vite.config.*`) and the styling approach before writing code. Never mix in a second framework, state library or CSS system. Check the installed major against the table; framework docs ship version-matched in `node_modules` for Next.js ≥ 16.2 (`node_modules/next/dist/docs/`).

| Package (npm, 2026-09-29) | Current | Changed recently |
|---|---|---|
| react / react-dom | 19.3.0 | Actions, `use`, `useActionState`, `useOptimistic`, `<Activity>` and `useEffectEvent` (19.2) |
| babel-plugin-react-compiler | 1.0.0 (stable 2025-10-07) | auto-memoization |
| next | 16.3.6 | see below |
| svelte | 5.57.1 | runes |
| vue | 3.5.43 | `<script setup>`, `defineModel`, reactive props destructure |
| astro | 7.3.5 | Rust compiler, Vite 8, Sätteri Markdown |
| tailwindcss | 4.3.3 | CSS-first config |

## React 19 and React Compiler
- Server vs client: in RSC frameworks components are server by default; `'use client'` marks the boundary — keep it low in the tree; pass serializable props only; `'use server'` functions are public endpoints (validate and authorize inside).
- Forms: `<form action={fn}>` + `useActionState` for pending/error state, `useOptimistic` for optimistic UI.
- React Compiler 1.0 memoizes automatically (React 17+; below 19 needs `react-compiler-runtime` and a `target`). New code: skip `useMemo`/`useCallback`/`memo` unless you need a stable identity for an effect dependency. Existing memoization: leave it or remove only with tests. Pin the plugin exactly (`--save-exact`). Lint with `eslint-plugin-react-hooks@latest` (`reactHooks.configs.flat.recommended`), which replaces `eslint-plugin-react-compiler`.
- Effects are for synchronizing with external systems, not for deriving state; derive during render.

## Framework version notes
Read `references/framework-versions.md` before upgrading or writing Next.js 16, Svelte 5, Vue 3, Astro 7 or Tailwind v4 code (breaking changes, defaults, new APIs).

## Modern CSS worth using
Container queries (`container-type: inline-size`, `@container`), `:has()`, cascade layers (`@layer`), subgrid, `clamp()` fluid type, logical properties (`margin-inline`, `inset-block`), `color-mix()` and OKLCH, `@starting-style` and view transitions for enter animations, `prefers-reduced-motion`/`prefers-color-scheme` queries. Check support on caniuse or MDN Baseline for the project's browser floor.

## Core Web Vitals
- Targets at the 75th percentile, mobile and desktop separately: **LCP ≤ 2.5 s, INP ≤ 200 ms, CLS ≤ 0.1**. INP replaced FID in 2024.
- LCP: server-render the hero, `fetchpriority="high"` on the LCP image, no lazy-loading above the fold, preload the hero font, cut TTFB (caching, streaming).
- INP = input delay + processing + presentation delay. Keep handlers small, yield in long work (`scheduler.yield()` where supported, else `setTimeout`), avoid layout thrash, keep the DOM small, `content-visibility: auto` for off-screen sections, move heavy work to workers.
- CLS: `width`/`height` or `aspect-ratio` on media, reserve space for ads/embeds, `font-display: optional|swap` with metric-compatible fallbacks (`size-adjust`), no content inserted above existing content.
- Images: `srcset`/`sizes`, AVIF/WebP, framework image components; JS: route-level code splitting, third-party scripts deferred or removed.
- Measure: Lighthouse 13 (`npx lighthouse <url> --preset=desktop` or throttled mobile default) in the lab; field data with `web-vitals` 6 (`import {onLCP, onINP, onCLS} from 'web-vitals/attribution'` — INP attribution includes `longAnimationFrameEntries`), CrUX/PageSpeed Insights. Set per-route budgets and compare before/after on the same profile.

## Common failures
Hydration mismatches (dates, random ids, `window` during SSR → `useId`, client-only islands, `suppressHydrationWarning` only for known text); client-only APIs in server code; secrets in public env vars; unbounded client bundles from barrel imports; layout shift from late fonts.

## Verify before reporting
Build passes; Playwright at 375/768/1440 with no console errors or failed requests; keyboard pass and axe scan (`web-accessibility`); Lighthouse or web-vitals numbers before/after.

Sources (checked 2026-09-29): https://nextjs.org/docs/app/guides/upgrading/version-16 · https://react.dev/blog/2025/10/07/react-compiler-1 · https://tailwindcss.com/docs/upgrade-guide · https://svelte.dev/docs/svelte/v5-migration-guide · https://docs.astro.build/en/guides/upgrade-to/v7/ · https://web.dev/articles/vitals · https://web.dev/articles/optimize-inp · https://github.com/GoogleChrome/web-vitals · registry.npmjs.org (versions above)
