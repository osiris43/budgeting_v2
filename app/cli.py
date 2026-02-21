from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
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

    @app.cli.command("sams-pdf-to-csv")
    @click.option("--pdf-path", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
    @click.option("--out-csv-path", type=click.Path(dir_okay=False, path_type=Path), required=True)
    def sams_pdf_to_csv(pdf_path: Path, out_csv_path: Path) -> None:
        """Extract transactions from a Sam's Club / Synchrony PDF statement into a CSV.

        The PDF statement contains multi-line transaction descriptions (e.g. ", UNLEAD") that are
        often missing from the downloaded CSV export.

        Output CSV columns:
        - date
        - reference_number
        - description
        - amount
        """

        try:
            import pdfplumber  # type: ignore
        except Exception as e:
            raise click.ClickException(
                "Missing dependency 'pdfplumber'. Install requirements.txt (or `pip install pdfplumber`) and try again."
            ) from e

        @dataclass
        class _Tx:
            posted_date: str
            reference_number: str
            description: str
            amount: str

        date_re = re.compile(r"^\s*(\d{2}/\d{2})\s+")
        amount_re = re.compile(r"(-?\$[0-9,]+\.[0-9]{2})\s*$")

        def _is_header_line(line: str) -> bool:
            s = line.strip().lower()
            return (
                not s
                or s.startswith("transaction detail")
                or s.startswith("date")
                or s.startswith("payments")
                or s.startswith("purchases and other debits")
                or s.startswith("(continued on next page")
                or s.startswith("page ")
            )

        def _parse_year_from_pdf(text: str) -> Optional[int]:
            m = re.search(r"\b(20\d{2})\b", text)
            if not m:
                return None
            try:
                return int(m.group(1))
            except ValueError:
                return None

        txs: list[_Tx] = []
        current: Optional[_Tx] = None
        statement_year: Optional[int] = None

        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                if statement_year is None:
                    statement_year = _parse_year_from_pdf(text)

                for raw_line in text.splitlines():
                    line = raw_line.rstrip()
                    if _is_header_line(line):
                        continue

                    m_date = date_re.match(line)
                    m_amt = amount_re.search(line)

                    if m_date and m_amt:
                        if current is not None:
                            txs.append(current)

                        mmdd = m_date.group(1)
                        amt = m_amt.group(1)

                        middle = line[m_date.end() : m_amt.start()].strip()
                        middle = re.sub(r"\s+", " ", middle)

                        parts = middle.split(" ", 1)
                        if len(parts) == 2:
                            reference_number, desc_part = parts[0].strip(), parts[1].strip()
                        else:
                            reference_number, desc_part = "", middle

                        if statement_year is None:
                            posted_date = mmdd
                        else:
                            month_s, day_s = mmdd.split("/")
                            posted_date = f"{statement_year:04d}-{int(month_s):02d}-{int(day_s):02d}"

                        current = _Tx(
                            posted_date=posted_date,
                            reference_number=reference_number,
                            description=desc_part,
                            amount=amt.replace("$", ""),
                        )
                        continue

                    if current is not None:
                        cont = line.strip()
                        if cont:
                            cont = re.sub(r"\s+", " ", cont)
                            current.description = f"{current.description} {cont}".strip()

        if current is not None:
            txs.append(current)

        if not txs:
            raise click.ClickException("No transactions found in PDF. If this is a scanned PDF, OCR support may be needed.")

        out_csv_path.parent.mkdir(parents=True, exist_ok=True)
        with out_csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["date", "reference_number", "description", "amount"])
            writer.writeheader()
            for tx in txs:
                writer.writerow(
                    {
                        "date": tx.posted_date,
                        "reference_number": tx.reference_number,
                        "description": tx.description,
                        "amount": tx.amount,
                    }
                )

        click.echo(f"Wrote {len(txs)} transactions to {out_csv_path}")


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
