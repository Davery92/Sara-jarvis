"""Execute/commit/rollback helpers that work against either an AsyncSession
or a sync Session, for code reachable from both async (FastAPI) and sync
(Celery) callers. ``db.execute()`` etc. return an awaitable on AsyncSession
but a plain result on sync Session — calling ``await`` on the latter raises
TypeError, which is how held notifications silently vanished (never flushed,
rolled back) when the research-brief Celery path passed a sync Session.
"""
import inspect
from typing import Any, Dict, Optional


async def db_execute(db: Any, query, params: Optional[Dict[str, Any]] = None):
    result = db.execute(query, params or {})
    if inspect.isawaitable(result):
        return await result
    return result


async def db_commit(db: Any):
    result = db.commit()
    if inspect.isawaitable(result):
        return await result
    return result


async def db_rollback(db: Any):
    result = db.rollback()
    if inspect.isawaitable(result):
        return await result
    return result
