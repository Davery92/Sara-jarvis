from logging.config import fileConfig
import sys
import os

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Add the parent directory to sys.path so we can import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# NOTE (2026-09-22 incident follow-up): unlike pytest (which routes through
# tests/conftest.py's assert_disposable_test_environment() guard before any
# app import), `alembic <command>` is a legitimate, deliberate way to run
# migrations against the REAL production database — that guard must NOT be
# applied here, or real migrations would become impossible. What IS fixed
# here is narrower: `from app.main_simple import Base` below transitively
# imports app.db.base, which creates its own SQLAlchemy engine from
# DATABASE_URL at import time — so a genuinely unset DATABASE_URL still
# fails here (via that import), just before reaching this file's own
# _require_database_url() check further down. Both paths refuse to
# silently default anywhere; neither can accidentally target production
# by omission now that alembic.ini's hardcoded fallback is gone.

# Import the Base and all models
from app.main_simple import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


class DatabaseURLNotConfigured(RuntimeError):
    """Raised when neither DATABASE_URL nor alembic.ini's sqlalchemy.url is
    set. 2026-09-22 incident follow-up: alembic.ini used to hardcode the
    production credential as a fallback here, so a missing DATABASE_URL
    silently ran migrations against production instead of failing. Now
    DATABASE_URL must be set explicitly (alembic.ini's own sqlalchemy.url
    is left blank) — an absent target is an error, not a silent default."""


def _require_database_url() -> str:
    url = os.getenv("DATABASE_URL") or config.get_main_option("sqlalchemy.url")
    if not url:
        raise DatabaseURLNotConfigured(
            "DATABASE_URL is not set and alembic.ini's sqlalchemy.url is "
            "blank. Set DATABASE_URL explicitly before running migrations — "
            "there is no default target."
        )
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = _require_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _require_database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
