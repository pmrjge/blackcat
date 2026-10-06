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
| C1 | `container image inspect alpine:latest \| jq '.[0] \| {id, d: .configuration.descriptor.digest}'` | `d` is `sha256:<64 hex>` and `id` is the same 64 hex without `sha256:` (the 1.5.0 source, ImageResource.swift; the earlier `.configuration.index.digest` guess was wrong and is no longer read) | `lib/eq-container/eqc_json.py` DIGEST_PATHS (`digest`), `lib.sh` eqc_image_digest/eq_require_image, `dot-claude/bin/doctor.sh` eqc_digest, harness `INSPECT_DIGEST_PATHS`/`inspect_digest`/`require_image`. If neither: every digest check fails closed (images "not present") |
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

## Pins and real image builds (branch `eq-pins`, 2026-10-06)

The agent pinned bash and perl from the downloaded base-image layer. busybox (`BUSYBOX_SHA256`) and jq still hold placeholders:
snapshot.debian.org is outside the agent's sandbox. Run these from the repository root in a normal terminal, in order. C14 needs
curl, gpgv, xz and ar (`brew install gnupg xz`; `ar` comes with the Xcode command line tools) and no container. C15-C17 need
`container system start` and download several GB. Nothing here pushes, and the builds write only `~/.local/state/claude-agent-stack/eq-container`.

| # | command | confirms when | code that depends on it |
|---|---|---|---|
| C14 | `bash lib/eq-container/distro-pins.sh; echo rc=$?` | rc=13. Four `TOOL` lines. bash `5.2.37-2+b10 ccbd5106…413a` and perl `5.40.1-6+deb13u1 b37d5994…f3bb` say `pinned: same`. busybox and jq say `pinned: PLACEHOLDER`, with the versions the snapshot pool lists, `1:1.37.0-6+b9` and `1.7.1-6+deb13u3` (unverified). `gpgv=OK` appears. Give the whole output to the pins owner. Its busybox and jq values go into TOOLS.toml (version, sha256, checksum_source) and into `BUSYBOX_SHA256` (PINS, `ARG` in Dockerfile.minimal); then the same command prints rc=0 and `DISTRO-PINS: OK`. A `FAILED:` line: give it to the pins owner, and do not pin anything | `TOOLS.toml` bash/perl/jq/busybox, `PINS` `BUSYBOX_SHA256`/`BASE_LAYER_*`, `distro-pins.sh` |
| C15 | `bash lib/eq-container/build.sh --resolve-tools` | the builder's own apt, which checks the signed index inside the base image, prints `TOOL busybox …`, `TOOL bash …`, `TOOL perl …` and `TOOL jq …` lines equal to C14's four (it also prints `cc` and `ghc-link-libs`: not pinned here). Do not pass `--write-pin` | `Dockerfile.minimal` `tools-report`, `Dockerfile.toolchains` `tc-tools-report` |
| C16 | after the pins land: `bash lib/eq-container/verify-tools.sh --manifest --profiles core; bash lib/eq-container/build.sh --profiles core --yes; echo rc=$?` | `TOOLS: manifest OK`, then rc=0, and min-both and min-py are built. mkrootfs.sh's lock step refuses an installed bash, perl, jq or busybox that does not hash to its pin, so a wrong pin is a failed build (rc 12), never a wrong image | `minimal/mkrootfs.sh` TOOLS.lock, `Dockerfile.minimal` busybox stage |
| C17 | `bash lib/eq-container/verify-tools.sh --images --deep --inspect --smoke --profiles core; bash lib/eq-container/eq-container.sh install` | `TOOLS: images OK`, `inspect OK`, `smoke OK`; the install ends with status ok and the probe passes. Then `./install.sh --with-eq-container` reaches step 10c and does not skip the WALL | `verify-tools.sh`, `probe.sh`, `install.sh` 10b/10c |

Already verified by you (HANDOFF_STATE §7): `container run --help` flags; `--network none` (spike); `image inspect` top-level
keys `configuration`, `id`, `variants`.

Read in the CLI source at tag 1.5.0 during the R3 review (source, not behaviour; the rows above still need running):
C1's shape (Sources/ContainerResource/Image/ImageResource.swift, checked by the builder); `--mount` splits each key=value at
`=` and drops empty pieces (Sources/Services/ContainerAPIService/Client/Parser.swift, checked by the builder: so lib.sh,
the harness and install.sh refuse `=` in mounted paths, as they already refused `,`); C3's row shape (ManagedContainer.swift), `--ulimit
nproc` accepted and tmpfs mounts applied before binds (Utility.swift): security-auditor's reading, not re-checked.
