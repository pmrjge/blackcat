# lib/eq-docker

Isolation images for the equilibrium harness: Lean 4.34.1 + Mathlib v4.34.1 (PF checks) and CPython 3.14.8 + uv (CP/CR/ES
checks), built locally and run with `--network none --read-only --cap-drop ALL`, no host environment, a read-only copy of the
check files and a capped tmpfs `/work`. Optional extension toolchains (Node, Rust, Go, Julia, Haskell, Java and Scala) and two database servers
(PostgreSQL, MongoDB) are opt-in profiles of the same manifest. Optional: `install.sh --with-eq-docker` runs `eq-docker.sh install` (off by default).

| file | role |
|---|---|
| `eq-docker.sh` | the driver: `install`, `check`, `status`, `print-env`, `uninstall` (flags in its header: `--profiles`, `--wait-daemon`; Docker offer only with explicit consent, `--yes` alone is not consent) |
| `lib.sh` | shared helpers: state dir, image records, `eq_require_image` (refuses an unrecorded or retagged image), `eq_run` (the one place that builds a `docker run`) |
| `TOOLS.toml`, `tools.sh` | the declarative tool manifest (every tool, url, sha256, provenance, allowlists per image class, images, profiles) and the reader every script uses; no tool outside it gets into an image |
| `verify-tools.sh` | checks the manifest (`--manifest`) and the built images against it (`--images --deep --inspect --smoke`); never builds |
| `build.sh`, `build-minimal.sh` | idempotent builds from `Dockerfile` (full, Debian slim), `Dockerfile.minimal` (FROM scratch), `Dockerfile.distroless` (candidate), `Dockerfile.toolchains` (extension images); `--profiles core,jvm,db` selects manifest profiles; `--resolve-tools --write-pin` pins the distro-package tools; inputs pinned in `PINS` and `TOOLS.toml` |
| `Dockerfile.toolchains`, `tc/` | the extension images on the shared minimal base `eq-base` (`fetch-tool.sh`, `mkrootfs-tc.sh`, the recipes `build-postgresql.sh`, `install-rust.sh`, `install-ghc.sh`, the hash-pinned database entry scripts) |
| `compose.yaml`, `compose.wall.yaml`, `eq-compose.sh` | the compose front-end (read-only, no network except the internal-only database network, one service per image) and its wrapper; the WALL override adds the one tunnel mount |
| `spike.sh`, `probe.sh`, `probe_inner.sh`, `probe.d/` | does the image work under the flags (spike), do the isolation properties hold (probe; `probe.d/*.sh` hooks add the tools-manifest, internal-network and WALL tunnel proofs) |
| `reverify.sh`, `compare-images.sh`, `trace-reads.sh` | maintainer tools: re-verify the pools in the container, choose between candidate images, trace which module files a check reads |
| `minimal/` | `mkrootfs.sh` (ldd-resolved rootfs for the scratch images) and `lake-shim` |
| `project/` | the Lake project (lakefile, manifest, toolchain) the Mathlib cache is fetched for |
| `LAYOUT` | the word `repo`: state defaults to `${XDG_STATE_HOME:-~/.local/state}/claude-agent-stack/eq-docker` (without it, `./.state`) |

Profiles: `core` (the default and always included: `min-both` for PF, `min-py` for CP and CR; ES, RS, DS and OE run on the host), then opt-in
`node rust go julia haskell jvm db`; `mongo` (SSPL) is explicit-only and `all` never contains it. Entries that are still `PLACEHOLDER` in
`TOOLS.toml` (the distro-package versions until `build.sh --resolve-tools --write-pin`, the Scala 3 distribution, `mongosh`) stop the build with exit 13.

Run scripts with `bash script.sh`; exit codes are listed in the headers of `lib.sh`, `eq-docker.sh` and `verify-tools.sh` (10 = Docker missing or
daemon down: a skip, never a failed install; 13 = a pin in `PINS` or `TOOLS.toml` is still a placeholder; 16 = a tool verification or smoke test failed).

Tests (hermetic, fake `docker` and `brew`; the compose tests need PyYAML): `uv run --with pytest --with pyyaml --with pytest-xdist pytest -q -p no:cacheprovider -n 6 tests`
(about 5 minutes with six workers; each test starts several bash processes).
Maintainer steps that need a real daemon are in the equilibrium working directory's `RUNBOOK_MINIMAL.md`; the design is in its `INSTALLER_SPEC.md` section 12.
