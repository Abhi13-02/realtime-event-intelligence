"""
Alembic environment configuration.

This file runs every time an Alembic command is executed (migrate, upgrade,
downgrade, autogenerate, etc.). Its job is to connect Alembic to:
  1. Your database (via a sync SQLAlchemy connection)
  2. Your models (via Base.metadata — so autogenerate can diff the schema)
"""

import logging
import sys
from pathlib import Path
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# Ensure the project root is importable when Alembic runs inside Docker.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Import your models' Base so Alembic can see the current desired schema.
# This is what makes --autogenerate work: Alembic diffs Base.metadata
# (what your models say the DB should look like) against the live DB.
from app.db.models import Base
from app.config import get_settings

logger = logging.getLogger("alembic.env")

# Alembic Config object — gives access to alembic.ini values.
config = context.config

# Wire up Python logging from alembic.ini.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Tell Alembic what the schema *should* look like (from your SQLAlchemy models).
# Required for --autogenerate to produce meaningful diffs.
target_metadata = Base.metadata


def get_sync_url() -> str:
    """
    Build a synchronous database URL for Alembic.

    The app uses postgresql+asyncpg (async driver) for FastAPI. Alembic needs
    a synchronous driver to run migrations. We swap asyncpg → psycopg2, which
    is already installed (psycopg2-binary in requirements.txt).

    This avoids adding a separate SYNC_DATABASE_URL env variable — we derive
    it automatically from the existing DATABASE_URL.
    """
    settings = get_settings()
    return settings.database_url.replace("postgresql+asyncpg", "postgresql+psycopg2")


def run_migrations_offline() -> None:
    """
    Run migrations without a live database connection (--sql mode).

    Outputs raw SQL to stdout instead of executing it. Useful for:
    - Reviewing what a migration will do before running it
    - Generating SQL scripts for a DBA to apply manually in production

    You can invoke this with: alembic upgrade head --sql
    """
    url = get_sync_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Include schema objects like CHECK constraints in autogenerate output.
        include_schemas=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations against a live database connection (default mode).

    Creates a real connection, acquires the Alembic lock, runs the migration,
    then commits and closes. This is what `alembic upgrade head` does.
    """
    # Override the URL in alembic.ini with our sync URL from .env.
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_sync_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # No pooling for migrations — open, migrate, close.
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Render CHECK constraints and server defaults in autogenerate output.
            include_schemas=True,
            compare_type=True,          # Detect column type changes.
            compare_server_default=True, # Detect server_default changes.
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
