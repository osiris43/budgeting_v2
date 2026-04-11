import csv
import tempfile
from datetime import date
from pathlib import Path

from app.models import Account, StatementImport, Transaction


def _write_csv(rows, fieldnames=None):
    """Write rows to a temp CSV and return the path."""
    if fieldnames is None:
        fieldnames = rows[0].keys()
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline=""
    )
    writer = csv.DictWriter(tmp, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    tmp.close()
    return Path(tmp.name)


class TestImportCsvDeduplication:
    def test_import_creates_transactions(self, app, db, account):
        csv_path = _write_csv([
            {"date": "2024-01-15", "description": "WALMART", "amount": "42.50"},
            {"date": "2024-01-16", "description": "TARGET", "amount": "18.99"},
        ])

        runner = app.test_cli_runner(mix_stderr=False)
        result = runner.invoke(
            args=["import-csv", "--account-id", str(account.id), "--csv-path", str(csv_path)]
        )

        assert result.exit_code == 0
        assert "Imported 2" in result.output

        txs = db.session.execute(
            db.select(Transaction).where(Transaction.account_id == account.id)
        ).scalars().all()
        assert len(txs) == 2

    def test_duplicate_fingerprint_skipped(self, app, db, account):
        csv_path = _write_csv([
            {"date": "2024-01-15", "description": "WALMART", "amount": "42.50"},
        ])

        runner = app.test_cli_runner(mix_stderr=False)

        # Import once
        result1 = runner.invoke(
            args=["import-csv", "--account-id", str(account.id), "--csv-path", str(csv_path)]
        )
        assert result1.exit_code == 0
        assert "Imported 1" in result1.output

        # Import again — should skip the duplicate
        result2 = runner.invoke(
            args=["import-csv", "--account-id", str(account.id), "--csv-path", str(csv_path)]
        )
        assert result2.exit_code == 0
        assert "Imported 0" in result2.output
        assert "duplicates=1" in result2.output

    def test_external_id_deduplication(self, app, db, account):
        csv_path = _write_csv([
            {
                "date": "2024-01-15",
                "description": "WALMART",
                "amount": "42.50",
                "reference number": "REF123",
            },
        ])

        runner = app.test_cli_runner(mix_stderr=False)

        runner.invoke(
            args=["import-csv", "--account-id", str(account.id), "--csv-path", str(csv_path)]
        )

        # Reimport same external_id
        result = runner.invoke(
            args=["import-csv", "--account-id", str(account.id), "--csv-path", str(csv_path)]
        )
        assert result.exit_code == 0
        assert "duplicates=1" in result.output

    def test_debit_credit_columns(self, app, db, account):
        csv_path = _write_csv([
            {"date": "2024-01-15", "description": "PURCHASE", "debit": "25.00", "credit": ""},
            {"date": "2024-01-16", "description": "REFUND", "debit": "", "credit": "10.00"},
        ])

        runner = app.test_cli_runner(mix_stderr=False)
        result = runner.invoke(
            args=["import-csv", "--account-id", str(account.id), "--csv-path", str(csv_path)]
        )

        assert result.exit_code == 0
        assert "Imported 2" in result.output

        txs = db.session.execute(
            db.select(Transaction).where(Transaction.account_id == account.id)
            .order_by(Transaction.posted_date)
        ).scalars().all()
        assert txs[0].amount_cents == 2500  # debit positive
        assert txs[1].amount_cents == -1000  # credit negative

    def test_missing_description_skipped(self, app, db, account):
        csv_path = _write_csv([
            {"date": "2024-01-15", "description": "", "amount": "42.50"},
        ])

        runner = app.test_cli_runner(mix_stderr=False)
        result = runner.invoke(
            args=["import-csv", "--account-id", str(account.id), "--csv-path", str(csv_path)]
        )

        assert result.exit_code == 0
        assert "missing_desc=1" in result.output
