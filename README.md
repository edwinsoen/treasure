# Treasure — Personal Finance Tracker

A self-hosted, open-source personal finance tracker. Ingests transaction data from Gmail (bank alerts and receipts), manual entries, and monthly bank statements. No bank API connections required.

## Repository Structure

```
treasure/
├── backend/        # Python 3.12 / FastAPI
├── frontend/       # React 18 / TypeScript / Vite / Tailwind
├── docker/         # Docker Compose stack
└── docs/           # Requirements, epics, and stories
```

## Quick Start (Docker)

The fastest way to run the full stack:

```bash
# 1. Copy the example env file (edit values if needed)
cp .env.example .env

# 2. Build and start everything
docker compose -f docker/docker-compose.yml up --build
```

The app will be available at **http://localhost:8080**.

To stop: `docker compose -f docker/docker-compose.yml down`

---

## Local Development Setup

### Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Docker | 24+ | [docker.com](https://www.docker.com) |
| Python | 3.12+ | [python.org](https://www.python.org) or `pyenv` |
| uv | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Node.js | 20+ | [nodejs.org](https://nodejs.org) or `nvm` |

### 1. Clone the repository

```bash
git clone <repo-url>
cd treasure
cp .env.example .env
```

### 2. Start dependencies in Docker (recommended)

Run MongoDB and the backend API in Docker with hot-reload, then run the
frontend locally with the Vite dev server:

```bash
# Terminal 1 — backend + MongoDB (hot-reload on :8000, MongoDB on :27017)
docker compose -f docker/docker-compose.yml -f docker/docker-compose.dev.yml up --build

# Terminal 2 — frontend dev server (HMR on :5173, proxies /api to :8000)
cd frontend && npm install && npm run dev
```

The app is then available at **http://localhost:5173** with full hot-reload for both backend and frontend.

### 3. Or run everything locally (no Docker)

```bash
# Terminal 1 — backend
cd backend
uv sync --group dev
uv run uvicorn app.main:app --reload
# API at http://localhost:8000 — interactive docs at http://localhost:8000/docs

# Terminal 2 — frontend
cd frontend
npm install
npm run dev
# UI at http://localhost:5173
```

You'll need a MongoDB instance running locally at `mongodb://localhost:27017`.

---

## Testing & Linting

```bash
# Backend
cd backend
uv run pytest -v             # tests
uv run ruff check .          # lint
uv run black .               # format

# Frontend
cd frontend
npm run lint                 # eslint
npm run format:check         # prettier check
```

## Pre-commit Hooks

```bash
pip install pre-commit
pre-commit install
```

Hooks run automatically on `git commit` (ruff + black for Python, eslint + prettier for TypeScript).

---

## CI

GitHub Actions runs on every push:
- **Backend**: ruff → black → pytest
- **Frontend**: eslint → prettier → tsc → vite build

See [.github/workflows/ci.yml](.github/workflows/ci.yml) for details.
