from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

engine = create_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_timeout=10,
    # Roll back any open transaction when a connection returns to the pool, so a
    # connection is never left INTRANS to poison the next checkout's pool_pre_ping
    # ("can't change 'autocommit' now: connection in transaction status INTRANS").
    # It's the default, but make it explicit given the sync/async mixing here.
    pool_reset_on_return="rollback",
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()