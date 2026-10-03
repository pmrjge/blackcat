---
name: override-agent
description: Use to run a delegated agent type on another model for this session only; `list` shows overrides, `reset` undoes them.
disable-model-invocation: true
argument-hint: <agent> <model> | list | reset <agent|all>
---
The stack's hook (agent_guard.py override-agent, UserPromptExpansion) answers this command itself and never lets it reach you. If you are reading this, that hook did not run and nothing changed. Do not apply an override yourself (no `model` on Agent calls, no state files). Reply with exactly this line and nothing else:

override-agent: the stack hook did not run, nothing changed. Re-run ./install.sh in the stack repo, then restart Claude Code.
