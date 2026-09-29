---
name: frontend-frameworks
description: Load before building or changing a web front end — React 19 + Compiler, Next.js 16, Svelte 5, Vue, Astro 7, Tailwind v4, modern CSS, Core Web Vitals.
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

## Next.js 16 (upgrade guide checked Sep 2026)
- Node ≥ 20.9, TypeScript ≥ 5.1; browsers Chrome/Edge/Firefox 111+, Safari 16.4+.
- **Turbopack is the default** for `next dev` and `next build`; a custom `webpack` config makes `next build` fail — migrate, or opt out with `--webpack`. `turbopack` config is top-level (no longer `experimental`).
- **`middleware.ts` → `proxy.ts`**, export `proxy`; runs on Node.js only (keep `middleware` for edge runtime); `skipMiddlewareUrlNormalize` → `skipProxyUrlNormalize`.
- Request APIs are async only: `await cookies()`, `await headers()`, `await draftMode()`, `await props.params`, `await props.searchParams`; `npx next typegen` generates `PageProps<'/route'>` helpers.
- Caching: opt-in Cache Components (`cacheComponents: true`, `'use cache'`, `cacheLife`, `cacheTag` — no `unstable_` prefix). `revalidateTag(tag, 'max')` needs a profile; `updateTag` (Server Actions) for read-your-writes; `refresh()` refreshes the client router.
- `reactCompiler: true` is stable but off by default. `next lint` removed (run ESLint/Biome directly); AMP, `serverRuntimeConfig`/`publicRuntimeConfig` removed; parallel-route slots need `default.js`; `next/image` defaults changed (`minimumCacheTTL` 4 h, `qualities: [75]`, local IPs blocked, max 3 redirects).
- Upgrade: `npx @next/codemod@canary upgrade latest`, then `npx @next/codemod@canary next-async-request-api .` if sync access remains.
- `NEXT_PUBLIC_*` (and Vite's `VITE_*`) values are inlined into client bundles: public by definition.

## Svelte 5, Vue 3, Astro 7
- **Svelte 5 runes**: `$state`, `$derived`, `$effect`, `$props`, `$bindable`; `onclick={…}` replaces `on:click`; callback props replace `createEventDispatcher`; snippets (`{#snippet}` / `{@render children()}`) replace slots; `mount()` replaces `new App()`. Migrate with `npx sv migrate svelte-5`. Stores still work; runes in `.svelte.js/.ts` files share state.
- **Vue 3.5**: `<script setup lang="ts">`, `defineProps` with destructured defaults, `defineModel`, composables for shared logic, Pinia for global state.
- **Astro 7**: islands (`client:load|idle|visible|only`), content collections; Rust compiler rejects unclosed tags and no longer auto-corrects invalid HTML; `.md/.mdx` render with Sätteri — remark/rehype plugins need `@astrojs/markdown-remark` and `markdown.processor: unified()`; `compressHTML` defaults to `'jsx'` (may eat spaces between inline elements); `@astrojs/db` removed. Upgrade with `npx @astrojs/upgrade`.

## Tailwind CSS v4
- `@import "tailwindcss";` replaces the `@tailwind` directives; theme in CSS: `@theme { --color-brand-500: oklch(…); --font-display: …; }`; custom utilities with `@utility`; legacy JS config only via `@config "./tailwind.config.js"` (no `corePlugins`, `safelist`, `separator`; safelist with `@source inline()`).
- Plugins: `@tailwindcss/vite` (preferred) or `@tailwindcss/postcss`; CLI `npx @tailwindcss/cli`. Upgrade: `npx @tailwindcss/upgrade` (Node ≥ 20) on a branch, then review.
- Browser floor: Safari 16.4+, Chrome 111+, Firefox 128+ (stay on 3.4 for older).
- Renamed scale: `shadow-sm→shadow-xs`, `shadow→shadow-sm`, same for `rounded`, `blur`, `drop-shadow`; `outline-none→outline-hidden`; `ring` is 1px `currentColor` (`ring-3` for old look); default border color `currentColor`; `!` goes at the end (`flex!`); `bg-(--var)` for CSS variables.

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
