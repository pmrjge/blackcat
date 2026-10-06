<!-- markdownlint-disable MD013 MD060 -->
# The CLAUDE.md block

`CLAUDE.md` in your config folder stays yours. Since 2026-10-05 the installer owns exactly one block in it,
between two marker lines, and never changes a byte outside them.

## What the block says

The block is `dot-claude/CLAUDE.block.md`, rendered at install time, between the markers:

```text
<!-- claude-agent-stack: begin (install.sh rewrites this block; your own text goes outside it) -->
This config folder runs claude-agent-stack: its global rules are `rules/claude-agent-stack.md` here; the stack changes in its repo, `<your checkout>`, and reaches this folder only through `./install.sh` there.
<!-- claude-agent-stack: end -->
```

(`<your checkout>` stands for the rendered `__STACK_REPO__` placeholder: your checkout's path.) It loads with
`CLAUDE.md` into every thread except an `omitClaudeMd` agent's, and `tests/prompt_budget.py` counts it per spawn
(341 characters, about 114 tokens). `tests/cache_stability_lint.py` keeps the template free of dates, ids and
versions, so it does not break prompt caching.

## How the installer edits the file

| Your `CLAUDE.md` | What a run does | Shown as |
|---|---|---|
| does not exist | creates it with only the block | `created` |
| exists, no block | appends the block after your text, one blank line between | `added` |
| has the block the last install wrote | rewrites it in place; byte-identical when unchanged | `updated` / `unchanged` |
| has a block edited by hand (or unknown to the manifest) | replaces it; your version is in the backup | `replaced` |
| a symlink, not a regular file, read-only, not UTF-8, or markers that are not exactly one begin line followed by one end line | leaves it alone and says why in a `note:` | `skipped` |

Every byte before and after the block stays as it was, CRLF line ends, a UTF-8 BOM and a missing final newline
included. A marker line is a whole line starting with `<!-- claude-agent-stack: begin` or
`<!-- claude-agent-stack: end` and ending in `-->`. Write your own instructions outside the two marker lines.

- `--dry-run` prints the line `CLAUDE.md (the stack's block)` with what the run would do.
- `--diff` compares the installed block with the repo's render (your text outside it is never compared).
- `--restore` puts the whole file back, byte for byte, as it was before that install.
- A stack version that ships no `CLAUDE.block.md` removes the block, and a file the stack created and that is now
  empty is removed.

The manifest records the block's sha256 and whether the stack created the file (key `claude_md_block`);
`CLAUDE.md` itself never enters the manifest's file list, so nothing prunes it. The code is
`lib/claude_md_block.py` (stdlib), run on the staged copy so the plan, backup and `--restore` treat `CLAUDE.md`
like any other file. Agents cannot edit the installed `CLAUDE.md`: `Edit(/<config>/CLAUDE.md)` is a deny rule.

Tests: `tests/test_install_claude_md.py` (marker parsing, splice properties on random text, every action, the
left-alone cases, scratch-HOME installs with dry run, idempotence, `--restore` byte for byte, retraction,
`--diff`), and `tests/install_smoke.sh`.

Sources: `dot-claude/CLAUDE.block.md`, `lib/claude_md_block.py`, `dot-claude/settings.json`, `README.md` ("Your
`CLAUDE.md`"), `CONFIG.md` §7 "The `CLAUDE.md` block" and §9 (2026-10-05).
