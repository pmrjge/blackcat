# Docker isolation backend: user runbook

Everything here is run by you in a normal terminal (the agent sandbox cannot reach the Docker socket). Nothing was run
by the agent: no image was built or pulled, no container started. Statements about Docker behaviour are UNVERIFIED until
the step that exercises them passes.

Should an LLM replace the 218 reference-proof re-verification? No. Lean's kernel is the verifier, and the re-verification
is a scripted compute run (`reverify.sh`): about an hour of unattended wall time, no model involved.

Layout (`.../.claude-work/equilibrium/isolation/`): `Dockerfile`, `project/` (the host's lakefile.toml, lake-manifest.json,
lean-toolchain, StackMathlib sources; `project/SHA256SUMS`), `lib.sh`, `build.sh`, `spike.sh`, `probe.sh` + `probe_inner.sh`,
`reverify.sh`. Defaults for your daemon (16 CPUs, 253 GiB, cgroup v2, runc, seccomp default): `--cpus 2 --memory 8g
--memory-swap 8g --pids-limit 512 --user 10001:10001 --tmpfs /tmp:rw,nosuid,nodev,exec,size=2g`, overridable by `EQ_CPUS`,
`EQ_MEMORY`, `EQ_PIDS`, `EQ_USER`, `EQ_TMPFS_OPTS`, `EQ_JOBS`.

## Steps, in order

1. `cd equilibrium/isolation`
2. `docker info` (you did: Docker Desktop 29.8.1, aarch64, daemon up). If `Server:` is missing: `docker context use desktop-linux`.
   Check Settings > Resources: the virtual disk limit must leave >= 40 GB free (`docker system df` shows current use).
3. Optional base-digest check: `docker buildx imagetools inspect debian:trixie-slim` and compare the top-level `Digest:` with
   `ARG BASE_IMAGE` in the Dockerfile. The pinned digest was copied from docker-library/repo-info (debian:trixie-slim built
   2026-09-18), not read from the registry; `build.sh` verifies it resolves and has linux/arm64, and stops if not. A newer
   tag digest is not an error: the older digest stays pullable; re-pin only if you want the newer base.
4. `./build.sh` (10-40 min; network: github.com, snapshot.debian.org, the Mathlib cache host; goes through Docker Desktop's
   proxy http.docker.internal:3128, unverified for BuildKit: if downloads fail with proxy/TLS errors, pass the proxy
   with `docker buildx build --build-arg HTTPS_PROXY=...` by editing build.sh, and `./build.sh --no-snapshot` if
   snapshot.debian.org is unreachable). It prints the **image ID** and the in-image provenance (Lean, uv, Python, Mathlib
   rev, olean file count and `olean_tree_sha256`) and writes `.image.env`; every later script refuses a different image.
5. `./spike.sh` (about 3-6 min). Expect all gating rows PASS; INFO rows: whether host macOS oleans load in Linux Lean
   (expected NO or irrelevant: the image's own Mathlib is used either way), whether the olean trees are byte-identical,
   whether the fixture checker equals `items/PF/check_lean.sh`. It also prints the mean seconds per check: use it to
   re-estimate step 7. `/work` is a capped tmpfs (default 1 GiB, `EQ_WORK_TMPFS`) that the container fills with
   `cp -R` from a read-only mount of the check copy at `/eqsrc/work` (review finding F4), so `/work` no longer depends
   on the host uid: a FAIL at that copy step means the cap is too small for the check or the image has no `/bin/sh`/`cp`.
   Lake failing read-only: see Unverified.
6. `./probe.sh` (about 2 min). Every row must PASS before the backend is frozen.
7. `caffeinate -i ./reverify.sh --only PF-DEV1,PF-0001 --jobs 2 --stages pf` (trial, ~2 min), then the real run:
   `caffeinate -i ./reverify.sh` (defaults: 8 jobs, mode `oracle`, all stages). It is resumable: after Ctrl-C, a Docker
   restart or a reboot, run the same command; finished items are kept in `reverify-out/pf/`. Results: `reverify-out/reverify.tsv`
   (per item: scores, seconds, match against `items/PF/oracle/build/final_check.tsv`), `stages.tsv`, `summary.txt`, `logs/`.
   Exit 0 and `REVERIFY: PASS` means 218/218 references score 1, 218/218 wrong answers score 0, all matching the host
   baseline, and the CP/CR/ES selftests, the CP/CR `prove_pool.py` proofs and the PF dev selftest pass in the container.
   `--mode both` also runs the fixtures' shipped check scripts (the public check a member sees); add it if the pool owner
   changes fixtures again.
8. Freeze: record the image ID, the `olean_tree_sha256`, the backend (`docker`) and the limits in CONFIG.txt / `flags.json`
   before any paid run (`eq_harness.py flags --docker-image CLASS=<id>`, see RUNBOOK_MINIMAL.md section 8). `isolate()` is
   wired into `eq_harness.py` (it was a separate step when this file was first written); `isolation-probe` runs `probe.sh`
   with the images of `flags.json`.

## Time estimate (UNVERIFIED until step 5/7 measure it)

- Per check ~25 s (README: four Lean runs) + ~1 s container start; the wrong answer fails at compile time or at the
  verifier, so it is not slower. Per item (ref + wrong) ~50 s at 2 CPUs. 436 checks is about 3.0 h serial.
- At 8 parallel jobs x 2 CPUs (= the 16 CPUs of the VM): about 25-40 min for the PF stage (first checks are cold, memory
  bandwidth contention). More jobs than CPUs/2 does not help. Memory: 8 jobs x 8 GiB caps = 64 GiB of 253 GiB; real use
  is lower (the ~2 GB of Mathlib oleans are mmap'd, shared in the VM page cache).
- Extra stages: CP/CR/ES selftests a few minutes in total, the two `prove_pool.py` runs ~5-15 min, the PF dev selftest
  (39 sequential checks) ~15 min, run next to the PF stage. Total unattended wall time ~45-70 min. Image build adds
  10-40 min once. Your active time is about 15 minutes of commands.

## Disk (UNVERIFIED estimates)

Image ~8-12 GB (toolchain 2.7 GB, Mathlib + packages with their git history, oleans 1.9 GB; the build stages' cache
needs about the same again during the build, peak ~25 GB; the cache download itself is not stored in the final image).
Per-run copies in `.state/work/` are a few MB each and deleted after each check (the work root and `.state/` are mode 0700).
`.state/reverify-out/` is a few MB.

## Rollback and cleanup

- Remove the image: `docker rmi eq-lean:4.34.1-arm64` then `docker builder prune` (frees the build cache); `rm -rf .state .image.env build.log build-metadata.json .base-inspect.txt`
  (`.state/` holds `work/`, `reverify-out/`, the image records `images/*.env` and the results; `./build.sh --uninstall` removes
  images and records together).
- Stray containers: `docker ps -a --filter label=eq-harness=1`; remove with `docker rm -f $(docker ps -aq --filter label=eq-harness=1)`.
- Nothing outside this directory and Docker's own storage is changed. The harness is untouched; `backend: none` remains the default.

## Security notes

- Never mount `/var/run/docker.sock` (or any socket); no script here does. Mounts per container: the fresh check copy
  (read-only at `/eqsrc/work`; `/work` itself is a tmpfs, mode 1777, capped at 1 GiB, filled by `cp -R` at start, so nothing
  the code under test writes reaches the host) and the pristine fixture (ro, `/fixture`); stages that run the pools' own
  selftests mount only `items/<CLS>` ro. `reverify.sh` PF checks and `spike.sh` mount nothing else (the olean test mounts the
  host `.lake` ro in its own container). Containers start from the image ID that `eq_require_image` verified against the
  build record (an image without a record is refused, exit 11, unless `EQ_ALLOW_UNRECORDED=1`).
- No `--env-file`, no `--privileged`, no `--network` other than `none`, `--pull never`: a run can never fetch an image. The
  only `-e` entries are the constants LANG, HOME, TMPDIR, UV_CACHE_DIR, UV_OFFLINE, UV_NO_CONFIG, UV_PYTHON_DOWNLOADS (the
  same set the harness passes); no host variable is ever forwarded (probe row `host_env_not_passed`). Container logs are
  bounded (`--log-opt max-size=1m max-file=1`).
- The check copy is made world-readable (`chmod a+rX`, never writable) under the 0700 work root and is mounted read-only; it
  is a throw-away copy and is deleted after the run. All containers share one Linux VM kernel: this is a stronger boundary
  than `sandbox-exec` but not a per-run VM.
- Pinning: base image by digest (see step 3), Lean tarball sha256 (verified against both GitHub's release digest and a
  local download, 2026-10-04), uv and CPython by sha256, Mathlib by the lake-manifest rev (= tag v4.34.1, checked), Debian
  packages by snapshot date. Not pinned: the Mathlib cache download is checked by lake against Mathlib's own hashes, not by
  us; hence the recorded `olean_tree_sha256`. The image is built locally from this Dockerfile; never pull a prebuilt
  `eq-lean` image from anywhere.
- `probe.sh` tries benign writes and connects only; it does not attack the Lean checker.

## Provenance of the pins (looked up 2026-10-04)

- Lean 4.34.1 linux_aarch64 sha256 fdb974c2cdb4627e090d5d4007b913e09d13c4868720fb5594e22808b3de9e37: GitHub API
  `repos/leanprover/lean4/releases/tags/v4.34.1` asset digest, and `shasum -a 256` of the downloaded 581,946,052-byte file (equal).
- uv 0.12.22 aarch64-unknown-linux-gnu sha256 6f66a14e...: github.com/astral-sh/uv release asset digest and its `.sha256` file.
- CPython 3.14.8+20261001 install_only_stripped sha256 4395ae16...: python-build-standalone release 20261001 `SHA256SUMS`;
  the same version/tag is what uv 0.12.22 resolves for linux-aarch64-gnu, and the host's `uv run --no-project python` is 3.14.8.
  No pool pins a Python version (`requires-python >=3.10`/`>=3.11` only); 3.14.8 mirrors the host default.
- Base debian:trixie-slim index sha256 a99cfc51...: docker-library/repo-info (see step 3). Registry not reachable by the agent.

## Unverified (needs your daemon)

- That the Dockerfile builds at all (no daemon here; shellcheck and `bash -n` pass on the scripts, hadolint is not installed).
- That `lake exe cache get` completes inside the build, the size of the cache download, and that Lake's `lake env` works as
  non-root on a read-only root filesystem (`check_lean.sh` calls it unchanged). Spike row "lake env (non-root, read-only root)".
- That the non-root user can read the read-only bind mount at `/eqsrc/work` and write the tmpfs `/work` (spike/probe rows
  `work_writable`, `work_is_tmpfs`, `work_size_capped`), that `--tmpfs ...exec` is needed
  (try `EQ_TMPFS_OPTS=rw,nosuid,nodev,noexec,size=2g` and re-run the spike), and that Lean tolerates `pids-limit 512` with
  16 visible cores (it starts one thread per core).
- Whether snapshot.debian.org is reachable from BuildKit through the Docker Desktop proxy.
- Wall-clock per check, hence every time estimate above; PF verdicts matching the host baseline (that is what step 7 decides).
- `docker run` accepting the exact flag set on Docker Desktop 29.8.1 (all are standard Docker flags).
- The `.image.env` ID check assumes `docker image inspect --format '{{.Id}}'` is stable for the containerd image store.

## Notes from this staging

- The PF pool was being edited while this was written: fixtures and `pool.sha256` were re-synced at 22:16 to the current
  `check_lean.sh`/`EqVerify.lean` (before that the fixtures carried older copies, so a member's public check differed from
  the oracle's). `reverify.sh` preflight prints how many fixtures still differ; `final_check.tsv` (22:10) post-dates the checker.
- `items/CP/pool.sha256` reports `prove_pool.py: FAILED` (that script was edited after the hash): the preflight prints
  MISMATCH for CP. It does not gate the run; the pool owner should re-hash.
