import os
from unittest.mock import patch

import pytest

from app import db as _db
from app.models import Account, Category


@pytest.fixture(scope="session")
def app():
    os.environ["OLLAMA_MODEL"] = "test-model"
    os.environ["DATABASE_URL"] = "sqlite://"

    with patch("app._check_ollama"):
        from app import create_app
        application = create_app()

    application.config["TESTING"] = True

    with application.app_context():
        _db.create_all()

    yield application

    with application.app_context():
        _db.drop_all()


@pytest.fixture(autouse=True)
def _clean_tables(app):
    """Drop and recreate all tables between tests for isolation."""
    with app.app_context():
        _db.session.remove()
        _db.drop_all()
        _db.create_all()
    yield
    with app.app_context():
        _db.session.remove()


@pytest.fixture
def db(app):
    with app.app_context():
        yield _db


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def account(db):
    acct = Account(
        name="Test Checking",
        institution="Test Bank",
        account_type="checking",
    )
    db.session.add(acct)
    db.session.commit()
    return acct


@pytest.fixture
def categories(db):
    cats = {}
    for name in ["Groceries", "Gas", "Dining", "Shopping", "Income"]:
        c = Category(name=name)
        db.session.add(c)
    db.session.commit()
    for name in ["Groceries", "Gas", "Dining", "Shopping", "Income"]:
        cats[name] = db.session.execute(
            db.select(Category).where(Category.name == name)
        ).scalar_one()
    return cats
