# ---- base: shared OS setup ----
FROM python:3.12-slim AS base
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
RUN pip install uv

# ---- dev: all deps installed to /opt/venv so source mount doesn't conflict ----
FROM base AS dev
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
COPY pyproject.toml uv.lock ./
RUN uv sync --group dev
# Source is mounted at runtime via docker-compose.dev.yml volume
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ---- prod: prod deps only, source baked in ----
FROM base AS prod
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev
COPY app ./app
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1
CMD ["uv", "run", "gunicorn", "app.main:app", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--access-logfile", "-"]
