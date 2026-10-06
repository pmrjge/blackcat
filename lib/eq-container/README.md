# lib/eq-container

Isolation images of the equilibrium harness, run with Apple `container` (https://github.com/apple/container, CLI 1.5.0): every
container is its own lightweight Linux VM. Images: Lean 4.34.1 + Mathlib v4.34.1 (PF checks) and CPython 3.14.8 + uv (CP/CR
checks), built locally with `container build`, run with `--network none --read-only --cap-drop ALL --init`, a VM size (`-m`, `-c`),
a process-count limit (`--ulimit nproc`), the unprivileged user 10001, no host environment, ONLY the staged check inputs mounted
read-only and a capped tmpfs `/work` filled from them. Oracles, credentials and the home folder are never mounted. Optional:
`install.sh --with-eq-container` runs `setup.sh run` (off by default): with your consent it installs the `container` CLI (Apple's
signed .pkg, pinned in `PINS`), starts its service and runs `eq-container.sh install` (CONFIG.md §7). This replaces the Docker
backend (`lib/eq-docker`, never merged); Seatbelt/sandbox-exec and App Sandbox were rejected (USER, 2026-10-05).

| file | role |
|---|---|
| `eq-container.sh` | the driver: `install` (`--no-build`: a due build is a skip), `build-due`, `check`, `status`, `print-env`, `uninstall`; never installs `container` or starts its services |
| `setup.sh` | the guided set-up (`run`, `state`, `removal`): 1. the CLI (download from GitHub's release hosts, size/sha256/signer against `PINS` `CONTAINER_PKG_*`, `sudo installer`: the one sudo), 2. `container system start`, 3. the driver; each step only with consent (a typed answer or its flag), skipped when done; records `cli.env`, `setup.env` |
| `lib.sh` | shared helpers: state dir, image records, `eq_require_image` (the digest `container image inspect` reports must equal the record before every run), `eq_run` (the one place that builds a `container run`) |
| `eqc_json.py` | the one reader of the CLI's JSON (`image inspect`, `list --format json`) and of `image save` archives |
| `TOOLS.toml`, `tools.sh` | the declarative tool manifest (every tool, url, sha256, provenance, allowlists per image class, images, profiles) and its reader |
| `verify-tools.sh` | checks the manifest (`--manifest`) and the built images against it (`--images --deep --inspect` from the saved image, `--smoke`) |
| `build.sh` | idempotent builds from `Dockerfile.minimal` (core, candidates) and `Dockerfile.toolchains` (extension images); `--profiles core,jvm`; a `check-<target>` stage is built first (a failure is exit 12); refuses a placeholder (13), a malformed pin (2) and a deferred profile (10); `--set full` is exit 2; `--resolve-tools [--write-pin]` prints (and writes) the three bash pins after the source signatures verified |
| `base-pins.sh`, `base/` | host-side, no container: checks the pinned distroless base (format, the bytes in `base/` against the pins, `cosign verify` with the Google identity); edits nothing. `base/` keeps the index and arm64 manifest bytes the pins were read from |
| `probe.sh`, `probe_inner.sh`, `probe.d/50-tunnel.sh` | the isolation proof (in-container rows, limit sub-probes, the image works under the flags) and the WALL tunnel probe |
| `minimal/`, `tc/` | `mkrootfs.sh` (the one layer of the distroless-cc images: no shared object copied, every dynamic ELF must resolve against base + layer via the loader's `--list` in a chroot), `check.sh` (the `check-<target>` stage, run in the final filesystem as user 10001), `perl-shim`, `lake-shim`, `untar.py`; the toolchain recipes `fetch-tool.sh`, `mkrootfs-tc.sh`, `tc/build-bash.sh` (static bash from the GPG-signed source); `install-rust.sh` and `install-ghc.sh` stay for the deferred profiles |
| `project/` | the Lake project (lakefile, manifest, toolchain) the Mathlib cache is fetched for |
| `LAYOUT` | the word `repo`: state defaults to `${XDG_STATE_HOME:-~/.local/state}/claude-agent-stack/eq-container` (without it, `./.state`) |

Profiles: `core` (default, always included: `min-both` for PF, `min-py` for CP and CR), then opt-in `node go julia jvm`; `rust` and
`haskell` are deferred (no distroless image supplies the linker they call): the profile is refused with exit 10 and the reason.

Images and bases (USER decisions, 2026-10-06; spec and record: `DESIGN_DISTROLESS.md`). Every final image is `FROM` the
digest-pinned `gcr.io/distroless/cc-debian13` (`nonroot`; index and linux/arm64 manifest in `PINS`) or `scratch` (`tc-go`), with one
`COPY`, no `RUN` and `USER 10001:10001`. There is no Debian runtime image, apt, dpkg or Debian snapshot in any final image or in the
build path; the builders are `buildpack-deps:trixie` and `alpine:3.24`, both by digest, and `apk` runs only in the bash stage.
- bash: static GNU bash 5.3 with patches 001-020, built in the Alpine stage by `tc/build-bash.sh` from the GPG-signed source (key
  7C0135FB088AAF6C66C650B9BB5869F064EA74AB, fetched from keyserver.ubuntu.com, fingerprint enforced); the built binary is pinned.
- perl: none. `minimal/perl-shim` (`/opt/eq/bin/perl`) answers only `check_lean.sh`'s timeout wrapper and refuses any other script;
  `check_lean.sh` and the PF pool are unchanged.
- CP and CR: distroless cc plus the glibc python-build-standalone CPython. jq: the official static jq 1.8.2. busybox: docker-library's
  musl build (rootfs tarball and binary pinned). uv: the static musl build 0.12.22.
- The Debian `full` image and `STACK_EQ_CONTAINER_SET=full` are removed (`--set full`: exit 2 in `build.sh` and `eq-container.sh`).
  Scala 3 comes from the release tarball on the shared JDK; MongoDB is out (and PostgreSQL with it: compose was its only runner).
The probe has three rows for this: `no_debug_shell`, `no_package_manager`, `network_probe_control` (bash's `/dev/tcp` is compiled in
and a connect to a closed port is refused, so the network rows cannot pass vacuously).

Pins still open: `BASH_SRC_SHA256`, `BASH_PATCHES_SHA256` and `BASH_BIN_SHA256` (`PINS`, `TOOLS.toml`). Until they are set, `core`
stops with exit 13. Run `bash lib/eq-container/build.sh --resolve-tools` from a normal terminal: it prints the three values after
"SIGNATURES OK"; review them, then run `--resolve-tools --write-pin` (writes `PINS`, the `Dockerfile.minimal` ARGs and `TOOLS.toml`;
trust on first use after the signature check: a set source or patch pin that differs is refused, exit 12). `bash lib/eq-container/base-pins.sh` checks the base's authenticity (needs cosign).
Re-pin of the distroless base (it is rebuilt often): fetch the new index and linux/arm64 manifest bytes into `base/`, change
`DISTROLESS_CC` and `DISTROLESS_CC_ARM64` in `PINS` and the ARG defaults of both Dockerfiles together, run `base-pins.sh`, rebuild.

Run the scripts with `bash script.sh` from a normal terminal (an agent's sandbox cannot reach the `container` services); exit codes
are in the headers of `lib.sh` and `eq-container.sh` (10 = the CLI missing or its services down: a skip, never a failed install).
Tests (hermetic, a fake `container` CLI): `tests/test_eq_container.py`, `tests/test_install_eq_container.py`,
`tests/test_eq_container_pins.py` (pins and the manifest rules).
