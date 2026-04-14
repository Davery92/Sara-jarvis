"""DB-backed Celery beat scheduler.

Loads its schedule from the `scheduled_job` table and reloads periodically
so edits made via the settings API/UI take effect without restarting beat.
"""
from .db_scheduler import DBScheduler

__all__ = ["DBScheduler"]
