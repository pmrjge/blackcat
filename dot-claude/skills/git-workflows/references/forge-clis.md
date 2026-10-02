# Forge CLIs

Agents use these read-only (`gh pr view|checks`, `gh run view|watch`, `tea pulls list`); creating, merging,
reviewing or commenting on a PR/MR, releases and `gh api` writes go to the remote, so they are the user's step,
like a push (the no-push hook refuses them); the write commands below are for the user's reference.
- GitHub (`gh`): `gh pr create --fill --base main --head <branch> [--draft]`; `gh pr checks --watch --fail-fast`;
  `gh pr view --json state,mergeable,reviewDecision`; `gh pr merge --squash --delete-branch [--auto]
  [--match-head-commit <sha>]`; `gh run view <id> --log-failed`; `gh run watch <id> --exit-status`; `gh api ...`.
- Gitea/Forgejo (`tea` 0.16): `tea login add --name <n> --url <url> --token <t>`; `tea pulls create --head <b>
  --base main --title ... --description ...`; `tea pulls checkout <n>`; `tea pulls merge --style squash <n>`
  (merge|rebase|squash|rebase-merge); `tea pulls clean <n>`; `tea issues create --title ...`; `-o json`;
  `tea api` and `tea actions` exist since 0.12. Forgejo-native alternative: `fj` (forgejo-cli):
  `fj auth login`, `fj pr create "<title>" --body ...`, `fj pr merge --method <m> --delete`.
- Tokens come from the CLI's own login store or env; never paste them into commands that end up in logs.
