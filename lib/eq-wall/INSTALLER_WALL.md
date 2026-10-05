# Installer integration spec: WALL + the ONE tunnel under `--with-eq-docker` (SCOPE X7)

> **Superseded in part (2026-10-05):** the backend is Apple `container`; the option is `--with-eq-container`, the state dir of the
> images `.../claude-agent-stack/eq-container`, the tunnel probe `lib/eq-container/probe.d/50-tunnel.sh` (results
> `results/tunnel.*.env`, field `TUNNEL_IMAGE_DIGEST`). What is implemented is described in CONFIG.md §7 "Container isolation and
> the WALL"; this spec is kept as the design record. Docker-only parts (compose, `--install-docker`) were dropped.

For the integration agent working in the stack repo. M = `/Users/pmrj/ZDone/claude-agent-stack` (work in a worktree).
EQ-T = this staging tree.

This spec extends `EQ-T/isolation/INSTALLER_SPEC.md`: step 10b `eq_docker_step`, the non-clobbering `stack.env`
helper, the manifest key `eq_docker`, the doctor section "eq-docker", the hermetic test helpers `_scratch_repo` /
`_install`, `tests/fake-docker/docker` and `tests/fake-brew/brew`. Integrate that spec first. Agents never run
install.sh, docker or brew for real; every test below is hermetic (fakes first on PATH, scratch HOME and
`XDG_STATE_HOME` / `XDG_CACHE_HOME`).

## 0. The default: ON only if POSITIVE, else opt-in

X7 rule: WALL + its tunnel are enabled by default with `--with-eq-docker` only if all of these hold:
- the security-auditor reviews have no open High/Critical;
- code-reviewer passes;
- the fake tests and mutation checks pass.

That status is a maintainer fact, so it ships as a file, never as an installer guess: `M/lib/eq-wall/REVIEW` (KEY=VALUE,
read with `sed`, never sourced):

```
POSITIVE=0                 # 1 only when every line below holds; set by the maintainer, in the same commit as the refs
SECURITY_AUDITOR_REF=      # review id/path of the security-auditor review of lib/eq-wall + the tunnel
OPEN_HIGH_CRITICAL=        # integer from that review (must be 0)
CODE_REVIEWER_REF=         # review id/path of the code-reviewer pass
TESTS_REF=                 # `pytest lib/eq-wall/tests` + `mutations.py` output (all KILLED) at this commit
```

Today (2026-10-05) the staging tree has had one static security-auditor review (N23) and one code-reviewer pass (N24),
both "pass with fixes"; the fixes are applied (WALL_DESIGN §12 item 10) but not yet re-reviewed, and the integration
diff has not been reviewed at all. So the shipped value is `POSITIVE=0` and the WALL is **opt-in**
(`--with-eq-broker`). The open findings go to the user as `NEXT: ASK USER` (see this brief's report).

`wall_default()` returns `on` iff all of these hold: `POSITIVE=1`, `OPEN_HIGH_CRITICAL=0`, and every `*_REF`
non-empty. Otherwise it returns `off`. A malformed or missing file means `off`. `--with-eq-docker` itself stays
opt-in.

## 1. Files copied (EQ-T → M)

| source | destination | mode |
|---|---|---|
| `wall/eq_wall.py`, `wall/eq_wall_client.py` | `lib/eq-wall/` | 100755, 100644 |
| `wall/policy.default.toml` | `lib/eq-wall/policy.default.toml`, with ONE line rewritten: `path = "../isolation/TOOLS.toml"` becomes `path = "../eq-docker/TOOLS.toml"` (N24#2: the path is relative to the policy file, and the repo's manifest is `lib/eq-docker/TOOLS.toml`; the staging path would resolve to a missing `lib/isolation/TOOLS.toml`, so `manifest_tools()` returns None, `check-policy` skips the overlap check and, once any kind is allowed, every missing-tool request is denied `manifest_unavailable`). That line is the only allowed difference; `policy_sha256` / `config_sha256` are computed from the repo copy, never copied from staging | 100644 |
| `wall/WALL_DESIGN.md`, `wall/AMENDMENT_PROPOSAL.md`, this file | `lib/eq-wall/` | 100644 |
| `wall/tests/{conftest.py,test_wall.py,mutations.py,mutations.out}` | `lib/eq-wall/tests/` (relative imports unchanged: `WALL = tests/..`) | 100644 |
| new `lib/eq-wall/REVIEW` (§0) | `lib/eq-wall/REVIEW` | 100644 |
| `isolation/probe.d/50-tunnel.sh` | `lib/eq-docker/probe.d/50-tunnel.sh` (beside `lib.sh`; `probe.sh` section G runs it as a hook) | 100644 |

After the copy, `diff -r` of each pair must be empty, except the one `[tools_manifest] path` line of the policy.

**Interpreter (N24#1).** `eq_wall.py` needs Python 3.11+ (`tomllib`, `datetime.UTC`); install.sh only requires a
`python3` of 3.8+ (`M/install.sh` step 1). Every installer and doctor call of `eq_wall.py` therefore uses the stack's
own interpreter, never `python3` from PATH: in install.sh `"$C/bin/stack-python" -I …` (the uv-managed Python 3.13
link made after step 6, `STACK_PYTHON`, install.sh "stack-python (S2)"), in doctor.sh the rendered `__PYTHON3__`.
The WALL step runs after that link exists; if `"$C/bin/stack-python" -c 'import tomllib'` fails, status `failed`, why
`stack-python unusable`.

The harness finds the broker through `EQ_WALL_DIR` (or its search path, `../lib/eq-wall` from the harness dir), and
checks its bytes against the frozen `flags.json` before importing it. The repo copy is the only source: nothing is
copied into `~/.claude`.

## 2. install.sh options

New variables beside `WITH_EQ_DOCKER=0`: `EQ_BROKER=default`. Values: `default` = follow `wall_default()`; `on` =
`--with-eq-broker`; `off` = `--no-eq-broker`.

Usage lines (after the `--with-eq-docker` block):

```
  --no-eq-broker          with --with-eq-docker: do not set up the WALL (host-access broker) and its tunnel
  --with-eq-broker        with --with-eq-docker: set up the WALL even though lib/eq-wall/REVIEW is not positive
```

Parsing: `--no-eq-broker) EQ_BROKER=off ;;`, `--with-eq-broker) EQ_BROKER=on ;;`. Errors (exit 2, nothing written):
- either flag without `--with-eq-docker`: `--no-eq-broker/--with-eq-broker work only with --with-eq-docker`;
- both together: `--no-eq-broker and --with-eq-broker contradict each other`.

`--yes` / `--no-prompt` change nothing here: there is no prompt, and the default comes from §0.

## 3. Step `10c/11 WALL (host-access broker + tunnel)`: `eq_wall_step()`

Runs right after `eq_docker_step`, only when `WITH_EQ_DOCKER=1` AND `eq_docker_step` ended with `EQ_DOCKER_STATUS=ok`.
A skipped or failed eq-docker prints `note "WALL skipped: eq-docker is not installed"` and sets status `skipped`.
Any failure in this step is `warn` + status `failed` + WALL off. It is never fatal: the installer exit code is
unchanged.

```bash
eq_wall_step() {
  say "10c/11 WALL (host-access broker + tunnel)"
  local want; want=$(eq_wall_decision)            # on|off from EQ_BROKER and wall_default(); prints why
  local TUN="${XDG_CACHE_HOME:-$HOME/.cache}/claude-agent-stack/eq-tunnel"
  local WST="${XDG_STATE_HOME:-$HOME/.local/state}/claude-agent-stack/eq-wall"
  local POL="$HERE/lib/eq-wall/policy.default.toml"
  if [ "$DRY_RUN" = 1 ]; then
    note "would: WALL $want (default: $(wall_default); --no-eq-broker / --with-eq-broker), tunnel root $TUN (0700), state $WST (0700), policy $POL (default deny)"
    return 0
  fi
  [ "$want" = on ] || { write_wall_status off "$why"; note "WALL off ($why)"; return 0; }
  ...
}
```

Steps when on:
1. **Directories.** `mkdir -p` then `chmod 700` for `$TUN` and `$WST`. Refuse (status `failed`) if either is a
   symlink, not owned by the user, `$HOME`, or contains the other: run `"$C/bin/stack-python" -I
   "$HERE/lib/eq-wall/eq_wall.py" check --tunnel-root "$TUN" --state "$WST" --policy "$POL" --verdicts
   "$WST/verdicts.jsonl" --consents "$WST/consents.jsonl"` and require exit 0 (`roots`, `policy`, `verdicts`,
   `consents` rows PASS). Never create, copy or edit `verdicts.jsonl` / `consents.jsonl`: they are the user's
   (`eq_wall.py verdict-add` / `consent-add`, TTY only).
2. **Policy.** The default-deny file in the repo, not copied. `"$C/bin/stack-python" -I
   "$HERE/lib/eq-wall/eq_wall.py" check-policy "$POL"` must exit 0, and its first line gives `policy_sha256`.
3. **Config hash.** `"$C/bin/stack-python" -I "$HERE/lib/eq-wall/eq_wall.py" config-hash --policy "$POL"` gives
   `config_sha256`; record
   it in the manifest. The harness freezes the same value into `flags.json` with `eq_harness.py flags --wall-policy
   "$POL"`. That is the user's pre-registration step, not the installer's.
4. **Tunnel probe.** eq-docker's probe already ran `probe.sh`. Its section G hook `probe.d/50-tunnel.sh` writes
   `$EQ_STATE_DIR/results/tunnel.<image>.env` (`TUNNEL_RESULT=PASS|FAIL`, `TUNNEL_FAILS`). WALL on requires
   `TUNNEL_RESULT=PASS` for every image in `image.env`. Otherwise status `failed`, why `tunnel probe FAIL (<n> rows)`.
5. **stack.env** (non-clobbering helper of INSTALLER_SPEC §4; mode 0600 kept; backup first). Write `EQ_WALL=on`,
   `EQ_TUNNEL_DIR=$TUN`, `EQ_WALL_STATE_DIR=$WST`, `EQ_WALL_DIR=$HERE/lib/eq-wall`. When off, write `EQ_WALL=off`
   only. Not added to `STACK_EXPORT`: the harness defaults are the same paths. A user who moves them must export
   them; the doctor row says so.
6. **Agent-write protection.** `dot-claude/settings.json` already has `__STACK_STATE__` and `__STACK_CACHE__` in
   `sandbox.filesystem.denyWrite`, so the state dir and the tunnel root are not writable by sandboxed agent Bash.
   Add to `permissions.deny`, so that Claude's file tools cannot touch the user's stores, the receipt or the audit
   logs:
   - `"Edit(//__STACK_STATE__/eq-wall/**)"`
   - `"Write(//__STACK_STATE__/eq-wall/**)"`
   - `"Read(//__STACK_STATE__/eq-wall/**)"`

   Whether Claude Code enforces the `//` absolute form on every file tool is **unverified** without a real `claude`.
   Add a `doctor.sh` lint that the three entries are present after placeholder substitution. This is part of
   WALL_DESIGN §12 item 2; it is not a complete fix.
7. **Manifest** key `eq_wall` (beside `eq_docker`):
   `{"status": "on|off|skipped|failed", "at": "<utc>", "why": "...", "default": "on|off", "flag": "default|on|off",
   "tunnel_dir": "...", "state_dir": "...", "wall_dir": "...", "policy_sha256": "...", "broker_sha256": "...",
   "client_sha256": "...", "config_sha256": "...", "tunnel_probe": "PASS|FAIL|none"}`. `--restore` puts it back like
   `eq_docker`.

   Removal never deletes the state dir: audit logs, verdicts and consents are evidence. It prints the path for the
   user to remove.
8. **Status file** `$WST/status.env` (0600): `EQ_WALL_STATUS`, `_AT`, `_WHY`, `_CONFIG_SHA256`. Read by doctor.

Closing "Next:" list: `· WALL <on|off>: freeze it with eq_harness.py flags --wall-policy …; grants are yours only:
eq_wall.py verdict-add / consent-add (terminal)`.

## 4. doctor.sh section `== WALL (eq-wall)`

Uses `ok` / `warn` / `fail`. `W=${EQ_WALL_STATE_DIR from stack.env, else ${XDG_STATE_HOME:-$HOME/.local/state}/claude-agent-stack/eq-wall}`,
`T=` likewise for `EQ_TUNNEL_DIR`.

| condition | row |
|---|---|
| no `$W/status.env` | `ok    WALL: not set up (optional: ./install.sh --with-eq-docker [--with-eq-broker])` |
| `EQ_WALL_STATUS=off` | `ok    WALL: off (<WHY>)` |
| status on, `$T` and `$W` real dirs owned by you, mode exactly 0700 | `ok    WALL tunnel root <T> 0700` / `FAIL  WALL tunnel root <T> is <mode or symlink or owner>: chmod 700 or remove it` |
| status on, every regular file under `$T` and `$W` is 0600 (`find "$T" "$W" -type f ! -perm 600`) | `ok    WALL files 0600` / `FAIL  WALL files not 0600: <first 3 paths>` |
| status on, no socket, FIFO or symlink under `$T` (`find "$T" ! -type d ! -type f`) | `ok    WALL tunnel holds no special files` / `WARN  stale special file(s) in the tunnel: <paths> (the broker removes them unread; remove stale run dirs by hand)` |
| status on, `__PYTHON3__ -I "$EQ_WALL_DIR/eq_wall.py" check --tunnel-root T --state W --policy <EQ_WALL_POLICY or default> --verdicts W/verdicts.jsonl --consents W/consents.jsonl` (the rendered stack interpreter, never `python3` from PATH: N24#1) | exit 0: `ok    WALL up: roots, policy (default deny\|<kinds>), stores intact`; else `FAIL  WALL check: <first FAIL row>` |
| status on, `__PYTHON3__ -I "$EQ_WALL_DIR/eq_wall.py" config-hash --policy <policy>` equals `_CONFIG_SHA256` | `ok    WALL config <first 12>` / `WARN  WALL config changed since install (policy or broker edited): re-run ./install.sh --with-eq-docker; a frozen flags.json will refuse runs` |
| status on, `$W/tunnel_probe.json` | `ok    WALL tunnel probe PASS (<at_utc>)` / `WARN  WALL tunnel probe FAIL or missing: eq_harness.py isolation-probe` |
| a broker process for no live run (`pgrep -f "eq_wall.py serve"` while no harness runs) | `WARN  WALL broker still running: pid <n>` |
| status on, the three `permissions.deny` entries of §3.6 present in `~/.claude/settings.json` | `ok    WALL stores denied to agent file tools` / `WARN  …` |
| `EQ_WALL_STATUS=failed` | `WARN  WALL: setup failed at <AT>: <WHY>` |

## 5. Tests (names fixed; hermetic)

**`tests/fake-docker/docker` addition.** In the `run` case, an argv containing `probe-tunnel --inner` emulates the
tunnel container:
- print `T|<row>|PASS|fake` for each of the 10 rows in `TUNNEL_PROBE_REQUIRED`: `tunnel_single_host_mount`,
  `eq_namespace_single`, `tunnel_writable`, `no_docker_or_host_service_socket`, `outbound_blocked`,
  `host_paths_absent`, `sibling_channels_invisible`, `host_signal_blocked`, `own_pid_namespace`, `no_inherited_fds`;
- write `probe` into `<host source of the target=/eq/tunnel mount>/req-probe.json` (the round-trip positive control);
- knobs `FAKE_TUNNEL_OMIT="a b"` and `FAKE_TUNNEL_FAIL="a b"` drop rows or report them as FAIL, as
  `FAKE_PROBE_OMIT` / `FAKE_PROBE_FAIL` do;
- log the mount list, so tests can count mounts.

**`tests/test_install_eq_wall.py`.** Through `test_install_state.py`'s `_scratch_repo` / `_install`, with `--no-deps
--no-profile`, `STACK_EQ_DOCKER_SET=full`, the fakes first on PATH, and a test-written `lib/eq-wall/REVIEW` in the
scratch repo:
1. `test_fresh_yes_install_with_positive_review_lands_wall_on` (the X7 install-time test). `REVIEW` positive. Fresh
   `--with-eq-docker --yes`: exit 0; manifest `eq_wall.status == "on"`; stack.env `EQ_WALL=on` plus the three paths
   (0600). The tunnel root exists, 0700, owned, empty: the single tunnel, with channels created per call. The state
   dir is 0700. The fake docker's tunnel `run` has exactly one `--mount` whose target is `/eq/tunnel`, and its
   source is a channel dir `…/<32 hex>/c<32 hex>`, never the root. No `/var/run/docker.sock`, no `--network host`,
   no `--pid`/`--ipc host`, no `-v`. `doctor.sh` prints the `ok` rows of §4.
2. `test_everything_outside_the_policy_is_denied` (same install). Import `lib/eq-wall/eq_wall.py` from the scratch
   repo. Using the installed `EQ_TUNNEL_DIR` / `EQ_WALL_STATE_DIR`, a fresh run id and nonce, `prepare_run`,
   `open_channel` and a `Broker` on the installed policy, write one request of each kind (missing-tool, web-research,
   other) through `eq_wall_client.build_request`. `poll_once` must give `denied`, code `kind`, for all three, and
   `verify_audit` must hold. Also check that `verdicts.jsonl` / `consents.jsonl` were not created by the install.
3. `test_default_review_not_positive_leaves_wall_off`: the shipped `REVIEW` (`POSITIVE=0`). `eq_wall.status ==
   "off"`, why `review not positive (opt-in: --with-eq-broker)`, no tunnel root created, stack.env `EQ_WALL=off`.
4. `test_with_eq_broker_opts_in_despite_review`: `POSITIVE=0` plus `--with-eq-broker` gives status on, as in test 1.
5. `test_no_eq_broker_opts_out`: positive `REVIEW` plus `--no-eq-broker` gives status off and no tunnel root.
6. `test_broker_flags_need_eq_docker_and_do_not_mix`: each flag alone, and both together, exit 2 with nothing
   written.
7. `test_dry_run_shows_the_wall_default_and_creates_nothing`: `--dry-run --with-eq-docker` prints `would: WALL on`
   (positive) or `would: WALL off` (shipped). No tunnel root, no state dir, no stack.env or manifest change.
8. `test_tunnel_probe_fail_turns_the_wall_off`: positive `REVIEW` plus `FAKE_TUNNEL_FAIL=outbound_blocked`. Install
   exit 0, `eq_wall.status == "failed"`, why names the probe, stack.env `EQ_WALL` not `on`.
9. `test_tunnel_probe_missing_row_is_a_fail`: `FAKE_TUNNEL_OMIT=host_signal_blocked`, same as test 8.
10. `test_unsafe_preexisting_dirs_are_refused`: a symlinked `eq-tunnel`, or a 0755 `eq-wall` owned by the user, gives
    status `failed` (or chmod to 0700 for an owned real dir: pick one and pin it). Nothing is written through the
    symlink.
11. `test_second_install_is_idempotent_and_keeps_user_stores`: a user-written `verdicts.jsonl` survives byte-identical;
    stack.env is unchanged on the second run.
12. `test_restore_keeps_audit_logs`: `--restore` after test 1. Manifest and stack.env come back; `$WST/audit/` is
    untouched; the output names the path.
13. Doctor cases, one each (§4 rows): not set up; off; on and healthy; tunnel 0755; a 0644 file; a stale socket;
    check FAIL (a broken `verdicts.jsonl` chain); config changed; probe receipt missing.
14. `test_wall_step_uses_stack_python` (N24#1): positive `REVIEW`, and a `python3` shim first on PATH that reports
    Python 3.9 (`sys.version_info` (3, 9); it passes install.sh's 3.8+ prerequisite) and fails on `import tomllib`.
    Fresh `--with-eq-docker --yes`: exit 0, manifest `eq_wall.status == "on"`, and the shim's log shows it was never
    asked to run `eq_wall.py`. The doctor section prints no `FAIL` with the same shim on PATH.
15. `test_installed_policy_finds_the_tools_manifest` (N24#2): after test 1's install, `lib/eq-wall/policy.default.toml`
    differs from `EQ-T/wall/policy.default.toml` in the `[tools_manifest] path` line only (`../eq-docker/TOOLS.toml`);
    `eq_wall.load_policy(...).manifest_path` is `lib/eq-docker/TOOLS.toml` and exists; `eq_wall.manifest_tools(...)`
    is not None and non-empty; `eq_wall.py check-policy` exits 0; the manifest's `policy_sha256` equals the sha256 of
    the repo copy. With a test policy allowing `missing-tool` for a tool listed in that manifest, the request is
    denied `tools_manifest` (never `manifest_unavailable`).

**`tests/install_smoke.sh`.** Case `eq-wall`: `--with-eq-docker --with-eq-broker --no-deps --no-profile --yes` with
the fakes. Assert exit 0, `EQ_WALL=on`, tunnel root mode `drwx------`, and the `== WALL (eq-wall)` section with no
`FAIL`.

**Suite.** `uv run --no-project --with pytest pytest -q lib/eq-wall/tests` and `uv run --script
lib/eq-wall/tests/mutations.py` (every mutant KILLED) join the repo's test instructions. Run `pytest -q tests` and
`bash tests/install_smoke.sh` before committing.

Review triggers fired (installer, permissions, untrusted input, IPC): one security-auditor review of the integration
diff, plus a code-reviewer pass. Those two reviews, together with this tree's own, are what flip `REVIEW` to
`POSITIVE=1`.

## 6. Optional hardening the user may choose (not default)

A size-capped tunnel root closes WALL_DESIGN §12 item 1: an APFS volume with a quota, or a fixed-size sparse disk
image mounted at `$TUN`, created by the user. The installer could offer `--eq-tunnel-quota <MiB>`, which runs
`hdiutil create -size <MiB>m -fs APFS -type SPARSE … && hdiutil attach -mountpoint "$TUN" -nobrowse …` and records
the image in the manifest. That is an externally visible system change, so it needs explicit consent, as for
Docker; it is not implemented or tested here.

## 7. Compose (devops-engineer's files)

`isolation/compose.wall.yaml` and `eq-compose.sh --tunnel` must mount ONE channel dir, never the tunnel root
(WALL_DESIGN §3, §12 item 8, severity High if used). Keep `read_only: false`: the container writes requests. Do not
default `--tunnel` from `EQ_TUNNEL_DIR` (the root). As read 2026-10-05 this is done in `isolation/` (`--tunnel`
validated as ONE channel dir, no default, `up` refused with `--tunnel`; WALL_DESIGN §12 item 8). The harness path
(`isolate(tunnel=…)`) stays the supported one.
