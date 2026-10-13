from logging.config import fileConfig
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import Connection, make_url

from app.config import get_settings
from app.core.db import Base
import app.models

config = context.config

if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def migration_database_url():
    url = make_url(get_settings().database_url)
    if url.drivername in {"postgresql", "postgresql+asyncpg", "postgresql+psycopg2"}:
        url = url.set(drivername="postgresql+psycopg")
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=migration_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(migration_database_url(), poolclass=pool.NullPool, connect_args={"connect_timeout": 15, "options": "-c lock_timeout=15000 -c statement_timeout=120000"})
    with connectable.connect() as connection:
        do_run_migrations(connection)
    connectable.dispose()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
