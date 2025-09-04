from sqlalchemy import text
from app.db.base import engine, SessionLocal
import logging

logger = logging.getLogger(__name__)


def get_db():
    """Dependency to get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def create_tables():
    """Create database tables and extensions"""
    from app.models import user, note, folder, reminder, calendar, episode, memory, doc
    # Import fitness models explicitly to ensure tables are created
    from app.models import fitness as fitness_models  # noqa: F401
    
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
        reminder.Base.metadata.create_all(bind=engine)
        calendar.Base.metadata.create_all(bind=engine)
        episode.Base.metadata.create_all(bind=engine)
        memory.Base.metadata.create_all(bind=engine)
        doc.Base.metadata.create_all(bind=engine)
        # Create fitness tables
        try:
            fitness_models.Base.metadata.create_all(bind=engine)
        except Exception as e:
            logger.error(f"Error creating fitness tables: {e}")
            raise
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Error creating tables: {e}")
        raise
