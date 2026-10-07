# Framework version notes (Next.js 16, Svelte 5, Vue 3, Astro 7, Tailwind v4)

Part of `frontend-frameworks`.

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
