"""Interoception alerts — Sara tells David when something inside her is broken.

Routes through the normal notification funnel under a dedicated ``health``
category with a 1/day/task cooldown (a broken task fires every few minutes; we
must not re-nag). This is a *feature*, not ops noise — the aliveness of a mind
that notices its own malfunction. Carries the diagnostics event_id so tapping
the alert (or asking "what's that about?") resolves to diagnostics_explain.
"""
from __future__ import annotations

import logging
from typing import Any, Dict
from app.core.config import get_owner_id

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = get_owner_id()
_COOLDOWN_SECONDS = 24 * 3600  # 1/day/task


def _sync_redis():
    from app.core.redis import get_redis_sync
    return get_redis_sync()


def _cooldown_ok(task_name: str) -> bool:
    """True if we haven't alerted about this task in the cooldown window. Sets the
    key atomically so concurrent workers don't double-send."""
    try:
        r = _sync_redis()
        key = f"sara:health_alert:{task_name}"
        # SET NX EX — returns True only if the key didn't exist.
        ok = bool(r.set(key, "1", nx=True, ex=_COOLDOWN_SECONDS))
        r.close()
        return ok
    except Exception as e:
        logger.debug(f"health cooldown check failed (allowing send): {e}")
        return True


async def escalate_task_failure(task_name: str, error_class: str, res: Dict[str, Any],
                                user_id: str = DEFAULT_USER_ID) -> Dict[str, Any]:
    """Send a health alert about a failing task, subject to the 1/day/task cooldown."""
    if not _cooldown_ok(task_name):
        return {"sent": False, "reason": "health_cooldown"}

    from app.services.diagnostics_service import feature_for_task
    feature = feature_for_task(task_name) or task_name.split(".")[-1]
    count = res.get("count_24h", 1)
    event_id = res.get("event_id")
    short = task_name.split(".")[-1]

    if count >= 3:
        body = (f"My {feature} has failed {count}× today ({error_class}). "
                f"Want me to write up a handoff for Claude Code?")
    else:
        body = (f"Something just broke: my {feature} hit a {error_class}. "
                f"I'll keep an eye on it — ask me 'what's broken?' for details.")

    try:
        from app.services.unified_notification import send_notification
        result = await send_notification(
            user_id=user_id,
            title="Sara: internal health",
            message=body,
            priority="normal",
            topic=f"health:{short}",
            category="system_health",
            source="interoception",
            extra_push_data={"target": "chat"},
            payload={
                "prediction_grade": "novel",
                "stimulus_key": f"health:{task_name}",
                "generator": "interoception",
                "event_id": event_id,
                "task_name": task_name,
                "diagnostics": True,
            },
        )
        logger.info(f"[interoception] health alert sent for {task_name}: {result}")
        return {"sent": True, "result": result, "event_id": event_id}
    except Exception as e:
        logger.error(f"[interoception] failed to send health alert: {e}")
        return {"sent": False, "error": str(e)}
