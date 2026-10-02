---
name: localization
description: Use for i18n and translation — plurals, locales, machine-translation review, catalogs, subtitles.
---
# Localization and internationalization (hub)

## Scope
Making software translatable (i18n), translating string catalogs and subtitles (l10n), and checking the result. Prose translation and writing: `technical-writing`; European Portuguese specifics: `portuguese-pt-writing`; subtitle encoding and muxing: `media-ffmpeg`.

## Modules
| module | load when |
|---|---|
| `l10n-catalogs` | gettext .po, XLIFF, Apple .xcstrings/.strings, Android strings.xml, ARB, ICU JSON, Fluent; extract/merge/compile; QA checks (placeholders, plurals, markup, lengths, terminology), pseudo-localization, screenshot review |
| `subtitles` | SRT, WebVTT, TTML/IMSC, ASS; timing, reading speed, line breaks, subtitle translation |

## Reference data
- Unicode CLDR 48.2 (plural rules, locale data) and ICU 78.3 — Verified 2026-10-02 https://github.com/unicode-org/cldr/releases/latest https://github.com/unicode-org/icu/releases/latest
- Plural categories come from CLDR per locale (`zero/one/two/few/many/other`); never assume English one/other. Check the locale's rules at the CLDR plural-rules chart for the version in use.

## i18n rules for code
- Every user-visible string goes through the catalog; no concatenation of translated fragments — whole sentences with named placeholders (`{count}`, `%1$@`, `%(name)s`) so translators can reorder.
- Plurals and gender/select through the platform's mechanism (ICU MessageFormat, gettext `ngettext`, `.stringsdict`/String Catalog variations, Android `<plurals>`), never `if n == 1`.
- Context for translators: a comment or `msgctxt` on every ambiguous string ("Open" verb vs adjective), maximum length when the UI constrains it, screenshots where possible.
- Locale-aware formatting from the platform (ICU, `Intl`, `NumberFormatter`/`DateFormatter`, Babel): numbers, currencies, dates, times, lists, units, collation and case mapping. Never hand-format.
- Locale identifiers in BCP 47 (`pt-PT`, `pt-BR`, `zh-Hant-TW`, `sr-Latn`); fallback chains explicit (pt-PT must not silently fall back to pt-BR text).
- Layout: 30–40 % expansion for short strings (more for very short ones), RTL mirroring (Arabic, Hebrew) with logical properties (`start/end`), bidi isolation of embedded LTR values, fonts covering the target scripts.
- Keys stable across releases; changing a source string's meaning gets a new key.

## Translation rules
- Terminology from a glossary and translation memory; do-not-translate list (product names, code, placeholders).
- Machine or LLM translation produces drafts: mark them as needing review (fuzzy/`needs-review` state) unless the user accepts unreviewed output.
- Sending strings or subtitles to an external MT service or translation platform shares the user's content outside: needs the user's consent (and never for confidential or unreleased material without it). Local tools are fine.
- Register and audience per locale (formal vs informal address — e.g. "você"/"tu" in pt-PT, "Sie"/"du" in German) decided once and recorded in the style guide.

## Verify
Catalogs compile/validate with the platform tool · `l10n-catalogs` QA checks clean (placeholders, plurals, markup, lengths) · pseudo-locale run shows no hard-coded strings or truncation · native-language screenshots reviewed for the changed screens · locales and CLDR/ICU versions reported.
