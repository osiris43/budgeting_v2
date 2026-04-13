"""Tests for route handlers."""
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


def _make_import_with_model_txs(db_session, account, category):
    """Helper: create import with model-categorized transactions."""
    imp = StatementImport(
        account_id=account.id,
        filename="test.csv",
        imported_at=datetime.utcnow(),
        status="pending",
    )
    db_session.add(imp)
    db_session.flush()

    for i, merchant in enumerate(["walmart", "target", "walmart"]):
        tx = Transaction(
            account_id=account.id,
            statement_import_id=imp.id,
            posted_date=date(2026, 3, 15),
            amount_cents=1000 + i,
            description_raw=f"{merchant.upper()} #{i}",
            description_clean=merchant,
            merchant=merchant,
            fingerprint=f"fp_{i}",
            category_id=category.id,
            category_source="model",
        )
        db_session.add(tx)

    db_session.commit()
    return imp


class TestConfirmImportRedirect:
    """POST /imports/:id/confirm redirects to promote-rules."""

    def test_confirm_redirects_to_promote_rules(self, client, account, categories):
        imp, _ = _make_import_with_tx(db.session, account)

        resp = client.post(f"/imports/{imp.id}/confirm")

        assert resp.status_code == 302
        assert f"/imports/{imp.id}/promote-rules" in resp.headers["Location"]


class TestPromoteRulesGet:
    """GET /imports/:id/promote-rules page."""

    def test_shows_model_categorized_merchants(self, client, account, categories):
        cat = categories["Groceries"]
        imp = _make_import_with_model_txs(db.session, account, cat)

        resp = client.get(f"/imports/{imp.id}/promote-rules")

        assert resp.status_code == 200
        assert b"walmart" in resp.data
        assert b"target" in resp.data

    def test_excludes_merchants_with_existing_rules(self, client, account, categories):
        cat = categories["Groceries"]
        imp = _make_import_with_model_txs(db.session, account, cat)

        # Create a rule for walmart (no detail_pattern)
        db.session.add(MerchantRule(pattern="walmart", category_id=cat.id))
        db.session.commit()

        resp = client.get(f"/imports/{imp.id}/promote-rules")

        assert resp.status_code == 200
        assert b"walmart" not in resp.data
        assert b"target" in resp.data

    def test_redirects_to_imports_when_no_promotable(self, client, account, categories):
        """If no model-categorized merchants, skip to /imports."""
        imp, _ = _make_import_with_tx(db.session, account)
        # tx has category_source='unknown', not 'model'

        resp = client.get(f"/imports/{imp.id}/promote-rules")

        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/imports")

    def test_excludes_merchants_with_detail_pattern_rules(
        self, client, account, categories
    ):
        """A merchant with only a detail_pattern rule should still be promotable."""
        cat = categories["Groceries"]
        gas = categories["Gas"]
        imp = _make_import_with_model_txs(db.session, account, cat)

        # Create a detail_pattern rule for walmart — should NOT exclude it
        db.session.add(MerchantRule(
            pattern="walmart", category_id=gas.id, detail_pattern="GAS"
        ))
        db.session.commit()

        resp = client.get(f"/imports/{imp.id}/promote-rules")

        assert resp.status_code == 200
        assert b"walmart" in resp.data


class TestPromoteRulesPost:
    """POST /imports/:id/promote-rules creates rules."""

    def test_creates_rules_for_checked_merchants(self, client, account, categories):
        cat = categories["Groceries"]
        imp = _make_import_with_model_txs(db.session, account, cat)

        resp = client.post(
            f"/imports/{imp.id}/promote-rules",
            data={
                "merchant_0": "walmart",
                "category_id_0": str(cat.id),
                "checked_0": "on",
                "merchant_1": "target",
                "category_id_1": str(cat.id),
                "checked_1": "on",
            },
        )

        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/imports")

        rules = db.session.execute(db.select(MerchantRule)).scalars().all()
        patterns = {r.pattern for r in rules}
        assert "walmart" in patterns
        assert "target" in patterns

    def test_skips_unchecked_merchants(self, client, account, categories):
        cat = categories["Groceries"]
        imp = _make_import_with_model_txs(db.session, account, cat)

        resp = client.post(
            f"/imports/{imp.id}/promote-rules",
            data={
                "merchant_0": "walmart",
                "category_id_0": str(cat.id),
                # checked_0 not present — unchecked
                "merchant_1": "target",
                "category_id_1": str(cat.id),
                "checked_1": "on",
            },
        )

        assert resp.status_code == 302
        rules = db.session.execute(db.select(MerchantRule)).scalars().all()
        patterns = {r.pattern for r in rules}
        assert "walmart" not in patterns
        assert "target" in patterns

    def test_creates_rule_with_detail_pattern(self, client, account, categories):
        cat = categories["Gas"]
        imp = _make_import_with_model_txs(db.session, account, cat)

        resp = client.post(
            f"/imports/{imp.id}/promote-rules",
            data={
                "merchant_0": "walmart",
                "category_id_0": str(cat.id),
                "checked_0": "on",
                "detail_pattern_0": "UNLEADED|GAS",
            },
        )

        assert resp.status_code == 302
        rule = db.session.execute(
            db.select(MerchantRule).where(MerchantRule.pattern == "walmart")
        ).scalar_one()
        assert rule.detail_pattern == "UNLEADED|GAS"
        assert rule.category_id == cat.id

    def test_does_not_create_duplicate_rules(self, client, account, categories):
        cat = categories["Groceries"]
        imp = _make_import_with_model_txs(db.session, account, cat)

        # Pre-existing rule
        db.session.add(MerchantRule(pattern="walmart", category_id=cat.id))
        db.session.commit()

        resp = client.post(
            f"/imports/{imp.id}/promote-rules",
            data={
                "merchant_0": "walmart",
                "category_id_0": str(cat.id),
                "checked_0": "on",
            },
        )

        assert resp.status_code == 302
        rules = db.session.execute(
            db.select(MerchantRule).where(MerchantRule.pattern == "walmart")
        ).scalars().all()
        assert len(rules) == 1
