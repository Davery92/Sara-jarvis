from sqlalchemy import inspect, text
from app.db.base import engine, SessionLocal
import logging
import os

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared async session factory (per-event-loop singleton)
# ---------------------------------------------------------------------------
_async_engine = None
_AsyncSessionLocal = None
# Identity of the loop the engine was built on. We keep a WEAKREF to the loop
# object, NOT id(loop): CPython reuses the id() of a freed object, so a new
# asyncio.run() loop can land on the same id() a previous (now-closed) loop had.
# The old guard then thought "same loop", kept the stale engine, and handed out
# connections bound to a closed loop — the "underlying connection is closed" /
# rollback-on-closed-connection errors on the check-in sweep. Identity via a live
# weakref is collision-free; a dead weakref means the loop was GC'd -> rebuild.
_async_loop_ref = None      # weakref.ref to the loop the engine was built on
_async_loop_id = None       # kept only for _try_dispose_engine's skip check
_async_pid = None


def _get_async_url() -> str:
    """Convert sync DATABASE_URL to asyncpg-compatible URL."""
    url = os.getenv("DATABASE_URL", str(engine.url))
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
    return url


def _current_loop_id() -> int:
    """Return id() of the running event loop, or 0 if none."""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        return id(loop)
    except RuntimeError:
        return 0


def reset_async_session_factory():
    """Drop the cached async engine so the next call recreates it.

    Call this at the top of any Celery task that uses asyncio.run() to avoid
    'Event loop is closed' / 'Future attached to a different loop' errors. The
    old engine is abandoned (its connections belong to a closed/other loop, so it
    cannot be disposed cleanly from here) and closed when garbage-collected.
    """
    global _async_engine, _AsyncSessionLocal, _async_loop_ref, _async_loop_id, _async_pid
    _async_engine = None
    _AsyncSessionLocal = None
    _async_loop_ref = None
    _async_loop_id = None
    _async_pid = None


def _use_async_null_pool() -> bool:
    value = (
        os.getenv("ACS_ASYNC_DB_NULLPOOL")
        or os.getenv("ASYNC_DB_NULLPOOL")
        or ""
    ).strip().lower()
    return value in {"1", "true", "yes", "on"}


def _try_dispose_engine(engine, engine_loop_id: int | None = None):
    """Best-effort dispose of an async engine without crossing event loops.

    Asyncpg connections are bound to the loop that created them. Disposing the
    engine on a different loop raises the exact "Future attached to a different
    loop" / "Event loop is closed" errors ACS has been hitting in Celery.
    """
    try:
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            if engine_loop_id and id(loop) != engine_loop_id:
                logger.debug("Skipping async engine dispose across event loops")
                return
            loop.create_task(engine.dispose())
        except RuntimeError:
            logger.debug("Skipping async engine dispose without a running loop")
    except Exception as e:
        logger.debug(f"Async engine dispose skipped: {e}")


def get_async_session_factory():
    """Return a shared async sessionmaker, recreated when the event loop changes.

    Safe to call from Celery tasks that use asyncio.run() — the engine is
    automatically rebuilt if the event loop has changed since last creation.
    """
    global _async_engine, _AsyncSessionLocal, _async_loop_ref, _async_loop_id, _async_pid
    import asyncio
    import weakref
    current_pid = os.getpid()
    try:
        cur_loop = asyncio.get_running_loop()
    except RuntimeError:
        cur_loop = None

    cached_loop = _async_loop_ref() if _async_loop_ref is not None else None
    stale = (
        _AsyncSessionLocal is None
        or _async_pid != current_pid
        # Identity comparison — collision-free (see _async_loop_ref note above).
        or (cur_loop is not None and cached_loop is not cur_loop)
        # Cached loop was GC'd or closed underneath us.
        or (cached_loop is None and _AsyncSessionLocal is not None and cur_loop is not None)
        or (cached_loop is not None and cached_loop.is_closed())
    )
    if stale:
        # Abandon the old engine. Its connections are bound to a closed/other loop
        # and cannot be disposed from here without raising; GC closes them.
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.orm import sessionmaker as sa_sessionmaker
        engine_kwargs = {
            "echo": False,
            "pool_pre_ping": not _use_async_null_pool(),
        }
        if _use_async_null_pool():
            from sqlalchemy.pool import NullPool
            engine_kwargs["poolclass"] = NullPool
        _async_engine = create_async_engine(_get_async_url(), **engine_kwargs)
        _AsyncSessionLocal = sa_sessionmaker(
            _async_engine, class_=AsyncSession, expire_on_commit=False,
        )
        _async_loop_ref = weakref.ref(cur_loop) if cur_loop is not None else None
        _async_loop_id = id(cur_loop) if cur_loop is not None else None
        _async_pid = current_pid
    return _AsyncSessionLocal


def get_db():
    """Dependency to get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ensure_note_metadata_columns():
    """Backfill new note metadata columns for existing databases."""
    inspector = inspect(engine)
    if "note" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("note")}
    if "tags" in existing_columns and "starred" in existing_columns:
        return

    dialect = engine.dialect.name

    with engine.begin() as conn:
        if "starred" not in existing_columns:
            starred_default = "0" if dialect == "sqlite" else "FALSE"
            conn.execute(
                text(f"ALTER TABLE note ADD COLUMN starred BOOLEAN DEFAULT {starred_default} NOT NULL")
            )

        if "tags" not in existing_columns:
            if dialect == "sqlite":
                conn.execute(text("ALTER TABLE note ADD COLUMN tags JSON DEFAULT '[]' NOT NULL"))
            else:
                conn.execute(text("ALTER TABLE note ADD COLUMN tags JSON DEFAULT '[]'::json NOT NULL"))


async def create_tables():
    """Create database tables and extensions"""
    from app.models import user, note, folder, reminder, calendar, episode, memory, doc, user_role
    
    # Import all models to ensure they're registered
    
    # Create extensions first
    with engine.connect() as conn:
        try:
            # Enable required PostgreSQL extensions
            conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
            conn.execute(text('CREATE EXTENSION IF NOT EXISTS vector'))
            conn.commit()
            logger.info("Database extensions created successfully")
        except Exception as e:
            logger.error(f"Error creating extensions: {e}")
            
    # Create all tables
    try:
        user.Base.metadata.create_all(bind=engine)
        note.Base.metadata.create_all(bind=engine)
        _ensure_note_metadata_columns()
        reminder.Base.metadata.create_all(bind=engine)
        calendar.Base.metadata.create_all(bind=engine)
        episode.Base.metadata.create_all(bind=engine)
        memory.Base.metadata.create_all(bind=engine)
        doc.Base.metadata.create_all(bind=engine)
        user_role.Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Error creating tables: {e}")
        raise
