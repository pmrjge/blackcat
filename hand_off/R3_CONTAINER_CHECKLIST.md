# R3: Apple `container` 1.5.0 behaviour the code assumes but no agent could check (T3, 2026-10-05)

User checklist (branch `r3-ready`). Every agent test runs against a fake CLI (`tests/fake-container/container`, the
harness's `harness/tests/fake_container`); this table is what the real CLI must do for those fakes to be faithful. A row
that prints something else: give the output to the R3 owner (the last column names the code that depends on it).

Run each block in a normal logged-in terminal (an agent's Seatbelt sandbox cannot reach the container services).
They need `container system start` once and the `alpine:latest` image you already pulled; none touches the stack's
images or state. Docs-verified (apple/container 1.5.0 docs/command-reference.md,
https://raw.githubusercontent.com/apple/container/1.5.0/docs/command-reference.md; a copy in the git-ignored
`M/.claude/worktrees/agent-a5a3114a94bceb867/.claude-work/r3/container-1.5.0-command-reference.md`): `run -e/-i/-l/--label/-d/--ulimit/--tmpfs`,
`list --format json`, `kill`, `delete --force`, `image save --output`, `build -m/-c/--progress/--no-cache/--platform/--target`.
Docs are not behaviour: every item below stays [unverified] until its command prints what is described.

| # | command | confirms when | code that depends on it |
|---|---|---|---|
| C1 | `container image inspect alpine:latest \| jq '.[0] \| {id, d: .configuration.descriptor.digest}'` | `d` is `sha256:<64 hex>` and `id` is the same 64 hex without `sha256:` (the 1.5.0 source, ImageResource.swift; the earlier `.configuration.index.digest` guess was wrong and is no longer read) | `lib/eq-container/eqc_json.py` DIGEST_PATHS (`digest`), `lib.sh` eqc_image_digest/eq_require_image, `dot-config/dot-claude/bin/doctor.sh` eqc_digest, harness `INSPECT_DIGEST_PATHS`/`inspect_digest`/`require_image`. If neither: every digest check fails closed (images "not present") |
| C2 | `container system status; echo rc=$?` then `container system stop; container system status; echo rc=$?; container system start` (only with nothing running) | rc=0 while running, rc!=0 after stop | every skip path: `lib.sh` eqc_state (exit 10), `eq-container.sh` install skip, `doctor.sh` "services not running", harness `require_services` (run_abort) |
| C3 | `container run -d --name eq-chk-1 --label eq-harness=1 --label eq-inv=x alpine:latest sleep 60; container list --all --format json \| jq '.[] \| {id: .configuration.id, labels: .configuration.labels}'; container delete --force eq-chk-1` | a row with `id == "eq-chk-1"` and `labels` an object holding `eq-harness: "1"`, `eq-inv: "x"` | `eqc_json.py` ids/exists, `lib.sh` eq_list_ids/eq_sweep, harness `list_rows`/`sweep` (orphan reaper; a different shape = nothing is ever swept) |
| C4 | `container kill eq-none-404; echo rc=$?; container delete --force eq-none-404; echo rc=$?` | note the two rc values (the fake returns 0) | informational: `lib.sh` eq_sweep and the harness `kill`/`sweep` ignore these rc values |
| C5 | `container image save --output "$TMPDIR/a.tar" alpine:latest && tar -tf "$TMPDIR/a.tar" \| head` | `index.json` + `blobs/sha256/...` (OCI layout) or `manifest.json` (docker-save) | `eqc_json.py` oci-config/oci-cat/oci-sha256, `lib.sh` eq_save_image, `verify-tools.sh --inspect` (tool re-hash from the saved image) |
| C6 | `container run --rm --read-only --tmpfs /work:size=64M,mode=1777 alpine:latest sh -c 'df -k /work; stat -c %a /work; dd if=/dev/zero of=/work/f bs=1M count=100; echo rc=$?'` | df total about 65536 KB, mode `1777`, dd stops with "No space left on device" and rc!=0 | `lib.sh` eq_base_flags/eq_run (`/tmp`, `/work`), harness `isolate()` `--tmpfs` (`container_tmp_size`, `container_work_size`), probe.sh work_tmpfs_size/work_size_capped |
| C7 | `container run --rm --user 10001:10001 --ulimit nproc=16 alpine:latest sh -c 'ulimit -u; for i in $(seq 1 40); do sleep 5 & done; wait; echo done'` | prints `16` and fork errors ("can't fork" / "Resource temporarily unavailable") | `lib.sh` EQ_NPROC `--ulimit nproc=`, harness `limits()`, probe.sh nproc sub-probe (no `--pids-limit` exists) |
| C8 | `container run --rm alpine:latest sh -c 'exit 7'; echo rc=$?` and `container run --rm --bogus-flag alpine:latest true; echo rc=$?` | first rc=7; note the second rc | harness `Isolation.run` (code's own exit = verdict input; CLI errors are not told apart), `lib.sh` eq_run return value |
| C9 | `printf 'hello\n' \| container run --rm -i alpine:latest cat` | prints `hello` | harness EQV1 nonce on stdin (`-i`), `lib.sh` EQ_RUN_STDIN |
| C10 | `FOO=leak container run --rm -e A=1 alpine:latest env` | `A=1` present, no `FOO` | harness CONTAINER_ENV (`-e KEY=VALUE` only), `lib.sh` eq_base_flags |
| C11 | `container run --rm --read-only --user 10001:10001 alpine:latest id` | `uid=10001 gid=10001` (no passwd entry needed) | `EQ_USER`, harness `container_user` |
| C12 | `container run --rm eq.invalid/none:x true; echo rc=$?` | rc!=0 quickly, an image-not-found/resolve error, no pull from a registry | the `eq.invalid/` image names (`lib.sh`, `install.sh` eq_image_ref_ok) |
| C13 | `container --version \| head -n 1` | one line naming 1.5.0 | `build.sh` EQ_CONTAINER_VERSION record (informational) |

## Distroless images and real builds (branch `eq-distroless`, 2026-10-06; replaces C14-C17 of `eq-pins`)

The Debian images, the snapshot and `distro-pins.sh` are gone (USER decisions 2026-10-06, `hand_off/HANDOFF_STATE.md` §6;
`lib/eq-container/DESIGN_DISTROLESS.md`). Run these from the repository root in a normal terminal, in order. D1 needs `cosign`
(`brew install cosign`), python3 and network, no container. D2-D6 need `container system start`, download several GB (hosts:
`DESIGN_DISTROLESS.md` §9) and write only `~/.local/state/claude-agent-stack/eq-container`. Nothing here pushes. Until D2 is done,
`core` stops at exit 13: the three bash pins (`BASH_SRC_SHA256`, `BASH_PATCHES_SHA256`, `BASH_BIN_SHA256`) are placeholders.

| # | command | confirms when | code that depends on it |
|---|---|---|---|
| D1 | `bash lib/eq-container/base-pins.sh; echo rc=$?` | one `BASE distroless-cc gcr.io/distroless/cc-debian13@sha256:e792ab3d... arm64 sha256:2f0295ce... layers N cosign=OK` line and rc=0. Any other rc (1 a failed check, 2 a malformed pin, 13 a placeholder): give the output to the pins owner and pin nothing | `PINS` `DISTROLESS_CC`/`DISTROLESS_CC_ARM64`, `base/`, `base-pins.sh` |
| D2 | `bash lib/eq-container/build.sh --resolve-tools`; after review of the printed values, `bash lib/eq-container/build.sh --resolve-tools --write-pin`; then `bash lib/eq-container/verify-tools.sh --manifest --profiles core` | the first command prints `SIGNATURES OK` (primary key `7C0135FB088AAF6C66C650B9BB5869F064EA74AB`) and three `PIN KEY VALUE pinned: ...` lines (`BASH_SRC_SHA256`, `BASH_PATCHES_SHA256`, `BASH_BIN_SHA256`; `pinned: PLACEHOLDER` before the first write); a bad or missing signature stops before any hash is printed. After `--write-pin` the last command prints `TOOLS: manifest OK` | `tc/build-bash.sh`, `Dockerfile.minimal` `bash`/`bash-report`, `PINS`, `TOOLS.toml` |
| D3 | `bash lib/eq-container/build.sh --profiles core --yes; echo rc=$?` | `check-eq-min` and `check-eq-py-min` pass (`CHECK ok` lines, no `CHECK FAIL`), then min-both and min-py are built; rc=0. A failing check is rc=12 and nothing is recorded | `minimal/check.sh`, `minimal/mkrootfs.sh`, `Dockerfile.minimal` |
| D4 | reproducibility: run `bash lib/eq-container/build.sh --profiles core --yes --force` again; for each of the two builds save the image (`container image save --output "$TMPDIR/a.tar" <eq.invalid tag>`) and read `python3 -I lib/eq-container/eqc_json.py oci-cat "$TMPDIR/a.tar" /opt/eq/MANIFEST.root` | the two `/opt/eq/MANIFEST.root` files are byte-equal (save the first build's archive before the `--force` rebuild, in case the tag is reused [unverified]) | `minimal/mkrootfs.sh` MANIFEST.root, `eqc_json.py` oci-cat |
| D5 | `bash lib/eq-container/verify-tools.sh --images --deep --inspect --smoke --profiles core; bash lib/eq-container/eq-container.sh install` | `TOOLS: images OK`, `inspect OK`, `smoke OK` (the base layers equal the pinned distroless layers); the install ends with status ok and the probe passes, including `no_debug_shell`, `no_package_manager` and `network_probe_control`. Then `./install.sh --with-eq-container` reaches step 10c and does not skip the WALL | `verify-tools.sh`, `probe.sh`, `probe_inner.sh`, `install.sh` 10b/10c |
| D6 | harness parity: `uv run --script <equilibrium>/harness/eq_harness.py isolation-probe ...` [arguments: see the harness README], then the PF, CP and CR dev items through the container and again with isolation `off` | the same verdicts on both backends | the harness, `minimal/perl-shim` (PF timeout wrapper), the isolation contract |
| D7 | exec-form `RUN` in a stage built FROM a distroless image: the `check-*` stages of D3 are one (`RUN ["/opt/eq/bin/busybox", "sh", "/opt/eq-check/check.sh", ...]`) | the check stage runs, although the base has no shell [unverified until D3] | `Dockerfile.minimal` `check-*` stages |
| D8 | `COPY --from=distroless-cc / /base-rootfs/` in `container build`, where `distroless-cc` is `FROM ${DISTROLESS_CC}` (the `prep` stage of `Dockerfile.minimal`; D3 exercises it) | the stage builds and `mkrootfs.sh` sees the base's libraries under `/base-rootfs` [unverified until D3] | `Dockerfile.minimal`, `minimal/mkrootfs.sh` |
| D9 | `--init` on an image without a shell: the toolchain images have none (min-both and min-py carry `/opt/eq/bin/bash`), e.g. `bash lib/eq-container/build.sh --profiles go --yes; bash lib/eq-container/verify-tools.sh --smoke --select tc-go` (optional profile) | the smoke row passes (`container run --init ... /opt/go/bin/go version`); the init comes from the runtime's init image per the 1.5.0 command reference, behaviour [unverified] | `lib.sh` `eq_run`, `Dockerfile.toolchains` |

D7-D9 are the three behaviour rows of `DESIGN_DISTROLESS.md` §9; D7 and D8 have no command of their own (D3 exercises them), D9
needs an optional toolchain image. A failure there appears as a failed D3, D5 or smoke row: give the output to the pins owner.

Already verified by you (HANDOFF_STATE §7): `container run --help` flags; `--network none` (spike); `image inspect` top-level
keys `configuration`, `id`, `variants`.

Read in the CLI source at tag 1.5.0 during the R3 review (source, not behaviour; the rows above still need running):
C1's shape (Sources/ContainerResource/Image/ImageResource.swift, checked by the builder); `--mount` splits each key=value at
`=` and drops empty pieces (Sources/Services/ContainerAPIService/Client/Parser.swift, checked by the builder: so lib.sh,
the harness and install.sh refuse `=` in mounted paths, as they already refused `,`); C3's row shape (ManagedContainer.swift), `--ulimit
nproc` accepted and tmpfs mounts applied before binds (Utility.swift): security-auditor's reading, not re-checked.

## The guided set-up: CLI install, service start, consent (branch `eq-cli-install`, 2026-10-06)

`./install.sh --with-eq-container` now runs `lib/eq-container/setup.sh` (CONFIG.md §7). Agents tested it with fakes only:
no agent downloaded the package, ran sudo or `installer`, or started the service. Run these in a normal logged-in terminal,
from the repository's main checkout, in order. C22 changes the system and is optional. A scratch home
(`HOME=$(mktemp -d)`) does NOT isolate C21 or C22: the package installs system-wide under `/usr/local`, and the container
services are per user (launchd), not per home folder.

| # | command | confirms when | code that depends on it |
|---|---|---|---|
| C18 | `d=$(mktemp -d) && curl -q -fL --proto =https -o "$d/c.pkg" https://github.com/apple/container/releases/download/1.5.0/container-1.5.0-installer-signed.pkg && wc -c < "$d/c.pkg" && shasum -a 256 "$d/c.pkg" && /usr/sbin/pkgutil --check-signature "$d/c.pkg"; rm -rf "$d"` (downloads 118 MB, installs nothing, no sudo) | `118045087`; sha256 `a24808cb202318fa1c3bbee0c6c6887fe1225fe899d7b687a0ddd939bd6573f8` (the PINS value, from GitHub's API); a `Status: signed ...` line and a Certificate Chain. Give the whole output to the pins owner: the text after `1. ` becomes `CONTAINER_PKG_SIGNER` in `lib/eq-container/PINS` (commit it). Until then step 1 refuses (exit 13, nothing downloaded). A different size or sha256: do not pin anything; report it | `PINS` `CONTAINER_PKG_*`, `setup.sh` verify_pkg |
| C19 | `bash lib/eq-container/setup.sh state` | `EQ_CLI_STATE=ok`, `EQ_CLI_VERSION=1.5.0`, `EQ_PLATFORM=ok`, `EQ_SERVICE=running` (or `stopped`), `EQ_CLI_PINS=placeholder` before C18, `ok` after. Nothing is downloaded, started or written | `setup.sh` cli_state/svc_state/platform (the `container --version` format, `sw_vers`) |
| C20 | `./install.sh --dry-run --with-eq-container`, then the same with `--setup-container` | `ok  container CLI 1.5.0 at /usr/local/bin/container (pinned 1.5.0)`; with the service stopped, `would: Step: start the container service` and `(needs consent: ...)`, with `--setup-container` `(consent: --start-container-service)`; nothing changes (`container system status` is unchanged afterwards) | install.sh 10b dry run, `setup.sh` dry run |
| C21 | `container system stop`, then `./install.sh --with-eq-container` and answer `step`, then `no`; run it again and answer `step`, then `yes` (then `no` at the build question if one appears) | the first run lists the steps and the service stays stopped (`! not started: the container service (no consent)`); the second prints the step in full, runs `container system start --enable-kernel-install` and `container system status` answers. Neither run asks for `y`: only `all`, `step`, `yes` count. `./install.sh --yes --with-eq-container` asks nothing and starts nothing. With `no` at the build question the run ends at exit 10 (build not consented); with `yes`, until the busybox/jq pins land (C14-C17), the image step ends at exit 13 | `setup.sh` consent, start_svc |
| C22 | optional, system-wide: `container system stop; /usr/local/bin/uninstall-container.sh -k` (keeps your container data), then `./install.sh --with-eq-container` and answer `all` (or pass `--install-container --start-container-service`) | in this order: `1. download https://github.com/...`, `2. size 118045087 and sha256 a24808cb…: equal to the pins`, `3. signature: ...`, sudo's own password prompt, `5. /usr/local/bin/container --version: 1.5.0; receipt com.apple.container-installer: 1.5.0`, then the service start. Then `~/.local/state/claude-agent-stack/eq-container/cli.env` says `EQ_CLI_INSTALLED_BY=stack`, and `./install.sh --restore` prints `container system stop; /usr/local/bin/uninstall-container.sh -k` and leaves the CLI in place | `setup.sh` fetch (GitHub's redirect to `release-assets.githubusercontent.com`), install_cli, cli_record; install.sh `--restore` |
| C23 | after C22 (or any start): `container system stop; container system start --enable-kernel-install; echo rc=$?`, then `container system stop; container system start --disable-kernel-install; echo rc=$?; container system status` | both rc=0, no question, and no new kernel download when one is already installed; the second start (what a failed upgrade runs to start the old service again) leaves the service running [unverified: the docs only say the flags answer the kernel question] | `setup.sh` start_svc, restart_old_svc |
