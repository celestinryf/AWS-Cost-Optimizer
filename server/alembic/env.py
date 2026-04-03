"""Alembic env.py — runs migrations using raw SQL (no ORM models).

The app uses raw sqlite3, not SQLAlchemy ORM. Alembic is used here purely
for migration version tracking. Migrations are written with op.execute().

DB resolution order (first match wins):
  1. DATABASE_URL env var  — full SQLAlchemy URL, e.g. sqlite:///data/runs.db
  2. RUNS_DB_PATH env var  — bare file path, e.g. data/runs.db (wrapped in
                             sqlite:///…) — mirrors the app's own default in
                             server/app/dependencies.py
  3. sqlalchemy.url in alembic.ini
"""

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Resolve the target DB using the same precedence the application uses.
# DATABASE_URL takes priority; RUNS_DB_PATH is the fallback so that Alembic
# always migrates the same file the app is reading from.
database_url = os.environ.get("DATABASE_URL")
if not database_url:
    runs_db_path = os.environ.get("RUNS_DB_PATH")
    if runs_db_path:
        database_url = f"sqlite:///{runs_db_path}"
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
