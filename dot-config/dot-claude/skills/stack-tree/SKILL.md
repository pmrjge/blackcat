---
name: stack-tree
description: Show this session's tree of agents and subagents with the commands each ran; `table` for a markdown table, `static` for the design.
disable-model-invocation: true
---
The stack's hook (`bin/stack-tree --hook`, UserPromptExpansion) answers this command itself and never lets it reach you. If you are reading this, that hook did not run or timed out (30 s). Do not rebuild the tree yourself or through an agent. Reply with exactly this line and nothing else:

stack-tree: the stack hook did not run or timed out. Run `/usr/bin/python3 "__CLAUDE_DIR__/bin/stack-tree"` in a terminal (`--table`, `--static`, `--help`); to restore /stack-tree, re-run ./install.sh in the stack repo, then restart Claude Code.
