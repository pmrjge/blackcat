# Localization QA

Rules: `localization`; formats and their validators: `l10n-catalogs`.

## Automated checks (run all; report counts per locale)
1. **Format validity**: the platform validator (`msgfmt -c --check-format`, `xmllint --noout`, `plutil -lint`, `jq empty`, `./gradlew lint`, `flutter gen-l10n`).
2. **Placeholders**: same set, count and types as the source (`%1$s`, `{name}`, `{{count}}`, `%@`); positional forms when the order changed; no translated placeholder names.
3. **Plurals**: every CLDR category the locale needs is present (from the CLDR plural rules for that locale); ICU `#` used where the number must appear; no forms copied blindly from English.
4. **ICU syntax**: messages parse (`@formatjs/icu-messageformat-parser` via `npx`, or the runtime's parser); `select` has `other`.
5. **Markup and escapes**: tags balanced and identical in kind (HTML, XLIFF inline, Android `<b>`), entities and escapes valid (Android `\'`).
6. **Untranslated and suspicious**: empty targets, target == source (except allowed loanwords/brands), fuzzy/needs-review leftovers, leading/trailing whitespace or punctuation differing from the source, doubled spaces.
7. **Length**: against stated maximums and UI constraints; flag targets > 1.5× source for short UI labels.
8. **Terminology**: glossary terms translated consistently; do-not-translate terms untouched; same source string translated the same way across the catalog unless context differs.
9. **Locale typography**: quotes and punctuation per locale (French narrow no-break space before `;:!?` and inside « »; German „…"; pt-PT « » or "…" per the style guide), number formats not hard-coded in strings.
translate-toolkit's `pofilter` (`uv run --with translate-toolkit pofilter --gnome in.po out.po` and other check sets) covers many of these for PO/XLIFF; small uv scripts cover the rest.

## Pseudo-localization (before translations exist)
- Generate a pseudo-locale that expands text (~30–40 %), adds accents and brackets (`[Ŝéţţîñĝš ___]`) and, separately, a bidi pseudo-locale for RTL.
- Android: `pseudoLocalesEnabled = true` in the debug build type → `en-XA` (accents, expansion) and `ar-XB` (RTL). Apple: scheme option "Double-Length Pseudolanguage" and "Right-to-Left Pseudolanguage" (`-AppleLanguages`, `-NSDoubleLocalizedStrings YES` launch arguments). Web: a pseudo-locale build of the message files.
- Look for: unbracketed text (hard-coded strings), truncation and clipping, overlapping layouts, mirrored icons that should not mirror (and vice versa), concatenated fragments.

## Visual and linguistic review
- Screenshots per locale of changed screens (UI tests with `-testLanguage`/`-AppleLanguages`, Android `adb shell setprop`/per-app language, Playwright `locale`); Read them before reporting.
- Native-speaker review for shipped locales; the checker reports issues by key with source, target and the rule violated, so a reviewer can act without opening the files.
- LLM-assisted review is a filter, not a sign-off: it flags meaning shifts, register mismatches and terminology issues for a human.

## Report format
`| locale | entries | translated | fuzzy | untranslated | placeholder errors | plural errors | markup errors | length warnings |` plus a list of issues `key — rule — source — target — suggestion`.

## Verify
All automated checks run on every locale touched · zero placeholder, plural and markup errors (or each explained) · pseudo-locale screenshots reviewed when UI changed · counts reported in the table above.
