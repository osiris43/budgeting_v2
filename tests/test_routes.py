"""Tests for route handlers — focused on inline category save (US-003)."""
from datetime import date, datetime

from app import db
from app.models import (
    Account, Category, MerchantRule, StatementImport, Transaction,
)


def _make_import_with_tx(db_session, account, category=None):
    """Helper: create a StatementImport with one transaction."""
    imp = StatementImport(
        account_id=account.id,
        filename="test.csv",
        imported_at=datetime.utcnow(),
        status="pending",
    )
    db_session.add(imp)
    db_session.flush()

    tx = Transaction(
        account_id=account.id,
        statement_import_id=imp.id,
        posted_date=date(2026, 3, 15),
        amount_cents=1234,
        description_raw="SAMS CLUB #123",
        description_clean="sams club",
        merchant="sams club",
        fingerprint="abc123",
        category_id=category.id if category else None,
        category_source="unknown",
    )
    db_session.add(tx)
    db_session.commit()
    return imp, tx


class TestSetImportTransactionCategoryJSON:
    """XHR-based inline category save returns JSON."""

    def test_xhr_returns_json(self, client, account, categories):
        imp, tx = _make_import_with_tx(db.session, account)
        cat = categories["Groceries"]

        resp = client.post(
            f"/imports/{imp.id}/transactions/{tx.id}/set-category",
            data={"category_id": str(cat.id)},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["tx_id"] == tx.id
        assert data["category_id"] == cat.id
        assert data["category_name"] == "Groceries"
        assert data["category_source"] == "manual"

    def test_xhr_with_create_rule(self, client, account, categories):
        imp, tx = _make_import_with_tx(db.session, account)
        cat = categories["Gas"]

        resp = client.post(
            f"/imports/{imp.id}/transactions/{tx.id}/set-category",
            data={"category_id": str(cat.id), "create_rule": "on"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["category_name"] == "Gas"

        rule = db.session.execute(
            db.select(MerchantRule).where(
                MerchantRule.pattern == "sams club"
            )
        ).scalar_one_or_none()
        assert rule is not None
        assert rule.category_id == cat.id

    def test_non_xhr_redirects(self, client, account, categories):
        imp, tx = _make_import_with_tx(db.session, account)
        cat = categories["Dining"]

        resp = client.post(
            f"/imports/{imp.id}/transactions/{tx.id}/set-category",
            data={"category_id": str(cat.id)},
        )

        assert resp.status_code == 302
        assert f"/imports/{imp.id}" in resp.headers["Location"]

    def test_xhr_missing_category_returns_400(self, client, account, categories):
        imp, tx = _make_import_with_tx(db.session, account)

        resp = client.post(
            f"/imports/{imp.id}/transactions/{tx.id}/set-category",
            data={},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        assert resp.status_code == 400

    def test_xhr_invalid_tx_returns_404(self, client, account, categories):
        imp, tx = _make_import_with_tx(db.session, account)
        cat = categories["Groceries"]

        resp = client.post(
            f"/imports/{imp.id}/transactions/99999/set-category",
            data={"category_id": str(cat.id)},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        assert resp.status_code == 404
