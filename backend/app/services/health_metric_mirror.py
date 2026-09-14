"""Mirror HRV readings into `health_metric` at ingest time.

Why this exists
---------------
Two stores received the same watch reading and disagreed:

  * ``daily_recovery_log.hrv`` — written by ``POST /api/health/sync-recovery``
    (iOS ``healthSync.ts`` → ``getLatestHRV()``, any sample in the last 24h).
    Read by the weekly health note, the morning brief, progressive overload
    and the recovery tool.
  * ``health_metric`` (``hrv_morning``) — written by
    ``POST /api/health/metrics/batch`` only when the sync happens between
    05:00 and 07:59 local AND a sample exists in the preceding 4 hours.
    Read by ``context_snapshot``, ``body_state_service``, ``readiness_engine``,
    ``emotional_state``, ``world_brief`` and ``health_baselines`` — i.e. by
    everything the chat persona actually sees.

The iOS gates meant ``hrv_morning`` landed on 11 of the last 30 days while the
recovery log had all 30, so Sara could truthfully say both "your HRV swung
between 16 and 137 last week" and "nothing recorded in the last 36 hours" in
the same reply. ``health_metric`` is the single authority for body numbers, so
the fix is on the write path: every ingest that learns an HRV number also
mirrors it into the authoritative store.

Idempotency: the canonical stamp is 06:00 **ET** on the reading's date, which is
exactly what iOS uses (``hrvRecordedAt.setHours(6,0,0,0)``). The unique index
``ix_health_metric_dedup (user_id, metric_type, recorded_at)`` therefore makes a
later real iOS ``hrv_morning`` for the same day a no-op rather than a duplicate.
"""

from __future__ import annotations

import json
import logging
import math
import uuid
from datetime import date, datetime, time
from typing import Optional, Union

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.timezone import USER_TIMEZONE, UTC, today as local_today

logger = logging.getLogger(__name__)

METRIC_TYPE = "hrv_morning"

# The hour (ET) iOS stamps a morning reading with. Keep in sync with
# ios-app/src/services/backgroundHealthSync.ts.
CANONICAL_HOUR_ET = 6


def canonical_recorded_at(on_date: date) -> datetime:
    """06:00 ET on ``on_date`` as an aware UTC datetime (10:00Z in EDT, 11:00Z in EST)."""
    local = datetime.combine(on_date, time(CANONICAL_HOUR_ET, 0), tzinfo=USER_TIMEZONE)
    return local.astimezone(UTC)


def mirror_hrv_morning(
    db: Session,
    user_id: str,
    hrv: Optional[Union[int, float]],
    on_date: Optional[date] = None,
    source: str = "apple_health",
    via: str = "sync-recovery",
) -> bool:
    """Upsert the canonical ``hrv_morning`` row (06:00 ET stamp) for ``on_date``.

    Returns True only if a row was actually inserted. Never raises — a failed
    mirror must not roll back the caller's real write — but always logs the real
    exception class first. Does NOT commit: the caller owns the transaction.
    """
    if hrv is None:
        return False
    try:
        value = float(hrv)
    except (TypeError, ValueError) as e:
        logger.warning("mirror_hrv_morning: non-numeric hrv %r (%s)", hrv, type(e).__name__)
        return False
    if not math.isfinite(value) or value <= 0:
        return False

    stamp = canonical_recorded_at(on_date or local_today())

    try:
        # SAVEPOINT: a failed mirror must not abort the caller's transaction —
        # in Postgres any error poisons the whole transaction otherwise, so the
        # real recovery-log write would fail to commit behind us.
        with db.begin_nested():
            row = db.execute(text("""
                INSERT INTO health_metric (id, user_id, metric_type, value, recorded_at, source, metadata)
                VALUES (:id, :uid, :mt, :val, :ts, :src, CAST(:meta AS jsonb))
                ON CONFLICT (user_id, metric_type, recorded_at) DO NOTHING
                RETURNING id
            """), {
                "id": str(uuid.uuid4()),
                "uid": user_id,
                "mt": METRIC_TYPE,
                "val": value,
                "ts": stamp,
                "src": source,
                "meta": json.dumps({"morning_reading": True, "sample_count": 1, "via": via}),
            }).fetchone()
    except Exception as e:
        logger.error(
            "mirror_hrv_morning failed (%s): user=%s hrv=%s via=%s: %s",
            type(e).__name__, user_id, hrv, via, e,
        )
        return False

    return row is not None
