---
name: fpga-hdl
description: Load for HDL and FPGA work — SystemVerilog/VHDL, Verilator, cocotb, formal checks, Yosys/nextpnr, timing closure, CDC, programming.
---
# FPGA and HDL

Safety gates: `embedded-firmware`. Programming a device is a hardware action: SRAM configuration is volatile (needs the user's go-ahead once per board); writing configuration flash, eFUSE/BBRAM keys or security bits is persistent and needs explicit consent per action — eFUSE keys are permanent.

## Versions
- Verilator 5.052 — Verified 2026-10-02 https://github.com/verilator/verilator (tags)
- Yosys 0.69, nextpnr 0.11.1 — Verified 2026-10-02 https://github.com/YosysHQ/yosys/releases/latest https://github.com/YosysHQ/nextpnr/releases/latest
- cocotb 2.1.0 (2.x removed deprecated 1.x APIs: read the migration guide before porting 1.x testbenches) — Verified 2026-10-02 https://github.com/cocotb/cocotb/releases/latest
- OSS CAD Suite ships nightly bundles (Yosys, nextpnr, Verilator, Icarus, GHDL, SymbiYosys, openFPGALoader) — Verified 2026-10-02 https://github.com/YosysHQ/oss-cad-suite-build/releases/latest
- Vendor tools (Vivado/Vitis, Quartus Prime, Radiant/Diamond, Gowin EDA) are large, licensed installs: ask before installing; versions are tied to device support — unverified here, check the vendor's release notes.

## Design rules
- Synchronous design: one clock edge per domain, no gated clocks (use clock enables), no combinational loops, no latches (`always_comb` must assign every output on every path; Yosys/Verilator warn).
- `always_ff` for flops with non-blocking `<=`; `always_comb` with blocking `=`; never mix in one block.
- Reset: pick synchronous or asynchronous-assert/synchronous-deassert per the vendor's guidance; reset only what needs it (control paths), not wide datapaths.
- **CDC**: single bits through 2-flop synchronizers; multi-bit values through async FIFOs (Gray-coded pointers) or handshakes; pulses through toggle synchronizers. Every crossing named and listed; constraints mark them (`set_max_delay -datapath_only` / `set_false_path` only on synchronizer inputs).
- Parameterize widths; `localparam` for derived constants; `$clog2` for address widths; explicit widths on literals (`8'd0`).
- Valid/ready handshakes (AXI-Stream style) between blocks; a transfer happens when both are high; `ready` may depend on `valid`, never the reverse.
- Inference over instantiation: write RAMs/DSPs in the vendor-recommended inference template so the design stays portable; check the synthesis report confirms BRAM/DSP mapping.

## Simulation and verification
- Verilator for speed (`verilator --binary --timing -Wall top.sv tb.sv`, or `--cc --exe` with a C++ harness; `--trace-fst` for waves); Icarus/`iverilog` or nvc/GHDL (VHDL) for event-driven 4-state checks.
- cocotb testbenches in Python (run with `uv run --with cocotb …` or a uv project): drive clocks with `Clock`, `await RisingEdge(dut.clk)`, scoreboards compared against a Python reference model; randomized stimulus with fixed seeds logged.
- Formal: SymbiYosys (`sby -f prop.sby`) with SVA `assert property` / `assume` / `cover` for handshake and FIFO invariants; bounded model check depth stated in the report.
- Lint every file: `verilator --lint-only -Wall`; zero warnings or each waived with a reason.
- Waveforms: GTKWave or Surfer on FST/VCD; attach the signal list to bug reports.

## Synthesis, place and route
- Open flow: `yosys -p 'synth_ice40 -top top -json top.json'` (or `synth_ecp5`, `synth_gowin`, `synth_xilinx`) then `nextpnr-ice40 --up5k --json top.json --pcf pins.pcf --asc top.asc` (`nextpnr-ecp5`, `nextpnr-himbaechel` for Gowin and others), `icepack`/`ecppack`.
- Constraints: every clock defined (frequency), I/O standards and pins in the constraint file, generated clocks from PLLs declared; unconstrained paths are bugs.
- Read `references/timing-closure.md` when a design fails timing or the timing report shows unconstrained paths.

## Programming
`openFPGALoader -b <board> top.bit` loads SRAM (volatile); `-f` writes flash (persistent) — both after the user's go-ahead, flash only with explicit consent. Vendor programmers likewise.

## Pitfalls
Simulation/synthesis mismatch from `initial` blocks or `x` propagation; blocking assignments in sequential logic; inferred latches; async reset glitches; missing CDC constraints hiding real violations; testbenches that never check outputs; trusting a passing sim of an unconstrained design.

## Verify
Lint clean · unit testbenches and a randomized cocotb run pass (seed logged) · formal properties prove or the bound is stated · synthesis report shows expected resources and no latches · timing met on all constrained clocks with zero unconstrained paths · hardware test only with consent.
