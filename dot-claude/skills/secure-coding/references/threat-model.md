# Threat model: writing it down
Read from `secure-coding` (the five steps are in its SKILL.md).

- One page: a data-flow sketch (Mermaid or ASCII; `diagrams-as-code`), a table `| boundary | threat (STRIDE) | asset | mitigation | test |`, and the residual risks you accept with a reason.
- Each mitigation names where it lives (file, config, hook) so a reviewer can check it; each top abuse case names the test that proves the mitigation (`test_<abuse>_rejected`).
- Route each mitigation to its module: sinks → `sec-web-vulns`, identity → `sec-authn-authz`, secrets → `sec-secrets`, dependencies → `sec-supply-chain`, LLM paths → `sec-llm-apps`, ports, sockets and runtime limits → `sec-hardening`, logging and alerting → `sec-detection`.
- Revisit when a new entry point, asset or trust boundary appears (new endpoint, new tool for an agent, new dependency with install scripts).

## Verify
- [ ] Every entry point listed maps to at least one boundary row.
- [ ] Each top-ranked threat has a mitigation and a test that fails without it.
- [ ] Residual risks are explicit, not silent omissions.
