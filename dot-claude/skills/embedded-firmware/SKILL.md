---
name: embedded-firmware
description: Use for firmware and hardware-near work — MCUs, RTOS, drivers, flashing safety, FPGA, PCB.
---
# Embedded firmware (hub)

## Scope
MCU firmware in C or Rust, RTOS apps, peripheral drivers, bootloaders, probes and flashing, FPGA/HDL, KiCad boards. Load the module for the part you are about to do; general Rust in `rust-engineering`, C/C++ in `cpp-engineering`, builds in `cmake-ninja-builds`, robots in `robotics-engineering`.

## Modules
| module | load when |
|---|---|
| `emb-rust` | no_std Rust, embassy, RTIC, esp-hal, defmt, HAL crates, memory.x |
| `emb-c-rtos` | C firmware, Zephyr, FreeRTOS, ESP-IDF, vendor SDKs, ISRs, linker scripts |
| `emb-debug-flash` | probes (probe-rs, OpenOCD, J-Link), flashing, RTT/SWO, GDB, QEMU/Renode simulation, fault triage |
| `fpga-hdl` | Verilog/SystemVerilog/VHDL/Amaranth, Verilator, cocotb, Yosys/nextpnr, timing |
| `pcb-kicad` | schematics, layout, DRC/ERC, kicad-cli, BOM and fab outputs |

## Safety gates (hardware is not undoable)
- **Simulate first.** Unit-test logic on the host, then run in QEMU or Renode (or an HDL simulator) before any target. Real hardware comes last, and only when the user has a board connected and said to use it.
- **Ask before** flashing, mass-erasing, changing option bytes or read-out protection, writing eFuses/OTP, burning secure-boot or flash-encryption keys, or setting debug-lock bits. eFuse/OTP and RDP level 2 are permanent: state the exact command, the bits and the consequence, and stop for the user's consent.
- Never power a board through two sources at once; check the probe's target-voltage sense and the board's I/O voltage before connecting.
- Keep a known-good image and the recovery path (ROM bootloader, DFU, `--connect-under-reset`) written down before changing the boot chain.
- Secrets (signing keys, Wi-Fi credentials, cloud certs) never go in the repo or the image source; provision them at flash time from the user's store.

## Baseline engineering rules
- Pin the toolchain: `rust-toolchain.toml`, Zephyr `west.yml` manifest revision, ESP-IDF version, vendor SDK tag; record them in the README.
- Memory is a budget: report flash and RAM use per build (`size`, `cargo size`, `west build -t rom_report/ram_report`, `idf.py size`) and stack high-water marks.
- Interrupt context does the minimum: set a flag, push to a queue, signal a task. No blocking, allocation or logging that can block in ISRs.
- Shared state between ISR and thread: critical sections or atomics, `volatile` only for MMIO; document every priority and who owns each peripheral.
- Timing claims come from measurement (logic analyzer, GPIO toggles, DWT cycle counter), not from reading code.
- Datasheet and reference-manual section numbers go in comments next to register-level code; errata sheets are read before blaming the code.
- Watchdog on in production builds; brown-out detection configured; fault handlers log the fault registers and reset into a safe state.

## Verify (any embedded change)
Host tests pass · builds for the target with no new warnings · size report within budget · runs in the simulator (or HIL with the user's consent) · on hardware, the observable behavior (UART/RTT log, scope trace) matches the spec · versions reported.
