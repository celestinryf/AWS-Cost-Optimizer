"""Alembic env.py — runs migrations using raw SQL (no ORM models).

The app uses raw sqlite3, not SQLAlchemy ORM. Alembic is used here purely
for migration version tracking. Migrations are written with op.execute().

DATABASE_URL env var overrides the ini-file default, e.g.:
    DATABASE_URL=sqlite:///data/runs.db alembic upgrade head
"""

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Allow DATABASE_URL env var to override alembic.ini value.
database_url = os.environ.get("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

# No target_metadata since we use raw SQL migrations, not ORM autogenerate.
target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations without an active DB connection (emit SQL to stdout)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
