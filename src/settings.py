from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _value(v: str | SecretStr) -> str:
    return v.get_secret_value() if isinstance(v, SecretStr) else v


SECRET_FIELDS = (
    "litellm_master_key",
    "litellm_router_key",
    "litellm_catalog_key",
    "litellm_career_key",
    "langfuse_public_key",
    "langfuse_secret_key",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = Field(default="dev", pattern="^(dev|test|ci|prod)$")
    # Dev-only: print each orchestrator step to the API terminal (api/debug.py)
    debug: bool = False

    # Conversations with no activity for this long are deleted (no accounts, no export yet)
    conversation_ttl_hours: int = 24

    # Postgres + pgvector. The password comes from .env (random per install, infra/make_env.py);
    # nothing secret has a default here, so a missing .env fails loudly instead of using a
    # password published in the repo.
    database_url: str = "postgresql+psycopg://postgres@localhost:5433/ssa"

    # Embedding model for the course catalog (catalog_course.embedding is vector(768)),
    # served through the LiteLLM gateway
    embedding_model: str = "nomic-embed-text"

    # LiteLLM gateway: the only way the app talks to any AI model.
    litellm_base_url: str = "http://localhost:4000"
    litellm_master_key: SecretStr = SecretStr("")
    litellm_router_key: SecretStr = SecretStr("")
    litellm_catalog_key: SecretStr = SecretStr("")
    litellm_career_key: SecretStr = SecretStr("")
    llm_default_model: str = "local-llm"

    # Web search for current job openings (tools.career.web_search; https://tavily.com). The
    # one outside service the app calls that is not a model. Unset: the Career agent says web
    # search isn't set up.
    tavily_api_key: SecretStr | None = None

    # Router: small model for stage 2, and the confidence below which it asks to clarify
    ollama_model: str = "qwen3:14b"
    router_confidence_threshold: float = 0.6

    # Langfuse tracing
    langfuse_host: str = "http://localhost:3000"
    langfuse_public_key: str = ""
    langfuse_secret_key: SecretStr = SecretStr("")
    # Traces (message text included) older than this are deleted; 7 days leaves room for the
    # weekly review of flagged and blocked messages (api/trace_retention.py)
    langfuse_trace_retention_days: int = Field(default=7, ge=1)

    @model_validator(mode="after")
    def _no_debug_in_prod(self) -> "Settings":
        if self.debug and self.env == "prod":
            raise ValueError("DEBUG=true is not allowed with ENV=prod")
        return self

    @model_validator(mode="after")
    def _secrets_set_in_prod(self) -> "Settings":
        if self.env != "prod":
            return self
        missing = [name.upper() for name in SECRET_FIELDS if not _value(getattr(self, name))]
        if not urlsplit(self.database_url).password:
            missing.append("DATABASE_URL (no password)")
        if missing:
            raise ValueError(f"ENV=prod needs these set in .env: {', '.join(missing)}")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
