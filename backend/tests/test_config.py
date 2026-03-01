import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings, resolve_encryption_key

# Minimal valid kwargs for direct Settings construction in unit tests.
BASE = {
    "app_env": "test",
    "log_level": "INFO",
    "mongodb_uri": "mongodb://localhost:27017/treasure",
}


class TestSettings:
    def test_direct_construction(self):
        settings = Settings(**BASE)
        assert settings.app_env == "test"
        assert settings.log_level == "INFO"
        assert settings.mongodb_uri.get_secret_value() == "mongodb://localhost:27017/treasure"

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            Settings(**{k: v for k, v in BASE.items() if k != "mongodb_uri"})

    def test_invalid_app_env_raises(self):
        with pytest.raises(ValidationError):
            Settings(**{**BASE, "app_env": "invalid"})

    def test_llm_fields_optional(self):
        settings = Settings(**BASE)
        assert settings.llm_provider is None
        assert settings.llm_model is None
        assert settings.encryption_key is None


class TestSettingsLoad:
    def test_loads_from_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("TSR_APP_ENV", "production")
        monkeypatch.setenv("TSR_LOG_LEVEL", "WARNING")
        monkeypatch.setenv("TSR_MONGODB_URI", "mongodb://localhost:27017/treasure")
        settings = Settings.load()
        assert settings.app_env == "production"
        assert settings.log_level == "WARNING"

    def test_missing_required_env_raises(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("TSR_APP_ENV", raising=False)
        monkeypatch.delenv("TSR_LOG_LEVEL", raising=False)
        monkeypatch.delenv("TSR_MONGODB_URI", raising=False)
        with pytest.raises(ValidationError):
            Settings.load()

    def test_mongodb_uri_with_credentials(self, monkeypatch: pytest.MonkeyPatch):
        uri = "mongodb://user:pass@host:27017/mydb"
        monkeypatch.setenv("TSR_APP_ENV", "test")
        monkeypatch.setenv("TSR_LOG_LEVEL", "INFO")
        monkeypatch.setenv("TSR_MONGODB_URI", uri)
        settings = Settings.load()
        assert settings.mongodb_uri.get_secret_value() == uri


class TestGetSettings:
    def test_returns_cached_instance(self, monkeypatch: pytest.MonkeyPatch):
        for k, v in BASE.items():
            monkeypatch.setenv(f"TSR_{k.upper()}", v)
        get_settings.cache_clear()
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2
        get_settings.cache_clear()

    def test_cache_clear_reloads(self, monkeypatch: pytest.MonkeyPatch):
        for k, v in BASE.items():
            monkeypatch.setenv(f"TSR_{k.upper()}", v)
        monkeypatch.setenv("TSR_APP_ENV", "development")
        get_settings.cache_clear()
        s1 = get_settings()

        monkeypatch.setenv("TSR_APP_ENV", "test")
        get_settings.cache_clear()
        s2 = get_settings()

        assert s1.app_env == "development"
        assert s2.app_env == "test"
        get_settings.cache_clear()


class TestResolveEncryptionKey:
    def test_uses_settings_key(self):
        key = os.urandom(32).hex()
        settings = Settings(**{**BASE, "encryption_key": key})
        assert resolve_encryption_key(settings) == key

    def test_generates_and_persists_new_key(self, tmp_path: Path):
        settings = Settings(**BASE)
        key = resolve_encryption_key(settings, secrets_dir=tmp_path)
        assert len(key) > 0
        assert (tmp_path / "encryption.key").exists()

    def test_second_call_loads_from_file(self, tmp_path: Path):
        settings = Settings(**BASE)
        key1 = resolve_encryption_key(settings, secrets_dir=tmp_path)
        key2 = resolve_encryption_key(settings, secrets_dir=tmp_path)
        assert key1 == key2

    def test_loads_existing_key_from_file(self, tmp_path: Path):
        key = os.urandom(32).hex()
        (tmp_path / "encryption.key").write_text(key)
        settings = Settings(**BASE)
        assert resolve_encryption_key(settings, secrets_dir=tmp_path) == key

    def test_generated_key_is_256_bits(self, tmp_path: Path):
        settings = Settings(**BASE)
        key = resolve_encryption_key(settings, secrets_dir=tmp_path)
        assert len(bytes.fromhex(key)) == 32
