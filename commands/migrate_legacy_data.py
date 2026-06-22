from __future__ import annotations

import argparse
from pathlib import Path
import sys

from migration_toolkit.importer import (
    DESCRIPTION_POLICIES,
    DESCRIPTION_POLICY_FAIL,
    PHASE_ORDER,
    ImportOptions,
    LegacyMigrationImportError,
    render_import_report_json,
    run_import,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Safely import supported legacy source data into a freshly migrated target database."
    )
    parser.add_argument(
        "--legacy-url",
        default=None,
        help=(
            "Legacy PostgreSQL URL. Defaults to LEGACY_DATABASE_URL, or a database named by "
            "LEGACY_DATABASE_NAME derived from --target-url, TARGET_DATABASE_URL, or DATABASE_URL."
        ),
    )
    parser.add_argument(
        "--target-url",
        default=None,
        help=(
            "Target PostgreSQL URL. Defaults to TARGET_DATABASE_URL, DATABASE_URL, or a compose-style "
            "URL from TARGET_DATABASE_NAME/POSTGRES_DB and POSTGRES_* env."
        ),
    )
    parser.add_argument(
        "--phase",
        action="append",
        choices=("all", *PHASE_ORDER),
        default=None,
        help="Import phase to run. Repeat for multiple phases. Default: all.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually write to the target database. Without this flag the command only plans the import.",
    )
    parser.add_argument(
        "--allow-non-empty-target",
        action="store_true",
        help="Allow writes when import target tables already contain rows. Use only for approved recovery work.",
    )
    parser.add_argument(
        "--allow-warnings",
        action="store_true",
        help="Allow post-import audit warnings after they have been recorded in the manifest.",
    )
    parser.add_argument(
        "--unsupported-description-policy",
        choices=DESCRIPTION_POLICIES,
        default=DESCRIPTION_POLICY_FAIL,
        help=(
            "How to handle legacy digipal_description rows that cannot become historical-item descriptions. "
            "Default: fail before writing. Use skip only after reviewing and recording those rows."
        ),
    )
    parser.add_argument(
        "--unsupported-description-output",
        type=Path,
        default=None,
        help=(
            "Optional JSON quarantine output for unsupported digipal_description rows when policy is skip. "
            "Defaults to a sibling *-skipped-descriptions.json file when --manifest is provided."
        ),
    )
    parser.add_argument(
        "--skip-post-audit",
        action="store_true",
        help="Skip the post-import audit. Intended only for partial phase testing.",
    )
    parser.add_argument("--publication-author-id", type=int, default=None, help="Target auth_user.id for publications.")
    parser.add_argument(
        "--publication-author-username",
        default=None,
        help="Target auth_user.username to assign to imported publications.",
    )
    parser.add_argument("--manifest", type=Path, default=None, help="Optional JSON output path for the import report.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    options = parser.parse_args(argv)
    import_options = ImportOptions(
        legacy_url=options.legacy_url,
        target_url=options.target_url,
        phases=tuple(options.phase or ("all",)),
        execute=options.execute,
        allow_non_empty_target=options.allow_non_empty_target,
        allow_warnings=options.allow_warnings,
        unsupported_description_policy=options.unsupported_description_policy,
        unsupported_description_output_path=options.unsupported_description_output,
        publication_author_id=options.publication_author_id,
        publication_author_username=options.publication_author_username,
        skip_post_audit=options.skip_post_audit,
        manifest_path=options.manifest,
    )
    try:
        report = run_import(import_options)
    except LegacyMigrationImportError as exc:
        parser.error(str(exc))

    print(render_import_report_json(report))
    if report.dry_run:
        print("Dry run only. Re-run with --execute to write data.", file=sys.stderr)
    elif report.status == "ok":
        print("Legacy data import completed.", file=sys.stderr)
    else:
        print(f"Legacy data import completed with status: {report.status}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
