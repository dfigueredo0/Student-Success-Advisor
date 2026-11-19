"""infra/make_env.py gives every install its own random passwords and keys, and nothing in the
compose file falls back to a password published in this repo."""

import importlib.util
import re
import stat
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parents[2]
EXAMPLE = (ROOT / ".env.example").read_text()
COMPOSE = (ROOT / "infra" / "docker-compose.yml").read_text()
# The fixed values used before random secrets (Nov 2026). None may come back.
OLD_DEV_VALUES = [
    "postgres:postgres@",
    "sk-ssa-dev-master-key",
    "sk-ssa-router-dev",
    "pk-lf-ssa-dev",
    "sk-lf-ssa-dev",
    "ssa-dev-salt",
    "ssa-dev-nextauth-secret",
    "ssa-dev-password",
    "redissecret",
    "miniosecret",
    "0" * 64,
]


@pytest.fixture
def make_env() -> Any:
    spec = importlib.util.spec_from_file_location("make_env", ROOT / "infra" / "make_env.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_secret_is_filled_and_unique(make_env: Any) -> None:
    env = make_env.read_env(make_env.render(EXAMPLE))
    values = [env[name] for name in make_env.SECRETS]
    assert all(len(v) >= 24 for v in values)
    assert len(set(values)) == len(values)
    assert re.fullmatch(r"[0-9a-f]{64}", env["LANGFUSE_ENCRYPTION_KEY"])
    assert env["LITELLM_MASTER_KEY"].startswith("sk-")
    assert env["LANGFUSE_PUBLIC_KEY"].startswith("pk-lf-")


def test_two_installs_never_share_a_secret(make_env: Any) -> None:
    a = make_env.read_env(make_env.render(EXAMPLE))
    b = make_env.read_env(make_env.render(EXAMPLE))
    assert all(a[name] != b[name] for name in make_env.SECRETS)


def test_database_url_carries_the_new_password(make_env: Any) -> None:
    env = make_env.read_env(make_env.render(EXAMPLE))
    assert env["DATABASE_URL"] == (
        f"postgresql+psycopg://postgres:{env['POSTGRES_PASSWORD']}@localhost:5433/ssa"
    )


def test_keep_carries_settings_but_never_old_secrets(make_env: Any) -> None:
    old = (
        "OLLAMA_MODEL=qwen3:1.7b\nLANGFUSE_PORT=3001\nLITELLM_MASTER_KEY=sk-ssa-dev-master-key\n"
        "DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5433/ssa\n"
    )
    env = make_env.read_env(make_env.render(EXAMPLE, make_env.read_env(old)))
    assert env["OLLAMA_MODEL"] == "qwen3:1.7b"
    assert env["LANGFUSE_PORT"] == "3001"
    assert env["LITELLM_MASTER_KEY"] != "sk-ssa-dev-master-key"
    assert "postgres:postgres@" not in env["DATABASE_URL"]


def test_writes_an_owner_only_file_and_never_overwrites(make_env: Any, tmp_path: Path) -> None:
    out = tmp_path / ".env"
    assert make_env.main(["--example", str(ROOT / ".env.example"), "--out", str(out)]) == 0
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    with pytest.raises(SystemExit):
        make_env.main(["--example", str(ROOT / ".env.example"), "--out", str(out)])


def test_example_has_no_secret_values(make_env: Any) -> None:
    env = make_env.read_env(EXAMPLE)
    assert set(make_env.SECRETS) <= set(env)
    assert all(env[name] == "" for name in make_env.SECRETS)


def test_compose_has_no_fixed_secrets_or_fallbacks(make_env: Any) -> None:
    for value in OLD_DEV_VALUES:
        assert value not in COMPOSE, value
    for name in make_env.SECRETS:
        assert f"${{{name}:-" not in COMPOSE, f"{name} has a fallback"
    used = set(re.findall(r"\$\{([A-Z_]+):\?", COMPOSE))
    assert used <= set(make_env.SECRETS), used - set(make_env.SECRETS)
