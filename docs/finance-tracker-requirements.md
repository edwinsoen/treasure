# Personal Finance Tracker — High-Level Requirements

## 1. Product Overview

A self-hosted, open-source personal finance tracker that ingests transaction data from Gmail (bank alerts and receipts), manual entries, and monthly bank statements. The core model is money-movement-first with optional itemization. Reconciliation is a first-class workflow, not an afterthought. No bank API connections.

Tracking scope: **expenses, income, investments, and giving.**

---

## 2. Core Data Model

### 2.1 Transaction (Money Movement)
The primary entity of the app. Represents a confirmed or pending movement of money.

- Amount (alert/estimated) and amount (settled/canonical from statement)
- Currency, exchange rate at alert time vs. settled rate
- Direction: debit or credit
- Date (alert date) and settled date (from statement)
- Source account
- Status: `unconfirmed` | `confirmed` | `reconciled`
- Optional: linked receipts, linked transactions (reimbursement, BNPL), manual notes, tags
- Optional: itemization (line items with category attribution)
- Flag: `amount_mismatch` when settled amount differs from alert amount

**Bank statements are canonical.** Alert-derived transactions are provisional. When a statement is imported, the settled amount and date on the statement override the alert values. Discrepancies are flagged for user acknowledgement, not silently resolved.

#### Reimbursement Tracking
Reimbursement is modeled as a relationship between transactions, not a separate entity.

- An expense transaction can be flagged `reimbursable`, with an optional expected reimbursement amount and reimbursing party (employer, insurance provider, or individual)
- When a reimbursement arrives, it is recorded as a normal income transaction
- The income transaction is linked to one or more expense transactions with an **attributed amount** on each link -- since a single inbound credit (e.g. a paycheck, an insurance payout) may partially or fully settle multiple claims
- Net outstanding per expense = expected amount minus sum of attributed portions across all linked income transactions
- Reimbursement status (`pending` | `partially received` | `received` | `written off`) is derived from the above, not stored

### 2.2 Receipt
A document representing a purchase, with optional line items.

- Merchant name, date, total amount
- Line items: description, amount, quantity, inferred category
- Source: Gmail parse, manual entry, or file upload
- Status: `unmatched` | `partially matched` | `matched`
- May be linked to one or more transactions and vice versa, only when the many-to-many case genuinely applies. Linkage is a lightweight association on the transaction, not a first-class entity.

### 2.3 Transaction Link
A directed association between two transactions or between a transaction and a receipt, carrying an optional attributed amount.

- Used for: receipt-to-transaction matching, transaction-to-transaction reimbursement linkage, BNPL parent-to-installment relationships
- Attributed amount: the portion of the linked item relevant to this specific relationship
- Link type: `receipt_match` | `reimbursement` | `bnpl_installment`

### 2.4 Account
Represents a financial account or wallet.

- Types: checking, savings, credit card, investment/brokerage, cash/manual
- Balance: derived from reconciled transactions or manually entered
- Statement periods for monthly reconciliation
- Currency (supports foreign-currency accounts)

### 2.5 Category
Hierarchical taxonomy with fixed top-level types and user-defined subcategories.

- Top-level types are fixed and not user-customizable: **expense, income, investment, giving**
- User can create and manage categories beneath each top-level type
- A transaction or line item can be split across multiple categories with attributed amounts
- Categories can have a `suggested` status (see section 5.2)

**Investment** covers cash movements into and out of investment or brokerage accounts (contributions, withdrawals). Individual holdings, lots, cost basis, and portfolio performance are out of scope for v1. Net worth tracking is a future milestone.

**Giving** covers charitable donations, religious giving (e.g. tithing), and direct financial assistance to individuals. Gifts with a transactional or social nature (holiday gifts, birthday presents) are categorized as expenses, not giving.

### 2.6 Budget
A spending or income target referencing one or more categories.

- Frequency: one-time (date range), weekly, monthly, quarterly, annual
- Type: expense cap, income target, savings goal, giving target
- Rollover option: unspent amount carries to next period
- Actuals computed from confirmed and reconciled transactions only
- User controls whether reimbursable expenses appear gross or net in budget actuals
- When a category reclassification affects a budget's actuals, the budget is flagged for user review

---

## 3. Data Ingestion

### 3.1 Gmail Integration (Phase 1)
- Gmail Pub/Sub push notifications for near-real-time inbound email processing
- Two email parsers:
  - **Transaction alert parser**: extracts amount, merchant, account, date from bank/card notification emails. Deterministic regex and template matching per institution; LLM fallback for unknown formats.
  - **Receipt parser**: extracts merchant, line items, totals, tax, tip. LLM-primary due to format variance; layout-aware parsing via Docling for PDF receipts.
- Duplicate detection on ingest (idempotent by Gmail message ID)
- Unprocessable emails flagged for user review, never silently dropped
- Parser confidence score attached to every auto-extracted field

Gmail read access for backfill (e.g. historical receipt import) is deferred to a future phase.

### 3.2 Manual Entry
- Quick entry: amount, account, date, merchant, optional note
- Full entry: itemization, category splits, receipt attachment, reimbursable flag with party and expected amount
- BNPL entry: parent transaction with scheduled installment children linked via `bnpl_installment` transaction links

### 3.3 Bank Statement Import
- Supported formats: CSV, OFX/QFX, PDF (text-based and layout-parsed via Docling)
- Statement is the canonical record. On import:
  1. Each statement line is matched to existing app transactions by amount, date, and merchant
  2. Matched transactions have their settled amount and date updated from the statement
  3. Amount or date discrepancies between alert and statement are flagged for user acknowledgement
  4. Statement lines with no matching app transaction are surfaced as missing -- user creates or skips
  5. App transactions with no matching statement line are surfaced as unconfirmed -- user investigates
- Once a statement period is reconciled and locked, it is immutable (override requires explicit unlock)

---

## 4. Reconciliation Workflow

- Reconciliation dashboard per account showing unreconciled items by period
- **Auto-match on ingest**: attempts to link incoming alerts and receipts to existing unmatched items
  - Matching signals: amount proximity, merchant name similarity, date window, account
  - Deterministic for high-confidence matches; LLM-assisted for ambiguous cases
  - Many-to-many linking created only when sum-match requires it; single linkage is the default
- **Manual match UI**: select and link transactions to receipts; split a receipt across transactions or vice versa
- **Monthly reconciliation flow**:
  1. User uploads bank statement for the period
  2. System matches statement lines to app transactions
  3. Discrepancies shown: missing transactions, settled amount mismatches, FX rate deltas, duplicates
  4. User resolves each item; period locked when all items are cleared or explicitly skipped
- Audit trail: every match, override, and lock action is logged with timestamp and source (auto/manual)

---

## 5. Categorization

### 5.1 Auto-Categorization
- On ingest, categories are inferred using:
  - Merchant name rules (deterministic, user-defined and system defaults)
  - Receipt line items (LLM-assisted)
  - Historical patterns per merchant per user
- Suggestions presented for unconfirmed transactions; user confirms or overrides
- Category splits: a transaction or line item can be attributed to multiple categories with amounts
- Learned rules: correcting a category prompts the system to offer a persistent rule for that merchant

### 5.2 Smart Recategorization (AI-Suggested Categories)
- AI periodically analyzes spend patterns to identify clusters of transactions that may warrant a dedicated category (e.g. a rising skincare spend spread across Shopping and Health)
- When a cluster is identified, the system creates a `suggested` category pre-populated with the identified transactions
- Transactions remain in their current categories -- no reclassification occurs at suggestion time
- The user reviews the suggested category and its member transactions, and can add or remove transactions before deciding
- On **confirm**: the system presents the full reclassification impact -- which transactions will move, which categories they leave, and which budgets are affected -- and asks the user to approve before committing
- On **delete**: the suggestion is discarded and all transactions remain untouched

---

## 6. Budgets and Reporting

### 6.1 Budgets
- Reference one or more categories; no separate category group entity
- Periods: one-time (date range), weekly, monthly, quarterly, annual
- Progress: spent vs. budgeted, remaining, projected end-of-period spend
- Overspend alerts at configurable threshold (e.g. warn at 80%)
- Rollover option per budget

### 6.2 Reports and Dashboard
- Cash flow: income vs. expenses vs. giving vs. investments by period
- Spending breakdown by category (chart and table)
- Budget vs. actuals
- Account balances over time
- Net worth snapshot (assets minus liabilities, manually maintained)
- Reimbursement aging report: pending reimbursements by party, outstanding amount, and days pending
- Transaction list: searchable and filterable by account, category, tag, status, date, amount, reimbursement status
- All reports filterable by account, category, and date range; tags available for ad-hoc drill-down
- Gross vs. net views where reimbursements apply

---

## 7. LLM and Parsing Stack

### 7.1 LLM Usage Policy
Use LLM where deterministic methods are insufficient or brittle. Use deterministic methods where rules are stable and auditable.

| Task | Approach |
|---|---|
| Bank alert parsing (known institution) | Deterministic (regex / template) |
| Bank alert parsing (unknown format) | LLM fallback |
| Receipt line item extraction (non-PDF) | LLM-primary |
| Receipt and statement parsing (PDF) | Docling layout extraction, then LLM on structured output |
| Merchant name normalization | Deterministic + fuzzy match; LLM for novel merchants |
| Transaction-to-receipt matching (high confidence) | Deterministic |
| Transaction-to-receipt matching (ambiguous) | LLM-assisted |
| Category inference from line items | LLM |
| Category inference from merchant name | Deterministic rules; LLM for new merchants |
| Spend cluster detection for category suggestions | LLM / ML |
| Duplicate detection | Deterministic |
| Anomaly detection (future) | ML / LLM agent |
| Financial advice (future) | LLM agent |

LLM calls must be logged, auditable, non-blocking (failures fall back to user review queue), and always user-overridable.

### 7.2 Document Parsing
- Docling used as the layout-aware parsing layer for all PDF inputs (receipts and bank statements)
- Docling output (structured tables, line items, totals) is passed to the LLM or deterministic parser rather than raw text
- Improves accuracy for columnar statement formats and itemized PDF receipts

---

## 8. Storage

MongoDB is the primary data store.

Transactions are naturally document-shaped: a transaction with its line items, tags, and links is a coherent document. Receipt parsing output, LLM extraction results, and raw email payloads vary in schema per institution and fit the document model well. Reporting queries (budget actuals, cash flow, reimbursement aging) are handled via the aggregation pipeline and operate over a dataset that is small by any measure for a single-user app. Schema flexibility also reduces friction as the data model evolves across open-source releases.

A lightweight embedded option (e.g. via Mongita or a file-backed store) may be supported in a future phase for minimal installs.

---

## 9. Self-Hosted / Open Source Requirements

- Deployable via Docker Compose (single-host target)
- Configuration via environment variables and config file
- LLM provider configurable: OpenAI, Anthropic, or local Ollama (no external LLM dependency required)
- Gmail credentials stored locally, never transmitted to third parties
- Full data export to CSV and JSON at any time

---

## 10. Non-Functional Requirements

- All user financial data encrypted at rest
- Gmail OAuth tokens stored securely, not in plaintext config
- Audit log for all data mutations
- API-first backend: all features accessible via REST API
- UI: web-based, responsive, desktop and tablet target
- All ingestion pipelines idempotent and replayable

---

## 11. Future Milestones (Out of Scope for v1)

- Investment holdings tracking: individual positions, lots, cost basis, ticker symbols, and portfolio performance
- Net worth tracking: assets minus liabilities across all account types
- Gmail read access for historical backfill and receipt import
- Import from third-party expense trackers (YNAB, Monarch, Mint)
- Anomaly detection agent: flags unusual transactions, unexpected charges, spend spikes, and overdue reimbursements
- Financial advice agent: proactive recommendations based on trends and budget performance
- Recurring transaction and subscription detection
- Multi-user / household support with per-user transaction attribution
- Mobile app or PWA
