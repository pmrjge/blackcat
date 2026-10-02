---
name: docs-sites
description: Use to build a docs site — Zensical/MkDocs, Sphinx, Docusaurus, Starlight, VitePress.
---
# Documentation sites

Part of `technical-writing` (what goes on each page: `technical-writing` `references/docs-adr.md`, Diátaxis). Markdown conventions: `markdown-publishing`; diagrams: `diagrams-as-code`.

Versions (Verified 2026-10-02 from https://pypi.org/pypi/<name>/json and https://registry.npmjs.org/<name>/latest): zensical 0.0.67, mkdocs-material 9.7.7, mkdocs 1.6.1 (Aug 2024), mkdocstrings 1.0.6, sphinx 9.1.0, furo 2025.12.19, myst-parser 5.1.0, sphinx-autobuild 2025.8.25, @docusaurus/core 3.10.2, @astrojs/starlight 0.42.5 (astro 7.3.5), vitepress 1.6.4, typedoc 0.28.20.

## Choosing a generator
| Project | Default | Why |
|---|---|---|
| Python library, Markdown docs | Zensical (reads `mkdocs.yml`) or MkDocs Material | API pages from docstrings via mkdocstrings; search built in |
| Python with heavy cross-references, intersphinx, PDF | Sphinx + MyST (Markdown) + furo theme | autodoc, intersphinx, LaTeX/PDF builder |
| JS/TS project, versioned docs, i18n, blog | Docusaurus | React/MDX, doc versioning, i18n |
| Fast static docs, any stack | Astro Starlight | Markdown/MDX, built-in search (Pagefind), i18n, small JS |
| Vue ecosystem, minimal config | VitePress | Vite-based, Markdown with Vue components |
| TS API reference | TypeDoc (standalone, or as a plugin) | generated from types and TSDoc |

MkDocs status (Verified 2026-10-02 https://squidfunk.github.io/mkdocs-material/blog/): Material for MkDocs entered maintenance mode on 2025-11-11 (9.7.0 the final feature release, critical and security fixes for at least 12 months); its authors call MkDocs 1.x unmaintained and MkDocs 2.0 a breaking rewrite still in pre-release; their successor Zensical reads `mkdocs.yml` but supports only a subset of plugins. New projects: prefer Zensical or another generator; existing MkDocs Material sites keep working, pin versions and check plugin support before migrating.

## Setup sketches
Zensical's subcommands were checked with `zensical --help` on 0.0.67 (2026-10-02); the other commands were not re-run here (unverified: check each tool's `--help` first).
- Zensical: `uv add --dev zensical`, `uv run zensical new .`, `uv run zensical serve`, `uv run zensical build` (pre-1.0: the CLI moves fast).
- MkDocs Material: `uv add --dev mkdocs-material "mkdocstrings[python]"`, `uv run mkdocs serve`, `uv run mkdocs build --strict` (warnings become errors).
- Sphinx: `uv add --dev sphinx furo myst-parser sphinx-autobuild`, `uv run sphinx-quickstart docs`, `uv run sphinx-autobuild docs docs/_build/html`, CI: `uv run sphinx-build -W --keep-going -b html docs docs/_build/html` (`-W` warnings are errors), `-b linkcheck` for links.
- Docusaurus: `npx create-docusaurus@latest site classic --typescript`, `npm run start`, `npm run build` (fails on broken links by default: `onBrokenLinks`).
- Starlight: `npm create astro@latest -- --template starlight`, `npm run dev`, `npm run build`.
- VitePress: `npx vitepress init`, `npx vitepress dev docs`, `npx vitepress build docs`.

## Practice
- Navigation mirrors Diátaxis: tutorials, how-to guides, reference, explanation as top-level sections.
- Reference pages are generated from code (mkdocstrings, autodoc, TypeDoc), never hand-copied; prose pages live beside the code in the same repository and change in the same commit.
- Versioned docs only when users run several versions at once (Docusaurus versions, `mike` for MkDocs, Read the Docs for Sphinx); otherwise publish `main` plus the latest release.
- Hosting: GitHub/Forgejo Pages, Read the Docs, Netlify, Cloudflare Pages, or the self-hosted Caddy in `ops-systemd-caddy`. Publishing to a public host is the user's step.
- Build in CI with strict flags; fail on broken links and missing references; set `site_url`/`url` so canonical links and the sitemap are right.
- Search: built-in (MkDocs/Zensical, Starlight's Pagefind, VitePress local search) before an external service.
- Accessibility: headings in order, alt text on every image, sufficient contrast in the theme's light and dark modes (`web-accessibility`).

## Verify
- The strict build (`mkdocs build --strict`, `sphinx-build -W`, `npm run build`) passes with zero warnings; link check passes.
- Every code sample on the site is executed in CI (doctests or extracted blocks); the generated API reference matches the current code.
- Local preview checked at a phone width and in dark mode; search finds a page by a term in its body.
