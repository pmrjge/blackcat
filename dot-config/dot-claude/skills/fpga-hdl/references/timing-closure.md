# Timing closure

## Read the report first
- Worst negative slack (WNS), total negative slack (TNS), failing endpoints count, per clock. nextpnr prints `Max frequency for clock` per domain; Vivado `report_timing_summary`; Quartus TimeQuest.
- Unconstrained paths and clocks first: they are missing constraints, not passing paths.
- Identify the critical path: source flop, logic levels, routing vs logic delay share. Routing > 60 % → placement/congestion; many logic levels → restructure.

## Fixes, cheapest first
1. Correct constraints: real clock frequency, multicycle paths only where the design guarantees them (with the enable logic to back it), false paths only on CDC synchronizer inputs.
2. Pipeline: add register stages on long arithmetic and wide muxes; retime with the tool (`-retime`, Vivado `phys_opt_design -retime`) when available.
3. Reduce logic depth: one-hot FSMs, precomputed comparisons, carry-chain friendly adders, DSP blocks with their internal pipeline registers enabled (MREG/PREG).
4. Fan-out: duplicate high fan-out registers (enables, resets); avoid resetting wide datapaths.
5. Placement: floorplan (pblocks/regions) for tightly coupled blocks; seed sweeps (`nextpnr --seed`, Vivado strategies) only after structural fixes, and report the seed.
6. Slow down: a clock-enable at a lower rate or a second clock domain (adds CDC work).

## Clock domain crossings
Run the vendor's CDC report (Vivado `report_cdc`) or review every crossing manually against the list kept in the design; a crossing without a synchronizer is a bug even when timing passes.

## Hold violations
Usually clock skew between domains or I/O; fix with proper clock buffers and I/O constraints (input/output delay), not by adding delay logic by hand.
