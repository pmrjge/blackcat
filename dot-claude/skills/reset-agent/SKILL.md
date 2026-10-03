---
name: reset-agent
description: Use to undo /override-agent for one delegated agent type, or all, in this session (model and effort back to the definition's).
disable-model-invocation: true
argument-hint: <agent|all>
---
The stack's hook (agent_guard.py override-agent, UserPromptExpansion) answers this command itself and never lets it reach you. If you are reading this, that hook did not run and nothing changed. Do not change anything yourself. Reply with exactly this line and nothing else:

reset-agent: the stack hook did not run, nothing changed. Re-run ./install.sh in the stack repo, then restart Claude Code.
