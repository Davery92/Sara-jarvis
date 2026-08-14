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

**Steps 1-6: DONE and live-verified, 2026-07-30** (David's "all three decisions are made... proceed without waiting" work order authorized this). Steps 7-8 deliberately NOT executed this session — see the status note below.

- Step 1: `alembic/versions/131_outbox_item.py` creates `outbox_item`, additive.
- Step 2: dual-write implemented as a Postgres trigger (`sync_attention_to_outbox()`, AFTER INSERT OR UPDATE on `autonomy_attention_item`) rather than hand-editing 15 call sites — see the revised §5 note below for why. Live-verified: an INSERT and a subsequent status UPDATE against `autonomy_attention_item` both mirrored into `outbox_item` synchronously, same transaction, zero lag.
- Step 3: backfill migrated 249 live `autonomy_attention_item` rows (254 at the 2026-07-29 census, 249 by execution time — normal live-table drift) and 111 `jarvis_inbox` rows. **Caught and fixed a real bug during verification**: the first backfill pass carried `jarvis_inbox`'s own status through 1:1, which resurrected 7 rows that had sat `NEW` for David's real account — but `jarvis_inbox` never had a reader, so those 7 had never actually surfaced to him anywhere. Reviving them as live unread badge count on cutover would have been a genuine regression (stale historical residue reappearing as fresh notifications), not neutral data preservation. Fixed: `jarvis_inbox` backfill now forces `status='archived'` unconditionally, preserving the data without reviving false urgency. Migration file and live dev-DB rows both corrected.
- Step 4: verified — `outbox_item` = 360 rows (249 + 111), spot-checked content match on both source tables, confirmed via badge parity (below).
- Step 5: `compute_badge()` and `build_unified_inbox()` (`app/routes/assistant_inbox.py`) now read `outbox_item` instead of `autonomy_attention_item`. Badge parity verified live against the real account: 1 == 1 before/after (the 7-row bug above was caught by exactly this check — badge went 1→8 before the archived-status fix, back to 1→1 after). `needs_you`/`fyi` counts verified via the real `/api/assistant-inbox/*` endpoints with a minted JWT.
- Step 6: `alembic/versions/132_outbox_notification_fk.py` renames `notification_log.attention_item_id` → `outbox_item_id` (no FK constraint existed to repoint — it was always a bare UUID column). All 6 real call sites with literal SQL references updated (`unified_notification.py`, `notification_ack.py`, `autonomy_traces.py`, `assistant_inbox.py` ×2, `attention_queue.py` ×3); Python-level dict-key/schema-field names left as `attention_item_id` where they refer to the concept generically, not the literal column (`app/schemas/chat.py`, `contracts.py`, `morning_proactive_service.py`, `attention_shadow_recorder.py` — none of these touch notification_log's schema directly). Live-verified: real notification insert via `_log_notification()` round-tripped through the renamed column; full test suite run against both the modified and unmodified tree confirms zero regressions attributable to this change (pre-existing unrelated failures in `test_unified_notification.py`/`test_personality_engine.py`/`test_reflection.py` reproduce identically on `main` before this diff).

**Update 2026-07-30 (later same day, Work Order B continuation):** every real SQL reference to `autonomy_attention_item` (not just the 15 write call sites — reads too) migrated to `outbox_item` across 12 files (`attention_queue.py`, `unified_notification.py`, `notification_ack.py`, `memory_subscribers.py`, `attention_shadow_recorder.py`, `debug_notifications.py`, `autonomy_attention.py`, `autonomy_traces.py`, `main_simple.py`, `tasks/content_inbox.py`, `tasks/autonomy.py`, `tasks/attention.py`). `autonomy_attention_item` is now referenced by nothing in app code except its own dual-write trigger — a real, code-verified write-freeze. The `jarvis_inbox` subsystem (model, service, `calendar_monitor.py`, `reminder_monitor.py`) was deleted outright rather than migrated — confirmed zero live callers, zero scheduled_job rows. `outbox_usage_log` + `app/services/outbox_usage.py` now count real traffic against David's step-7 bar as it happens (wired into both read functions and all 5 attention_queue write methods) — not synthetic. Live-verified full create/engage/archive cycle, badge parity, zero regressions (confirmed via targeted before/after test isolation, not just eyeballing counts).

**Steps 7-8 status: deliberately not executed this session.** Step 7's usage window is David's own explicit, event-count bar ("≥50 reads, ≥20 writes across web + iOS, badge parity on every check, zero regressions") — it cannot be manufactured in one sitting; it needs real usage across real days. Step 8 (`DROP autonomy_attention_item, jarvis_inbox`) is additionally blocked on its own precondition the original proposal didn't surface: the trigger-based dual-write means `autonomy_attention_item` is still the *real* write target for all 15 live call sites — dropping it today would break every one of them (create + all 14 status-transition updates), trigger or no trigger. `jarvis_inbox` alone could be dropped safely right now (confirmed fully dead, zero writers, zero readers) but David's plan bundles both tables into one step 7/8 pair, so it stays live-but-inert pending the same gate. Before step 8 can run for real, the write call sites need to be migrated off `autonomy_attention_item` directly (or a compatibility view substituted in its place) — that's follow-up work, not a same-session task, and is the next thing to pick up when the usage window closes.

## 5. Known unknowns — RESOLVED (work-order item 13, 2026-07-30, before dual-write per David's rider)

**`compute_badge` / iOS+web read-path trace.** Both real, live functions — `compute_badge()` and `build_unified_inbox()`, both in `app/routes/assistant_inbox.py` — read **only** `autonomy_attention_item` (plus `background_task`, `notification_log`, `shared_content` for the other inbox sections). Neither reads `jarvis_inbox` at all. Traced further: web (`frontend/src/components/ChatInterface.tsx`, `OverlayContent.tsx`) and iOS (`ios-app/src/services/api.ts:764,769`) both call the exact same two backend endpoints (`/api/assistant-inbox/unified`, `/api/assistant-inbox/badge`) — there is no separate iOS read path to trace; it's the same two functions, one cutover point, not two. **This means the "4 mailboxes" framing has one more correction on top of §2's:** `jarvis_inbox`'s own writers (`app/services/monitors/calendar_monitor.py`, `reminder_monitor.py`, via `jarvis_inbox_service.py`) are themselves unreferenced anywhere else in the codebase — not imported, not scheduled (`scheduled_job` has zero rows matching either name), not called. `jarvis_inbox` is dead on **both** ends: no live writer, no live reader, 111 static historical rows. `autonomy_attention_item` is the only side of this with real traffic — its own write surface is 1 create call site (`AttentionQueueService.create_item()`, `app/services/autonomy/attention_queue.py:109`, already the sole INSERT — confirmed via full-repo grep) but **14 separate UPDATE call sites** across 6 files (`attention_queue.py` itself ×8, `memory_subscribers.py`, `notification_ack.py`, `tasks/attention.py` ×2, `tasks/autonomy.py`, `routes/autonomy_attention.py`) for status mutations (mark-sent, mark-read, archive, dedup-bump, etc.).

**`jarvis_inbox.kind` enum → `outbox_item.category` mapping.** `InboxKind` (Postgres enum `inboxkind`, `app/models/jarvis_inbox.py`) has exactly 4 values — `insight`, `alert`, `reminder`, `suggestion` — each a direct 1:1 string carry-over into the free-text `category` column (no collision with `autonomy_attention_item.category`'s existing free-text values). `InboxStatus` has 3 values (`new`/`read`/`archived` — no `sent` state, unlike `autonomy_attention_item`'s 4-state status) — maps directly into `outbox_item.status`'s superset.

**Dual-write mechanism, revised given the 14-call-site finding:** rather than hand-editing 14 UPDATE sites (real risk of missing one and silently desyncing the migration), dual-write is implemented as a **Postgres trigger** (`sync_attention_to_outbox()`, AFTER INSERT OR UPDATE on `autonomy_attention_item`, upserting the same row — same `id` — into `outbox_item`) for the transition window. This is provably complete — it fires on every write regardless of which of the 15 (or an as-yet-unfound 16th) code paths performed it — trading a small amount of DB-side logic for eliminating an entire class of "missed a call site" bugs a code-level dual-write would risk. The trigger is the *dual-write*, not the final state: step 8's drop still requires migrating the real write call sites onto `outbox_item` directly first (deferred — see the work-order item 13 status note in the main plan doc).

Real usage window for step 7 (David's rider, 2026-07-30): event counts, not elapsed time — ≥50 reads, ≥20 writes across web + iOS, badge parity on every check, zero regressions.
