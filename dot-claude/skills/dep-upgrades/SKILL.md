---
name: dep-upgrades
description: Use when upgrading dependencies or toolchains — batching, changelogs, semver checks, update bots, rollback; vetting is sec-supply-chain.
---
# Dependency and toolchain upgrades

## Scope
Planned upgrades of libraries, frameworks, language toolchains and base images. Security side (cooldowns, install scripts, audits, provenance): `sec-supply-chain`. Mechanical call-site changes: `codemods`. Licences of new versions: `oss-licensing`.

## Plan
- Inventory what is outdated and why it matters: security advisories first, then end-of-life runtimes, then features you need; leave the rest for routine batches.
- Read the changelog and migration guide between the current and target versions — every major in between, not just the last one. List breaking changes that touch your code (grep for the affected APIs).
- One risky upgrade per change (a framework major, a runtime major); group low-risk patch/minor updates.
- Respect a cooldown on fresh releases (`sec-supply-chain`).

## Commands (lockfile stays authoritative)
- Python/uv: `uv lock --upgrade-package <pkg>` (one) or `uv lock --upgrade` (all), then `uv sync --locked`.
- Rust: `cargo update -p <crate>` (within semver), `cargo update -p <crate> --precise <ver>`; major bumps edit `Cargo.toml` (cargo-edit's `cargo upgrade`); library authors check API compatibility with `cargo semver-checks`.
- JS: `pnpm update <pkg>` / `pnpm update --latest <pkg>` or `npm install <pkg>@<ver>`; `pnpm outdated`, `npm outdated` to list.
- Containers: bump base images by digest (`container-images`); CI actions by SHA (`ci-cd-pipelines`).
- Command spellings above: unverified as of 2026-10-02 against current docs — check `--help` of the installed version.

## Automation
- Renovate or Dependabot with grouping (dev tools together, framework families together), a schedule, minimum release age, automerge only for patch updates of well-tested dev dependencies, and CI required. Keep their config in the repo; review their PRs like any change.

## Execute and verify
1. Upgrade on a branch or worktree; regenerate the lockfile with the project's tool.
2. Build, type check, full tests, plus the app's smoke tests; diff deprecation warnings (new warnings are next upgrade's breakages).
3. For runtime majors (Python, Node, Rust edition, JDK): run the test matrix on old and new; check native extensions and Docker images.
4. Rollout: deploy behind the usual checks; keep the previous lockfile to roll back.

## Verify
- [ ] Changelog/migration notes read for every skipped major; affected call sites listed and changed.
- [ ] Lockfile diff reviewed (unexpected transitive majors, new install scripts, new licences).
- [ ] Build, types, tests and smoke tests green; deprecation warnings triaged.
- [ ] Rollback path stated (previous lockfile/commit).
