# Signing, pre-commit and gitleaks

## Signing with SSH keys
```bash
git config gpg.format ssh
git config user.signingkey ~/.ssh/id_ed25519.pub
git config commit.gpgsign true; git config tag.gpgsign true
git config gpg.ssh.allowedSignersFile ~/.config/git/allowed_signers
# allowed_signers line: you@example.com namespaces="git" ssh-ed25519 AAAA...
git log --show-signature -1; git verify-commit HEAD; git log --format='%h %G? %GS'
```
Upload the public key to the forge as a signing key. Never create keys or turn signing on for the user; if a
signature needs an agent or passphrase that is unavailable, stop and report instead of committing unsigned.

## Hooks: pre-commit and gitleaks
```yaml
# .pre-commit-config.yaml  (bump with `pre-commit autoupdate --freeze`, which pins commit SHAs)
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v6.0.0
    hooks:
      - {id: check-added-large-files, args: ["--maxkb=1024"]}
      - {id: check-merge-conflict}
      - {id: detect-private-key}
      - {id: end-of-file-fixer}
      - {id: trailing-whitespace}
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.30.1
    hooks:
      - {id: gitleaks}        # runs: gitleaks git --pre-commit --redact --staged --verbose
```
- `uv tool install pre-commit`; `pre-commit install` (add `--hook-type pre-push` for push hooks);
  `pre-commit run --all-files` once after adding. `SKIP=<id>` or `--no-verify` only on the user's instruction.
- gitleaks: `gitleaks git --redact -v` scans history; `--log-opts="origin/main..HEAD"` limits the range;
  `gitleaks dir <path>` scans files. False positives: `.gitleaksignore` fingerprints or a `gitleaks:allow` comment.
  (`detect`/`protect` are deprecated since 8.19.)
- Git 2.54 can also define hooks in config (`hook.<name>.event`, `hook.<name>.command`, `git hook list <event>`).
