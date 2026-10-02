---
name: a11y-aria-patterns
description: Use for accessible web UI — semantic HTML, ARIA APG widget patterns, labelled forms, keyboard operation, focus order.
---
# Semantics, ARIA patterns, keyboard and focus
Hub: `web-accessibility` (target WCAG 2.2 AA, legal frame, 2.2 additions, contrast, motion, report format). Sources (checked 2026-09-29, listed in the hub `web-accessibility`): W3C WCAG 2.2, WAI-ARIA APG, axe-core API, Playwright accessibility testing.

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

## Verify
- [ ] Every interactive element is a native element or follows its APG pattern (role, states, keyboard model, focus).
- [ ] Keyboard-only walkthrough: every control reachable and operable, focus visible, never lost; dialogs trap and return focus.
- [ ] Forms: visible labels, `autocomplete` tokens, errors in text linked with `aria-describedby`.
- [ ] ARIA snapshot or axe scan of the component's key states passes (`a11y-audit`).
