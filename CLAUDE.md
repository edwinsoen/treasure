# CLAUDE.md -- Finance Tracker Project Guide

## What This Project Is

A self-hosted, open-source personal finance tracker. Ingests transaction data from Gmail (bank alerts and receipts), manual entries, and monthly bank statements. The core model is money-movement-first with optional itemization. Reconciliation is a first-class workflow. No bank API connections.

Tracking scope: expenses, income, investments, and giving.

## Reference Documents

- `docs/requirements.md` -- High-level product requirements
- `docs/epics-and-stories.md` -- Epics, user stories with acceptance criteria, technical notes, and dependency maps

Read the relevant story in `docs/epics-and-stories.md` before implementing anything. Each story has acceptance criteria, technical notes, and dependencies.

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12+, FastAPI, async throughout |
| Database | MongoDB 7.x via Motor (async driver) |
| Frontend | React 18+, TypeScript, Vite, Tailwind CSS |
| PDF Parsing | Docling (Phase 2) |
| LLM | Provider-agnostic: OpenAI, Anthropic, or Ollama (Phase 2) |
| Deployment | Docker Compose, single-host |

## Architectural Principles

### Multi-Tenant by Default

Every document has `owner_id` (who owns it) and `created_by` (who created it). For v1, both resolve to a hardcoded default user. When multi-user auth is added later, only the auth middleware changes.

- All queries filter by `owner_id`
- All compound indexes lead with `owner_id`
- Uniqueness constraints are scoped to `owner_id`
- The repository base class enforces this; individual repositories cannot bypass it

### Bank Statements Are Canonical

Alert-derived transactions are provisional. Statement values override alert values. Discrepancies are flagged for user acknowledgement, never silently resolved.

Transaction status flow: `unconfirmed` -> `confirmed` -> `reconciled`. No skipping, no backward without explicit unlock.

### Deterministic First, LLM as Fallback

Use deterministic methods where patterns are stable. LLM only where deterministic methods are insufficient. All LLM calls are logged, non-blocking, and user-overridable.

### Audit Everything

Every create, update, and delete on core entities produces an audit log entry. Append-only.

### Gmail Event Store

Raw Gmail events are stored before processing and can be replayed to rebuild all gmail-derived data. The event store survives DB wipes.

## Coding Conventions

### Python / Backend

- Async everywhere: route handlers, repositories, services
- Pydantic v2 for all schemas: domain models, API request/response, config
- Repository pattern: data access through repository classes, never raw queries in routers
- Dependency injection via FastAPI `Depends()`
- Type hints on all function signatures
- Domain exceptions in services/repositories; `HTTPException` only in routers
- `structlog` for logging, no print statements
- `pytest` with `pytest-asyncio` for tests

### TypeScript / Frontend

- Functional components only, TypeScript strict mode
- API client generated from OpenAPI spec
- Tailwind for styling, no CSS modules
- TanStack Query for server state
- No default exports except pages/routes

### Naming

| Item | Convention | Example |
|------|-----------|---------|
| Python files | snake_case | `transaction_link.py` |
| Python classes | PascalCase | `TransactionRepository` |
| API routes | kebab-case | `/api/transaction-links` |
| MongoDB collections | snake_case plural | `transactions` |
| TypeScript components | PascalCase | `TransactionList.tsx` |
| Env vars | SCREAMING_SNAKE_CASE | `MONGODB_URI` |
| Pydantic models | PascalCase, suffixed | `TransactionCreate`, `TransactionResponse` |

### API Conventions

- All endpoints prefixed with `/api/`
- Cursor-based pagination, not offset
- Filters as query parameters
- Soft deletes only
- All timestamps UTC ISO 8601

## Key Domain Rules

- `category_attributions` amounts must sum to the transaction amount
- Transfers (linked or one-sided) are excluded from income/expense reports by default
- `expects_alerts` on accounts determines whether the receipt parser waits for a bank alert or creates a transaction immediately
- Reimbursement status is derived from linked transactions, never stored
- `email_events` collection and `/data/email-events/` directory are never wiped

## Build Commands

### Backend
```bash
cd backend
uv sync --group dev          # install deps
uv run uvicorn app.main:app --reload  # dev server (port 8000)
uv run pytest -v             # tests
uv run ruff check .          # lint
uv run black .               # format
```

### Frontend
```bash
cd frontend
npm install                  # install deps
npm run dev                  # dev server (port 5173, proxies /api → 8000)
npm run build                # production build
npm run lint                 # eslint
npm run format               # prettier (write)
npm run format:check         # prettier (check only)
```

## Implementation Order

Follow the story order in `docs/epics-and-stories.md`. Each story lists its dependencies. Do not start a story until its dependencies are complete.
