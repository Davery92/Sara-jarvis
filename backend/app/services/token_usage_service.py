"""Token usage tracking service"""
import logging
import uuid
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Callable
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.token_usage import TokenUsage, TokenUsageAggregate

logger = logging.getLogger(__name__)

# Global context for tracking current request info
_request_context: Dict[str, Any] = {}

# Queue for storing token usage asynchronously
_token_queue: asyncio.Queue = None
_db_factory: Callable = None
_worker_task: asyncio.Task = None


def init_token_tracking(db_factory: Callable):
    """Initialize token tracking with database factory"""
    global _token_queue, _db_factory, _worker_task
    _db_factory = db_factory
    _token_queue = asyncio.Queue()
    _worker_task = asyncio.create_task(_token_worker())
    logger.info("📊 Token usage tracking initialized")


async def _token_worker():
    """Background worker to process token usage queue"""
    global _token_queue, _db_factory
    while True:
        try:
            # Wait for token usage data
            data = await _token_queue.get()
            if data is None:
                break  # Shutdown signal

            # Get a database session
            db = _db_factory()
            try:
                await log_token_usage(
                    db=db,
                    prompt_tokens=data.get("prompt_tokens", 0),
                    completion_tokens=data.get("completion_tokens", 0),
                    total_tokens=data.get("total_tokens", 0),
                    model=data.get("model", "unknown"),
                    operation_type=data.get("operation_type", "unknown"),
                    user_id=data.get("user_id"),
                    endpoint=data.get("endpoint", "unknown"),
                    session_id=data.get("session_id"),
                    metadata=data.get("metadata")
                )
            finally:
                db.close()

            _token_queue.task_done()

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Token worker error: {e}")


def record_token_usage_sync(
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    model: str,
    operation_type: str,
):
    """Write one usage row immediately, with no event loop involved.

    Follow-up plan §7. `queue_token_usage` is the FastAPI path: it hands work to
    an asyncio queue drained by a worker task created once at startup. A Celery
    prefork child has no such loop — each task runs its own `asyncio.run(...)`
    and throws the loop away — so a queue created at fork time would be drained
    by a worker task that dies with the first task's loop, and every background
    model call would report into a void.

    That is why `token_usage` held nothing but chat rows: appraisal, judge,
    deliberation and compose all run in Celery, so ~140 deliberations a day plus
    every other background call were invisible while chat was measured to the
    token.

    One small INSERT inside a call that just waited seconds on a model is not
    worth an async hop.
    """
    from app.db.base import SessionLocal

    try:
        with SessionLocal() as db:
            usage = TokenUsage(
                id=str(uuid.uuid4()),
                user_id=None,
                endpoint="celery",
                model=model,
                operation_type=operation_type,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            )
            db.add(usage)
            _apply_aggregate(db, None, prompt_tokens, completion_tokens, total_tokens)
            db.commit()
    except Exception as e:
        logger.warning(f"Failed to record background token usage for {operation_type}: {e}")


def queue_token_usage(
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    model: str,
    operation_type: str
):
    """Queue token usage for async processing (callback for LLM client)"""
    global _token_queue
    if _token_queue is None:
        logger.warning("Token queue not initialized")
        return

    ctx = get_request_context()
    try:
        _token_queue.put_nowait({
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "model": model,
            "operation_type": operation_type,
            "user_id": ctx.get("user_id"),
            "endpoint": ctx.get("endpoint", "unknown"),
            "session_id": ctx.get("session_id")
        })
    except asyncio.QueueFull:
        logger.warning("Token queue full, dropping usage data")


def set_request_context(
    user_id: Optional[str] = None,
    endpoint: Optional[str] = None,
    session_id: Optional[str] = None
):
    """Set the current request context for token tracking"""
    global _request_context
    _request_context = {
        "user_id": user_id,
        "endpoint": endpoint or "unknown",
        "session_id": session_id
    }


def get_request_context() -> Dict[str, Any]:
    """Get the current request context"""
    return _request_context.copy()


def clear_request_context():
    """Clear the request context"""
    global _request_context
    _request_context = {}


async def log_token_usage(
    db: Session,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    model: str,
    operation_type: str,
    user_id: Optional[str] = None,
    endpoint: Optional[str] = None,
    session_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
):
    """Log token usage to database"""
    try:
        # Use request context if parameters not provided
        ctx = get_request_context()
        user_id = user_id or ctx.get("user_id")
        endpoint = endpoint or ctx.get("endpoint", "unknown")
        session_id = session_id or ctx.get("session_id")

        usage = TokenUsage(
            id=str(uuid.uuid4()),
            user_id=user_id,
            endpoint=endpoint,
            model=model,
            operation_type=operation_type,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            session_id=session_id,
            request_metadata=metadata
        )
        db.add(usage)

        # Update aggregate table
        await update_aggregate(
            db,
            user_id=user_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens
        )

        db.commit()
        logger.debug(f"Logged token usage: {total_tokens} tokens for {operation_type}")

    except Exception as e:
        logger.error(f"Failed to log token usage: {e}")
        db.rollback()


def _apply_aggregate(
    db: Session,
    user_id: Optional[str],
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int
):
    """Update the aggregate token counts. Caller commits."""
    try:
        # Find or create aggregate record
        aggregate = db.query(TokenUsageAggregate).filter(
            TokenUsageAggregate.user_id == user_id
        ).first()

        if not aggregate:
            aggregate = TokenUsageAggregate(
                id=str(uuid.uuid4()),
                user_id=user_id,
                total_prompt_tokens=0,
                total_completion_tokens=0,
                total_tokens=0,
                total_requests=0
            )
            db.add(aggregate)

        aggregate.total_prompt_tokens += prompt_tokens
        aggregate.total_completion_tokens += completion_tokens
        aggregate.total_tokens += total_tokens
        aggregate.total_requests += 1
        aggregate.updated_at = datetime.now(timezone.utc)

    except Exception as e:
        logger.error(f"Failed to update token aggregate: {e}")


async def update_aggregate(
    db: Session,
    user_id: Optional[str],
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int
):
    """Async-signature wrapper kept for existing callers."""
    _apply_aggregate(db, user_id, prompt_tokens, completion_tokens, total_tokens)


def get_token_stats(db: Session, user_id: Optional[str] = None) -> Dict[str, Any]:
    """Get token usage statistics (global - sums all users)"""
    try:
        # Get aggregate stats - sum all aggregates for global view
        # This gives us total token usage across all users/sessions
        from sqlalchemy import func

        result = db.query(
            func.coalesce(func.sum(TokenUsageAggregate.total_prompt_tokens), 0).label('total_prompt_tokens'),
            func.coalesce(func.sum(TokenUsageAggregate.total_completion_tokens), 0).label('total_completion_tokens'),
            func.coalesce(func.sum(TokenUsageAggregate.total_tokens), 0).label('total_tokens'),
            func.coalesce(func.sum(TokenUsageAggregate.total_requests), 0).label('total_requests'),
            func.max(TokenUsageAggregate.last_reset_at).label('last_reset_at'),
            func.max(TokenUsageAggregate.updated_at).label('updated_at')
        ).first()

        if not result or result.total_tokens == 0:
            return {
                "total_prompt_tokens": 0,
                "total_completion_tokens": 0,
                "total_tokens": 0,
                "total_requests": 0,
                "last_reset_at": None,
                "updated_at": None
            }

        return {
            "total_prompt_tokens": int(result.total_prompt_tokens),
            "total_completion_tokens": int(result.total_completion_tokens),
            "total_tokens": int(result.total_tokens),
            "total_requests": int(result.total_requests),
            "last_reset_at": result.last_reset_at.isoformat() if result.last_reset_at else None,
            "updated_at": result.updated_at.isoformat() if result.updated_at else None
        }

    except Exception as e:
        logger.error(f"Failed to get token stats: {e}")
        return {
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_tokens": 0,
            "total_requests": 0,
            "error": str(e)
        }


def reset_token_stats(db: Session, user_id: Optional[str] = None) -> bool:
    """Reset token usage statistics (resets all aggregates for global view)"""
    try:
        # Reset all aggregate records for global reset
        aggregates = db.query(TokenUsageAggregate).all()

        for aggregate in aggregates:
            aggregate.total_prompt_tokens = 0
            aggregate.total_completion_tokens = 0
            aggregate.total_tokens = 0
            aggregate.total_requests = 0
            aggregate.last_reset_at = datetime.now(timezone.utc)
            aggregate.updated_at = datetime.now(timezone.utc)

        db.commit()
        logger.info(f"Reset token stats (all aggregates)")
        return True

    except Exception as e:
        logger.error(f"Failed to reset token stats: {e}")
        db.rollback()
        return False


def get_usage_breakdown(
    db: Session,
    user_id: Optional[str] = None,
    days: int = 30
) -> Dict[str, Any]:
    """Get breakdown of token usage by model and operation type"""
    try:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        query = db.query(
            TokenUsage.model,
            TokenUsage.operation_type,
            func.sum(TokenUsage.prompt_tokens).label('prompt_tokens'),
            func.sum(TokenUsage.completion_tokens).label('completion_tokens'),
            func.sum(TokenUsage.total_tokens).label('total_tokens'),
            func.count(TokenUsage.id).label('request_count')
        ).filter(
            TokenUsage.created_at >= cutoff
        )

        if user_id:
            query = query.filter(TokenUsage.user_id == user_id)

        results = query.group_by(
            TokenUsage.model,
            TokenUsage.operation_type
        ).all()

        breakdown = []
        for row in results:
            breakdown.append({
                "model": row.model,
                "operation_type": row.operation_type,
                "prompt_tokens": row.prompt_tokens or 0,
                "completion_tokens": row.completion_tokens or 0,
                "total_tokens": row.total_tokens or 0,
                "request_count": row.request_count or 0
            })

        return {
            "period_days": days,
            "breakdown": breakdown
        }

    except Exception as e:
        logger.error(f"Failed to get usage breakdown: {e}")
        return {"period_days": days, "breakdown": [], "error": str(e)}
