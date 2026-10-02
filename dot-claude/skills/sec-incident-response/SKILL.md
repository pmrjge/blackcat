---
name: sec-incident-response
description: Use when something may be compromised — triage, containment, evidence, credential rotation, postmortem.
---
# Incident response
Hub: `secure-coding`. For one leaked secret the short path is in `sec-secrets` (revoke and rotate first). This module covers anything wider.

## Ground rules
- Containment, rotation, wiping hosts, notifying anyone outside the team and any action on a system you don't own are the user's decisions: propose them with the exact command, then wait for consent.
- Work from a clean machine and clean credentials when the compromise may include your own workstation or tokens.
- Preserve before you change: every containment step that destroys state (reboot, reimage, `docker rm`, log rotation) is preceded by evidence capture.
- Keep a timestamped log (UTC) of every observation and action from the first minute: `.claude-work/<incident>/timeline.md`.

## Phases
1. **Triage:** what was observed, by whom, when; which assets from the threat model are involved; is it ongoing? Assign severity by impact on the assets, not by how alarming the alert looks.
2. **Scope:** which hosts, accounts, keys, repositories and data are touched; from logs (`sec-detection`), forge audit logs, cloud audit trails, `last`/`journalctl`/shell history, recent commits and CI runs, new SSH keys, new OAuth apps or tokens, unexpected cron/launchd/systemd units.
3. **Preserve evidence:** copy logs off the host; record running processes, network connections and listening ports (`ps auxww`, `lsof -nP -i`, `ss -tupan`); hash collected files (`shasum -a 256`); snapshot disks or VMs where the platform allows. Store evidence read-only with its hash list.
4. **Contain:** revoke and rotate exposed credentials (API keys, deploy keys, OAuth tokens, session secrets, signing keys); isolate hosts from the network rather than powering them off when memory evidence matters; disable compromised accounts; block indicators (IPs, domains) at the egress proxy or firewall.
5. **Eradicate and recover:** rebuild from known-good sources (images by digest, lockfiles, reviewed commits) instead of cleaning in place; restore data from a backup older than the first malicious action and verify it; re-enable access gradually with monitoring on.
6. **Post-incident:** a blameless write-up — timeline, root cause, what detected it and how late, what slowed response; each action item has an owner and a test or rule that proves it (new detection in `sec-detection`, new control in `sec-hardening`).

## Supply-chain incidents
- A malicious dependency version: find every lockfile and image that resolved it (`git log -S '<pkg>@<ver>'`, SBOMs), treat any machine that installed it as compromised (install scripts run with the user's rights), rotate what those machines held, pin the last good version and add a cooldown (`sec-supply-chain`).

## Verify
- [ ] Timeline covers first malicious action → detection → containment → recovery, with sources for each entry.
- [ ] Every credential in scope shows revoked/rotated with time; old credentials fail when tried.
- [ ] Recovered systems built from known-good inputs; restore verified.
- [ ] Each post-incident action has an owner and a check that would have caught this incident.

## Sources
- Verified 2026-10-02 https://csrc.nist.gov/pubs/sp/800/61/r3/final — NIST SP 800-61 Rev. 3, "Incident Response Recommendations and Considerations for Cybersecurity Risk Management: A CSF 2.0 Community Profile", April 2025, supersedes Rev. 2. The phase list above is this stack's working order, not a quotation of Rev. 3.
