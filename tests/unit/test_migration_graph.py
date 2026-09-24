from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def test_single_head() -> None:
    heads = ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_heads()
    assert len(heads) == 1, f"multiple alembic heads, merge them: {heads}"
