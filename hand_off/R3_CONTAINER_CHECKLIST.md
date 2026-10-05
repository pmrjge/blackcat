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
| C1 | `container image inspect alpine:latest \| jq '.[0] \| {id, idx: .configuration.index.digest}'` | at least one of `id`/`idx` is `sha256:<64 hex>`; if both are, they are equal | `lib/eq-container/eqc_json.py` DIGEST_PATHS (`digest`), `lib.sh` eqc_image_digest/eq_require_image, `dot-claude/bin/doctor.sh` eqc_digest, harness `INSPECT_DIGEST_PATHS`/`inspect_digest`/`require_image`. If neither: every digest check fails closed (images "not present") |
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

Already verified by you (HANDOFF_STATE §7): `container run --help` flags; `--network none` (spike); `image inspect` top-level
keys `configuration`, `id`, `variants`.
