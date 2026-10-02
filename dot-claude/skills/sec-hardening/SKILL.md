---
name: sec-hardening
description: Use when locking down a service, container, host or CI runner — least privilege, dropped capabilities, sandboxing, network limits.
---
# Hardening
Hub: `secure-coding`. Hardening limits the blast radius of a bug the code review missed; it never replaces fixing the bug. Mechanics live in the platform skills — this module is the order of work and the checks.

## Order of work
1. **Inventory exposure:** listening ports and sockets, public URLs, mounted volumes, credentials each process holds, outbound destinations. Anything not needed is removed, not filtered.
2. **Identity:** a dedicated non-root user per service; no shared accounts; credentials scoped to one purpose, short-lived where the platform allows (federated cloud credentials, OIDC in CI — `ci-cd-pipelines`).
3. **Filesystem:** read-only root; writable state only in named directories; secrets as 0600 files or credentials, never env dumps (`sec-secrets`); `umask 077` for services that write private files.
4. **Process sandbox:** drop all capabilities, then add back only the ones needed; no new privileges; syscall and address-family filters where the platform supports them; resource limits (memory, CPU, PIDs, open files) so one runaway process cannot starve the host.
5. **Network:** bind loopback or a private interface (`sec-local-servers`); egress allowlist for services that only call known hosts; TLS 1.2+ with verification on (`sec-crypto`); HTTP security headers (CSP, `nosniff`, `frame-ancestors`) as in `sec-web-vulns`.
6. **Updates:** a dated plan for OS packages, base images and dependencies (`sec-supply-chain`); rebuild images on base-image advisories.
7. **Observe:** logs and alerts for the events that matter (`sec-detection`).

## Where the mechanics live
| Target | Skill and section |
|---|---|
| Container images and `docker run` flags (`--read-only`, `--cap-drop ALL`, `--security-opt no-new-privileges`, non-root `USER`, no Docker socket) | `container-images` § Runtime hardening |
| systemd services (`DynamicUser=`, `ProtectSystem=strict`, `NoNewPrivileges=`, `SystemCallFilter=@system-service`, `systemd-analyze security`) | `self-hosting-ops` § systemd |
| Exposure over Tailscale, reverse proxy, published ports | `self-hosting-ops` |
| CI runners and workflow tokens | `ci-cd-pipelines` |
| Kubernetes, cloud IAM | `terraform-opentofu` for IaC; cluster specifics unverified here |
| Agent tool sandboxes, MCP servers | `sec-llm-apps` |

## SSH and admin access (Linux hosts)
- Key-only authentication (`PasswordAuthentication no`, `KbdInteractiveAuthentication no`), `PermitRootLogin no`, an `AllowUsers`/`AllowGroups` list; validate with `sshd -t` before reloading, and keep a second session open while you test.
- Prefer access over a private overlay network (Tailscale) to a public port 22; rate-limit or alert on public SSH if it must exist.
- `sudo` only for named admins; no passwordless sudo for service users.

## Verify
- [ ] Exposure inventory written; every open port and credential has an owner and a reason.
- [ ] The service still works under the hardened settings: start it, run its health check and one real request.
- [ ] Platform score or lint recorded before and after (e.g. `systemd-analyze security <unit>`, `docker inspect` of `User`, `ReadonlyRootfs`, `CapDrop`).
- [ ] One negative test per control: writing outside the allowed path fails, an outbound call to a non-allowlisted host fails.

## Sources
- Verified 2026-10-02 https://man7.org/linux/man-pages/man5/systemd.exec.5.html — `NoNewPrivileges=`, `ProtectSystem=strict`, `ProtectHome=`, `CapabilityBoundingSet=`, `DynamicUser=` present; other directive names are from `self-hosting-ops` and unverified here.
- Unverified as of 2026-10-02: the OpenSSH directive names above (stable for many releases; check `man sshd_config` on the host).
