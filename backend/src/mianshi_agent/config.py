"""Application configuration loaded from local environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Keep model and storage choices configurable without exposing credentials."""

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_data_dir: Path = Path("../data/runtime")
    app_database_path: Path = Path("../data/runtime/mianshiagent.sqlite3")
    app_cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    app_max_upload_bytes: int = Field(default=15 * 1024 * 1024, ge=1024)

    llm_provider: str = "custom"
    llm_base_url: str = ""
    llm_api_key: str = Field(default="", repr=False)
    llm_model_id: str = "deepseek-v4-flash"
    llm_timeout: float = Field(default=90.0, gt=0, le=600)

    memory_embedding_model: str = "qwen3-embedding:0.6b"
    memory_embedding_dimensions: int = Field(default=1024, ge=32, le=8192)
    memory_embedding_base_url: str = "http://127.0.0.1:11434"
    memory_embedding_api_key: str = Field(default="", repr=False)
    embedding_timeout: float = Field(default=120.0, gt=0, le=600)

    retrieval_vector_limit: int = Field(default=12, ge=1, le=100)
    retrieval_lexical_limit: int = Field(default=12, ge=1, le=100)
    retrieval_rrf_k: int = Field(default=60, ge=1, le=1000)
    retrieval_max_graph_hops: int = Field(default=2, ge=0, le=4)
    retrieval_max_graph_nodes: int = Field(default=30, ge=1, le=200)

    @field_validator("app_data_dir", "app_database_path", mode="after")
    @classmethod
    def resolve_backend_relative_path(cls, value: Path) -> Path:
        """Resolve relative paths against the backend directory, not process cwd."""
        return value if value.is_absolute() else (BACKEND_DIR / value).resolve()

    @property
    def cors_origins(self) -> list[str]:
        """Return normalized configured frontend origins."""
        return [item.strip() for item in self.app_cors_origins.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return one immutable-by-convention settings object per process."""
    return Settings()
