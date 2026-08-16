"""
Health monitoring tasks for Sara's cognitive architecture.

These tasks monitor system health and alert on issues.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any

from app.celery_app import celery_app
from app.core.config import get_owner_id

logger = logging.getLogger(__name__)


class HealthStatus:
    HEALTHY = "healthy"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@celery_app.task(bind=True, name="app.tasks.health.system_heartbeat")
def system_heartbeat(self) -> Dict[str, Any]:
    """
    Check system health every 5 minutes.
    Verifies all critical services are responsive.
    """
    import redis
    from app.core.redis import get_redis_sync_bytes
    import os
    from sqlalchemy import create_engine, text

    health_report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {},
        "overall_status": HealthStatus.HEALTHY,
    }

    # Check Redis
    try:
        r = get_redis_sync_bytes()
        r.ping()
        health_report["checks"]["redis"] = {
            "status": HealthStatus.HEALTHY,
            "message": "Redis responding"
        }
    except Exception as e:
        health_report["checks"]["redis"] = {
            "status": HealthStatus.ERROR,
            "message": f"Redis error: {str(e)}"
        }
        health_report["overall_status"] = HealthStatus.ERROR

    # Check PostgreSQL
    try:
        database_url = os.getenv("DATABASE_URL", "")
        if database_url:
            engine = create_engine(database_url)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            health_report["checks"]["database"] = {
                "status": HealthStatus.HEALTHY,
                "message": "Database responding"
            }
    except Exception as e:
        health_report["checks"]["database"] = {
            "status": HealthStatus.ERROR,
            "message": f"Database error: {str(e)}"
        }
        health_report["overall_status"] = HealthStatus.ERROR

    # Check raw buffer status (once implemented)
    try:
        r = get_redis_sync_bytes()

        # Check if raw buffer streams exist and have recent data
        streams = ["raw_buffer:text", "raw_buffer:screen", "raw_buffer:notification"]
        buffer_status = {}

        for stream in streams:
            try:
                info = r.xinfo_stream(stream)
                buffer_status[stream] = {
                    "length": info.get("length", 0),
                    "last_entry": info.get("last-generated-id", "none")
                }
            except redis.exceptions.ResponseError:
                # Stream doesn't exist yet - that's OK during initial setup
                buffer_status[stream] = {"length": 0, "last_entry": "not_created"}

        health_report["checks"]["raw_buffer"] = {
            "status": HealthStatus.HEALTHY,
            "message": "Buffer streams accessible",
            "details": buffer_status
        }
    except Exception as e:
        health_report["checks"]["raw_buffer"] = {
            "status": HealthStatus.WARNING,
            "message": f"Buffer check warning: {str(e)}"
        }

    # Check consolidation status.
    #
    # `consolidation:last_deep_run` is stamped by app.tasks.autonomy.run_consolidation
    # (app.services.consolidation.consolidation_engine) — the job that actually
    # turns episodes into knowledge, scheduled 2x/day (2PM/9PM) plus a nightly
    # pass (~3:40AM). The longest gap between those is ~10.5h, so 16h gives
    # headroom for the single retry (countdown=120s) before flagging real
    # trouble.
    #
    # This is deliberately NOT `consolidation:last_run` (app.tasks.consolidation
    # .run_consolidation) — that's a separate, event-driven raw-sensory-buffer
    # compaction path fed by raw_buffer:* Redis streams with no current
    # producer in this deployment, so it legitimately sits idle. A 5-minute
    # staleness threshold on that key was flagging an idle-but-fine subsystem
    # as "degraded" and describing it to David as "episodes aren't being
    # turned into knowledge" — which was never true; that's this check's job.
    try:
        r = get_redis_sync_bytes()

        last_run = r.get("consolidation:last_deep_run")
        if last_run:
            last_run_time = datetime.fromisoformat(last_run.decode())
            age = datetime.now(timezone.utc) - last_run_time

            if age > timedelta(hours=16):
                health_report["checks"]["consolidation"] = {
                    "status": HealthStatus.WARNING,
                    "message": f"Consolidation last ran {age} ago"
                }
            else:
                health_report["checks"]["consolidation"] = {
                    "status": HealthStatus.HEALTHY,
                    "message": f"Consolidation ran {age} ago"
                }
        else:
            health_report["checks"]["consolidation"] = {
                "status": HealthStatus.WARNING,
                "message": "Consolidation never ran (or just started)"
            }
    except Exception as e:
        health_report["checks"]["consolidation"] = {
            "status": HealthStatus.WARNING,
            "message": f"Consolidation check warning: {str(e)}"
        }

    # Check working memory
    try:
        r = get_redis_sync_bytes()
        solo_user_id = os.getenv("SOLO_USER_ID", "")

        if solo_user_id:
            wm_key = f"working_memory:{solo_user_id}:context"
            exists = r.exists(wm_key)

            health_report["checks"]["working_memory"] = {
                "status": HealthStatus.HEALTHY,
                "message": "Working memory accessible",
                "initialized": exists == 1
            }
        else:
            health_report["checks"]["working_memory"] = {
                "status": HealthStatus.WARNING,
                "message": "SOLO_USER_ID not set"
            }
    except Exception as e:
        health_report["checks"]["working_memory"] = {
            "status": HealthStatus.WARNING,
            "message": f"Working memory check warning: {str(e)}"
        }

    # Check LLM endpoints
    try:
        import httpx
        llm_primary = os.getenv("OPENAI_BASE_URL", "http://100.104.68.115:8081/v1")
        llm_fallback = os.getenv("FAST_MODEL_URL", "http://10.185.1.8:8686/v1")
        for name, url in [("llm_primary", llm_primary), ("llm_fallback", llm_fallback)]:
            try:
                resp = httpx.get(f"{url}/models", timeout=5.0)
                health_report["checks"][name] = {
                    "status": HealthStatus.HEALTHY if resp.status_code == 200 else HealthStatus.WARNING,
                    "message": f"{url} status={resp.status_code}"
                }
            except Exception as e:
                health_report["checks"][name] = {
                    "status": HealthStatus.ERROR,
                    "message": f"{url} unreachable: {str(e)[:100]}"
                }
    except Exception as e:
        health_report["checks"]["llm_primary"] = {"status": HealthStatus.WARNING, "message": f"LLM check skipped: {e}"}

    # Check embedding service
    try:
        import httpx
        embed_url = os.getenv("EMBEDDING_BASE_URL", "http://embeddings:8100")
        resp = httpx.get(f"{embed_url}/health", timeout=5.0)
        health_report["checks"]["embeddings"] = {
            "status": HealthStatus.HEALTHY if resp.status_code == 200 else HealthStatus.WARNING,
            "message": f"Embedding service status={resp.status_code}"
        }
    except Exception as e:
        health_report["checks"]["embeddings"] = {
            "status": HealthStatus.ERROR,
            "message": f"Embedding service unreachable: {str(e)[:100]}"
        }

    # Check Celery queue depths
    try:
        r = get_redis_sync_bytes()
        queues = ["critical", "cognitive", "health", "input", "maintenance", "low_priority", "reflection", "acs"]
        queue_depths = {}
        for q in queues:
            depth = r.llen(q)
            queue_depths[q] = depth
        max_depth = max(queue_depths.values()) if queue_depths else 0
        health_report["checks"]["queue_depths"] = {
            "status": HealthStatus.WARNING if max_depth > 50 else HealthStatus.HEALTHY,
            "message": f"Max queue depth: {max_depth}",
            "details": queue_depths
        }
    except Exception as e:
        health_report["checks"]["queue_depths"] = {
            "status": HealthStatus.WARNING,
            "message": f"Queue depth check failed: {str(e)[:100]}"
        }

    # Determine overall status
    statuses = [check["status"] for check in health_report["checks"].values()]
    if HealthStatus.CRITICAL in statuses:
        health_report["overall_status"] = HealthStatus.CRITICAL
    elif HealthStatus.ERROR in statuses:
        health_report["overall_status"] = HealthStatus.ERROR
    elif HealthStatus.WARNING in statuses:
        health_report["overall_status"] = HealthStatus.WARNING
    else:
        health_report["overall_status"] = HealthStatus.HEALTHY

    # Store health status in Redis for quick access
    try:
        r = get_redis_sync_bytes()
        import json
        r.setex("system:health_status", 600, json.dumps(health_report, default=str))
    except Exception as e:
        logger.warning(f"Failed to store health status: {e}")

    # Interoception (ONE_MIND §3.1): feed this health report — plus daemon
    # liveness and host reachability — into Sara's own body-sense. It emits
    # SYSTEM_HEALTH_DEGRADED/RECOVERED events onto the salience pipeline and
    # sends the composed, cooldown-gated alert through the one attention
    # economy. Runs on EVERY tick (not just error) so recovery transitions and
    # daemon/host checks are caught even when the local checks are green.
    _run_body_sense(health_report)

    logger.info(f"System heartbeat: {health_report['overall_status']}")

    return health_report


def _run_body_sense(health_report: dict):
    """Drive Sara's interoception from the heartbeat's health report."""
    import asyncio
    import os
    try:
        from app.services.body_sense import reflect
        user_id = get_owner_id()

        async def _go():
            await reflect(health_report, user_id=user_id)

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(_go())
            else:
                loop.run_until_complete(_go())
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_go())
            finally:
                loop.close()
    except Exception as e:
        logger.warning(f"Body-sense reflection failed: {e}")
