---
name: stack-doctor
description: Check the multi-agent stack installation — binaries, API keys, MCP servers, agents, hooks, settings.
disable-model-invocation: true
context: fork
agent: claude-code-guide
background: false
allowed-tools: Bash(bash *)
---
Run the stack health check and report on it. This is a read-only check: do not fix anything.

1. Run: `bash "__CLAUDE_DIR__/bin/doctor.sh" 2>&1 | tail -n 150`
2. Summarize for the user: FAIL lines first, each with its exact fix command; then WARN lines; then one line saying what is healthy. Be brief. Never print key values.
