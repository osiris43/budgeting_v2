# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # then configure OLLAMA_BASE_URL, OLLAMA_MODEL, etc.
flask db upgrade
flask init-default-categories
```

Requires a running [Ollama](https://ollama.ai) instance for AI categorization (`ollama pull llama3.2:3b`), but app startup and migrations do not require Ollama unless `CHECK_OLLAMA_ON_STARTUP=1`.

## Common Commands

```bash
# Run dev server
python run.py

# Database migrations
flask db migrate -m "description"
flask db upgrade

# Lint
ruff check .

# Import a CSV statement
flask import-csv --account-id <id> --csv-path <path>

# Categorize uncategorized transactions
flask categorize [--limit 500] [--dry-run] [--create-rules]

# Process a statement end-to-end (PDF or CSV → import → categorize)
flask process-statement --account-id <id> --file <path>

# Convert PDF statement to CSV
flask pdf-to-csv --pdf-path <path> --out-csv-path <path> --format auto
```

## Architecture

This is a personal budgeting app: **import statements → normalize/deduplicate → categorize → visualize**.

### Key layers

- **`app/cli.py`** — All data ingestion: `import-csv`, `pdf-to-csv`, `categorize`. This is the heaviest file; CSV import handles multiple formats and SHA1 fingerprint-based deduplication.
- **`app/routes.py`** — Flask views for accounts, transactions, imports review, categories, and spending analysis (Plotly charts).
- **`app/services/`**
  - `categorization.py` — Rules-first categorization with Ollama LLM fallback; handles dry-run, rule creation, category auto-creation.
  - `normalization.py` — Cleans raw descriptions and extracts merchant name.
  - `ollama_client.py` — Calls Ollama `/api/generate` with structured prompts; parses JSON or falls back to pattern matching.
- **`app/models.py`** — 5 models: `Account`, `Transaction`, `Category` (hierarchical), `StatementImport`, `MerchantRule`.

### Data model notes

- Amounts stored as **integer cents** (`amount_cents`) to avoid floating-point issues.
- `Transaction.fingerprint` is a SHA1 hash used for deduplication on import.
- `category_source` tracks how a transaction was categorized: `rule`, `model`, `manual`, or `unknown`.
- `Category` is self-referential (`parent_id`) for hierarchical budgets.

### PDF parsing

`pdf-to-csv` auto-detects statement format (Sam's Club/Synchrony, Barclays) or accepts `--format` override. Parsers live inline in `cli.py`.

### Environment variables

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | SQLite path (default: `sqlite:///budget.db`) |
| `OLLAMA_BASE_URL` | Ollama API URL |
| `OLLAMA_MODEL` | Model name for categorization commands (e.g., `llama3.2:3b`) |
| `CHECK_OLLAMA_ON_STARTUP` | Optional startup validation; set to `1` to require Ollama at app boot |
| `SECRET_KEY` | Flask session key |
