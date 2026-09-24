"""Alembic environment. The database URL comes from `settings.Settings`
unless a caller (e.g. a test) sets `sqlalchemy.url` on the Config explicitly."""

from alembic import context
from sqlalchemy import create_engine, pool

from settings import get_settings

config = context.config

# No ORM models yet; point this at the declarative Base's metadata once one exists.
target_metadata = None


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
