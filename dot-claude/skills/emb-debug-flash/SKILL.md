---
name: emb-debug-flash
description: Use before flashing or debugging a board — probe-rs, OpenOCD, GDB, RTT, QEMU/Renode, faults.
---
# Flashing, probes, simulation and debugging

Safety gates: `embedded-firmware` (flash, erase, option bytes, eFuse/OTP and lock bits need the user's consent; simulate first).

## Versions
- probe-rs 0.32.0 — Verified 2026-10-02 https://github.com/probe-rs/probe-rs/releases/latest
- OpenOCD 0.12.0 is the latest tagged release; distro and vendor builds (ST, Espressif, Raspberry Pi forks) are often newer git snapshots — Verified 2026-10-02 https://github.com/openocd-org/openocd/releases/latest
- Renode 1.17.0 — Verified 2026-10-02 https://github.com/renode/renode/releases/latest
- QEMU 11.1.2 — Verified 2026-10-02 https://gitlab.com/qemu-project/qemu (tags)

## Order of work
1. Host tests → 2. QEMU or Renode → 3. hardware read-only (`probe-rs info`, `list`, attach, read memory) → 4. flash, only after the user confirmed the board, the image and the address range.
- Read-only probe actions (list probes, read chip ID, attach, `reset` without erase, read memory, RTT attach) are fine once the user has said the board is connected.
- Write actions (download, `erase`, `--chip-erase`, option bytes, `unlock`, `mass_erase`, eFuse/OTP, lock bits) are consent gates: show the exact command, chip, image hash and region first.

## Simulation
- Renode: `renode --console -e 'include @scripts/single-node/<board>.resc; start'`; Robot Framework tests (`renode-test test.robot`) assert UART output and peripheral state in CI. Model coverage varies per peripheral — check the platform's `.repl` before trusting a result.
- QEMU: `qemu-system-arm -M mps2-an385 -nographic -semihosting -kernel fw.elf` (or the board the SDK targets); `-s -S` then `gdb` / `arm-none-eabi-gdb -ex 'target remote :1234'` to debug.
- Zephyr: `west build -t run` on QEMU boards; ESP-IDF: `idf.py qemu`; Rust: a QEMU runner in `.cargo/config.toml`.

## probe-rs (Rust and C ELF files alike)
- `probe-rs list`, `probe-rs info --chip <CHIP>` (read-only); `probe-rs run --chip <CHIP> fw.elf` flashes, resets and streams RTT/defmt (consent gate); `probe-rs attach` streams RTT without flashing; `probe-rs gdb` serves GDB; `--connect-under-reset` recovers chips whose firmware disables SWD pins or sleeps.
- `cargo embed` / `Embed.toml` for per-project profiles; the VS Code probe-rs debugger uses the DAP server.

## OpenOCD + GDB
- `openocd -f interface/<probe>.cfg -f target/<chip>.cfg` then `gdb fw.elf -ex 'target extended-remote :3333' -ex 'monitor reset halt'`; `load` writes flash (consent gate).
- Keep scripted sessions in `.gdbinit`-style files in the repo; never commit `monitor flash erase_*` or protection commands into automatic scripts.

## Logging and tracing
RTT (fast, needs a probe) · SWO/ITM (needs the trace pin and correct clock) · UART (works without a probe) · semihosting (very slow, halts without a debugger: dev builds only) · GPIO toggles on a logic analyzer for timing.

## Fault triage
Read `references/fault-triage.md` when the target hard-faults, resets unexpectedly, hangs or the probe cannot connect.

## Pitfalls
Flashing the wrong ELF (check the build ID/hash); release image without symbols; RDP/APPROTECT enabled by vendor defaults (nRF52 APPROTECT, STM32 RDP) locking you out — unlocking mass-erases, which is a consent gate; SWD pins remapped by firmware; low-power modes dropping the debug connection; probe firmware too old for the chip.

## Verify
Image hash printed before flashing · simulator run green first · after flashing, read back or verify (`probe-rs` verifies by default; OpenOCD `verify_image`) · expected log lines over RTT/UART · reset cause register read after the first boot.
