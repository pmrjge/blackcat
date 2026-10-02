---
name: sec-threat-model
description: Use at the start of a security design or review — assets, entry points, trust boundaries, STRIDE, mitigations.
---
# Threat model in five steps
Hub: `secure-coding` (ground rules, checklist, report format).

1. **Assets:** credentials and keys, personal data, user files, money-moving or message-sending capabilities, code execution and deploy rights, model weights, availability.
2. **Entry points:** HTTP endpoints, CLI args, environment, config files, uploads and archives, IPC/sockets, webhooks, queues, dependencies and the build pipeline, and for LLM systems every prompt, retrieved document, web page, tool result and image.
3. **Trust boundaries:** where data moves from less to more trusted — network → server, user → admin, model output → tool execution, plugin/MCP server → host, container → host. Sketch the data flow.
4. **STRIDE per boundary:** Spoofing (authn), Tampering (integrity, signatures), Repudiation (audit logs), Information disclosure (logs, errors, side channels), Denial of service (unbounded sizes, ReDoS, decompression bombs, token/cost exhaustion), Elevation of privilege (authz gaps, injection, deserialization).
5. **Rank** by impact × likelihood, choose mitigations, and write the top abuse cases as tests.

## Writing it down
- One page: a data-flow sketch (Mermaid or ASCII; `diagrams-as-code`), a table `| boundary | threat (STRIDE) | asset | mitigation | test |`, and the residual risks you accept with a reason.
- Each mitigation names where it lives (file, config, hook) so a reviewer can check it; each top abuse case names the test that proves the mitigation (`test_<abuse>_rejected`).
- Route each mitigation to its module: sinks → `sec-web-vulns`, identity → `sec-authn-authz`, secrets → `sec-secrets`, dependencies → `sec-supply-chain`, LLM paths → `sec-llm-apps`, ports, sockets and runtime limits → `sec-hardening`, logging and alerting → `sec-detection`.
- Revisit when a new entry point, asset or trust boundary appears (new endpoint, new tool for an agent, new dependency with install scripts).

## Verify
- [ ] Every entry point listed maps to at least one boundary row.
- [ ] Each top-ranked threat has a mitigation and a test that fails without it.
- [ ] Residual risks are explicit, not silent omissions.
