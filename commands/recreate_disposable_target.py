from __future__ import annotations

import argparse
from pathlib import Path

from migration_toolkit.disposable_target import (
    DEFAULT_ALLOWED_PREFIXES,
    DisposableTargetError,
    DisposableTargetOptions,
    recreate_disposable_target,
    render_report_json,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Drop and recreate an explicitly named disposable target database for migration trials."
    )
    parser.add_argument(
        "--target-url",
        default=None,
        help="PostgreSQL URL used for server credentials. Defaults to TARGET_DATABASE_URL, DATABASE_URL, or env parts.",
    )
    parser.add_argument(
        "--database-name",
        default=None,
        help="Disposable database name to recreate. Defaults to the database name in --target-url/env target URL.",
    )
    parser.add_argument(
        "--maintenance-database",
        default="postgres",
        help="Database to connect to while dropping/recreating the disposable target. Default: postgres.",
    )
    parser.add_argument(
        "--owner",
        default=None,
        help="Owner for the recreated database. Defaults to the username from the target URL.",
    )
    parser.add_argument(
        "--allowed-prefix",
        action="append",
        default=None,
        help=(
            "Allowed disposable database-name prefix. Repeat to replace defaults. "
            f"Defaults: {', '.join(DEFAULT_ALLOWED_PREFIXES)}"
        ),
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually drop and recreate the database. Without this flag the command only prints the plan.",
    )
    parser.add_argument(
        "--confirm-name",
        default=None,
        help="Required with --execute. Must exactly match the disposable database name.",
    )
    parser.add_argument("--manifest", type=Path, default=None, help="Optional JSON output path for the reset report.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parsed = parser.parse_args(argv)
    options = DisposableTargetOptions(
        target_url=parsed.target_url,
        database_name=parsed.database_name,
        maintenance_database=parsed.maintenance_database,
        owner=parsed.owner,
        allowed_prefixes=tuple(parsed.allowed_prefix or DEFAULT_ALLOWED_PREFIXES),
        execute=parsed.execute,
        confirm_name=parsed.confirm_name,
    )
    try:
        report = recreate_disposable_target(options)
    except DisposableTargetError as exc:
        parser.error(str(exc))

    rendered = render_report_json(report)
    if parsed.manifest:
        parsed.manifest.parent.mkdir(parents=True, exist_ok=True)
        parsed.manifest.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
