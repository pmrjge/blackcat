# Amendment proposal A3 to COMPARE_eq.md: WALL + sandboxed member execution

For the USER to decide. Nothing here is applied: `COMPARE_eq.md` and `eq_freeze.sh` are unchanged, and the
pre-registered `harness/flags.json` has no `wall` section (WALL off, members' Bash on the host, as frozen in A0-A2).
If approved, the user appends the text of §2 to `COMPARE_eq.md` §12 before `eq_freeze.sh` runs (PRE-FREEZE). After
the freeze it would be a dated post-freeze amendment with a sidecar line, per the `eq_freeze.sh` header.

Design and evidence: `WALL_DESIGN.md`. Ledger fields: `../harness/LEDGER_SCHEMA.md` (`run_start.wall`,
`run_start.member_exec`, `call.member_exec` / `wall_channel` / `member_exec_calls`, `item_arm.wall_requests` /
`wall_approved` / `wall_used`, `wall` records).

## 1. Options

| option | what is frozen | what changes for the arms |
|---|---|---|
| **A. Approve** (WALL + `member_exec: "sandbox"`) | `flags.json` `wall` section (the policy, broker and client hashes and `config_sha256`) and `member_exec: "sandbox"`; `wall/` copied and hashed by `eq_freeze.sh` | every arm's Bash (PF, CP, CR in the real pools) runs in the class container; host requests only through the WALL, default deny |
| **B. Reject** | nothing new | none: A0-A2 as written; members' Bash runs on the host under the agent sandbox |
| **C. WALL only, no member sandboxing** | `wall` section and `wall/` hashed; `member_exec: "host"` | none at run time: only sandboxed member calls get a tunnel, so with `member_exec: "host"` no arm can reach the broker. What it buys is the frozen config, the probe receipt gate and a broker lifecycle per run (an always-empty audit log). It is the step that lets A be enabled later as a dated amendment without changing the frozen tooling |

Recommendation: **B until the reviews are in**. X7's POSITIVE condition is not met: no security-auditor review, no
code-reviewer pass. Then A, if the user wants member commands out of the host. A is the only option that changes
what the arms can do.

## 2. Text to append (option A; for C replace item 2 by "`member_exec` stays `host`")

- **A3 — <date>, PRE-FREEZE (WALL and sandboxed member execution; SCOPE X6/X7; written before `eq_freeze.sh` and
  before any eq call; A0-A2 stand).**
  1. **WALL config frozen in `flags.json`.** `wall = {enabled: true, mechanism: "dir-v1", ctr_path: "/eq/tunnel",
     policy_sha256, broker_sha256, client_sha256, config_sha256}`, written by `eq_harness.py flags --wall-policy
     <policy> --member-exec sandbox`.
     - The policy is the frozen file. The default is `wall/policy.default.toml`, deny everything; any allowlist entry
       must be added before the freeze, together with its security-auditor verdict.
     - The harness refuses a run if any hash differs, or if the tunnel probe receipt (`eq_harness.py
       isolation-probe`) is not PASS for this `config_sha256` and these images.
     - Verdicts and consents are host records of the user and are not part of the frozen package. Their prefixes
       are hashed into every decision record.
  2. **`member_exec: "sandbox"`.**
     - In every arm, the pool's `Bash` tool is replaced by one MCP tool, `mcp__eqbox__sandbox_exec`. It runs argv in
       the class image (the same image, flags and limits as checks), on a fresh copy of the member's working
       directory, with `--network none`; with the WALL on, the call's own channel is at `/eq/tunnel`.
     - Read, Edit and Write stay on the host, as before.
     - Applies to the classes whose pools allow Bash (PF, CP, CR), identically for S*, E, G and EG.
     - `member_exec_timeout_s` (default `check_timeout_s`) and `member_exec_max_calls` (default 200 per member call)
       are frozen with the flags.
  3. **Requests and cost counted per arm, equally.**
     - Each WALL request (approved or denied) is charged to the item-arm whose call owns the channel
       (`wall_requests`, `wall_approved`).
     - The per-run quota (`max_requests_per_run`) and the per-call quota (`max_requests_per_channel`) are the same
       for every arm.
     - A WALL-run tool has no USD price; its wall time is inside the member call's wall time (P4).
     - No arm gets a different policy, quota or image.
  4. **Analysis flag `wall_used`.**
     - `item_arm.wall_used = wall_requests > 0`.
     - Route 1 and route 2 report every primary and secondary result twice: on all item-arms, and on the item-arms
       of items where no arm used the WALL. A difference between the two is reported in §11 as a confound, never
       used to choose a result.
     - Items with `wall_used` in any arm are listed in the pilot reading (§7.4).
  5. **`eq_freeze.sh` freezes `wall/`.** It copies `wall/eq_wall.py`, `wall/eq_wall_client.py`, the policy named in
     `flags.json` (`policy.default.toml` by default), `wall/WALL_DESIGN.md` and `isolation/probe.d/50-tunnel.sh`
     into `$EQ/wall/` (the harness finds the broker at `$EQ/wall`), read-only, in the sidecar. `--collect` also
     copies, for each WALL run id of the stage's ledger:
     - `<state>/audit/<run_id>.jsonl`;
     - `<state>/runs/<run_id>/nonce.revealed`;
     - `verdicts.jsonl` and `consents.jsonl`

     into `$EQ/runs/<stage>/inputs/wall/`, where `<state>` = `${EQ_WALL_STATE_DIR:-~/.local/state/claude-agent-stack/eq-wall}`.
     `eq_wall.py replay` must then report `REPLAY OK` for every run id.
  6. **Confound recorded (§11).** Under A, member commands run in Linux containers rather than on the macOS host.
     Every eq arm gets the same environment, but it differs from the c0 baseline's host Bash. Tool availability is
     the image's (TOOLS.toml), not the host's.
  7. Nothing else in §0-§11 changes: no arm, label, cap, schedule, hypothesis or stop rule.

## 3. `eq_freeze.sh` lines (for the user; not applied)

In the install block, after the harness copy loop:

```bash
  WALL_D=$STAGE/wall
  if jq -e '.wall.enabled == true' "$H_/flags.json" >/dev/null; then
    for f in eq_wall.py eq_wall_client.py policy.default.toml WALL_DESIGN.md; do
      [ -f "$WALL_D/$f" ] || die "missing WALL input: $WALL_D/$f"
    done
    mkdir -p "$EQ/wall"
    cp -p "$WALL_D/eq_wall.py" "$WALL_D/eq_wall_client.py" "$WALL_D/policy.default.toml" "$WALL_D/WALL_DESIGN.md" "$EQ/wall/"
    cp -p "$STAGE/isolation/probe.d/50-tunnel.sh" "$EQ/wall/"
    # the frozen hashes must match what is installed
    [ "$(shasum -a 256 "$EQ/wall/eq_wall.py" | cut -d' ' -f1)" = "$(jq -r .wall.broker_sha256 "$H_/flags.json")" ] || die "eq_wall.py differs from flags.json"
    [ "$(shasum -a 256 "$EQ/wall/eq_wall_client.py" | cut -d' ' -f1)" = "$(jq -r .wall.client_sha256 "$H_/flags.json")" ] || die "eq_wall_client.py differs from flags.json"
    [ "$(shasum -a 256 "$EQ/wall/policy.default.toml" | cut -d' ' -f1)" = "$(jq -r .wall.policy_sha256 "$H_/flags.json")" ] || die "policy differs from flags.json (a non-default policy: copy that file instead)"
  fi
```

These lines go before the `find "$EQ" -type f -exec chmod a-w {} +` line, so that the sidecar hashes them. The
`--collect` copy follows the transcripts block with the same `die`-on-missing style. The existing `test_shell.py`
freeze tests would gain a case with a `wall` section.
