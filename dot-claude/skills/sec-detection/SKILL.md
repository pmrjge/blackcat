---
name: sec-detection
description: Use when writing security detection — audit logging, Semgrep/CodeQL rules, Sigma rules, canaries; alert handling is sec-incident-response.
---
# Detection
Hub: `secure-coding`. Detection answers "would we notice?" for each top threat in the threat model (`sec-threat-model`).

## 1. Security logging (the source of every detection)
- Log security events as structured records: authentication success and failure, MFA changes, password resets, privilege and role changes, authorization denials, admin actions, API-key creation and use, data exports, configuration changes, and every side-effecting agent tool call with its arguments.
- Fields: UTC timestamp, actor (user/service id), source (IP, client, session id hash), action, target object, outcome, request id. Never the secret, token, password or full body (`sec-secrets` on redaction).
- Ship logs off the host they describe (an attacker with root edits local logs); keep retention long enough to cover your detection lag.
- Clock sync on every host (NTP); otherwise timelines in `sec-incident-response` are guesswork.

## 2. Detection rules
- Start from abuse cases, not from a tool: one rule per threat, each with a test event that fires it and a benign event that must not.
- **Code-level (SAST):** custom rules for your own anti-patterns (e.g. raw SQL helpers, `shell=True`, `yaml.load`) in Semgrep or CodeQL; run them in CI on changed files; every rule ships with a positive and a negative fixture. Version and syntax checks: unverified here — read the tool's current docs before writing rules.
- **Log/SIEM rules:** Sigma (YAML, vendor-neutral) converted to the backend with the pySigma-based `sigma` CLI: `sigma plugin install <backend>`, `sigma list targets`, `sigma convert -t <target> -f <format> ./rules` (pipelines via `sigma list pipelines`).
- **Host rules:** process, file and network telemetry (osquery, auditd, Falco on Linux; Endpoint Security-based tools on macOS) — unverified here; check each tool's docs and install path before recommending.
- Thresholds and baselines: count-based rules (N failed logins per account per window; logins from new countries; spikes in 403s or exports) with the window and N written in the rule.

## 3. Deception and canaries
- Canary credentials (fake API keys in plausible places), canary files and DNS names: any use is a high-confidence alert. Store which canary lives where; never place one where a legitimate process will touch it.

## 4. Alerting
- Each alert names: what fired, why it matters, the first three triage steps, and the owner. An alert nobody acts on is deleted or tuned, not muted forever.
- Route high-confidence alerts (canaries, impossible admin actions) to a paging channel; noisy heuristics to a daily review.

## Verify
- [ ] Every top threat in the threat model maps to a log event and a rule, or is listed as undetected with a reason.
- [ ] Each rule fires on its test event and stays silent on its benign event (run it, keep the fixtures in the repo).
- [ ] Logs contain no secrets: grep a day of logs for token prefixes and `Authorization`.
- [ ] Off-host log shipping confirmed by finding a fresh test event at the destination.

## Sources
- Verified 2026-10-02 https://sigmahq.io/docs/digging-deeper/backends.html — `sigma plugin install`, `sigma list targets`, `sigma convert -t {target} -f {output_format} ./rules`, `sigma list pipelines`.
