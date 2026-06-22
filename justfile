set dotenv-load := true

backend_repo := env_var_or_default("BACKEND_REPO", "../backend")

_default:
    just --list

# Run unit tests directly in this repo.
test:
    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest

# Run unit tests in the backend API container.
test-compose:
    BACKEND_REPO="{{backend_repo}}" ./scripts/backend-compose-run.sh env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest

# Check CLI entry points without requiring live databases.
cli-check:
    python -m commands.audit_legacy_migration --help
    python -m commands.migrate_legacy_data --help
    python -m commands.legacy_migration_procedure --help
    python -m commands.recreate_disposable_target --help
    python -m commands.legacy_migration_procedure --output /tmp/operator-guide.md --manifest-template /tmp/legacy-migration-manifest-template.json

# Render the static operator guide and manifest template.
procedure:
    BACKEND_REPO="{{backend_repo}}" ./scripts/backend-compose-run.sh python -m commands.legacy_migration_procedure --output docs/operator-guide.md --manifest-template manifests/legacy-migration-manifest-template.json

# Render the operator guide with a live read-only audit summary.
procedure-live:
    BACKEND_REPO="{{backend_repo}}" ./scripts/backend-compose-run.sh python -m commands.legacy_migration_procedure --with-live-audit --output docs/operator-guide.md --manifest-template manifests/legacy-migration-manifest-template.json

# Run the read-only migration audit and write a markdown report.
audit:
    BACKEND_REPO="{{backend_repo}}" ./scripts/backend-compose-run.sh python -m commands.audit_legacy_migration --format markdown --output reports/legacy-migration-audit.md

# Run a read-only post-import audit for a fallback publication author policy.
audit-fallback AUTHOR:
    BACKEND_REPO="{{backend_repo}}" ./scripts/backend-compose-run.sh python -m commands.audit_legacy_migration --format markdown --publication-author-policy fallback --publication-author-username "{{AUTHOR}}" --output reports/legacy-migration-post-audit.md

# Run the importer in dry-run mode only. This should be the default trial command.
dry-run-import:
    BACKEND_REPO="{{backend_repo}}" ./scripts/backend-compose-run.sh python -m commands.migrate_legacy_data --manifest reports/legacy-migration-import-dry-run.json

# Execute the importer without author.
execute-import-without-author:
    BACKEND_REPO="{{backend_repo}}" ./scripts/backend-compose-run.sh python -m commands.migrate_legacy_data --execute --allow-warnings --manifest reports/legacy-migration-import-run.json


# Execute the importer. Requires an explicit target publication author username.
execute-import AUTHOR:
    BACKEND_REPO="{{backend_repo}}" ./scripts/backend-compose-run.sh python -m commands.migrate_legacy_data --execute --publication-author-username "{{AUTHOR}}" --allow-warnings --manifest reports/legacy-migration-import-run.json

# Drop and recreate a disposable target database. Refuses normal DB names by default.
recreate-disposable-target DB:
    BACKEND_REPO="{{backend_repo}}" ./scripts/backend-compose-run.sh python -m commands.recreate_disposable_target --database-name "{{DB}}" --confirm-name "{{DB}}" --execute --manifest "reports/{{DB}}-recreate.json"

# Show CLI help for all toolkit commands.
help-commands:
    BACKEND_REPO="{{backend_repo}}" ./scripts/backend-compose-run.sh python -m commands.audit_legacy_migration --help
    BACKEND_REPO="{{backend_repo}}" ./scripts/backend-compose-run.sh python -m commands.legacy_migration_procedure --help
    BACKEND_REPO="{{backend_repo}}" ./scripts/backend-compose-run.sh python -m commands.migrate_legacy_data --help
    BACKEND_REPO="{{backend_repo}}" ./scripts/backend-compose-run.sh python -m commands.recreate_disposable_target --help
