import json

import pytest

from commands.recreate_disposable_target import main as recreate_main
from migration_toolkit.disposable_target import (
    DisposableTargetError,
    DisposableTargetOptions,
    database_name_from_url,
    database_url_with_name,
    recreate_disposable_target,
    validate_disposable_database_name,
)


def test_database_name_from_url_decodes_path():
    assert database_name_from_url("postgresql://user:pass@postgres:5432/legacy_import_trial") == "legacy_import_trial"


def test_database_url_with_name_preserves_connection_parts():
    assert (
        database_url_with_name("postgresql://user:pass@postgres:5432/target_current?sslmode=disable", "postgres")
        == "postgresql://user:pass@postgres:5432/postgres?sslmode=disable"
    )


def test_validate_disposable_database_name_requires_allowed_prefix():
    with pytest.raises(DisposableTargetError, match="must start with"):
        validate_disposable_database_name("target_current_copy")


def test_validate_disposable_database_name_refuses_protected_names():
    with pytest.raises(DisposableTargetError, match="protected database"):
        validate_disposable_database_name("postgres")


def test_validate_disposable_database_name_requires_confirmation_for_execute():
    with pytest.raises(DisposableTargetError, match="confirm-name"):
        validate_disposable_database_name("legacy_import_trial", execute=True, confirm_name="other")


def test_recreate_disposable_target_dry_run_never_connects():
    report = recreate_disposable_target(
        DisposableTargetOptions(
            target_url="postgresql://postgres:secret@postgres:5432/legacy_import_trial",
            execute=False,
        )
    )

    assert report.status == "planned"
    assert report.dry_run is True
    assert report.database_name == "legacy_import_trial"
    assert report.owner == "postgres"


def test_recreate_disposable_target_cli_renders_plan(capsys):
    assert (
        recreate_main(
            [
                "--target-url",
                "postgresql://postgres:secret@postgres:5432/legacy_import_trial",
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    data = json.loads(output)
    assert data["status"] == "planned"
    assert data["database_name"] == "legacy_import_trial"
