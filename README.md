# Treasure — Personal Finance Tracker

A self-hosted, open-source personal finance tracker. Ingests transaction data from Gmail (bank alerts and receipts), manual entries, and monthly bank statements. No bank API connections required.

## Repository Structure

```
treasure/
├── backend/        # Python 3.12 / FastAPI
├── frontend/       # React 18 / TypeScript / Vite / Tailwind
├── docker/         # Docker Compose stack (Story 1.2)
└── docs/           # Requirements, epics, and stories
```

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.12+ | [python.org](https://www.python.org) or `pyenv` |
| uv | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Node.js | 20+ | [nodejs.org](https://nodejs.org) or `nvm` |
| npm | 10+ | Bundled with Node.js |

## Local Development Setup

### 1. Clone the repository

```bash
git clone <repo-url>
cd treasure
```

### 2. Backend

```bash
cd backend

# Install dependencies (creates .venv automatically)
uv sync --group dev

# Start the dev server (hot-reload enabled)
uv run uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`.
Interactive docs: `http://localhost:8000/docs`

**Run tests:**
```bash
uv run pytest -v
```

**Lint and format:**
```bash
uv run ruff check .          # linting
uv run black .               # formatting
```

### 3. Frontend

```bash
cd frontend

# Install dependencies
npm install

# Start the dev server (proxies /api to localhost:8000)
npm run dev
```

The frontend will be available at `http://localhost:5173`.

**Build for production:**
```bash
npm run build
```

**Lint and format:**
```bash
npm run lint             # eslint
npm run format           # prettier (write)
npm run format:check     # prettier (check only)
```

### 4. Pre-commit Hooks

Install [pre-commit](https://pre-commit.com) and set up the hooks:

```bash
pip install pre-commit
pre-commit install
```

Hooks run automatically on `git commit`. To run manually against all files:

```bash
pre-commit run --all-files
```

Hooks configured:
- **ruff** — Python linting (backend)
- **black** — Python formatting (backend)
- **prettier** — TypeScript/CSS/JSON formatting (frontend)
- **eslint** — TypeScript linting (frontend)

## Running Both Services Together

Open two terminals:

```bash
# Terminal 1 — backend
cd backend && uv run uvicorn app.main:app --reload

# Terminal 2 — frontend
cd frontend && npm run dev
```

The Vite dev server proxies all `/api/*` requests to `http://localhost:8000`, so the frontend and backend work together seamlessly.

## CI

GitHub Actions runs on every push:
- **Backend job**: ruff lint → black format check → pytest
- **Frontend job**: eslint → prettier check → tsc type-check → vite build

See [.github/workflows/ci.yml](.github/workflows/ci.yml) for details.
