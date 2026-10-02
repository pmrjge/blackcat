---
name: sec-secrets
description: Use for storing, passing, logging or scanning secrets and leak response — keychains, gitleaks, rotation.
---
# Secrets
Hub: `secure-coding`. When a scanner finds a secret, report its location and type, never its value.

- **Storage:** injected at runtime from a secret manager or OS keychain — macOS `security add-generic-password -a "$USER" -s myapp -w` (prompts when `-w` is last) and `security find-generic-password -a "$USER" -s myapp -w`; Linux `secret-tool store --label=myapp service myapp` / `secret-tool lookup service myapp`; Python `keyring`; 1Password `op run --env-file=.env.tpl -- cmd` with `op://vault/item/field` references; encrypted files in git with sops + age.
- **Never in:** source, git history, container layers, CI logs, argv (visible to other users in `ps` and in shell history), URLs (query strings land in logs and referrers), crash reports, frontend bundles, prompts or tool outputs. Environment variables leak to children and to `/proc/<pid>/environ` (same user): scope them; pass secrets through stdin or a 0600 file.
- **Logs:** structured logging with explicit fields; redact by key name and value pattern; never dump headers (`Authorization`, `Cookie`) or bodies wholesale.
- **Scanning:** `gitleaks git -v` (history), `gitleaks dir -v .` (working tree), and the pre-commit hook (`id: gitleaks`, which runs `gitleaks git --pre-commit --redact --staged --verbose`); `trufflehog git file://. --results=verified,unknown` or `trufflehog filesystem .` — its verification contacts the provider, so run it only on your own repositories. Enable push protection on the forge.
- **After a leak:** revoke and rotate first (pushed = compromised), check access logs for use, then purge history (`git filter-repo`) and caches; a history rewrite alone does not un-leak. Wider compromise: `sec-incident-response`.
- **Randomness and comparison:** `secrets.token_urlsafe(32)`/`os.urandom`, Rust `getrandom`/`OsRng`, JS `crypto.getRandomValues`/`crypto.randomBytes` — never `random`/`Math.random`; compare tokens and MACs with `hmac.compare_digest`/`crypto.timingSafeEqual`.

## Verify
- [ ] `gitleaks git` and `gitleaks dir .` report nothing (or only triaged false positives with an allowlist entry).
- [ ] No secret in argv, URLs or logs: grep the CI log and a debug log of one request for the token's prefix.
- [ ] Every leaked credential has a rotation record (time, who, new secret location) before any history rewrite.

## Sources
- Verified 2026-10-02 https://github.com/gitleaks/gitleaks/releases — latest gitleaks v8.30.1. The `git`/`dir` subcommand names are unverified as of 2026-10-02.
