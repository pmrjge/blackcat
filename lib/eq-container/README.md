# lib/eq-container

Isolation images of the equilibrium harness, run with Apple `container` (https://github.com/apple/container, CLI 1.5.0): every
container is its own lightweight Linux VM. Images: Lean 4.34.1 + Mathlib v4.34.1 (PF checks) and CPython 3.14.8 + uv (CP/CR
checks), built locally with `container build`, run with `--network none --read-only --cap-drop ALL --init`, a VM size (`-m`, `-c`),
a process-count limit (`--ulimit nproc`), the unprivileged user 10001, no host environment, ONLY the staged check inputs mounted
read-only and a capped tmpfs `/work` filled from them. Oracles, credentials and the home folder are never mounted. Optional:
`install.sh --with-eq-container` runs `eq-container.sh install` (off by default). This replaces the Docker backend (`lib/eq-docker`,
never merged); Seatbelt/sandbox-exec and App Sandbox were rejected (USER, 2026-10-05).

| file | role |
|---|---|
| `eq-container.sh` | the driver: `install`, `check`, `status`, `print-env`, `uninstall`; never installs `container` or starts its services |
| `lib.sh` | shared helpers: state dir, image records, `eq_require_image` (the digest `container image inspect` reports must equal the record before every run), `eq_run` (the one place that builds a `container run`) |
| `eqc_json.py` | the one reader of the CLI's JSON (`image inspect`, `list --format json`) and of `image save` archives |
| `TOOLS.toml`, `tools.sh` | the declarative tool manifest (every tool, url, sha256, provenance, allowlists per image class, images, profiles) and its reader |
| `verify-tools.sh` | checks the manifest (`--manifest`) and the built images against it (`--images --deep --inspect` from the saved image, `--smoke`) |
| `build.sh` | idempotent builds from `Dockerfile` (full, Debian slim), `Dockerfile.minimal` (FROM scratch), `Dockerfile.toolchains` (extension images); `--profiles core,jvm`; refuses a placeholder (13) or malformed (2) pin; `--resolve-tools --write-pin` pins the distro-package tools from the builder (trust on first use) |
| `distro-pins.sh` | host-side, no container: derives version + sha256 of bash, perl (base-image layer, `BASE_LAYER_*` in PINS), jq and busybox (snapshot: gpgv-verified InRelease, signed index and `.deb` hashes) and compares them with the pins; edits nothing |
| `probe.sh`, `probe_inner.sh`, `probe.d/50-tunnel.sh` | the isolation proof (in-container rows, limit sub-probes, the image works under the flags) and the WALL tunnel probe |
| `minimal/`, `tc/` | `mkrootfs.sh` (ldd-resolved rootfs of the scratch images), `lake-shim`; the toolchain recipes, `apt-closure.sh` (cc in Rust/Haskell) |
| `project/` | the Lake project (lakefile, manifest, toolchain) the Mathlib cache is fetched for |
| `LAYOUT` | the word `repo`: state defaults to `${XDG_STATE_HOME:-~/.local/state}/claude-agent-stack/eq-container` (without it, `./.state`) |

Profiles: `core` (default, always included: `min-both` for PF, `min-py` for CP and CR), then opt-in `node rust go julia haskell
jvm`. Image decisions (USER, 2026-10-05): Debian-packaged bash, perl, jq and busybox; Scala 3 from the release tarball on the shared
JDK; MongoDB out (and PostgreSQL with it: compose was its only runner); a `cc` linker in the Rust and Haskell images. bash and perl
are pinned (2026-10-06: hashed from the base image's layer, sources in `checksum_source`). Until `BUSYBOX_SHA256` (PINS) and the jq
pins (TOOLS.toml) hold the values `bash distro-pins.sh` prints from a normal terminal, `core` stops with exit 13; `--set full`
builds the full Debian image instead.

Run the scripts with `bash script.sh` from a normal terminal (an agent's sandbox cannot reach the `container` services); exit codes
are in the headers of `lib.sh` and `eq-container.sh` (10 = the CLI missing or its services down: a skip, never a failed install).
Tests (hermetic, a fake `container` CLI): `tests/test_eq_container.py`, `tests/test_install_eq_container.py`,
`tests/test_eq_container_pins.py` (pins; distro-pins.sh against a fake snapshot).
