---
name: stack-doctor
description: Check the multi-agent stack installation — binaries, API keys, MCP servers, agents, hooks.
disable-model-invocation: true
allowed-tools: Bash(bash *)
---
## Doctor report
!`bash "__CLAUDE_DIR__/bin/doctor.sh" 2>&1 | tail -n 100 || true`

Summarize the report above for the user: failures first, each with its exact fix command; then warnings; then one line saying what is healthy. Be brief.
