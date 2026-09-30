"""R06 remainder (Sara repair plan 2026-09-25): overdue catch-up and
no-duplicate-delivery for reminder/timer dispatch.

Extended in round 4 (2026-09-27 review remediation) — see below.

`notification_predispatch()` (app/tasks/inproc_schedulers.py) selected
items due in a narrow `now <= due_at <= now+20s` window with no persisted
delivery state at all — an item whose due time passed while the task
missed a beat (worker down, deploy restart, a slow prior run) silently
never fired, because `now <= due_at` becomes false the moment `due_at`
slips into the past. There was also no protection against dispatching the
same occurrence twice if the task ever overlapped or re-ran.

Additive, nullable columns on both `reminder` and `timer`:

- `notified_at` — set ONLY when an occurrence reaches a TERMINAL outcome
  (`sent`, `missed`, or `failed_permanent` — see `delivery_status` below),
  never before the outcome is actually known. This is the catch-up key
  (selection becomes "due and not yet terminally resolved," which
  naturally includes anything overdue, not just the next few seconds).
- `delivery_status` — round 4 extends this from a two-value flag
  (`sent`/`missed`) into a real state machine: `claimed` (an attempt is
  in flight — NOT yet a delivery outcome), `sent` (terminal success),
  `failed` (a dispatch attempt failed but retries remain — non-terminal),
  `failed_permanent` (terminal — retries exhausted), `missed` (terminal —
  overdue past the bounded catch-up window, never attempted or retried
  further).
- `claimed_at` (round 4, new) — when the CURRENT claim was taken. A claim
  that is never resolved (the worker crashed between claiming and
  recording an outcome) becomes reclaimable by a later run once
  `claimed_at` is older than `CLAIM_EXPIRY` — this IS the outcome-
  reconciliation mechanism: the next run's own selection query picks the
  stale claim back up, there is no separate sweep process.
- `delivery_attempts` (round 4, new) — count of dispatch attempts made;
  bounds retries (`MAX_DELIVERY_ATTEMPTS` in inproc_schedulers.py).
- `last_error` (round 4, new) — the most recent dispatch failure's error
  text, for diagnostics; never a stand-in for a real outcome status.

Round 4 fix, precisely: the round-3 version of `_claim_for_dispatch` set
`notified_at`/`delivery_status='sent'` in the SAME atomic UPDATE used to
CLAIM the occurrence — i.e. it recorded success BEFORE the push was ever
attempted. A crash or send failure between the claim and the actual send
left the occurrence marked 'sent' forever, even though nothing was ever
delivered — the exact defect review finding 1 named. The claim and the
outcome are now two separate writes: claiming only sets
`delivery_status='claimed'` + `claimed_at`; the REAL outcome (`sent` or a
bounded-retry `failed`/`failed_permanent`) is written only after the
actual dispatch attempt returns, and the claim's own WHERE clause
re-checks the occurrence is still active/not-completed (cancellation/
reschedule made between selection and claim is caught here, not only at
selection time).

NOT applied to any running database as part of this repair session — see
the repair status document for the deployment boundary.

Review remediation note (2026-09-27): this revision's ID was originally
`158_reminder_timer_delivery_tracking` (36 characters) — `alembic upgrade`
against a real, disposable Postgres (not just this file's own raw-SQL
self-provisioning in tests, which never exercises alembic's own
bookkeeping) failed with `StringDataRightTruncation: value too long for
type character varying(32)`, because `alembic_version.version_num` is
`VARCHAR(32)`. Renamed to fit. This is exactly the gap "migrations
applied nowhere does not demonstrate migration readiness" named — caught
only by actually running `alembic upgrade head`/`alembic downgrade` end to
end against a disposable database, which this revision (and 155-157) now
has been, cleanly in both directions — see the repair status document for
the exact commands and result.

Revision ID: 158_reminder_delivery_state
Revises: 157_action_receipt_chat_wiring
Create Date: 2026-09-26, extended 2026-09-27
"""
from alembic import op
import sqlalchemy as sa

revision = "158_reminder_delivery_state"
down_revision = "157_action_receipt_chat_wiring"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    for table in ("reminder", "timer"):
        bind.execute(sa.text(f"""
            ALTER TABLE {table}
            ADD COLUMN IF NOT EXISTS notified_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS delivery_status VARCHAR(20),
            ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS delivery_attempts INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS last_error TEXT
        """))


def downgrade():
    bind = op.get_bind()
    for table in ("reminder", "timer"):
        bind.execute(sa.text(f"""
            ALTER TABLE {table}
            DROP COLUMN IF EXISTS notified_at,
            DROP COLUMN IF EXISTS delivery_status,
            DROP COLUMN IF EXISTS claimed_at,
            DROP COLUMN IF EXISTS delivery_attempts,
            DROP COLUMN IF EXISTS last_error
        """))
