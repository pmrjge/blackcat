---
name: emb-rust
description: Load for no_std Rust firmware — embassy, RTIC, esp-hal, embedded-hal drivers, defmt logging, memory.x, panic handlers, host tests.
---
# Embedded Rust

Safety gates and baseline rules: `embedded-firmware`. General Rust: `rust-engineering`.

## Versions
- embassy-executor 0.10.0, embassy-stm32 0.6.0 — Verified 2026-10-02 https://crates.io/crates/embassy-executor
- esp-hal 1.2.2 (stable 1.x API) — Verified 2026-10-02 https://crates.io/crates/esp-hal
- defmt 1.1.1, rtic 2.3.1 — Verified 2026-10-02 https://crates.io/crates/defmt https://crates.io/crates/rtic
- probe-rs 0.32.0 — Verified 2026-10-02 https://github.com/probe-rs/probe-rs/releases/latest
- Embassy HAL crates move fast and break between minors: pin exact versions from the same embassy git revision or release set, and read the crate's CHANGELOG before upgrading.

## Choosing a framework
| need | pick |
|---|---|
| async tasks, many I/O waits, network stacks (embassy-net, smoltcp) | embassy |
| hard real-time priorities, preemptive tasks with static analysis of shared resources | RTIC 2 |
| Espressif chips | esp-hal with its embassy integration; Wi-Fi/BLE through the esp-rs radio crate (its name changed across releases — check the esp-hal book) |
| simple superloop, tiny parts | cortex-m-rt + PAC/HAL, no executor |

## Project skeleton
- `.cargo/config.toml`: `[build] target = "thumbv7em-none-eabihf"` (or the chip's target), `[target.<triple>] runner = "probe-rs run --chip <CHIP>"`, `rustflags = ["-C", "link-arg=-Tlink.x", "-C", "link-arg=-Tdefmt.x"]` when using defmt.
- `memory.x` with FLASH/RAM origins and lengths from the reference manual; bootloader offsets subtract from FLASH.
- `rust-toolchain.toml` pins the channel and lists the targets (`rustup target add`).
- Profiles: `[profile.release] debug = 2, lto = "fat", codegen-units = 1, opt-level = "s"` (or `"z"`); keep `debug` on — it costs no flash and the probe needs it.

## Rules
- `#![no_std]`, `#![no_main]`; exactly one panic handler (`panic-probe` with defmt in dev, a reset/log handler in production).
- Peripherals are singletons: take them once (`embassy_stm32::init`, `Peripherals::take()`), move ownership into the task or driver that uses them.
- Drivers are generic over `embedded-hal` 1.0 / `embedded-hal-async` traits so they test on the host with `embedded-hal-mock`.
- Shared state: `embassy_sync` channels/signals/mutexes or `critical_section::Mutex<RefCell<_>>`; no `static mut` (edition 2024 denies references to it by default).
- Allocation only with an explicit allocator (`embedded-alloc`) and a reason; prefer `heapless` collections.
- Tasks never block the executor: no busy loops without `.await`; use `Timer::after` and interrupt-driven peripherals.
- Interrupt priorities set explicitly; embassy interrupt executors for real-time work on top of the thread executor.
- `unsafe` for MMIO, linker symbols, DMA buffers only, each with a `// SAFETY:` comment; DMA buffers live in RAM regions the DMA can reach (check the memory map: some CCM/DTCM regions are not DMA-accessible).
- Logging: defmt (`defmt::info!`) over RTT; strings stay on the host, so it is cheap. Not in hot ISRs.

## Host testing
- Split pure logic into a `no_std` library crate with `#[cfg(test)]` tests that run on the host (`cargo test -p logic --target <host triple>`).
- On-target tests: `defmt-test` or `embedded-test` with probe-rs as runner.
- Simulation: QEMU `lm3s6965evb`/`mps2-an385` machines for Cortex-M logic; Renode for full boards (`emb-debug-flash`).

## Pitfalls
Wrong target triple (FPU `eabihf` vs `eabi`); `memory.x` mismatch with the chip variant; missing `#[interrupt]` binding (`bind_interrupts!`) so the future never wakes; mixing embassy crates from different releases; release builds without debug info; stack overflow into `.bss` (use `flip-link`).

## Verify
`cargo build --release` for the target · `cargo size --release -- -A` within budget · host tests pass · `cargo clippy --target <triple> -- -D warnings` · runs under QEMU/Renode or (with consent) `probe-rs run` with expected defmt output.
