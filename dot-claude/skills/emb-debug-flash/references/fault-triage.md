# Fault triage (Cortex-M first; RISC-V and Xtensa notes at the end)

## HardFault / UsageFault / BusFault / MemManage
1. Halt in the handler; read the stacked frame (R0–R3, R12, LR, PC, xPSR) from MSP or PSP — bit 2 of EXC_RETURN (LR in the handler) says which.
2. Read CFSR (0xE000ED28), HFSR (0xE000ED2C), MMFAR (0xE000ED34), BFAR (0xE000ED38). In GDB: `x/wx 0xE000ED28`.
3. Decode:
   - IACCVIOL / INVSTATE → jump to a bad address or Thumb bit clear (function pointer corruption, vtable).
   - PRECISERR + BFARVALID → load/store to BFAR (bad pointer, unclocked peripheral). IMPRECISERR → buffered write; set DISDEFWBUF in ACTLR temporarily to make it precise.
   - UNALIGNED (M0/M0+ always fault; M3+ when UNALIGN_TRP) · DIVBYZERO (if DIV_0_TRP) · UNDEFINSTR (wrong core flags, corrupted code) · NOCP (FPU used while disabled — enable CP10/CP11 in SCB->CPACR before any float code).
   - STKERR / MSTKERR → stack overflow while stacking the exception.
4. `addr2line -e fw.elf <PC>` or `info symbol` in GDB; probe-rs prints a backtrace with defmt/panic-probe.

## Unexpected resets
Read the reset-cause register first (RCC_CSR on STM32, RESETREAS on nRF, `esp_reset_reason()`): watchdog, brown-out, software, pin, lockup. Lockup = fault inside a fault handler (often stack overflow).

## Hangs
Halt and backtrace; check whether in WFI (expected idle), spinning on a peripheral flag (clock not enabled, wrong IRQ binding), or deadlocked (RTOS task states: Zephyr thread analyzer, FreeRTOS `vTaskList`).

## Probe cannot connect
Firmware disables SWD pins or enters deep sleep → `--connect-under-reset` / hold NRST. Read-out protection or APPROTECT → recovery mass-erases the chip (consent gate). Wrong voltage, missing ground, SWD clock too high (drop to 1 MHz), wrong chip variant string.

## RISC-V and Xtensa
- RISC-V: `mcause`, `mepc`, `mtval` CSRs give cause, PC and faulting address.
- ESP32 (Xtensa/RISC-V): the panic handler prints `EXCCAUSE`/`MEPC` and a backtrace; decode with `idf.py monitor` (it runs addr2line on the ELF) or `xtensa-esp32-elf-addr2line`.
