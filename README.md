# Archetype Data Migration

This repository is the dedicated operational home for the Archetype legacy-to-current database migration.
It keeps the migration process outside the backend application while still running real database work through the backend Docker Compose runtime.

`tei_exporter/` is intentionally preserved as the existing TEI export utility and export collection. The rest of the active repository focuses on migration audit, planning, guarded import, manifests, and operator evidence.

## Repository Layout

| Path | Purpose |
| --- | --- |
| `migration_toolkit/` | Standalone Python package for audit, import, and procedure generation. |
| `commands/` | CLI entry points runnable with `python -m commands.<name>`. |
| `docs/` | Current migration guide, plan, audit notes, and target database map. |
| `manifests/` | Manifest template and operator-run metadata shape. |
| `reports/` | Generated audits/import reports. Committed only as selected evidence. |
| `scripts/` | Helpers for running the toolkit inside the backend Compose API container. |
| `tests/` | Unit tests for the toolkit and CLI wrappers. |
| `tei_exporter/` | Existing TEI exporter directory, left intact. |

## Runtime Model

For real database work, run the toolkit inside the backend API container:

```bash
BACKEND_REPO=../backend ./scripts/backend-compose-run.sh python -m commands.audit_legacy_migration --help
```

The backend checkout supplies the current Django environment, Postgres network, and dependency set. This repo supplies the migration code and reports.

Direct local Python is fine for unit tests and offline rendering, but trial/staging/production database operations should use the Compose helper.

## Configuration

Copy `.env.example` to `.env` and fill the values for your environment:

```bash
cp .env.example .env
```

Use explicit URLs for serious runs:

```text
LEGACY_DATABASE_URL=postgresql://<user>:<password>@<host>:<port>/<legacy_database>
TARGET_DATABASE_URL=postgresql://<user>:<password>@<host>:<port>/<target_database>
```

The toolkit can also derive a legacy URL from the target URL when both databases live on the same Postgres server. In that case set `LEGACY_DATABASE_NAME` and either `TARGET_DATABASE_URL` or `DATABASE_URL`.

## Source Database Compatibility

The toolkit was developed and smoke-tested against one inspected DigiPal
database snapshot. Other DigiPal installations can use the same schema while
containing different optional relationships, identifiers, vocabularies, and
historical data-quality conditions. A successful run against one source does
not prove that every DigiPal database can be imported unchanged.

Before a write trial, review the baseline audit and dry-run counts for the
specific source database. Do not silently remove source rows to make an import
pass. Record unsupported or ambiguous rows in the run manifest and agree a
mapping, quarantine, or explicitly accepted exclusion policy.

## Common Commands

```bash
just test
just procedure
just audit
just dry-run-import
just execute-import <target-author-username>
just recreate-disposable-target <disposable-db-name>
```

The commands have different purposes:

| Command | Purpose | What success means |
| --- | --- | --- |
| `just procedure` | Generate the operator guide and manifest template. | Documentation rendered; no migration was tested or executed. |
| `just audit` | Compare the current source and target contents without writing. | The audit completed and produced evidence. An empty target normally produces `fail` and a non-zero command exit because source rows are missing from the target. |
| `just dry-run-import` | Check connections, required tables, planning queries, phase order, source-profile warnings, and expected row counts. | Planning completed. Inserts, foreign keys, target constraints, and post-import equality were not tested. |
| `just execute-import USERNAME` | Write supported mappings into a fresh target and run the post-import audit. | All write phases completed and the post-import audit returned `ok` or an explicitly accepted `warn`. |

`USERNAME` must already exist in the target database as an `auth_user.username`.
It is used as the publication author or fallback author; it is not a new user
created by the migration command.

Audit status must be interpreted in context:

- Before import into an empty target, `fail` is expected for missing target rows
  and is useful as a baseline comparison. The command can therefore exit
  non-zero after successfully writing the baseline report.
- After import, `fail` is a blocker and indicates unresolved missing/extra IDs,
  invalid annotation shape, or another failed audit check.
- `warn` requires review and sign-off. `--allow-warnings` accepts reviewed
  warnings only; it never accepts `fail`.

Dry-run reports include `source_profile` and `source_warnings`. Review those
fields before executing; execution is blocked before any writes when the current
source contains unsupported description relationships, broken allograph-character
links, or a missing publication author policy.

If the publications phase intentionally uses one fallback author, run post-import
audit with the same policy so the warning records the decision instead of only
showing a legacy numeric-ID mismatch:

```bash
./scripts/backend-compose-run.sh python -m commands.audit_legacy_migration \
  --publication-author-policy fallback \
  --publication-author-username <target-author-username>
```

Unsupported description relationships default to `fail`. If text-only,
unattached, or dangling `digipal_description` rows have been reviewed and the
approved decision is to exclude them from `manuscripts_historicalitemdescription`,
run the importer with `--unsupported-description-policy skip`. The import report
then records the selected policy and skipped row counts. When `--manifest` is
provided, the importer also writes a sibling
`*-skipped-descriptions.json` quarantine artifact containing every skipped row
and its reason. Do not use this flag until those rows are reviewed and the
artifact is listed in the run manifest.

Equivalent direct Compose commands:

```bash
./scripts/backend-compose-run.sh python -m commands.legacy_migration_procedure \
  --output docs/operator-guide.md \
  --manifest-template manifests/legacy-migration-manifest-template.json

./scripts/backend-compose-run.sh python -m commands.audit_legacy_migration \
  --format markdown \
  --output reports/legacy-migration-audit.md

./scripts/backend-compose-run.sh python -m commands.migrate_legacy_data \
  --manifest reports/legacy-migration-import-dry-run.json
```

Write imports require `--execute` and should only run after backups, audit review, and manifest sign-off.

For a disposable local execute test, follow [local-smoke-test.md](docs/local-smoke-test.md). Do not commit local database dumps or generated run reports unless the team explicitly wants them preserved as reviewed evidence.

For repeated trials, prefer recreating a disposable target database rather than
manually deleting rows from target tables:

```bash
just recreate-disposable-target legacy_import_trial_YYYYMMDD
```

The helper refuses normal database names by default and requires explicit
confirmation internally. After it recreates the empty database, apply backend
Django migrations and recreate/verify the target publication author before
running the dry-run or execute importer again.

## Backend Version Contract

Every trial or production run should record:

- backend git SHA
- migration repo git SHA
- Django migration state
- source database fingerprint
- target database fingerprint
- command arguments
- dry-run versus execute mode
- pre/post row counts
- accepted warnings
- backup file names, checksums, and restore location

The manifest template in `manifests/legacy-migration-manifest-template.json` is the starting point for that record.
