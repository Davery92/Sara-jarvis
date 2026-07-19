"""
Fleet Celery tasks — offline detection + metric retention (FLEET_DESIGN.md §6.4, §5).

Report ingest runs the alert rules inline; these two beats cover the parts that
can't be triggered by a report:

  * ``offline_sweep`` — a host that has *stopped* reporting emits no event on its
    own, so a 5-min sweep fires/resolves ``host_offline``.
  * ``prune_metrics`` — nightly, drops ``host_metric`` rows older than 30 days.

Both are seeded as scheduled_job rows in alembic 100_fleet_agent.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict

from app.celery_app import celery_app

logger = logging.getLogger(__name__)

SOLO_USER_ID = os.getenv("SOLO_USER_ID", "64f37c56-85cb-4590-8de9-adfc17d343ed")


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@celery_app.task(bind=True, name="app.tasks.fleet.offline_sweep")
def offline_sweep(self) -> Dict[str, Any]:
    """Fire/resolve host_offline for every agent-equipped host."""
    from app.db.session import SessionLocal
    from app.models.managed_host import ManagedHost
    from app.services.fleet import alerts as fleet_alerts
    from app.core.config import settings

    interval = int(getattr(settings, "fleet_report_interval", 300) or 300)
    db = SessionLocal()
    transitions_by_user: Dict[str, list] = {}
    checked = 0
    try:
        hosts = (db.query(ManagedHost)
                 .filter(ManagedHost.active == True,  # noqa: E712
                         ManagedHost.transport.in_(("agent", "both")))
                 .all())
        for h in hosts:
            checked += 1
            try:
                trs = fleet_alerts.evaluate_offline(db, h, interval)
                if trs:
                    transitions_by_user.setdefault(h.user_id, []).extend(trs)
            except Exception as e:
                logger.warning(f"[fleet.offline_sweep] {h.name}: {e}")
    finally:
        db.close()

    total = 0
    for user_id, trs in transitions_by_user.items():
        total += len(trs)
        try:
            _run_async(fleet_alerts.emit_transitions(user_id, trs))
        except Exception as e:
            logger.warning(f"[fleet.offline_sweep] emit failed: {e}")

    logger.info(f"[fleet.offline_sweep] checked={checked} transitions={total}")
    return {"checked": checked, "transitions": total}


@celery_app.task(bind=True, name="app.tasks.fleet.prune_metrics")
def prune_metrics(self, days: int = 30) -> Dict[str, Any]:
    """Drop host_metric rows older than `days` (default 30)."""
    from app.db.session import SessionLocal
    from app.models.host_metric import HostMetric

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    db = SessionLocal()
    try:
        deleted = (db.query(HostMetric)
                   .filter(HostMetric.ts < cutoff)
                   .delete(synchronize_session=False))
        db.commit()
    finally:
        db.close()
    logger.info(f"[fleet.prune_metrics] deleted {deleted} rows older than {days}d")
    return {"deleted": deleted}
