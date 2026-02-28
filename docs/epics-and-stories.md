# Personal Finance Tracker -- Epics and User Stories

## Phasing Strategy

The project is divided into three delivery phases. Each phase produces a usable increment. Epics are grouped by domain within each phase.

| Phase | Goal | Epics |
|-------|------|-------|
| **Phase 1: Foundation** | Core data model, API scaffold, accounts, manual transactions, categories. A working app that can record and categorize transactions by hand. | E1 Project Bootstrap, E2 Core Data Model & API, E3 Manual Entry, E4 Category Management |
| **Phase 2: Ingestion & Reconciliation** | Parsing infrastructure, Gmail pipeline, bank statement import, auto-matching, reconciliation workflow. Transactions flow in automatically and are reconciled against statements. | E5 Parsing Infrastructure, E6 Gmail Integration, E7 Bank Statement Import, E8 Reconciliation Engine, E9 Receipt Management |
| **Phase 3: Intelligence & Reporting** | Budgets, dashboards, reports, AI-assisted categorization, reimbursement tracking. The app becomes a decision-support tool. | E10 Budgets, E11 Reporting & Dashboard, E12 Smart Categorization, E13 Reimbursement Tracking |

Dependencies flow top-to-bottom: Phase 2 requires Phase 1 entities; Phase 3 requires Phase 2 ingestion pipelines. Within each phase, the epic order reflects internal dependencies.

---

## Phase 1: Foundation

---

### Epic 1: Project Bootstrap

Sets up the repository, toolchain, deployment stack, and cross-cutting infrastructure that every subsequent epic depends on.

#### Story 1.1: Repository and Toolchain Setup

**Description:** Initialize the monorepo with backend (Python/FastAPI), frontend (React/TypeScript), shared configuration, and CI scaffolding. Establish linting, formatting, and test conventions.

**Acceptance Criteria:**
- Monorepo structure with `/backend`, `/frontend`, `/docker`, `/docs` directories
- Backend: Python 3.12+, FastAPI, Poetry/uv for dependency management
- Frontend: React 18+, TypeScript, Vite, Tailwind CSS
- Pre-commit hooks for linting (ruff, eslint) and formatting (black, prettier)
- CI pipeline runs lint + unit tests on push (GitHub Actions)
- README with local development setup instructions

**Technical Notes:**
- FastAPI chosen for async support, automatic OpenAPI docs, and Pydantic model integration
- Consider uv over Poetry for faster dependency resolution
- Frontend build outputs static files served by the backend in production

**Dependencies:** None (first story)

---

#### Story 1.2: Docker Compose Deployment Stack

**Description:** Create a Docker Compose configuration that runs the full application stack (backend, frontend, MongoDB, reverse proxy) from a single command.

**Acceptance Criteria:**
- `docker compose up` starts all services and the app is reachable at `http://localhost`
- MongoDB container with a named volume for data persistence
- Backend container with hot-reload for development mode
- Frontend container (or served by backend in production mode)
- `.env.example` with all required environment variables documented
- Health check endpoints for backend and MongoDB

**Technical Notes:**
- Use multi-stage Dockerfile for backend: dev stage with reload, prod stage with gunicorn/uvicorn
- MongoDB 7.x; no authentication required for single-user self-hosted (document the trade-off)
- Nginx or Caddy as reverse proxy for production; direct port exposure for dev

**Dependencies:** Story 1.1

---

#### Story 1.3: Configuration and Secrets Management

**Description:** Implement a layered configuration system that reads from environment variables, a config file, and sensible defaults. Secrets (OAuth tokens, encryption keys) are handled separately from plain config.

**Acceptance Criteria:**
- Pydantic Settings model for all config values with validation and defaults
- Config file support (YAML or TOML) with env var overrides taking precedence
- Secrets loaded from environment variables only (never from config file)
- LLM provider selection via config: `openai`, `anthropic`, or `ollama` with provider-specific keys
- Config validation at startup; app refuses to start with invalid config and logs a clear error
- Documented config reference in `/docs/configuration.md`

**Technical Notes:**
- Use `pydantic-settings` with `SettingsConfigDict` for env + file loading
- For encryption at rest, generate a Fernet key on first run if not provided; store in a dedicated secrets path
- Gmail OAuth tokens stored encrypted, never in plaintext (see Story 1.4)

**Dependencies:** Story 1.1

---

#### Story 1.4: Authentication and Security Baseline

**Description:** Implement basic application security: encryption at rest for the database, secure storage for OAuth tokens, and a simple auth gate for the web UI. Design the auth layer so that upgrading from single-user to multi-user requires changes only in the auth module, not in the data layer or API logic.

**Acceptance Criteria:**
- MongoDB field-level encryption for sensitive fields (amounts, account numbers) using the configured encryption key
- OAuth token storage encrypted at rest via Fernet symmetric encryption
- Simple session-based auth for the web UI: password set on first run, hashed with bcrypt
- All API endpoints gated behind auth middleware (session cookie or API key)
- Auth middleware resolves the current user and injects `owner_id` and `created_by` into the request context; for v1, both resolve to a hardcoded default user created on first startup
- A `User` document exists in MongoDB with at minimum: `_id`, `email`, `display_name`, `created_at`; the default user is seeded on first run
- CORS restricted to configured origins
- Security headers set (CSP, X-Frame-Options, etc.)

**Technical Notes:**
- For v1 single-user, a lightweight session approach is sufficient; no need for full OAuth/OIDC for the app itself
- The `owner_id` injection pattern is the key multi-tenant enabler: every downstream service receives a user context, and when real auth is added later, only the middleware that resolves the user changes
- MongoDB client-side field-level encryption (CSFLE) is ideal but complex; acceptable alternative is application-level encryption of sensitive fields before write
- API key support allows headless/scripted access

**Dependencies:** Story 1.3

---

#### Story 1.5: Audit Log Infrastructure

**Description:** Implement a cross-cutting audit log that records every data mutation with timestamp, source (user/system/auto), entity type, entity ID, action, and before/after snapshot.

**Acceptance Criteria:**
- Audit log entries stored in a dedicated MongoDB collection
- Every create, update, and delete on core entities (Transaction, Receipt, Account, Category, Budget) generates an audit entry
- Entry includes: `timestamp`, `owner_id`, `actor` (user ID of who performed the action, or system process identifier), `action` (create/update/delete), `entity_type`, `entity_id`, `changes` (diff of modified fields), `source` (manual/gmail/statement/auto-match)
- Audit log is append-only; entries are never modified or deleted
- API endpoint to query audit log with filters: entity type, entity ID, date range, actor
- Audit log middleware/decorator pattern so new entities get logging automatically

**Technical Notes:**
- Implement as a FastAPI middleware or a repository-layer decorator that intercepts writes
- Store `changes` as a JSON diff (old value, new value per field) to keep entries compact
- Consider TTL index on MongoDB if log size becomes a concern (configurable retention)
- This is a foundational dependency for reconciliation (Story 7.x) which requires full traceability

**Dependencies:** Story 1.2, Story 1.3

---

### Epic 2: Core Data Model & API

Establishes the MongoDB schemas, repository layer, and REST API for all primary entities. This is the backbone that every feature builds on.

**Multi-tenant data pattern (applies to all entities in this epic and beyond):**
- Every document includes an `owner_id` field (the user who owns the entity and has full control) and a `created_by` field (the user who created it). For v1 both resolve to the default user; the distinction matters for future sharing (e.g., a household member creates a transaction on a shared account -- `owner_id` is the account holder, `created_by` is whoever entered it).
- Primary tenant scoping uses `owner_id`: all queries filter by it, all compound indexes lead with it (e.g., `(owner_id, account_id, date_alert)`), and uniqueness constraints are scoped to it (e.g., account name unique per owner, not globally)
- The repository base class enforces `owner_id` filtering so individual entity repositories cannot accidentally bypass it
- Future sharing model: an access-control layer (e.g., `shared_with` or a permissions collection) can grant other users read/write access to specific entities without changing the ownership model or existing queries
- For v1, `owner_id` and `created_by` always resolve to the single default user; this is invisible to the rest of the codebase

#### Story 2.1: Account Entity and API

**Description:** Implement the Account entity representing a financial account or wallet, with full CRUD API.

**Acceptance Criteria:**
- Account document schema: `name`, `type` (enum: checking, savings, credit_card, investment, cash, stored_value), `currency` (ISO 4217), `initial_balance` (optional, for manual accounts), `expects_alerts` (boolean, default true for checking/savings/credit_card, false for cash/stored_value; indicates whether this account receives bank alert emails), `is_active`, `created_at`, `updated_at`
- CRUD endpoints: `POST /api/accounts`, `GET /api/accounts`, `GET /api/accounts/{id}`, `PUT /api/accounts/{id}`, `DELETE /api/accounts/{id}` (soft delete only)
- Validation: unique account name per owner, valid currency code, type must be from the enum
- Derived balance field computed on read (sum of reconciled transactions + initial balance); not stored
- List endpoint supports filtering by type and is_active
- Soft delete sets `is_active=false`; account with reconciled transactions cannot be hard-deleted
- `stored_value` accounts (gift cards, store credit, prepaid balances) are lightweight: no statement reconciliation, no alert expectations. UX should make them easy to create (e.g., "Add gift card" shortcut) and show remaining balance prominently

**Technical Notes:**
- Use Motor (async MongoDB driver) with Pydantic models for schema validation
- Repository pattern: `AccountRepository` class with methods that return Pydantic models, not raw dicts
- Currency codes validated against a static ISO 4217 list (no external API call)
- Balance derivation via aggregation pipeline; cache in application layer if performance becomes an issue

**Dependencies:** Story 1.2, Story 1.5

---

#### Story 2.2: Category Entity and Hierarchy API

**Description:** Implement the hierarchical Category entity with fixed top-level types and user-defined subcategories.

**Acceptance Criteria:**
- Category document schema: `name`, `type` (enum: expense, income, investment, giving), `parent_id` (null for top-level), `status` (active, suggested), `is_system` (true for fixed top-level types), `sort_order`, `created_at`, `updated_at`
- Seed the four fixed top-level categories on first startup (expense, income, investment, giving); these cannot be deleted or renamed
- CRUD endpoints: `POST /api/categories`, `GET /api/categories` (returns tree), `GET /api/categories/{id}`, `PUT /api/categories/{id}`, `DELETE /api/categories/{id}`
- Subcategory creation requires a valid `parent_id` pointing to an existing category of the same `type`
- Tree endpoint returns nested structure: top-level types with children arrays
- Deletion: only if no transactions reference the category; otherwise return 409 with count of affected transactions
- Category `type` is inherited from the top-level ancestor and cannot differ

**Technical Notes:**
- Flat storage with `parent_id` is sufficient for a shallow hierarchy (2-3 levels max)
- Tree construction done in application layer, not aggregation pipeline, for simplicity
- `suggested` status used by Smart Recategorization (Phase 3); for now just include the field

**Dependencies:** Story 1.2, Story 1.5

---

#### Story 2.3: Transaction Entity and Core API

**Description:** Implement the Transaction entity -- the primary entity of the app -- with full CRUD, status management, and the core fields needed for manual entry and later ingestion.

**Acceptance Criteria:**
- Transaction document schema:
  - `amount_alert`: number (original/estimated amount)
  - `amount_settled`: number (canonical from statement, nullable until reconciled)
  - `currency`, `exchange_rate_alert`, `exchange_rate_settled`
  - `direction`: enum (debit, credit)
  - `date_alert`, `date_settled`
  - `account_id`: reference to Account
  - `merchant_name`, `merchant_name_normalized`
  - `status`: enum (unconfirmed, confirmed, reconciled)
  - `category_attributions`: array of `{category_id, amount}` for split categorization
  - `tags`: array of strings
  - `notes`: free text
  - `source`: enum (manual, gmail_alert, gmail_receipt, statement)
  - `is_reimbursable`, `reimbursement_expected_amount`, `reimbursement_party`
  - `is_transfer`: boolean (true for transfers; combined with presence/absence of `internal_transfer` link to determine one-sided vs. linked transfer)
  - `transfer_party`: string (free-text label for the untracked side of a one-sided transfer, nullable)
  - `flags`: array of strings (e.g., `amount_mismatch`)
  - `gmail_message_id`: for deduplication (nullable)
  - `line_items`: embedded array of `{description, amount, quantity, category_id}`
  - `created_at`, `updated_at`
- CRUD endpoints: `POST /api/transactions`, `GET /api/transactions`, `GET /api/transactions/{id}`, `PUT /api/transactions/{id}`, `DELETE /api/transactions/{id}`
- List endpoint with query parameters: `account_id`, `category_id`, `status`, `direction`, `date_from`, `date_to`, `amount_min`, `amount_max`, `tag`, `merchant`, `reimbursement_status`, `source`
- Pagination: cursor-based using `created_at` + `_id`
- Validation: `amount_alert` required; `category_attributions` amounts must sum to transaction amount if present; `account_id` must reference existing account
- Status transitions enforced: unconfirmed -> confirmed -> reconciled (no skipping, no backward without explicit unlock)
- `amount_mismatch` flag auto-set when `amount_settled` is written and differs from `amount_alert`

**Technical Notes:**
- `category_attributions` as an embedded array avoids a join table; keeps the document self-contained
- `merchant_name_normalized` populated by a normalizer utility (deterministic cleanup: lowercase, strip suffixes like "Inc.", collapse whitespace)
- Cursor-based pagination is essential for large transaction lists; offset-based breaks on concurrent inserts
- Index on: `(account_id, date_alert)`, `(status)`, `(merchant_name_normalized)`, `(gmail_message_id)` unique sparse
- Reimbursement fields are stored on the transaction but reimbursement *status* is derived (see Phase 3 Epic 12)

**Dependencies:** Story 2.1, Story 2.2

---

#### Story 2.4: Transaction Link Entity and API

**Description:** Implement the Transaction Link entity that represents directed associations between transactions, and between transactions and receipts.

**Acceptance Criteria:**
- TransactionLink document schema:
  - `source_type`: enum (transaction, receipt)
  - `source_id`: ID of the source entity
  - `target_type`: enum (transaction, receipt)
  - `target_id`: ID of the target entity
  - `link_type`: enum (receipt_match, reimbursement, bnpl_installment, internal_transfer)
  - `attributed_amount`: number (optional, the portion relevant to this link)
  - `created_by`: enum (auto, manual)
  - `confidence_score`: number 0-1 (for auto-created links)
  - `created_at`
- API endpoints:
  - `POST /api/transaction-links` -- create a link
  - `GET /api/transactions/{id}/links` -- get all links for a transaction
  - `DELETE /api/transaction-links/{id}` -- remove a link
- Validation:
  - Source and target must exist
  - No duplicate links (same source + target + link_type)
  - For `reimbursement` links: source must be a credit transaction, target must be a debit transaction with `is_reimbursable=true`
  - For `bnpl_installment` links: target (child) must reference the same account as source (parent)
  - For `internal_transfer` links: source and target must be on different accounts, one debit and one credit, amounts must match
  - `attributed_amount` must not cause total attributions to exceed the source or target amount
- When a link is created or deleted, affected transactions are re-evaluated for derived status (e.g., receipt match status)
- Transactions linked as `internal_transfer` are excluded from income/expense reporting by default (they are money moving between the user's own accounts, not earnings or spending)

**Technical Notes:**
- Stored as a separate collection rather than embedded, since links are queried from both directions
- Index on `(source_type, source_id)` and `(target_type, target_id)` for bidirectional lookups
- Link creation and deletion trigger audit log entries
- `confidence_score` is set by the auto-matching engine (Phase 2); manual links get `confidence_score=1.0`
- BNPL is modeled as plain transaction links: user creates a parent transaction and individual installment transactions, then links them with `bnpl_installment` type. No special batch API or auto-generation of children; the user (or statement import) creates each installment as a normal transaction

**Dependencies:** Story 2.3

---

#### Story 2.5: Receipt Entity and API

**Description:** Implement the Receipt entity representing a purchase document with optional line items, and the API for CRUD and file upload.

**Acceptance Criteria:**
- Receipt document schema:
  - `merchant_name`, `merchant_name_normalized`
  - `date`
  - `total_amount`, `subtotal`, `tax`, `tip`, `currency`
  - `line_items`: embedded array of `{description, amount, quantity, category_id}`
  - `source`: enum (gmail, manual, upload)
  - `status`: enum (unmatched, partially_matched, matched) -- derived from transaction links, not manually set
  - `file_path`: path to stored receipt file (PDF, image)
  - `raw_text`: extracted text content
  - `gmail_message_id`: for deduplication (nullable)
  - `parser_confidence`: object with per-field confidence scores
  - `created_at`, `updated_at`
- CRUD endpoints: `POST /api/receipts`, `GET /api/receipts`, `GET /api/receipts/{id}`, `PUT /api/receipts/{id}`, `DELETE /api/receipts/{id}`
- File upload endpoint: `POST /api/receipts/upload` accepts PDF or image, stores file, creates receipt record
- List endpoint with filters: `status`, `merchant`, `date_from`, `date_to`, `source`
- `status` is derived: count of transaction links with `link_type=receipt_match` determines unmatched/partially_matched/matched
- Validation: `total_amount` required; if `line_items` present, their amounts should sum to `subtotal` (warning, not blocking)

**Technical Notes:**
- File storage: local filesystem under a configurable path (e.g., `/data/receipts/`); serve via API endpoint
- Receipt file parsing (Gmail, PDF, image OCR) is handled by the ingestion pipeline (Phase 2); this story covers the entity and manual CRUD only
- `parser_confidence` structure: `{merchant_name: 0.95, total_amount: 0.99, line_items: 0.80}` -- per-field scores from the extraction pipeline
- Receipt-to-transaction matching is handled by the reconciliation engine (Phase 2)

**Dependencies:** Story 2.3, Story 2.4

---

#### Story 2.6: Multi-Currency and FX Handling

**Description:** Implement the infrastructure for multi-currency transactions: currency storage, exchange rate capture at alert time vs. settled time, and conversion logic for reporting in a base currency.

**Acceptance Criteria:**
- User sets a **base currency** in app settings (e.g., USD); all reporting and budget actuals are denominated in this currency
- Transaction schema already has `currency`, `exchange_rate_alert`, `exchange_rate_settled`; this story adds the logic around them:
  - When a transaction is created in a non-base currency, `exchange_rate_alert` is populated (manually entered or fetched)
  - When a statement settles the transaction, `exchange_rate_settled` is captured
  - If both rates exist and differ, an `fx_rate_delta` flag is set on the transaction
- Exchange rate source: manual entry for v1; optional integration with a free API (e.g., exchangerate.host) as a convenience, not a dependency
- Conversion utility: `to_base_currency(amount, currency, rate) -> base_amount` used by all aggregation queries
- Reporting and budgets operate in base currency:
  - Budget actuals converted using settled rate if available, alert rate otherwise
  - Cash flow and spending reports show base currency amounts with original currency noted
- Account-level currency: an account's currency is set at creation; transactions on that account default to its currency
- FX gain/loss: when `exchange_rate_settled != exchange_rate_alert`, compute the difference as an informational field on the transaction (not booked as a separate transaction in v1)

**Technical Notes:**
- Exchange rate API integration: optional, behind a feature flag; if disabled, user enters rates manually
- For the free API, `exchangerate.host` or `open.er-api.com` are reasonable choices with no API key required for basic usage
- Aggregation pipeline for reports: multiply `amount_settled` (or `amount_alert`) by the appropriate rate in a `$addFields` stage
- FX gain/loss = `(amount_settled * exchange_rate_settled) - (amount_alert * exchange_rate_alert)` in base currency terms
- Index consideration: no special indexing needed; FX is a per-transaction computation

**Dependencies:** Story 2.3, Story 1.3 (for base currency config)

---

#### Story 2.7: Data Export API

**Description:** Implement full data export to CSV and JSON for all core entities, fulfilling the self-hosted data portability requirement.

**Acceptance Criteria:**
- Export endpoints:
  - `GET /api/export/transactions?format=csv|json&date_from=&date_to=&account_id=`
  - `GET /api/export/receipts?format=csv|json`
  - `GET /api/export/accounts?format=json`
  - `GET /api/export/categories?format=json`
  - `GET /api/export/full?format=json` -- complete dump of all entities
- CSV export: flat structure with denormalized category names and account names; one row per transaction (splits exported as separate rows with a `split_group_id`)
- JSON export: nested structure preserving relationships (transaction with embedded links, category attributions, line items)
- Streaming response for large exports (no full materialization in memory)
- Export includes metadata header: export date, app version, entity counts

**Technical Notes:**
- Use `StreamingResponse` in FastAPI with async generators
- CSV flattening logic is non-trivial for split transactions; define a clear spec before implementing
- JSON export should be importable back (future story for import); design the schema with round-trip in mind
- Full export could be large; consider gzip compression via `Content-Encoding`

**Dependencies:** Story 2.1, Story 2.2, Story 2.3, Story 2.5
---

### Epic 3: Manual Entry

The primary user-facing data entry path until Gmail integration is built. Must be fast and friction-free for the common case, with full power available for detailed entries.

#### Story 3.1: Quick Transaction Entry

**Description:** Implement a streamlined UI and API flow for quickly recording a transaction with minimal fields.

**Acceptance Criteria:**
- UI form with fields: amount, account (dropdown), date (defaults to today), merchant name, direction (debit/credit toggle, defaults to debit), optional note
- Single-tap/click submit; transaction created with status `unconfirmed`
- After submit: toast confirmation with "Add another" and "View" actions
- Amount input supports calculator-style entry (e.g., "12.50 + 3.00")
- Merchant name autocomplete from previously used merchants
- Most recently used account pre-selected
- Keyboard shortcuts: Enter to submit, Tab between fields
- Mobile-friendly: large touch targets, no horizontal scroll

**Technical Notes:**
- Hits `POST /api/transactions` with `source=manual`
- Merchant autocomplete: `GET /api/merchants/suggest?q=` endpoint backed by a distinct query on `merchant_name_normalized`
- Calculator parsing: client-side eval of basic arithmetic in the amount field
- Pre-selection logic: store last-used account in localStorage

**Dependencies:** Story 2.3 (Transaction API)

---

#### Story 3.2: Full Transaction Entry with Itemization

**Description:** Extend the entry form to support line items, category splits, receipt attachment, and reimbursement flags.

**Acceptance Criteria:**
- All Quick Entry fields plus:
  - Line items table: description, amount, quantity, category (each row)
  - Category split: assign portions of the total to different categories (amounts must sum to total)
  - Receipt attachment: drag-and-drop or file picker for PDF/image; stored via Receipt upload API
  - Reimbursable toggle: when enabled, shows fields for expected amount (defaults to transaction amount) and reimbursing party (free text with autocomplete from past parties)
  - Tags: free-text tag input with autocomplete from existing tags
  - Notes: multiline text field
- BNPL support: user can create a parent transaction and manually link installment transactions to it via `bnpl_installment` link type (no special wizard; uses the standard transaction link UI)
- Validation:
  - Line item amounts must sum to transaction total (allow override with warning)
  - Category split amounts must sum to transaction total
  - If both line items and category split are provided, they must be consistent
- Transaction created with status `confirmed` (since user is providing full detail)

**Technical Notes:**
- Reuses the same `POST /api/transactions` endpoint with additional fields populated
- Receipt attachment: calls `POST /api/receipts/upload` first, then links via `POST /api/transaction-links`
- Category split UI: start with one row (full amount, one category), allow adding rows; auto-compute remainder
- Tags autocomplete: `GET /api/tags/suggest?q=` backed by a distinct aggregation on all transaction tags

**Dependencies:** Story 3.1, Story 2.5 (Receipt API), Story 2.4 (Transaction Link API)

---

#### Story 3.3: Transfer Entry

**Description:** Implement a dedicated form for recording internal transfers between accounts: credit card payments, bank-to-savings moves, gift card purchases, and transfers to/from accounts not tracked in the system.

**Acceptance Criteria:**
- Transfer form with fields: amount, source account, destination account, date (defaults to today), optional note
- Source and destination each support two modes:
  - **Tracked account**: selected from the account dropdown. Both sides create transactions, linked via `internal_transfer`.
  - **Untracked account**: free-text label (e.g., "Personal savings at XYZ Bank", "Venmo balance"). Only the tracked side creates a transaction. The untracked label is stored on the transaction as `transfer_party` for display and future reference.
- When both sides are tracked (internal-to-internal):
  - A single API call creates both transactions atomically (debit on source, credit on destination) plus an `internal_transfer` link
  - Both excluded from income/expense reports
- When one side is untracked (internal-to-external or external-to-internal):
  - Only the tracked-side transaction is created, with `source=manual` and a `transfer` tag
  - User chooses whether to treat it as a true transfer (excluded from income/expense reports) or as income/expense (included in reports). Default: excluded.
  - `transfer_party` field stores the free-text label for the untracked side
  - Autocomplete on `transfer_party` from previously used labels
- Gift card shortcut: if destination is a `stored_value` account, label the form as "Fund gift card"; offer inline "Create gift card account" flow if the account doesn't exist yet
- Transfer transactions display their linked counterpart or `transfer_party` label in the transaction list (e.g., "Transfer to Savings" or "Transfer to Personal savings at XYZ Bank")
- For linked transfers: editing or deleting one side prompts the user to update/delete the other

**Technical Notes:**
- Backend endpoints:
  - `POST /api/transfers` for tracked-to-tracked: creates both transactions + link atomically
  - For untracked-side transfers, reuse `POST /api/transactions` with a `transfer_party` field and `is_transfer` flag; no link created since there's no second transaction
- `transfer_party` is a string field on the Transaction document (nullable, only populated for transfers involving an untracked account)
- `is_transfer` boolean on Transaction: when true and no `internal_transfer` link exists, the transaction is a one-sided transfer to/from an untracked account. Reports check both the link and this flag to determine transfer exclusion.
- The two transactions in a tracked-to-tracked transfer should be created atomically; use MongoDB multi-document transaction if available, otherwise ensure consistent rollback on partial failure
- Gift card inline creation calls `POST /api/accounts` with `type=stored_value` before creating the transfer

**Dependencies:** Story 3.1, Story 2.4 (Transaction Link API), Story 2.1 (Account API)

---

#### Story 3.4: Transaction List View

**Description:** Build the primary transaction list view with search, filter, sort, and inline actions.

**Acceptance Criteria:**
- Paginated list of transactions, most recent first
- Columns: date, merchant, amount, account, category, status, tags
- Filter bar: account, category, status, direction, date range, amount range, tag, source
- Search: free-text search across merchant name, notes, tags
- Sort: by date, amount, merchant (toggle asc/desc)
- Inline actions: edit (opens form), delete (with confirmation), change status, quick-categorize
- Visual indicators: status badge, `amount_mismatch` flag, reimbursable icon, BNPL parent/child icon
- Bulk actions: select multiple -> bulk categorize, bulk tag, bulk delete
- Responsive: on mobile, collapses to card layout with swipe actions

**Technical Notes:**
- Hits `GET /api/transactions` with all filter/sort/pagination params
- Full-text search: MongoDB text index on `merchant_name`, `notes`, `tags`; or application-level filtering for v1
- Cursor-based pagination: use `?cursor=` param, not page numbers
- Consider virtual scrolling (react-window) if list performance is a concern

**Dependencies:** Story 2.3, Story 3.1

---

#### Story 3.5: Home Screen

**Description:** Build a lightweight landing page that gives the user an at-a-glance summary when they open the app. This is the Phase 1 home screen; it will be extended with budget progress, reconciliation status, and other widgets as later phases land.

**Acceptance Criteria:**
- **Recent transactions**: last 15 transactions displayed as a compact list (date, merchant, amount, category); "View all" link navigates to the full transaction list (Story 3.4)
- **Monthly summary**: current month income vs. expenses, shown as two numbers with a net figure (income minus expenses); period label (e.g., "February 2026") with previous/next month navigation
- Summary computed from `confirmed` and `reconciled` transactions only, consistent with how budgets will work later
- The home screen is the default route (`/`) when the app loads
- Empty state: when no transactions exist, show a welcome message with a prominent "Add your first transaction" call-to-action linking to Quick Entry (Story 3.1)
- Responsive layout: summary at the top, recent transactions below

**Technical Notes:**
- Monthly summary backed by a dedicated endpoint: `GET /api/summary?period=YYYY-MM` returning `{income, expenses, net}` via aggregation pipeline grouped by top-level category type
- Recent transactions reuse the existing `GET /api/transactions?limit=15&sort=-date_alert` endpoint
- Keep this screen simple and fast; it will accumulate widgets over time (budget cards in Phase 3 Story 10.2, reconciliation counters in Phase 2 Story 7.3, etc.)
- No charts in Phase 1; just numbers. Charts arrive with the reporting epic (Phase 3 E11)

**Dependencies:** Story 2.3, Story 3.1, Story 3.4

---

### Epic 4: Category Management

User-facing category CRUD, assignment UX, and the rule system for auto-categorization.

#### Story 4.1: Category Management UI

**Description:** Build the UI for viewing, creating, editing, and deleting categories within the fixed hierarchy.

**Acceptance Criteria:**
- Tree view showing the four top-level types with their subcategories
- Create subcategory: name, parent (must be within the same top-level type), optional icon/color
- Edit: rename, change color/icon, reorder within siblings
- Delete: only if no transactions reference it; show count of affected transactions on hover/attempt
- Merge: move all transactions from one category to another, then delete the source (with confirmation showing impact)
- Drag-and-drop reordering within the same parent

**Technical Notes:**
- Category tree from `GET /api/categories`
- Merge is a two-step operation: bulk update transactions, then delete category; wrap in a logical unit with audit log
- Color/icon are presentational metadata stored on the category document

**Dependencies:** Story 2.2, Story 3.4 (to see categories in transaction list)

---

#### Story 4.2: Transaction Categorization UX

**Description:** Implement the categorization experience within the transaction list and detail views, including split categorization.

**Acceptance Criteria:**
- Single-click category assignment from a dropdown in the transaction list (inline edit)
- Category assignment is independent of rules: setting a category on a transaction does not create or require a rule
- Category picker shows the hierarchy: top-level type headers with subcategories beneath
- Recent/frequent categories shown at the top of the picker for quick access
- Split categorization: button to "Split" opens a multi-row editor with category + amount per row
  - Amounts must sum to transaction total; remainder auto-computed for last row
  - Visual indicator on transactions that are split
- When user changes a category, system prompts: "Create a rule for [merchant]?" -- user can dismiss without creating a rule (see Story 4.3)
- Uncategorized transactions highlighted with a visual cue in the list

**Technical Notes:**
- Category picker is a reusable component (used in transaction entry, list, and receipt views)
- Split edits hit `PUT /api/transactions/{id}` updating the `category_attributions` array
- Frequent categories: query `category_attributions` across recent transactions, return top N category IDs

**Dependencies:** Story 3.4, Story 4.1

---

#### Story 4.3: Merchant-Category Rules Engine

**Description:** Implement a rule system where merchant names are mapped to categories, both system-default and user-defined, powering auto-categorization on transaction ingest.

**Acceptance Criteria:**
- Rule schema: `merchant_pattern` (exact or contains match on normalized name), `category_id`, `priority` (user rules override system defaults), `source` (system, user, learned), `created_at`
- System ships with a default rule set (e.g., "starbucks" -> Expense > Food & Drink, "netflix" -> Expense > Subscriptions)
- User can create rules manually via a rules management UI
- When a user recategorizes a transaction, system prompts to create a learned rule for that merchant (user can dismiss; the category change applies regardless)
- On rule creation (from prompt or rules management UI), user chooses:
  - **Apply retroactively**: recategorize all existing transactions matching this merchant (preview showing affected transaction count and list before committing)
  - **Forward only**: rule applies to new transactions only; existing transactions untouched
- On transaction creation (manual or ingested), the rule engine runs:
  1. Match merchant name against rules (user rules first, then system)
  2. If match found, set `category_attributions` and mark the categorization as `auto` with the rule ID
  3. If no match, leave uncategorized (LLM categorization in Phase 3)
- API endpoints: `GET /api/category-rules`, `POST /api/category-rules`, `PUT /api/category-rules/{id}`, `DELETE /api/category-rules/{id}`
- `POST /api/category-rules` accepts optional `apply_retroactively: boolean`; if true, returns a preview of affected transactions (two-step: preview then confirm)
- Retroactive application logged in audit trail as a batch operation with the rule ID as source
- Rules management UI: list all rules, filter by source, edit, delete

**Technical Notes:**
- Pattern matching: normalize the transaction merchant name, then check against rule patterns in priority order
- Start with exact and contains matching; regex patterns are a future enhancement
- System default rules shipped as a JSON seed file loaded on first startup
- Rule engine is a service called by the transaction creation pipeline (both manual entry and future ingestion paths)
- Learned rules have lower priority than explicit user rules but higher than system defaults

**Dependencies:** Story 2.2, Story 2.3, Story 4.2

---

## Phase 2: Ingestion & Reconciliation

---

### Epic 5: Parsing Infrastructure

Shared services that the Gmail pipeline, statement import, and receipt parsing all depend on. Built at the start of Phase 2 when they are first needed.

#### Story 5.1: LLM Service Abstraction Layer

**Description:** Build a provider-agnostic LLM service that routes calls to OpenAI, Anthropic, or Ollama based on configuration. All LLM calls go through this service for logging, retry, and fallback handling.

**Acceptance Criteria:**
- Unified interface: `llm.complete(prompt, schema=None) -> LLMResponse` with structured output support
- Provider adapters for OpenAI, Anthropic, and Ollama with consistent behavior
- Every call logged: timestamp, provider, model, prompt hash (not full prompt in prod), token count, latency, success/failure
- Configurable retry with exponential backoff; on final failure, return a `LLMFailure` result (never raise to caller)
- Structured output mode: pass a Pydantic model as `schema`, get validated parsed output or failure
- Rate limiting and concurrency control per provider
- Health check endpoint that verifies configured LLM provider is reachable

**Technical Notes:**
- Use `litellm` or build a thin adapter layer; `litellm` covers the provider abstraction but adds a dependency
- Ollama adapter must work with local models (e.g., llama3, mistral) and handle their different context window limits
- Log collection should be queryable for debugging extraction failures (links to audit log for traceability)
- Non-blocking: callers always get a result object, never an unhandled exception

**Dependencies:** Story 1.3

---

#### Story 5.2: Document Parsing Service (Docling)

**Description:** Build a document parsing service wrapping Docling as the layout-aware extraction layer for all PDF inputs (receipts and bank statements). This service is a shared dependency for both the receipt parser and statement import pipeline.

**Acceptance Criteria:**
- Service interface: `parse_document(file_path, doc_type: receipt|statement) -> ParsedDocument`
- `ParsedDocument` contains: extracted tables (as list of row dicts), text blocks, metadata (page count, detected language)
- Receipt mode: extracts merchant header, line item tables, totals section, tax/tip
- Statement mode: extracts transaction table(s) with columns for date, description, amount, balance; handles multi-page tables
- Handles text-based PDFs directly; for scanned/image PDFs, Docling's built-in OCR pipeline is used
- Service validates extraction quality: returns a `confidence` score based on table detection success and field coverage
- Graceful degradation: if Docling extraction fails or produces low-confidence output, return the raw text extraction as fallback
- Error cases: corrupted PDFs, password-protected files, and image-only PDFs without OCR support all return structured error responses (never raise unhandled)
- Service is callable independently for testing: CLI command to run Docling on a file and output the parsed result as JSON

**Technical Notes:**
- `pip install docling`; use `DocumentConverter` with `PdfFormatOption` configured for table extraction
- Docling outputs structured `DoclingDocument` objects; write a thin adapter to convert to our `ParsedDocument` schema
- For statement table extraction, Docling's table detection may split a multi-page table into separate tables; the adapter should merge them based on column header matching
- OCR quality varies; for scanned receipts, consider preprocessing (contrast, deskew) before passing to Docling
- This service does NOT do field-level extraction (merchant name, amount, etc.); it produces structured layout data that downstream parsers (LLM or regex) operate on
- Resource consideration: Docling with OCR can be memory-intensive; document the recommended container memory allocation

**Dependencies:** Story 1.1

---

### Epic 6: Gmail Integration

Real-time ingestion of bank alert emails and receipt emails via Gmail Pub/Sub.

#### Story 6.1: Gmail OAuth and Pub/Sub Setup

**Description:** Implement Gmail OAuth2 authentication and Pub/Sub subscription for real-time email push notifications.

**Acceptance Criteria:**
- OAuth2 flow: user initiates from the app UI, grants Gmail read-only access, tokens stored encrypted
- Pub/Sub topic and subscription created programmatically on setup
- Gmail watch registered on the user's inbox with a label filter (configurable, e.g., only specific labels)
- Webhook endpoint receives Pub/Sub push notifications
- Token refresh handled automatically; expired tokens trigger a re-auth prompt in the UI
- Setup wizard in the UI walks user through the Google Cloud project requirements (API enablement, OAuth consent screen)
- Teardown: user can disconnect Gmail, which revokes tokens and stops the watch

**Technical Notes:**
- Use `google-auth-oauthlib` and `google-api-python-client`
- Pub/Sub push endpoint must be HTTPS in production; for local dev, document ngrok or similar tunneling setup
- Watch expires every 7 days; implement a background task to renew it
- Store the `historyId` from each notification to avoid reprocessing
- Gmail message ID is the idempotency key for the entire ingestion pipeline

**Dependencies:** Story 1.3, Story 1.4

---

#### Story 6.2: Gmail Event Store and Replay

**Description:** Capture every raw Gmail event (Pub/Sub notification + fetched message content) into a durable event store before any processing occurs. Provide a replay mechanism that re-feeds stored events through the ingestion pipeline, enabling safe DB rebuilds and iterative development of parsers.

**Acceptance Criteria:**
- On every Pub/Sub notification, before classification or parsing:
  - Fetch the full Gmail message (headers, body, attachments)
  - Store the raw event as a document in an `email_events` collection: `gmail_message_id`, `history_id`, `raw_headers` (dict), `raw_body` (string), `attachments` (array of `{filename, content_type, content_base64}`), `received_at`, `replay_count` (number of times this event has been replayed, starts at 0)
  - Also write the raw event as a JSON file to a configurable local directory (e.g., `/data/email-events/`) as a backup that survives DB wipes
- Event store is append-only; raw events are never modified, only appended to
- Replay API:
  - `POST /api/dev/replay` -- replay all events (re-feeds each through classification and parsing)
  - `POST /api/dev/replay?gmail_message_id=<id>` -- replay a single event
  - `POST /api/dev/replay?from=<datetime>&to=<datetime>` -- replay events in a date range
  - Replay increments `replay_count` on the event document
  - Replay respects idempotency: if a transaction or receipt already exists for a `gmail_message_id`, the pipeline's existing duplicate detection (by `gmail_message_id`) handles it. The user can choose to wipe derived data first and replay clean.
- `POST /api/dev/replay/clean` -- deletes all gmail-sourced transactions and receipts, then replays all events from scratch. Requires confirmation parameter.
- Replay runs synchronously and returns a summary: events processed, transactions created, receipts created, errors
- All replay endpoints gated behind a `dev_mode` config flag; disabled in production by default
- CLI command: `python -m app.cli replay [--from] [--to] [--clean]` for headless replay without the API

**Technical Notes:**
- The `email_events` collection should be excluded from any DB wipe/reset scripts. Document this clearly.
- File-based backup: one JSON file per event, named `{gmail_message_id}.json`, in a date-partitioned directory structure (`/data/email-events/2026/02/`). These files are the last-resort recovery path.
- Replay calls the same `process_email_event(raw_event)` function that the live Pub/Sub handler calls. The pipeline must be stateless with respect to how the event arrives.
- Attachments are stored base64-encoded to preserve binary fidelity for PDF receipts.
- For development: maintain a curated set of anonymized sample events in `tests/fixtures/email-events/` for integration testing of the parsing pipeline without a live Gmail connection.
- Consider a `--dry-run` flag on replay that runs classification and parsing but does not persist results, useful for testing parser changes.

**Dependencies:** Story 6.1

---

#### Story 6.3: Email Classification and Routing

**Description:** When a Gmail notification arrives, fetch the email and classify it as a bank alert, receipt, or irrelevant. Route it to the appropriate parser.

**Acceptance Criteria:**
- On Pub/Sub notification: fetch new messages since last `historyId`
- For each message, classify into: `bank_alert`, `receipt`, `irrelevant`, `unknown`
- Classification logic:
  - Check sender against a known senders list (configurable, e.g., `alerts@chase.com`, `no-reply@amazon.com`)
  - Check subject line patterns (e.g., "transaction alert", "your receipt", "order confirmation")
  - If no deterministic match, use LLM classification with the email subject + first 500 chars of body
- Routing:
  - `bank_alert` -> Transaction Alert Parser (Story 6.4)
  - `receipt` -> Receipt Parser (Story 6.5)
  - `irrelevant` -> discard silently
  - `unknown` -> user review queue
- Duplicate detection: skip if `gmail_message_id` already exists in transactions or receipts
- All classification decisions logged with confidence score

**Technical Notes:**
- Known senders list stored in config/DB, user-editable
- LLM classification prompt should return structured output: `{type, confidence, reasoning}`
- Fetch message in `full` format for headers, `raw` format only if body parsing needed
- Rate limit Gmail API calls (quota is generous for single-user but be defensive)

**Dependencies:** Story 6.1, Story 6.2, Story 5.1 (LLM Service)

---

#### Story 6.4: Transaction Alert Parser

**Description:** Parse bank and credit card alert emails to extract transaction data, using deterministic templates for known institutions and LLM fallback for unknown formats.

**Acceptance Criteria:**
- Parser extracts: amount, merchant name, account (last 4 digits or name), date, transaction type (debit/credit)
- Template registry: a set of regex/template definitions per known institution (e.g., Chase, Amex, Bank of America, Capital One)
  - Each template defines: sender pattern, subject pattern, body extraction regex for each field
  - Templates shipped as a JSON/YAML config file, user-extensible
- Parser flow:
  1. Match email sender/subject to a template
  2. If matched: extract fields using the template's regex patterns
  3. If not matched: send email body to LLM with structured output schema
  4. Attach `parser_confidence` per field (1.0 for template match, LLM-reported for fallback)
- On successful parse:
  - Create Transaction with `source=gmail_alert`, `status=unconfirmed`
  - Run merchant normalization and category rule engine
  - Attempt auto-match with existing unmatched receipts (Story 8.2)
- On failed parse: create entry in user review queue with the raw email content
- Templates are testable in isolation: provide a test harness that runs sample emails against templates

**Technical Notes:**
- Template registry pattern: each template is a class/dict with `match(email) -> bool` and `extract(email) -> TransactionFields`
- LLM fallback prompt: include 3-4 few-shot examples of alert emails and expected JSON output
- Account matching: use last 4 digits extracted from email to match against user's accounts
- Consider storing raw email body on the transaction document for debugging/re-parsing

**Dependencies:** Story 6.3, Story 2.3, Story 4.3 (Category Rules), Story 5.1

---

#### Story 6.5: Receipt Email Parser

**Description:** Parse receipt and order confirmation emails to extract merchant, line items, totals, and tax. LLM-primary with Docling for PDF attachments.

**Acceptance Criteria:**
- Parser extracts: merchant name, date, total amount, subtotal, tax, tip, line items (description, amount, quantity), currency
- Two parsing modes:
  - **HTML/text email body**: send structured content to LLM with extraction schema
  - **PDF attachment**: extract via Docling first, then pass structured output to LLM for field extraction
- Parser flow:
  1. Check for PDF attachments; if present, run Docling extraction
  2. Send email body (or Docling output) to LLM with the receipt extraction schema
  3. Validate extracted fields (total >= subtotal, line items sum approximately to subtotal)
  4. Attach `parser_confidence` per field
- On successful parse:
  - Create Receipt with `source=gmail`, `status=unmatched`
  - Attempt auto-match with existing unmatched transactions (Story 8.2)
  - If no match found, determine whether to create a transaction:
    - **Payment method maps to an account with `expects_alerts=true`**: do not create a transaction immediately. Instead, schedule a deferred check after a configurable grace period (default: 48 hours). If no matching bank alert arrives within the grace period, create an `unconfirmed` transaction from the receipt data and link them.
    - **Payment method maps to an account with `expects_alerts=false`** (cash, stored_value) or **payment method is unrecognized**: create an `unconfirmed` transaction immediately from the receipt data and link via `receipt_match`.
  - Payment method extraction: parser attempts to identify payment method from receipt content (last 4 digits, card network, "paid with gift card", etc.) and match to a known account
- On failed parse: entry in user review queue
- Support for multi-item order emails (e.g., Amazon with multiple products)
- For split-funded purchases (e.g., partial gift card + credit card): parser extracts multiple payment lines if present; each creates a separate transaction on the respective account, all linked to the same receipt with `attributed_amount`

**Technical Notes:**
- Docling integration: `pip install docling`; use `DocumentConverter` for PDF -> structured JSON
- LLM receipt prompt: define a Pydantic schema for the expected output; use structured output mode
- Line item extraction is inherently noisy; store raw extracted text alongside parsed fields for user correction
- For image-based receipts (not PDF), this story handles email-attached images only; camera capture is future scope
- Grace period: implement as a delayed task (e.g., Celery/APScheduler/background coroutine). The receipt stores `pending_transaction_creation_at` timestamp; a periodic job checks for expired grace periods and creates transactions. If a bank alert arrives and matches during the grace period, the pending creation is cancelled.
- Payment method matching: extract last 4 digits or card network name from receipt text, compare against user's accounts. Confidence-scored; low-confidence matches fall back to the user review queue.

**Dependencies:** Story 6.3, Story 2.5, Story 5.1, Story 5.2 (Docling Service)

---

#### Story 6.6: Email Processing Review Queue

**Description:** Build a UI for reviewing emails that failed to parse or were classified as unknown, and for correcting auto-extracted data.

**Acceptance Criteria:**
- Review queue page showing all pending review items, newest first
- Each item shows: email subject, sender, received date, classification result, parser output (if any), confidence scores
- Actions per item:
  - **Correct and accept**: edit extracted fields, save as transaction or receipt
  - **Reclassify**: change from unknown to bank_alert or receipt, re-run appropriate parser
  - **Dismiss**: mark as irrelevant (won't appear again)
  - **Create template**: for bank alerts, option to define a new template from this email (opens template editor)
- Low-confidence fields highlighted in the parser output
- Batch dismiss for multiple irrelevant emails
- Counter/badge on the navigation showing pending review items

**Technical Notes:**
- Review queue backed by a `review_items` collection with status (pending, resolved, dismissed)
- Template creation from the review queue is a guided flow: user highlights the patterns in the email body, system generates regex patterns
- This is the safety net ensuring no data is silently dropped

**Dependencies:** Story 6.4, Story 6.5, Story 3.4

---

### Epic 7: Bank Statement Import

Ingest bank statements as the canonical record, match against existing transactions, and surface discrepancies.

#### Story 7.1: Statement Upload and Parsing

**Description:** Accept bank statement files (CSV, OFX/QFX, PDF), parse them into structured statement lines, and associate them with an account and statement period.

**Acceptance Criteria:**
- Upload endpoint: `POST /api/statements/upload` accepts file + account_id + statement_period (month/year)
- Supported formats:
  - **CSV**: configurable column mapping (amount, date, description, reference) per institution; UI for column selection on first upload per institution
  - **OFX/QFX**: parsed via `ofxparse` library; standard fields extracted automatically
  - **PDF**: processed via Docling to extract tabular data, then field extraction (LLM-assisted for complex layouts)
- Statement document schema: `account_id`, `period` (YYYY-MM), `file_path`, `format`, `status` (processing, ready, reconciled, locked), `line_count`, `balance_opening`, `balance_closing`, `uploaded_at`
- Statement Line schema (embedded or subcollection): `date`, `description`, `amount`, `reference`, `balance_after` (if available), `match_status` (unmatched, matched, skipped)
- Validation:
  - Reject duplicate statement (same account + period, unless previous was unlocked)
  - Opening balance of new statement should match closing balance of previous period (warn if mismatch)
- PDF parsing: Docling extracts tables; LLM cleans up any messy rows; user reviews before proceeding

**Technical Notes:**
- CSV column mapping: store per-institution mapping in config; on first upload, present a column mapping UI
- `ofxparse` handles OFX/QFX natively; extract `Statement` and `Transaction` objects
- PDF statement parsing is the hardest path; Docling's table extraction is the key enabler
- Statement lines stored with the raw `description` field for matching; normalized version computed on insert

**Dependencies:** Story 2.1 (Account API), Story 5.1 (LLM for PDF parsing), Story 5.2 (Docling Service)

---

#### Story 7.2: Statement-to-Transaction Matching

**Description:** When a statement is imported, automatically match each statement line to existing app transactions and surface discrepancies.

**Acceptance Criteria:**
- Matching runs automatically after statement parsing completes
- Match algorithm per statement line:
  1. Exact match: same account, amount within tolerance (configurable, e.g., +/- $0.01), date within window (configurable, e.g., +/- 3 days), merchant name similarity > threshold
  2. Fuzzy match: relax one or more criteria; present as candidate matches with confidence score
  3. No match: line marked as `unmatched`
- On match:
  - Transaction `amount_settled` and `date_settled` updated from statement line
  - Transaction status set to `reconciled`
  - If `amount_settled != amount_alert`, set `amount_mismatch` flag
  - If `date_settled != date_alert` beyond tolerance, log discrepancy
- After matching, surface:
  - **Matched with discrepancies**: transactions where settled differs from alert (amount or date)
  - **Unmatched statement lines**: lines with no matching app transaction (user must create or skip)
  - **Orphaned app transactions**: app transactions in this period with no matching statement line (user investigates)
- All matches logged in audit trail with match type (exact/fuzzy) and confidence

**Technical Notes:**
- Matching is a batch operation scoped to the statement's account and date range
- Merchant name similarity: use normalized names + Levenshtein distance or token-based similarity
- Tolerance values should be configurable per account (some institutions post with delays)
- Performance: for a single-user app, brute-force comparison is fine (hundreds, not millions of records)
- Consider LLM-assisted matching for ambiguous cases (merchant name variants, split transactions)

**Dependencies:** Story 7.1, Story 2.3, Story 1.5 (Audit Log)

---

#### Story 7.3: Statement Reconciliation UI

**Description:** Build the reconciliation interface where users review matches, resolve discrepancies, and lock the statement period.

**Acceptance Criteria:**
- Reconciliation view per statement, showing three sections:
  1. **Matched**: statement line paired with app transaction; show both side-by-side; discrepancies highlighted
  2. **Unmatched statement lines**: lines with no app transaction; actions: create transaction, skip, manual match
  3. **Orphaned transactions**: app transactions not on statement; actions: investigate, mark as pending, delete
- For matched items with discrepancies:
  - "Accept statement value" button (updates transaction with settled amount/date, acknowledges mismatch)
  - "Keep app value" button (flags for further investigation)
- Manual match: select an unmatched statement line and an orphaned transaction, link them
- Progress bar: X of Y items resolved
- Lock period: enabled when all items are resolved or explicitly skipped
  - Locked period is immutable; transactions within it cannot be edited without explicit unlock
  - Unlock requires confirmation dialog explaining the implications
- Opening/closing balance shown at top of the view; closing balance cross-checked against derived balance from reconciled transactions

**Technical Notes:**
- This is one of the most complex UI screens in the app; consider a step-by-step wizard flow as alternative to showing all sections at once
- Locking sets `status=locked` on the statement document and marks all associated transactions as `reconciled`
- Unlock resets statement status to `ready` and affected transaction statuses to `confirmed`
- Side-by-side comparison component reusable for other matching contexts

**Dependencies:** Story 7.2, Story 3.4

---

### Epic 8: Reconciliation Engine

Cross-cutting auto-matching logic used by both Gmail ingestion and statement import.

#### Story 8.1: Merchant Name Normalization Service

**Description:** Build a normalization service that cleans and standardizes merchant names for consistent matching across alerts, receipts, and statements.

**Acceptance Criteria:**
- Normalization pipeline:
  1. Lowercase
  2. Strip common suffixes: "Inc.", "LLC", "Corp.", "Ltd.", "Co."
  3. Strip location qualifiers: "Store #1234", "Location: NYC", city/state suffixes
  4. Collapse whitespace and special characters
  5. Apply alias mapping: user-defined and system-default (e.g., "AMZN MKTP" -> "amazon", "SQ *" -> strip prefix)
- Alias management: `GET/POST/PUT/DELETE /api/merchant-aliases`
- System ships with a default alias set for common merchant variants
- Service callable from: transaction creation, receipt creation, statement line parsing, matching engine
- Fuzzy match function: given two normalized names, return similarity score (0-1)
- For novel merchants with no alias match, optionally call LLM to suggest canonical name

**Technical Notes:**
- Normalization should be idempotent and fast (called on every ingest)
- Fuzzy matching: use `rapidfuzz` library for Levenshtein / token sort ratio
- Alias mapping stored in DB, seeded from a JSON file on first startup
- LLM call for novel merchants is async and non-blocking; create the transaction with the cleaned name immediately

**Dependencies:** Story 5.1, Story 2.3

---

#### Story 8.2: Auto-Match Engine

**Description:** Implement the automatic matching engine that attempts to link transactions to receipts and vice versa as new items are ingested.

**Acceptance Criteria:**
- Triggered on: new transaction creation (any source), new receipt creation (any source)
- Matching logic:
  1. Find unmatched items of the opposite type for the same account
  2. Score candidates on: amount proximity (weight: high), merchant name similarity (weight: high), date proximity (weight: medium)
  3. High-confidence match (score > configurable threshold): create `receipt_match` link automatically, log as auto-match
  4. Medium-confidence match: add to suggestions queue (user confirms)
  5. No match: item remains unmatched
- Sum-match detection: if a single receipt total matches the sum of multiple transactions (or vice versa), create many-to-one links with attributed amounts
- Match suggestions surfaced in the transaction detail view and receipt detail view
- All auto-matches logged with confidence score in audit trail

**Technical Notes:**
- Scoring weights and thresholds configurable in settings
- Run matching asynchronously (background task) to avoid blocking the ingest pipeline
- For sum-match, limit the combination search to avoid combinatorial explosion (max 5 items per side)
- Consider a dedicated `match_suggestions` collection for medium-confidence candidates

**Dependencies:** Story 8.1, Story 2.4 (Transaction Links), Story 2.5 (Receipts)

---

### Epic 9: Receipt Management

User-facing receipt workflows beyond parsing -- viewing, editing, manual upload, and matching.

#### Story 9.1: Receipt Detail View and Editor

**Description:** Build a UI for viewing, editing, and correcting receipt data including line items.

**Acceptance Criteria:**
- Receipt detail view showing: merchant, date, totals, line items table, source, confidence scores, linked transactions
- Inline editing of all fields
- Line item editor: add, remove, edit rows; auto-recalculate subtotal
- Receipt image/PDF viewer alongside the data (side-by-side on desktop)
- Low-confidence fields highlighted for review
- "Re-parse" button: re-runs the parser on the original file/email with current LLM settings
- Link/unlink transactions from the receipt detail view

**Technical Notes:**
- PDF/image viewer: use `react-pdf` for PDFs, native `<img>` for images
- Re-parse triggers the receipt parser (Story 6.5) on the stored raw content
- Editing a receipt that is linked to a transaction should surface a warning if it changes the total

**Dependencies:** Story 2.5, Story 6.5, Story 3.4

---

#### Story 9.2: Manual Receipt Upload and Entry

**Description:** Allow users to upload receipt files or manually enter receipt data outside the Gmail pipeline.

**Acceptance Criteria:**
- Upload flow: drag-and-drop or file picker for PDF, PNG, JPG
  - On upload: file stored, parser runs automatically, extracted data shown for review
  - User corrects any fields and saves
- Manual entry flow: form with merchant, date, total, optional line items (no file)
- After save: auto-match engine (Story 8.2) runs to find matching transactions
- Bulk upload: accept multiple files at once, queue for parsing, show progress

**Technical Notes:**
- File upload to `POST /api/receipts/upload`, parsing is async
- For image receipts (PNG/JPG): use Docling with OCR capabilities, or send directly to LLM vision API
- Bulk upload: create a batch job, process sequentially, update UI via polling or WebSocket

**Dependencies:** Story 2.5, Story 8.2, Story 5.1

---

## Phase 3: Intelligence & Reporting

---

### Epic 10: Budgets

Budget creation, tracking, and alerting.

#### Story 10.1: Budget CRUD and Configuration

**Description:** Implement the Budget entity and API for creating and managing spending targets.

**Acceptance Criteria:**
- Budget document schema: `name`, `type` (expense_cap, income_target, savings_goal, giving_target), `category_ids` (array, references one or more categories), `amount`, `frequency` (one_time, weekly, monthly, quarterly, annual), `start_date`, `end_date` (for one-time), `rollover_enabled`, `alert_threshold` (percentage, e.g., 80), `gross_or_net` (for reimbursable expense handling), `is_active`, `created_at`, `updated_at`
- CRUD endpoints: `POST /api/budgets`, `GET /api/budgets`, `GET /api/budgets/{id}`, `PUT /api/budgets/{id}`, `DELETE /api/budgets/{id}`
- Validation:
  - Category IDs must exist and match the budget type (e.g., expense_cap only references expense categories)
  - Amount must be positive
  - Frequency + start_date defines the periods
- Actuals calculation: sum of `confirmed` and `reconciled` transactions in the budget's categories for the current period
  - If `gross_or_net=net`: subtract attributed reimbursement amounts from actuals
- Period computation: given frequency and start_date, compute current period boundaries and actuals

**Technical Notes:**
- Actuals computed on read via aggregation pipeline (not stored); cache if needed
- Rollover: unspent amount from previous period added to current period's budget amount
- Rollover computation needs previous period's actuals; recursive lookback capped at configurable depth
- `category_ids` allows a single budget to span multiple categories (e.g., "Food" budget covering "Groceries" + "Restaurants")

**Dependencies:** Story 2.2, Story 2.3

---

#### Story 10.2: Budget Dashboard and Progress UI

**Description:** Build the budget tracking interface showing progress, projections, and alerts.

**Acceptance Criteria:**
- Budget dashboard: card per active budget showing name, period, spent vs. budgeted, remaining, progress bar
- Progress bar color: green (< 60%), yellow (60-80%), orange (80-threshold%), red (> threshold%)
- Projected end-of-period spend: linear projection based on current spend rate and days elapsed/remaining
- Click into a budget: see the transactions contributing to actuals, grouped by category
- Overspend alert: visual badge on the budget card; optionally, in-app notification
- Period navigation: view past periods with actuals, see rollover amounts
- Summary row: total budgeted vs. total spent across all active budgets

**Technical Notes:**
- Projection: `(current_spend / days_elapsed) * total_days_in_period`
- In-app notifications: for v1, surface as UI badges; push notifications are future scope
- Consider caching budget actuals on a short TTL (1 minute) since the aggregation runs on every page load

**Dependencies:** Story 10.1, Story 3.4

---

#### Story 10.3: Budget Impact on Category Changes

**Description:** When categories are reclassified (moved, merged, or split), flag affected budgets for user review.

**Acceptance Criteria:**
- When a transaction's category changes and the transaction falls within an active budget's period:
  - Recalculate affected budget actuals
  - If the change moves spend into or out of a budgeted category, flag the budget with a `needs_review` indicator
- Budget review: user sees which transactions moved, the old and new actuals, and can acknowledge the change
- When a category is deleted via merge (Story 4.1), all budgets referencing it are automatically updated to reference the merge target
- Audit log records the budget impact of category changes

**Technical Notes:**
- Implement as a post-update hook on transaction category changes
- Budget flagging: add a `flags` array on the budget document (e.g., `category_change_review`)
- This becomes more important when Smart Recategorization (Story 12.x) moves transactions in bulk

**Dependencies:** Story 10.1, Story 4.2

---

### Epic 11: Reporting & Dashboard

Dashboards, charts, and data views for financial insight.

#### Story 11.1: Main Dashboard

**Description:** Extend the Phase 1 home screen (Story 3.4) into a full dashboard with budget progress, account balances, reconciliation status, and pending action counters.

**Acceptance Criteria:**
- Cash flow summary: income vs. expenses vs. giving vs. investments for current month, with comparison to previous month
- Account balances: card per account showing current derived balance
- Budget overview: top 3-5 budgets with progress bars (links to full budget dashboard)
- Recent transactions: last 10 transactions with quick link to full list
- Pending items counter: unreconciled transactions, unmatched receipts, review queue items
- Period selector: switch between current month, last month, custom range
- All data reflects confirmed and reconciled transactions only (consistent with budget actuals)

**Technical Notes:**
- Dashboard data aggregated via dedicated API endpoint: `GET /api/dashboard?period=`
- Aggregate multiple queries in parallel for performance
- Consider a dashboard data cache with short TTL

**Dependencies:** Story 2.1, Story 2.3, Story 10.1

---

#### Story 11.2: Cash Flow and Spending Reports

**Description:** Detailed reporting views for cash flow analysis and spending breakdowns.

**Acceptance Criteria:**
- **Cash flow report**: bar or area chart showing income, expenses, giving, investments by period (weekly, monthly, quarterly)
  - Table view alongside chart with exact figures
  - Toggle: show as stacked or side-by-side
- **Spending breakdown**: pie/donut chart + table showing expense categories by amount and percentage
  - Click a category to drill down into subcategories
  - Top merchants per category
- Filters on all reports: account, category, date range, tags
- Gross vs. net toggle: when enabled, subtract reimbursed amounts from expenses
- Export: download any report view as CSV

**Technical Notes:**
- Use a charting library: Recharts (React) for consistency and simplicity
- Report data from dedicated aggregation endpoints: `GET /api/reports/cashflow`, `GET /api/reports/spending`
- Aggregation pipeline for spending breakdown: group by category, compute sums, sort by amount

**Dependencies:** Story 2.3, Story 2.2

---

#### Story 11.3: Reimbursement Aging Report

**Description:** A dedicated report showing outstanding reimbursements by party, amount, and age.

**Acceptance Criteria:**
- Table showing all transactions flagged `is_reimbursable=true` with status not `received` or `written_off`
- Columns: date, merchant, amount, expected reimbursement, received so far, outstanding, reimbursing party, days pending
- Group by reimbursing party with subtotals
- Sort by: days pending (oldest first), amount outstanding, party
- Status filter: pending, partially received, written off
- Summary row: total outstanding across all parties
- Click a row to see the transaction detail and linked reimbursement income transactions

**Technical Notes:**
- Reimbursement status derived at query time: compare `reimbursement_expected_amount` against sum of `attributed_amount` on linked `reimbursement` transaction links
- `days_pending = today - date_alert` for unreceived; `today - date of last partial receipt` for partially received
- Aggregation pipeline: match reimbursable transactions, lookup links, compute outstanding

**Dependencies:** Story 2.3, Story 2.4, Story 13.1

---

#### Story 11.4: Account Balance History

**Description:** Chart showing account balances over time, derived from transaction history.

**Acceptance Criteria:**
- Line chart: one line per selected account(s), showing balance by day/week/month
- Balance computed as running sum of reconciled and confirmed transactions from initial balance
- Hover: show exact balance on the date
- Account selector: pick one or more accounts, or "all accounts" for aggregate view
- Date range selector
- Net worth line: sum of all account balances (assets positive, credit card balances negative)

**Technical Notes:**
- Running balance computation: aggregation pipeline with `$setWindowFields` for cumulative sum, or application-level computation
- For accounts with initial_balance set, start the line from that value
- Net worth is a simple sum; v1 is manually maintained (investment accounts just track cash movements)

**Dependencies:** Story 2.1, Story 2.3

---

### Epic 12: Smart Categorization

AI-powered category suggestions and spend pattern analysis.

#### Story 12.1: AI Category Suggestions

**Description:** Periodically analyze spending patterns to identify transaction clusters that may warrant a new dedicated category.

**Acceptance Criteria:**
- Background job runs periodically (configurable, e.g., weekly) or on-demand
- Analysis:
  - Group transactions by merchant, subcategory, and spend pattern
  - Identify clusters: transactions spread across multiple categories that share a theme (e.g., "skincare" across Shopping and Health)
  - Use LLM to propose a category name and description for each cluster
- For each identified cluster:
  - Create a `suggested` category with the proposed name
  - Associate the identified transactions (by ID) without moving them
  - Store the suggestion with: proposed name, rationale, transaction IDs, affected current categories
- Suggested categories appear in a dedicated review section in the Category Management UI
- Maximum active suggestions: configurable cap (e.g., 5) to avoid overwhelming the user

**Technical Notes:**
- LLM prompt: provide transaction list (merchants, amounts, current categories) and ask for clustering suggestions
- Consider using embeddings for transaction descriptions and clustering via DBSCAN/HDBSCAN as an alternative to pure LLM
- Suggestion stored in a `category_suggestions` collection, not the main categories collection, until confirmed

**Dependencies:** Story 4.1, Story 5.1, Story 2.3

---

#### Story 12.2: Category Suggestion Review and Reclassification

**Description:** UI for reviewing AI-suggested categories, editing the proposed grouping, and committing the reclassification with full impact visibility.

**Acceptance Criteria:**
- Suggestion review page shows each proposed category with: name, rationale, list of member transactions, current categories those transactions belong to
- User can: rename the category, add transactions, remove transactions, view each transaction's detail
- **Confirm flow**:
  1. User clicks "Apply"
  2. System shows reclassification impact: which transactions move, which categories they leave, which budgets are affected (with before/after actuals)
  3. User approves or cancels
  4. On approve: category created as `active`, transactions reclassified, budget flags set, audit log entries created
- **Delete flow**: discard suggestion, all transactions remain untouched
- Dismissal feedback: optionally tell the system why the suggestion was irrelevant (improves future suggestions)

**Technical Notes:**
- Impact preview is a dry-run aggregation: recompute budget actuals with the proposed category changes without committing
- Reclassification is a batch update on transactions; wrap in a logical operation with full audit trail
- Dismissed suggestions stored with feedback for training/tuning the suggestion algorithm

**Dependencies:** Story 12.1, Story 10.3, Story 4.1

---

### Epic 13: Reimbursement Tracking

Full reimbursement lifecycle: flagging, linking, tracking, and write-off.

#### Story 13.1: Reimbursement Flagging and Linking

**Description:** Allow users to flag expenses as reimbursable and link incoming payments to settle them.

**Acceptance Criteria:**
- On any debit transaction: toggle `is_reimbursable`, set `reimbursement_expected_amount` (defaults to transaction amount), set `reimbursement_party` (with autocomplete from past parties)
- On any credit transaction: option to "Apply to reimbursement" which opens a picker showing pending reimbursable expenses
  - User selects one or more expenses and enters the attributed amount per expense
  - System creates `reimbursement` links with attributed amounts
  - Validation: total attributed amounts from this credit cannot exceed the credit amount
- Reimbursement status derived per expense:
  - `pending`: expected > 0, no linked income
  - `partially_received`: sum of attributed income < expected
  - `received`: sum of attributed income >= expected
  - `written_off`: manually marked by user
- Write-off action: user marks a pending reimbursement as written off with optional note

**Technical Notes:**
- Reimbursement party autocomplete: distinct query on `reimbursement_party` field across transactions
- Status derivation: compute on read via a utility function, not stored on the document
- Link attribution validation must be cross-transaction: sum of all attributions from a single credit across all its reimbursement links <= credit amount

**Dependencies:** Story 2.3, Story 2.4

---

#### Story 13.2: Reimbursement Dashboard Widget

**Description:** Add a reimbursement summary to the main dashboard and a dedicated management view.

**Acceptance Criteria:**
- Dashboard widget: total outstanding reimbursements, count of pending items, oldest pending item age
- Dedicated reimbursement view:
  - Grouped by party: expandable sections showing each party's pending expenses
  - Per expense: date, merchant, expected amount, received so far, outstanding, age in days
  - Quick actions: link a payment, write off, view transaction detail
- Filter by party, status, date range
- Sort by age (oldest first), amount outstanding

**Technical Notes:**
- Reuses the aggregation from Story 11.3 but with a more interactive UI
- Consider combining with Story 11.3 into a single view with dashboard widget and detailed report tabs

**Dependencies:** Story 13.1, Story 11.1

---

## Dependency Graph Summary

```
Phase 1:
  E1 (Bootstrap) --> E2 (Data Model) --> E3 (Manual Entry) --> E4 (Categories)
  
Phase 2:
  E1 --> E5 (Parsing Infra: LLM + Docling)
  E2 + E5 --> E6 (Gmail) --> E8 (Reconciliation Engine)
  E2 + E5 --> E7 (Statement Import) --> E8
  E6 + E8 --> E9 (Receipt Management)

Phase 3:
  E4 + E2 --> E10 (Budgets)
  E2 --> E11 (Reporting)
  E4 + E10 --> E12 (Smart Categorization)
  E2 --> E13 (Reimbursement Tracking)
  E13 --> E11.3 (Reimbursement Report)
```

---

## Story Count Summary

| Phase | Epic | Stories |
|-------|------|---------|
| 1 | E1: Project Bootstrap | 5 |
| 1 | E2: Core Data Model & API | 7 |
| 1 | E3: Manual Entry | 5 |
| 1 | E4: Category Management | 3 |
| 2 | E5: Parsing Infrastructure | 2 |
| 2 | E6: Gmail Integration | 6 |
| 2 | E7: Bank Statement Import | 3 |
| 2 | E8: Reconciliation Engine | 2 |
| 2 | E9: Receipt Management | 2 |
| 3 | E10: Budgets | 3 |
| 3 | E11: Reporting & Dashboard | 4 |
| 3 | E12: Smart Categorization | 2 |
| 3 | E13: Reimbursement Tracking | 2 |
| **Total** | **13 epics** | **46 stories** |
