---
name: ci-cd-pipelines
description: Use for CI/CD workflows — GitHub/Forgejo Actions, permissions, SHA pinning, OIDC, caching, zizmor.
---
# CI/CD pipelines

## Scope
Workflow files for GitHub Actions and Forgejo Actions (`.github/workflows/`, `.forgejo/workflows/`). Registering and securing a Forgejo runner host → `self-hosting-ops`; image builds inside jobs → `container-images`; macOS signing jobs → `macos-app-distribution`; the shell in `run:` steps → `shell-scripting`. Stack rule: no agent pushes or triggers remote runs; validate locally and report the branch.

## Skeleton
```yaml
name: ci
on:
  push: { branches: [main] }
  pull_request:
permissions:
  contents: read                 # top level: read-only; escalate per job
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@<full-40-char-sha> # vX.Y.Z
        with: { persist-credentials: false }
      - uses: astral-sh/setup-uv@<sha> # vX.Y.Z
        with: { enable-cache: true }
      - run: uv sync --locked && uv run pytest -q
```
- `permissions:` at workflow level `contents: read`; a job that needs more declares only that (`id-token: write` for OIDC, `packages: write`, `pull-requests: write`). Anything unset is `none` once a `permissions` block exists.
- `timeout-minutes` on every job; `concurrency` to cancel superseded PR runs.

## Supply chain
- Pin every third-party action to a full commit SHA with a version comment; first-party `actions/*` too for release jobs. Let Dependabot or Renovate bump the SHA and comment together (zizmor's `ref-version-mismatch` catches drift).
- GitHub policy (changelog 2025-08-15) can require SHA pinning — unpinned actions then fail — and block actions with a `!` prefix in the allowed-actions list. Turn it on for repos that matter.
- Why: tj-actions/changed-files (CVE-2025-30066, March 2025) rewrote its tags to exfiltrate secrets from logs; SHA pins were unaffected.
- Install tools from lockfiles (`uv sync --locked`, `pnpm install --frozen-lockfile`, `cargo --locked`); `curl | sh` in `run:` is an unpinned dependency.

## Dangerous triggers and injection
- `pull_request_target`, `workflow_run`, `issue_comment` run with secrets and a write token in the base repo context. Never check out and build the PR head in them. Since 2025-12-08 `pull_request_target` always takes the workflow file and checkout commit from the **default branch** (`GITHUB_REF` = default branch), and environment branch rules evaluate against `GITHUB_REF` (`refs/pull/<n>/merge` for `pull_request`) — update environment branch filters accordingly.
- Script injection: never put `${{ github.event.* }}`, `github.head_ref` or step outputs derived from user input inside `run:`. Pass through `env:` and quote:
  ```yaml
  - env: { TITLE: "${{ github.event.pull_request.title }}" }
    run: printf '%s\n' "$TITLE"
  ```
- Writes to `$GITHUB_ENV`/`$GITHUB_PATH` from attacker-controlled data are code execution in later steps.
- `actions/checkout` persists the token in `.git/config` unless `persist-credentials: false`; never upload the workspace as an artifact with it.

## Secrets and cloud access
- OIDC federation instead of long-lived cloud keys (`id-token: write` + the provider's login action with a role scoped to repo, branch or environment).
- Environments with required reviewers and branch rules for deploy jobs; secrets scoped to the environment, not the repo.
- Fork PRs get no secrets and a read-only token on `pull_request` (GitHub and Forgejo). Do not work around it.
- Masking is best-effort (transformed secrets leak: base64, JSON-escaped); never echo secrets, never `toJSON(secrets)`, avoid `secrets: inherit`.

## Caching and artifacts
- Prefer the setup action's cache (`setup-uv` `enable-cache`, `setup-node` `cache: pnpm`, `Swatinem/rust-cache`); keys from lockfile hashes.
- A run can restore caches from its own branch and the default branch; any job running on the default branch (including `pull_request_target`/`workflow_run` jobs that touch PR content) can seed caches a release job later restores. Build releases without cache restores (zizmor `cache-poisoning`).
- Artifacts: set `retention-days`; never include `.git` or credential files.

## Structure
- Matrix: `strategy.matrix` with `fail-fast: false` for test grids; `include`/`exclude` for odd combinations.
- Reusable workflows (`on: workflow_call`, `jobs.<id>.uses: org/repo/.github/workflows/x.yml@<sha>`) for shared pipelines; composite actions for shared steps. Job outputs via `$GITHUB_OUTPUT`.
- Required checks: give jobs stable names; a final `needs:` gate job simplifies branch protection.

## Forgejo Actions differences (docs checked Sep 2026)
- Relative `uses: actions/checkout@v6` resolves against the instance's `DEFAULT_ACTIONS_URL` (default `https://data.forgejo.org`, admin-changeable): write fully qualified URLs (`uses: https://data.forgejo.org/actions/checkout@v6`) or pin by SHA from a mirror you control.
- `runs-on` matches labels the runner registered (`docker`, `lxc`, custom); what the job gets depends entirely on the runner config. No runner online for a label → the job waits.
- `github` context = `forgejo` context; `FORGEJO_*` variables are also exposed as `GITHUB_*` (runner ≥ 7); token is `FORGEJO_TOKEN`/`GITHUB_TOKEN`.
- OIDC is opt-in: `enable-openid-connect: true` at workflow or job level; disabled for fork PRs.
- `on.schedule` and `issue_comment` run only from the default branch; concurrency is best-effort; `container.volumes` limited to what the runner allows. Reusable workflows from other instances must be public.
- Test locally with `forgejo-runner exec` (Forgejo) or `act` (GitHub, v0.2.89) — both approximate the hosted environment.

## Lint and audit before reporting
```bash
actionlint                                  # v1.7.12; syntax, expressions, shellcheck on run: blocks
uvx zizmor .                                # v1.30.1; security audits (template-injection, dangerous-triggers,
                                            # unpinned-uses, artipacked, excessive-permissions, cache-poisoning)
uvx zizmor --offline .                      # no network; skips impostor-commit, known-vulnerable-actions
uvx zizmor --fix=safe .                     # apply safe autofixes, then review the diff
```
Treat zizmor High findings as blockers; justify any `# zizmor: ignore[rule]` inline.

## Releases
Build from a tag on the default branch, never from PR contexts; attach provenance (`actions/attest-build-provenance`) and checksums; publish with OIDC trusted publishing (PyPI, npm) instead of tokens. Creating the tag or release is the user's step in this stack.

## Verify
Top-level read-only permissions · every `uses:` SHA-pinned · no `${{ }}` of user data in `run:` · no untrusted checkout in privileged triggers · `persist-credentials: false` · OIDC over stored keys · timeouts and concurrency · actionlint and zizmor clean.

Sources (checked 2026-09-29): https://github.blog/changelog/2025-11-07-actions-pull_request_target-and-environment-branch-protections-changes · https://github.blog/changelog/2025-08-15-github-actions-policy-now-supports-blocking-and-sha-pinning-actions · https://docs.github.com/en/actions/reference/security/secure-use · https://www.cisa.gov/news-events/alerts/2025/03/18/supply-chain-compromise-third-party-tj-actionschanged-files-cve-2025-30066-and-reviewdogaction · https://forgejo.org/docs/latest/user/actions/ · https://docs.zizmor.sh/audits/ · https://github.com/rhysd/actionlint/releases · https://github.com/nektos/act/releases
