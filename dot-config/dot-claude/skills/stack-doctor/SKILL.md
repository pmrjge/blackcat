---
name: stack-doctor
description: Check the multi-agent stack installation — binaries, API keys, MCP servers, agents, hooks, settings.
disable-model-invocation: true
---
The stack's hook (`bin/doctor.sh --hook`, UserPromptExpansion) answers this command itself, outside the Bash sandbox, and never lets it reach you. If you are reading this, that hook did not run or timed out (180 s). Do not run doctor.sh yourself or through an agent: sandboxed Bash cannot read stack.env or ~/.claude.json and reports false FAILs. Reply with exactly this line and nothing else:

stack-doctor: the stack hook did not run or timed out. Run `bash "__CLAUDE_DIR__/bin/doctor.sh"` in a terminal; to restore /stack-doctor, re-run ./install.sh in the stack repo, then restart Claude Code.
