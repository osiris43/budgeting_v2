from __future__ import annotations

import csv
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional

import click
from flask import Flask

from . import db
from .models import Account, Category, StatementImport, Transaction
from .services.categorization import categorize_transactions


def register_cli(app: Flask) -> None:
    @app.cli.command("init-default-categories")
    def init_default_categories() -> None:
        defaults = [
            "Income",
            "Transfer",
            "Groceries",
            "Dining",
            "Coffee",
            "Gas",
            "Auto",
            "Shopping",
            "Entertainment",
            "Travel",
            "Utilities",
            "Rent/Mortgage",
            "Insurance",
            "Medical",
            "Education",
            "Subscriptions",
            "Fees",
            "Taxes",
            "Charity",
            "Other",
        ]

        created = 0
        for name in defaults:
            exists = db.session.execute(db.select(Category).where(Category.name == name)).scalar_one_or_none()
            if not exists:
                db.session.add(Category(name=name))
                created += 1

        db.session.commit()
        click.echo(f"Created {created} categories")

    @app.cli.command("create-account")
    @click.option("--name", required=True)
    @click.option("--institution", required=True)
    @click.option("--type", "account_type", required=True)
    def create_account(name: str, institution: str, account_type: str) -> None:
        acct = Account(name=name, institution=institution, account_type=account_type)
        db.session.add(acct)
        db.session.commit()
        click.echo(f"Created account id={acct.id}")

    @app.cli.command("import-csv")
    @click.option("--account-id", type=int, required=True)
    @click.option("--csv-path", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
    def import_csv(account_id: int, csv_path: Path) -> None:
        """Import a CSV using a very simple generic column mapping.

        This is a placeholder importer until we add institution-specific adapters.
        Required columns (case-insensitive):
        - date (or posted date)
        - description
        - amount OR debit+credit
        """

        acct = db.session.get(Account, account_id)
        if not acct:
            raise click.ClickException(f"Account {account_id} not found")

        imp = StatementImport(account_id=acct.id, filename=str(csv_path.name), imported_at=datetime.utcnow())
        db.session.add(imp)
        db.session.flush()

        with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                raise click.ClickException("CSV has no header")

            fields = {name.lower().strip(): name for name in reader.fieldnames}

            def get(row: dict, *candidates: str) -> str | None:
                for c in candidates:
                    key = fields.get(c)
                    if key and row.get(key) not in (None, ""):
                        return str(row.get(key)).strip()
                return None

            imported = 0
            skipped = 0

            for row in reader:
                date_s = get(row, "posted date", "transaction date", "date")
                desc = get(row, "description", "details", "merchant", "name")
                card_no = get(row, "card no.", "card no", "card")
                bank_category_raw = get(row, "category")

                if not date_s or not desc:
                    skipped += 1
                    continue

                amt_s = get(row, "amount")
                debit_s = get(row, "debit")
                credit_s = get(row, "credit")

                amount_cents = _parse_amount_to_cents(amt_s, debit_s, credit_s)
                posted_date = _parse_date(date_s)

                fingerprint = hashlib.sha1(
                    f"{acct.id}|{posted_date.isoformat()}|{amount_cents}|{desc}".encode("utf-8")
                ).hexdigest()[:40]

                exists = db.session.execute(
                    db.select(Transaction).where(Transaction.account_id == acct.id, Transaction.fingerprint == fingerprint)
                ).scalar_one_or_none()
                if exists:
                    skipped += 1
                    continue

                tx = Transaction(
                    account_id=acct.id,
                    statement_import_id=imp.id,
                    posted_date=posted_date,
                    amount_cents=amount_cents,
                    description_raw=desc,
                    card_no=card_no,
                    bank_category_raw=bank_category_raw,
                    fingerprint=fingerprint,
                    category_source="unknown",
                )

                db.session.add(tx)
                imported += 1

        db.session.commit()
        click.echo(f"Imported {imported} transactions; skipped {skipped}")

    @app.cli.command("categorize")
    @click.option("--account-id", type=int, required=False)
    @click.option("--limit", type=int, default=200, show_default=True)
    @click.option("--dry-run", is_flag=True, default=False)
    @click.option("--create-rules", is_flag=True, default=False)
    @click.option("--auto-create-categories", is_flag=True, default=False)
    def categorize(
        account_id: Optional[int],
        limit: int,
        dry_run: bool,
        create_rules: bool,
        auto_create_categories: bool,
    ) -> None:
        """Categorize uncategorized transactions (rules-first, then Ollama)."""

        summary = categorize_transactions(
            account_id=account_id,
            limit=limit,
            dry_run=dry_run,
            create_rules=create_rules,
            auto_create_categories=auto_create_categories,
        )

        click.echo(
            " ".join(
                [
                    f"found={summary['found']}",
                    f"categorized={summary['categorized']}",
                    f"ruled={summary['ruled']}",
                    f"modeled={summary['modeled']}",
                    f"skipped={summary['skipped']}",
                    f"created_categories={summary.get('created_categories', 0)}",
                    f"dry_run={summary['dry_run']}",
                ]
            )
        )


def _parse_amount_to_cents(amount: Optional[str], debit: Optional[str], credit: Optional[str]) -> int:
    if amount is not None:
        return _money_to_cents(amount)

    debit_cents = _money_to_cents(debit) if debit else 0
    credit_cents = _money_to_cents(credit) if credit else 0

    # Convention: spend (debit) is positive, credits (payments/refunds) are negative.
    if debit_cents and credit_cents:
        # if both present, treat as ambiguous and prioritize amount spent
        return debit_cents - credit_cents
    if debit_cents:
        return debit_cents
    if credit_cents:
        return -credit_cents

    raise click.ClickException("Missing amount/debit/credit")


def _money_to_cents(s: str) -> int:
    cleaned = s.replace("$", "").replace(",", "").strip()
    if cleaned in ("", "-"):
        return 0
    value = float(cleaned)
    return int(round(value * 100))


def _parse_date(s: str):
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise click.ClickException(f"Unrecognized date format: {s}")
