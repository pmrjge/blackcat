---
name: pcb-kicad
description: Load before PCB work in KiCad — schematics, ERC/DRC, layout rules, kicad-cli, BOM and fab files.
---
# PCB design with KiCad

Ordering boards or parts spends money and uploading design files to a fab or assembler shares them: both need the user's consent. Generating files locally is fine.

## Versions
- KiCad 10.0.6 is the current stable tag (10.99 = development) — Verified 2026-10-02 https://gitlab.com/kicad/code/kicad (tags)
- File formats move forward only: a project saved in a newer major does not open in an older one. Ask which major the user's team uses before saving; `kicad-cli version` reports the installed one.

## Workflow
1. Requirements: power budget, rails and currents, interfaces, connectors, mechanical outline and mounting holes, layer count, target fab and its capabilities (min trace/space, drill, via types, impedance control).
2. Schematic: hierarchical sheets per function; every symbol with a footprint, value, MPN and datasheet field; power flags on driven nets; no-connect flags on unused pins.
3. ERC clean (`kicad-cli sch erc --exit-code-violations`), each waived item with a reason.
4. Board setup: stackup and net classes from the fab's capabilities (trace width per current with IPC-2152, clearance per voltage with IPC-2221), design rules imported from the fab's KiCad template when it has one.
5. Placement before routing: connectors and mechanical first, then decoupling at the pins, then critical analog/RF/high-speed blocks; keep a solid reference plane under every high-speed signal.
6. Routing: impedance-controlled pairs with the fab's calculated widths, length matching where the interface requires it, no stubs, return-path vias next to layer changes.
7. DRC clean (`kicad-cli pcb drc --exit-code-violations --schematic-parity`), parity with the schematic included.
8. Outputs: read `references/fab-outputs.md` when producing Gerbers, drill, BOM, pick-and-place or a release set.

## Layout rules that catch most failures
- Decoupling: one small cap per power pin, as close as possible, via straight to the plane; bulk cap per rail.
- Switching regulators: follow the datasheet layout exactly (hot loop minimal, feedback trace away from the switch node).
- Crystals: short traces, ground guard, no signals underneath.
- Thermal: copper pours and via arrays under exposed pads; check the regulator's dissipation.
- Connectors and test points for every rail, SWD/JTAG, UART and boot pins; mark pin 1 and polarity on silkscreen.
- Mounting holes and keep-outs from the mechanical drawing (STEP export to check in MCAD).

## Libraries
Prefer KiCad's official libraries; project-local libraries for custom parts (`sym-lib-table`/`fp-lib-table` in the project), each footprint checked against the datasheet land pattern and the 3D model aligned. Never point a project at a library path outside the repo.

## Automation
`kicad-cli` (exports, ERC/DRC, renders) and the KiCad Python API / IPC API for scripted edits; KiBot for CI pipelines that produce the full output set. Check `kicad-cli <sch|pcb> --help` for the installed version's subcommands.

## Pitfalls
Footprint pin numbering not matching the symbol (SOT-23 variants, diodes); mirrored connectors on the bottom side; missing solder-mask expansion or paste reduction on large pads; thermal reliefs on high-current nets; silkscreen over pads; unconnected copper islands; via-in-pad without the fab's filling option.

## Verify
ERC and DRC exit 0 (or every waiver reasoned) · schematic parity · 3D view and STEP checked against the enclosure · Gerbers re-opened in the Gerber viewer · BOM MPNs available (stock checked by the user or with consent to query distributors) · fab capabilities met.
