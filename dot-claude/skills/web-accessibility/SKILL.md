---
name: web-accessibility
description: Load before building, designing or auditing UI for accessibility — WCAG 2.2 AA, semantic HTML and ARIA patterns, keyboard and focus, screen readers, axe, EAA.
---
# Web accessibility

## Scope
Accessibility of web UIs and UI designs. Contrast math and color spaces → `color-management`; framework code → `frontend-frameworks`; design tokens and component states → `ui-design-systems`; running the browser → `browser-automation`; accessible PDFs/Office files → the pdf/docx skills; slides → `presentation-design`.

## Modules
| Module | Load when |
|---|---|
| `a11y-mobile` | native or cross-platform mobile apps: iOS, Android, Flutter, React Native APIs, audits, VoiceOver/TalkBack passes |

## Target and legal frame (checked 2026-09-29)
- Target **WCAG 2.2 Level AA** (W3C Recommendation, 5 Oct 2023; 4.1.1 Parsing removed as obsolete).
- WCAG 3.0 is a **Working Draft** (latest 10 Sep 2026): never cite it as a requirement.
- EU: the European Accessibility Act applies since 2025-06-28 to covered products/services (e-commerce, banking, e-books, transport ticketing, …; microenterprises providing services are exempt). Presumption of conformity comes from the harmonised standard **EN 301 549 v3.2.1 (WCAG 2.1 AA)**. **EN 301 549 v4.1.1 (WCAG 2.2 AA, with an EAA mapping annex) was published 2026-09-02 but is not yet cited in the Official Journal**; citation expected late 2026 — test against 2.2 now, and state in accessibility statements which version you tested.

## 1. Semantics first
- Native elements before ARIA: `<button>` for actions, `<a href>` for navigation, `<label for>` on every control, `<fieldset>/<legend>` for groups, `<table>` with `<th scope>` for data.
- Landmarks (`header`, `nav`, `main` once, `footer`, `aside`), one `h1`, heading levels without gaps; `lang` on `<html>` and on foreign-language passages; unique, descriptive `<title>` per page/route.
- Images: meaningful `alt`; decorative `alt=""`; complex charts get a text summary or data table.
- ARIA only following the APG patterns (dialog, disclosure, tabs, menu button, combobox, listbox, tree, grid) — roles, states, keyboard model and focus handling together. A wrong role is worse than none. `aria-live="polite"` regions for async status (toasts, form results).
- Forms: visible labels (placeholders are not labels), `autocomplete` tokens on personal data fields (1.3.5), errors identified in text next to the field and linked with `aria-describedby`, summary on submit, don't clear the user's input.

## 2. Keyboard and focus
- Everything operable by keyboard in a logical order (DOM order = visual order); no `tabindex` > 0; custom widgets follow APG key bindings (arrows inside composite widgets, Tab between them).
- Visible focus indicator on every focusable element (2.4.7); never `outline: none` without a replacement; use `:focus-visible`.
- Modals: move focus in, trap it, Escape closes, return focus to the opener; background `inert`. Native `<dialog>` with `showModal()` does most of this.
- Skip link to `main`; SPA route changes move focus to the new heading and announce the title.

## 3. WCAG 2.2 additions — test steps
| SC | Level | Test |
|---|---|---|
| 2.4.11 Focus Not Obscured (Minimum) | AA | Tab through with sticky headers/footers, cookie banners, chat widgets open: the focused element is never fully hidden (`scroll-padding` fixes most) |
| 2.5.7 Dragging Movements | AA | every drag action (sliders, sortable lists, maps) has a single-pointer alternative (buttons, click-to-place) |
| 2.5.8 Target Size (Minimum) | AA | pointer targets ≥ 24×24 CSS px, or spaced so a 24 px circle around each doesn't overlap another; inline links in text exempt |
| 3.2.6 Consistent Help | A | help mechanisms (contact, chat, FAQ link) appear in the same relative order across pages |
| 3.3.7 Redundant Entry | A | information already entered in the same process is auto-filled or selectable, not retyped (except security re-entry) |
| 3.3.8 Accessible Authentication (Minimum) | AA | no cognitive test to log in: allow paste and password managers, offer passkeys/email links; CAPTCHAs need a non-cognitive alternative |

AAA extras (2.4.12, 2.4.13 Focus Appearance, 3.3.9) are good practice, not the AA target.

## 4. Color, contrast, text
- Text contrast ≥ 4.5:1 (≥ 3:1 for ≥ 24 px or ≥ 18.66 px bold); UI component boundaries, focus indicators and meaningful graphics ≥ 3:1 (1.4.11). Compute on actual rendered colors, in every theme (dark mode included).
- Never color alone for meaning (errors, chart series, links in body text need underline or 3:1 against text plus another cue).
- Reflow at 320 CSS px wide (400% zoom) without horizontal scroll (1.4.10); text resize to 200%; text spacing overrides (1.4.12) don't clip content.

## 5. Motion, media, timing
Honor `prefers-reduced-motion` (disable parallax, autoplaying and large transitions); nothing flashes > 3 times/s; pause/stop/hide for anything moving > 5 s; captions for video, transcripts for audio, audio description where visuals carry information; adjustable or no time limits.

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

## Design review checklist (before code)
Focus styles designed for every interactive component; target sizes ≥ 24 px (44 px recommended for touch per Apple HIG); contrast verified per theme; error, empty and loading states specified with text; no information by color alone; reading and focus order annotated; motion has a reduced variant.

## Report format
`| SC (number + name, level) | page/component + selector | impact on users | how found (axe/manual/AT) | fix |`, ordered by impact; state standard and version tested (WCAG 2.2 AA; EN 301 549 v3.2.1 or v4.1.1), browsers and assistive tech used, and what was not tested.

Sources (checked 2026-09-29): https://www.w3.org/TR/WCAG22/ · https://www.w3.org/WAI/standards-guidelines/wcag/new-in-22/ · https://www.w3.org/TR/wcag-3.0/ · https://www.w3.org/WAI/ARIA/apg/ · https://accessible-eu-centre.ec.europa.eu/content-corner/news/european-accessibility-standard-en-301-549-has-been-updated-2026-09-07_en · https://commission.europa.eu/strategy-and-policy/policies/justice-and-fundamental-rights/disability/european-accessibility-act-eaa_en · https://github.com/dequelabs/axe-core/blob/develop/doc/API.md · https://playwright.dev/docs/accessibility-testing
