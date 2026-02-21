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
- `OLLAMA_MODEL`: required (e.g. `llama3.2:3b`)
- `FLASK_APP`: set to `run.py` (enables `flask ...` commands)

Ollama must be running and the configured model must already be pulled (example):

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

### Sam's Club / Synchrony PDF statement to CSV

This converts a statement PDF into a CSV that contains the fuller multi-line descriptions from the statement.

```bash
flask sams-pdf-to-csv --pdf-path data/sams_statement.pdf --out-csv-path data/sams_statement.csv
```

The output CSV contains:

- `date`
- `reference_number`
- `description`
- `amount`
