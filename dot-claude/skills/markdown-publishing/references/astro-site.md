# Markdown publishing: Astro 7 site

Scaffold: `npm create astro@latest site -- --template blog` (the example already has MDX, RSS, sitemap and
sharp; elsewhere `npx astro add mdx sitemap`), then `npm install @astrojs/markdown-remark remark-math rehype-katex katex`.
```js
// astro.config.mjs
import { defineConfig } from 'astro/config';
import { unified } from '@astrojs/markdown-remark';
import mdx from '@astrojs/mdx';
import sitemap from '@astrojs/sitemap';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';

export default defineConfig({
  site: 'https://example.org',                 // required by sitemap, RSS, canonical URLs
  integrations: [mdx(), sitemap()],            // MDX inherits markdown.processor
  image: { layout: 'constrained', responsiveStyles: true },
  markdown: {
    processor: unified({
      remarkPlugins: [remarkMath],
      rehypePlugins: [[rehypeKatex, { macros: { '\\R': '\\mathbb{R}' } }]],
    }),
    syntaxHighlight: { type: 'shiki', excludeLangs: ['mermaid', 'math'] },
    shikiConfig: { themes: { light: 'github-light', dark: 'github-dark' }, wrap: true },
  },
});
```
```ts
// src/content.config.ts
import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { z } from 'astro/zod';

const blog = defineCollection({
  loader: glob({ base: './src/content/blog', pattern: '**/*.{md,mdx}' }),
  schema: ({ image }) => z.object({
    title: z.string().max(70),
    description: z.string().max(160),
    pubDate: z.coerce.date(),
    updatedDate: z.coerce.date().optional(),
    draft: z.boolean().default(false),
    tags: z.array(z.string()).default([]),
    cover: image().optional(),                 // relative path in frontmatter, validated and optimized
    coverAlt: z.string().optional(),
  }),
});
export const collections = { blog };
```
```astro
---
// src/pages/blog/[...id].astro
import { getCollection, render } from 'astro:content';
import { Image } from 'astro:assets';
import Base from '../../layouts/Base.astro';
export async function getStaticPaths() {
  const posts = await getCollection('blog', ({ data }) => !data.draft);
  return posts.map((post) => ({ params: { id: post.id }, props: { post } }));
}
const { post } = Astro.props;
const { Content, headings } = await render(post);
---
<Base title={post.data.title} description={post.data.description}>
  <article>
    <h1>{post.data.title}</h1>
    {post.data.cover && <Image src={post.data.cover} alt={post.data.coverAlt ?? ''} width={1200} priority />}
    <Content />
  </article>
</Base>
```
```js
// src/pages/rss.xml.js
import rss from '@astrojs/rss';
import { getCollection } from 'astro:content';
export async function GET(context) {
  const posts = await getCollection('blog', ({ data }) => !data.draft);
  return rss({ title: 'Blog', description: 'Posts', site: context.site,
    items: posts.map((p) => ({ title: p.data.title, description: p.data.description, pubDate: p.data.pubDate, link: `/blog/${p.id}/` })) });
}
```
The layout imports `katex/dist/katex.min.css` once and sets `<title>`, description, canonical
(`new URL(Astro.url.pathname, Astro.site)`), `og:title`, `og:description`, `og:url`, `og:image` (absolute
URL, 1200×630), `twitter:card=summary_large_image`, and an RSS `<link rel="alternate">`.

Astro 7 specifics and pitfalls:
- Markdown renders with Sätteri (Rust) by default. remark/rehype plugins need `@astrojs/markdown-remark` and
  `processor: unified({…})`; top-level `markdown.remarkPlugins`/`rehypePlugins` are deprecated. Sätteri parses
  math but rendering it needs a plugin (the ecosystem is young): use `unified()` for math and Mermaid.
- The Rust compiler rejects unclosed tags and no longer repairs invalid nesting (`<div>` inside `<p>`);
  `compressHTML: 'jsx'` is the default and drops whitespace between inline elements (write `{" "}` or set
  `compressHTML: true`); `src/fetch.ts` is a reserved routing file.
- Collections: entry `id` comes from the file name (`slug:` in frontmatter overrides); `render(entry)` from
  `astro:content` (not `entry.render()`); `z` from `astro/zod` is Zod 4. Schema failures stop the build with
  `[InvalidContentEntryDataError] blog → <id> data does not match collection schema.` plus one line per field.
- Code: with dual Shiki themes the light colors are inline and the dark ones are CSS variables; add the
  documented rule (`.astro-code, .astro-code span { color: var(--shiki-dark) !important; … }` inside
  `prefers-color-scheme: dark` or a theme class). `defaultColor: false` removes the inline default so both themes
  come from your CSS. `<Code />` from `astro:components` highlights code inside `.astro` files.
- Mermaid: build-time `rehype-mermaid` (`[rehypeMermaid, {strategy: 'img-svg', dark: true}]` inside `unified()`;
  needs `playwright` and `npx playwright install chromium`), or ship `mermaid` client-side for `<pre class="mermaid">`.
- MDX: `import` components at the top of the `.mdx` file; map Markdown elements with
  `<Content components={{ h2: MyHeading }} />`; `<Image>`/`<Picture>` work in MDX, not in `.md`.
- Images: `![alt](./x.png)` in `src/` is optimized and gets `srcset`, `sizes`, width/height, lazy loading;
  `<Picture formats={['avif', 'webp']} />` for art-directed formats; `priority` on the LCP image; `public/`
  files are served untouched.
- Open Graph images per post: static exports, or generated at build with `satori` + `@resvg/resvg-js` or `astro-og-canvas`.
- Build and deploy: `npx astro build` → `dist/` (static by default), `npx astro preview` to test. GitHub Pages:
  `withastro/action@v6` + `actions/deploy-pages@v5`; project pages need `site` plus `base: '/repo'` and
  links built from `import.meta.env.BASE_URL`. Any static host (Cloudflare, Netlify, Vercel) serves `dist/`.
  `npx astro check` (with `@astrojs/check` and `typescript`) type-checks templates.
