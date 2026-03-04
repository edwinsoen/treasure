from app.audit.sanitize import REDACTED, sanitize_dict


class TestSanitizeDict:
    def test_returns_none_for_none(self) -> None:
        assert sanitize_dict(None) is None

    def test_returns_empty_for_empty(self) -> None:
        assert sanitize_dict({}) == {}

    def test_preserves_non_sensitive_keys(self) -> None:
        data = {"email": "a@b.com", "name": "Alice", "amount": 100}
        result = sanitize_dict(data)
        assert result == data

    def test_redacts_password(self) -> None:
        result = sanitize_dict({"password": "hunter2", "email": "a@b.com"})
        assert result is not None
        assert result["password"] == REDACTED
        assert result["email"] == "a@b.com"

    def test_redacts_hashed_password(self) -> None:
        result = sanitize_dict({"hashed_password": "$argon2..."})
        assert result is not None
        assert result["hashed_password"] == REDACTED

    def test_redacts_api_key(self) -> None:
        result = sanitize_dict({"api_key": "tsr_abc123"})
        assert result is not None
        assert result["api_key"] == REDACTED

    def test_redacts_api_key_with_hyphen(self) -> None:
        result = sanitize_dict({"api-key": "tsr_abc123"})
        assert result is not None
        assert result["api-key"] == REDACTED

    def test_redacts_token(self) -> None:
        result = sanitize_dict({"access_token": "eyJhb..."})
        assert result is not None
        assert result["access_token"] == REDACTED

    def test_redacts_secret(self) -> None:
        result = sanitize_dict({"auth_secret": "super-secret"})
        assert result is not None
        assert result["auth_secret"] == REDACTED

    def test_redacts_case_insensitive(self) -> None:
        result = sanitize_dict({"PASSWORD": "x", "ApiKey": "y", "Secret": "z"})
        assert result is not None
        assert result["PASSWORD"] == REDACTED
        assert result["ApiKey"] == REDACTED
        assert result["Secret"] == REDACTED

    def test_redacts_nested_dicts(self) -> None:
        data: dict[str, object] = {
            "user": {"email": "a@b.com", "hashed_password": "$argon2..."},
        }
        result = sanitize_dict(data)
        assert result is not None
        inner = result["user"]
        assert isinstance(inner, dict)
        assert inner["email"] == "a@b.com"
        assert inner["hashed_password"] == REDACTED

    def test_redacts_inside_lists(self) -> None:
        data: dict[str, object] = {
            "items": [{"password": "x"}, {"name": "ok"}],
        }
        result = sanitize_dict(data)
        assert result is not None
        items = result["items"]
        assert isinstance(items, list)
        assert items[0]["password"] == REDACTED
        assert items[1]["name"] == "ok"

    def test_does_not_mutate_original(self) -> None:
        original: dict[str, object] = {"password": "hunter2", "email": "a@b.com"}
        sanitize_dict(original)
        assert original["password"] == "hunter2"

    def test_encryption_key_redacted(self) -> None:
        result = sanitize_dict({"encryption_key": "abc", "encryption-key": "def"})
        assert result is not None
        assert result["encryption_key"] == REDACTED
        assert result["encryption-key"] == REDACTED

    def test_hash_field_redacted(self) -> None:
        result = sanitize_dict({"api_key_hash": "sha256hex"})
        assert result is not None
        assert result["api_key_hash"] == REDACTED
