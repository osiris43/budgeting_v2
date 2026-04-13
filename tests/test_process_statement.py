import csv
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.models import Transaction


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


class TestProcessStatementCSV:
    def test_csv_imports_and_categorizes(self, app, db, account, categories):
        """CSV file is imported directly and then categorized."""
        csv_path = _write_csv([
            {"date": "2024-01-15", "description": "WALMART SUPERCENTER", "amount": "42.50"},
            {"date": "2024-01-16", "description": "SHELL GAS", "amount": "35.00"},
        ])

        runner = app.test_cli_runner(mix_stderr=False)

        with patch("app.services.categorization.categorize_with_ollama", return_value="Groceries"):
            result = runner.invoke(
                args=[
                    "process-statement",
                    "--account-id", str(account.id),
                    "--file", str(csv_path),
                ]
            )

        assert result.exit_code == 0, result.output
        assert "Skipping PDF conversion" in result.output
        assert "Importing CSV" in result.output
        assert "Categorizing" in result.output
        assert "=== Summary ===" in result.output
        assert "Transactions imported: 2" in result.output

    def test_csv_summary_shows_all_fields(self, app, db, account, categories):
        """Summary includes rule/model/uncategorized counts."""
        csv_path = _write_csv([
            {"date": "2024-01-15", "description": "WALMART", "amount": "42.50"},
        ])

        runner = app.test_cli_runner(mix_stderr=False)

        with patch("app.services.categorization.categorize_with_ollama", return_value="Groceries"):
            result = runner.invoke(
                args=[
                    "process-statement",
                    "--account-id", str(account.id),
                    "--file", str(csv_path),
                ]
            )

        assert result.exit_code == 0, result.output
        assert "Transactions imported: 1" in result.output
        assert "Transactions skipped:  0" in result.output
        assert "Categorized by rule:" in result.output
        assert "Categorized by model:" in result.output
        assert "Uncategorized:" in result.output

    def test_csv_nonexistent_account_fails(self, app, db):
        """Non-existent account ID causes non-zero exit."""
        csv_path = _write_csv([
            {"date": "2024-01-15", "description": "WALMART", "amount": "42.50"},
        ])

        runner = app.test_cli_runner(mix_stderr=False)
        result = runner.invoke(
            args=[
                "process-statement",
                "--account-id", "9999",
                "--file", str(csv_path),
            ]
        )

        assert result.exit_code != 0

    def test_csv_skipped_duplicates(self, app, db, account, categories):
        """Duplicate transactions are skipped on second run."""
        csv_path = _write_csv([
            {"date": "2024-01-15", "description": "WALMART", "amount": "42.50"},
        ])

        runner = app.test_cli_runner(mix_stderr=False)

        # First import
        with patch("app.services.categorization.categorize_with_ollama", return_value="Groceries"):
            runner.invoke(
                args=[
                    "process-statement",
                    "--account-id", str(account.id),
                    "--file", str(csv_path),
                ]
            )

        # Second import — same file, should skip duplicate
        with patch("app.services.categorization.categorize_with_ollama", return_value="Groceries"):
            result = runner.invoke(
                args=[
                    "process-statement",
                    "--account-id", str(account.id),
                    "--file", str(csv_path),
                ]
            )

        assert result.exit_code == 0, result.output
        assert "Transactions imported: 0" in result.output
        assert "Transactions skipped:  1" in result.output


class TestProcessStatementPDF:
    def test_pdf_converts_then_imports(self, app, db, account, categories):
        """PDF file triggers conversion, import, and categorization."""
        # Create a fake PDF file
        tmp_pdf = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp_pdf.write(b"fake pdf content")
        tmp_pdf.close()
        pdf_path = Path(tmp_pdf.name)

        csv_rows = [
            {"date": "2024-01-15", "description": "WALMART", "amount": "42.50"},
        ]

        def mock_pdfplumber_open(path):
            """Mock that writes a CSV to the out_csv_path via _write_pdf_csv."""
            raise AssertionError("Should not be called when _pdf_to_csv is patched")

        # We need to patch the _pdf_to_csv nested function. Since it's nested
        # inside register_cli, we patch pdfplumber.open and write the CSV ourselves
        # using a side_effect on the actual pdf-to-csv logic.
        # Simpler: patch at the pdfplumber level to produce known output.

        # Actually, the cleanest way: use a mock page that returns text
        # matching a known format so the parser produces a known CSV.
        # But that's complex. Instead, let's patch the function by
        # temporarily replacing pdfplumber.open.

        import pdfplumber
        original_open = pdfplumber.open

        class FakePage:
            def extract_text(self):
                return (
                    "Sam's Club Credit\n"
                    "Closing Date 01/20/2024\n"
                    "01/15 REF123 WALMART SUPERCENTER $42.50\n"
                )

        class FakePDF:
            pages = [FakePage()]

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        with patch.object(pdfplumber, "open", return_value=FakePDF()), \
             patch("app.services.categorization.categorize_with_ollama", return_value="Groceries"):
            runner = app.test_cli_runner(mix_stderr=False)
            result = runner.invoke(
                args=[
                    "process-statement",
                    "--account-id", str(account.id),
                    "--file", str(pdf_path),
                ]
            )

        assert result.exit_code == 0, result.output
        assert "Converting PDF to CSV" in result.output
        assert "Transactions imported: 1" in result.output

        txs = db.session.execute(
            db.select(Transaction).where(Transaction.account_id == account.id)
        ).scalars().all()
        assert len(txs) == 1

    def test_pdf_conversion_failure_exits_nonzero(self, app, db, account):
        """If PDF conversion fails, command exits non-zero."""
        tmp_pdf = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp_pdf.write(b"fake pdf content")
        tmp_pdf.close()
        pdf_path = Path(tmp_pdf.name)

        import pdfplumber

        with patch.object(pdfplumber, "open", side_effect=Exception("parse error")):
            runner = app.test_cli_runner(mix_stderr=False)
            result = runner.invoke(
                args=[
                    "process-statement",
                    "--account-id", str(account.id),
                    "--file", str(pdf_path),
                ]
            )

        assert result.exit_code != 0
