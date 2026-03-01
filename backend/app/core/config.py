from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import structlog
from pydantic import SecretStr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

logger = structlog.get_logger()


class Settings(BaseSettings):
    """Application settings. Missing required fields raise ValidationError at startup."""

    model_config = SettingsConfigDict(
        env_prefix="TSR_",
        toml_file="config.toml",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App — required
    app_env: Literal["development", "production", "test"]
    log_level: str

    # Database — required, env only (may contain credentials)
    mongodb_uri: SecretStr

    # Encryption — optional (auto-generated on first run if absent)
    encryption_key: SecretStr | None = None

    # LLM — optional (Phase 2); per-provider validation lives in the LLM module
    llm_provider: Literal["openai", "anthropic", "ollama"] | None = None
    llm_model: str | None = None
    llm_ollama_base_url: str | None = None
    llm_openai_api_key: SecretStr | None = None
    llm_anthropic_api_key: SecretStr | None = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Priority: env vars > config.toml > .env file > init kwargs
        return (
            env_settings,
            TomlConfigSettingsSource(settings_cls),
            dotenv_settings,
            init_settings,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


def resolve_encryption_key(settings: Settings, secrets_dir: Path = Path("secrets")) -> str:
    """Return the AES-256-GCM key (64-char hex). Generates and persists to disk if absent."""
    if settings.encryption_key is not None:
        return settings.encryption_key.get_secret_value()

    key_file = secrets_dir / "encryption.key"
    if key_file.exists():
        return key_file.read_text().strip()

    key = os.urandom(32).hex()
    secrets_dir.mkdir(parents=True, exist_ok=True)
    key_file.write_text(key)
    key_file.chmod(0o600)
    logger.warning("Generated new encryption key — back it up!", path=str(key_file))
    return key
