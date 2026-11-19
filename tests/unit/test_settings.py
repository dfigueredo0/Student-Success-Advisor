import pytest
from pydantic import ValidationError

from settings import Settings


def test_defaults_match_compose_stack() -> None:
    s = Settings(_env_file=None)
    assert s.database_url.startswith("postgresql+psycopg://")


def test_env_overrides_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/x")
    s = Settings(_env_file=None)
    assert s.database_url == "postgresql+psycopg://u:p@db:5432/x"


def test_secrets_are_not_printed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-not-for-printing")
    assert "sk-not-for-printing" not in repr(Settings(_env_file=None))


def test_no_secret_has_a_built_in_value() -> None:
    s = Settings(_env_file=None)
    assert s.litellm_master_key.get_secret_value() == ""
    assert s.langfuse_secret_key.get_secret_value() == ""
    assert ":postgres@" not in s.database_url


def test_prod_refuses_missing_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "prod")
    with pytest.raises(ValidationError, match="LITELLM_MASTER_KEY"):
        Settings(_env_file=None)


def test_prod_starts_with_every_secret_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://postgres:pw@db:5432/ssa")
    for name in (
        "LITELLM_MASTER_KEY",
        "LITELLM_ROUTER_KEY",
        "LITELLM_CATALOG_KEY",
        "LITELLM_CAREER_KEY",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
    ):
        monkeypatch.setenv(name, "x" * 24)
    assert Settings(_env_file=None).env == "prod"


def test_unknown_env_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "staging")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
