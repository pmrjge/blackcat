---
name: l10n-catalogs
description: Use to edit translation catalogs — gettext .po, XLIFF, .xcstrings/.strings, Android strings.xml, ARB, ICU JSON, Fluent; validators.
---
# Translation catalog formats

i18n and translation rules: `localization`. Checks: `l10n-qa`.

## Edit rules (all formats)
- Edit translations only; never change source strings, keys, IDs, placeholders or markup unless the task is to change the source.
- Preserve file structure, ordering, comments, encoding (UTF-8, no BOM unless the format requires it) and line endings; minimal diffs.
- Mark machine or uncertain translations with the format's review state (below); never mark them final without review or the user's say-so.
- Validate with the format's own tool after every edit.

## gettext (.pot/.po/.mo)
- Header `Plural-Forms` must match the locale (e.g. pt_PT `nplurals=2; plural=(n != 1);` but pt_BR `plural=(n > 1)` — 0 is singular there; Polish has 3 forms; Arabic 6); `Language: pt_PT`.
- Entries: `msgctxt` (context), `msgid`, `msgid_plural` + `msgstr[0..n-1]`; flags `#, fuzzy` (needs review — excluded from `.mo`), `#, python-format`/`c-format` enable placeholder checks.
- Tools: `xgettext` or `pybabel extract` (via `uv run --with babel pybabel …`) to the `.pot`; `msgmerge --update --backup=none xx.po app.pot`; `msgfmt -c --check-format -o /dev/null xx.po` to validate; `msgattrib --only-fuzzy` / `--untranslated` to list work.
- Babel 2.18.0 — Verified 2026-10-02 https://github.com/python-babel/babel/releases/latest

## XLIFF (1.2 and 2.x)
- `<trans-unit>`/`<unit>` with `<source>` and `<target>`; inline tags (`<x/>`, `<g>`, `<ph>`, `<pc>`) are placeholders and markup — keep them, reorder only if grammar requires.
- States: 1.2 `state="needs-review-translation"|"translated"|"final"`; 2.x `state="initial|translated|reviewed|final"`.
- Validate: `xmllint --noout file.xlf` (well-formed) and the schema when available. Apple `.xcloc` bundles contain XLIFF exported/imported with `xcodebuild -exportLocalizations` / `-importLocalizations`.

## Apple
- String Catalogs (`.xcstrings`, JSON): per-key `localizations.<lang>.stringUnit {state, value}`; plural and device variations under `variations`; states `new|translated|needs_review|stale`. Edit with care for JSON validity (`jq empty`); Xcode re-syncs keys at build.
- Legacy `.strings` (`"key" = "value";`, UTF-8 or UTF-16) and `.stringsdict` (plist plurals) — validate with `plutil -lint`.
- Format specifiers: `%@`, `%d`, `%lld`; positional `%1$@` when reordering.

## Android
- `res/values-<qualifier>/strings.xml` (`values-pt-rPT`, or BCP 47 `values-b+pt+PT`); `<string>`, `<plurals>` with `<item quantity="one|few|many|other">`, `<string-array>`.
- Escape `'` as `\'` and `"` as `\"`, `@`/`?` at the start, `&lt;` for `<`; `translatable="false"` for non-translatables; placeholders `%1$s`, `%2$d`.
- Validate with `./gradlew lint` (MissingTranslation, StringFormatInvalid, PluralsCandidate).

## Web and cross-platform
- ICU MessageFormat in JSON (FormatJS/react-intl, i18next with ICU plugin): `{count, plural, one {# file} other {# files}}`, `{gender, select, …}`; extract and compile with `formatjs extract`/`formatjs compile`.
- i18next JSON v4 plural keys (`key_one`, `key_other`); nesting and interpolation `{{name}}`.
- Flutter ARB: `"key": "…"`, metadata `"@key": {"description", "placeholders"}`; `flutter gen-l10n` validates.
- Fluent (`.ftl`): messages with variants and selectors; terms (`-brand`); validate with the Fluent parser of the runtime.
- Java `.properties` (ISO-8859-1 before Java 9, UTF-8 after for resource bundles), .NET `.resx` (XML).

## Conversions
translate-toolkit (`uv run --with translate-toolkit po2xliff …`, `xliff2po`, `json2po`, `prop2po`) to move between formats for review, converting back with the reverse tool; diff the round trip on a sample first.

## Verify
Format tool passes (`msgfmt -c`, `xmllint`, `plutil -lint`, `jq empty`, `gradlew lint`, `gen-l10n`) · counts of translated/fuzzy/untranslated entries reported per locale · diff touches only target text and states.
