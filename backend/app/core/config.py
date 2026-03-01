from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import structlog
from pydantic import BaseModel, SecretStr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

logger = structlog.get_logger()


class _EnvReader(BaseSettings):
    """Reads raw config values from all sources. All fields optional at this layer."""

    model_config = SettingsConfigDict(
        env_prefix="TSR_",
        toml_file="config.toml",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str | None = None
    log_level: str | None = None
    mongodb_uri: SecretStr | None = None
    encryption_key: SecretStr | None = None
    llm_provider: str | None = None
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
        # Priority: env vars > config.toml > .env file
        return (env_settings, TomlConfigSettingsSource(settings_cls), dotenv_settings)


class Settings(BaseModel):
    """Application settings. Required fields are validated at load time."""

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
    def load(cls) -> Settings:
        """Load and validate settings from environment, config file, and .env."""
        raw = _EnvReader()
        return cls.model_validate(
            {
                "app_env": raw.app_env,
                "log_level": raw.log_level,
                "mongodb_uri": raw.mongodb_uri,
                "encryption_key": raw.encryption_key,
                "llm_provider": raw.llm_provider,
                "llm_model": raw.llm_model,
                "llm_ollama_base_url": raw.llm_ollama_base_url,
                "llm_openai_api_key": raw.llm_openai_api_key,
                "llm_anthropic_api_key": raw.llm_anthropic_api_key,
            }
        )


@lru_cache
def get_settings() -> Settings:
    return Settings.load()


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
