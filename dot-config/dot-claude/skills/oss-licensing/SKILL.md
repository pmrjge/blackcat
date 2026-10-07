---
name: oss-licensing
description: Use to choose, apply or audit open-source licences — compatibility, SPDX, REUSE, notices.
---
# Open-source licensing (engineering practice, not legal advice)

## Scope
Choosing a licence for a project, applying it correctly, and checking that dependencies' licences fit how the software is distributed. Dependency security: `sec-supply-chain`. Legal questions with money or liability at stake go to a lawyer: say so and stop at the facts.

## Licence families (what triggers obligations)
| Family | Examples (SPDX ids) | Main obligations when you distribute |
|---|---|---|
| Permissive | `MIT`, `BSD-2-Clause`, `BSD-3-Clause`, `ISC`, `Apache-2.0` | keep copyright and licence text; Apache-2.0 also: state changes, keep `NOTICE`, explicit patent grant |
| Weak copyleft | `MPL-2.0` (file-level), `LGPL-2.1-or-later`, `LGPL-3.0-or-later`, `EPL-2.0` | modified files/library source under the same licence; allow relinking/replacing the library (LGPL) |
| Strong copyleft | `GPL-2.0-only`, `GPL-3.0-or-later` | the combined work distributed under the GPL with source |
| Network copyleft | `AGPL-3.0-or-later` | source must be offered to users interacting over a network, too |
| Source-available (not OSI open source) | `BUSL-1.1`, `SSPL-1.0`, Elastic License 2.0, RSALv2 | usage restrictions (competing services, production use) — read the specific terms |

- "Distribution" is the usual trigger (shipping binaries, containers, apps, firmware); internal use and SaaS without distribution don't trigger GPL obligations, but do trigger AGPL's network clause.
- Compatibility: GPL-2.0-only is incompatible with Apache-2.0; GPL-3.0 accepts Apache-2.0; permissive code can go into copyleft projects, not the reverse.

## Applying a licence to your project
- Pick deliberately: MIT or Apache-2.0 for maximum reuse (Apache-2.0 when patents matter); MPL-2.0 for file-level copyleft; GPL/AGPL when derivatives must stay open.
- `LICENSE` file with the full text; SPDX headers in source files (`SPDX-License-Identifier: Apache-2.0` plus a copyright line); the REUSE convention (`LICENSES/` directory, `REUSE.toml` or headers) and `reuse lint` to check.
- Contributions: a DCO (`Signed-off-by`) or a CLA, decided before outside contributions arrive.
- Package metadata: `license = "Apache-2.0"` (SPDX expression) in pyproject/Cargo/package.json.

## Auditing dependencies
- Inventory licences from the lockfile: `cargo deny check licenses` (allowlist in `deny.toml`), Python `pip-licenses` (or the SBOM), npm `license-checker`-style tools, or an SBOM (CycloneDX/SPDX) scanned by a licence tool. Tool names other than `cargo deny` and REUSE: unverified as of 2026-10-02.
- Keep an allowlist policy (e.g. permissive + MPL for distributed binaries; flag LGPL for static linking, GPL/AGPL and source-available for review).
- Third-party notices: generate the attribution file for distributed artefacts (binaries, containers, apps) from the inventory.
- Unknown or missing licence = no permission to use: ask upstream or replace.
- Vendored or copied code (snippets, generated code from models) needs its origin and licence recorded.

## Verify
- [ ] `LICENSE` present; SPDX headers or REUSE metadata; `reuse lint` clean.
- [ ] Dependency licence inventory produced from the lockfile; every non-allowlisted licence reviewed with a decision.
- [ ] Notices file shipped with each distributed artefact.

## Sources
- Verified 2026-10-02 https://pypi.org/pypi/reuse/json — REUSE tool 6.2.0; https://github.com/spdx/license-list-data/releases/latest — SPDX License List 3.29.0.
- Unverified as of 2026-10-02: licence-compatibility statements and tool names other than those above (general knowledge; check the FSF/OSI compatibility notes and each tool's docs).
