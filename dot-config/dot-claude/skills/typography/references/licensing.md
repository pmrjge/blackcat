# typography — licensing (reference)
Read when checking whether a font licence covers the use (web, app, embedding, logo). Parent: `typography` SKILL.md.

## 11. Font licensing
| License | Usually covers | Read the EULA for |
|---|---|---|
| Desktop | Installing on N computers; static artwork, print, PDFs, logos | Seats, logo/trademark clause, outline modification, sharing with printers |
| Web | Self-hosted `@font-face` | Pageview or domain limits, subsetting, self-hosting |
| App | Embedding in software | Per-app or per-platform terms |
| ePub, server/SaaS, broadcast | Those uses | Often separate licenses |
- OFL: any design use, logos included (FAQ 1.1); embedding in documents, full or subset (1.12); may be
  bundled, not sold alone; Reserved Font Names on modified versions (§9).
- Adobe Fonts: commercial print and digital work and PDFs allowed; logos may be registered as trademarks
  (the typeface itself cannot); protected ebook formats and broadcast allowed; no app embedding; not
  packageable (font files can't go to a printer or client); after the subscription ends, fonts go missing.
- `OS/2.fsType`: 0 installable, 2 restricted (no embedding), 4 preview & print, 8 editable; flag 0x100 no
  subsetting, 0x200 bitmap-only embedding. PDF exporters and PowerPoint honor it.
- Handoff: record family, version, foundry, licensee and scope; never send commercial font files; PDFs carry
  embedded subsets; logotypes are outlined.
