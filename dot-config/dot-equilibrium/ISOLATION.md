# Isolation of model-run code in the equilibrium harness: sandbox-exec vs Docker vs Apple Virtualization backends

Date 2026-10-04. Read-only assessment (nothing installed, pulled or started). Everything not marked "verified" is
unverified. Supersedes the Docker-only draft name (ISOLATION_DOCKER.md).

## 0. Verdict

- Docker is feasible and clearly stronger than `sandbox-exec` (separate kernel, deny-by-default visibility, fresh
  container per run). It costs a second Lean environment (Linux arm64) and ~2-3 days; `sandbox-exec` costs ~1 day and
  reuses the macOS toolchain bit-for-bit but is deprecated, in-kernel, and needs a brittle read allow-list.
- Apple `container` is the architecturally nicest (VM per container) but pre-1.0, not installed, and its documented
  `run` flags lack `--network none`, `--security-opt`, `--pids-limit` (verified against the command reference).
  Not a first choice today; re-check in a few months.
- Linux VM via Lima/Tart: same Linux-Lean problem as Docker, plus harder network-off and fresh-state; no gain over Docker.
- macOS guest (Tart): only option that reuses the host toolchain and oleans unchanged, but 2 concurrent macOS VMs max,
  ~25 GB base image, boot time added to every ~25 s check. Fallback only if Linux Lean fails the ref re-verification.
- Recommended: one `isolate()` backend interface in the harness; implement `docker` first (CP/CR checks, PF checks,
  oracle runs, mediator `verify()`), keep `none`/`sandbox-exec` as a fallback; pick ONE backend and freeze it
  (image digest + backend in flags.json/CONFIG.txt) before the run so every arm sees identical conditions.

## 1. This machine (checked)

- macOS 27.0.1 (Darwin 27.0.0), arm64 (Apple M-series, T6031 kernel). Disk: 6.9 TiB free. Free RAM: `vm_stat` shows
  29.1M free 16 KiB pages = ~477 GB free; total RAM not readable (`sysctl hw.memsize` blocked by the agent sandbox).
- Docker: `~/.docker/bin/docker` CLI 29.8.1 and `/Applications/Docker.app` 4.93.0 (Docker Desktop) installed.
  Daemon state UNKNOWN: this agent's sandbox denies the socket (`permission denied ... ~/.docker/run/docker.sock`; the
  `default` context points at `/var/run/docker.sock`, which does not exist; context `desktop-linux` exists) and also
  `~/.docker/config.json`. The user must run `docker info` (and `docker context use desktop-linux` if needed) in their
  own terminal. The harness must therefore be started from a normal terminal, not from inside an agent sandbox.
- Not installed (`command -v` empty): podman, colima, orb, container (Apple), tart, limactl, vfkit, utm. Homebrew exists.
- Lean artefacts on the host (verified): `$HOME/lean/stack_mathlib` (Lean 4.34.1, Mathlib v4.34.1 rev d13f23b7),
  `.lake` 7.6 GB, of which `.olean` 8930 files = 1.92 GB, `.ilean` 0.29 GB, `.c/.o/.a/.dylib` 0.49 GB, the rest build
  traces/IR; toolchain `~/.elan/toolchains/leanprover--lean4---v4.34.1` 2.7 GB, Mach-O arm64 (useless in Linux).

## 2. Threat being closed

Code runs from: PF `check_lean.sh` and `oracle.py` (answer's `#eval`/`run_cmd`/`initialize`/macros run at compile time),
CP/CR public checks (model-edited Python under `uv run ... unittest`), CP/CR/ES oracles, mediator `verify()` for
allow-listed argv. Today: no OS sandbox, network open, caller's privileges (README open items). Required properties:
no network, no read of `$HOME`/secrets/`items/*/oracle`/grading keys/other arms, write only to the fresh check copy
and a private tmp, bounded CPU/memory/pids/time, no state surviving to the next run.
Out of scope here: the member `claude -p` sessions (section 9).

## 3. Docker (Docker Desktop, or Colima/OrbStack)

Isolation. Containers on macOS run inside one Linux VM (Docker Desktop VM on Virtualization.framework), so the boundary
to the host is the hypervisor plus the virtiofs share, not seatbelt. Only bind-mounted paths exist in the container;
no home, no oracle dirs, no keychain. Flags (standard Docker, not re-verified here):
`docker run --rm --name eq-<uuid> --label eq-harness=1 --network none --read-only --cap-drop ALL
--security-opt no-new-privileges --user 10001:10001 --pids-limit 512 --memory 6g --memory-swap 6g --cpus 2 --init
--tmpfs /tmp:rw,size=2g -v <check_copy>:/work:rw -v <pristine_fixture>:/fixture:ro -w /work <image@sha256:...> <argv>`.
Never mount `docker.sock` (root-equivalent on the VM, and it can mount any host path Docker Desktop shares).
Weaknesses: all containers share one VM kernel (a kernel escape reaches the VM and its shares, still not macOS);
Docker Desktop file sharing exposes `/Users` to the VM, so only bind what you list; no seccomp tuning needed (default
profile). Network off is exact (`--network none`: loopback only).

Lean 4.34.1 + Mathlib in Linux arm64 (the hard part).
- Host toolchain and macOS binaries are unusable. Need Lean 4.34.1 Linux aarch64 (release tarball from the leanprover/lean4
  GitHub release; pin by sha256) or `elan` in the build stage.
- Mathlib: (a) `lake exe cache get` at image build (network at build time only; size of the download unverified, the
  built oleans on the host are 1.9 GB, ~2-3 GB with the dependencies' sources/ilean), or (b) SPIKE FIRST: mount the HOST
  `.lake` read-only into the Linux container. `.olean` files should be OS-independent for the same architecture and Lean
  commit (Mathlib's cache is distributed per toolchain, not per OS) but that is UNVERIFIED; Mathlib has no
  `precompileModules` dylibs to worry about (the 0.49 GB of `.o/.a/.dylib` is not needed to import). If (b) works, no
  Mathlib rebuild and the oleans are bit-identical to the ones the 218/218 reference proofs were verified against.
- Bake into the image (ext4 inside the VM) rather than bind-mount if possible: Lean mmaps ~2 GB of oleans per import;
  virtiofs bind mounts are slower for many small/mmap reads (UNVERIFIED magnitude; measure). Image ~5-6 GB
  (toolchain 2.7 + oleans 1.9 + sources), built once, tagged and pinned by digest.
- Do the reference proofs still verify? Kernel checking is deterministic; `maxHeartbeats` are allocation counts, not
  wall time, so verdicts should match across OSes, but the harness's own wall-clock limits (check 600 s, Lean 300 s each)
  depend on speed. Re-verification is required anyway: `gen_pf.py finalcheck` over 218 refs (should score 1) and 218
  wrong answers (score 0) inside the container, compared to `oracle/build/final_check.tsv`. 218 x ~25 s = ~90 min
  serial, ~15-20 min at 6 concurrent. `pool.sha256` covers fixtures, not oleans: record the image digest and the
  olean-tree hash in CONFIG.txt as the new provenance.
- Per-check startup: container start ~1 s (typical, UNVERIFIED here) vs ~25 s per check (+4 %). First check after VM
  boot is cold (page cache); warm afterwards. Docker Desktop VM memory/CPU must be set explicitly (default unknown).

CP/CR/ES: python image with uv (pinned base digest, `uv` copied from a pinned image, `UV_CACHE_DIR` on a tmpfs or a
read-only prewarmed cache; the unittest argv uses `uv run --no-project`, so no network is needed if no dependencies;
CP/CR oracles declare `dependencies = []`). Trivial. ES oracle/lookups are read-only and need no container.

Harness cost (eq_harness.py: `run_bounded` l.1417, `run_check` l.1791, `run_oracle` l.2547, `check_copy`, `private_tmp`):
- One `isolate(argv, rw_dir, ro_dirs, limits) -> argv` function; `run_bounded` unchanged except the timeout path:
  `os.killpg` kills only the `docker run` client, NOT the container. Add `--name`, and on timeout run
  `docker kill <name>`; `--rm` removes it; sweep `docker ps -aq --filter label=eq-harness` at harness start and at exit
  (orphans after a harness crash/SIGKILL). `--init` reaps zombies in the container; `--stop-timeout 1`.
- Output tail: the `docker run` client pipes stdout/stderr unchanged; the 64 KiB tail logic keeps working.
- `private_tmp` 0700 dirs become `--tmpfs /tmp` (no host tmp leak, no cleanup needed).
- Ownership: Docker Desktop virtiofs presents host files to the container with its own uid mapping; a non-root
  container uid reading a 0700 host copy or writing into it may fail (UNVERIFIED; test). Options: make the fresh copy
  0777 for the run (it is deleted afterwards), or set `--user $(id -u):$(id -g)` (host uid 501 inside is fine with
  cap-drop ALL). Test with a hostile answer file that tries to write outside `/work`.
- `check_lean.sh` uses `perl` alarms, `mktemp`, `lake env`: present in a Debian/Ubuntu image; `LEAN_PATH` from
  `lake env` works inside the image, so the script needs only `EQ_LEAN_PROJECT` pointed at the in-image project.
- Mediator `verify()` re-runs CP/CR argv (60 s) in a fresh fixture copy: each becomes one `docker run`, +~1 s each; the
  10 min `fact_budget_s` includes container start.
- Determinism: same image digest, same `--cpus/--memory` for every arm, same backend for public check AND oracle (an
  answer that passes the public check in one environment and fails the oracle in another would contaminate scores).
  Concurrency changes wall-clock only (contention): keep concurrent checks <= cores of the Docker VM.

Risks / licensing. Image supply chain: build locally from a Dockerfile in the repo, `FROM <base>@sha256:`, tarball
sha256 checked, no `:latest`; `docker scout`/trivy optional. Docker Desktop licence: free for personal use / small
business per Docker's terms (employee and revenue thresholds from memory, UNVERIFIED; pricing page fetched did not state
them; check the Subscription Service Agreement). Colima (MIT, Lima-based VM, `docker` CLI only) or OrbStack avoid the
question; Docker Desktop is already installed here.

## 4. Apple `container` (apple/container, Swift, Apache-2.0)

Verified from github.com/apple/container README and docs/command-reference.md (fetched 2026-10-04):
- Requires Apple silicon and macOS 26 ("do not support older versions"); host is macOS 27.0.1, newer than the
  supported release: UNVERIFIED that it works. Not installed. Under active development; compatibility not guaranteed
  across versions (release 0.3.0 mentioned; latest release not checked).
- Each container runs as a lightweight VM on Virtualization.framework (hypervisor boundary per container, stronger
  than Docker's shared VM). OCI images; builds via a builder. `container system start` must run first (starts
  `container-apiserver` and launchd helpers): a user-terminal step; from inside the agent sandbox, almost certainly
  blocked (XPC/launchd) but untested.
- `container run` flags present: `--rm`, `--read-only`, `--tmpfs`, `-v/--volume`, `--mount type=,source=,target=,readonly`,
  `-c/--cpus`, `-m/--memory`, `-u/--user`, `--uid/--gid`, `--cap-drop`, `--init`, `--ulimit`, `--platform`, `--no-dns`.
  ABSENT/undocumented: `--network none`, `--security-opt`, `--pids-limit`. `container network create --internal`
  ("Restrict to host-only network") exists, but whether outbound internet is actually blocked is not stated: UNVERIFIED,
  would need a test (`curl` from the container). `--ulimit nproc` could substitute for pids-limit (untested).
- `container stop/kill/ls/prune` exist (`kill` default signal KILL): orphan cleanup = `container ls -a` + `kill` + `prune`.
- Lean: same Linux-guest question as Docker (needs the Linux toolchain + oleans; host `.lake` via `--mount ...readonly`
  over virtiofs). Per-container VM boot: Apple advertises sub-second starts (UNVERIFIED here); each VM has its own page
  cache, so Mathlib is read cold per container (1.9 GB mmap per check, cost UNMEASURED; Docker's shared VM caches it once).
- Fresh state: yes (`--rm`, read-only root). Harness wrapper identical to Docker's with different flags.
Verdict: promising, but the missing/undocumented network-off flag and pre-1.0 status make it a re-check in 6 months, or
a try-out only if you accept running a network test first.

## 5. Linux VM via Virtualization.framework (Lima vz / Tart / UTM / vfkit)

- Lima: `vmType: vz` is the default on macOS since v1.0 (verified; needs macOS >= 13). virtiofs mounts; Lima's default
  template mounts the HOST HOME read-only (from memory, UNVERIFIED): must set `mounts: []` plus explicit ones. The
  network doc fetched does not describe a no-network mode (verified: not covered); a vzNAT guest has outbound by default,
  so network-off would need an in-guest firewall set by root and unreachable to the check user (weaker than
  `--network none`). A Lima instance is long-lived: a hostile check can persist state (toolchain, shell rc) unless the
  harness clones/deletes per run (`limactl clone`/`delete` exist; cost and vz snapshot support UNVERIFIED). Calls via
  `limactl shell <vm> -- <argv>` (ssh); orphan cleanup `limactl stop -f`/`delete -f`.
- Tart (Cirrus Labs): Fair Source licence, free on personal computers/workstations; paid only beyond 100 CPU cores per
  org (verified, tart.run/licensing). `tart run --dir name:path:ro` shares read-only over virtiofs; Linux guests mount
  manually (`mount -t virtiofs com.apple.virtio-fs.automount ...`) (verified). `--net-softnet` isolates the host from
  the guest (verified); whether it can also deny internet is UNVERIFIED. `tart clone` of a golden image per run is the
  fresh-state mechanism (CoW on APFS: believed instant, UNVERIFIED); Linux images are >= 20 GB (verified). Harness:
  `tart clone golden eq-N; tart run --no-graphics ... &; ssh $(tart ip eq-N) <argv>; tart stop; tart delete`.
  Boot to ssh ~5-20 s (UNVERIFIED estimate): +20-80 % on a ~25 s PF check, more than Docker's ~1 s.
- Strength: hypervisor boundary, like Docker, with a per-run fresh VM possible; network-off and glue are harder than
  `docker run --network none`. Lean/Mathlib: same Linux requirement as Docker. No advantage over Docker except per-run
  fresh VM; no 2-VM limit for Linux guests (verified by web summaries).

## 6. macOS guest VM (Tart / Virtualization.framework macOS guest)

- Reuses the host's macOS Lean toolchain, uv, Python, and the same oleans: copy `~/.elan/toolchains/...4.34.1` (2.7 GB)
  and `stack_mathlib/.lake` (7.6 GB, or only oleans + sources) into the golden image at the same absolute path
  (olean/lake trace path sensitivity UNVERIFIED), then CoW-clone per run. No re-verification of numerics beyond a
  smoke test: this is the only option whose environment equals the one the 218/218 refs were verified in.
- Licence: macOS SLA section 2.B.iii allows 2 additional virtual macOS instances per Mac for development, testing,
  server or personal non-commercial use; the kernel enforces 2 concurrent macOS guests (secondary sources: eclecticlight,
  macstadium, khronokernel; legal reading UNVERIFIED, I am not a lawyer). So at most 2 checks in parallel, which also
  caps harness throughput.
- Size: base image ~25 GB (tart quick-start, verified) + 10 GB Lean => ~35-40 GB golden; per-run clones are CoW (cheap
  until written). Boot to ssh ~15-40 s (UNVERIFIED estimate): +60-160 % on every PF check; CP/CR checks (~1-3 s of
  work) become boot-dominated, so batch several item-arm checks per VM only if you accept shared state (weakens
  "fresh").
- Headless: Virtualization.framework needs an unlocked login keychain while a VM runs (verified, tart FAQ), so it runs
  from a logged-in user session in a normal terminal, not from an agent sandbox. Guests need Remote Login; default
  tart credentials admin/admin (change them).
- Network off: `--net-softnet` host isolation (verified); full deny UNVERIFIED. Mounts: `--dir x:path:ro` (guest at
  `/Volumes/My Shared Files`), fresh copy rw via a second share or scp in/out.
- Verdict: heaviest, but the exact-environment fallback.

## 7. Side-by-side

| | sandbox-exec | Docker (Desktop/Colima/OrbStack) | Apple `container` | Linux VM (Lima/Tart) | macOS guest (Tart) |
|---|---|---|---|---|---|
| Boundary | seatbelt, same kernel | Linux VM (shared by containers) | VM per container | VM per run possible | VM per run |
| Network off | `(deny network*)`, exact | `--network none`, exact | not documented; test | in-guest fw / softnet; weak | softnet; test |
| Default-deny files | no (read allow-list, brittle) | yes (only mounts) | yes | yes | yes |
| Lean/Mathlib | host as is | Linux Lean + oleans (spike) | same as Docker | same as Docker | host artefacts cloned |
| Re-verify 218 refs | no | yes (~20-90 min) | yes | yes | smoke only |
| Startup / 25 s check | ~0 | ~1 s | ~1 s (claimed) | 5-20 s | 15-40 s |
| Fresh state | fresh copy only | `--rm`, read-only root | `--rm` | clone per run | clone per run |
| Concurrency cap | none | VM resources | VM per ctr RAM | VM RAM | 2 macOS VMs |
| Installed here | built in (deprecated) | CLI + Desktop installed | no | no | no |
| Runs inside agent sandbox | yes | no (socket denied) | no (likely) | no | no |
| Effort (UNVERIFIED) | 1 d | 2-3 d | 2-4 d + test | 3-5 d | 4-6 d |
| Main risk | deprecated, escapes, brittle | 2nd Lean env, ownership | pre-1.0, flags | glue, network | licence, size, time |

"Both" (Docker for PF/CP/CR checks, sandbox-exec fallback): fine as engineering, but the experiment must freeze one
backend per stage; a mixed run changes conditions between arms. Keep sandbox-exec only as a pre-registered alternate
profile if Docker is unavailable, never mixed within a stage.

## 8. Recommended path

1. Spike (user terminal, 1-2 h): `docker info`; pin a Linux arm64 base by digest; fetch Lean 4.34.1 aarch64 Linux
   tarball (sha256-pinned); mount the host `stack_mathlib/.lake` read-only; run `check_lean.sh` on one ref and one wrong
   answer for PF-0001 with the full hardening flags. Pass => no Mathlib rebuild. Fail => `lake exe cache get` at build.
2. Build `isolate()` in `eq_harness.py` (backend key in `flags.json`: `none|docker`), covering `run_check`, `run_oracle`
   and mediator `verify()`; named containers + `docker kill` on timeout + orphan sweep; unit tests with a fake `docker`
   stub; negative tests (network, read `$HOME`, write outside `/work`, fork bomb, `#eval IO.Process.spawn`, sleep
   past timeout, orphan after harness kill).
3. Re-verify 218/218 refs and 218 wrong answers plus CP/CR selftests inside the image; compare to
   `oracle/build/final_check.tsv`; record image digest and olean-tree hash in CONFIG.txt; freeze.
Effort ~2-3 days (UNVERIFIED). If step 1/3 shows divergence, choose between sandbox-exec (1 d, host toolchain) and the
macOS guest (heaviest, exact environment).

## 9. Could Docker/VMs isolate the member `claude -p` sessions?

Probably not worth it. A member needs the Claude CLI plus its auth (OAuth keychain item or token, which a model with
Bash could read and exfiltrate unless egress is restricted to the API by a proxy), outbound HTTPS to the API, the
allowed tools (Read/Edit/Write/Bash in the arm's workdir), and `uv`/Lean for CP/CR/PF fixtures. A container would need a
Linux Claude install, credential injection, an allow-listing egress proxy (a container cannot be both `--network none`
and call the API), and the harness's session/permission plumbing would change, with the model-in-container run no
longer identical to the stub-tested path. The cheaper fixes target the actual leaks: keep `items/*/oracle/` and
`grading_keys/` out of any path a member can read (separate macOS user, or an unmounted disk image mounted only at
scoring), and, if Claude Code's own Bash sandbox (Seatbelt-based, as this agent session uses) can be enabled per member
call with `denyRead` on those paths, use that; whether `claude -p` accepts such settings per call is UNVERIFIED.

## 10. Sources (fetched 2026-10-04)

- https://github.com/apple/container and docs/command-reference.md (requirements, flags, network --internal)
- https://tart.run/faq/ , https://tart.run/licensing/ , https://tart.run/quick-start/ (keychain, softnet, --dir :ro, 25 GB image, licence)
- https://lima-vm.io/docs/config/vmtype/ , .../vmtype/vz/ , .../network/ (vz default since v1.0, macOS >= 13; no no-network mode documented)
- macOS 2-VM limit: web search summary citing eclecticlight.co/2023/09/14/..., docs.macstadium.com known-issues,
  khronokernel.com/macos/2023/08/08/AS-VM.html (secondary sources)
- Local: `docker`/Docker.app versions, `vm_stat`, `.lake` sizes, `check_lean.sh`, `eq_harness.py` (paths above).
