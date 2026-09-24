"""Every migration must apply, fully reverse, and re-apply on an empty database."""

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, make_url, text

from settings import Settings

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


@pytest.fixture
def empty_db_url(settings: Settings) -> Iterator[str]:
    base = make_url(settings.database_url)
    name = f"ssa_migrations_{uuid.uuid4().hex[:8]}"
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield base.set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def _state(engine: Engine) -> tuple[str | None, bool]:
    with engine.connect() as conn:
        has_table = conn.execute(text("select to_regclass('alembic_version')")).scalar()
        rev = None
        if has_table:
            rev = conn.execute(text("select version_num from alembic_version")).scalar()
        has_vector = conn.execute(
            text("select exists(select 1 from pg_extension where extname = 'vector')")
        ).scalar()
    return rev, bool(has_vector)


def test_upgrade_downgrade_upgrade(empty_db_url: str) -> None:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", empty_db_url.replace("%", "%%"))
    head = ScriptDirectory.from_config(cfg).get_current_head()
    engine = create_engine(empty_db_url)
    try:
        command.upgrade(cfg, "head")
        assert _state(engine) == (head, True)

        command.downgrade(cfg, "base")
        assert _state(engine) == (None, False)

        command.upgrade(cfg, "head")
        assert _state(engine) == (head, True)
    finally:
        engine.dispose()
