"""Typed configuration for Martin.

Everything in Martin depends on this module. Settings are loaded from environment
variables (and a local ``.env`` file), validated, and exposed as a typed object.
Nothing else in the codebase reads ``os.environ`` directly.

Usage:
    from martin.core.config import get_settings
    settings = get_settings()
    settings.default_model       # -> "ollama/qwen3:14b"
    settings.pillars             # -> ["business", "personal", "automation"]
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All of Martin's runtime configuration, validated and typed.

    Field names map to environment variables case-insensitively, so the field
    ``default_model`` is populated from ``DEFAULT_MODEL`` in the environment or
    ``.env``. See ``.env.example`` for the documented template.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Models (LiteLLM model strings) ──────────────────────────────────────
    default_model: str = Field(
        default="ollama/qwen3:14b",
        description="Main reasoning/conversation model.",
    )
    fast_model: str = Field(
        default="ollama/mistral:7b",
        description="Cheap model for intent routing and memory classification.",
    )
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Base URL of the local Ollama server.",
    )

    # ── Memory (ChromaDB, embedded) ─────────────────────────────────────────
    chroma_dir: Path = Field(
        default=Path("./data/chroma"),
        description="Folder where ChromaDB persists memories.",
    )

    # ── Web search ──────────────────────────────────────────────────────────
    brave_api_key: str | None = Field(
        default=None,
        description="Brave Search API key. Blank/None -> DuckDuckGo only.",
    )

    # ── Pillars ─────────────────────────────────────────────────────────────
    # Stored as a raw comma-separated string (env-friendly); exposed parsed via
    # the ``pillars`` computed property.
    pillars_raw: str = Field(
        default="business,personal,automation",
        validation_alias="PILLARS",
        description="Comma-separated organizational tags for memory.",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def pillars(self) -> list[str]:
        """The configured pillars as a clean list, in order, no blanks."""
        return [p.strip() for p in self.pillars_raw.split(",") if p.strip()]

    @property
    def has_brave(self) -> bool:
        """True when a usable Brave Search API key is configured."""
        return bool(self.brave_api_key and self.brave_api_key.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton (loaded once, then cached).

    Tests that mutate the environment should call ``get_settings.cache_clear()``
    or construct ``Settings(...)`` directly to avoid the cache.
    """
    return Settings()
