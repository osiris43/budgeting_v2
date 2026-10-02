from unittest.mock import patch

from app.models import StatementSourceConfig
from app.services import onepassword


def test_configure_statement_source_creates_config(app, db, account):
    runner = app.test_cli_runner(mix_stderr=False)

    result = runner.invoke(
        args=[
            "configure-statement-source",
            "--account-id", str(account.id),
            "--provider", "capital_one",
            "--username-ref", "op://Private/Capital One/username",
            "--password-ref", "op://Private/Capital One/password",
            "--statement-close-day", "12",
        ]
    )

    assert result.exit_code == 0, result.output
    assert "Stored 1Password references only" in result.output

    config = db.session.execute(
        db.select(StatementSourceConfig).where(StatementSourceConfig.account_id == account.id)
    ).scalar_one()
    assert config.provider == "capital_one"
    assert config.username_ref == "op://Private/Capital One/username"
    assert config.password_ref == "op://Private/Capital One/password"
    assert config.statement_close_day == 12
    assert config.download_dir == "data/statements"


def test_configure_statement_source_updates_existing_config(app, db, account):
    runner = app.test_cli_runner(mix_stderr=False)

    base_args = [
        "configure-statement-source",
        "--account-id", str(account.id),
        "--provider", "capital_one",
        "--username-ref", "op://Private/Capital One/username",
        "--password-ref", "op://Private/Capital One/password",
        "--statement-close-day", "12",
    ]
    assert runner.invoke(args=base_args).exit_code == 0

    result = runner.invoke(args=base_args[:-1] + ["18", "--download-dir", "data/capital-one"])

    assert result.exit_code == 0, result.output
    configs = db.session.execute(db.select(StatementSourceConfig)).scalars().all()
    assert len(configs) == 1
    assert configs[0].statement_close_day == 18
    assert configs[0].download_dir == "data/capital-one"


def test_configure_statement_source_rejects_non_op_refs(app, account):
    runner = app.test_cli_runner(mix_stderr=False)

    result = runner.invoke(
        args=[
            "configure-statement-source",
            "--account-id", str(account.id),
            "--provider", "capital_one",
            "--username-ref", "capital-one-user",
            "--password-ref", "op://Private/Capital One/password",
            "--statement-close-day", "12",
        ]
    )

    assert result.exit_code != 0


def test_check_statement_source_does_not_print_refs(app, account):
    runner = app.test_cli_runner(mix_stderr=False)
    runner.invoke(
        args=[
            "configure-statement-source",
            "--account-id", str(account.id),
            "--provider", "capital_one",
            "--username-ref", "op://Private/Capital One/username",
            "--password-ref", "op://Private/Capital One/password",
            "--statement-close-day", "12",
        ]
    )

    result = runner.invoke(args=["check-statement-source", "--account-id", str(account.id)])

    assert result.exit_code == 0, result.output
    assert "username_ref=configured" in result.output
    assert "password_ref=configured" in result.output
    assert "op://Private" not in result.output


def test_check_statement_source_resolves_refs_without_printing_values(app, account):
    runner = app.test_cli_runner(mix_stderr=False)
    runner.invoke(
        args=[
            "configure-statement-source",
            "--account-id", str(account.id),
            "--provider", "capital_one",
            "--username-ref", "op://Private/Capital One/username",
            "--password-ref", "op://Private/Capital One/password",
            "--statement-close-day", "12",
        ]
    )

    with patch("app.services.onepassword.read_secret", side_effect=["secret-user", "secret-password"]):
        result = runner.invoke(args=["check-statement-source", "--account-id", str(account.id), "--resolve-secrets"])

    assert result.exit_code == 0, result.output
    assert "1password_refs=ok" in result.output
    assert "secret-user" not in result.output
    assert "secret-password" not in result.output


def test_validate_op_ref_requires_op_scheme():
    assert onepassword.validate_op_ref("op://Private/Item/field") == "op://Private/Item/field"

    try:
        onepassword.validate_op_ref("not-secret")
    except ValueError as exc:
        assert "op://" in str(exc)
    else:
        raise AssertionError("expected ValueError")
