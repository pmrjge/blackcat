#!/usr/bin/env bash
# make-seccomp.sh (user-run, needs network + jq): derive an optional tighter seccomp profile from Docker's default.
#   ./make-seccomp.sh [--unix-sockets-only]      -> $EQ_STATE_DIR/seccomp-eq.json ; use it with EQ_SECCOMP=<that file>
# Source: moby/profiles seccomp/default.json at the commit pinned in PINS (SECCOMP_COMMIT), sha256 checked (SECCOMP_SHA256).
# Removes from every allow rule: ptrace, process_vm_readv/writev (allowed UNCONDITIONALLY by the default profile on kernels
# >= 4.8, so they are the real gain), kcmp, pidfd_getfd, process_madvise, perf_event_open, bpf, userfaultfd, io_uring_*,
# keyctl family, name_to_handle_at/open_by_handle_at, kexec_*, module syscalls, mount/chroot/unshare/setns family, clock
# setters, reboot, swapon/off (most of those are already gated by capabilities that --cap-drop ALL removes).
# --unix-sockets-only: socket() only for AF_UNIX (the checks need no AF_INET/AF_NETLINK; --network none already leaves only lo).
# UNVERIFIED: that Lean, perl, bash, busybox and python run unchanged under it. Prove it: EQ_SECCOMP=... ./spike.sh && ./probe.sh,
# then reverify. The default profile stays the baseline; adopt this only if all three pass.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd -P)
# shellcheck disable=SC1091
. "$here/lib.sh"
UNIX=0
[ "${1:-}" = --unix-sockets-only ] && UNIX=1
eq_have jq || eq_die "jq is required"
eq_have curl || eq_die "curl is required"
commit=$(sed -n 's/^SECCOMP_COMMIT=//p' "$here/PINS" | head -n 1); want=$(sed -n 's/^SECCOMP_SHA256=//p' "$here/PINS" | head -n 1)
case "$commit$want" in *UNSET*|*TODO*|"") eq_die "SECCOMP_COMMIT/SECCOMP_SHA256 not pinned in PINS";; esac
tmp="$EQ_STATE_DIR/seccomp-default.json"
curl -fsSL --proto '=https' "https://raw.githubusercontent.com/moby/profiles/$commit/seccomp/default.json" -o "$tmp"
if eq_have shasum; then got=$(shasum -a 256 "$tmp" | cut -d' ' -f1); else got=$(sha256sum "$tmp" | cut -d' ' -f1); fi
[ "$got" = "$want" ] || eq_die "default.json sha256 $got != pinned $want (profile changed upstream? re-pin deliberately)"
jq --argjson unix "$UNIX" '
  def drop: ["ptrace","process_vm_readv","process_vm_writev","kcmp","pidfd_getfd","process_madvise","perf_event_open","bpf",
    "userfaultfd","io_uring_setup","io_uring_enter","io_uring_register","keyctl","add_key","request_key","name_to_handle_at",
    "open_by_handle_at","kexec_load","kexec_file_load","pivot_root","chroot","unshare","setns","mount","umount2","swapon","swapoff",
    "reboot","acct","settimeofday","clock_settime","clock_adjtime","adjtimex","init_module","finit_module","delete_module"];
  .syscalls |= (map(.names |= map(select(. as $n | (drop | index($n)) | not))) | map(select((.names | length) > 0)))
  | if $unix == 1 then
      .syscalls |= (map(select((.names | index("socket")) | not))
        + [{"names":["socket"],"action":"SCMP_ACT_ALLOW","args":[{"index":0,"value":1,"op":"SCMP_CMP_EQ"}]}])
    else . end' "$tmp" > "$EQ_STATE_DIR/seccomp-eq.json"
jq -e '.defaultAction and (.syscalls | length > 0)' "$EQ_STATE_DIR/seccomp-eq.json" >/dev/null
echo "wrote $EQ_STATE_DIR/seccomp-eq.json (rules: $(jq '.syscalls | length' "$tmp") -> $(jq '.syscalls | length' "$EQ_STATE_DIR/seccomp-eq.json"))"
echo "use:  EQ_SECCOMP=$EQ_STATE_DIR/seccomp-eq.json ./spike.sh && EQ_SECCOMP=$EQ_STATE_DIR/seccomp-eq.json ./probe.sh"
