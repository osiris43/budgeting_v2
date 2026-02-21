# Budgeting (local)

## Setup

1. Create a virtualenv and install deps:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Create `.env` from `.env.example` and ensure Ollama is running and the model is pulled.

3. Run the app:

```bash
python run.py
```
