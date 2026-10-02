---
name: sec-supply-chain
description: Use when adding, pinning, auditing or publishing dependencies — lockfiles, cooldowns, install scripts, provenance; upgrades in dep-upgrades.
---
# Dependencies and supply chain
Hub: `secure-coding`. Version notes carry Verified lines (see Sources) or are marked unverified.

- **Lock and enforce:** `uv lock` + `uv sync --locked`; hashes with `uv pip compile --generate-hashes` + `--require-hashes`; `npm ci` / `pnpm install --frozen-lockfile`; `cargo build --locked`; containers pinned by digest.
- **Cooldown on fresh releases** (malicious versions are often detected and pulled within days): uv `exclude-newer = "7 days"` (friendly durations such as `24 hours`, `1 week`, `30 days`, or ISO 8601 `P7D`; months and years are not accepted), pnpm `minimumReleaseAge` (minutes, 10.16+; default 1440 from pnpm 11), npm `min-release-age` (days, 11.10+; cannot be combined with `--before`; older npm ignores it), Yarn `npmMinimalAgeGate` (a duration such as `"1w"`).
- **Install-time code:** `npm ci --ignore-scripts` where possible; pnpm 10+ runs dependency lifecycle scripts only when allowlisted (`allowBuilds`, 10.26+; pnpm 11 removed the older `onlyBuiltDependencies`, `neverBuiltDependencies`, `ignoredBuiltDependencies` and `ignoreDepScripts`); Python sdists execute build code — prefer wheels (`--only-binary :all:`, uv `--no-build`).
- **Audit and triage:** `uvx pip-audit` (or `uv audit`, preview in recent uv), `cargo audit`, `cargo deny check` (advisories, bans, licenses, sources), `npm audit --omit=dev`, `osv-scanner scan source -r .`. For each advisory: is the vulnerable code reachable, what is the fixed version, is there a workaround. Prioritize with CISA KEV (known exploited) and EPSS scores before raw CVSS (unverified as of 2026-10-02).
- **Provenance:** PyPI Trusted Publishing and attestations (PEP 740), `npm publish --provenance` and `npm audit signatures`, Sigstore/cosign for images, `gh attestation verify <artifact> --owner <org>`, `cargo vet`.
- **Name attacks:** before adding a dependency check its exact name, owner, age, downloads and repository — above all for names an LLM suggested (hallucinated names get registered: slopsquatting). Dependency confusion: resolve private names from one explicit index; uv's default `first-index` strategy does not fall through to PyPI, pip's `--extra-index-url` does.
- Planned upgrades (changelogs, batching, bots, rollback): `dep-upgrades`; licences of new dependencies: `oss-licensing`.
- CI-side controls (pinned actions, OIDC, token permissions): `ci-cd-pipelines`; image SBOMs and scanning: `container-images`.

## Verify
- [ ] Lockfile present and enforced in CI (`--locked`, `--frozen-lockfile`, `npm ci`).
- [ ] Audit output attached; every open advisory triaged (reachable? fixed version? workaround?).
- [ ] Each new dependency: name, owner, age, downloads and repository checked; install scripts allowlisted explicitly.

## Sources
- Verified 2026-10-02 https://docs.astral.sh/uv/reference/settings/ — `exclude-newer` durations; https://github.com/astral-sh/uv/releases — `uv audit` listed as preview (uv 0.12.22, 2026-10-01).
- Verified 2026-10-02 https://pnpm.io/settings/dependency-resolution — `minimumReleaseAge` minutes, 10.16.0, default 1440 from v11; https://pnpm.io/settings/build — `allowBuilds` 10.26.0, removals in v11; pnpm latest major is 12.
- Verified 2026-10-02 https://github.com/npm/cli/releases/tag/v11.10.0 and https://docs.npmjs.com/cli/v11/using-npm/config — `min-release-age` in days.
- Verified 2026-10-02 https://yarnpkg.com/configuration/yarnrc — `npmMinimalAgeGate` (first version not stated).
