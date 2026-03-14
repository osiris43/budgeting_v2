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
    @click.option("--invert-csv-amounts", is_flag=True, default=False)
    def create_account(name: str, institution: str, account_type: str, invert_csv_amounts: bool) -> None:
        acct = Account(
            name=name,
            institution=institution,
            account_type=account_type,
            invert_csv_amounts=invert_csv_amounts,
        )
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

            looks_like_anbtx_export = all(
                k in fields
                for k in [
                    "date",
                    "description",
                    "comments",
                    "check number",
                    "amount",
                    "balance",
                ]
            )

            if looks_like_anbtx_export and not getattr(acct, "invert_csv_amounts", False):
                click.echo(
                    "Warning: CSV looks like an ANBTX export (deposits positive / withdrawals negative). "
                    "Consider setting account.invert_csv_amounts (create-account --invert-csv-amounts) to map into app convention."
                )

            def get(row: dict, *candidates: str) -> str | None:
                for c in candidates:
                    key = fields.get(c)
                    if key and row.get(key) not in (None, ""):
                        return str(row.get(key)).strip()
                return None

            def normalize_desc_for_fingerprint(s: str) -> str:
                s = (s or "").lower().strip()
                s = re.sub(r"\s+", " ", s)
                s = re.sub(r"\b\d{6,}\b", "", s)
                s = re.sub(r"\s+", " ", s).strip()
                return s

            imported = 0
            skipped = 0
            skipped_missing_date = 0
            skipped_missing_desc = 0
            skipped_missing_amount = 0
            skipped_duplicate = 0
            sample_duplicates: list[str] = []

            for row in reader:
                date_s = get(row, "posted date", "transaction date", "date")
                desc = get(row, "description", "details", "merchant", "name")
                comments = get(row, "comments", "memo")
                check_no = get(row, "check number", "check #", "check")
                card_no = get(row, "card no.", "card no", "card")
                bank_category_raw = get(row, "category")
                external_id = get(
                    row,
                    "reference number",
                    "reference",
                    "ref",
                    "transaction id",
                    "transaction_id",
                    "fitid",
                    "id",
                )

                if not date_s:
                    skipped_missing_date += 1
                    skipped += 1
                    continue

                if not desc:
                    if check_no:
                        desc = f"Check {check_no}"
                    else:
                        skipped_missing_desc += 1
                        skipped += 1
                        continue

                if comments:
                    desc = re.sub(r"\s+", " ", f"{desc} {comments}").strip()

                amt_s = get(row, "amount")
                debit_s = get(row, "debit")
                credit_s = get(row, "credit")

                if amt_s is None and debit_s is None and credit_s is None:
                    skipped_missing_amount += 1
                    skipped += 1
                    continue

                amount_cents = _parse_amount_to_cents(amt_s, debit_s, credit_s)
                if getattr(acct, "invert_csv_amounts", False):
                    amount_cents = -amount_cents
                posted_date = _parse_date(date_s)

                if external_id:
                    ext_exists = db.session.execute(
                        db.select(Transaction).where(
                            Transaction.account_id == acct.id,
                            Transaction.external_id == external_id,
                        )
                    ).scalar_one_or_none()
                    if ext_exists:
                        skipped_duplicate += 1
                        if len(sample_duplicates) < 5:
                            sample_duplicates.append(
                                f"external_id={external_id} {posted_date.isoformat()} {amount_cents/100:.2f} {desc}"
                            )
                        skipped += 1
                        continue

                desc_norm = normalize_desc_for_fingerprint(desc)
                fingerprint = hashlib.sha1(
                    f"{acct.id}|{posted_date.isoformat()}|{amount_cents}|{desc_norm}".encode("utf-8")
                ).hexdigest()[:40]

                exists = db.session.execute(
                    db.select(Transaction).where(Transaction.account_id == acct.id, Transaction.fingerprint == fingerprint)
                ).scalar_one_or_none()
                if exists:
                    skipped_duplicate += 1
                    if len(sample_duplicates) < 5:
                        sample_duplicates.append(
                            f"{posted_date.isoformat()} {amount_cents/100:.2f} {desc}"
                        )
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
                    external_id=external_id,
                    fingerprint=fingerprint,
                    category_source="unknown",
                )

                db.session.add(tx)
                imported += 1

        db.session.commit()
        click.echo(
            " ".join(
                [
                    f"Imported {imported} transactions; skipped {skipped}",
                    f"(duplicates={skipped_duplicate}",
                    f"missing_date={skipped_missing_date}",
                    f"missing_desc={skipped_missing_desc}",
                    f"missing_amount={skipped_missing_amount})",
                ]
            )
        )
        if sample_duplicates:
            click.echo("Sample duplicates:")
            for s in sample_duplicates:
                click.echo(f"- {s}")

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

    def _write_pdf_csv(*, out_csv_path: Path, rows: list[dict]) -> None:
        if not rows:
            raise click.ClickException("No transactions found in PDF. If this is a scanned PDF, OCR support may be needed.")

        out_csv_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = ["date", "reference_number", "description", "amount"]
        with out_csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k, "") for k in fieldnames})

        click.echo(f"Wrote {len(rows)} transactions to {out_csv_path}")

    def _parse_year_from_text(text: str) -> Optional[int]:
        m = re.search(r"\b(20\d{2})\b", text)
        if not m:
            return None
        try:
            return int(m.group(1))
        except ValueError:
            return None

    def _parse_period_end_from_text(text: str) -> Optional[tuple[int, int]]:
        m = re.search(r"Statement Period\s+(\d{2})/(\d{2})/(\d{2})\s*-\s*(\d{2})/(\d{2})/(\d{2})", text)
        if not m:
            return None
        end_mm = int(m.group(4))
        end_yy = int(m.group(6))
        end_year = 2000 + end_yy
        return end_year, end_mm

    def _parse_closing_date_from_text(text: str) -> Optional[tuple[int, int]]:
        # Synchrony statements often include a closing/ending date like:
        # "Closing Date 01/20/2026" or "Statement Closing Date: 01/20/26"
        m = re.search(
            r"(closing date|statement closing date|statement ending)\s*[:#-]?\s*(\d{2})/(\d{2})/(\d{2,4})",
            text,
            re.IGNORECASE,
        )
        if not m:
            return None
        end_mm = int(m.group(2))
        yy = int(m.group(4))
        end_year = yy if yy >= 1000 else 2000 + yy
        return end_year, end_mm

    def _parse_synchrony_sams(*, pdf, first_page_text: str) -> list[dict]:
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

        txs: list[_Tx] = []
        current: Optional[_Tx] = None
        closing = _parse_closing_date_from_text(first_page_text)
        if closing is None:
            closing = _parse_period_end_from_text(first_page_text)
        statement_year: Optional[int] = _parse_year_from_text(first_page_text)

        for page in pdf.pages:
            text = page.extract_text() or ""
            if statement_year is None:
                statement_year = _parse_year_from_text(text)

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
                        mm_i = int(month_s)
                        dd_i = int(day_s)
                        year = statement_year
                        if closing is not None:
                            end_year, end_month = closing
                            year = end_year - 1 if mm_i > end_month else end_year
                        posted_date = f"{year:04d}-{mm_i:02d}-{dd_i:02d}"

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
                        cont_low = cont.lower()
                        if cont_low.startswith("total fees") or cont_low.startswith("total interest"):
                            continue
                        cont = re.sub(r"\s+", " ", cont)
                        current.description = f"{current.description} {cont}".strip()

        if current is not None:
            txs.append(current)

        return [
            {
                "date": t.posted_date,
                "reference_number": t.reference_number,
                "description": t.description,
                "amount": t.amount,
            }
            for t in txs
        ]

    def _parse_barclays(*, pdf, first_page_text: str) -> list[dict]:
        period_end = _parse_period_end_from_text(first_page_text)

        tx_line_re = re.compile(
            r"^\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s+"
            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s+"
            r"(.+?)\s+(N/A|[0-9,]+)\s+(-?\$[0-9,]+\.[0-9]{2})\s*$",
            re.IGNORECASE,
        )

        month_map = {
            "JAN": 1,
            "FEB": 2,
            "MAR": 3,
            "APR": 4,
            "MAY": 5,
            "JUN": 6,
            "JUL": 7,
            "AUG": 8,
            "SEP": 9,
            "OCT": 10,
            "NOV": 11,
            "DEC": 12,
        }

        def _to_iso(mm_str: str, dd_str: str) -> str:
            mm = month_map.get(mm_str.upper()[:3])
            try:
                dd = int(dd_str)
            except ValueError:
                return f"{mm_str} {dd_str}".strip()
            if not mm:
                return f"{mm_str} {dd_str}".strip()

            if period_end is None:
                year = datetime.utcnow().year
            else:
                end_year, end_month = period_end
                year = end_year - 1 if mm > end_month else end_year
            return f"{year:04d}-{mm:02d}-{dd:02d}"

        rows: list[dict] = []
        in_transactions = False

        for page in pdf.pages:
            text = page.extract_text() or ""
            for raw_line in text.splitlines():
                line = raw_line.rstrip()
                s = line.strip()
                s_low = s.lower()
                if not s:
                    continue

                if s_low == "transactions":
                    in_transactions = True
                    continue
                if s_low.startswith("fees and interest"):
                    in_transactions = False
                    continue
                if not in_transactions:
                    continue
                if s_low.startswith("transaction date"):
                    continue
                if s_low.startswith("total "):
                    continue
                if s_low.startswith("purchase activity"):
                    continue

                m = tx_line_re.match(line)
                if not m:
                    continue

                post_mm, post_dd = m.group(3), m.group(4)
                desc = m.group(5).strip()
                amt = m.group(7)

                rows.append(
                    {
                        "date": _to_iso(post_mm, post_dd),
                        "reference_number": "",
                        "description": desc,
                        "amount": amt.replace("$", ""),
                    }
                )

        return rows

    def _detect_pdf_kind(first_page_text: str) -> str:
        t = (first_page_text or "").lower()
        if "samsclubcredit.com" in t or "sam's club" in t or "sam\u2019s club" in t or "synchrony" in t:
            return "sams"
        if "barclays" in t or "wyndham rewards" in t:
            return "barclays"
        return "unknown"

    def _pdf_to_csv(*, pdf_path: Path, out_csv_path: Path, fmt: str) -> None:
        try:
            import pdfplumber  # type: ignore
        except Exception as e:
            raise click.ClickException(
                "Missing dependency 'pdfplumber'. Install requirements.txt (or `pip install pdfplumber`) and try again."
            ) from e

        with pdfplumber.open(str(pdf_path)) as pdf:
            first_page_text = (pdf.pages[0].extract_text() or "") if pdf.pages else ""

            chosen = fmt
            if chosen == "auto":
                chosen = _detect_pdf_kind(first_page_text)

            if chosen == "sams":
                rows = _parse_synchrony_sams(pdf=pdf, first_page_text=first_page_text)
            elif chosen == "barclays":
                rows = _parse_barclays(pdf=pdf, first_page_text=first_page_text)
            else:
                kind = _detect_pdf_kind(first_page_text)
                raise click.ClickException(
                    f"Unsupported PDF (detected={kind}). Use --format sams or --format barclays (or add a new parser)."
                )

        _write_pdf_csv(out_csv_path=out_csv_path, rows=rows)

    @app.cli.command("pdf-to-csv")
    @click.option("--pdf-path", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
    @click.option("--out-csv-path", type=click.Path(dir_okay=False, path_type=Path), required=True)
    @click.option(
        "--format",
        "fmt",
        type=click.Choice(["auto", "sams", "barclays"], case_sensitive=False),
        default="auto",
        show_default=True,
    )
    def pdf_to_csv(pdf_path: Path, out_csv_path: Path, fmt: str) -> None:
        """Convert a statement PDF into a normalized CSV for importing.

        Supports:
        - Synchrony / Sam's Club statements
        - Barclays statements

        Output CSV columns:
        - date
        - reference_number
        - description
        - amount
        """

        _pdf_to_csv(pdf_path=pdf_path, out_csv_path=out_csv_path, fmt=fmt.lower())

    @app.cli.command("sams-pdf-to-csv")
    @click.option("--pdf-path", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
    @click.option("--out-csv-path", type=click.Path(dir_okay=False, path_type=Path), required=True)
    def sams_pdf_to_csv(pdf_path: Path, out_csv_path: Path) -> None:
        _pdf_to_csv(pdf_path=pdf_path, out_csv_path=out_csv_path, fmt="sams")

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
