# Configuration Reference

All backend configuration is managed via `backend/app/core/config.py` using [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/).

## Layer precedence (highest → lowest)

1. **Environment variables** — always win; use for secrets and deployment overrides
2. **`backend/config.toml`** — local config file; gitignored
3. **`.env` file** — loaded by pydantic-settings for local development
4. **Defaults** — defined in the `Settings` class

## Environment variable naming

All variables are prefixed with `TSR_` and uppercased:

| Setting field | Environment variable |
|---------------|----------------------|
| `app_env` | `TSR_APP_ENV` |
| `log_level` | `TSR_LOG_LEVEL` |
| `mongodb_uri` | `TSR_MONGODB_URI` |
| `encryption_key` | `TSR_ENCRYPTION_KEY` |
| `llm_provider` | `TSR_LLM_PROVIDER` |
| `llm_model` | `TSR_LLM_MODEL` |
| `llm_ollama_base_url` | `TSR_LLM_OLLAMA_BASE_URL` |
| `llm_openai_api_key` | `TSR_LLM_OPENAI_API_KEY` |
| `llm_anthropic_api_key` | `TSR_LLM_ANTHROPIC_API_KEY` |

## config.toml

Copy `backend/config.example.toml` to `backend/config.toml` to customise non-secret settings locally. The file is optional — if absent, defaults apply.

```toml
app_env = "development"
log_level = "INFO"

llm_provider = "anthropic"
llm_model = "claude-sonnet-4-6"
llm_ollama_base_url = "http://localhost:11434"
```

**Do not put secrets in config.toml.** Connection strings, API keys, and encryption keys must be set via environment variables only.

## Settings reference

### App

| Field | Default | Description |
|-------|---------|-------------|
| `app_env` | `development` | Runtime environment: `development`, `production`, or `test` |
| `log_level` | `INFO` | Log verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR` |

### Database

| Field | Default | Env only | Description |
|-------|---------|----------|-------------|
| `mongodb_uri` | `mongodb://localhost:27017/treasure` | Yes | Full MongoDB connection string |

The URI may contain credentials (`mongodb://user:pass@host:27017/db`), so it must always be supplied via `TSR_MONGODB_URI` in any environment with authentication.

### Encryption

| Field | Default | Env only | Description |
|-------|---------|----------|-------------|
| `encryption_key` | _(auto-generated)_ | Yes | Fernet key for encrypting sensitive fields at rest |

If `TSR_ENCRYPTION_KEY` is not set, a key is generated on first startup and written to `backend/secrets/encryption.key` (mode `0600`). **Back up this file** — losing it makes encrypted data unrecoverable. In production, inject the key via `TSR_ENCRYPTION_KEY` rather than relying on the file.

### LLM

| Field | Default | Env only | Description |
|-------|---------|----------|-------------|
| `llm_provider` | `anthropic` | No | Active LLM provider: `openai`, `anthropic`, or `ollama` |
| `llm_model` | `claude-sonnet-4-6` | No | Model identifier passed to the provider |
| `llm_ollama_base_url` | `http://localhost:11434` | No | Base URL for the Ollama server (ollama provider only) |
| `llm_openai_api_key` | — | Yes | Required when `llm_provider = openai` |
| `llm_anthropic_api_key` | — | Yes | Required when `llm_provider = anthropic` |

The app refuses to start if the API key for the selected provider is missing. Use `llm_provider = ollama` for local development without an API key.

## Startup validation

At startup the app loads and validates all settings. If validation fails (e.g. missing required API key), a clear error is logged and the process exits. Example:

```
error    Invalid configuration — app will not start
         error="1 validation error for Settings\nvalidate_llm_provider\n  Value error,
                TSR_LLM_ANTHROPIC_API_KEY must be set when llm_provider is 'anthropic'"
```
