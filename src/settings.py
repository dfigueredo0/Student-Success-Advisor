from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = Field(default="dev", pattern="^(dev|test|ci|prod)$")

    # Postgres + pgvector
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/ssa"

    # Langfuse tracing
    langfuse_host: str = "http://localhost:3000"
    langfuse_public_key: str = "pk-lf-ssa-dev"
    langfuse_secret_key: SecretStr = SecretStr("sk-lf-ssa-dev")

@lru_cache
def get_settings() -> Settings:
    return Settings()
