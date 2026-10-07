# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy==2.5.3"]
# ///
"""DS pool generator: one design item per (scenario, kind) from scenarios.py.

Outputs (class folder): manifest.jsonl, oracle/criteria.jsonl, selftest/*.json.
Segment order: numpy.random.default_rng(3725927731) (seed eq|items), one permutation per item in manifest order.
Item order: content RNG 20261004 ^ int(sha256("eq|items|DS|gen")[:8], 16) permutes the (scenario, kind) list.
Run: uv run --offline --script gen_ds.py
"""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
CLS_DIR = HERE.parent
sys.path.insert(0, str(HERE))
from scenarios import DEV, S  # noqa: E402

SEED_ITEMS = 3725927731
SEED_GEN = 20261004 ^ int(hashlib.sha256(b"eq|items|DS|gen").hexdigest()[:8], 16)
WORD_LIMIT = 900
KIND = {
    "api": ("API design",
            "Design the HTTP API of this system. Deliver: the resources and endpoints (method, path, purpose); request "
            "and response shapes for the two most important operations; the error model; pagination; idempotency and "
            "retry semantics; authentication and authorisation scopes; versioning; and the one decision you found "
            "hardest, with the alternative you rejected.",
            ["Endpoints are resource-oriented and consistent; status codes and error bodies are specified.",
             "Idempotency, retries, pagination and concurrency control (e.g. ETags or versions) are handled where the "
             "requirements need them.",
             "Authorisation is specified per operation, and versioning or evolution is addressed."]),
    "schema": ("schema design",
               "Design the database schema of this system (relational unless you argue otherwise). Deliver: the "
               "tables or collections with keys and constraints; the indexes, each justified by a named query; how the "
               "hardest integrity requirement is enforced in the database; retention or archival; and a safe "
               "migration plan for one likely future change (name it).",
               ["Keys, types and constraints enforce the stated invariants in the database, not only in application "
                "code.",
                "Every index is justified by a stated query; no obviously missing index for a stated access path.",
                "The migration plan is safe on a live system (expand/contract, backfill, no long locks)."]),
    "arch": ("architecture",
             "Design the architecture of this system. Deliver: the components and their responsibilities; the data "
             "flow of the main path; the consistency and failure model (what happens when each dependency fails); a "
             "back-of-envelope capacity estimate from the stated numbers; observability (key metrics and alerts); the "
             "rollout plan; and the one decision you found hardest, with the alternative you rejected.",
             ["Components and data flow are clear, and each requirement maps to a mechanism.",
              "The failure model covers each dependency, with a stated behaviour on failure.",
              "The capacity estimate uses the stated numbers correctly (arithmetic checks out)."]),
}
COMMON = ["Every listed requirement is addressed explicitly; none is silently dropped.",
          "Technical claims are correct and assumptions are stated; vague or hand-waving answers rank lower.",
          f"Stays within {WORD_LIMIT} words; extra length is not a merit, and padding counts against an answer."]

REFS = {
    "api": """## Resources
- `POST /lists`, `GET /lists?cursor=`, `GET/PATCH/DELETE /lists/{id}`; `POST /lists/{id}/restore` (30-day window).
- `GET /lists/{id}/items?cursor=`, `POST /lists/{id}/items`, `PATCH/DELETE /lists/{id}/items/{itemId}`.
- `PUT /lists/{id}/shares/{userId}` with `{"role": "view"|"edit"}`; `DELETE` revokes.
- `GET /sync?since=<cursor>` returns changed lists and items plus tombstones; `POST /sync` uploads offline changes.
## Concurrency and retries
Every item carries `version`; `PATCH` needs `If-Match: <version>`, else `428`; a stale version gets `409` with the
current item so the client can merge. `POST` accepts `Idempotency-Key` (kept 24 h).
## Errors, auth, versioning
Errors are `application/problem+json` (`type`, `title`, `detail`). OAuth2 scopes `lists:read`, `lists:write`; share
roles are checked per request and again during `/sync`, so a revoked user receives tombstones only. URL major version
`/v1`; additive changes only within it.
## Hardest decision
Optimistic versions with client-side merge versus a CRDT. Chose versions: items are small and conflicts rare at 20
collaborators; a CRDT would add payload and complexity without need.""",
    "schema": """## Tables
- `users(id pk)`; `lists(id pk, owner_id fk, title, deleted_at null, version bigint)`.
- `list_shares(list_id fk, user_id fk, role check in ('view','edit'), pk(list_id, user_id))`.
- `items(id pk, list_id fk, body, done bool, position numeric, version bigint, updated_at, deleted_at null)`;
  a trigger bumps `version` and appends to `changes`.
- `changes(seq bigserial pk, list_id, item_id null, op, at)` feeds offline sync cursors.
## Indexes (by query)
- `items(list_id, position) where deleted_at is null`: render a list.
- `changes(list_id, seq)`: `sync since cursor` per list.
- `list_shares(user_id)`: lists shared with me.
## Integrity
The 2,000-item cap is enforced by a statement trigger counting live items. Concurrent edits use `version` compare-and-
set (`update ... where id = $1 and version = $2`).
## Retention
Soft delete via `deleted_at`; a nightly job purges rows older than 30 days, and `changes` older than 35 days.
## Migration (add item due dates)
Add a nullable `due_at`, deploy readers, backfill nothing, then add an index concurrently.""",
    "arch": """## Components
API service (stateless, 2+ instances), PostgreSQL primary with one replica, a sync endpoint, a push notifier and a
nightly purge job.
## Main path
Client edit -> API checks the share role -> conditional update on `version` -> change row appended -> notifier pushes
to the other collaborators. Offline clients replay queued edits through `/sync`; conflicts return the server copy.
## Failures
DB primary down: writes fail fast (503) and clients queue offline; replica promotion is manual with a runbook.
Notifier down: collaborators converge on their next sync. A revoked share is enforced at sync time.
## Capacity
50k users x 10 lists = 500k lists; at most 2,000 items each but typically about 50, so about 25M items, roughly 10 GB
with indexes. Peak about 200 writes/s: one modest Postgres instance suffices.
## Observability
p95 latency per endpoint, 409 conflict rate, sync lag, purge job success; alert on error rate above 2% for 5 minutes.
## Rollout
Behind a flag for 5% of users, then 50%, then all; rollback by flag.
## Hardest decision
Polling sync versus WebSockets for live updates: chose push hints plus pull sync, which is simpler and works offline.""",
}
WRONG = ("The best approach is microservices on Kubernetes with an event bus. Use a NoSQL database because it "
         "scales. Add caching everywhere. Security is handled by HTTPS.")


def main():
    rng = np.random.default_rng(SEED_GEN)
    pool = [(s, k) for s in S for k in s["kinds"]]
    keys = [s["key"] for s in S]
    assert len(keys) == len(set(keys)) and DEV["key"] not in keys
    order = rng.permutation(len(pool))
    items = [(f"DS-DEV{i + 1}", True, DEV, k) for i, k in enumerate(DEV["kinds"])] + \
            [(f"DS-{n + 1:04d}", False, *pool[j]) for n, j in enumerate(order)]
    seg_rng = np.random.default_rng(SEED_ITEMS)
    man, crit = [], []
    for iid, dev, s, k in items:
        title, deliver, kcrit = KIND[k]
        prompt = (f"Design task ({title}).\n\nSystem: {s['context']}\n\n{deliver}\n\nLimits: at most {WORD_LIMIT} "
                  "words of Markdown in `answer`; short illustrative snippets only (at most 15 lines in total); state "
                  "every assumption you add. `evidence` may stay empty.\n\nRequirements (all apply):")
        perm = seg_rng.permutation(len(s["reqs"]))
        segs = [{"id": f"r{j + 1}", "text": s["reqs"][j]} for j in perm]
        man.append({"id": iid, "class": "DS", "dev": dev, "answer_kind": "long_form", "prompt": prompt,
                    "segments": segs, "decisive_segment": None, "fixture": None, "public_check": None,
                    "allowed_tools": []})
        crit.append({"id": iid, "scenario": s["key"], "kind": k, "source": s["src"], "word_limit": WORD_LIMIT,
                     "criteria": COMMON[:1] + kcrit + [f"Scenario-specific: {p}" for p in s["pitfalls"]] + COMMON[1:]})
    (CLS_DIR / "manifest.jsonl").write_text("".join(json.dumps(m, ensure_ascii=False) + "\n" for m in man))
    (CLS_DIR / "oracle").mkdir(exist_ok=True)
    (CLS_DIR / "oracle" / "criteria.jsonl").write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in crit))
    st = CLS_DIR / "selftest"
    st.mkdir(exist_ok=True)
    for iid, _, _, k in items[:3]:
        ref = {"answer": REFS[k], "evidence": [], "confidence": 0.7}
        wrong = {"answer": WRONG, "evidence": [], "confidence": 0.9}
        (st / f"{iid}.ref.json").write_text(json.dumps(ref, ensure_ascii=False, indent=1) + "\n")
        (st / f"{iid}.wrong.json").write_text(json.dumps(wrong, ensure_ascii=False, indent=1) + "\n")
    from collections import Counter
    print("items", len(man), "non-dev", len(man) - 3, Counter(c["kind"] for c in crit[3:]),
          "from graded prompts", sum(c["source"] != "authored" for c in crit[3:]), "gen seed", SEED_GEN)


if __name__ == "__main__":
    main()
