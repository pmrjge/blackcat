# Minimal image runbook: choose the smallest lean/python image that gives the same verdicts

Everything below is run by you in a normal terminal (Terminal.app or iTerm), not in an agent sandbox (the sandbox cannot reach the
Docker socket). Docker Desktop must be running (`docker info` shows `Server:`). Nothing in this file was run by the agent that wrote it:
no image was built or pulled, no container started. Every size, time and speed-up below is an ESTIMATE until a step of this runbook prints
the measured value; the scripts print only values they measured themselves, on your machine. Statements about Docker behaviour are
UNVERIFIED until the step that exercises them passes.

Every command block starts with the same `cd`, so each can be pasted alone. State (records, results, scratch copies, logs) is under
`isolation/.state/` (mode 0700); the pools are `../items` (`EQ_ITEMS`).

## 0. State of play and the provisional recommendation

Provisional (static reasoning only, nothing measured): FROM-scratch images with an `ldd`-resolved root filesystem:
`eq-lean-min` (PF checks: Lean + Mathlib module files + bash + perl + busybox + a lake shim), `eq-py-min` (CP/CR/ES: CPython 3.14.8 + uv + jq + bash + busybox),
`eq-min` (both, used only by the PF dev selftest of `reverify.sh`), and the full Debian-slim `eq-lean` as baseline and fallback.
Distroless is rejected on static grounds: its base adds only glibc, libstdc++, libgcc, tzdata, ca-certificates and `/etc` files, supplies no bash, perl,
busybox, jq, python or uv, `items/PF/check_lean.sh` is hash-frozen (`pool.sha256`) and needs bash and perl, and the distroless python image has no uv.
It is still built as a measurement candidate (section 4) because the cost is one more build; skip it if you accept the static argument.
Bytes are dominated by Mathlib's `.olean`/`.olean.private` files (the predecessor measured on the host: Mathlib `build/lib/lean` 6400 MB, toolchain `lib/lean`
2673 MB; not re-measured here), so the KEEP PROFILE decides the size, not the base image: `conservative` (olean, olean.private, olean.server, ir, ir.sig),
`noprivate` (drops `.olean.private`), `slim` (olean, ir, ir.sig). Which profile still gives identical verdicts is decided by section 5 (what the checks read)
and section 9 (the full re-verification), never assumed.

Unverified until a step passes: that any Dockerfile here builds; that the scratch images start; that Lean in the scratch rootfs loads Mathlib; the size and
cold-proof-time differences between candidates; that `docker run <image-id>` accepts an image ID on your containerd image store.

## 1. Baseline: rebuild and record the full image (once)

The Dockerfiles gained the mount point `/eqsrc/work` and the scripts now refuse an image that no build record covers (exit 11), so the baseline needs a record. The
first image (`eq-lean:4.34.1-arm64`, ID in `.image.env`) is still accepted through that legacy file, but rebuild it so spike/probe also prove the new mount point
exists. Estimate: minutes when BuildKit's cache holds the earlier stages, up to the 10-40 min of a cold build (RUNBOOK.md step 4). Network: github.com, snapshot.debian.org, the Mathlib cache host.

```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
bash build.sh --yes
```

## 2. Resolve and write the busybox pin

`PINS` has `BUSYBOX_SHA256=UNSET` on purpose (the registries were unreachable for the agent). This builds the diagnostic stage, prints the sha256 of the `busybox-static`
binary from the pinned Debian snapshot and, with `--write-pin`, writes it into `PINS` and the `ARG` of `Dockerfile.minimal` (trust on first use: review the printed
package version, then keep the change). Estimate: a few minutes.

```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
bash build.sh --resolve-busybox --write-pin
```
```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
grep -n '^BUSYBOX_SHA256=' PINS; grep -n '^ARG BUSYBOX_SHA256=' Dockerfile.minimal
```
The two values must be equal 64-hex strings (build.sh refuses to build when they differ or either is a placeholder: exit 13).

## 3. Build the FROM-scratch set

Builds `eq-lean-min`, `eq-py-min`, `eq-min` (conservative keep profile). Each image's `mkrootfs.sh` fails the build on an unresolved library, on a different olean tree
hash than the full image, on a missing `/bin/sh` or a failing `cp -R`. Estimate: 10-40 min cold; the first stages are shared with section 1's cache.

```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
bash build-minimal.sh scratch --yes
```

## 4. Optional: the distroless candidate

Skip unless you want the measurement. Look up the digest (read-only), then put it in `PINS` (`DISTROLESS_BASE=gcr.io/distroless/cc-debian13@sha256:<digest>`) and in the first
`ARG DISTROLESS_BASE=` line of `Dockerfile.distroless`, and note the date and source next to it in `PINS`; `bash build.sh --check --set dl` compares the two.

```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
docker buildx imagetools inspect gcr.io/distroless/cc-debian13:nonroot
```
```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
bash build-minimal.sh distroless --yes
```
UNVERIFIED: that `COPY --from=rootfs / /` over the distroless base's own `/bin` and `/lib` works; if it stops there, drop this candidate.

## 5. What do the checks read? (decides which keep profiles are worth building)

Runs the trusted reference and wrong answers of three PF items (the first, the 100th and the last non-dev item) under `strace -f` in the FULL image, as root, with default capabilities and a
network (apt installs `strace`; the snapshot host must be reachable). It is a diagnostic, not an isolation test. Output: `.state/trace/summary.txt` (files read versus present, per
extension) and `opened.txt`. Coverage caveat: a trace shows what THESE answers read; `.ir` files are read lazily, other tactics may read more. Estimate: 5-10 min.

```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
bash trace-reads.sh
```
Then build the profiles the trace allows. If `.olean.private` shows 0 files read, build `noprivate`; if `.olean.server` and `.ir.sig` are also unread, `slim` is plausible. Each build adds
its own records (`min-lean-noprivate`, ...) next to the default ones and its own tags (`...-noprivate`, `...-slim`); `eq-py-min` is unaffected.

```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
bash build-minimal.sh scratch --keep-profile noprivate --yes
```
```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
bash build-minimal.sh scratch --keep-profile slim --yes
```

## 6. Spike and probe, per candidate

`spike.sh` (does the image work under the hardening flags: Lean imports Mathlib, `lake env`, the PF reference proof scores 1 and the wrong answer 0, python/uv run) and `probe.sh` (network,
mounts, planted secrets, limits, the `/work` size cap, kill path) write `results/spike.<tag>.env` and `results/probe.<tag>.env`, which section 7 reads. Name the python image next to the lean one so the
python checks run too (`EQ_IMAGE` alone names a lean-only candidate). Estimates: spike 3-6 min, probe 2-3 min per image (RUNBOOK.md steps 5-6). Every row must PASS.
Baseline first (it also proves the new `/eqsrc/work` design on the Debian image):

```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
bash spike.sh
```
```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
bash probe.sh
```
FROM-scratch conservative (probe.sh probes the lean image and then the python image):

```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
EQ_IMAGE=eq-lean-min:4.34.1-arm64 EQ_IMAGE_PY=eq-py-min:4.34.1-arm64 bash spike.sh
```
```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
EQ_IMAGE=eq-lean-min:4.34.1-arm64 EQ_IMAGE_PY=eq-py-min:4.34.1-arm64 bash probe.sh
```
Keep-profile candidates (only those built in section 5):

```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
EQ_IMAGE=eq-lean-min:4.34.1-arm64-noprivate EQ_IMAGE_PY=eq-py-min:4.34.1-arm64 bash spike.sh
```
```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
EQ_IMAGE=eq-lean-min:4.34.1-arm64-noprivate EQ_IMAGE_PY=eq-py-min:4.34.1-arm64 bash probe.sh
```
```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
EQ_IMAGE=eq-lean-min:4.34.1-arm64-slim EQ_IMAGE_PY=eq-py-min:4.34.1-arm64 bash spike.sh
```
```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
EQ_IMAGE=eq-lean-min:4.34.1-arm64-slim EQ_IMAGE_PY=eq-py-min:4.34.1-arm64 bash probe.sh
```
Distroless (only if built in section 4):

```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
EQ_IMAGE=eq-lean-dl:4.34.1-arm64 EQ_IMAGE_PY=eq-py-min:4.34.1-arm64 bash spike.sh
```
```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
EQ_IMAGE=eq-lean-dl:4.34.1-arm64 EQ_IMAGE_PY=eq-py-min:4.34.1-arm64 bash probe.sh
```
A spike FAIL in `import Mathlib` for a keep profile means a module file the check needs was dropped: that profile is out. On a FAIL at the `/work` copy step, see RUNBOOK.md step 5.

## 7. Compare the candidates

Defaults: the baseline `eq-lean` (first), `lean-min` and `lean-dl` when present; `--cand LABEL=TAG` adds the keep-profile images (a label starting `scratch-` counts as FROM scratch in the rule).
It times the PF check of the PF-0001 reference proof (3 rounds, candidates interleaved; round 1 is "cold" for that image: restart Docker Desktop first if you want a cold VM page cache), checks the verdicts of
PF-0001 and PF-DEV1 (reference 1, wrong answer 0, identical to the baseline), inventories every image (`docker create` + `docker export`, nothing is started), compares the olean tree hash and the CP-0001 checks of
`eq-py-min`, and reads the spike/probe results of section 6. Estimate: 15-30 min with 4-5 candidates (dominated by the timing rounds and the exports).

```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
bash compare-images.sh --cand scratch-noprivate=eq-lean-min:4.34.1-arm64-noprivate --cand scratch-slim=eq-lean-min:4.34.1-arm64-slim --both-min eq-min:4.34.1-arm64
```
(Leave out the `--cand` options for profiles you did not build. `--runs N`, `--tol PCT`, `--items "PF-0001 PF-DEV1"`, `--time-item`, `--skip-inventory`, `--skip-cp` exist; `-h` prints them.)

## 8. How to read the table

Columns: `insp_MB` (`docker image inspect .Size`), `exp_MB` (sum of regular-file sizes of the exported root filesystem; the number the rule uses), files, links, `suid` (setuid/setgid files), shells/interp and pkgmgr
(what the image ships), `build_s`, `PFgate` (SAME = every smoke item gave the baseline's verdict and detail; DIFF = right verdict, different detail; FAIL = wrong verdict; n/a = no pools), `olean` (tree hash SAME as the
baseline), `cold_ms` (round 1), `med_ms` (median of the rounds), `time%` and `size%` (relative to the baseline), `spike`, `probe` (recorded results, `n/a` = not run).

The rule is fixed in the header of `compare-images.sh` before anything is measured:
- A candidate is ELIGIBLE only if PFgate is SAME, the olean hash is SAME, `med_ms` is at most the baseline median times (1 + 10%) (the 10% tolerance is `--tol` / `EQ_COMPARE_TOL`; wall-clock noise at 2 CPUs is the reason it is not 0),
  and `spike` and `probe` both say PASS. A missing measurement makes it INCOMPLETE (named in the output), never eligible.
- PICK = the eligible candidate with the fewest exported bytes; an eligible FROM-scratch candidate (`lean-min`, `scratch-*`) within 5% of that size wins instead (fewer unpinned inputs, no registry digest, no mixed libc).
- No eligible candidate: keep the baseline `eq-lean` (`PICK: none`, exit 1). `COMPARE: PICK <label>` (exit 0) names the winner.
- ONE-vs-TWO: two images (a separate, smaller attack surface per class) unless `eq-min` is more than 25% smaller than `eq-lean-min` + `eq-py-min`.
- `py-min CP rows: all SAME` is required before `eq-py-min` serves CP/CR; any DIFF there disqualifies it whatever the PF table says.
The table is the evidence; the machine pick is only the rule applied. You may override it, but record why next to the freeze (section 10). A PF verdict that differs from the baseline (`NOTE:` line) is a defect to understand, not a tolerance question.

## 9. Re-verify the pick against all 218 references

Trial first (two items, about 2 min estimated), with the picked lean image (replace the tag by the label's tag: `eq-lean-min:4.34.1-arm64`, `...-noprivate`, `...-slim`, or `eq-lean:4.34.1-arm64`). `EQ_IMAGE` alone names one image, so the stages default to `pf` only
and `--stages pf` just states it.

```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
EQ_IMAGE=eq-lean-min:4.34.1-arm64 caffeinate -i bash reverify.sh --only PF-DEV1,PF-0001 --stages pf
```
Then the full run (resumable: after Ctrl-C, a Docker restart or a reboot run the same command; finished items are kept in `.state/reverify-out/pf/`). The lean image serves PF, the python image the CP/CR/ES stages and the `prove_pool.py` runs,
and the `both` image the PF dev selftest (39 sequential checks); for a keep-profile pick use the matching `eq-min:...-<profile>` tag if you built it (otherwise the conservative `eq-min`; it only runs the dev selftest). Estimate: 45-70 min unattended
(RUNBOOK.md, "Time estimate": unverified until the trial prints seconds per check).

```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
EQ_IMAGE=eq-lean-min:4.34.1-arm64 EQ_IMAGE_PY=eq-py-min:4.34.1-arm64 EQ_IMAGE_BOTH=eq-min:4.34.1-arm64 caffeinate -i bash reverify.sh
```
Success: `REVERIFY: PASS`, exit 0 (218/218 references 1, 218/218 wrong answers 0, all equal to `items/PF/oracle/build/final_check.tsv`, the CP/CR/ES selftests, the two `prove_pool.py` proofs and the PF dev selftest pass).
`REVERIFY: INCOMPLETE` (exit 3): run it again. `FAIL`: read `.state/reverify-out/summary.txt`; if the pick was a keep profile, fall back to the next more conservative one and repeat sections 6, 7 and 9 for it. The same command
with the baseline (`bash reverify.sh`, no variables) is what RUNBOOK.md step 7 describes; running it for the baseline too gives the control.

## 10. Freeze: image IDs into the harness flags, then the isolation probe

The harness takes image IDs (or `name@sha256:` digests), never tags. `image.env` lists them; refresh it for the pick (a run with nothing to build only rewrites the summary files). Conservative scratch pick:

```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
bash build.sh --set min --yes && grep '^EQ_DOCKER_IMAGE_' .state/image.env
```
Keep-profile pick (example `noprivate`; use the record name `min-lean-noprivate` or `min-lean-slim`):

```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
EQ_SELECT_LEAN=min-lean-noprivate bash build.sh --set min --keep-profile noprivate --yes && grep '^EQ_DOCKER_IMAGE_' .state/image.env
```
Baseline pick (no candidate eligible):

```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
EQ_SELECT_LEAN=full EQ_SELECT_PY=full bash build.sh --yes && grep '^EQ_DOCKER_IMAGE_' .state/image.env
```
Then, from the equilibrium directory (the parent of `isolation/`), write the flags with the three IDs printed above (`EQ_DOCKER_IMAGE_PF`, `_CP`, `_CR`; CP and CR use the same python image). This rewrites `harness/flags.json`
(its `docker_images`) and takes `allowed_tools` from the pools; do it only once the pools are final. Alternative with the same effect: `--docker-images-env isolation/.state/image.env` instead of the three `--docker-image` options.

```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium
uv run --script harness/eq_harness.py flags --items items --docker-image PF=<EQ_DOCKER_IMAGE_PF> --docker-image CP=<EQ_DOCKER_IMAGE_CP> --docker-image CR=<EQ_DOCKER_IMAGE_CR>
```
```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium
uv run --script harness/eq_harness.py isolation-probe
```
`isolation-probe` builds its containers with the harness's own `isolate()` argv (so it probes what the checks really run with) and runs `isolation/probe.sh` with `EQ_IMAGE` = the PF image and `EQ_IMAGE_PY` = the CP image; if CR differs
from CP, run `EQ_PROBE_EXTRA_IMAGES=<CR id> bash isolation/probe.sh` once as well. Exit 0 only if every row passes. Then record the chosen image IDs, the `olean_tree_sha256` (`.state/images/<record>.env`), the limits and the
compare table (`.state/compare/`) in CONFIG.txt before any paid run, together with the reason for any override of the machine pick.

## 11. Rollback and cleanup

- Remove every image and record this runbook made: `bash build.sh --set all --uninstall --yes` (also the keep-profile records), then `docker builder prune` to free the build cache (it prunes ALL unused cache of the current builder).
- Scratch: `rm -rf .state` removes records, results, compare and trace output; `.image.env`, `build.log`, `build-metadata.json` are the first build's leftovers.
- The harness is untouched except `harness/flags.json` in section 10; `backend: none`/`off` stays available there.
- Stray containers: `docker ps -a --filter label=eq-harness=1`; remove one by name with `docker rm -f <name>` (do not remove containers of a run that is still going).

## 12. Tools manifest: resolve the distro-package pins (once, before the first profile build)

`TOOLS.toml` is the allowlist of every tool that may exist in an image (INSTALLER_SPEC.md section 12). The extension toolchains are pinned from upstream checksum files read on 2026-10-05 (`../../eq-toolchains/TOOLCHAINS.md`,
no binary was downloaded by that pass, so the first build verifies each hash: a mismatch stops the build). The four distro-package tools of the check images (busybox, bash, perl, jq) cannot be pinned without a build: their `version` and
`sha256` are `PLACEHOLDER` (trust on first use). This builds the diagnostic stage of `Dockerfile.minimal` on the pinned Debian snapshot, prints one `TOOL name version sha256` line per tool and, with `--write-pin`, writes them into
`TOOLS.toml` (and `BUSYBOX_SHA256` into `PINS` and `Dockerfile.minimal`; it replaces section 2's `--resolve-busybox`). Review the printed package versions, then keep the change. Estimate: a few minutes.

```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
bash build.sh --resolve-tools --write-pin
```
```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
bash verify-tools.sh --manifest --profiles core
```
Expected: `TOOLS: manifest OK (images: min-both min-py)`. Still pending after this step, by design (nothing is invented): `scala3` (profile `jvm`: no Scala 3 distribution url or checksum was read; pending your Scala decision) and `mongosh`
(profile `mongo`: not covered by the facts file). `bash verify-tools.sh --manifest --profiles all --allow-placeholder` lists every pending value without failing.

## 13. Verify the tools manifest and the images built from it

`verify-tools.sh` never builds and never starts anything except in `--smoke`. `--manifest` (default) checks structure, class and profile allowlists, https-only urls, in-repo files and recipes against their sha256, and PINS agreement. `--images` compares, per image of the
selected profiles, the build record, the image ID, the label `eq.tools.sha256` (hash of the current manifest entries: an edited entry makes an image STALE) and `/opt/eq/TOOLS.lock` (read with `docker create` + `docker cp`; every listed tool, no undeclared one);
`--deep` also re-hashes every installed tool file from outside the container (so a tampered in-image `sha256sum` cannot lie). `--inspect`: unprivileged user, no EXPOSE/VOLUME/ENTRYPOINT/HEALTHCHECK, no secret-like ENV name, PATH inside /opt and /usr.
`--smoke`: runs each tool's smoke argv (`node --version`, ...) in its image under the hardened flags (network none, read-only, capabilities dropped). Exit 0 ok, 2 invalid manifest, 10 no docker, 11 an image is missing/stale/mismatching, 13 a pending value.
Run it after section 14 (the images must exist):

```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
bash verify-tools.sh --images --deep --inspect --smoke --profiles core
```
```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
bash verify-tools.sh --images --deep --inspect --smoke --profiles node,rust,go,julia,haskell,jvm,db
```
Add `mongo` to the list only if you decided to accept the SSPL (INSTALLER_SPEC.md 12.5). A STALE row means the manifest changed after the build: rebuild that profile (section 14). UNVERIFIED until it passes: that the scripts' `docker create`/`docker cp` calls work on your
containerd image store, that every smoke argv exits 0 (the Scala one, `java -cp /opt/scala3/lib/* ...`, uses a main class name that was not looked up), and that every ELF in each image resolves its libraries (`mkrootfs-tc.sh` fails the build otherwise, naming the library).

## 14. Build the profiles (core is the default; every other profile is opt-in)

`core` = the minimum the item classes PF, CP and CR need: `min-both` (Lean + Mathlib + uv + python + bash + perl + jq + busybox + the lake shim; the PF oracle runs `uv run --script oracle.py` inside the PF image) and `min-py` (uv + python + bash + jq + busybox).
ES, RS, DS and OE run no model-written code: their oracles run on the host, so they have no image. `all` = every profile that is not marked explicit (everything except `mongo` and `candidates`). A build stops with exit 13 naming the placeholder while a selected
tool is unpinned. Estimates (not measured): core 10-40 min cold (the Mathlib cache dominates), each extension image a few minutes, `tc-haskell`, `tc-pg` and `tc-jvm` the longest because of a source build or a large archive. The records print the measured values:
`grep -H 'EQ_IMAGE_BYTES\|EQ_BUILD_SECONDS' .state/images/*.env`.

```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
bash build.sh --profiles core --dry-run
```
```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
bash build.sh --profiles core --yes
```
```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
bash build.sh --profiles core,node,rust,go,julia,haskell,db --yes
```
```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
grep -H 'EQ_IMAGE_BYTES\|EQ_BUILD_SECONDS\|EQ_TOOLS_SHA256' .state/images/*.env
```
`jvm` needs the Scala 3 values (section 12 lists what is pending) and `mongo` your SSPL decision plus the `mongosh` entry; both stop with exit 13 until then. The images are built locally (nothing is pulled): the digests that are verified are the base image's (PINS), every tool archive's
sha256 (checked in the discarded builder stage, before extraction) and the built image's ID (recorded, rechecked before every run).

## 15. Spike and probe, per profile

The core images have a shell, so section 6's spike and probe apply to them; `probe.sh` now also runs the hooks of `probe.d/` (the tools-manifest rows, the internal-network proof, and the WALL tunnel probe when `probe.d/50-tunnel.sh` is present) and the new in-container rows
(`host_path_not_inherited`, `path_dirs_readonly`, `path_executables_allowlisted`, `tools_hash_verified`, `tools_mount_readonly`, `no_docker_socket`, `no_home_mount`, `no_default_route`). Every row must PASS.

```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
EQ_IMAGE=eq-min:4.34.1-arm64 EQ_IMAGE_PY=eq-py-min:4.34.1-arm64 bash spike.sh
```
```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
EQ_IMAGE=eq-min:4.34.1-arm64 EQ_IMAGE_PY=eq-py-min:4.34.1-arm64 bash probe.sh
```
The extension images (`eq-node:arm64`, `eq-rust:arm64`, `eq-go:arm64`, `eq-julia:arm64`, `eq-haskell:arm64`, `eq-jvm:arm64`, `eq-pg:arm64`, `eq-mongo:arm64`) have no shell by design, and `probe.sh`'s main container needs `bash`, so it is not run on them.
Their proofs are `verify-tools.sh --inspect --smoke --deep` (section 13) and the compose run of section 16 (read-only root, no network, dropped capabilities, the internal-only database network). Whether that is enough for a language a pool will one day use is part of the decision
that adds the class (a class that runs model-written code through `isolate()` needs `/bin/sh` and `cp` in its image, INSTALLER_SPEC.md 12.6 conflict C1).

## 16. Compose: validate, then one run

`compose.yaml` is the declarative front-end (read-only root, no network except the internal-only database network, capabilities dropped, limits, only the per-run work directory mounted read-only, no published port, tmpfs scratch, one service per image, profiles as in `TOOLS.toml`).
Always start it through `eq-compose.sh`: it verifies the manifest hashes and the image records first (`verify-tools.sh --images --deep`, exit 11 when an image is stale or tampered), fills the image references from the verified records, generates the database credential for the run
(held only in that process's environment), and removes the containers and the network when the run ends. `config` validates the compose files and starts nothing:

```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
bash eq-compose.sh config
```
```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
bash eq-compose.sh --profiles node,go,db config
```
One language run (the work directory must be an absolute plain directory under a path Docker Desktop shares, not a symlink and not `$HOME`; it is mounted read-only at `/work`):

```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
mkdir -p .state/work/compose-demo && printf 'console.log("hello from a read-only, network-less container")\n' > .state/work/compose-demo/hello.js
bash eq-compose.sh --profiles node --work "$PWD/.state/work/compose-demo" run node /opt/node/bin/node hello.js
```
The database check (PostgreSQL on the internal-only network; the script only opens TCP connections: the database by service name must answer, an outside address must not):

```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
mkdir -p .state/work/compose-db && printf 'import socket\nfor h, p in (("pg", 5432), ("1.1.1.1", 443)):\n    s = socket.socket(); s.settimeout(3)\n    try:\n        s.connect((h, p)); print(h, "REACHABLE")\n    except OSError as e:\n        print(h, "unreachable:", e)\n' > .state/work/compose-db/net.py
bash eq-compose.sh --profiles db --work "$PWD/.state/work/compose-db" run cp-db python3 net.py
```
Expected: `pg REACHABLE` and `1.1.1.1 unreachable`. UNVERIFIED until it prints that: that `docker compose config` accepts the files on your Compose version, that the `required: false` entries of `depends_on` are honoured, that `internal: true` leaves the service name resolvable, and that PostgreSQL starts as
`10002:10002` on the tmpfs (`tc/entry-pg.sh` is a first draft). With `--tunnel CHANNEL_DIR` (ONE WALL channel directory `c<32 hex>` opened for this call, mode 0700; never the tunnel root, which is refused) `compose.wall.yaml` adds the one WALL mount at `/eq/tunnel`; see `../../wall/INSTALLER_WALL.md`.

## 17. Rollback and cleanup of sections 12-16

```bash
cd /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium/isolation
bash eq-compose.sh --profiles all,mongo down; bash build.sh --profiles all,mongo --uninstall --yes
```
Images are removed with their records (`--prune-cache` also runs `docker builder prune`, which prunes ALL unused cache of the current builder). `rm -rf .state/work/compose-demo .state/work/compose-db` removes the demo directories. `git checkout TOOLS.toml PINS Dockerfile.minimal` (or your own diff review) undoes section 12's pins.

## What is estimated or unverified (summary)

| item | status |
|---|---|
| extension toolchain pins (node, rust, go, julia, ghc, cabal, jdk, postgresql, mongodb) | sha256 read from upstream checksum files on 2026-10-05, not downloaded; the first build verifies them |
| distro-package pins (busybox, bash, perl, jq), `scala3`, `mongosh` | `PLACEHOLDER` until section 12 / your decisions; never invented |
| archive layouts, prune lists, recipe flags, runtime library lists of the extension images | unverified until section 14 builds and section 13 passes |
| compiling inside `tc-rust` and `tc-haskell` | not possible without a linker driver in the image (conflict C6): the smoke tests only run `--version` |
| compose files against a real daemon, the database entry scripts | unverified until section 16 prints the expected lines |
| any build, start, spike, probe or reverify result | not run: unverified |
| image sizes, time per check, build times, step durations above | estimates (labelled where they appear); `compare-images.sh`, `spike.sh` and `reverify.sh` print the measured values |
| host sizes 6400 MB / 2673 MB | measured on the host by the predecessor, not re-measured |
| distroless rejection | static argument, not measured; the candidate exists to confirm it |
| `docker run` by image ID on the containerd image store; `COPY` of `/bin -> usr/bin` over the distroless base; in-container behaviour of `work_size_capped`, `eqsrc_mounted_ro`, `bin_sh_present` | unverified until section 6 passes |
| `BUSYBOX_SHA256`, `DISTROLESS_BASE` | placeholders until sections 2 and 4; never invented |
