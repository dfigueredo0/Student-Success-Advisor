import pytest
from pydantic import ValidationError

from settings import Settings


def test_defaults_match_compose_stack() -> None:
    s = Settings(_env_file=None)
    assert s.database_url.startswith("postgresql+psycopg://")
    assert s.litellm_base_url == "http://localhost:4000"
    assert s.llm_default_model == "local-llm"


def test_env_overrides_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/x")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-other")
    s = Settings(_env_file=None)
    assert s.database_url == "postgresql+psycopg://u:p@db:5432/x"
    assert s.litellm_master_key.get_secret_value() == "sk-other"


def test_secrets_are_not_printed() -> None:
    assert "sk-ssa-dev-master-key" not in repr(Settings(_env_file=None))


def test_unknown_env_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "staging")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
