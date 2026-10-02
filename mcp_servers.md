# Apps and tools for your Claude subscription

Sep 27, 2026 · @Pedro Jorge

Two kinds of tools work with your Max 20x plan: apps that run Claude Code itself under your login, which load your `~/.claude` stack, and connectors that give Claude a design, media or maths tool, each billed by that tool's own plan or free. Best picks first, then the full lists.

## Best pick per job

For coding, keep Claude Code with your stack in the terminal and add Conductor for parallel work; for everything else, add one connector per job from this table.

| Job | Best pick | Why | Next best |
| --- | --- | --- | --- |
| Coding, deep work | Claude Code in Ghostty or Terminal | Every feature of your stack, including `claude-ninja` and `claude-god` at ultracode | Claude Desktop, Code tab |
| Coding, many tasks at once | [Conductor](https://conductor.build) | Parallel chats in git worktrees; loads your `~/.claude` as is | Superset, Emdash, Claude Squad |
| UI and visual design | [Claude Design](https://claude.com/product/design) + [Figma MCP](https://developers.figma.com/docs/figma-mcp-server/) | Design from a prompt, then read and write real Figma files | Penpot (free, open source), Canva |
| Vector graphics (SVG) | [Recraft](https://www.recraft.ai/docs/mcp-reference/remote-server) | Generates true vector images and vectorizes rasters | SVGator for animated SVG; Illustrator (Beta) MCP |
| Image generation | [ComfyUI](https://docs.comfy.org/agent-tools/mcp) locally + [fal](https://mcp.fal.ai/mcp) for hosted models | ComfyUI runs on your Mac at no cost; fal reaches hundreds of hosted models through one server | BFL FLUX, Replicate, Krea, Runway |
| Motion graphics | [Remotion Agent Skills](https://www.remotion.dev/docs/ai/skills) | Videos as React code that Claude Code writes, previews and renders | HyperFrames, Rive, Lottie Creator |
| Video editing | [DaVinci Resolve 21.1](https://www.cgchannel.com/2026/09/blackmagic-design-releases-resolve-21-1/) | Built-in MCP server: edit timelines by instruction | Descript |
| 3D | [MCP for Blender](https://github.com/ahujasid/blender-mcp) | Drives Blender through its Python API | Spline, Blender Lab's official server |
| Diagrams | [draw.io](https://www.drawio.com/docs/manual/generate/drawio-mcp-server/) plugin | Free; writes `.drawio` files you can edit | Excalidraw, Mermaid |
| Maths | [Wolfram](https://claude.com/marketplace/connectors-plugins) connector | Already in your stack, free: exact computation and curated data | Lean tools, math-olympiad skills |
| Papers | alphaXiv connector | Search and full text of arXiv | arxiv-mcp-server, Elicit |

## Coding apps that run Claude Code on your plan

Every row works with your Claude login, no API key; rows marked Yes run Claude Code with your user settings, so your whole stack loads (BlackCat, 33 agents, 61 skills, hooks, MCP servers). In those, pick Sonnet 5.5 and low effort for BlackCat chats.

| App | What it is | Your stack |
| --- | --- | --- |
| [Claude Code](https://code.claude.com/docs/en/overview) CLI | The reference, in any terminal | Yes, everything |
| Claude Desktop, Code tab | Local sessions with diff view and preview | Yes; add the background-model variable in its Local environment |
| Claude Code on the web and mobile | Cloud sessions on your GitHub repos | No: the repo's `.claude/` only |
| [VS Code extension](https://marketplace.visualstudio.com/items?itemName=anthropic.claude-code) | Also runs in Cursor, Windsurf and Kiro | Yes |
| JetBrains plugin | Your `claude` in the IDE terminal, with IDE diffs | Yes |
| Xcode 26.3 or later | Xcode's Claude Agent, signed in with your Claude account | No |
| [claude-code-action](https://github.com/anthropics/claude-code-action) | GitHub Actions; `claude setup-token` gives the OAuth token | Repo's `.claude/` only |
| Claude in Slack | Hands a thread's coding task to a cloud session | No |
| Claude for Excel, PowerPoint, Word | Office add-ins; Outlook in beta | No |
| [Conductor](https://conductor.build) | Parallel chats in git worktrees, diff review | Yes |
| [T3 Code](https://github.com/pingdotgg/t3code) | Open-source GUI for Claude Code and Codex | Yes |
| [Nimbalyst](https://github.com/nimbalyst/nimbalyst) | Visual workspace, successor of Crystal | Yes; its effort control overrides every agent's effort |
| [Sculptor](https://github.com/imbue-ai/sculptor) | Imbue's app; runs Claude Code sandboxed with auto-approved tools | Yes; swaps in its own question and plan tools |
| [Superset](https://github.com/superset-sh/superset) | Many agents in worktrees, terminal-first | Yes |
| [Emdash](https://github.com/generalaction/emdash) | Parallel agents in worktrees | Yes |
| [Vibe Kanban](https://github.com/BloopAI/vibe-kanban) | Kanban board; each card runs an agent | Yes |
| [Claude Squad](https://github.com/smtg-ai/claude-squad) | tmux manager for many sessions | Yes |
| [cmux](https://github.com/manaflow-ai/cmux) | macOS terminal built for agents: tabs, notifications | Yes |
| [Jean](https://github.com/coollabsio/jean) | Projects, worktrees and sessions across agent CLIs | Yes |
| [Maestro](https://github.com/pedramamini/Maestro) | Agent orchestration desktop app | Yes |
| [CCManager](https://github.com/kbwo/ccmanager) | Session manager across worktrees | Yes |
| [Vibeyard](https://github.com/elirantutia/vibeyard) | IDE for coding agents; several logins side by side | Yes |
| [Cate](https://github.com/0-AI-UG/cate) | Zoomable canvas of editor, terminal and browser panels | Yes, in its terminals |
| [Warp](https://www.warp.dev) | Terminal with agent management | Yes |
| [Zed](https://zed.dev) | Claude Agent through the ACP adapter | Yes; a few slash commands hidden |
| Emacs: [agent-shell](https://github.com/xenodium/agent-shell), [claude-code-ide.el](https://github.com/manzaltu/claude-code-ide.el) | Claude Code inside Emacs | Yes |
| Neovim: [claudecode.nvim](https://github.com/coder/claudecode.nvim), [CodeCompanion](https://github.com/olimorris/codecompanion.nvim) | Claude Code inside Neovim | Yes |
| [Claudian](https://github.com/YishenTu/claudian) | Claude Code in an Obsidian vault | Yes |
| [CloudCLI](https://github.com/siteboon/claudecodeui) | Web and phone UI for Claude Code on your Mac | Yes |
| [Happy](https://github.com/slopus/happy), [HAPI](https://github.com/tiann/hapi) | Phone apps that drive Claude Code on your Mac | Yes |
| [AionUi](https://github.com/iOfficeAI/AionUi) | Desktop GUI for CLI agents | Yes, until you enable an AionUi MCP server |
| [Claude Threads](https://github.com/anneschuth/claude-threads) | Claude Code sessions in Slack or Mattermost threads | Yes |
| [Cline](https://github.com/cline/cline) | VS Code agent with a Claude Code provider | Partly: Cline drives, `claude` answers |
| [Goose](https://github.com/block/goose) | Block's agent, through its Claude ACP provider | Partly |

The Claude app itself (web, desktop, phone) adds chat, research, artifacts and Claude Design on the same plan; it runs its own agent, not your `~/.claude`.

## Design and graphics

Claude Design covers most visual work inside your plan; connect Figma or Penpot when the result must live in a design file.

| Tool | What Claude does with it | Connect | Cost |
| --- | --- | --- | --- |
| [Claude Design](https://claude.com/product/design) | Screens, flows, posters and prototypes from a prompt, exported as PDF or image | Built into Claude | Your plan |
| [Figma MCP](https://developers.figma.com/docs/figma-mcp-server/) | Reads design context for code, and writes native frames and components to the canvas | Remote: `https://mcp.figma.com/mcp` | Starter seats: 20 calls a month; Dev or Full seats: 200 a day; canvas writes aren't rate-limited |
| [Penpot](https://help.penpot.app/mcp/) | The same for Penpot's open-source design files | `npx @penpot/mcp@stable` | Free |
| Adobe connector | Edits and combines images, documents and designs with Adobe tools | Remote: `https://adobe-creativity.adobe.io/mcp` | Adobe account |
| [Illustrator (Beta)](https://helpx.adobe.com/in/illustrator/desktop/connect-with-other-apps-and-tools/about-using-ai-tools-with-illustrator.html) | Its built-in MCP server reads, creates and exports artwork | Your stack's designer agent drives it through illustrator-mcp-server; Adobe's own server is in the Illustrator beta | Creative Cloud |
| Canva | Creates, edits and exports Canva designs | Remote: `https://mcp.canva.com/mcp` | Canva free or Pro |
| [Affinity](https://www.affinity.studio) | Automates repetitive work in the Affinity app | Desktop extension from the connector directory | App is free |
| Sketch | Explores and organizes your Sketch documents | Local server inside the Sketch app | Sketch plan |
| Framer | Builds and edits Framer sites through its External Agent connection; no separate MCP needed | Framer's agent setup | Framer account |
| v0 | Generates full-stack web apps | Remote: `https://v0.app/api/mcp` | v0 account |
| Brandfetch, Frontify | Your brand's logos, colours and guidelines, so output stays on brand | Remote connectors | An account with each |
| Unsplash, Shutterstock | Stock photos to place in layouts | Remote connectors | Unsplash free; Shutterstock licence |
| Mobbin | Real app screens as UI references | Remote: `https://api.mobbin.com/mcp` | Mobbin account |

Figma's remote server also works in Claude Desktop; the connector directory lists the rest with one-click setup for the Claude app.

## Vector graphics and SVG

Recraft is the hosted generator that returns real vector files; for icons, logos, charts and diagrams, Claude writes clean SVG itself.

| Tool | Use | Connect | Cost |
| --- | --- | --- | --- |
| [Recraft](https://www.recraft.ai/docs/mcp-reference/remote-server) | Raster or vector images from a prompt, vectorizing rasters, reusable styles | `claude mcp add --transport http recraft https://mcp.recraft.ai/mcp`, then `/mcp` to sign in | Recraft credits, same prices as its web app |
| [SVGator](https://www.svgator.com/help/svgator-mcp/connect-svgator-to-your-ai-assistant) | Animated SVG from your SVGator projects | `claude mcp add --transport http svgator https://mcp.svgator.com/mcp` | SVGator account |
| Illustrator (Beta) | Vector artwork created and exported in Illustrator | Your stack's designer agent, or the beta's built-in server | Creative Cloud |
| Figma, Penpot | Vector frames and components inside design files | See Design and graphics | See above |
| Claude, no tool | Hand-written SVG; in your stack the designer agent with the brand-identity, typography and color-management skills | Nothing to add | Your plan |
| Inkscape | Conversions such as SVG to PDF or PNG from its command line | No official MCP; Claude runs the CLI | Free |

## Image generation

Keep the Opper server your stack already has, add ComfyUI for free local generation, and add fal or FLUX for the strongest hosted models. All of these bill outside your Claude plan except ComfyUI on your own Mac.

| Tool | Models and use | Connect | Cost |
| --- | --- | --- | --- |
| Opper (in your stack) | Many providers' image models behind one key: generate, edit, upload references | Set `OPPER_API_KEY` in `~/.claude/stack.env` | Opper credits |
| [ComfyUI](https://docs.comfy.org/agent-tools/mcp) | Images, video, audio and 3D from your own workflows, models and custom nodes | Local: [comfy-mcp](https://github.com/Comfy-Org/comfy-mcp). Cloud: `/plugin marketplace add Comfy-Org/comfy-skills`, then `/plugin install comfy-cloud@comfy-skills` | Local free (partner models such as FLUX use credits); Cloud needs a Comfy Cloud plan |
| [fal](https://mcp.fal.ai/mcp) | Hundreds of hosted image and video models | `claude mcp add --transport http fal-ai https://mcp.fal.ai/mcp --header "Authorization: Bearer $FAL_KEY"` | Pay per use |
| [BFL FLUX](https://docs.bfl.ml/api_integration/mcp_integration) | FLUX images and video: generate, edit, vary, reuse results | `claude mcp add --transport http FLUX https://mcp.bfl.ai`; signs in on first use | BFL credits |
| [Replicate](https://replicate.com/docs/reference/mcp) | Any public model on Replicate | Remote `https://mcp.replicate.com`; web sign-in with your API token | Pay per use |
| [Krea](https://www.krea.ai/docs/developers/mcp) | Krea's image and video models | Remote `https://api.krea.ai/mcp`, sign in with your Krea account | Krea compute units |
| [Runway](https://runway.com/mcp) | Images and video with Gen-4.5, Seedance 2.5, Kling 3.0 and Veo 3.1, as your plan allows | Remote connector, [setup](https://help.runwayml.com/hc/en-us/articles/51931843164691-Connecting-to-Runway-MCP) | Runway credits |
| Google Imagen, Veo | Google's image and video models through Vertex AI | MCP servers in the `experiments/` folder of [vertex-ai-creative-studio](https://github.com/GoogleCloudPlatform/vertex-ai-creative-studio) | Google Cloud billing |

OpenAI's image models, Ideogram, Stability and Midjourney have no official MCP server; for the ones with an API, Claude calls it from a script, after downscaling any input image.

## Motion graphics, video and audio

For motion made in code, Remotion's skills are the best fit for Claude Code; for motion made in an editor, your stack's motion-designer agent already drives After Effects and Premiere Pro once you run `./install.sh --with-adobe`.

| Tool | Use | Connect | Cost |
| --- | --- | --- | --- |
| [Remotion Agent Skills](https://www.remotion.dev/docs/ai/skills) | Videos as React code: create, preview in Studio, render | `npx remotion skills add` in a Remotion project; the old hosted Remotion MCP is deprecated | Free for individuals and small teams; companies need a licence |
| After Effects, Premiere Pro (in your stack) | Comps, layers, keyframes, expressions; edits, sequences, exports | `./install.sh --with-adobe` | Creative Cloud |
| [HyperFrames](https://hyperframes.heygen.com) by HeyGen | Animated slides and motion graphics written in HTML, rendered in the cloud | Remote: `https://mcp.heygen.com/mcp/hyperframes` | HeyGen account |
| [Rive](https://rive.app/docs/editor/ai/mcp) | Artboards, state machines, view models and shapes for interactive animation | MCP in the Rive desktop editor (macOS, Windows) | Rive account |
| [Lottie Creator](https://docs.lottiefiles.com/en/creator/13_ai-tools/lottie-creator-mcp) | Builds and edits Lottie animations layer by layer | Local bridge to LottieFiles Creator | LottieFiles account |
| Moda | Editable decks, ads, social posts and motion graphics | Remote: `https://agents.moda.app/mcp` | Moda account |
| [DaVinci Resolve 21.1](https://www.cgchannel.com/2026/09/blackmagic-design-releases-resolve-21-1/) | Controls the edit by instruction, released 8 Sep 2026 | Built-in MCP server | 21.1 moved Python scripting to Studio ($295): check your edition |
| Descript | Imports, edits or creates video from prompts | Remote: `https://api.descript.com/v2/mcp/claude` | Descript account |
| Riverside, Tella | Edit, clip and publish recordings and podcasts | Remote connectors | Account with each |
| Splice | Search sounds and build stacks for a soundtrack | Remote: `https://mcp.splice.com/mcp` | Splice account |
| Manim, ffmpeg | Maths animation and any conversion, cut or encode | Nothing: Claude writes the code; your motion-graphics and media-ffmpeg skills cover them | Free |

## 3D and CAD

Blender through MCP for Blender is the most capable free route; Spline suits web 3D, and Fusion covers CAD.

| Tool | Use | Connect | Cost |
| --- | --- | --- | --- |
| [MCP for Blender](https://github.com/ahujasid/blender-mcp) | Creates and modifies objects and materials, runs Python in Blender, pulls Poly Haven and Sketchfab assets, generates models with Hyper3D Rodin | `uvx blender-mcp install-addon`, enable the add-on, then `claude mcp add --scope user blender -- uvx blender-mcp` | Free (community project) |
| Blender Lab's server | Blender's Python API and documentation through natural language | Desktop extension in the [connector directory](https://claude.com/marketplace/connectors-plugins) | Free |
| [Spline](https://docs.spline.design/generate/spline-mcp-server) | Builds and edits 3D scenes and Hana designs, generates 3D models and images | Built into the Spline desktop app (macOS, Windows) | Spline account |
| Autodesk Fusion | Creates, modifies and inspects CAD geometry | Desktop extension in the connector directory | Fusion licence |
| three.js | 3D on the web, written by Claude directly | Nothing to add | Free |
| [houdini-mcp](https://github.com/kleer001/houdini-mcp) | Drives Houdini (nodes, sims, PDG, USD/Solaris, renders) through a Houdini-side plugin over local TCP; starts headless hython when no GUI runs | Optional, not enabled in your stack: its bootstrap installs a plugin and a `pythonrc.py` hook into your Houdini preferences; then `claude mcp add --scope user houdini -- uv --directory <repo> run python houdini_mcp_server.py` and `mcp__houdini` on vfx-td's tools line | Free (MIT) |

## Diagrams and whiteboards

For diagrams that live in a repository, Mermaid and draw.io files cost nothing; team whiteboards need the whiteboard's own connector.

| Tool | Use | Connect | Cost |
| --- | --- | --- | --- |
| [draw.io](https://www.drawio.com/docs/manual/generate/drawio-mcp-server/) | Editable `.drawio` diagrams, images or share links | `/plugin marketplace add jgraph/drawio-mcp`, then install its `drawio` plugin; or `npx @drawio/mcp` | Free |
| Mermaid, Graphviz, D2 | Diagrams as code in Markdown and docs | Nothing: your diagrams-as-code skill writes and renders them | Free |
| Excalidraw | Hand-drawn style sketches | Claude writes `.excalidraw` files; your diagrams-as-code skill covers the format | Free |
| tldraw | Sketch and diagram together on a canvas | Remote connector for the Claude app and Desktop | Free |
| Lucid | Lucidchart diagrams and docs | Remote: `https://mcp.lucid.app/mcp` | Lucid plan |
| Whimsical | Flowcharts, mind maps, wireframes | Remote: `https://mcp.whimsical.com/mcp` | Whimsical account |
| Eraser | Architecture diagrams and design docs | Remote: `https://app.eraser.io/api/mcp` | Eraser account |
| Miro | Boards shared with your team | Miro's connector | Miro plan |

## Maths and research

Your stack's mathematician agent (Opus 5.5 at xhigh) with the formal-methods, latex-typesetting and literature-review skills handles proofs and write-ups, the proof-checker agent referees them and checks Lean proofs; Wolfram adds exact computation.

| Tool | Use | Connect | Cost |
| --- | --- | --- | --- |
| Wolfram | Exact symbolic and numeric computation, curated data | Already in your stack for the mathematician: `https://agenttools.wolfram.com/mcp` | Free, no key |
| math-olympiad skills | Anthropic's competition-maths skills | `./install.sh --with-extra-plugins` | Free |
| Lean 4 and Mathlib | Machine-checked proofs | In your stack: proof-checker runs `lean-lsp-mcp` itself and mcp-broker can mount the catalog copy; you install elan and a built Mathlib Lake project and set `LEAN_PROJECT_PATH` in stack.env; LeanExplore searches Mathlib | Free |
| [arxiv-mcp-server](https://github.com/blazickjp/arxiv-mcp-server) | Search, download and read arXiv papers | In your stack's catalog as `arxiv` | Free |
| alphaXiv | Search and full text of arXiv papers | Remote: `https://api.alphaxiv.org/mcp/v1` | Free |
| Elicit | Search and analyse scientific papers | Remote: `https://elicit.com/api/mcp` | Elicit plan |
| Manim | Maths animations | Nothing: Claude writes the scenes | Free |

## On demand and automatic

Each server loads automatically when an agent's work needs it and on request otherwise, and costs nothing while idle. An inline server starts and stops with its one agent. A catalog server stays unmounted until an agent's one-line pointer ("cluster state → mcp-broker mounts `kubernetes`") or your request sends mcp-broker to it. Nothing new went into user scope. Plugins are session-wide, never per agent; skills are listed with a description and loaded by name. The full matrix with idle costs is in CONFIG.md §5, "On demand and automatic".

## Engineering domains

Servers for the database, mobile, game, embedded, HPC, bio/chem, cloud and finance agents, vetted on 2 Oct 2026 (licence, last release, flags, telemetry). In your stack they run either inside one agent (inline) or through mcp-broker's catalog, where every call asks you first.

| Tool | Use | In your stack | Cost |
| --- | --- | --- | --- |
| [postgres-mcp](https://github.com/crystaldba/postgres-mcp) 0.3.0 | Schema, read-only SQL, EXPLAIN, index advice | Inline in db-engineer, `--access-mode=restricted`; `DATABASE_URI` in stack.env | Free |
| [mongodb-mcp-server](https://github.com/mongodb-js/mongodb-mcp-server) 3.0.5 | find, aggregate, explain, indexes | Inline in db-engineer, `--readOnly`, telemetry off; `MDB_MCP_CONNECTION_STRING` | Free |
| [MobileBuildMCP](https://github.com/getsentry/MobileBuildMCP) 2.7.1 (was XcodeBuildMCP) | Xcode builds, tests, simulators | Inline in mobile-engineer (macOS), Sentry telemetry off | Free |
| [mobile-mcp](https://github.com/mobile-next/mobile-mcp) 1.0.8 | iOS simulator and Android emulator UI: screenshots, taps, installs | Catalog `mobile` (no read-only mode; telemetry off) | Free |
| [android-mcp](https://github.com/us-all/android-mcp-server) 1.14.4 | Android over adb, read-only by default | Catalog `android` | Free |
| [godot-mcp](https://github.com/Coding-Solo/godot-mcp) 0.1.1 | Run Godot projects, edit scenes, read debug output | Catalog `godot`; `GODOT_PATH` | Free |
| [biomcp](https://github.com/genomoncology/biomcp) 0.9.1 | PubMed, trials, variants, genes, drugs (public APIs) | Catalog `biomcp`; optional `NCBI_API_KEY` | Free |
| [pubchem-mcp-server](https://github.com/cyanheads/pubchem-mcp-server) 0.6.5 | PubChem compounds, read-only | Catalog `pubchem` | Free |
| [kubernetes-mcp-server](https://github.com/containers/kubernetes-mcp-server) 0.0.67 | Pods, logs, events through your kubeconfig | Catalog `kubernetes`: read-only, Secrets denied (`magg/k8s-mcp.toml`) | Free |
| [mcp-grafana](https://github.com/grafana/mcp-grafana) 2.0.0 | Dashboards, datasources, alerts | Catalog `grafana`, `--disable-write`, usage stats off; `GRAFANA_URL`, `GRAFANA_SERVICE_ACCOUNT_TOKEN` | Free |
| [sec-edgar-mcp](https://github.com/stefanoamorelli/sec-edgar-mcp) 1.1.0 | SEC filings and XBRL financials (AGPL-3.0) | Catalog `sec-edgar`; `SEC_EDGAR_USER_AGENT` | Free |
| [serial-mcp](https://github.com/qarnet/serial-mcp) 0.9.3 | Serial consoles of dev boards, port allowlist | Catalog `serial`; `cargo install serial-mcp@0.9.3 --locked` first | Free |
| [gis-mcp](https://github.com/mahdin75/gis-mcp) 0.15.0 | Geometry, CRS, vector and raster operations | Catalog `gis` | Free |

Documented, not installed (heavy, an app plugin, cloud credentials or hardware writes): [unity-mcp](https://github.com/CoplayDev/unity-mcp) (Unity Editor package; set `DISABLE_TELEMETRY`), [Unreal_mcp](https://github.com/ChiR24/Unreal_mcp) (C++ editor plugin), AWS [aws-api-mcp-server](https://github.com/awslabs/mcp) (`READ_OPERATIONS_ONLY=true`, telemetry off), Azure (`npx -y @azure/mcp@2.0.5 server start --read-only`, `AZURE_MCP_COLLECT_TELEMETRY=false`), [gcloud-mcp](https://github.com/googleapis/gcloud-mcp) 0.5.3 (no read-only flag), [Alpha Vantage](https://github.com/alphavantage/alpha_vantage_mcp) (API key passed on the command line), [KiCAD-MCP-Server](https://github.com/mixelpixx/KiCAD-MCP-Server) v2.8.2 (built from git), [embedded-debugger-mcp](https://github.com/Adancurusul/embedded-debugger-mcp) v0.3.0 (writes flash), [slurm-mcp-server](https://github.com/charlie-z-work/slurm-mcp-server) 2.0.1 (submits jobs over SSH), [lara-mcp](https://github.com/translated/lara-mcp) 2.0.0 (cloud translation memory), [houdini-mcp](https://github.com/kleer001/houdini-mcp) (see 3D), gopls's built-in `gopls mcp` (experimental; the gopls LSP plugin already gives go-engineer code intelligence).

Rejected: lamaalrajih/kicad-mcp (unmaintained since 2025-10), qgis_mcp (no licence), the audio servers whisper-mcp, local-stt-mcp and mcp-music-analysis (unmaintained), runreal/unreal-mcp (unmaintained), tandemai mcp-rdkit (repository gone), Flux159 mcp-server-kubernetes (its non-destructive mode still writes), unlicensed SLURM servers.

## Connecting a tool, and the 1920 px image limit

A new connector takes one command, but your stack's agents see it only once it is on their tool list.

1. Add it for every project: `claude mcp add --transport http --scope user recraft https://mcp.recraft.ai/mcp`; for a local server, `claude mcp add --scope user <name> -- npx -y <package>`. Then run `/mcp` once to sign in.
2. Give it to an agent: add `mcp__recraft` to the `tools:` line of that agent in the repo (`dot-claude/agents/image-director.md` for image tools, `designer.md` for design tools, `motion-designer.md` for motion tools) and rerun `./install.sh`. Only agents that name a server can use it.
3. For a one-off, ask BlackCat to have mcp-broker use it, or start `claude --agent claude`, a plain session that sees every tool.
4. In the Claude app and Desktop chat, add connectors under Customize, then Connectors.

Tool schemas load only when a tool is used, so extra connectors cost almost no context.

The image limit, as installed:

- Images agents read (files, screenshots, images returned by any MCP tool) reach the model at 1919 px or less on the longest side.
- Local images passed to MCP upload or image tools (image, reference, mask and file parameters) are swapped for downscaled copies in `~/.cache/claude-agent-stack/images`; originals stay untouched.
- For curl, scripts and SDK calls, the rules make agents downscale a copy first: `sips -Z 1919 in.png --out out.png`.
- Images you paste into a chat are only capped by Claude Code's own 2000 px limit: hooks can't change a prompt.
- Generated deliverables keep their full resolution. `STACK_IMAGE_MAX_PX` changes the limit; `0` turns it off.

## Subscription rules, and what to avoid

Today every app in the coding table draws from your plan's normal usage limits, because each one runs Anthropic's own Claude Code or Agent SDK under your login.

- Anthropic announced a separate monthly credit for Agent SDK, `claude -p` and third-party app use (from $20 on Pro), then paused it on 15 June 2026: "For now, nothing has changed." It promises notice before any change ([support article](https://support.claude.com/en/articles/15036540)). If it returns, apps built on the SDK (Conductor, Zed, Nimbalyst, Sculptor, AionUi) would likely move to that credit; the terminal would not.
- Apps may not offer their own claude.ai login unless Anthropic approved them ([Agent SDK docs](https://code.claude.com/docs/en/agent-sdk/overview)).

| Avoid | Why | Instead |
| --- | --- | --- |
| [Craft Agents](https://github.com/lukilabs/craft-agents-oss) | Ships its own Claude sign-in | Any app in the coding table |
| [OpenCode](https://github.com/sst/opencode) | Can't use your Claude plan; needs an API key | Claude Code, or OpenCode with an API key |
| JetBrains AI's Claude Agent | Billed through JetBrains AI, not your plan | The Claude Code JetBrains plugin |
| Claude Tag, Code Review | Team and Enterprise plans only | Claude Code with your stack's code-reviewer agent |

## Sources

Checked 26 and 27 September 2026. Connector URLs without a link come from Anthropic's connector directory.

- Anthropic: [connector directory](https://claude.com/marketplace/connectors-plugins), [Claude Design](https://claude.com/product/design), [Agent SDK with your plan](https://support.claude.com/en/articles/15036540), [Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview), [Claude Code MCP](https://code.claude.com/docs/en/mcp)
- Coding apps: [Vibeyard](https://github.com/elirantutia/vibeyard), [Jean](https://github.com/coollabsio/jean), [Maestro](https://github.com/pedramamini/Maestro), [Claude Threads](https://github.com/anneschuth/claude-threads), [Cate](https://github.com/0-AI-UG/cate); Conductor, Desktop, Zed, Nimbalyst and AionUi were checked in their code for your stack's README
- Design: [Figma MCP](https://developers.figma.com/docs/figma-mcp-server/), [Penpot MCP](https://help.penpot.app/mcp/), [Illustrator (Beta)](https://helpx.adobe.com/in/illustrator/desktop/connect-with-other-apps-and-tools/about-using-ai-tools-with-illustrator.html), [Affinity](https://www.affinity.studio)
- Vector: [Recraft](https://www.recraft.ai/docs/mcp-reference/remote-server), [SVGator](https://www.svgator.com/help/svgator-mcp/connect-svgator-to-your-ai-assistant)
- Images: [Comfy MCP](https://docs.comfy.org/agent-tools/mcp), [BFL](https://docs.bfl.ml/api_integration/mcp_integration), [Replicate](https://replicate.com/docs/reference/mcp), [Krea](https://www.krea.ai/docs/developers/mcp), [Runway](https://runway.com/mcp), [vertex-ai-creative-studio](https://github.com/GoogleCloudPlatform/vertex-ai-creative-studio)
- Motion: [Remotion skills](https://www.remotion.dev/docs/ai/skills), [HyperFrames](https://hyperframes.heygen.com), [Rive MCP](https://rive.app/docs/editor/ai/mcp), [Lottie Creator MCP](https://docs.lottiefiles.com/en/creator/13_ai-tools/lottie-creator-mcp), [DaVinci Resolve 21.1](https://www.cgchannel.com/2026/09/blackmagic-design-releases-resolve-21-1/)
- 3D and diagrams: [MCP for Blender](https://github.com/ahujasid/blender-mcp), [Spline MCP](https://docs.spline.design/generate/spline-mcp-server), [draw.io MCP](https://www.drawio.com/docs/manual/generate/drawio-mcp-server/)
