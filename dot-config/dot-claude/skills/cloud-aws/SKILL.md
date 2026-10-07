---
name: cloud-aws
description: Use for AWS from the CLI — SSO profiles, IAM least privilege, S3, costs, CloudTrail.
---
# AWS from the command line

Part of `self-hosting-ops` (principles). Infrastructure as code: `terraform-opentofu`; CI credentials (OIDC): `ci-cd-pipelines`; secrets handling: `secure-coding`. AWS CLI 2.37.8 is current (Verified 2026-10-02 `git ls-remote --tags https://github.com/aws/aws-cli`).

## Safety and identity
- First call in any session: `aws sts get-caller-identity` (which account and role). Name the profile and region on every command (`--profile`, `--region`) or export `AWS_PROFILE`/`AWS_REGION` once.
- Reads (`describe-*`, `list-*`, `get-*`) are free to run; anything that creates, deletes, opens access or costs money needs the user's go-ahead. EC2 calls accept `--dry-run` to test permissions.
- Humans sign in through IAM Identity Center: `aws configure sso`, then `aws sso login --profile <p>`; no long-lived access keys on laptops. Workloads use roles (instance profiles, EKS Pod Identity or IRSA, Lambda execution roles); CI uses OIDC federation with a role to assume.
- Least privilege: start from AWS managed job-function policies only for exploration, then narrow to the actions and resources used; IAM Access Analyzer generates a policy from CloudTrail activity and flags external access. MFA on the root user, root never used day to day.

## Output and scripting
- `--output json` plus `--query` (JMESPath) to extract fields; `--no-cli-pager` in scripts; paginate with `--max-items` and `--starting-token`.
- `aws s3 sync src s3://bucket/prefix --dryrun` before a real sync; `--delete` only after reviewing the dry run.

## S3
- Keep Block Public Access on (account and bucket); serve public content through CloudFront with origin access control instead of a public bucket.
- Versioning on for anything that matters, with lifecycle rules for noncurrent versions; server-side encryption on (SSE-S3 or SSE-KMS).
- Share single objects with presigned URLs (`aws s3 presign s3://bucket/key --expires-in 3600`), not bucket policies.

## Costs
- AWS Budgets with alert thresholds before creating resources; tag everything (`project`, `owner`, `env`) and activate cost-allocation tags.
- Usual surprises: NAT gateways (hourly + per GB), data transfer out, public IPv4 addresses (billed), idle load balancers, unattached EBS volumes and old snapshots, CloudWatch Logs without retention.
- Clean-up check: `aws ec2 describe-volumes --filters Name=status,Values=available`, `aws ec2 describe-addresses`, Cost Explorer by service.

## Logging
- CloudTrail trail for all regions into a dedicated bucket; set a retention on every CloudWatch Logs group (`aws logs put-retention-policy`), since the default keeps logs forever.

## Verify
- `aws sts get-caller-identity` shows the intended account and role; no access keys were created for humans.
- New resources are tagged, covered by a budget alert, private by default; a dry run or diff preceded every write.
