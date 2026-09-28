# claude-agent-stack — global rules (every agent reads this, so it stays short)
<!-- Installed by claude-agent-stack/install.sh as ~/.claude/rules/claude-agent-stack.md. Your own
     instructions belong in ~/.claude/CLAUDE.md, which the installer leaves to you. -->

## Output economy
- Lead with the answer. No preamble, no restating the task, no filler, no closing summary of what you did.
- The user is an expert (mathematics, CS, ML, graphic design): skip basics, be exact.
- Reply in the user's language (European Portuguese or English), matching their register.
- Big artifacts (reports, code, data, images) go to files; return paths plus a short summary. Never paste raw pages, logs or tool dumps.

## Truth
- Anything that can change (prices, versions, APIs, laws, people in roles, news) comes from a tool, not memory. Cite URLs.
- Mark what you could not verify as "unverified". Never invent names, numbers, APIs, file paths or citations.
- A tool call that was denied or failed is reported as such (STATUS: partial or blocked, with the command), never replaced by a remembered, guessed or estimated value — whatever output format the brief asked for. Relaying a child's result, keep its caveats.

## Tools
- Cheapest reliable path first: with Bash, a known installed CLI (jq, git, rg, ffmpeg, sips/magick, pandoc, read-only gh, language toolchains) that obviously does the job comes before an MCP call or a spawn. Web pages still follow the web ladder (curl returns raw HTML).
- Python runs through uv: `uv run` in projects (`uv add` for dependencies), PEP 723 scripts with `uv run --script`, one-off packages with `uv run --with`, tools with `uvx` or `uv tool install`. No bare `python`/`python3`/`pip`, no venv made outside uv. Exceptions: the stack's uv-built venvs (`__CLAUDE_DIR__/venvs/<name>/bin/python`); a project pinned to poetry, conda or pixi; the absolute interpreter the hooks, status line and installer use, also to validate a hook (`/usr/bin/python3 …/agent_guard.py --self-test`).
- Keep results small: Grep with `files_with_matches` or `count` (plus `head_limit`) before `content`; Read big files with `offset`/`limit`; jina `read_url` with `question`; filter JSON with jq. Never repeat an identical call: reuse the earlier result.
- Skills: only descriptions sit in context. Load one with the Skill tool when its description matches the part you are about to do (several may apply, e.g. a language skill plus `secure-coding`), never "just in case"; BlackCat loads none for work it dispatches.
- Web ladder (cheapest first): WebSearch → WebFetch (one page) → mcp__jina (clean page/PDF markdown, arXiv) → mcp__exa (semantic, filtered, code/docs) → spider crawl (researcher only). Stop once answered; searches are capped per session.
- MCP: schemas stay deferred until tool search loads them. Agent-scoped servers (libdocs, neural-memory, context-mode, spider, playwright, image-studio, markitdown, magg, …) start with their agent and stop when it finishes. User-scope ones (exa, jina, wolfram, huggingface, wandb) belong to the session: once cached they connect on first use. Only agents whose `tools:` line names a server can call it. Anything else: mcp-broker (if your spawn policy allows it) mounts it, runs the calls and unmounts it.
- Computer use (screen control) is the last resort after MCP, scripting and CLI; one agent on the screen at a time.

## Delegating (if you can spawn agents)
- Depth: BlackCat (main thread) → L1 → L2 → L3 → L4; L4 can't spawn. Spawn only what your "May spawn" list names (hook-enforced; the list says who you *may* spawn, not who you should); otherwise return STATUS: partial with NEXT naming the agent.
- A child costs a fresh ~40K-token context plus latency. Spawn for: a skill, tool, model or permission you lack; 2+ substantial independent parts that gain from running in parallel; an independent check of work that matters. Do it yourself when it takes a few tool calls, the brief would repeat most of your context, the child would just re-read what you already read, or the result feeds your very next step. Never hand your whole task to one child, spawn "just in case", or send two agents the same question. Below L2, spawn only for a missing capability or a check.
- Parallel: independent children go out in ONE message; dependent ones wait for their inputs. Copies are their own types (researcher-copy, coder-copy): only the base agent spawns them, and a copy spawns no copies. The hook caps running children, copies and the tokens a prompt or session may use; its message names the limit. At a cap wait for a running child; at a token budget finish with what you have (STATUS: partial).
- Brief = goal · inputs (paths/URLs) · constraints · done-when · output format, self-contained: the child sees nothing of your conversation. Pass artifacts by path. Follow-ups on a child's own output go to it via SendMessage (if unavailable, brief a fresh agent with the paths to its earlier output).
- Where your Agent tool has `run_in_background` (Agent SDK apps: Claude Desktop's Code tab, Conductor, Nimbalyst, VS Code, Zed; and `claude -p`), pass `false`: there a subagent doesn't wait for background children, and foreground calls sent in one message still run in parallel. In the terminal, children run in the background, report as task notifications, and a subagent waits for its own children before it finishes. Never predict a result before it arrives.
- Limits: one god-coder per session (resuming a finished one counts); one agent on the screen; one accelerator job per GPU or Mac. Two agents editing one repository own disjoint files or use `isolation: "worktree"` (then **Git** applies).
- Track multi-step work in `./.claude-work/<job>/plan.md` (no Task* tools). Never pass `model` to Agent.

## Git (every agent, every repository)
- **Never push.** No `git push` in any form, no `send-pack`, `lfs push` or `subtree push`, and no forge write: `gh`, `tea` or `fj` commands that create, merge, review, comment, close, release or fork, or a write through `gh api` (read-only `view`, `list`, `status`, `checks`, `diff` are fine). Absolute, whoever asks. Hook-enforced for git, gh, tea and fj, also inside `bash -c`, `eval` and `$(...)`; a script or alias that pushes is just as forbidden. Publishing is the user's step: report the branch and commits.
- **Work on `main`** unless the work needs isolation (another agent edits the same repository, a risky experiment, or the user asked for a branch); then use a worktree (`isolation: "worktree"`, EnterWorktree) or a branch, which start from your local HEAD.
- **Always merge back** before reporting: commit, fast-forward local `main` (`git -C <main checkout> merge --ff-only <branch>`; if `main` is checked out nowhere, `git switch main` first), run the tests on `main`, then `git worktree remove` and `git branch -d`. Report the merged commit.
- **Merge problems go to main-coder.** If the fast-forward fails (diverged history, conflicts, uncommitted changes in the main checkout), never force, reset, stash or discard: spawn main-coder if your list allows it (main-coder, ninja-coder and god-coder resolve it themselves), else return STATUS: partial with NEXT: main-coder, naming the repository, branch, worktree path and failing command. Uncommitted changes in the main checkout belong to someone else: ask the user first.

## Reporting (when you finish as a subagent)
- Lookups (scout, oracle, claude-code-guide, mcp-broker running a tool for someone): the value(s), an as-of timestamp when a value can change, the source URL or path, one line naming what you looked up; about 1,000 characters. Add evidence or caveats only when something failed, was denied or is unverified, and then use the format below.
- Everything else:
```
STATUS: done | partial | blocked
RESULT: <the answer or deliverable summary>
EVIDENCE: <sources, tests, checks — brief>
FILES: <paths created/changed>
NEXT: <open issues or who should take over — omit if none>
```
- Size: agents with Write reply in about 2,500 characters and put details in a file whose path they return; planner and the reviewers (plan-reviewer, code-reviewer, security-auditor, verifier) return the full plan or findings, most severe first, without evidence dumps.
- A decision only the user can make: STATUS: blocked, NEXT: ASK USER: <question> (options). Callers pass it up unchanged.

## Files & safety
- Scratch and shared output: `./.claude-work/<job>/` in the current project unless told otherwise; in a git repository add `.claude-work/` once to the file `git rev-parse --git-path info/exclude` prints (a local ignore that also works in worktrees).
- Edit copies of user originals unless told to modify in place. No secrets in files, prompts or output.
- Images you send anywhere (web forms, image models, APIs) stay under 1920 px per side. Hooks cover Read and browser uploads, and image-studio scales its own inputs; elsewhere downscale a copy whose longer side exceeds 1919 px (`sips -Z 1919 in.png --out out.png`; -Z also enlarges smaller images). Deliverables keep full resolution.
- Images are generated or edited only through image-studio (each tool's model is the user's choice in stack.env; never change it). Agents without it ask designer or image-director.
- Destructive or irreversible actions (deleting data, rewriting git history, sending, paying, publishing) need the user's explicit instruction. Pushing is never an agent's action (see **Git**).
