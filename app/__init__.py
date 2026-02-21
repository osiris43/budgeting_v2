import os

import requests
from dotenv import load_dotenv
from flask import Flask
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()
migrate = Migrate()


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _check_ollama(ollama_base_url: str, model: str) -> None:
    try:
        resp = requests.get(f"{ollama_base_url.rstrip('/')}/api/tags", timeout=3)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        raise RuntimeError(
            "Ollama is required but is not reachable at OLLAMA_BASE_URL. "
            "Start Ollama and try again."
        ) from e

    models = payload.get("models") or []
    names = {m.get("name") for m in models if isinstance(m, dict)}
    if model not in names:
        raise RuntimeError(
            f"Required Ollama model '{model}' is not available. "
            "Pull it (e.g. `ollama pull <model>`) and try again."
        )


def create_app() -> Flask:
    load_dotenv()

    app = Flask(__name__, instance_relative_config=True)

    os.makedirs(app.instance_path, exist_ok=True)

    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev")
    default_db_path = os.path.join(app.instance_path, "budget.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "DATABASE_URL", f"sqlite:///{default_db_path}"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model = _require_env("OLLAMA_MODEL")

    _check_ollama(ollama_base_url=ollama_base_url, model=ollama_model)

    db.init_app(app)
    migrate.init_app(app, db)

    from . import models  # noqa: F401
    from .cli import register_cli

    register_cli(app)

    from .routes import bp as main_bp

    app.register_blueprint(main_bp)

    return app
