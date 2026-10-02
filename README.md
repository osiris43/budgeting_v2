# Budgeting (local)

## Setup

### 1) Python + dependencies

Create a virtualenv and install deps:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) Environment variables (`.env`)

Create a `.env` file from `.env.example`:

```bash
cp .env.example .env
```

Key variables:

- `SECRET_KEY`: Flask secret key (dev default is fine locally)
- `DATABASE_URL`: SQLAlchemy database URL
  - Recommended local default is SQLite in `instance/` (the app will default to `instance/budget.db` if `DATABASE_URL` is not set)
- `OLLAMA_BASE_URL`: where Ollama is running (default `http://localhost:11434`)
- `OLLAMA_MODEL`: required for categorization commands (e.g. `llama3.2:3b`)
- `CHECK_OLLAMA_ON_STARTUP`: optional; set to `1` to fail app startup unless Ollama is reachable
- `FLASK_APP`: set to `run.py` (enables `flask ...` commands)

Ollama must be running and the configured model must already be pulled before running categorization commands:

```bash
ollama pull llama3.2:3b
```

### 3) Database migrations

Apply migrations:

```bash
flask db upgrade
```

If you change models and need a new migration:

```bash
flask db migrate -m "describe change"
flask db upgrade
```

### 4) Run the app

```bash
python run.py
```

Or:

```bash
flask run
```

## Workflow (current)

### Import + review

1. Create accounts (one per bank/credit card export source)
2. Import CSV statements into an account
3. Categorize uncategorized transactions (rules-first, then Ollama)
4. Review/confirm imports in the UI

## Common Flask workflows

### Run development server

```bash
flask run
```

### Open a Flask shell

```bash
flask shell
```

### Apply migrations after pulling new code

```bash
flask db upgrade
```

## Existing CLI commands

This app registers several commands under `flask ...`.

### Categories

```bash
flask init-default-categories
```

### Accounts

```bash
flask create-account --name "Chase Checking" --institution "Chase" --type "checking"
```

### Statement source credentials

Statement automation stores 1Password references only, not raw credential values:

```bash
flask configure-statement-source \
  --account-id 1 \
  --provider capital_one \
  --username-ref "op://Private/Capital One/username" \
  --password-ref "op://Private/Capital One/password" \
  --statement-close-day 12

flask check-statement-source --account-id 1
flask check-statement-source --account-id 1 --resolve-secrets
```

### Import CSV

```bash
flask import-csv --account-id 1 --csv-path /path/to/statement.csv
```

### Categorize transactions

```bash
flask categorize --limit 500
flask categorize --account-id 1 --limit 500
flask categorize --dry-run
flask categorize --create-rules
flask categorize --auto-create-categories
```

### PDF statement to CSV

Convert a statement PDF into a normalized CSV that is better suited for importing and categorization.

```bash
flask pdf-to-csv --pdf-path data/statement.pdf --out-csv-path data/statement.csv
```

Auto-detection supports:

- Synchrony / Sam's Club statements
- Barclays statements

If auto-detection fails, you can force a parser:

```bash
flask pdf-to-csv --format sams --pdf-path data/sams_statement.pdf --out-csv-path data/sams_statement.csv
flask pdf-to-csv --format barclays --pdf-path barclays_0226.pdf --out-csv-path data/barclays_0226.csv
```

The output CSV contains:

- `date`
- `reference_number`
- `description`
- `amount`

`flask sams-pdf-to-csv` is kept as a backwards-compatible alias for the Sam's/Synchrony parser.
