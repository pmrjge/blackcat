# WALL: the host-access broker and the ONE tunnel (SCOPE X6 + X7)

> **Backend note (2026-10-05, USER decision):** the isolation backend is Apple `container` (CLI 1.5.0), not Docker. Read
> "Docker" below as "the container backend": the tunnel (mechanism dir-v1) is the ONE read-write bind of a channel directory
> at `/eq/tunnel` (`container run --mount type=bind,source=<channel>,target=/eq/tunnel`, carried into the container's VM by
> virtiofs); every other mount is read-only and the container has no network (`--network none`). The unix-socket argument of §3
> still holds (no socket is relied on; the probe's `host_socket_not_reached` row checks it). The repo copies live in
> `lib/eq-wall` (this folder) and `lib/eq-container`; installer integration: `install.sh --with-eq-container` (CONFIG.md §7).

Status 2026-10-05: built and tested with fakes only (no real host action, no daemon, no network). Default policy =
deny everything. Reviewed statically by security-auditor (N23) and code-reviewer (N24), both "pass with fixes", no
open High/Critical; the fixes are in (§12 item 10) and await the re-review the caller schedules. Until that re-review
passes and `lib/eq-wall/REVIEW` is set by the maintainer, X7's POSITIVE condition is not met and the WALL stays
**opt-in** (see `INSTALLER_WALL.md`). The pre-registered `flags.json` has no `wall` section: WALL off.

Files: `eq_wall.py` (broker + user-only CLI, stdlib only), `eq_wall_client.py` (in-container client, stdlib only),
`policy.default.toml` (default deny), `tests/` (broker tests + `mutations.py`); harness side in
`../harness/eq_harness.py` (`Wall`, `Isolation.check_tunnel`, `tunnel_probe`, `member-exec`), `../harness/tests/
test_wall_integration.py`; container-side proof in `../isolation/probe.d/50-tunnel.sh`.

## 1. Threat model

Assets: the host (files, credentials, processes, network identity, git remotes and forges), the experiment's integrity
(no arm gains undeclared capabilities; every request and its cost is counted), and the audit trail.

Adversary: everything inside the container. That is model-written code and, under `member_exec: "sandbox"`, the
member's own commands. Its abilities:
- write any bytes, names and file types into its channel directory (symlinks, hard links, FIFOs, sockets, directories,
  huge files, floods);
- race the broker (rename and swap between scan and read);
- replay or forge requests (other ids, other channels, other runs);
- inject argv and options;
- try to reach the host through anything else (sockets, network, signals, inherited fds, host paths);
- plant prompt-injection text in tool output.

Trusted: the user; host code whose bytes hash to the frozen configuration (`eq_wall.py`, `eq_wall_client.py`, the
policy, `eq_harness.py`); the user's verdict and consent stores.

Out of scope, stated as residuals (§12): another process of the same host user. It can do anything the user can,
including editing the stores, the receipt and the harness itself.

Agents (including the broker and every subagent) can never grant a verdict or a consent. Only the user can, at a
terminal (§6.3).

## 2. Components and trust boundaries

```
container (untrusted)                 |  host (user's uid)
  /eq/tunnel  = ONE channel dir  <----+-->  <tunnel_root>/<run_id>/<channel>/   (0700, created fresh per channel)
  python3 /eq/tunnel/eq_wall_client.py|      broker reads it via dir fds only
                                      |  eq_wall.py serve (one per run, flock on its audit log)
                                      |  <state_dir>/  (0700, host-only, never mounted, disjoint from tunnel_root)
                                      |     audit/<run_id>.jsonl   hash-chained, fsync'd, 0600
                                      |     runs/<run_id>/channels/<c>.json   host-side registrations (identity)
                                      |     verdicts.jsonl, consents.jsonl    user-only, hash-chained
                                      |     tunnel_probe.json                 probe receipt
                                      |     work/wallx.*                      throwaway exec dirs
```

The harness (host) creates every channel: the directory, `.channel.json` (identity + per-channel token, read by the
client), the hash-checked client copy, and the registration in the state dir. The broker trusts only the registration
and the nonce for identity. It never trusts what the container wrote.

Paths: `EQ_TUNNEL_DIR` (default `${XDG_CACHE_HOME:-~/.cache}/claude-agent-stack/eq-tunnel`) and `EQ_WALL_STATE_DIR`
(default `${XDG_STATE_HOME:-~/.local/state}/claude-agent-stack/eq-wall`). `check_roots` enforces three things: both
are real dirs owned by the user and 0700; neither contains the other; and the tunnel root is not `$HOME` or an
ancestor of it. The harness also refuses a tunnel root under a forbidden (secret) path (`Isolation.refuse_forbidden`).

## 3. The tunnel: one request/response directory per channel

Mechanism `dir-v1`. Each sandboxed member call gets one fresh channel directory, bind-mounted read-write at
`/eq/tunnel` into the one container running that call. The harness's `eqbox` server handles one command at a time,
so only one container mounts a channel at a time. Checks, oracles and fact re-runs never get a tunnel. The `/eq`
prefix is reserved: `isolate()` refuses any other mount under it.

Why not a unix socket:
- Docker Desktop on macOS does not carry unix-socket traffic across its VM boundary through a bind mount. In
  docker/for-mac#483 "Support for sharing unix sockets" (https://github.com/docker/for-mac/issues/483), the reporter
  says: "The socket is 'there', but non-functional". They quote the docs: "Socket files and named pipes only transmit
  between containers and between OS X processes ... no transmission across the hypervisor is supported, yet". The
  issue is closed; whether a current Docker Desktop release changed this is **unverified**.
- A socket would also need a long-lived listener on the host. A directory is passive: the broker polls it through
  directory file descriptors.

The design does not rely on sockets being dead. The broker never connects to anything in the tunnel and removes
every non-regular entry unread. The probe treats any connection from the container to a host listener inside the
tunnel as a FAIL (`host_socket_not_reached`).

Why one directory per channel, not one shared directory:
- identity is bound to the directory (the registration);
- a container never sees another channel's token;
- quotas, tripping and purge are per channel;
- a channel is never reused: the name is `c` + 128 random bits, created with `mkdir` (refused if it exists), and
  removed at close.

Container write access: the mount must be read-write, because the container writes `req-<id>.json` and the infiles.
It holds only regular 0600 files the harness or the broker created, plus whatever the container writes.

**Interface contract for other mounters (compose).** The source of `/eq/tunnel` must be ONE channel directory,
`<tunnel_root>/<run_id>/<channel>` created by `eq_wall.open_channel`, never the tunnel root. Mounting the root
exposes every channel's `.channel.json` token to the container, which can then post authenticated requests as
another item or arm. See §12 item 8: `compose.wall.yaml` / `eq-compose.sh --tunnel` currently default to
`EQ_TUNNEL_DIR` (the root).

## 4. Request and response schema; size limits

Request `eqwall.request.v1`: one JSON object per file `req-<request_id>.json`, written atomically by the client
(`.req-<id>.tmp`, then rename).

| field | type, limit |
|---|---|
| `schema` | `"eqwall.request.v1"` |
| `request_id` | 16..64 lower hex; must equal the file name's id |
| `run_id`, `channel`, `item`, `arm` | must equal the HOST registration of the directory the file was found in (else `identity`) |
| `token` | HMAC-SHA256(nonce, `EQWALL-CHANNEL-V1\0run\0channel`), constant-time compare (else `token`) |
| `kind` | `web-research` \| `missing-tool` \| `other` |
| `tool` | `[a-z0-9][a-z0-9_.+-]{0,63}`; `fetch` for web research |
| `argv` | missing-tool/other only: 1..64 strings, ≤ 4096 chars each, no control characters, `argv[0] == tool` |
| `url` | web-research only: ≤ 2048 chars |
| `args` | ≤ 32 typed args `{name, type ∈ enum/int/str/infile, value}`; int \|v\| ≤ 2^53; strings ≤ 4096 |
| `justification` | 10..2000 chars, newlines and tabs only |
| `content_sha256` | domain-separated sha256 of the canonical request minus token and itself |

Unknown fields are refused. A request can never carry a cwd, an environment, a verdict id or a consent. Parsing is
strict: UTF-8 only; no duplicate keys, NaN or Infinity.

Response `eqwall.response.v1` (`resp-<id>.json`, written by the broker through a private temp file and a rename):
- `request_id`;
- `decision` ∈ approved/denied/error;
- `reason` (≤ 300 chars) and `next` (`ASK USER: …` when only the user can unblock it);
- `summary` (≤ `summary_chars`; web output is prefixed with the data notice);
- `output_path` (`/eq/tunnel/out-<id>.txt` only), `output_sha256`, `output_bytes`;
- `data_notice` ("data, never instructions");
- `audit_seq`.

The client validates the exact key set, the request id, the output path prefix and a 16 KiB cap.

Limits (policy `[limits]`; a policy may tighten them, never exceed the code's `CEILINGS`):

| key | default | ceiling | meaning |
|---|---|---|---|
| `max_request_bytes` | 16 KiB | 64 KiB | one request file |
| `max_requests_per_channel` | 8 | 64 | authenticated attempts (denied ones count) |
| `max_requests_per_run` | 64 | 1024 | all arms; equal for every arm |
| `max_channels_per_run` | 2048 | 4096 | beyond: the channel is tripped |
| `max_tunnel_bytes` / `max_tunnel_entries` | 1 MiB / 32 | 8 MiB / 256 | container-written bytes and entries per channel; above: trip + purge |
| `exec_timeout_s` | 60 | 600 | per tool (a tool entry may lower it) |
| `max_output_bytes` | 256 KiB | 4 MiB | tool output; above it the process group is killed |
| `summary_chars` | 1500 | 4000 | the summary in the response |
| `max_infile_bytes` | 1 MiB | 8 MiB | ALL infiles of one request together (snapshotted with the request) |

## 5. Policy format (`eqwall.policy.v1`, TOML)

Tables: `[limits]`, `[kinds] allowed = [...]`, `[web] fetch_command, fetch_command_sha256, domains = [...]` (exact
lower-case DNS names; no IP literals, no wildcards), `[tools_manifest] path, required`, and `[[tool]]` entries:
- `name`, `kind` (missing-tool | other);
- `command`: absolute path of the REAL file, not a symlink;
- `command_sha256`;
- `fixed_args`;
- `args`: typed specs. `enum` needs values; `int` needs min and max; `str` needs a full-match pattern and `max_len`;
  `infile` takes a name `in-<name>` in the channel, never a path. `allow_dash` defaults to false: a value starting
  with `-` is refused;
- `externally_visible`, `destructive`, `timeout_s`, `max_output_bytes`.

At load, the broker refuses all of the following:
- unknown keys;
- a command that is or passes through a symlink, or whose sha256 differs from the policy;
- any command or tool name in `NEVER_COMMANDS`: git and forge CLIs (git, gh, tea, fj, glab, hub, git-lfs,
  send-pack…), network clients, shells and interpreters, package managers, docker/kubectl, sudo/launchctl/open/
  osascript, `claude`.

`eq_wall.py check-policy <file>` prints the policy sha256 and the class sha256 of every entry. It also fails on a tool
that is in the TOOLS manifest ("add it to the manifest instead").

## 6. The decision (pure, replayable): `decide()` in this order

1. Size, strict JSON, schema.
2. Identity = host registration.
3. Token.
4. Content hash.
5. Replay (request id seen in this run).
6. Quotas.
7. `NEVER_COMMANDS` (request side too). There is never a push or forge write, whatever the policy says.
8. Kind allowlisted.
9. Web: https only, exact allowlisted host, default port, no credentials or fragment. Tools: a `missing-tool` that is
   in the TOOLS manifest is refused; a missing or unreadable manifest with `required = true` refuses every
   missing-tool request (fail closed). Then: entry exists with the same kind; typed args render exactly; `argv` equals
   `[tool, *rendered]`.
10. **Verdict binding** (§6.1).
11. **Consent** (§6.2).
12. Approved: the plan's `argv[0]` is the POLICY's command, never the request's.

Any failure is a one-line denial with a code (LEDGER_SCHEMA `decision.code`).

### 6.1 Verdict binding

A verdict binds to the **class sha256**: `dhash("EQWALL-CLASS-V1", entry.norm())`. That covers the whole normalised
entry: command path, binary sha256, fixed args, every arg schema, the visibility flags and the limits. For the web it
is (fetch command, its sha256, ONE domain). It never binds to a run or a request.

Every hash is domain-separated: `CLASS`, `ACTION`, `CONTENT`, `CONFIG`, `STORE`, `AUDIT`. A class hash can therefore
never be confused with an action, content or audit hash (`test_verdict_hash_confusion`).

The latest record for the class decides. It approves only if it is reviewer `security-auditor`, verdict `pass` and
`open_high_critical == 0`. A later `fail` or `revoked` withdraws it.

### 6.2 Consent

Consent is needed for `externally_visible`, `destructive` and every kind `other`. It must be a user record for the
exact **action sha256**: kind, tool, argv or URL, typed args, and (new 2026-10-05) the sha256 of every infile's bytes
as snapshotted with the request. It must be for this run and is single use (`consumed`). A denial names the action
hash in `next: ASK USER: …`.

### 6.3 Consent and verdict records: user only

`verdict-add` and `consent-add` are the only writers (`append_store`). Both refuse unless stdin and stdout are a TTY
and the user types the first 12 hex characters of the hash. No flag bypasses this. The broker never writes either
store (`test_broker_never_writes_verdicts_or_consents`). The stores are hash-chained JSONL (0600, no symlink, owned
by the user, not group/world-writable). A broken chain fails closed (`store_broken`).

The chain is unkeyed: it detects edits by mistake or by a tool that does not recompute it. It does not stop a
same-uid writer (§12 item 2).

## 7. Host-side execution (confined)

`run_confined`:
- a throwaway 0700 dir under `<state>/work`;
- the command's bytes are COPIED into it, re-hashed against the policy sha256, and executed from the copy (no swap
  between check and exec);
- infiles are written from the snapshot taken WITH the request (§12 item 5, fixed), never re-read from the tunnel;
- environment `PATH=/usr/bin:/bin`, `HOME=TMPDIR=<throwaway>`, `LANG`; no inherited secrets;
- stdin `/dev/null`, own session, `close_fds`, `shell=False`;
- the process group is killed at the timeout or the output cap;
- the dir is removed afterwards.

Output: secret patterns are scrubbed (private keys, GitHub/OpenAI/AWS/Slack/JWT tokens, `key=value` credentials, the
run nonce, the home path). The full scrubbed output goes to `out-<id>.txt` in the channel; the response carries a
summary and that path.

Web research uses a fixed, hash-pinned fetcher named by the policy (none in the default). Its output is labelled data,
never instructions.

There is no push or forge write ever. `NEVER_COMMANDS` is checked at policy load and per request. The WALL has no
code path that runs git or a forge client.

## 8. Harness integration

- **Frozen config.** `eq_harness.py flags --wall-policy P [--wall-dir D] [--member-exec sandbox]` writes
  `flags.json` `wall = {enabled, mechanism, ctr_path, policy_sha256, broker_sha256, client_sha256, config_sha256}`.
  `config_sha256 = dhash(CONFIG; mechanism, ctr_path, the three file hashes, both schema ids)`. `Wall.__init__`
  refuses unless the broker bytes it imports hash to `broker_sha256` (`load_wall_module` hashes the executed bytes),
  and the client, policy, mechanism, ctr_path and config hash all match. It also refuses unless the backend is
  docker. Without a `wall` section the WALL is off (the pre-registered default).
- **Probe receipt gate.** `run` refuses unless `<state>/tunnel_probe.json` (written by `eq_harness.py
  isolation-probe`, opened `O_NOFOLLOW`) says PASS for this `config_sha256` and covers every image the run uses, and
  its `rows` (re-checked at `run`, not only when the probe wrote them) are well formed, hold every
  `TUNNEL_PROBE_REQUIRED` row and no row other than PASS/INFO. Its sha256 goes into
  `run_start.wall.probe_receipt_sha256`.
- **Per-run nonce.** 256 random bits, given to the broker on stdin and never in the ledger (`run_start.wall`
  carries its sha256). It is revealed beside the audit log at run end for replay.
- **Lifecycle.** The broker is started per run (`serve`, `python -I`, minimal env, own session, stderr to a 0600
  `broker.stderr` created `O_EXCL|O_NOFOLLOW`; refuses unless it prints `ready` AND its `broker_start` record reports
  the frozen `broker_sha256` and `policy_sha256`: `serve` re-reads both files after `Wall.__init__` hashed them, so a
  rewrite in between is caught and the broker killed). For each channel: open, then the container runs, then
  `close_channel` (the broker drains, records `channel_close`, removes the dir). The audit log is verified and copied
  into the ledger (`wall` records) after every channel and at stop. A broker that dies or stalls, or a broken chain,
  is an `IsolationError` (`run_abort`). The broker is serial and writes no record while an approved tool runs, so
  "stalls" = no new audit record for max(timeout, `exec_timeout_s` + 60 s). An exception while serving one channel
  trips that channel (`abuse`, `broker error <type>`); the broker keeps serving the others. One WALL/`member_exec`
  configuration per ledger.
- **`member_exec: "sandbox"`** (off by default; amendment proposal). The pool's Bash becomes ONE MCP tool,
  `mcp__eqbox__sandbox_exec`, served by `eq_harness.py member-exec --spec` (started as `uv run --no-config
  --directory / --script …`: no uv config file, e.g. a user-level `uv.toml` a host-side member could write, and a
  fixed cwd instead of the member's). Each command runs through `isolate()` in
  the class image: argv only, ≤ 256 strings, 64 KiB; `--network none`; the member's copy read-only at
  `/eqsrc/work`, copied into a capped tmpfs `/work`. With the WALL on, the call's channel is at `/eq/tunnel`.
  `--disallowedTools Bash`; calls are capped by `member_exec_max_calls`.
- **Client delivery** (new 2026-10-05). `Wall.open_channel` writes the client bytes hash-checked at start into
  `<channel>/eq_wall_client.py` (0600, `O_EXCL|O_NOFOLLOW`). Inside the container: `python3
  /eq/tunnel/eq_wall_client.py`. Whether every class image ships `python3` is **unverified** here (TOOLS.toml).
- **Accounting.** `item_arm.wall_requests` / `wall_approved` / `wall_used` (LEDGER_SCHEMA).

## 9. "Only path, proven": the probe

`eq_harness.py isolation-probe` runs, per image, ONE container built by `isolate()` with a fresh channel as its only
extra mount. It runs `probe.d/50-tunnel.sh --inner`, which checks:
- exactly one host-backed mount, at `/eq/tunnel`;
- `/eq` holds nothing else;
- the tunnel is writable (positive control);
- no docker socket or host-services socket;
- a host listener socket inside the tunnel cannot be connected;
- 6 outbound connects fail;
- no host paths (`/Users`, `/Volumes`, `/host_mnt`, the tunnel root…);
- sibling channels are invisible;
- `kill -0` of a host pid fails;
- pid 1 is init or tini;
- no inherited fds.

The host side checks the round trip, the listener never accepted, the sleeper survived and the sibling channel is
unchanged.

Every in-container row is REQUIRED (`TUNNEL_PROBE_REQUIRED`), and a result other than PASS/FAIL/INFO is a FAIL (fixed
2026-10-05: a probe that died part-way could have yielded a PASS receipt). `isolate()` must produce exactly one
writable bind, at `/eq/tunnel`.

`probe.sh` section G runs the same file in host mode as a `probe.d` hook. There it prints `T|name|RESULT|detail` rows
(fixed 2026-10-05: it used to print only a table, which the hook contract scores as a FAIL "no row"). It probes the
image `probe.sh` names (`EQ_PROBE_IMAGE`). A failed precondition (docker, image) is a FAIL row, never a silent exit.

## 10. Attack → test map (X6 §7, X7 reviews)

| attack | tests (`wall/tests/test_wall.py` unless marked; mutants in brackets) |
|---|---|
| request forging from inside the container | `test_forged_identity_token_and_content_are_refused`, `test_malformed_requests_are_refused`, `test_unknown_fields_cannot_smuggle_cwd_env_or_verdicts`, `test_file_name_must_match_request_id` [W01-W03, W39] |
| path traversal | `test_infile_path_traversal_is_refused`, `test_infile_symlink_or_hardlink_to_a_host_secret_is_never_read` [W13, W14] |
| TOCTOU on the queue | `test_read_regular_never_follows_or_blocks`, `test_write_atomic_replaces_a_symlink_swapped_in_after_the_scan`, `test_swapped_channel_dir_is_refused_and_tripped`, `test_command_swapped_after_policy_load_is_not_run`, `test_infiles_are_snapshotted_at_decision_time_not_execution_time` [W17, W18, W38, W41] |
| replay of an old approval | `test_replayed_request_id_is_refused`, `test_old_runs_request_and_consent_do_not_carry_over`, `test_consent_is_single_use_and_bound_to_the_exact_action`, `test_consent_binds_the_infile_content`, `test_restarted_broker_remembers_seen_ids` [W04, W12, W42] |
| argv injection | `test_argv_injection_is_refused`, `test_control_characters_in_argv_are_refused`, `test_args_reach_the_tool_verbatim_without_a_shell` [W28, W29] |
| verdict-hash confusion | `test_verdict_hash_confusion`, `test_only_a_clean_security_auditor_pass_approves`, `test_a_later_revocation_withdraws_the_verdict`, `test_web_verdict_binds_one_domain` [W09-W11, W40] |
| confused deputy | `test_web_research_refuses_off_policy_urls`, `test_execution_is_confined_and_output_scrubbed`, `test_tools_manifest_covered_request_is_refused`, `test_other_kind_always_needs_user_consent` [W08, W19, W20, W30, W36] |
| resource exhaustion | `test_oversized_request_is_refused`, `test_tunnel_flood_trips_the_channel`, `test_request_quotas_per_channel_and_run`, `test_tool_output_cap_and_timeout_kill_the_process_group`, `test_infile_bytes_are_capped_per_request`, `test_deep_directory_in_the_tunnel_trips_without_killing_the_broker`, `test_remove_entry_is_depth_bounded`, `test_a_broker_error_on_one_channel_trips_it_and_serves_the_rest`, `test_unauthenticated_request_flood_is_bounded`, `test_restarted_broker_keeps_the_abuse_budget` [W05, W16, W21, W22, W34, W43, W44-W50] |
| audit log writable from the container | `test_audit_log_never_under_the_tunnel_root`, `test_audit_log_symlink_or_loose_mode_is_refused`, `test_audit_chain_detects_any_edit`; integration `test_wall_roots_must_be_disjoint_and_never_secrets`, `test_broken_audit_chain_is_an_isolation_error` [W23-W25, M111] |
| tunnel hijack / second reader or writer | `test_second_broker_for_the_same_run_is_refused`, `test_channels_are_never_reused_and_registrations_are_exclusive`, `test_a_second_writer_cannot_answer_for_the_broker`, `test_client_rejects_malformed_or_foreign_responses` [W32, W33] |
| stale sockets, symlink swaps | `test_stale_fifo_in_the_tunnel_is_removed_without_blocking`, `test_stale_socket_in_the_tunnel_is_removed_never_connected`, `test_stale_run_dir_at_the_tunnel_path_is_refused`, `test_request_symlink_to_host_file_is_removed_unread`, `test_planted_response_symlink_is_replaced_not_followed`, `test_hardlinked_request_is_refused` [W15, W37] |
| no push / forge write | `test_policy_refuses_never_commands`, `test_never_push_or_forge_write_even_if_requested` [W06, W26, W27] |
| user-only grants | `test_grants_need_the_users_terminal`, `test_broker_never_writes_verdicts_or_consents`, `test_broken_verdict_store_fails_closed` [W31] |
| frozen config, receipt, one mount (harness) | `test_wall_refuses_any_change_to_the_frozen_configuration`, `test_probe_receipt_gate`, `test_isolate_adds_exactly_one_writable_mount_the_tunnel`, `test_tunnel_mount_refusals`, `test_run_refuses_without_a_passing_tunnel_probe`, `test_isolation_probe_requires_every_tunnel_row`, `test_tunnel_hook_meets_the_probe_d_contract`, `test_tunnel_hook_reports_a_fail_row_when_docker_is_down`, `test_each_channel_carries_the_frozen_client`, `test_probe_receipt_rows_are_revalidated`, `test_the_broker_that_starts_must_be_the_frozen_one`, `test_broker_stderr_is_private`, `test_close_channel_waits_for_a_busy_broker`, `test_eqbox_server_reads_no_uv_config_and_runs_from_a_fixed_cwd` [M99-M126] |

## 11. Ledger records, audit and replay

- **Audit records:** `broker_start`, `channel_open`, `request` (raw bytes base64, store prefix counts and hashes,
  infile hashes), `decision`, `result`, `abuse`, `store_error`, `channel_close`, `broker_stop`. Each is
  hash-chained (`prev_sha256`, `record_sha256`, `seq`) and fsync'd.
- **Ledger:** the harness copies them into the ledger as `wall` records, without `raw_b64` (fields:
  `../harness/LEDGER_SCHEMA.md`).
- **Replay:** `eq_wall.py replay` re-derives every decision from four inputs: the audit log, the revealed nonce
  (checked against `nonce_sha256`), the same policy bytes, and the store prefixes the decision saw (any later edit to
  those prefixes is reported).
- **Replay protection:** request ids are unique per run, including after a broker restart (`_replay_state`);
  consents are single use and per run; a channel is never reused; tokens are per run and per channel.

## 12. Open review items (each: fixed now, or the residual)

1. **No host-side disk quota on the rw tunnel.** RESIDUAL. The broker trips and purges a channel above
   `max_tunnel_bytes` / `max_tunnel_entries` at its next poll (200 ms). Between polls the container can write as fast
   as virtiofs allows, bounded only by host free space and the call timeout. A real fix needs a size-capped host
   filesystem under `EQ_TUNNEL_DIR` (e.g. an APFS volume with a quota, or a fixed-size sparse disk image mounted
   there). That is an installer option for the user (INSTALLER_WALL.md §6), not code here.
2. **Consent gate = TTY + typed confirmation; stores outside agent-writable paths.** PARTIAL. The CLI gate holds
   against every non-interactive caller (`claude -p`, the harness, the broker, pipes). But the stores are plain files
   of the user's uid, and the hash chain is unkeyed: a host process of the same user, including a host-side member
   using Edit/Write under `member_exec: "host"`, could append a valid-looking record. Mitigations (installer):
   - state dir 0700 outside every repo, work and run dir;
   - Claude Code deny rules for the state dir in the members' settings (`Edit`, `Write`, `Read` on
     `//<state_dir>/**`; exact enforcement **unverified** without a real `claude` run);
   - the stack's sandbox deny list.

   A complete fix needs a different uid or a keyed signature whose key the agents cannot read.
3. **Probe receipt `tunnel_probe.json` forgeable by a host process.** RESIDUAL (same uid as item 2). It is opened
   `O_NOFOLLOW` and bound to `config_sha256` and the image refs; its sha256 is in `run_start`, so a forged receipt is
   at least on record. Any same-uid writer able to forge it could equally edit the harness.
4. **Member Read/Edit/Write still on the host.** RESIDUAL. Under `member_exec: "sandbox"` only Bash is boxed.
   Claude's own file tools run in the host process, in the member's work copy (cwd). Boxing them needs claude itself
   inside the container, which is out of scope. The sandbox tool works on a fresh copy per call; files written in the
   container are discarded.
5. **Infiles snapshotted at execution, not decision time.** FIXED 2026-10-05:
   - the infiles named by a request are read (fd-based, `O_NOFOLLOW`, one link, capped together by
     `max_infile_bytes`) WITH the request, before `decide()`;
   - their sha256s go into the `request` audit record and into the action hash a consent binds to;
   - execution uses those bytes;
   - replay re-derives the action hash from the recorded hashes.

   PoC before/after: `test_infiles_are_snapshotted_at_decision_time_not_execution_time` (before: the tool printed
   `SWAPPED-CONTENT`), `test_consent_binds_the_infile_content` and `test_infile_bytes_are_capped_per_request` (before:
   failed); mutants W41-W43 killed.
6. **ES fixture pools have Bash; the real pools do not.** RESIDUAL (test fixture vs production). The fixture pools
   give ES Bash, so the integration tests box ES and need an ES image. The real pools give Bash to PF, CP and CR only:
   with `member_exec: "sandbox"` only those calls are boxed and need images; every other class runs exactly as
   pre-registered.
7. **`eq_freeze.sh` does not freeze `wall/` yet.** RESIDUAL, by brief (the user's file). `AMENDMENT_PROPOSAL.md`
   item 5 lists the exact copy and hash lines. Until then the frozen `flags.json` hashes are the only binding, and
   the harness checks them at every run start.
8. **Compose mounted the tunnel ROOT.** FIXED by devops-engineer (isolation owner), as read 2026-10-05:
   `compose.wall.yaml` now mounts `${EQ_TUNNEL_CHANNEL}` (set only by `eq-compose.sh --tunnel`, no default from
   `EQ_TUNNEL_DIR`), and `eq-compose.sh` (lines 84-92) refuses a `--tunnel` that is not ONE 0700 channel dir
   (`c<32 hex>` with `.channel.json`, no subdirectory) and refuses `up` with `--tunnel` (W3: one container per
   channel). Before: a compose container saw every channel's `.channel.json` token (confused deputy, High if used).
   The fix and its tests are in `isolation/`, not re-verified here.
9. **Fixed while finishing (2026-10-05):**
   - `probe.d/50-tunnel.sh` now meets the hook contract in host mode;
   - `isolation-probe` requires every in-container row;
   - each channel carries the hash-checked client. Before this, the eqbox tool description advertised a client that
     was not in the container.
10. **N23/N24 review fixes (R1, 2026-10-05).** Each with a proof test that failed before the fix:
   - W1 (CWE-674/400): `remove_entry` recursed without a bound; a 1200-level directory chain in a channel raised
     RecursionError out of `poll_once` and ended `serve` (then `run_abort`). Now depth ≤ `MAX_REMOVE_DEPTH` (64),
     True/False result, an unremovable entry trips its channel, and `poll_once` turns any exception while serving one
     channel into a tripped channel (`broker error <type>`). Tests:
     `test_deep_directory_in_the_tunnel_trips_without_killing_the_broker`, `test_remove_entry_is_depth_bounded`,
     `test_a_broker_error_on_one_channel_trips_it_and_serves_the_rest`.
   - W2 (CWE-770): every `req-*` file was logged (base64 + two fsync'd records) and refusals (unauthenticated,
     malformed, replayed, over quota, unreadable) counted toward no quota: 40 polls x 8 x 16 KiB gave ~7 MB of audit.
     Now each channel has an abuse budget, `ABUSE_BUDGET_FACTOR` (4) x `max_requests_per_channel`, spent by those
     refusals (`REFUSED_CODES`) and by removed non-regular entries; over it the channel trips ("abuse budget spent").
     The count is rebuilt from the audit log on restart. `test_unauthenticated_request_flood_is_bounded` (audit < 1 MiB,
     33 request records), `test_restarted_broker_keeps_the_abuse_budget`.
   - W5 / N24#7 (CWE-367), N24#3, N24#6, the receipt rows, the eqbox launch: §8 above; tests in §10's harness row.
   - Residual of W5: the broker hashes `__file__` after Python compiled it, so a rewrite racing exactly between the
     interpreter's read and that hash (milliseconds, same uid) is not caught; same-uid writers are §12 items 2-3.
   - Residual (N23 2g, unchanged): the audit log and the stores are hash-chained but unkeyed, so a same-uid process
     can forge a consistent chain. This blocks any NON-EMPTY policy (keyed MAC in the Keychain, or a separate uid),
     not the default-deny one.
11. **R2 review fixes (R2d, 2026-10-05).** Each with a proof test that failed before the fix:
   - R2b (a): `Wall.check_probe` also requires the host-side receipt rows `TUNNEL_PROBE_HOST_ROWS`
     (`tunnel_only_extra_mount`, `tunnel_roundtrip`, `host_process_unsignalled`, `sibling_channel_unchanged`).
     `test_probe_receipt_requires_the_host_side_rows` (harness).
   - R2c F2 (CWE-400): the `.channel.json` exemption went by name and size only, so a DIRECTORY by that name (APFS
     `st_size` 96) bypassed `max_tunnel_bytes`/`max_tunnel_entries`, the non-regular purge and the abuse budget; the
     tripped-channel purge and `trip()` spared it by name too. Now only a regular file of at most 4096 bytes is exempt
     (`is_identity`). `test_a_directory_named_channel_json_is_purged`,
     `test_a_tripped_channel_purges_a_directory_named_channel_json`.

## 13. Evidence (2026-10-05)

Runs from a copy of STAGE under `/tmp/claude` (the agent sandbox blocks writes beside the sources), cwd
`/tmp/claude-501`, `TMPDIR=/tmp/claude`. Details: `../harness/R2_RUN.md` (R2, after the R1 fixes; and its R2d
section, after the §12 item 11 fixes and the `no_verdict_policy` = `"zero"` default).

- `wall/tests`: 100 passed, 2 skipped (R2: 98 passed, 2 skipped). The skips are AF_UNIX binds denied by the agent
  sandbox.
- `wall/tests/mutations.py`: 52/52 killed, W01-W52, all `pytest exit 1` (`mutations.out`; R2: 50/50).
- Harness suite: 401 passed, 0 failed in the copy (R2: 395/0 in the copy; at the real location 2 known
  agent-sandbox failures, `test_shell.py::test_freeze_installs_and_writes_sidecar` and
  `test_verifier_lows.py::test_low1_score_copy_keeps_tests_pristine`).
- `harness/tests/mutations.py`: M01-M136, 136/136 killed, all `pytest exit 1` (`../harness/tests/mutations.out`;
  R2: M01-M130, 130/130).
- `ruff check` clean on `harness/` and `wall/`.

Commands (from STAGE):

```
uv run --no-project --with pytest pytest -q -p no:cacheprovider wall/tests
uv run --script wall/tests/mutations.py
uv run --no-project --with pytest --with duckdb --with-requirements harness/eq_harness.py pytest -q harness/tests
uv run --script harness/tests/mutations.py
```
