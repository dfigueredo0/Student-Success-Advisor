from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = Field(default="dev", pattern="^(dev|test|ci|prod)$")
    # Dev-only: print each orchestrator step to the API terminal (api/debug.py)
    debug: bool = False

    # Postgres + pgvector
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5433/ssa"

    # Ollama embeddings for the course catalog (catalog_course.embedding is vector(768))
    ollama_host: str = "http://localhost:11434"
    embedding_model: str = "nomic-embed-text"

    # LiteLLM gateway: the only way the app talks to any AI model.
    litellm_base_url: str = "http://localhost:4000"
    litellm_master_key: SecretStr = SecretStr("sk-ssa-dev-master-key")
    llm_default_model: str = "local-llm"

    # Router: small model for stage 2, and the confidence below which it asks to clarify
    ollama_model: str = "qwen3:1.7b"
    router_confidence_threshold: float = 0.6

    # Langfuse tracing
    langfuse_host: str = "http://localhost:3000"
    langfuse_public_key: str = "pk-lf-ssa-dev"
    langfuse_secret_key: SecretStr = SecretStr("sk-lf-ssa-dev")

    @model_validator(mode="after")
    def _no_debug_in_prod(self) -> "Settings":
        if self.debug and self.env == "prod":
            raise ValueError("DEBUG=true is not allowed with ENV=prod")
        return self

@lru_cache
def get_settings() -> Settings:
    return Settings()
