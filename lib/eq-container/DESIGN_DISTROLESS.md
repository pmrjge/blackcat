# eq-container on distroless or scratch bases: design (no code)

Status: implemented on branch eq-distroless (2026-10-06); user decisions recorded in hand_off/HANDOFF_STATE.md §6; remaining user
steps D1-D6 (hand_off/R3_CONTAINER_CHECKLIST.md). The design below is from branch `eq-distroless-design` (from `main` 0781a15, which
already contains the `eq-pins` branch: `main` = `eq-pins` = 0781a15); when it was written nothing was built or run and no `container`
command was executed. Every line marked
**[unverified]** needs a real build or a user-run command. Line numbers are of this commit unless a path says otherwise; `EQ-T`
is the equilibrium working copy `M/.claude-work/worktrees/eq-t-1005/.claude-work/equilibrium` (git-ignored, read as found).

## 0. The instruction, and the record it changes

The user's current instruction: "I said I want distroless or scratch". It replaces the recorded decision
`hand_off/HANDOFF_STATE.md:188-189` ("Debian packages for bash/perl/jq/busybox; ... `cc` linker in the Rust/Haskell images").
The record, factually:

- `claude_info/HANDOFF_FULL.md` at 73eec41, §5 line 129: earlier sessions fixed "image rules X4 (binary-only final images)" and
  "Lean 4 + Mathlib image: the leanest that works, by comparison".
- Same file §6 item 2 (line 141) put the open question as "Debian-packaged bash/perl/jq/busybox vs pinned static binaries
  (provenance)"; HANDOFF_STATE §6 item 2 then records the Debian-package answer as a USER decision of 2026-10-05.
- What was built from it: the `core` final images are already `FROM scratch` (`Dockerfile.minimal:164,177,189`), and so is the
  toolchain base `eq-base` (`Dockerfile.toolchains:88`), but their content comes from Debian: an `ldd`-copied Debian glibc
  closure, bash and perl from the Debian base layer, busybox and jq from snapshot.debian.org, and Debian gcc/libc6-dev/libgmp-dev
  closures in the Rust and Haskell images. The `full` image (`Dockerfile:102-108`, `--set full`) is a Debian runtime with apt.

This design follows the current instruction: every final image is `scratch` or a Google distroless image pinned by digest; no
final image carries a distribution's shell, coreutils, interpreter, compiler or package manager (the only distribution files left
are the distroless base's own libraries and data, §2.1); nothing depends on apt, dpkg or snapshot.debian.org; and the Debian
package pins of `eq-pins` are superseded (§8). Where that cannot be done honestly (glibc-only toolchains, C linkers), §3 says so
and §10 asks.

## 1. What exists today

### 1.1 Images

| image (TOOLS.toml / lib.sh name) | Dockerfile:target | final base | contents | provenance of each part |
|---|---|---|---|---|
| `full` (`eq.invalid/eq-lean:4.34.1-arm64`) | `Dockerfile` (no target) | `debian:trixie-slim@a99cfc51` (`Dockerfile:19,102`) | the whole Debian runtime (dpkg, apt, coreutils, bash), apt `git jq perl` (`:104`), Lean, Mathlib, uv, Python | Debian snapshot + upstream archives |
| `min-both` (PF) | `Dockerfile.minimal:eq-min` | `scratch` (`:189`) | Lean + Mathlib module files (KEEP_EXTS), lake shim, uv, Python (pruned), bash, perl, busybox (43 applet links, `mkrootfs.sh:74`), jq, glibc/libstdc++ closure, passwd/group, mount points | Lean/uv/PBS upstream; bash+perl Debian base layer (`mkrootfs.sh:70-71`); busybox-static, jq Debian snapshot (`Dockerfile.minimal:111-125,135-138`); libraries `ldd`-copied from Debian (`mkrootfs.sh:46-56`) |
| `min-py` (CP, CR) | `Dockerfile.minimal:eq-py-min` | `scratch` (`:177`) | uv, Python, bash, busybox, jq, glibc closure | as above |
| `min-lean` (profile `candidates`, explicit) | `Dockerfile.minimal:eq-lean-min` | `scratch` (`:164`) | Lean + Mathlib, bash, perl, busybox, lake shim (no Python: unusable for the PF oracle) | as above |
| `eq-base` | `Dockerfile.toolchains:eq-base` | `scratch` (`:88`) | glibc, libm, libgcc_s, libstdc++, libnss_files, passwd/group (`tc/mkrootfs-tc.sh:48-67`) | Debian, `ldd`/`ldconfig` in the builder |
| `tc-node`, `tc-go`, `tc-julia`, `tc-jvm` | `Dockerfile.toolchains:eq-<x>` | `eq-base` | tool tree + extra libraries (`mkrootfs-tc.sh:101-104`) | upstream archive + Debian libraries |
| `tc-rust` | `:eq-rust` | `eq-base` | rust + tool `cc` (Debian gcc, libc6-dev closure) (`Dockerfile.toolchains:101`) | upstream + Debian packages |
| `tc-haskell` | `:eq-haskell` | `eq-base` | ghc, cabal, `cc`, `ghc-link-libs` (libgmp-dev, libffi-dev) (`:119-124`) | upstream + Debian packages |

Builder stages of all three Dockerfiles: `debian:trixie-slim@sha256:a99cfc51...` with apt reading
`snapshot.debian.org/archive/debian/20260918T000000Z` (`Dockerfile:22-31`, `Dockerfile.minimal:26-35`,
`Dockerfile.toolchains:27-35`). Profiles: `core` = `min-both` + `min-py` (`TOOLS.toml:527-530`), the others opt-in.

### 1.2 Who executes what inside a container (why each tool is there)

| # | caller | argv in the container | needs in the image |
|---|---|---|---|
| 1 | harness `isolate()` copy-in prefix, every call with a rw dir (checks, fact re-runs, member sandbox) — `EQ-T harness/eq_harness.py:1590,1895-1898`; same text in `lib.sh:154,196` | `/bin/sh -c COPY_IN eq-run SRC DST -- ARGV` | `/bin/sh` (absolute path), `cp` |
| 2 | PF public check (`items/PF/manifest.jsonl` `public_check`), run at `eq_harness.py:2796` | `bash check_lean.sh Answer.lean` | an executable named `bash` on PATH; `check_lean.sh` (hash-frozen, `items/PF/pool.sha256:5` = `e740de46...`, 219 identical copies) runs `perl -e <alarm wrapper>` (`check_lean.sh:44-53`), `lake env printenv LEAN_PATH` (`:56`, answered by `minimal/lake-shim`), `lean` (`:59-83`), `mktemp date head tail tr cp grep cut rm` |
| 3 | PF oracle, isolated (`oracle_isolated_classes` = PF, CP: `eq_harness.py:223`; argv `:3959`) | `uv run --script --quiet /in/pool/oracle.py ...` | uv, Python; `items/PF/oracle.py:115` runs `bash check_lean.sh` → row 2 |
| 4 | CP and CR public checks | `uv run --no-project python -m unittest discover -s tests -t . -q` | uv, Python |
| 5 | CP oracle, isolated (CR's oracle runs on the host) | `uv run --script oracle.py`; `items/CP/oracle.py:108` runs `sys.executable -m unittest` | uv, Python |
| 6 | mediator fact re-runs (`eq_harness.py:1974-1984`) | whatever argv a member ran | the same tool set the member had |
| 7 | sandboxed member execution (`member_exec` "sandbox", `eq_harness.py:2256-2347`) | arbitrary model argv | the image PATH IS the member's toolbox |
| 8 | harness `isolation-probe` (`eq_harness.py:3480-3491`), tunnel probe (`:3549`) | `bash -c <probe_inner.sh>`, `bash -c PROBE_IN`, `/bin/sh -c PROBE_FILL`, `/bin/sh -c <50-tunnel.sh>` | bash, sh, busybox applets |
| 9 | `probe.sh` (`:71,93,98-111,115-166`) + `probe_inner.sh` | `bash -c`, `/bin/sh -c` | `id awk grep find sha256sum timeout cut sed tr head ls env wc sort`, bash's `/dev/tcp` (`probe_inner.sh:76-85`), `ulimit -u` (`:91`), lake shim, lean, uv, python3 |
| 10 | `verify-tools.sh --smoke` (`:327-341`) | each tool's `smoke` argv | no shell |

Every use of `perl` in EQ-T `items/`, `harness/`, `wall/` (grep `\bperl\b`): the 219 copies of `check_lean.sh`, plus a name in
the WALL's interpreter deny list (`wall/eq_wall.py:95`, not an execution). Nothing else runs perl.
`jq`: TOOLS.toml role `selftest` (`:174`); the selftests that use it (`items/PF/selftest.sh:15,20,25`, DS, RS, OE) run on the host:
no `isolate()` call runs a selftest (grep `selftest` in `harness/eq_harness.py`, `harness/eq_check.sh`: no match), and the
harness's own `jq` call (`eq_harness.py:4198`) is a host subprocess. So jq has no in-container consumer today except row 7.

### 1.3 Where Debian enters today (all of it goes away)

1. Builder base + apt from snapshot.debian.org (three Dockerfiles, lines above) and the user-run `distro-pins.sh` chain
   (`PINS:16-27,43-49`; `hand_off/R3_CONTAINER_CHECKLIST.md` C14-C15).
2. Final-image files: the glibc/libstdc++/libgcc_s closure (`mkrootfs.sh:46-56`, `mkrootfs-tc.sh:56-61`); bash and perl
   (`mkrootfs.sh:70-71`); busybox-static and jq (`Dockerfile.minimal:111-115,135-138`, `mkrootfs.sh:134`); gcc + libc6-dev
   (+ libgmp-dev, libffi-dev) package closures (`tc/apt-closure.sh`, `mkrootfs-tc.sh:78-98`); dpkg queries for provenance
   (`mkrootfs.sh:145-148,186-190`).
3. The `full` image's entire runtime (`Dockerfile:102-108`) and its role as the fallback while pins are placeholders
   (`README.md:28-30`, `install.sh:3610`).

## 2. Base images, verified 2026-10-06

### 2.1 Distroless (the only distroless images considered: `-debian13`, tags `latest nonroot debug debug-nonroot`)

`gcr.io` is not on this sandbox's network allowlist, so the registry was read through the `r.jina.ai` reader. Method: fetch the
index by tag, re-serialise it (JSON, indent 2, trailing newline), hash it, then fetch the manifest BY THAT DIGEST: the registry
served it (a wrong digest returns `MANIFEST_UNKNOWN`, observed for a mis-serialised candidate). This proves internal consistency,
not authenticity (a proxy could fabricate both answers): the authoritative checks are the user's `cosign verify` (§9, D1) and the
builder, which verifies the digest when it pulls.

| image:tag (role) | index digest | linux/arm64 v8 manifest | how read |
|---|---|---|---|
| `gcr.io/distroless/cc-debian13:nonroot` (all glibc images) | `sha256:e792ab3d241a468a4fd7519ddbbebe66b49b5f365771716ea688ad40b6c6f1c2` | `sha256:2f0295ce228a23109ec1c8d38763bfe995b0dba7b3672f58d3a67ebfbc542fdc` (21 gzip layers, config `sha256:d52dcb5d...`) | tag + by-digest fetch; manifest fetched by digest |
| `gcr.io/distroless/static-debian13:nonroot` (optional, `tc-go`) | `sha256:e2e927ec666bae08560abb3c55d0659eceabb657f56b6782ab500a9fc7f555e3` | `sha256:dd804b6c91a33a478f9a56e5033f463007696c2934a73303eb186767226bc33d` | tag + by-digest fetch |
| `gcr.io/distroless/base-debian13:nonroot` (not used: no libgcc_s) | `sha256:a0d70d6a97cd697d9362bc2aae4a6560dd65817e365d0043b07325a97975dc91` | `sha256:538c4d631883b52e6379c6a8e26ccaa33a1387b2153f37430b87d267f0298db0` | tag + by-digest fetch |
| `gcr.io/distroless/cc-debian13:latest` (reference only) | `sha256:159783207c2cd44c2aa5715961d13c8612368ac9bd450f887e3f08fc8ea461e3` | `sha256:4072cefb505420cf3d69b5de2b6edd508ff4c8ff7ef17e868d1b59985ae2299e` | tag fetch + hash; the registry's tag list shows this digest carrying `latest` |
| `gcr.io/distroless/cc-debian13:debug-nonroot` (EXCLUDED, listed to be refused) | `sha256:984d31d4...` (computed, not fetched by digest) | `sha256:9acc91edd80f23c7f3856518e2c23d97e491271fd11145f35ac22bb6888d5130` | tag fetch |

All five indexes list amd64, arm64/v8, arm/v7, s390x, ppc64le, riscv64. Contents (distroless `main`, `base/config.bzl`,
`cc/config.bzl`, `base/README.md`): `static` = ca-certificates, tzdata, `/etc/passwd` root (+ nonroot in `:nonroot`), `/tmp`;
`base` = static + Debian 13 `libc6 libssl3t64 libzstd1 zlib1g`; `cc` = base + `libgomp1 libstdc++6 libgcc-s1 gcc-14-base`.
Debian 13 distroless images are usr-merged. The `debug` tags add a busybox shell under `/busybox` (README) and are refused (§5.4,
§6.8). All images are cosign-signed keyless; the README's command is `cosign verify $IMAGE --certificate-oidc-issuer
https://accounts.google.com --certificate-identity keyless@distroless.iam.gserviceaccount.com`. The registry tag list also holds
`.att` attestation tags (their predicate types: [unverified]).

Honest note: distroless is Debian packages assembled by Google (Bazel `rules_distroless`), not a non-Debian libc. What disappears is
apt, snapshot.debian.org, our own `ldd` copy of Debian files and every Debian userland binary. No glibc-free route exists for Lean
(§3).

### 2.2 Builder bases (not in any final image; digests from docker-library/repo-info, NOT read from Docker Hub)

| ref | index digest | arm64 v8 | source |
|---|---|---|---|
| `buildpack-deps:trixie` (fetch, Mathlib, assemble; has curl, gnupg, git, xz, bzip2, unzip, gcc, make, file; no zstd) | `sha256:47fa3fd7df8022082e3f885881775cc7927ec210b470cc4eae9e874f871b008a` | `sha256:5f1ada0ba6a57173dfbc1abfa65eb26afb3437220e3011223eec82b8eff224b1` | repo-info `c0ec1cf4` (2026-10-06); package lists from docker-library/buildpack-deps `debian/trixie{,/scm,/curl}/Dockerfile` |
| `alpine:3.24` (static musl bash build, §4.2 option B1) | `sha256:294b683cb724975bec92580e1e685676bd4b50bda910ddb8c51d4cabeaec77e6` | `sha256:260479a1cfaf304c4c20da7f8405d3ce313513dcd534bb743257bdd2fe0f3e2d` | repo-info `c667a56c` (2026-09-18) |

A wrong digest fails the pull loudly (as for today's `BASE_IMAGE`). The buildpack-deps image removes every `apt-get` from the
builder; the Alpine stage still runs `apk add build-base` (floating within 3.24, apk-signature-checked), which is why the built bash
is pinned by its OUTPUT hash (§4.2).

## 3. Target per image

| image | target final base | why / what cannot be distroless |
|---|---|---|
| `min-both` (PF check + PF oracle) | `distroless/cc-debian13:nonroot@sha256:e792ab3d...` | Lean ships only glibc builds (v4.34.1 assets: `lean-4.34.1-linux.*`, `lean-4.34.1-linux_aarch64.*`; no musl or static), and its bundled glibc is "for linking, but not for running" (`script/prepare-llvm-linux.sh:54` at v4.34.1). So PF needs a system glibc: distroless cc. Scratch would mean hand-copying glibc again, which is what is being removed. |
| `min-lean` (explicit profile) | same | same |
| `min-py` (CP, CR) | **user decision 3**: (a) distroless cc, same digest [recommended] or (b) `scratch` + Python built for musl | (a) keeps the pinned glibc Python (no verdict-relevant change for CP/CR), shares the PF base layers, brings tzdata. (b) is smallest but needs the musl loader from somewhere (§4.5). |
| `full` | removed | a Debian runtime with apt; violates the rule. Its only job was the fallback while busybox/jq were placeholders, which disappear (§8). **User decision 4.** |
| `eq-base` | removed: the glibc toolchain images use `distroless/cc` directly | the shared-layer argument (`INSTALLER_SPEC.md` 12.2 in EQ-T) holds unchanged: the distroless layers are stored once |
| `tc-node`, `tc-julia`, `tc-jvm` | distroless cc | glibc binaries; node needs libstdc++ (cc), Temurin zlib (base) [linkage unverified until the check stage runs]; no shell (as today: `Dockerfile.toolchains:15-18`) |
| `tc-go` | `scratch` | Go >= 1.21 toolchains are built with cgo disabled (go.dev/blog/rebuild), so `go` and its tools are static; `CGO_ENABLED=0` already set (`TOOLS.toml:282`); static output [unverified for the pinned 1.27.1 until `file` in the check stage] |
| `tc-rust` | **user decision 5** | `rustc` (gnu host) runs on distroless cc, but LINKING needs a linker driver + crt objects. Possible without any distribution: target `aarch64-unknown-linux-musl` with its self-contained crt and `rust-lld` [unverified] |
| `tc-haskell` | **user decision 5** | GHC always calls a C compiler/assembler/linker and links libgmp: no distroless image supplies them. Options: defer; Zig (`zig cc`, official minisign-signed static tarballs) as the C toolchain [unverified]; or a Debian gcc closure on distroless (breaks the rule) |

No pool class uses an extension toolchain today (`TOOLS.toml:216-217`, classes `EXT`), so deferring Rust and Haskell costs nothing now.

## 4. Where every tool comes from

| tool | source (official) | artifact | integrity | linkage (how checked) |
|---|---|---|---|---|
| busybox | docker-library/busybox (the Docker Official Image; distroless's own `debug` images take their busybox from the same place: distroless `private/extensions/busybox.bzl`) | `raw.githubusercontent.com/docker-library/busybox/b6edf7d5c5200d629d7c3f7758293a3675471dde/latest/musl/arm64v8/rootfs.tar.gz` (branch `dist-arm64v8`, 2026-09-08) | rootfs sha256 `7e75e6d7d7c97e99528d165ddae068049dfd29846f693e5b35feba66c0e78912` = the layer digest in the same commit's `image-manifest.json`; `bin/busybox` sha256 `4ab4ce065532286051cf7f3ca9d142a115b98da96016fb8be378008fedd70bda`; built from `busybox-1.38.0.tar.bz2` (sha256 `34f9ea6f...`) whose GPG signature is checked against key `C9E9416F76E610DBD09D040F47B70C55ACC9965B` (`latest/musl/Dockerfile.builder` on master) | static-pie, aarch64 (`file`, downloaded and checked here). BusyBox 1.38.0 (musl), built on Alpine 3.23.6 (`image-config.json`). busybox.net labels both 1.38.0 and 1.37.0 "unstable" (`versions.json`). No `bash` applet in this build. |
| jq | jqlang/jq release `jq-1.8.2` (2026-06-20) | `jq-linux-arm64` | sha256 `8b85c817833814ddca00a144c33705546355afccf0cf39b188f3cdb48b852309` = `sha256sum.txt` = GitHub asset digest (downloaded, recomputed) | statically linked (`file`) |
| uv | astral-sh/uv `0.12.22` | `uv-aarch64-unknown-linux-musl.tar.gz` | sha256 `228bd32c180421a94eef91378a92b2dd63c768bd278430e833250524c4a13382` = `.sha256` asset = asset digest (downloaded, recomputed); GitHub attestations exist | `uv`, `uvx` statically linked (`file`) |
| Python | python-build-standalone `20261001`, CPython 3.14.8 | (a) `...-aarch64-unknown-linux-gnu-install_only_stripped.tar.gz` (today's pin) / (b) `...-aarch64-unknown-linux-musl-install_only_stripped.tar.gz` | (a) `4395ae16...` (PINS, = asset digest); (b) `d077f2fd670a512b7d681efb72d2d07e51b7b8ae3a7071a9fc53f4ffd3af909f` = SHA256SUMS = asset digest (downloaded) | (a) glibc dynamic; (b) dynamic against musl: `INTERP /lib/ld-musl-aarch64.so.1`, `NEEDED libc.so` (pyelftools on the download); the musl loader is NOT in the archive. `_zstd` is built in. |
| Lean | leanprover/lean4 `v4.34.1` | `lean-4.34.1-linux_aarch64.tar.zst` | unchanged pin `fdb974c2...` (asset digest; no checksum file upstream) | glibc dynamic |
| Mathlib | unchanged: `MATHLIB_REV`, `project/`, cache verified by lake | | | |
| bash | GNU, `bash-5.3` + official patches `bash53-001..020` (each with a `.sig`; 020 dated 2026-09-14, ftp.gnu.org listing) | built from source, §4.2 | GPG signature of tarball and patches, key `7C0135FB088AAF6C66C650B9BB5869F064EA74AB` (Chet Ramey; the same key docker-library's `bash` image verifies 5.3.20 with: tianon/docker-bash `5.3/Dockerfile`) | static musl [unverified until built] |
| perl | none shipped: §4.3 | | | |
| lake | unchanged in-repo shim `minimal/lake-shim` | | sha256 pinned (`TOOLS.toml:188`) | script |

GNU publishes no bash binary, cpan.org no perl binary, busybox.net no current arm64 binary (`TOOLS.toml:124,142,160`). The
official `bash` Docker image is linked dynamically against Alpine libraries (its `runDeps`), so it is a recipe reference, not a
binary to copy. Whether a bash newer than 5.3 exists: [unverified] (the `ftp.gnu.org/gnu/bash/` listing could not be read).

### 4.1 busybox

Copy `bin/busybox` out of the docker-library rootfs in a builder stage (rootfs sha256 checked, then the binary's sha256 checked),
install it as `/opt/eq/bin/busybox` with the existing applet links (`mkrootfs.sh:74`, unchanged list). The rootfs's other files
(`/etc`, the separately built `getconf`) are discarded. Alternative if the user prefers no docker-library trust: build busybox
here from the signed busybox.net tarball in the Alpine stage (same recipe as docker-library's `Dockerfile.builder`).

### 4.2 bash (user decision 1)

The frozen PF argv is `bash check_lean.sh Answer.lean`, and probes use `bash -c`, bash's `/dev/tcp` and `ulimit -u`.

- **B1 [recommended]: static GNU bash 5.3 patch level 20**, built in a stage `FROM alpine:3.24@sha256:294b683c...`:
  fetch tarball + 20 patches + `.sig` files, `gpg --verify` each against the pinned fingerprint (key from an in-repo exported key
  file whose sha256 is pinned; keyserver fallback must still match the fingerprint), apply the patches, `./configure
  --enable-static-link --without-bash-malloc --disable-nls` (recipe `tc/build-bash.sh`, `recipe_sha256` pinned, provenance
  `built-from-source`), smoke `bash --version`, `bash -c 'exec 3<>/dev/tcp/127.0.0.1/1' ` must fail with "Connection refused"
  (proves net redirections are compiled in). Pins: `BASH_SRC_SHA256`, `BASH_PATCHES_SHA256` (sha256 of the ordered
  `sha256sum bash53-0*` listing) and `BASH_BIN_SHA256` (the built binary). Because apk floats, the binary pin is what makes a drift
  fail closed. First values: the builder prints them after the signatures verify (`build.sh --resolve-tools`, trust on first use
  after a signature check), or the user computes the source hashes on the host (`curl` + `gpg --verify` + `shasum -a 256`).
  Amended 2026-10-10 (USER decision: three builds gave three binaries): the recipe is made reproducible (`tc/build-bash.sh`
  header), `repro-check.sh` builds it several times and compares, and `--write-pin` builds nothing: it pins only values that two
  or more reports of the present recipe agree on.
- **B2: busybox ash as `bash`**: a two-line in-repo `bash` wrapper (`exec /opt/eq/bin/busybox ash "$@"`), no compiled-from-source
  tool and no remaining placeholder. Cost: the hash-frozen `check_lean.sh` then runs under ash (it uses only POSIX features plus
  `local`, but its interpreter changes), and `probe_inner.sh:76-85` would PASS vacuously (`/dev/tcp` does not exist in ash, so every
  connect "fails"): the network rows must move to busybox `nc` with a positive control (§6.8).

### 4.3 perl (user decision 2)

Only one use exists (§1.2): `check_lean.sh:48-52`, a wall-clock limit around each Lean run (124 timeout, 125 fork failure, 127
exec failure, 128+N signal, else the child's code; messages `eqlean: timeout`, `eqlean: killed by signal N`).

- **P1 [recommended]: an in-repo `perl` shim** (`minimal/perl-shim`, installed as `/opt/eq/bin/perl`, provenance `in-repo`,
  sha256 pinned), the same pattern as `minimal/lake-shim`: it accepts exactly `perl -e SCRIPT T CMD [ARG...]` where SCRIPT is
  byte-identical to the wrapper text bash passes from the frozen `check_lean.sh` (`e740de46...`; compared by sha256 constant) and T
  is digits; anything else exits 2 with "perl: not available in this image (eq perl-shim runs only check_lean.sh's timeout
  wrapper)". It runs CMD in the background with stdin kept (`0<&0`), a timer that sets a flag and sends KILL after T seconds,
  waits, and maps the status to the same codes and messages. Known difference: a child that EXITS with a code >= 129 is reported
  as a signal (the shell cannot tell them apart); the code itself is unchanged and lean exits 0/1. Proven by a differential test
  against real perl (§9).
- P2: a static perl (or only `miniperl`) built from `perl-5.44.0.tar.gz` (sha256 from its `.sha256.txt`, `TOOLS.toml:160`) in the
  Alpine stage: exact semantics, a second from-source build.
- P3: change `check_lean.sh` to use `timeout` and re-freeze the PF pool (`pool.sha256`): touches the pre-registered judge.

### 4.4 jq (user decision 6)

No in-container consumer exists today (§1.2). (a) [recommended] keep it as the official static `jq-1.8.2` binary (keeps the
sandboxed member's toolbox, row 7); (b) drop it from the images.

### 4.5 uv and Python

uv: the official musl build is fully static (checked), so it works on distroless and on scratch: use it everywhere (a re-pin of
`UV_SHA256`). Python: (a) keep the pinned gnu build on distroless cc for PF and CP/CR (one Python build across the three classes:
the PF oracle and the CP/CR checks run the same interpreter as today). (b) for a scratch `min-py`: the PBS musl build plus
`/lib/ld-musl-aarch64.so.1` taken from a digest-pinned Alpine (the only extra file); behaviour differences to accept: musl libm
results, no tzdata (`zoneinfo` fails; the current scratch images have no tzdata either), musl's allocator.

### 4.6 Users, CA certificates, tzdata

`--user 10001:10001` is numeric and needs no passwd entry ([unverified]: checklist C11). An in-repo `/etc/passwd` and `/etc/group`
(root, nobody, nonroot 65532, eq 10001) are COPY'd over the base's so that `getpwuid` users (Python `getpass`, bash `~`) behave
as today. CA certificates and tzdata come with distroless and are harmless under `--network none`; none are added to scratch images.

## 5. Build design

### 5.1 Stages (one Dockerfile per family; `Dockerfile` (full) is deleted)

```
buildpack-deps:trixie@digest ── fetch      lean (.tar.zst unpacked by the verified PBS python's tarfile 'r:zst' [unverified:
                                           _zstd is built in, the tarfile mode not run]; fallback: the release's .zip asset
                                           and unzip, a LEAN_SHA256 re-pin), uv musl, PBS, jq, busybox rootfs; every archive
                                           sha256-checked BEFORE extraction (as today)
                             ── mathlib    lake exe cache get (network at build time only; unchanged), LEAN_PATH, PROVENANCE
alpine:3.24@digest ───────── bash         (B1 only) signatures, patches, static build, BASH_BIN_SHA256 check
buildpack-deps ───────────── assemble-*   mkrootfs.sh: /rootfs = /opt trees + /opt/eq/bin (busybox, applet links, bash,
                                           perl-shim, lake-shim, jq) + passwd/group + mount points; NO libraries copied;
                                           COPY --from=${DISTROLESS_CC} / /base-rootfs/  → chroot check of every ELF over
                                           base + layer (ld.so --list); TOOLS.lock, MANIFEST.sha256, SBOM.tsv
${DISTROLESS_CC}@digest ──── eq-min, eq-py-min, eq-lean-min   COPY --from=assemble-* /rootfs/ / ; ENV; USER 10001:10001
final ────────────────────── check-*      FROM the final target: RUN ["/opt/eq/bin/busybox","sh","/opt/eq/check.sh"]
                                           (exec form, no /bin/sh needed): ld.so --list over the REAL final filesystem,
                                           smoke tests, perl-shim wrapper test, cp -R copy-in test; never exported
```

- Every `FROM` is `name@sha256:` (builders too); the final stages are `scratch` or `${DISTROLESS_*}` only, with no `RUN`.
- No `apt-get`, `dpkg`, `apk` or snapshot in any stage except `apk add` in the Alpine bash stage (B1).
- `mkrootfs.sh` keeps its structure but its library rule becomes: a library `ldd` names must be in `/base-rootfs` (distroless) or
  inside the tool's own `/opt` tree; anything else is an ERROR naming the library ("no third source of shared objects"), never a
  copy. For scratch images `/base-rootfs` is empty (plus, for option 3b, the one musl loader).
- `tc/mkrootfs-tc.sh` already compares against `/base-rootfs` (`:23-27`); `base` mode and `tc/apt-closure.sh` are deleted; the
  distro-package branch (`:78-98`) is deleted and the same "third source" rule applies.
- `build.sh` builds `check-<image>` before the final target (same cache, so the final image is the checked one); a failing check
  is exit 12.
- PATH = `/opt/eq/bin` plus the tool trees (`/opt/lean/bin`, `/opt/uv`, `/opt/python/bin`); `/usr/bin` and `/usr/sbin` are NOT on
  PATH, so whatever executables the distroless packages carry (inventory [unverified]) are outside the PATH allowlist rows;
  `/usr/bin/sh` and `/usr/bin/bash` are symlinks to `/opt/eq/bin/bash` (B1) or busybox (B2), so `/bin/sh` (copy-in) and the
  `#!/bin/bash` of `lake-shim` keep working through the usr-merged `/bin`.
- Mount points `/work /eqsrc/work /fixture /in /eq/tunnel /items /hostlake` stay in the layer (`mkrootfs.sh:20-21`).

### 5.2 Pins and manifest

`PINS` after the change (keys removed: `BASE_IMAGE`, `APT_SNAPSHOT`, `BASE_LAYER_URL`, `BASE_LAYER_SHA256`):

```
BUILDER_IMAGE=buildpack-deps:trixie@sha256:47fa3fd7df8022082e3f885881775cc7927ec210b470cc4eae9e874f871b008a
MUSL_BUILDER_IMAGE=alpine:3.24@sha256:294b683cb724975bec92580e1e685676bd4b50bda910ddb8c51d4cabeaec77e6     (B1 only)
DISTROLESS_CC=gcr.io/distroless/cc-debian13@sha256:e792ab3d241a468a4fd7519ddbbebe66b49b5f365771716ea688ad40b6c6f1c2
DISTROLESS_CC_ARM64=sha256:2f0295ce228a23109ec1c8d38763bfe995b0dba7b3672f58d3a67ebfbc542fdc   (read by base-pins.sh, verify-tools)
LEAN_*, PYTHON_*, PBS_TAG, MATHLIB_REV      unchanged
UV_VERSION=0.12.22  UV_SHA256=228bd32c180421a94eef91378a92b2dd63c768bd278430e833250524c4a13382   (musl)
BUSYBOX_ROOTFS_URL=https://raw.githubusercontent.com/docker-library/busybox/b6edf7d5c5200d629d7c3f7758293a3675471dde/latest/musl/arm64v8/rootfs.tar.gz
BUSYBOX_ROOTFS_SHA256=7e75e6d7d7c97e99528d165ddae068049dfd29846f693e5b35feba66c0e78912
BUSYBOX_SHA256=4ab4ce065532286051cf7f3ca9d142a115b98da96016fb8be378008fedd70bda
BASH_VERSION=5.3  BASH_PATCHLEVEL=20  BASH_GPG_FPR=7C0135FB088AAF6C66C650B9BB5869F064EA74AB          (B1 only)
BASH_SRC_SHA256=UNSET  BASH_PATCHES_SHA256=UNSET  BASH_BIN_SHA256=UNSET                                (B1: filled after §4.2)
```

`TOOLS.toml`: provenance `distro-package` and `apt:` urls are refused for any tool listed by an `[[image]]` (they stay legal only for
`build-only` git, which itself disappears: buildpack-deps has git); `busybox`, `jq`, `uv` become `prebuilt-upstream` with the values
above; `bash` becomes `built-from-source` (B1, `recipe = "tc/build-bash.sh"`) or an `in-repo` wrapper (B2); `perl` is replaced by
`perl-shim` (`in-repo`); new `in-repo` entries `passwd-group`; `cc` and `ghc-link-libs` are deleted (decision 5); `[[image]].base`
takes `scratch | distroless-cc | distroless-static`, each distroless value naming a PINS key that must be `@sha256:` and must not
contain `debug`. Keeping the table set `[[tool]] [[image]] [[profile]]` means `tools.sh`'s awk reader and the WALL's tomllib reader
(`lib/eq-wall/eq_wall.py:521-528`, path `lib/eq-wall/policy.default.toml:38`) need no format change. Note for the WALL: with `perl`
gone from the manifest, a WALL missing-tool request for `perl` is no longer refused by the `tools_manifest` rule; it falls to the
policy (deny-all by default).

`verify-tools.sh`: `pair busybox` compares `BUSYBOX_SHA256`; new pairs for jq, uv musl, bash; `--images --inspect` gains a base
check: the saved image's bottom layers must equal the layer list of `DISTROLESS_CC_ARM64` (21 layers today) for distroless
images, and there must be exactly our layers for scratch images (`eqc_json.py` gets an `oci-layers` reader); `--deep` also re-hashes
`/opt/eq/BASE_EXECUTABLES.txt` (inventory written by the assemble stage: every executable file outside `/opt`, with sha256; any
setuid/setgid file fails the build).

`distro-pins.sh` is deleted; its replacement `base-pins.sh` (host-side, read-only, user-run like today) verifies each distroless
digest with `cosign verify` (identity and issuer above), checks that the pinned arm64 manifest is listed in the pinned index, that no
pinned ref contains `debug`, and prints `BASE name digest` lines beside the pins (exit 0 equal, 1 a failed check, 13 a placeholder).

### 5.3 Reproducibility and SBOM

- Image digests differ between builds (timestamps); the content identity is `MANIFEST.root` (sha256 of the sorted per-file
  manifest, `mkrootfs.sh:221-229`), which must be equal for two builds from the same pins (a user-run check, §9 D4).
- Floating inputs left: `apk add build-base` (B1 only; output pinned by `BASH_BIN_SHA256`) and the Mathlib git clones and cache
  (pinned revisions, lake-verified hashes, `olean_tree_sha256` recorded as today).
- SBOM: `/opt/eq/SBOM.tsv` per image = one row per component (name, version, source URL, artifact sha256, installed-file sha256,
  licence, provenance) generated from TOOLS.toml + PINS, plus a row for the distroless base (index and arm64 digests). The
  distroless package list itself is in its signed attestation (`cosign verify-attestation`, user-run, optional).
- The record (`images/NAME.env`) gains `EQ_BASE_REF` and `EQ_BASE_ARM64` so `doctor.sh` and `--check` can name the base.

## 6. Changes per file (implementation scope)

1. `Dockerfile` (full): delete. `Dockerfile.minimal`: §5.1; finals `FROM ${DISTROLESS_CC}` (or scratch for 3b); `tools-report`
   and the snapshot `base` stage removed; ARGs mirror PINS. `Dockerfile.toolchains`: builders on `BUILDER_IMAGE`; `eq-base` gone;
   finals `FROM ${DISTROLESS_CC}` (node, julia, jvm), `scratch` (go); rust/haskell per decision 5; `tc-tools-report` removed.
2. `minimal/mkrootfs.sh`: drop `add_bin` for bash/perl and the Debian closure, the dpkg provenance and `MANIFEST.debian-files.tsv`;
   install busybox/bash/perl-shim/jq/lake-shim into `/opt/eq/bin`; library rule and chroot check over `/base-rootfs`; keep the
   wrapper smoke (`:203-212`, now against the shim) and the copy-in smoke (`:214-218`); write SBOM and IMAGE_KIND
   (`min-both distroless-cc` etc.). New `minimal/perl-shim`, `minimal/etc/{passwd,group}`, `minimal/check.sh`; `tc/build-bash.sh`
   (B1); delete `tc/apt-closure.sh`.
3. `build.sh`: `--set full` and `--no-snapshot` removed (usage error 2 naming the removal); `--set min` stays; `--resolve-tools`
   becomes "print the signature-verified bash pins" (B1) or is removed (B2); `needed_pins`/`pin_format` for the new keys
   (`*_IMAGE` and `DISTROLESS_*` must be `name@sha256:<64 hex>` without `debug`); `inputs_hash` covers the new files; check targets
   built first; `pick` (`:335-336`) without `full`; messages at `:254,262` rewritten.
4. `lib.sh`: run flags UNCHANGED (`--rm --network none --read-only --cap-drop ALL --init -m -c --ulimit nproc --user 10001:10001
   --tmpfs /tmp`, `/work` tmpfs + read-only `/eqsrc/work`, `lib.sh:139-149,213`); `EQ_IMAGE_NAMES` and `eq_img_default_tag` lose
   `full` (`:87-96`); `EQ_COPY_IN` unchanged (it must stay byte-identical to the harness's).
5. `eq-container.sh`: `--set full` refused; status/help text. `install.sh`: `STACK_EQ_CONTAINER_SET` accepts `min` only
   (`:3526,3576-3577`), the exit-13 note (`:3610`) loses the `full` fallback. (install.sh is a security surface: §9 reviews.)
6. `probe_inner.sh`: PATH rows over `/opt/eq/bin` and the tool trees; `image_kind` fallback (`:176`, "full-debian") removed; new
   rows `no_debug_shell` (`/busybox` absent), `no_package_manager` (no apt, apt-get, dpkg, apk, rpm executable anywhere),
   `network_probe_control` (a loopback listener via busybox `nc -l` must ACCEPT the same connect primitive the network rows use, so
   a missing `/dev/tcp` or `nc` is a FAIL, never a vacuous PASS); `probe.sh`'s required-row list (`:81-85`) gains them.
   `probe.d/50-tunnel.sh`: unchanged (POSIX sh; uses bash `/dev/tcp` when present, python3 otherwise).
7. `verify-tools.sh`, `tools.sh`, `eqc_json.py`: §5.2. `distro-pins.sh` → `base-pins.sh`.
8. Docs: `README.md` (this directory), `TOOLS.toml` header, `CONFIG.md` §7 container section (`:612-623`, the `full` fallback and
   the exit-13 text) plus a changelog entry, root `README.md:1023`, `hand_off/R3_CONTAINER_CHECKLIST.md` (C14-C17 → D1-D6, §9),
   `hand_off/HANDOFF_STATE.md` §6 item 2 (record the new decision and the superseded one).
9. Tests: §9.

## 7. The harness contract

No harness change is required: the argv shapes of §1.2 keep working, because every check image keeps `/bin/sh`, `cp`, an
executable `bash`, `perl` (shim), `lake` (shim), `lean`, `uv`, `python3` and the busybox applets. What changes for EQ-T:

- Interpreter of the frozen PF checker: unchanged under B1 (GNU bash 5.3 instead of Debian bash 5.2.37, both GNU); ash under B2.
- `perl` becomes a shim that refuses anything but the wrapper: rows 6 (fact re-runs) and 7 (sandboxed members) lose perl as a
  general tool, and so does jq under 4b. A sandboxed member's toolbox = `/opt/eq/bin` (busybox applets listed in `mkrootfs.sh:74`,
  bash, jq, lean, lake-shim, uv, python3). Whether the arms' tool sets are part of the pre-registration: for the EQ-T owner.
- CP/CR under 3b: musl Python (numerics of libm, no tzdata) — a verdict-relevant change; none under 3a.
- `flags.json` keys (`container_images`, limits, user) and `image.env` keys are unchanged; image tags stay.
- The harness's isolation-probe runs this directory's `probe_inner.sh` (`eq_harness.py:3624`), so the new rows reach it.

## 8. The `eq-pins` values (now on `main`)

| value on main | fate |
|---|---|
| `TOOLS.toml` bash `5.2.37-2+b10` / `ccbd5106...` (Debian base layer) | superseded: B1 static bash 5.3.20 (new pins after the signature check) or B2 wrapper |
| `TOOLS.toml` perl `5.40.1-6+deb13u1` / `b37d5994...` | superseded: removed; `perl-shim` (in-repo) |
| `BUSYBOX_SHA256=UNSET`, busybox `PLACEHOLDER` (`PINS:43-49`, `TOOLS.toml:112-128`) | resolved: `4ab4ce06...` (docker-library musl build, verified here); no snapshot needed |
| jq `PLACEHOLDER` (`TOOLS.toml:166-182`) | resolved: jq 1.8.2 static `8b85c817...` (or dropped, 4b) |
| `BASE_IMAGE=debian:trixie-slim@a99cfc51`, `APT_SNAPSHOT`, `BASE_LAYER_URL`, `BASE_LAYER_SHA256` | removed (builder becomes `buildpack-deps:trixie@47fa3fd7...`) |
| `distro-pins.sh`, `tests/test_eq_container_pins.py` distro-pins cases, checklist C14-C15 | removed / replaced by `base-pins.sh` and its tests, D1 |
| `cc`, `ghc-link-libs` placeholders | removed with decision 5 |
| UV gnu `6f66a14e...` | replaced by uv musl `228bd32c...` |
| Lean, PBS gnu, Mathlib pins | unchanged |

After the change the only remaining placeholders are the three bash pins under B1; under B2 none, so `core` would no longer stop at
exit 13.

## 9. Plan

| phase | owner | effort | content | done when |
|---|---|---|---|---|
| 0 | user | — | answer §10 | decisions recorded in HANDOFF_STATE §6 |
| 1 pins + manifest | python-engineer (tests) + main-coder (shell) | 1 day | PINS, TOOLS.toml, tools.sh, verify-tools.sh rules, `base-pins.sh`, delete `distro-pins.sh`; tests below | manifest tests green, every seeded bug caught |
| 2 Dockerfiles + build | main-coder | 1-2 days | §5.1, §6 items 1-5; `tc/build-bash.sh` (B1), shims, passwd | `build.sh --dry-run --profiles core` plans the new targets; hermetic tests green |
| 3 probes | main-coder | 0.5 day | §6 item 6 | probe tests green against the fake CLI |
| 4 docs | writer or main-coder | 0.5 day | §6 item 8 | docs name no Debian runtime, `full` or snapshot step |
| 5 reviews | security-auditor; code-reviewer | 0.5-1 day | supply chain (new trust roots: Google distroless cosign identity, docker-library busybox build, GNU bash key, Alpine apk in one builder stage, GitHub release digests), the shims (input refusal), install.sh; the diff (> 300 lines, > 8 files) | no open HIGH/CRITICAL |
| 6 user-run | user, normal terminal | 1-2 h + downloads | D1-D6 below | all rows as described |

Tests (hermetic; each proven by a seeded bug that must make it fail):

- `test_final_stages_are_scratch_or_pinned_distroless`: every `[[image]]` target's `FROM` is `scratch` or a `DISTROLESS_*` ARG
  whose value is `gcr.io/distroless/<x>-debian13@sha256:<64 hex>` without `debug`. Seeds: `FROM debian:trixie-slim`, a
  `:debug-nonroot` ref, a tag-only ref.
- `test_every_from_is_digest_pinned` (builders too). Seed: `FROM alpine:3.24`.
- `test_no_package_manager_or_run_in_final_stages`. Seed: `RUN apt-get ...` in `eq-min`.
- `test_manifest_refuses_distro_package_in_images` (verify-tools exit 2). Seed: an `apt:` tool in `min-py`.
- `test_perl_shim_matches_real_perl`: differential against the host's `/usr/bin/perl` running the exact wrapper text: exit 0, exit
  3, timeout (124 + `eqlean: timeout`), self-kill TERM (143 + message), missing command (127), stdin passed through. Seeds: the
  shim returning 137 on timeout; dropping stdin.
- `test_perl_shim_refuses_other_scripts`: one changed byte in SCRIPT, a non-numeric T, no CMD → exit 2. Seed: a shim that skips the
  hash check.
- `test_perl_shim_wrapper_text_is_check_leans`: the shim's constant equals the sha256 of the wrapper in a vendored copy of the frozen
  `check_lean.sh` (`e740de46...`). Seed: the constant of an edited wrapper.
- `test_base_pins_*` (fake `cosign`, fake registry JSON): good; wrong identity; arm64 missing from the index; index/arm64 mismatch;
  a `debug` ref → each fails closed with nothing printed on stdout.
- `test_bash_recipe_refuses_bad_signature` (B1; fake `gpg`): bad signature or wrong fingerprint stops before `configure`.
- `test_mkrootfs_refuses_a_third_source_library` (a fake `ldd` naming a library absent from `/base-rootfs`). Seed: the old copy rule.
- Updates: `tests/test_eq_container.py` (no `full` in `EQ_IMAGE_NAMES`, `--set full` → 2, `pick`), `test_eq_container_pins.py`
  (new keys and formats, awk reader vs tomllib), `test_install_eq_container.py:193,256-263` (`STACK_EQ_CONTAINER_SET=full` refused).

User-run steps (an agent's sandbox can reach neither the `container` services nor `gcr.io`, Docker Hub, ftp.gnu.org or
busybox.net). Hosts the build needs: `gcr.io` and its blob redirect target [unverified host], `registry-1.docker.io`,
`auth.docker.io` (buildpack-deps, alpine), `dl-cdn.alpinelinux.org` (B1 apk), `github.com` and its release-asset host (Lean, uv,
PBS, jq), `raw.githubusercontent.com` (busybox rootfs), `ftp.gnu.org` (B1 bash) and `keyserver.ubuntu.com` only if the key is not
in-repo, `lakecache.blob.core.windows.net` + `github.com` (Mathlib). D1 also needs `cosign` and the Sigstore hosts.

| # | command | confirms when |
|---|---|---|
| D1 | `bash lib/eq-container/base-pins.sh` | cosign verifies `cc-debian13@e792ab3d...` (and `static` if used); arm64 `2f0295ce...` is in the index; rc 0 |
| D2 | (B1) `bash lib/eq-container/repro-check.sh`, then `bash lib/eq-container/build.sh --resolve-tools --write-pin` | each build prints the three bash pins after "Good signature" from `7C0135FB...`; the check must end `REPRODUCIBLE x3`; `--write-pin` builds nothing and pins the agreeing values |
| D3 | `bash lib/eq-container/build.sh --profiles core --yes` | `check-min-both` and `check-min-py` pass, then the finals build; rc 0 |
| D4 | the same with `--force`, then compare `MANIFEST.root` of both builds | equal |
| D5 | `bash lib/eq-container/verify-tools.sh --images --deep --inspect --smoke --profiles core; bash lib/eq-container/eq-container.sh install` | base layers equal the pinned distroless layers; the probe passes including the new rows |
| D6 | `uv run --script EQ-T/harness/eq_harness.py isolation-probe ...`, then the PF/CP/CR dev items through the container and with isolation `off` | the same verdicts on both backends |

Plus three behaviour rows for the R3 table: exec-form `RUN` in a stage built FROM a distroless image; `COPY --from=<gcr.io
ref@digest> / /base-rootfs/` in `container build`; `--init` working on an image without a shell (the init comes from the runtime's
init image per the 1.5.0 command reference, behaviour [unverified]).

## 10. Decisions for the user

1. bash: B1 static GNU bash 5.3.20 from the signed source [recommended] | B2 busybox ash as `bash`.
2. perl: P1 in-repo shim for the one wrapper [recommended] | P2 static perl from source | P3 edit `check_lean.sh` and re-freeze the PF
   pool.
3. CP/CR base: (a) distroless cc with the pinned glibc Python [recommended] | (b) scratch with musl Python + the musl loader.
4. The Debian `full` image and `STACK_EQ_CONTAINER_SET=full`: remove [recommended] | keep as a non-default fallback (breaks the rule).
5. Rust and Haskell: (a) defer both, ship node, go, julia, jvm [recommended] | (b) Rust via `rust-lld` + the musl self-contained
   target (no cc, [unverified]), Haskell deferred | (c) Zig as the C toolchain for both [unverified] | (d) Debian gcc closure on
   distroless (breaks the rule).
6. jq: (a) official static jq 1.8.2 [recommended] | (b) drop.

Defaulted unless the user objects: busybox from docker-library's GPG-checked musl build (alternative: compile it here); uv switches to
its static musl build; PF stays on distroless cc (no alternative short of hand-copying glibc).

## 11. Unverified and risks

- Distroless digests were read through a reader proxy (consistency proven, authenticity not): D1 decides. Distroless rebuilds often;
  a re-pin is PINS + ARG + D1 + rebuild.
- Lean's, node's, Julia's and Temurin's library needs on distroless cc: the check stage names any gap (fail closed).
- The distroless executable inventory (`/usr/bin`, `/usr/sbin`) was not listed (the blobs were not reachable): the check stage
  records it; PATH excludes it.
- The bash recipe flags, the Go 1.27.1 static linkage, Rust `rust-lld` linking, Zig + GHC: never run.
- docker-library's `dist-arm64v8` commit b6edf7d5 predates the master `Dockerfile.builder` that was read; the binary's version
  string (1.38.0 musl) comes from the same commit's `image-config.json`.
- The bash patch signatures 011-020 are larger files (123 vs 95 bytes) than 001-010; the official `bash` image verifies all of
  them with the same fingerprint, but which key or format produced them was not checked here.

## Sources (read 2026-10-06)

- https://github.com/GoogleContainerTools/distroless (README; `base/config.bzl`, `cc/config.bzl`, `base/README.md`,
  `cc/README.md`, `private/extensions/busybox.bzl`, `MODULE.bazel` on `main`)
- https://gcr.io/v2/distroless/{cc,static,base}-debian13/manifests/{nonroot,latest,debug-nonroot} and by digest (via r.jina.ai)
- https://github.com/docker-library/busybox (`dist-arm64v8` @ b6edf7d5; `master`: `versions.json`, `latest/musl/Dockerfile.builder`)
- https://github.com/docker-library/repo-info (`repos/{alpine/remote/3.24.md, buildpack-deps/remote/trixie.md, debian/remote/trixie-slim.md}`)
- https://github.com/docker-library/buildpack-deps (`debian/trixie{,/scm,/curl}/Dockerfile`)
- https://github.com/tianon/docker-bash (`5.3/Dockerfile`); https://ftp.gnu.org/gnu/bash/bash-5.3-patches/
- https://api.github.com/repos/{astral-sh/uv, astral-sh/python-build-standalone, leanprover/lean4, jqlang/jq}/releases
- https://raw.githubusercontent.com/leanprover/lean4/v4.34.1/script/prepare-llvm-linux.sh
- https://go.dev/blog/rebuild; https://ziglang.org/download/ (minisign files listed; newest stable not read)
