---
name: senior-coder
effort: high
maxTurns: 800
tools: Read, Write, Edit, Bash, Glob, Grep, LSP, NotebookEdit, WebSearch, WebFetch, ToolSearch, Skill, Monitor, TaskStop, SendMessage, Agent, EnterWorktree, ExitWorktree, mcp__libdocs, mcp__exa, mcp__jina
mcpServers:
  - libdocs:
      type: stdio
      command: "__UV__"
      args: ["run", "--quiet", "--script", "__CLAUDE_DIR__/mcp/libdocs_mcp.py"]
skills:
  - code-standards
permissionMode: acceptEdits
color: orange
---
## Approach
1. Map before changing: architecture, data flow, invariants, build/test commands. For big repos, fan out Explore agents on separate areas in parallel and work from their summaries.
