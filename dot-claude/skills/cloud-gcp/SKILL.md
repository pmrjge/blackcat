---
name: cloud-gcp
description: Load for Google Cloud work — gcloud configs, ADC, service accounts, Cloud Run, buckets, costs.
---
# Google Cloud from the command line

Part of `self-hosting-ops` (principles). Infrastructure as code: `terraform-opentofu`; CI credentials (Workload Identity Federation): `ci-cd-pipelines`. gcloud versions: check `gcloud version` (not re-verified here).

## Safety and identity
- First: `gcloud config list` (account, project, region). One named configuration per project or account: `gcloud config configurations create <name>`, `activate <name>`; pass `--project` explicitly in scripts.
- Reads (`list`, `describe`) are free to run; creates, deletes, IAM changes and anything billable need the user's go-ahead.
- Two credential sets: `gcloud auth login` (the CLI) and `gcloud auth application-default login` (Application Default Credentials for SDKs and Terraform). Know which one a tool uses.
- Service accounts: attach them to workloads (Cloud Run, GCE, GKE Workload Identity) and use Workload Identity Federation for CI; avoid downloadable keys (the org policy `iam.disableServiceAccountKeyCreation` enforces it). Impersonate for testing: `--impersonate-service-account=<sa>`.
- Grant predefined roles at the narrowest resource; avoid the basic roles Owner and Editor. `gcloud projects get-iam-policy <project>` to review.

## Output and scripting
- `--format=json` (or `value(field)`), `--filter='status=RUNNING'`; `--quiet` only after the command was reviewed.

## Common services
- Cloud Run for containers: `gcloud run deploy <svc> --image <region>-docker.pkg.dev/<project>/<repo>/<img>@sha256:<digest> --region <r> --no-allow-unauthenticated`; images live in Artifact Registry.
- Cloud Storage: uniform bucket-level access and public access prevention on; object versioning plus lifecycle rules for anything that matters; signed URLs for sharing.
- Logs: `gcloud logging read 'resource.type="cloud_run_revision" AND severity>=ERROR' --limit 50 --freshness 1h`.

## Costs
- A budget with alert thresholds per billing account before creating resources; labels on every resource (`project`, `owner`, `env`).
- Usual surprises: always-on minimum instances, egress, idle static IPs, persistent disks and snapshots left behind, log volume.

## Verify
- `gcloud config list` and `gcloud auth list` show the intended project and identity; no service-account keys were created.
- New resources carry labels, sit under a budget alert, are private by default; each write was reviewed before running.
