# Documentation, READMEs, ADRs and changelogs

Read from `technical-writing` (reader/purpose/claim, sentences, editing passes, checklist live in its SKILL.md). Building the site: `docs-sites`. Vale 3.24.0 is current (Verified 2026-10-02 `git ls-remote --tags https://github.com/errata-ai/vale`); Keep a Changelog 1.1.0 is the current spec (Verified 2026-10-02 https://keepachangelog.com/en/1.1.0/).

## Structure
| Genre | Structure | Notes |
|---|---|---|
| Documentation | Diátaxis: tutorial / how-to / reference / explanation, never mixed on one page | See table below |
| Decision record | ADR (Nygard): context → decision → consequences | template below |
| Release notes | Keep a Changelog categories, newest first | template below |

Diátaxis (Daniele Procida, diataxis.fr) — the compass asks *action or cognition?* and *acquisition (study) or
application (work)?*:
| | Acquisition (study) | Application (work) |
|---|---|---|
| **Action** (doing) | Tutorial — a lesson; guaranteed success path, no choices, no explanation detours | How-to guide — steps to a goal for a competent user; assumes context, handles real variations |
| **Cognition** (knowing) | Explanation — why and how it fits; alternatives, history, design rationale | Reference — dry, complete, structured like the thing described (API, CLI flags, config keys) |
Symptoms of mixing: tutorials that explain theory mid-step, reference pages with opinions, how-tos that teach
basics. Fix by splitting and cross-linking.

## 5. Code in prose
- Every snippet is **runnable as shown** or visibly marked as a fragment (`...`); minimal; no dead parameters;
  versions pinned where behaviour depends on them; show the actual output you claim.
- Test documentation code: `pytest --doctest-glob="*.md"` (default glob is `test*.txt`; the flag may repeat),
  `pytest --doctest-modules` for docstrings; Rust doc tests run with `cargo test`; otherwise extract fenced
  blocks and execute them in CI.
- Fences carry a language tag; commands copy-pasteable (either no prompts, or `$ ` prompts with output shown —
  be consistent); placeholders as `<like-this>`; never real secrets, tokens or personal paths.
- Before the block: what it does and why; after it: what to notice in the output.
- No screenshots of code or terminal text.

## Prose linting with Vale
`brew install vale`; `.vale.ini` at the repo root, then `vale sync` and `vale docs/`
(only `error` alerts give a non-zero exit, so CI can gate on them):
```ini
StylesPath = styles
MinAlertLevel = suggestion
Packages = Microsoft, write-good
Vocab = Project

[*.md]
BasedOnStyles = Vale, Microsoft, write-good
```
Project terms go one regex per line in `styles/config/vocabularies/Project/accept.txt` (Vale ≥ 3; older versions
used `styles/Vocab/`); commit the vocabulary, ignore the synced packages (`styles/*` plus `!styles/config/` in
`.gitignore`). House style for software docs: the Google developer documentation style guide or the Microsoft
Writing Style Guide (both exist as Vale packages). Grammar and LaTeX linters: §8 of the `technical-writing` SKILL.md.

## 9. Templates
**README**
```markdown
# <name> — <what it does, one line>
<2–4 sentences: the problem, who it is for, what makes it different>
## Quick start      <install + smallest runnable example + expected output>
## Usage            <common tasks; link to how-to guides>
## Configuration    <table: option | default | meaning>
## How it works     <short; link to explanation docs>
## Development      <setup, tests, lint, release>
## Limitations      <known issues, non-goals>
## License · Citation (CITATION.cff) · Acknowledgements
```
**ADR** (Nygard: numbered sequentially, numbers never reused, superseded records kept, stored e.g. `doc/adr/`)
```markdown
# ADR-007: <short noun phrase>
Status: proposed | accepted | deprecated | superseded by ADR-012 · Date: YYYY-MM-DD
## Context        <forces at play, value-neutral: technical, organizational, constraints>
## Decision       <"We will …" — full sentences, active voice>
## Consequences   <all of them: positive, negative, neutral; what becomes easier/harder>
## Alternatives considered (optional) <option → why not>
```
**Changelog entry** (Keep a Changelog 1.1.0 + Semantic Versioning; ISO dates; user-visible effects, not commits)
```markdown
## [Unreleased]
## [1.4.0] - 2026-09-26
### Added
- `--dry-run` flag for `sync` (#123).
### Changed / Deprecated / Removed / Fixed / Security
[1.4.0]: https://github.com/<org>/<repo>/compare/v1.3.0...v1.4.0
```

## Verify
- Each page has one Diátaxis type; every snippet executed (doctests or CI extraction) with the shown output.
- `vale` shows no errors; ADR numbers sequential and never reused; changelog entries describe user-visible effects with ISO dates.
