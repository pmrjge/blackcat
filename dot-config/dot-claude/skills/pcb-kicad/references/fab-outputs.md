# Fab and assembly outputs (KiCad)

Run from the project directory; outputs go to a versioned folder (`fab/v1.0/`), never overwriting a released set.

```bash
kicad-cli sch erc --exit-code-violations -o fab/erc.rpt board.kicad_sch
kicad-cli pcb drc --exit-code-violations --schematic-parity -o fab/drc.rpt board.kicad_pcb
kicad-cli pcb export gerbers -o fab/gerbers/ board.kicad_pcb       # layer set from the board's plot settings
kicad-cli pcb export drill --format excellon --excellon-separate-th -o fab/gerbers/ board.kicad_pcb
kicad-cli pcb export pos --format csv --units mm --side both -o fab/pos.csv board.kicad_pcb
kicad-cli sch export bom -o fab/bom.csv board.kicad_sch
kicad-cli sch export pdf -o fab/schematic.pdf board.kicad_sch
kicad-cli pcb export step -o fab/board.step board.kicad_pcb
```
Flags differ between majors: confirm each with `--help` on the installed version. Newer majors also export IPC-2581 and ODB++ (`kicad-cli pcb export ipc2581|odb`) — prefer them when the fab accepts them (one file carries stackup, netlist and drill data).

## Checklist per release
- Gerber set: all copper layers, mask, paste, silkscreen, edge cuts; drill files (plated and non-plated); a README with stackup, thickness, copper weight, finish (ENIG/HASL), mask color, impedance notes.
- Netlist (IPC-D-356) for the fab's electrical test.
- BOM columns: reference, quantity, value, footprint, MPN, manufacturer, DNP flag; alternates noted.
- Pick-and-place: rotation conventions differ between assemblers — check one rotated part (e.g. SOT-23, polarized cap) on the assembler's preview.
- Tag the commit and record the KiCad version used.
- Upload to the fab/assembler and ordering are the user's steps (or need their consent).
