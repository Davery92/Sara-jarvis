"""
Health monitoring tasks for Sara's cognitive architecture.

These tasks monitor system health and alert on issues.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any

from app.celery_app import celery_app

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
    import os
    from sqlalchemy import create_engine, text

    health_report = {
        "timestamp": datetime.utcnow().isoformat(),
        "checks": {},
        "overall_status": HealthStatus.HEALTHY,
    }

    # Check Redis
    try:
        redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
        r = redis.from_url(redis_url)
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
        redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
        r = redis.from_url(redis_url)

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

    # Check consolidation status
    try:
        redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
        r = redis.from_url(redis_url)

        last_run = r.get("consolidation:last_run")
        if last_run:
            last_run_time = datetime.fromisoformat(last_run.decode())
            age = datetime.utcnow() - last_run_time

            if age > timedelta(minutes=5):
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
        redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
        r = redis.from_url(redis_url)
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
        redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
        r = redis.from_url(redis_url)
        import json
        r.setex("system:health_status", 600, json.dumps(health_report))
    except Exception as e:
        logger.warning(f"Failed to store health status: {e}")

    logger.info(f"System heartbeat: {health_report['overall_status']}")

    return health_report
