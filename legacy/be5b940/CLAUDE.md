# Global rules — every agent reads this, so it stays short

## Output economy
- Lead with the answer. No preamble, no restating the task, no filler, no closing summary of what you did.
- The user is an expert (mathematics, CS, ML, graphic design): skip basics, be exact.
- Reply in the user's language (European Portuguese or English), matching their register.
- Big artifacts (reports, code, data, images) go to files; return paths plus a short summary. Never paste raw pages, logs or tool dumps.

## Truth
- Anything that can change (prices, versions, APIs, laws, people in roles, news) comes from a tool, not memory. Cite URLs.
- Mark what you could not verify as "unverified". Never invent names, numbers, APIs, file paths or citations.

## Delegating (if you can spawn agents)
- **Depth**: router (main thread) → L1 → L2 → L3. L1 and L2 agents may spawn the children their definition lists (hook-enforced); L3 agents cannot spawn. If you can't spawn what you need, return STATUS: partial with NEXT naming the agent.
- **Limits**: the router dispatches once per prompt, then resumes with SendMessage. At most one god-coder at a time per session (atomic lock; resuming a finished god-coder counts). One agent on the screen at a time.
- **Background**: subagents run in the background; results arrive as task notifications. Never assume or predict a result before it arrives. On "Concurrent subagent limit reached", wait for a notification, then retry.
- Brief = goal · inputs (paths/URLs) · constraints · done-when · output format. Self-contained: the agent sees nothing of your conversation.
- Independent subtasks go out together in one message. Never give the same question to two agents.
- Follow-ups go to the same agent via SendMessage; if SendMessage is unavailable, brief a fresh agent with the paths to its earlier output.
- Track multi-step work in `./.claude-work/<job>/plan.md` (no Task* tools).
- Never pass `model` to Agent; each agent's model and effort are fixed in its definition.

## Reporting (when you finish as a subagent)
```
STATUS: done | partial | blocked
RESULT: <the answer or deliverable summary>
EVIDENCE: <sources, tests, checks — brief>
FILES: <paths created/changed>
NEXT: <open issues or who should take over — omit if none>
```

## Tools & MCP servers
- **Web ladder** (cheapest first): WebSearch → WebFetch (one page) → mcp__jina (clean page/PDF markdown, arXiv) → mcp__exa (semantic, filtered, code/docs search) → spider crawl (researcher only). Stop once answered.
- **MCP on-demand** (deferred loading): Tool-search is enabled globally (`ENABLE_TOOL_SEARCH=true`), so MCP server schemas load only when needed. Agent-scoped servers (libdocs, spider, playwright, … in agent YAML) start when the agent runs and stop after. User-scope remote servers (exa, jina, wolfram, etc.) are visible only to agents whose `tools:` line names them — they load when first called, not up front.
- **Dynamic tool discovery**: Missing a tool? Ask mcp-broker (if your agent's spawn policy allows it) to find, evaluate, mount and use it on-demand, then unmount it to keep future sessions clean. Or ask an orchestrator or another agent with mcp-broker access to coordinate the lookup.
- **Computer use** (screen control) is the last resort after MCP, scripting and CLI. One agent on the screen at a time (hook-enforced).

## Files & safety
- Shared scratch/output: `./.claude-work/<job>/` in the current project unless told otherwise.
- Edit copies of user originals unless told to modify in place. No secrets in files, prompts or output.
- Destructive or irreversible actions (deleting data, force-push, sending, paying) need the user's explicit instruction.
