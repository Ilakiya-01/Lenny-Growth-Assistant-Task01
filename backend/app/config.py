"""Environment-backed application configuration."""

from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


def normalize_database_url(url: str) -> str:
    """Return a SQLAlchemy-compatible PostgreSQL URL.

    Supabase and Railway hand out plain ``postgresql://`` connection strings and
    may append a ``pgbouncer=true`` parameter that psycopg2 does not understand.
    """
    if not url:
        return url

    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://") :]

    parts = urlsplit(url)
    query = [(key, value) for key, value in parse_qsl(parts.query) if key.lower() != "pgbouncer"]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


class Settings(BaseSettings):
    """Values loaded from environment variables or the root ``.env`` file."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Lenny Growth Assistant API"
    app_env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000"
    database_url: str = ""

    # Phase 2 - knowledge base and ingestion.
    transcripts_path: str = "../lennys-podcast-transcripts"
    embedding_provider: str = "sentence-transformers"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_batch_size: int = 64
    chunk_size: int = 400
    chunk_overlap: int = 60
    openai_api_key: str = ""

    # Phase 3 - application agent and LLM providers.
    llm_mode: str = "ollama"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"
    anthropic_max_tokens: int = 2048
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = ""
    # Context window for the local runtime. 0 keeps Ollama's own default (4096
    # tokens for the installed qwen3 build), which is far below what the model
    # itself supports; raising it trades RAM for a larger KV cache, so it is an
    # explicit opt-in.
    ollama_num_ctx: int = 0
    llm_timeout_seconds: float = 120.0
    # Opt-in: let the configured provider classify the request intent instead of
    # the deterministic heuristic classifier. Off by default so routing works
    # offline and without paid API calls.
    llm_router_llm_classification: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def dev_agent_endpoints_enabled(self) -> bool:
        """The Phase 3 verification endpoints are never exposed in production."""
        return self.app_env.strip().lower() != "production"

    @property
    def sqlalchemy_database_url(self) -> str:
        return normalize_database_url(self.database_url)

    @property
    def transcripts_root(self) -> Path:
        """Absolute path of the local transcript repository.

        Relative values in ``.env`` are resolved against the repository root so
        the ingestion commands can be run from any working directory.
        """
        path = Path(self.transcripts_path).expanduser()
        return path if path.is_absolute() else (REPO_ROOT / path).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
