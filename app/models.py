from datetime import datetime

from . import db


class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    institution = db.Column(db.String(200), nullable=False)
    account_type = db.Column(db.String(50), nullable=False)
    invert_csv_amounts = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    transactions = db.relationship("Transaction", back_populates="account", lazy=True)
    imports = db.relationship("StatementImport", back_populates="account", lazy=True)
    statement_source_config = db.relationship(
        "StatementSourceConfig",
        back_populates="account",
        uselist=False,
        lazy=True,
    )


class StatementSourceConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False, unique=True)
    provider = db.Column(db.String(50), nullable=False)
    username_ref = db.Column(db.String(500), nullable=False)
    password_ref = db.Column(db.String(500), nullable=False)
    statement_close_day = db.Column(db.Integer, nullable=False)
    download_dir = db.Column(db.String(500), nullable=False)
    browser_state_path = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    account = db.relationship("Account", back_populates="statement_source_config")


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    transactions = db.relationship("Transaction", back_populates="category", lazy=True)

    parent = db.relationship("Category", remote_side=[id], backref="children")


class StatementImport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False)
    filename = db.Column(db.String(500), nullable=False)
    imported_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    status = db.Column(db.String(20), nullable=False, default="pending")
    confirmed_at = db.Column(db.DateTime, nullable=True)

    account = db.relationship("Account", back_populates="imports")
    transactions = db.relationship("Transaction", back_populates="statement_import", lazy=True)


class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False)
    statement_import_id = db.Column(db.Integer, db.ForeignKey("statement_import.id"), nullable=True)

    posted_date = db.Column(db.Date, nullable=False)
    amount_cents = db.Column(db.Integer, nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="USD")

    description_raw = db.Column(db.String(2000), nullable=False)
    description_clean = db.Column(db.String(2000), nullable=True)
    merchant = db.Column(db.String(500), nullable=True)

    card_no = db.Column(db.String(50), nullable=True)
    bank_category_raw = db.Column(db.String(200), nullable=True)

    external_id = db.Column(db.String(200), nullable=True)
    fingerprint = db.Column(db.String(200), nullable=True, index=True)

    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=True)
    category_source = db.Column(db.String(20), nullable=False, default="unknown")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    account = db.relationship("Account", back_populates="transactions")
    category = db.relationship("Category", back_populates="transactions")
    statement_import = db.relationship("StatementImport", back_populates="transactions")


class MerchantRule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    pattern = db.Column(db.String(500), nullable=False)
    detail_pattern = db.Column(db.String(500), nullable=True)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    category = db.relationship("Category")

    __table_args__ = (
        db.UniqueConstraint("pattern", "detail_pattern", name="uq_rule_pattern_detail"),
    )
