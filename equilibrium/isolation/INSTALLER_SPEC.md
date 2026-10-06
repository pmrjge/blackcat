# Installer integration spec: `--with-eq-docker`

For the integration agent that works in `M = /Users/pmrj/ZDone/claude-agent-stack` (the stack repo). Everything described here is
staged and tested in `ISO/repo-stage/` (ISO = `.../next-steps-7c1c7f/.claude-work/equilibrium/isolation`). Nothing in M was
changed by the staging. Conventions were read from `M/install.sh` (option block lines 95-140, `say`/`note`/`would` helpers at 409-411,
steps `1/11` .. `11/11`, step 10 ends at line 3169 before `say "11/11 Shell profile"`), `M/dot-claude/bin/doctor.sh`
(`ok`/`warn`/`fail` print `  ok    `, `  WARN  `, `  FAIL  `; sections `echo "== Name"`), `M/lib/stack.env.example`,
`M/tests/install_smoke.sh`, `M/tests/test_install_state.py` (`_scratch_repo`, `_install`), `M/tests/test_install_devtools.py`
(the `test -t` shim) and `M/dot-claude/hooks/agent_guard.py:4357-4366`. Line numbers are as of M commit 70de58b.

## 1. What is copied (ISO/repo-stage -> M), and the git modes

| from `ISO/repo-stage/` | to `M/` |
|---|---|
| `lib/eq-docker/**` (every file; `LAYOUT` holds the word `repo`) | `lib/eq-docker/**` |
| `tests/fake-docker/docker`, `tests/fake-brew/brew`, `tests/conftest.py`, `tests/test_eq_docker.py`, `tests/test_eq_docker_isolation.py` | same paths under `tests/` |

The staging is the source. After the copy, `diff -r ISO/repo-stage/lib/eq-docker M/lib/eq-docker` and the same for `tests/fake-docker`,
`tests/fake-brew` and the three test files must print nothing (they are new paths in M). `ISO/` itself (RUNBOOK*.md, INSTALLER_SPEC.md,
the staging copies of the scripts at its top level) is not copied.
`tests/conftest.py` is new in M: it must not shadow other fixtures (M has none today; check `git ls-files tests/conftest.py` first,
and if one exists merge the `Env` class and the `env` fixture into it).

Files written with the Write tool carry no execute bit. Set the git mode explicitly (`git update-index --chmod=+x <path>` after
`git add`, or `chmod 755` before it) on:
`lib/eq-docker/{eq-docker.sh,lib.sh,build.sh,build-minimal.sh,spike.sh,probe.sh,probe_inner.sh,reverify.sh,compare-images.sh,trace-reads.sh,make-seccomp.sh}`,
`lib/eq-docker/minimal/{mkrootfs.sh,lake-shim}`, `tests/fake-docker/docker`, `tests/fake-brew/brew` (all mode 100755). Everything else
(Dockerfiles, `PINS`, `LAYOUT`, `README.md`, `project/**`, `.dockerignore`, tests `*.py`) stays 100644. The scripts are started with
`bash script.sh` and the tests copy the shims with an execute bit, so a missing bit does not break them, but `install.sh` and the
README call `bash lib/eq-docker/eq-docker.sh`, and a 755 `lib.sh` matches the ISO originals. Add `lib/eq-docker/.state/` to the
repo `.gitignore` (the source-layout state directory when `LAYOUT` is absent; never created in the repo layout).

## 2. install.sh: options

New variables next to the others (line ~95): `WITH_EQ_DOCKER=0; INSTALL_DOCKER=0; DOCKER_VIA=cask`.

```
--with-eq-docker        also build and verify the Docker isolation images for the equilibrium harness (off by default)
--install-docker        with --with-eq-docker: when Docker is missing, install it with Homebrew (this is the consent; --yes is not)
--docker-via cask|colima   which Homebrew route --install-docker and the terminal offer use (default cask)
```
Parsing (in the `case "$a" in` block): `--with-eq-docker) WITH_EQ_DOCKER=1 ;;`, `--install-docker) INSTALL_DOCKER=1 ;;`,
`--docker-via)` takes the next word like `--config-dir` does (error `--docker-via needs cask or colima`, exit 2), `--docker-via=*)`.
After the loop, usage errors (exit 2, one line, nothing written, same style as the `--force` check at line 135):
- `--install-docker` or `--docker-via` without `--with-eq-docker`: `--install-docker/--docker-via work only with --with-eq-docker`
- `--docker-via` value other than `cask` or `colima`
- `--install-docker` together with `--no-deps`: `--install-docker installs a tool; --no-deps forbids tool installs`
`--diff` takes only `--config-dir`: the existing `DIFF_CONFLICT` logic already rejects the new flags. Add the three options to the
header comment (lines 2-63; `-h/--help` prints it), to README.md's option list and CONFIG.md (a short "Docker isolation" section).
`--yes` and `--no-prompt` keep their meaning and are NEVER consent to install Docker. A new knob `STACK_EQ_DOCKER_SET`
(`min|dl|full`, default: unset = `eq-docker.sh`'s own `DEFAULT_SET`) is passed as `--set`; tests use it to select the `full` set.

## 3. install.sh: step "10b/11 Docker isolation (--with-eq-docker)"

Placement: after the step-10 plugin block's closing `fi` (line 3169) and before `say "11/11 Shell profile"`, outside the
`SKIP_PLUGINS` conditional (`--no-plugins` does not affect it). A run without `--with-eq-docker` prints nothing new and calls neither
docker nor brew (so every existing smoke expectation is unchanged). The step is a function `eq_docker_step` followed by one call,
so the dry-run and real paths share the code:

```
eq_docker_step() {                       # only when WITH_EQ_DOCKER=1
  say "10b/11 Docker isolation (--with-eq-docker)"
  local drv="$HERE/lib/eq-docker/eq-docker.sh" args=(install)
  [ -f "$drv" ] || { note "! $drv missing: Docker isolation skipped"; return 0; }
  [ -z "${STACK_EQ_DOCKER_SET:-}" ] || args+=(--set "$STACK_EQ_DOCKER_SET")
  [ "$ASSUME_YES" = 1 ] && args+=(--yes)                 # answers eq-docker's build question only
  { [ "$NO_PROMPT" = 1 ] || [ "$NO_DEPS" = 1 ]; } && args+=(--no-prompt)   # --no-deps: a Homebrew offer is a tool install
  [ "$INSTALL_DOCKER" = 1 ] && args+=(--install-docker --docker-via "$DOCKER_VIA")
  [ "$DOCKER_VIA" = colima ] && [ "$INSTALL_DOCKER" = 0 ] && args+=(--docker-via colima)   # the terminal offer's route
  if [ "$DRY_RUN" = 1 ]; then
    would "bash $drv ${args[*]} --dry-run   (creates nothing; reads docker info and image ids)"
    bash "$drv" "${args[@]}" --dry-run || note "! eq-docker dry run exited $?"
    return 0
  fi
  note "builds locally from lib/eq-docker (10-40 min cold, several GB of disk, network for the build only); Ctrl-C is safe"
  ...  rc=0; bash "$drv" "${args[@]}" || rc=$?       # stdin stays the terminal: eq-docker asks there, never in a pipe
  eq_docker_manifest "$rc"
  case "$rc" in
    0)  eq_docker_env_set; note "+ Docker isolation verified: $(…print-env EQ_IMAGE…)  (state: $STATE_ROOT/eq-docker)" ;;
    10) note "! Docker isolation skipped (not an error): see the eq-docker lines above; re-run ./install.sh --with-eq-docker when Docker runs" ;;
    *)  note "! Docker isolation NOT installed (eq-docker exit $rc): $STATE_ROOT/eq-docker/logs/ ; the rest of the install is unaffected" ;;
  esac
}
```
Contract: the step never makes `install.sh` fail and never changes its exit status (an optional feature, like a failed plugin
install: a `note "! ..."` line). `STATE_ROOT` is `${XDG_STATE_HOME:-$HOME/.local/state}/claude-agent-stack`, the same expression as
`state_root()` in agent_guard.py and as the backup root's parent. `bash "$drv"` inherits the environment, so the test knobs
`EQ_DOCKER_APP_DIRS`, `EQ_DOCKER_BIN_DIRS`, `EQ_BREW_DIRS` and `EQ_STATE_DIR` work through the installer. Under `--dry-run`
nothing is created: `eq-docker.sh install --dry-run` is read-only (`docker info`, `docker image inspect`; verified by
`test_dry_run_creates_nothing_and_builds_nothing`). Add the step to the closing "Next:" list (item 5: `· --with-eq-docker
(Docker isolation images for the equilibrium harness)`).

Exit codes of `eq-docker.sh install` (the table the step maps): 0 ok | 2 usage | 10 skipped (docker missing, daemon down, wrong
architecture, no consent, no terminal, declined build) | 12 build failed | 13 a pin in `PINS` is still a placeholder | 14 spike failed | 15 probe
failed. Docker missing or its daemon down is therefore `warn + skip` (10), never a failed install.

### Homebrew offer (inside eq-docker.sh; the installer only passes flags)
- Shown only when no `docker` CLI exists, `/Applications/Docker.app` (or `~/Applications/Docker.app`) does NOT exist, and `brew` exists.
  Docker.app present: never `brew install --cask` (the cask would collide with the app; the driver says "start Docker Desktop once").
- Consent = a `y` typed at the prompt on a terminal (`test -t 0`), or `--install-docker`. `--yes` alone is NOT consent, `--no-prompt`
  removes the prompt. No terminal and no flag: skip with "no consent ... (--yes is not enough)".
- DEFAULT OFFER (user decision) = Docker Desktop: `brew install --cask docker-desktop`. Verified read-only 2026-10-04 with `brew info`
  (Homebrew 7.0.7): cask `docker-desktop` 4.93.0, requires macOS >= 14, links binaries into `/usr/local/bin` and `/usr/local/cli-plugins`; the old
  token `docker` points at it and conflicts with cask `rancher`. Admin-rights note (printed): the links need write access to
  `/usr/local/...` and Docker Desktop's first launch may ask for the macOS password for its privileged helper: UNVERIFIED here.
- Licence note (printed; UNVERIFIED, from memory, not checked against https://www.docker.com/pricing/ today): Docker Desktop is free for personal
  use, education, non-commercial open source and small businesses (< 250 employees and < US$10M revenue); larger organisations need a
  paid subscription. The text tells the user to read Docker's terms at first launch.
- Alternative `--docker-via colima`: `brew install colima docker docker-buildx` (colima 0.10.3, docker 29.8.2, docker-buildx 0.37.2, brew info
  2026-10-04). docker-buildx's caveat: add `"cliPluginsExtraDirs": ["$(brew --prefix)/lib/docker/cli-plugins"]` to `~/.docker/config.json`; the
  driver prints it and NEVER edits that file. After either route the driver stops with exit 10 ("installed but not running yet": start Docker Desktop /
  `colima start`, then re-run). Nothing is started for the user and no `sudo` is ever run.
- Never installs Homebrew (no brew: skip, with the link to install Docker by hand). A `brew info` miss (the cask or a formula is not known) or an
  install failure is a skip, never a failed install.

## 4. Non-clobbering stack.env lines

`lib/stack.env.example`: append, in the same commented style (these lines are off; "Upgrades append new variables ... commented out"):

```
# equilibrium harness, Docker isolation (install.sh --with-eq-docker writes these two lines after a verified install, unless you set them):
# EQ_ISOLATION: docker = model-written code (checks, oracles, fact re-runs) runs in containers; empty = the harness' own default.
# EQ_IMAGE: the verified lean image id (sha256:<64 hex>) the harness takes for PF. Not a secret; not exported to your shells (STACK_EXPORT).
#EQ_ISOLATION=docker
#EQ_IMAGE=
```
Function `eq_docker_env_set` (called after exit 0 only; not in `--dry-run`): reads `bash "$drv" print-env` (two lines
`EQ_ISOLATION=docker`, `EQ_IMAGE=sha256:<64 hex>`, exit 1 and no output unless the install is verified). For each `KEY=VALUE`: if `$C/stack.env`
already has an UNcommented, NON-EMPTY `KEY=` assignment, keep it and `note "= stack.env keeps your KEY=..."`; otherwise replace the first
`KEY=` (empty) or `#KEY=` line, else append the line. `ensure_backup; python3 "$STATE_PY" record "$B" file stack.env` first, preserve mode 0600,
write atomically (temp + rename, as `deduped()` does for the manifest). `EQ_IMAGE` is rewritten on a later verified install only when the line still
holds the value the installer wrote last time (`eq_docker.env_image` in the manifest, section 7); a value you changed is yours.
`STACK_EXPORT` is NOT changed: neither key is exported into shells, agents' Bash or MCP processes.

## 5. State directory and the SessionStart prune (REQUIRED change in agent_guard.py)

State lives in `${XDG_STATE_HOME:-~/.local/state}/claude-agent-stack/eq-docker/` (mode 0700; the driver creates it, `LAYOUT=repo` selects it):
`status.env` (0600; `EQ_DOCKER_STATUS=ok|skipped|failed`, `_AT`, `_WHY`, `_SET`, `_PINS_SHA256`, `_VERIFIED_IDS`, `_SPIKE`, `_PROBE`), `image.env`,
`image.json`, `images/<name>.env` (one build record per image and keep profile), `results/{spike,probe,reverify}.<tag>.env`, `logs/*.log`, `work/`
(fresh check copies, 0700, empty between runs), `reverify-out/`, `compare/`.

`dot-claude/hooks/agent_guard.py` `session_start_bookkeeping` (lines 4357-4366) deletes EVERY directory under that root idle for more than
3 days except `usage` and `limits`: it would delete `eq-docker/` (its mtime does not move while nothing is built). Change
`if s in ("usage", "limits"):` to `if s in ("usage", "limits", "eq-docker"):` and its comment to name `eq-docker/` (kept: image records and
verification results that cannot be recreated without a rebuild).
Test (extend `tests/test_stack_usage.py::test_guard_prune_keeps_usage`, which already builds an idle-5-days `usage` and `old-session`): add `eq-docker`
to the tuple of names, create it with a file `status.env`, and assert `(st / "eq-docker" / "status.env").exists()` while `old-session` is gone.
This test fails before the one-word change. (`doctor.sh`'s hook-wiring checks need no change: no hook is added.)

## 6. doctor.sh section

Insert after the `== Platform` section (line ~1026) a section `echo "== Docker isolation (eq-docker)"`. It reads files only, plus bounded docker calls
(`$T docker ...`, the 90 s wrapper the other sections use; `docker` found through `command -v docker` and `$HOME/.docker/bin`).
`S=${XDG_STATE_HOME:-$HOME/.local/state}/claude-agent-stack/eq-docker`; `want_docker=1` iff `$C/stack.env` has an uncommented `EQ_ISOLATION=docker`.

| state | output |
|---|---|
| no `$S/status.env` | `ok    eq-docker: not installed (optional: ./install.sh --with-eq-docker)`; `WARN  EQ_ISOLATION=docker is set in stack.env but eq-docker is not installed` when `want_docker` |
| `EQ_DOCKER_STATUS=ok` | `ok    eq-docker: verified <AT> (set <SET>, spike <SPIKE>, probe <PROBE>)` |
| status ok, docker CLI missing or `docker info` fails | `WARN  eq-docker: Docker not reachable, images not checked (start Docker Desktop / colima)` |
| status ok, docker up, each distinct id of `image.env` (`EQ_DOCKER_IMAGE_PF`, `_CP`, `_CR`) | `docker image inspect --format '{{.Id}}' <id>` equal: `ok    eq-docker image <id first 12> present`; else `FAIL  eq-docker image <id12> is not in Docker (pruned, rebuilt or another daemon): run ./install.sh --with-eq-docker` |
| status ok but `image.env` lacks `EQ_DOCKER_IMAGE_PF` | `WARN  eq-docker: image.env has no EQ_DOCKER_IMAGE_PF (rerun the install)` |
| `results/probe.*.env` with `PROBE_RESULT=FAIL` (or `spike`) | `WARN  eq-docker: probe FAIL at <AT> (<FAILS> rows): see $S/logs/probe.log` |
| `EQ_DOCKER_STATUS=skipped` | `ok    eq-docker: skipped at <AT> (<WHY>)`; `WARN` instead when `want_docker` |
| `EQ_DOCKER_STATUS=failed` | `WARN  eq-docker: install failed at <AT>: <WHY> (logs: $S/logs)` |
`reverify` is a maintainer result: `results/reverify.*.env` PASS gives `ok    eq-docker: reverify PASS`, anything else prints nothing (it is not an install check).
Never print a path outside `$S` and never source a state file (parse `KEY=` lines with `sed -n 's/^KEY=//p'`, as `eq-docker.sh`'s `env_get` does).

## 7. Manifest key `eq_docker`, `--restore`, removal

After every run of the step (any exit code) `eq_docker_manifest rc` stores in `$C/.stack-manifest.json` (same read-modify-write pattern as `deduped()`, line
2899; preceded by `ensure_backup; python3 "$STATE_PY" record "$B" file .stack-manifest.json`; not in `--dry-run`):
```
"eq_docker": {"status": "ok|skipped|failed", "at": "<UTC ISO>", "why": "<status.env WHY, or 'eq-docker exit N'>", "set": "min|dl|full",
              "image_ids": {"pf": "sha256:...", "cp": "sha256:...", "cr": "sha256:..."}, "pins_sha256": "<64 hex>",
              "state_dir": "<abs path>", "env_image": "<EQ_IMAGE written to stack.env, or empty>"}
```
(values copied from `status.env`/`image.env`; missing ones are empty strings). `install_state.py` keeps unknown manifest keys (it only
validates `files`); add a unit test in `tests/test_install_state.py` that a later plain install keeps the key.
`--restore` puts `stack.env` and `.stack-manifest.json` back from the backup (the key disappears with it) but touches neither the Docker images nor
`$STATE_ROOT/eq-docker/`: say so in `--restore`'s output when the manifest being replaced holds `eq_docker`, and name the removal command:
`bash lib/eq-docker/eq-docker.sh uninstall --yes [--purge]` (images and records; `--purge` also the state directory, only when it is named
`eq-docker`; `--prune-cache` also runs `docker builder prune -f`, which cannot be limited to these images). There is no `install.sh` flag for removal on purpose.

## 8. Tests to add (names fixed; all hermetic: fake `docker`/`brew` first on PATH, scratch HOME and `XDG_STATE_HOME`, `EQ_DOCKER_APP_DIRS=""`, `EQ_DOCKER_BIN_DIRS=""`, `EQ_BREW_DIRS=""`)

Already written and passing in the staging (copy as they are): `tests/test_eq_docker.py` (the driver: docker missing, brew missing, daemon down, wrong
architecture, consent declined, `--yes` alone is not consent, `--install-docker`, `--docker-via colima`, brew failure, unknown cask, Docker.app present -> no cask
install, dry-run creates nothing, idempotent build, spike/probe skipped while the verified ids are unchanged and rerun after a rebuild or `--force-verify`, `--check`,
`status`, `print-env`, `uninstall`, `--purge`, pin placeholder -> exit 13, build/spike/probe failure exit codes, usage errors, bash -n, shellcheck, no push/sudo, PINS
agree with the Dockerfiles) and `tests/test_eq_docker_isolation.py` (the isolation-side proofs of the R1 findings).

New, for the installer (`tests/test_install_eq_docker.py`; run install.sh through `tests/test_install_state.py`'s `_scratch_repo` / `_install` helpers, with `--no-deps --no-profile --yes`, `STACK_EQ_DOCKER_SET=full`):
1. `test_default_install_never_touches_docker_or_brew` - no `--with-eq-docker`: both fakes' logs empty, no `eq_docker` manifest key, no step-10b heading.
2. `test_option_errors` - `--install-docker` alone, `--docker-via pip`, `--docker-via` with no value, `--install-docker --with-eq-docker --no-deps`, `--diff --with-eq-docker`: exit 2, nothing written.
3. `test_docker_missing_is_warn_and_skip` and `test_daemon_down_is_warn_and_skip` - install.sh exit 0, manifest `eq_docker.status == "skipped"`, no `buildx build`.
4. `test_yes_is_not_consent_to_install_docker` and `test_install_docker_flag_is_consent` - brew fake: `--yes` -> no `brew install`; `--install-docker` -> exactly `install --cask docker-desktop`; installer still exit 0.
5. `test_docker_app_present_no_cask_install` - `EQ_DOCKER_APP_DIRS` pointing at a scratch `Docker.app`.
6. `test_dry_run_prints_would_and_creates_nothing` - the `would:` line, no state dir, no manifest change, no stack.env change.
7. `test_happy_path_records_manifest_env_and_doctor` - fake daemon up: state `status.env` ok, manifest `eq_docker` as in section 7, stack.env gets `EQ_ISOLATION=docker` and `EQ_IMAGE=sha256:...`, `bin/doctor.sh` prints the `ok` lines of section 6.
8. `test_stack_env_lines_are_not_clobbered` - a user `EQ_IMAGE=custom` stays, a user `EQ_ISOLATION=` empty line is filled, mode stays 0600, one backup holds the old file.
9. `test_second_install_is_idempotent` - no second build, spike/probe skipped, stack.env byte-identical.
10. `test_pin_placeholder_warns_and_installs_the_rest` - `STACK_EQ_DOCKER_SET=min` with the shipped placeholder: install.sh exit 0, `eq_docker.status == "failed"`, why `unresolved pin`.
11. `test_restore_puts_back_stack_env_and_manifest_but_not_images` - `--restore` after the happy path: stack.env and manifest are the pre-install ones, the fake daemon still lists the image, `$STATE_ROOT/eq-docker/status.env` still exists, the output names `eq-docker.sh uninstall`.
12. doctor cases (one test each, state files written by the test): not installed -> `ok`; ok + image present -> `ok`; ok + image missing -> `FAIL`; ok + docker down -> `WARN`; skipped with and without `EQ_ISOLATION=docker`; failed -> `WARN`; probe FAIL result -> `WARN`.
13. `test_manifest_key_survives_a_later_plain_install` (in `tests/test_install_state.py`) and the agent_guard keep test of section 5.
`tests/install_smoke.sh`: one case `eq-docker` (after the existing option cases): `--with-eq-docker --no-deps --no-profile --yes` with the fakes on PATH, `STACK_EQ_DOCKER_SET=full`: asserts exit 0, the
`10b/11` heading, `status.env` ok under the scratch `XDG_STATE_HOME`, a second run skips the build, and (belt and braces, like the existing fingerprint) the REAL
`~/.local/state/claude-agent-stack/eq-docker` is not created. The smoke must never see the real docker: the fakes come first on PATH and `EQ_DOCKER_BIN_DIRS`, `EQ_DOCKER_APP_DIRS`, `EQ_BREW_DIRS` are empty.
Run the whole `pytest -q tests` and `bash tests/install_smoke.sh` before committing; one security review (installer, consent, Homebrew, network) is required by the stack's triggers.

## 9. Maintainer steps before the minimal set ships (not integration)

`lib/eq-docker/PINS` holds two placeholders by design (nothing was invented; both registries answered 403 to the staging agent):
- `BUSYBOX_SHA256=UNSET`: run `bash build.sh --resolve-busybox --write-pin` (RUNBOOK_MINIMAL.md section 1), review the printed Debian package version, commit PINS and `Dockerfile.minimal`.
- `DISTROLESS_BASE=UNSET`: needed only for the distroless candidate: `docker buildx imagetools inspect gcr.io/distroless/cc-debian13:nonroot`, put the top-level digest in PINS and the ARG of `Dockerfile.distroless`, record date and source.
Then RUNBOOK_MINIMAL.md sections 2-8 decide the image set (keep profile, one image or two) and fill the real numbers. Until they are filled, `eq-docker.sh`'s `DEFAULT_SET=min` makes
`install` exit 13 ("a pin in PINS is still a placeholder"), which the installer reports as a warning. The integration commit must therefore either set `DEFAULT_SET=full` in
`eq-docker.sh` (the full Debian image needs no placeholder and was built once on the host) and flip it to `min` in the maintainer's commit, or wait for the maintainer step. State which in the commit message.

Sections 10-13 below are the scope extensions X1-X5 and X7 (profiles, tools manifest, compose, WALL tunnel mount). They add files to section 1's copy list (`lib/eq-docker/**` already covers them): `TOOLS.toml`, `tools.sh`, `verify-tools.sh`,
`eq-compose.sh`, `compose.yaml`, `compose.wall.yaml`, `Dockerfile.toolchains`, `tc/*`, `probe.d/*`; and to the test list: `tests/test_eq_docker_toolchains.py`, `tests/test_eq_docker_compose.py` (needs PyYAML: `uv run --with pytest --with pyyaml pytest -q tests`).
Modes 100755 for `tools.sh verify-tools.sh eq-compose.sh tc/*.sh probe.d/*.sh`; `TOOLS.toml`, `compose*.yaml`, `Dockerfile.toolchains` stay 100644.

## 10. The installer flow with profiles (X3, X5)

New installer option: `--eq-docker-profiles=LIST` (also `--eq-docker-profiles LIST`), valid only with `--with-eq-docker` (usage error otherwise, exit 2, same style as section 2). `LIST` is a comma list of `TOOLS.toml` profiles (`core node rust go julia haskell jvm db mongo`, and `all` =
every profile not marked explicit, so not `mongo`, not the measurement-only `candidates`). The step passes it as `eq-docker.sh install --profiles LIST`; `core` is always added by the driver (the minimum the item classes PF, CP and CR need; ES, RS, DS and OE run no model-written code and have no image).
Without the option the installer passes `--profiles core` (the default = the minimum); every other profile is opt-in. A knob `STACK_EQ_DOCKER_PROFILES` is the stack.env-free equivalent for tests. `--eq-docker-profiles` is rejected together with `STACK_EQ_DOCKER_SET`.

The flow `eq-docker.sh install` runs (all of it staged and tested; every step failing = a warning and a skip, never a failed install; Docker is never installed without consent):

| step | what happens | non-fatal outcome |
|---|---|---|
| 1 docker | CLI present, or the Homebrew offer of section 3 (`brew install --cask docker-desktop` only after a typed `y` or `--install-docker`; `--yes` alone is never consent; skipped when `/Applications/Docker.app` exists) | exit 10, status `skipped` |
| 2 daemon | bounded wait: `--wait-daemon SECONDS` (default `EQ_DOCKER_WAIT_S`, else 90 s: an estimate, not measured), polling every `EQ_DOCKER_WAIT_POLL` s (default 3); nothing is started for the user; no wait in `--dry-run`; the architecture must be aarch64 | warn and skip (10) |
| 3 build | `build.sh --profiles LIST`: PINS checked against the Dockerfiles, `TOOLS.toml` checked (a `PLACEHOLDER` in a selected tool stops with exit 13 and the command that resolves it), idempotent (an image whose recorded ID and inputs hash still match is skipped), every image labelled `eq.tools.sha256` | 12 build failed, 13 unresolved pin |
| 4 digests | images are built locally, nothing is pulled, so no registry digest of an eq image exists to compare; the digests that are verified are the base image's (PINS: `docker buildx imagetools inspect` before the build), every tool archive's sha256 (checked in the discarded builder stage before extraction) and the built image's ID (recorded in `images/NAME.env`, rechecked before every run by `eq_require_image`) | stops the build |
| 5 verify | `verify-tools.sh --images --deep --inspect --profiles LIST` (labels, in-image locks, every tool file re-hashed from outside, unprivileged user, no EXPOSE/VOLUME/ENTRYPOINT/HEALTHCHECK), then `--smoke` for the extension images | exit 16 |
| 6 spike, probe | `spike.sh --builtin`, `probe.sh` (with `probe.d/` hooks) on the PF and CP images; skipped while the verified image IDs and the PINS+TOOLS hash are unchanged (`--force-verify` reruns them) | 14, 15 |
| 7 publish | `status.env` (adds `EQ_DOCKER_STATUS_PROFILES`), `image.env` (adds `EQ_DOCKER_PROFILES`, `EQ_<IMAGE>_TAG/_ID`); `print-env` prints `EQ_ISOLATION=docker` and `EQ_IMAGE=` only when status is ok | |

`install.sh` then writes `EQ_ISOLATION` / `EQ_IMAGE` into `stack.env` without clobbering (section 4), the manifest key `eq_docker` (section 7, which gains `"profiles": "core,node"` and the per-image ids of `image.env`), and the doctor.sh row (section 6; add: `ok    eq-docker profiles: <list>` and, per
selected profile, a `docker image inspect` of each recorded id with the same ok/FAIL rule as the PF image). Idempotent: a second run builds and verifies nothing. `--dry-run` reads only (`docker info`, `docker image inspect`) and prints the plan; `--check` (`eq-docker.sh check --profiles LIST`) compares records,
IDs, inputs hashes and the manifest without building (exit 0 ok, 11 not ok, 10 no docker); `--uninstall` is `eq-docker.sh uninstall --yes [--purge]` (section 7: removes every image `build.sh --set all` knows, extension images included, and the records). Exit codes: section 3's table plus 16 (tools verification or an
extension smoke test failed). Tests: `tests/test_eq_docker.py` (the driver), `tests/test_eq_docker_toolchains.py` (profiles, wait, verification, hooks). The installer-level tests of section 8 gain two cases: `--eq-docker-profiles=core,node` reaches `eq-docker.sh` as `--profiles core,node`, and the option without `--with-eq-docker` is exit 2.

## 11. Compose (X1, X3)

`compose.yaml` is the declarative front-end of the images; `eq-compose.sh` is the only supported way to start it (`bash eq-compose.sh [--profiles LIST] [--work DIR] [--tunnel CHANNEL_DIR] ACTION`, actions `config run up down ps logs`). It never mounts anything the compose files do not name, never passes the host environment on, and before `run`/`up` it runs
`verify-tools.sh --images --deep` for the selected profiles (exit 11 for a stale, missing or tampered image, 13 for a pending pin), takes each image reference from its verified build record (refusing a tag whose ID is not the recorded one), generates the per-run database credential into its own process environment (24 random bytes as hex,
never printed, never in argv or a file) and removes the project (containers and the network) when the run ends, also after a failure. Rules every service keeps (tested statically in `tests/test_eq_docker_compose.py`, proved in a container by `probe.sh`): read-only root, `cap_drop: [ALL]`,
`no-new-privileges`, `init`, pids/memory/swap/cpu limits, an unprivileged uid >= 10000, no published port, no host network, no `privileged`, no docker socket, tmpfs scratch with `nosuid,nodev` and a size cap (database data `noexec`), images only by interpolated reference, the only host mount the per-run work directory (`${EQ_WORK_DIR}`, bind, `read_only: true`,
long syntax = `--mount type=bind,...,readonly`). No network (`network_mode: none`) for everything that runs model-written code, except the Python solver `cp-db`, which joins the one `internal: true` network `eqdb` with the database service(s) of its run and reaches them by service name only (`pg`, `mongo`). Services: core `pf cp cr`; one per language `node rust go julia haskell jvm`;
`pg` (profile `db`), `mongo` (profile `mongo`, explicit), `cp-db` (profiles `db`, `mongo`). Check services copy the read-only source into a capped tmpfs `/work` with the harness's own copy prefix; language services mount the work copy read-only at `/work` and send every output to `/tmp` through the image ENV (their images have no shell). Database servers: tmpfs data, per-run credential,
scram authentication, healthcheck, nothing from the host. Cross-run leakage: no volume exists and the tmpfs and the network die with the project, so no byte survives a run (to be proved with a real run: RUNBOOK_MINIMAL.md section 16). Everything user-run is in RUNBOOK_MINIMAL.md sections 12-17.

## 12. Design: which tools, baked or mounted, binary-only rules, conflicts, interim defaults (X1-X4)

### 12.1 What each item class needs (read from `harness/eq_harness.py` and `items/*/README.md`)

| class | runs model-written code in a container? | tools its image needs |
|---|---|---|
| PF (Lean proofs) | yes: the check (`bash check_lean.sh Answer.lean`) and the oracle (`uv run --script oracle.py`, `oracle_isolated_classes` PF and CP, `eq_harness.py:216`) | lean + Mathlib module files, uv, python, bash and perl (`check_lean.sh` is hash-frozen and runs `perl -e` for the timeout), jq (selftest), the lake shim, busybox (copy prefix) |
| CP (code, unit tests) | yes: `python -m unittest` and its oracle | uv, python, bash, busybox, jq |
| CR (code review) | yes, same image as CP | same as CP |
| ES, RS, DS, OE | no: their oracles run on the host | none (no image) |
| EXT: node rust go julia haskell jvm (java, scala) postgresql mongodb | no pool uses them today; the scope extension X3 adds them | one image per toolchain, one per database server |

Default profile `core` = `min-both` (PF) + `min-py` (CP, CR): the minimum. Every other profile is opt-in; `all` never contains `mongo` or `candidates`.

### 12.2 Baked images versus a read-only tools volume (X2.2)

Evaluated both; recommendation: bake each toolchain into its own image on the shared minimal base `eq-base` (glibc closure, `/etc/passwd`, `/etc/group`, mount points; `FROM scratch`; no shell). Reasons: (1) the unit the harness pins is the image ID, so tool bytes are covered by the same identity as everything else, with no second thing to hash before a run;
(2) a volume needs a mount at run time that the container could be tricked into writing (`tools_mount_readonly` and `path_dirs_readonly` rows exist to prove it is not) and a host directory that must be hash-verified before every run (a TOCTOU window between the check and the mount); (3) a volume does not remove the libc problem (dynamic tools still need their libraries inside the container);
(4) layers of `eq-base` are stored once however many language images exist, so the disk cost of one image per tool is the tool tree only. Costs of baking: a change of one tool rebuilds one image (minutes, estimate), and every image carries a lock. Measured sizes and build times are user commands (RUNBOOK_MINIMAL.md section 14 prints them from the records); nothing here is measured.
A volume remains possible later without redesign: it would be a `type: bind` or `volume` mount with `read_only: true` from a hash-verified directory, listed in `compose.yaml` and allowed by the probe; no such mount exists today.

### 12.3 Allowlist, extension and verification (X2.3-X2.5)

Each class gets its own tool set (`TOOLS.toml` `[[image]].tools`, checked against the per-tool `classes` and `profiles` allowlists by `verify-tools.sh`); no host PATH passthrough (the image ENV fixes PATH; probe rows `host_path_not_inherited`, `path_dirs_readonly`, `path_executables_allowlisted`), no docker socket, no host home mount, no network at run time. A new tool = a manifest entry + `build.sh --profiles P` + `verify-tools.sh --images --deep` (the header of `TOOLS.toml` is the procedure);
the installer's image step refreshes from the manifest (the manifest hash is part of every image's inputs hash, so an edited entry rebuilds). The review targets of X2.5 map to checks: tool-volume tampering and a writable mount (`--deep` re-hash from outside, `tools_mount_readonly`), PATH hijack (`path_executables_allowlisted`: every executable on PATH hashes to a lock entry), a forged verdict via an added tool (UNDECLARED in `--images`; a tool outside the manifest cannot be in an image because the Dockerfiles copy only what `TOOLS.toml` lists).
Each tool entry's sha256 is a hash of the archive the url returns, verified in the discarded builder stage before extraction (`tc/fetch-tool.sh`); the WALL policy binds a security-auditor verdict to `tm_image_hash`, so an edited entry invalidates an earlier verdict.

### 12.4 Scratch versus distroless, per image (X1, X3.1, X4)

Rule: a final image is `FROM scratch` (via `eq-base`) holding binaries, their `ldd`-resolved shared libraries, the language's own standard library files, `/etc/passwd` and `/etc/group`. Distroless only wins for a tool that `dlopen`s something `ldd` cannot see (tzdata, an NSS module, a CA bundle) AND whose measured size and smoke result are no worse; no such tool is known, so every image here is scratch-based.
That is a static argument, not a measurement: the user commands that would settle it are RUNBOOK_MINIMAL.md sections 13-15 (size from the records, smoke tests). Package managers, compilers and `curl` exist only in discarded builder stages (`Dockerfile.toolchains`: `tools-fetch`, `tools-build`, `prep`). Docs, man pages, headers and test suites are pruned per entry (`prune` lists; paths are UNVERIFIED until a build passes).
Go, Rust musl and other static output could run on bare scratch; the toolchains themselves are not what runs there, so the toolchain images use `eq-base`.

### 12.5 MongoDB: arm64 availability and licence (X3.2), read 2026-10-05 (`eq-toolchains/TOOLCHAINS.md`, [S28], not re-read today)

- Version: 9.0.2, the newest production release in `downloads.mongodb.org/current.json` (dated 2026-09-17, LTS).
- arm64 Linux builds exist only for Ubuntu 24.04, Ubuntu 22.04, RHEL/Rocky/Alma 8, 9 and 10, and Amazon Linux 2023 (`https://fastdl.mongodb.org/linux/mongodb-linux-aarch64-<target>-9.0.2.tgz`). There is no Debian arm64 build, and Ubuntu 20.04 arm64 stops at 8.x/7.x. The builds are distro-targeted and dynamic; the manifest pins the `ubuntu2404` tgz
  (sha256 `0f823dcb...c72f`, from the `.tgz.sha256` file) and runs it on the Debian trixie glibc closure of `eq-base`: compatibility is UNVERIFIED (the exact library list was not read; `mkrootfs-tc.sh` fails the build on an unresolved library). The Docker Official Image `mongo` is arm64v8 and amd64 only.
- CPU: MongoDB on arm64 requires an ARMv8.2-A or newer microarchitecture. Whether the Docker Desktop VM on your Mac exposes it is UNVERIFIED.
- Licence: SSPL-1.0 (`LICENSE-Community.txt`: "Server Side Public License VERSION 1, OCTOBER 16, 2018"). SSPL is not OSI-approved (general knowledge, not re-checked) and section 13 obliges someone who offers the program as a service to release the service's source under SSPL; redistributing an image that contains `mongod` passes those terms on. Using it privately as a test fixture is the lowest-risk case, but that is a legal judgement for you, not for this spec.
- Consequence in the design: profile `mongo` is explicit-only (never in `all`, never in the default), its tool entries are marked `SSPL-1.0`, and the profile is also pending until the `mongosh` entry is looked up (TOOLCHAINS.md does not cover it). PostgreSQL (PostgreSQL licence) is the default database (`db`).

### 12.6 Conflicts with "binary only" (X4) and the minimal resolution; interim defaults; the pending user decisions

- **C1** The harness's COPY_IN prefix (`/bin/sh -c ... cp -R ...`, `eq_harness.py` `COPY_IN`) needs `/bin/sh` and `cp` in every image that runs checks. Resolution: the pinned static busybox, only in the check images (core) and the two server images; the language images have no shell and take the work copy as a read-only mount (they are not used by `isolate()` today; the day a class needs one, that image gets busybox `sh` and `cp` under the same rule).
- **C2** A database server needs an init step (initdb, the first user) that a shell-less image cannot run. Resolution: busybox with a minimal applet set (`sh rm` for PostgreSQL; `sh sleep rm ls` for MongoDB) and a hash-pinned entry script (`tc/entry-pg.sh`, `tc/entry-mongo.sh`, manifest provenance `in-repo`, sha256 re-checked by `verify-tools.sh`); data on a tmpfs; the credential reaches the server only through the environment of its own container and is unset before the server starts.
- **C3** `check_lean.sh` is hash-frozen and needs bash and perl. Resolution (DEVIATION, pending): the Debian bash and perl-base from the pinned snapshot, copied with their libraries, provenance `distro-package`. No official binary exists for either (GNU and cpan publish source only); the from-source alternatives (bash 5.3 plus patches 001-020, GPG only, no sha256 file; perl 5.44.0, sha256 `3b855066...96c3` from `perl-5.44.0.tar.gz.sha256.txt`) are recorded in the entries' `notes`.
  The same status applies to busybox (no current official arm64 binary; 1.38.0 is listed as unstable) and jq (an official static arm64 binary DOES exist: jq 1.8.2, sha256 `8b85c817...2309`; switching to it is a follow-up that needs a change in `minimal/mkrootfs.sh` and a build to verify).
- **C4** Compiler and runtime standard-library sources are part of the toolchain (Go `src/`, the JDK `lib/modules`, GHC and Julia libraries): they are kept as part of the binary set; only docs, man pages, headers and tests are pruned.
- **C5** Scala: the brief names scala-cli or sbt; both are awkward in a shell-less, network-less image (scala-cli's aarch64 launcher has no checksum file and an unverified linkage and may fetch a JVM or the compiler at run time; sbt is a shell launcher that resolves dependencies over the network). Resolution (INTERIM, pending): the Scala 3 distribution tarball on the shared JDK (`tc-jvm` = Temurin 25 LTS + Scala 3), invoked as `java -cp /opt/scala3/lib/* ...`. The distribution's url and sha256 were not read (TOOLCHAINS.md lists only the tags), so the entry is `PLACEHOLDER` and the `jvm` profile is pending.
- **C6** (found while filling the manifest) `rustc` and `ghc` call a C compiler and linker (`cc`) to produce a program, and a binary-only image has none. The images carry the compilers, but compiling and linking a program in them is not possible; the smoke tests only run `--version`. Options (user decision, only if a pool class will compile Rust or Haskell): add distro binutils and gcc as `distro-package` (large, a deviation), or for Rust use the `-musl` self-contained target with `rust-lld` (unverified). Go (`CGO_ENABLED=0`), Node, Julia and the JVM are not affected.

Interim defaults until the user answers (all reversible, all labelled in `TOOLS.toml` `notes` and RUNBOOK_MINIMAL.md):
1. MongoDB only in the explicit-only profile `mongo`, excluded from `all` and from the default.
2. Debian bash, perl-base, jq and busybox-static recorded as provenance `distro-package` ("INTERIM, pending user decision"); version and sha256 are filled by `build.sh --resolve-tools --write-pin` (trust on first use) and are `PLACEHOLDER` until then.
3. Scala via the Scala 3 distribution tarball + JDK instead of scala-cli or sbt.
Pending decisions, in one place: (a) accept the distro-package deviation for bash, perl, jq and busybox (C3), or build them from source / use the official static jq; (b) the Scala route (C5) and the Scala 3 version whose distribution url and sha256 get pinned; (c) accept SSPL-1.0 for MongoDB, and the `mongosh` source. Additionally open, not decided here: C6 (a linker in the Rust and Haskell images).
Newer upstream versions than the core pins exist (uv 0.12.23, python-build-standalone 20261003); the core pins in `PINS` stay until a re-pin (PINS, Dockerfile ARGs, rebuild, spike, probe, reverify together).

## 13. WALL and the single tunnel mount (X6, X7)

`compose.wall.yaml` adds the one WALL tunnel mount: `${EQ_TUNNEL_CHANNEL}` at `/eq/tunnel` for every service that runs model-written code (never the database servers) and nothing else (no docker socket, host network, extra bind or volume). The source is ONE channel directory, never the tunnel root: `eq-compose.sh --tunnel CHANNEL_DIR` is a required explicit argument with no default (`EQ_TUNNEL_DIR`, the tunnel ROOT the harness and the installer use, is never read), and the directory must be absolute, owned by you, mode 0700, not a symlink, not `$HOME`, named `c` + 32 hex digits, holding the regular file `.channel.json` and no subdirectory (the layout `eq_wall.open_channel` creates, `<tunnel_root>/<run_id>/<channel>`). A root or run directory is refused (exit 2): mounting it would show the container every channel's token and let it post requests as another item or arm (WALL_DESIGN.md section 3 and 12.8; tests `test_only_one_channel_directory_may_be_mounted_never_the_root`, `test_the_tunnel_root_in_the_environment_is_never_a_default_and_never_mounted`). The harness opens a fresh channel per call, so a compose run with the WALL needs a channel opened for it.
`probe_inner.sh` accepts `/eq/tunnel` as the only extra host-backed mount; `probe.d/50-tunnel.sh` (WALL work) proves from inside a container that a second socket, an outbound connection, a host path and a signal to a host process are all blocked. Whether the container needs write access to the tunnel (`read_only: false` in the file today) and the tunnel mechanism are decided in `EQ-T/wall/INSTALLER_WALL.md` (being written by the security-engineer);
the installer behaviour of X7 (WALL enabled by default when `--with-eq-docker` is set up and the reviews are positive, `--no-eq-broker`, the policy file, the doctor row, the install-time test with fakes) is specified there, not here, and this section must be reconciled with it before integration. This spec does not decide whether WALL is on by default.
