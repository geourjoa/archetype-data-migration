# Local Disposable Smoke Test

This procedure verifies the migration toolkit against a throwaway target database.
It is for local operator confidence before staging or production work.

The disposable database itself is not committed to this repository. Keep only the
procedure and, if useful, selected reviewed reports. The generated `reports/*.json`
files are ignored by default.

## Requirements

- Docker Desktop is running.
- The backend repo is available beside this repo, or `BACKEND_REPO` points to it.
- The backend Compose `postgres` service can see the restored legacy database.
- `LEGACY_DATABASE_NAME` or `LEGACY_DATABASE_URL` identifies the legacy source.

## Example Variables

```bash
export BACKEND_REPO=../backend
export DOCKER_BIN=/Applications/Docker.app/Contents/Resources/bin/docker
export LEGACY_DATABASE_NAME=<legacy_source_database>
export SMOKE_DB=legacy_import_toolkit_smoke_$(date +%Y%m%d_%H%M)
```

If you prefer explicit URLs, set `LEGACY_DATABASE_URL` and `TARGET_DATABASE_URL`
instead of deriving by database name.

## Create A Disposable Target

```bash
./scripts/create-target-smoke-db.sh "$SMOKE_DB"
```

Build a target URL using the same Postgres credentials as the backend Compose
stack, then run the current backend migrations into the disposable database:

```bash
export POSTGRES_PASSWORD="$(awk -F= '/POSTGRES_PASSWORD=/{print $2; exit}' "$BACKEND_REPO/compose.yaml)"
export TARGET_DATABASE_URL="postgresql://postgres:${POSTGRES_PASSWORD}@postgres:5432/${SMOKE_DB}"

"$DOCKER_BIN" compose \
  --project-directory "$BACKEND_REPO" \
  -f "$BACKEND_REPO/compose.yaml" \
  run --rm \
  -e DATABASE_URL="$TARGET_DATABASE_URL" \
  api python manage.py migrate --noinput
```

Create a fallback publication author in the disposable target:

```bash
"$DOCKER_BIN" compose \
  --project-directory "$BACKEND_REPO" \
  -f "$BACKEND_REPO/compose.yaml" \
  run --rm \
  -e DATABASE_URL="$TARGET_DATABASE_URL" \
  api python manage.py shell -c "from django.contrib.auth import get_user_model; User = get_user_model(); User.objects.get_or_create(username='legacy-import-author', defaults={'email': 'legacy-import-author@example.invalid', 'is_staff': True})"
```

## Recreate A Disposable Target

For repeat trials, recreate the disposable database instead of deleting target
table rows by hand:

```bash
TARGET_DATABASE_URL="$TARGET_DATABASE_URL" \
DOCKER_BIN="$DOCKER_BIN" \
./scripts/backend-compose-run.sh python -m commands.recreate_disposable_target \
  --database-name "$SMOKE_DB" \
  --confirm-name "$SMOKE_DB" \
  --execute \
  --manifest "reports/${SMOKE_DB}-recreate.json"
```

The command refuses normal database names by default. After it recreates the
empty database, rerun backend migrations and recreate/verify the fallback
publication author before starting the next dry run.

## Dry Run

```bash
TARGET_DATABASE_URL="$TARGET_DATABASE_URL" \
LEGACY_DATABASE_NAME="$LEGACY_DATABASE_NAME" \
DOCKER_BIN="$DOCKER_BIN" \
./scripts/backend-compose-run.sh python -m commands.migrate_legacy_data \
  --manifest reports/local-smoke-dry-run.json
```

Expected result: status `warn`, not `fail`. The warning should come from known
target-only or accepted audit warnings, not from missing tables or failed phases.

This result proves only that connections, required tables, planning queries,
phase order, and expected counts were resolved. It does not exercise inserts,
foreign keys, unique constraints, or the post-import audit. Review the planned
counts against the source before execution.

Also review `source_profile` and `source_warnings` in the dry-run report. If
the source contains text-only descriptions, unattached descriptions, or broken
allograph-character links, execute mode will stop before writing until there is
an explicit migration policy for those rows.

For a source where unsupported description rows have been reviewed and approved
for exclusion, add `--unsupported-description-policy skip` to both dry-run and
execute commands. The report will record skipped `digipal_description` rows and
write a sibling `*-skipped-descriptions.json` quarantine artifact when
`--manifest` is provided.

## Execute

```bash
TARGET_DATABASE_URL="$TARGET_DATABASE_URL" \
LEGACY_DATABASE_NAME="$LEGACY_DATABASE_NAME" \
DOCKER_BIN="$DOCKER_BIN" \
./scripts/backend-compose-run.sh python -m commands.migrate_legacy_data \
  --execute \
  --publication-author-username legacy-import-author \
  --allow-warnings \
  --manifest reports/local-smoke-import-run.json
```

Expected result:

- `core_vocabularies`: `ok`
- `symbols`: `ok`
- `manuscripts`: `ok`
- `scribes_hands`: `ok`
- `image_text`: `ok`
- `annotations`: `ok`
- `publications`: `ok`
- `target_only`: `warn` by design

The author username supplied to `--publication-author-username` must already
exist in this disposable target. If a phase fails, do not clean individual
tables and continue unless performing an explicitly documented recovery test.
Discard and recreate the disposable target so that the next trial starts from
a known empty state.

## Post-Import Audit

```bash
TARGET_DATABASE_URL="$TARGET_DATABASE_URL" \
LEGACY_DATABASE_NAME="$LEGACY_DATABASE_NAME" \
DOCKER_BIN="$DOCKER_BIN" \
./scripts/backend-compose-run.sh python -m commands.audit_legacy_migration \
  --format json \
  --publication-author-policy fallback \
  --publication-author-username legacy-import-author \
  --output reports/local-smoke-post-audit.json
```

Check the final status:

```bash
jq -r '.status' reports/local-smoke-post-audit.json
```

Expected result: `warn`, not `fail`, until all accepted migration warnings have
been resolved or explicitly signed off.

If the result is `fail`, inspect the failed mappings and checks before changing
the source or importer:

```bash
jq '{
  failed_mappings: [.mappings[] | select(.status == "fail")],
  failed_checks: [.checks[] | select(.status == "fail")]
}' reports/local-smoke-post-audit.json
```
