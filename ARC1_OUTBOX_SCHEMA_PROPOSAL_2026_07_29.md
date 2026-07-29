# Arc 1.5 outbox consolidation — schema proposal

**Status:** design proposal for approval, per David's 2026-07-29 review ("'no Phase G schema exists yet' is not a blocker, it's your next approval artifact"). No code changes, no migrations. Read-only investigation of the 4 tables ONE_MIND §3.2/Arc 1.5 names as "4 mailboxes."

## 1. Census (live, 2026-07-29)

| Table | Rows | Direction | Actual purpose |
|---|---|---|---|
| `autonomy_attention_item` | 254 | Sara → David | The attention-queue item: title/body/category/priority/status(new/sent/read/archived)/dedupe_key. What `route_through_attention_queue` writes. |
| `jarvis_inbox` | 111 | Sara → David | Structurally near-identical to the above: kind/title/body/priority/status/dedupe_key/batch_id. A second, parallel implementation of the same concept. |
| `notification_log` | 2,237 | Sara → David (ledger) | NOT an inbox in the same sense as the other two — it's the delivery audit log: every send *attempt* (sent=true/false, dedup_blocked, cooldown_hours, blocked_count), one row per attempt not per logical item. Already has `attention_item_id` FK linking a log row to the attention item it was for. |
| `sara_inbox` | 33 | **David → Sara** | Different direction entirely: `prompt`/`context`/`created_by='david_api'`, status queued→in_progress→done/dismissed. This is a task queue FOR Sara (the "queue_for_sara" hand-off), not a notification mailbox FROM Sara. |

## 2. Finding: the "4 → 1" framing needs a correction

`sara_inbox` is not a peer of the other three. It holds requests David queues *for Sara to act on*, not notifications Sara is delivering *to David*. Merging it into a Sara→David "outbox" would conflate two different concerns in one table (a classic "now you have two problems" outcome — you'd need a `direction` column and every reader would need to filter on it, which is exactly the kind of accidental complexity ONE_MIND's consolidation is trying to remove elsewhere).

**Recommendation:** the "one outbox" unifies `autonomy_attention_item` + `jarvis_inbox` only (365 rows combined) — they are structurally near-duplicates of the same concept already. `notification_log` stays a separate **delivery ledger** (different grain: attempts, not items) with its FK repointed at the new table. `sara_inbox` stays **separate and unrenamed** — it's a correctly-distinct table for a correctly-distinct concern, not a 4th mailbox to fold in.

This matches Arc 1.4's own mouth (`composed_utterance` + `mindv2_deliver`), which already treats "the queryable item" and "the delivery attempt/result" as two different things (`delivered_at`/`delivery_result` on the item itself, in that case) — the ledger-vs-item split is a pattern already established this session, not a new one.

## 3. Proposed unified schema: `outbox_item`

```sql
CREATE TABLE outbox_item (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         VARCHAR(255) NOT NULL,
    title           TEXT NOT NULL,
    body            TEXT,
    category        VARCHAR(50) NOT NULL DEFAULT 'general',
    priority        VARCHAR(20) NOT NULL DEFAULT 'normal',
    source          VARCHAR(50) NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'new',  -- new|sent|read|archived|completed
    dedupe_key      VARCHAR(255),
    payload         JSONB DEFAULT '{}',
    action_history  JSONB DEFAULT '[]',
    batch_id        VARCHAR(36),           -- from jarvis_inbox, for grouped digest-style items
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    read_at         TIMESTAMPTZ,
    archived_at     TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ
);
-- same dedup discipline autonomy_attention_item already has:
CREATE UNIQUE INDEX idx_outbox_dedupe ON outbox_item (user_id, dedupe_key)
    WHERE dedupe_key IS NOT NULL AND status IN ('new', 'sent');
CREATE INDEX idx_outbox_priority ON outbox_item (user_id, priority, created_at DESC)
    WHERE status IN ('new', 'sent');
CREATE INDEX idx_outbox_user_status ON outbox_item (user_id, status, created_at DESC);
```

Superset of both source schemas — every column in `autonomy_attention_item` and `jarvis_inbox` maps directly (`jarvis_inbox.kind` → `category`; everything else is a same-name or same-shape carry-over). No information loss on migration.

`notification_log.attention_item_id` gets renamed to `outbox_item_id` (repointed FK), no other schema change to that table.

## 4. Migration sequence (write-freeze pattern, same discipline as Arc 3/Arc 5)

1. Create `outbox_item` (additive, no reads/writes redirected yet).
2. Dual-write: every current writer of `autonomy_attention_item` or `jarvis_inbox` also writes `outbox_item` (mirrors Arc 1's say_candidate dual-write pattern exactly).
3. Backfill: one-time copy of existing 254 + 111 = 365 rows into `outbox_item`, preserving IDs.
4. Verify: row counts and spot-content-checks match on both sides.
5. Cut over readers (web inbox view, iOS inbox view, `/api/assistant-inbox/unified`, `compute_badge`) to read `outbox_item` — one reader at a time, each independently revertable.
6. Repoint `notification_log.attention_item_id` → `outbox_item_id`.
7. Write-freeze the two old tables (stop writers), verify nothing regresses for a real usage window.
8. Drop `autonomy_attention_item` and `jarvis_inbox`.

Not started — this document is step 0 (the proposal). Per the plan's approval-gate discipline, steps 1+ need explicit sign-off the same way the Arc 3 job inventory and Arc 5 notes manifest did.

## 5. Known unknowns / risks to resolve before step 2

- **`compute_badge`** (memory: "shared badge formula") and the iOS unified inbox both read from some combination of these tables today — needs tracing before cutover to know exactly what breaks if timing is off during the dual-write window.
- **`jarvis_inbox.kind`** is a Postgres enum (`inboxkind`), not a free-text category like `autonomy_attention_item.category` — the migration needs an explicit enum→text mapping, not an assumed 1:1.
- Real usage window length for step 7 isn't defined here — that's a David call, not an engineering one.
