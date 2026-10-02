---
name: a11y-audit
description: Use when auditing a web UI against WCAG 2.2 AA — axe in Playwright, manual keyboard, zoom and VoiceOver passes, the findings report.
---
# Accessibility audit: automated and manual
Hub: `web-accessibility` (target WCAG 2.2 AA, legal frame, 2.2 additions, contrast, motion, report format). Sources (checked 2026-09-29, listed in the hub `web-accessibility`): W3C WCAG 2.2, WAI-ARIA APG, axe-core API, Playwright accessibility testing.

## 6. Automated checks (catch roughly a third of issues)
```ts
import AxeBuilder from '@axe-core/playwright';          // 4.13
const r = await new AxeBuilder({ page })
  .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
  .analyze();
expect(r.violations).toEqual([]);
```
- Scan every key state (menus open, dialogs, errors shown), not just the initial load; `.include()` to scope, `.exclude()` only with a filed issue. Tags `EN-301-549` / `EN-301-549v4` select the EN rule sets.
- Also: Lighthouse accessibility audit (a subset of axe), `eslint-plugin-jsx-a11y` in React projects, Playwright ARIA snapshots (`await expect(locator).toMatchAriaSnapshot(...)`) to lock the accessible tree.

## 7. Manual pass (always)
1. Keyboard only: reach and operate everything; focus visible and never lost or obscured.
2. VoiceOver on macOS (⌘F5; VO = Ctrl+Option): VO+U rotor for headings/landmarks/links/form controls; read a form, trigger an error, open and close a dialog. Test with Safari (VoiceOver's best pairing).
3. Zoom 200% and 400% (reflow); text-spacing bookmarklet; Windows High Contrast / `forced-colors` if the audience needs it.
4. Reduced motion on; color-blindness simulation (DevTools Rendering panel).


## Report
`| SC (number + name, level) | page/component + selector | impact on users | how found (axe/manual/AT) | fix |`, ordered by impact; state standard and version tested (WCAG 2.2 AA; EN 301 549 v3.2.1 or v4.1.1), browsers and assistive tech used, and what was not tested.

## Verify
- [ ] axe scans cover every key state (menus, dialogs, errors), with the tag set stated; excluded regions have filed issues.
- [ ] Manual pass done: keyboard only, VoiceOver (+ Safari), 200%/400% zoom, text spacing, reduced motion.
- [ ] Report lists standard and version tested, browsers and assistive tech, findings by impact, and what was not tested.
