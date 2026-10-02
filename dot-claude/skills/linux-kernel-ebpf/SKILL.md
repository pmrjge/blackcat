---
name: linux-kernel-ebpf
description: Use when tracing the Linux kernel or writing eBPF — bpftrace one-liners, bcc tools, libbpf CO-RE, perf and ftrace, probe overhead.
---
# Linux kernel tracing and eBPF

## Scope
Observing what the kernel and processes do on Linux (syscalls, scheduling, I/O, network, page faults) and writing small eBPF programs. User-space CPU profiling: `perf-profilers`. Hardening and detection rules built on this telemetry: `sec-hardening`, `sec-detection`. Not for macOS (no eBPF; use Instruments/DTrace-style tools there).

## Ground rules
- Tracing needs root or capabilities (`CAP_BPF`, `CAP_PERFMON`, `CAP_SYS_ADMIN` on older kernels); run on machines you own. Loading programs on a production host is the user's decision: state the probe, its overhead and its duration.
- Prefer static tracepoints over kprobes on internal functions (kprobes break across kernel versions); keep per-event work tiny and aggregate in maps instead of printing every event.
- Record the kernel version (`uname -r`) and whether BTF is available (`/sys/kernel/btf/vmlinux` exists) — CO-RE programs need it.

## Pick the tool
| Need | Tool |
|---|---|
| One-off question in one line | bpftrace (`bpftrace -l 'tracepoint:syscalls:*'` to list; `bpftrace -e '…'`) |
| Ready-made diagnostics | bcc tools (`execsnoop`, `opensnoop`, `biolatency`, `tcplife`, `runqlat`, `offcputime`; names on some distros end in `-bpfcc`) |
| A shipped program or agent | libbpf + CO-RE in C (skeletons via `bpftool gen skeleton`), or Rust (Aya) / Go (cilium/ebpf) loaders |
| Function-level kernel tracing without BPF | ftrace via `trace-cmd record -p function_graph` |
| Counters, sampling, scheduler analysis | `perf stat`, `perf record -a -g`, `perf sched`, `perf trace` |
| Inspect loaded programs and maps | `bpftool prog`, `bpftool map` |

## Examples (bpftrace)
```sh
# syscalls by process, 10 s
bpftrace -e 'tracepoint:raw_syscalls:sys_enter { @[comm] = count(); } interval:s:10 { exit(); }'
# read() latency histogram for one PID
bpftrace -e 'tracepoint:syscalls:sys_enter_read /pid == 1234/ { @t[tid] = nsecs; }
             tracepoint:syscalls:sys_exit_read /@t[tid]/ { @us = hist((nsecs - @t[tid]) / 1000); delete(@t[tid]); }'
```

## Method
1. Start from the symptom and the USE method (utilization, saturation, errors) per resource: CPU run queue, disk, network, memory.
2. Use existing bcc/bpftrace tools before writing new probes.
3. Measure overhead: compare the workload's throughput with and without the probe.
4. Save raw outputs with the command lines; summarize as histograms or top-N tables.

## Verify
- [ ] Kernel version, BTF availability and tool versions recorded.
- [ ] Each probe's overhead measured or bounded; probes detached afterwards (`bpftool prog` shows none left).
- [ ] Conclusions backed by a histogram or count, not a single event.

## Sources
- Verified 2026-10-02 https://api.github.com/repos/bpftrace/bpftrace/releases/latest — bpftrace 0.27.0 (2026-09-10); https://api.github.com/repos/libbpf/libbpf/releases/latest — libbpf 1.7.0.
- Unverified as of 2026-10-02: tool names and flags above (bcc naming per distro, `bpftool gen skeleton`, trace-cmd options, capability names) — check the installed versions' `--help`/man pages.
