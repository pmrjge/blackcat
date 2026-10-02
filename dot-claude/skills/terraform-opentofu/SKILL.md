---
name: terraform-opentofu
description: Load before writing, planning or reviewing Terraform or OpenTofu — state and locking, plan/apply, modules, moved/import/removed, tflint.
---
# Terraform and OpenTofu

## Scope
Declarative infrastructure with HCL. Hosts configured by hand or with systemd/compose → `self-hosting-ops`; CI that runs plans → `ci-cd-pipelines`; secrets policy → `secure-coding`. Applying changes to shared or real infrastructure is the user's decision: agents write code, run `fmt`/`validate`/`plan` and report the plan.

## Tool choice (checked 2026-09-29)
| | Terraform | OpenTofu |
|---|---|---|
| Current | 1.16.4 (1.16 GA 2026-08-26); 1.17 in pre-release | 1.12.6 (1.12 current; 1.13 beta) |
| Licence | BSL 1.1 | MPL 2.0 (Linux Foundation) |
| Diverged features | `terraform_data` `store` block, actions (`-invoke`), `list`/query blocks, stacks, HCP integration | client-side **state and plan encryption** (since 1.7), ephemeral resources + write-only attributes and `lifecycle { enabled = … }` (1.11), `-exclude`, dynamic `prevent_destroy`, `-json-into=FILE` (1.12) |
| Both | `moved`, `import`, `removed` blocks, `lifecycle { destroy = false }` (Terraform 1.16, OpenTofu 1.12), provider-defined functions | |

Pick one per repository and pin it. Switching: back up state, read the migration guide for the exact versions, run `plan` and expect no changes before any apply. Once a feature unique to one tool is in the code, switching back is a rewrite. Binary: `brew install opentofu` (`tofu`); Terraform from `hashicorp/tap/terraform` or the release zips (Homebrew core has no `terraform` formula).

## Layout
```
infra/
  modules/<name>/        main.tf variables.tf outputs.tf versions.tf README.md
  envs/<env>/            main.tf backend.tf terraform.tfvars   # one root module + state per environment
```
- Separate state per environment and per blast radius (network vs apps); directories over workspaces for environments with different shapes.
- Remote state with locking (S3 with lockfile or DynamoDB, GCS, azurerm, HTTP/Terraform-compatible backends, Postgres); never local state for shared infra; never commit `*.tfstate`.
- Inputs typed with `validation` blocks; outputs minimal; no provider blocks inside reusable modules (pass providers in).

## Pinning
```hcl
terraform {
  required_version = "~> 1.16.0"            # or OpenTofu "~> 1.12.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}
```
Commit `.terraform.lock.hcl`. OpenTofu 1.12 records `zh:` and `h1:` checksums for all platforms on `init`; for Terraform run `terraform providers lock -platform=darwin_arm64 -platform=linux_amd64` so CI and laptops agree. Pin module sources to tags or commit SHAs.

## Plan discipline
1. `fmt -check -recursive`, `validate`, `tflint --recursive` (v0.64), security scan (`checkov -d .` 3.3.x or `trivy config .`).
2. `plan -out=tfplan` and read it: every **destroy** and **replace** (`-/+`, `+/-`) explained; `plan -json`/`show -json tfplan` for tooling.
3. Apply only the saved plan (`apply tfplan`), by the user or an approved pipeline; never `apply -auto-approve` against shared infra from an agent.
4. `-target`/`-exclude` only for recovery, with a follow-up full plan showing no drift.
5. `create_before_destroy`, `prevent_destroy` (OpenTofu 1.12 allows variables in it) on stateful resources (databases, buckets, DNS zones).

## Refactoring without destroy
```hcl
moved {                                   # rename/move (Terraform ≥ 1.1)
  from = aws_instance.web
  to   = module.web.aws_instance.this
}
import {                                  # adopt existing; `plan -generate-config-out=gen.tf` drafts the resource
  to = aws_s3_bucket.logs
  id = "my-logs-bucket"
}
removed {                                 # forget without destroying
  from = aws_instance.legacy
  lifecycle {
    destroy = false
  }
}
```
(HCL single-line blocks may hold only one argument — write these multi-line.)
Plans must then show moves/imports and zero destroys. Terraform 1.16 allows `import` blocks inside modules. `state mv`/`state rm` only when blocks can't express it, with a state backup (`state pull > backup.tfstate`) first.

## Secrets
- Anything in a resource argument lands in state in plain text unless it is write-only/ephemeral: prefer providers' write-only attributes and ephemeral resources (OpenTofu ≥ 1.11, recent Terraform) for passwords and tokens; `sensitive = true` only hides values from CLI output.
- Encrypt state at rest: backend encryption (S3 SSE-KMS etc.) and, with OpenTofu, client-side encryption:
  ```hcl
  terraform {
    encryption {
      key_provider "pbkdf2" "k" { passphrase = var.state_passphrase }   # ≥ 16 chars; or aws_kms/gcp_kms/openbao
      method "aes_gcm" "m" { keys = key_provider.pbkdf2.k }
      state {
        method   = method.aes_gcm.m
        enforced = true
      }
      plan {
        method   = method.aes_gcm.m
        enforced = true
      }
    }
  }
  ```
  Enabling it on existing state needs the documented migration (`unencrypted` fallback method) — plain `enforced = true` makes OpenTofu refuse the old state.
- Credentials from the environment/OIDC, never in `.tfvars` committed to git.

## Drift and rollback
`plan -refresh-only` to see drift; decide per resource: adopt (update code) or revert (apply). Document the rollback path for each change (previous module version/tag + its plan). Keep state versioning on the backend bucket.

## Review checklist
Tool and versions pinned · lock file committed · state remote, locked, encrypted · plan saved and read, destroys justified · refactors via `moved`/`import`/`removed` · no secrets in state or tfvars · tflint and checkov/trivy clean or waived with reasons · apply left to the user.

Sources (checked 2026-09-29): https://github.com/hashicorp/terraform/releases · https://opentofu.org/docs/intro/whats-new/ · https://opentofu.org/docs/v1.11/intro/whats-new/ · https://opentofu.org/blog/opentofu-1-7-0/ · https://opentofu.org/docs/language/state/encryption/ · https://developer.hashicorp.com/terraform/language/modules/develop/refactoring · https://developer.hashicorp.com/terraform/language/block/removed · https://developer.hashicorp.com/terraform/language/import · https://github.com/terraform-linters/tflint/releases · https://github.com/bridgecrewio/checkov/releases
