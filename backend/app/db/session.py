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
_async_loop_id = None  # track which event loop the engine was created on
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
    """Dispose the cached async engine so the next call recreates it.

    Call this at the top of any Celery task that uses asyncio.run() to avoid
    'Event loop is closed' / 'Future attached to a different loop' errors.
    """
    global _async_engine, _AsyncSessionLocal, _async_loop_id, _async_pid
    if _async_engine is not None:
        _try_dispose_engine(_async_engine, engine_loop_id=_async_loop_id)
    _async_engine = None
    _AsyncSessionLocal = None
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
    global _async_engine, _AsyncSessionLocal, _async_loop_id, _async_pid
    current_pid = os.getpid()
    cur_loop = _current_loop_id()
    if (
        _AsyncSessionLocal is None
        or _async_pid != current_pid
        or (cur_loop and cur_loop != _async_loop_id)
    ):
        # Process or event loop changed (or first call) — rebuild engine
        if _async_engine is not None:
            _try_dispose_engine(_async_engine, engine_loop_id=_async_loop_id)
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
        _async_loop_id = cur_loop
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
