# Legacy Migration Operator Guide

Procedure version: `2026-06-16`

This is the operational wrapper around the database map, migration plan, and read-only audit. It is designed for deployment runbooks, safe trial imports, and final migration evidence.

The current safe position is deliberate: generate instructions, run preflight checks, plan the import, write a manifest, execute only with explicit flags, and audit the result.

## Source Artifacts

- `docs/database-map.md`: target schema map and current row counts.
- `docs/legacy-migration-plan.md`: mapping policy and risk notes.
- `docs/legacy-migration-audit.md`: checked-in live comparison snapshot.
- `migration_toolkit/audit.py`: read-only audit/check engine.
- `migration_toolkit/procedure.py`: this operator procedure definition.
- `migration_toolkit/importer.py`: guarded write importer used by `migrate_legacy_data`.

## Deployment Rule

This migration should be a manual deployment lane, not an automatic step on every deploy. The automatic deploy can run tests and the read-only audit; the write importer should require explicit environment variables, approvals, backups, and a filled manifest.

## Command Semantics

- `legacy_migration_procedure` renders instructions and a manifest template; it does not test an import.
- `audit_legacy_migration` compares source and target contents without writing. Against a fresh empty target, `fail` and a non-zero exit are normally expected because source rows are missing from the target; the generated report is still the useful baseline evidence.
- `migrate_legacy_data` without `--execute` validates connections, tables, planning queries, phase order, and planned counts. It does not test inserts or target constraints.
- `migrate_legacy_data --execute` writes supported mappings and then runs the post-import audit.
- A post-import `fail` is a blocker. `--allow-warnings` accepts reviewed warnings only and never accepts `fail`.
- `--publication-author-username` must name an existing target `auth_user`; the importer does not create that user.

## Source Database Variability

DigiPal databases can share a schema while containing different identifiers, optional relationships, vocabularies, and data-quality cases. The checked-in audit describes one inspected source snapshot, not every DigiPal installation. Review every new source independently and do not silently remove rows to make an import pass.

Legacy `digipal_description` rows may refer to a historical item or to a text. The current importer supports historical-item descriptions. Text-only descriptions and rows linked to neither entity require an explicit mapping, quarantine, or approved exclusion policy before execution.

## Safety Gates

| Gate | Rule | Evidence |
| --- | --- | --- |
| Run through Docker Compose | Run backend migration commands in the Compose API container, not host Python. | Command log shows docker compose run/exec for every DB operation. |
| Backups before writes | Create verified custom-format dumps of legacy and target databases before any write importer runs. | Manifest records dump filenames, checksums, sizes, and storage location. |
| Refuse same source and target | The legacy URL and target URL must resolve to different database names. | Preflight/audit exits before import when the names match. |
| Read-only audit gate | Run audit_legacy_migration before and after import. An empty-target baseline normally fails for missing target rows; after import, fail is a blocker and warnings require sign-off. | Manifest stores baseline and post-import audit paths, statuses, and accepted warnings. |
| Empty target by default | Run the write importer only against a freshly migrated target DB unless explicitly approved. | Preflight row-count report is attached to the manifest. |
| Publication author policy | Do not map publication authors by legacy numeric id. Use username/email mapping or a fallback author. | Manifest records the chosen author policy and sample resolved posts. |
| Transaction per phase | Each import phase must be atomic and independently auditable. | Manifest records phase start/end time, status, row counts, and rollback reference. |
| Reset sequences after explicit ids | Run sequence synchronization after id-preserving imports and before application writes resume. | Manifest records just sync-sequences output or equivalent SQL result. |
| Target-only data is not legacy data | Create current-only workflow/product rows only from current-system sources, never by guessing legacy source data. | Manifest records skipped target-only tables or the approved current-system source for each. |

## Phase Overview

| Phase | Objective | Source | Target |
| --- | --- | --- | --- |
| `00_preflight` Preflight | Confirm environment, database URLs, schema state, table availability, and target readiness. | legacy source public schema | Django migration table, current public schema |
| `01_backups` Backups And Restore Point | Create restorable source and target snapshots before trial or production imports. | legacy source database | target database |
| `02_users_authors` Users And Publication Authors | Define the identity policy required before publication rows can be imported safely. | auth_user, blog_blogpost | auth_user, publications_publication |
| `03_core_vocabularies` Core Vocabularies | Import stable shared vocabularies before dependent manuscript rows. | digipal_date, digipal_format, digipal_source, digipal_repository | common_date, manuscripts_itemformat, manuscripts_bibliographicsource, manuscripts_repository |
| `04_symbols` Symbol Structure | Import characters, allographs, components, features, and positions before graph annotations. | digipal_character, digipal_allograph, digipal_component, digipal_feature, digipal_aspect | symbols_structure_character, symbols_structure_allograph, symbols_structure_component, symbols_structure_feature, symbols_structure_position |
| `05_manuscripts` Manuscripts And Images | Import manuscript hierarchy and IIIF-backed item images. | digipal_currentitem, digipal_historicalitem, digipal_description, digipal_cataloguenumber, digipal_itempart, digipal_itempartitem, digipal_image | manuscripts_currentitem, manuscripts_historicalitem, manuscripts_historicalitemdescription, manuscripts_cataloguenumber, manuscripts_itempart, manuscripts_itemimage |
| `06_scribes_hands` Scribes And Hands | Import scribes, hands, and image-hand links after item parts and images exist. | digipal_scribe, digipal_script, digipal_hand, digipal_hand_images | scribes_scribe, scribes_script, scribes_hand, scribes_hand_item_part_images |
| `07_image_text` Image Text | Import non-empty transcription/translation XML as target image text rows. | digipal_text_textcontentxml | manuscripts_imagetext |
| `08_annotations` Annotations And Graph Details | Import image/text/editorial annotations and graph through tables after symbols, hands, and images. | digipal_annotation, digipal_graph, digipal_idiograph, digipal_graphcomponent, digipal_graphcomponent_features, digipal_graph_aspects | annotations_graph, annotations_graphcomponent, annotations_graphcomponent_features, annotations_graph_positions |
| `09_publications` Publications And Carousel | Import public CMS records represented in the current application. | blog_blogpost, blog_blogpost_categories, digipal_carouselitem | publications_publication, publications_publication_keywords, publications_carouselitem |
| `10_target_only` Target-Only Current Data | Handle current-only tables without inventing unsupported legacy source mappings. | current-system sources only | common_editevent, manuscripts_historicalitemdateassessment, manuscripts_statustransition, worksets_workset |
| `11_final_validation` Final Validation | Prove the imported target is internally consistent and application-ready. | all mapped legacy tables | all target domain tables |
| `12_cutover` Deployment Cutover | Promote the validated target database as a deliberate deployment operation. | validated target database | production target database |

## Phase Details

### `00_preflight` Preflight

Confirm environment, database URLs, schema state, table availability, and target readiness.

Importer contract:
- Verify legacy and target URLs are present and point to different databases.
- Run and preserve the read-only baseline audit before any write step.
- Profile source-specific optional relationships and data-quality cases before execution.
- Collect target migration state and current domain row counts.
- Stop if the target is non-empty unless an explicit audit/update mode is approved.

Validation:
- audit_legacy_migration completes and its expected empty-target failures are understood.
- showmigrations reports all expected target migrations applied.
- Manifest contains operator, environment, source dump, target dump, and approval fields.

Rollback: No rollback needed; this phase must be read-only.

### `01_backups` Backups And Restore Point

Create restorable source and target snapshots before trial or production imports.

Importer contract:
- Create pg_dump custom-format dumps for legacy and target databases.
- Record sha256 checksums and byte sizes in the manifest.
- Store dumps outside the live Postgres Docker volume.

Validation:
- pg_restore --list succeeds for every dump.
- Checksums in the manifest match the stored files.

Rollback: Restore the target dump with pg_restore after dropping/recreating the target DB.

### `02_users_authors` Users And Publication Authors

Define the identity policy required before publication rows can be imported safely.

Importer contract:
- Map legacy users by username/email, or select one explicit fallback author.
- Do not rely on numeric legacy auth_user ids in a fresh target.
- Record original legacy username/email where the fallback author is used.

Validation:
- Publication author audit warning is either eliminated or explicitly accepted.
- Sample migrated publication authors resolve to expected target users.

Rollback: Delete imported publications for the phase or restore the target backup.

### `03_core_vocabularies` Core Vocabularies

Import stable shared vocabularies before dependent manuscript rows.

Importer contract:
- Preserve ids where the audit says ids are preserved.
- Keep target-only date seed rows documented and do not overwrite them.
- Apply repository label/type/place transformations explicitly.

Validation:
- Audit mappings for dates, item formats, sources, and repositories match accepted warnings.
- Foreign key lookups used by manuscript phases resolve.

Rollback: Delete rows imported by this phase after dependent phases are rolled back, or restore backup.

### `04_symbols` Symbol Structure

Import characters, allographs, components, features, and positions before graph annotations.

Importer contract:
- Preserve ids for direct vocabularies.
- Create symbol placeholder rows only when a source-specific policy requires them.
- Skip known stale/duplicate rows only when listed in the accepted audit warnings.

Validation:
- Unique allograph/component/position constraints pass.
- Audit mappings for symbol tables are ok or match accepted warnings.

Rollback: Delete symbol rows only before annotations are imported, or restore backup.

### `05_manuscripts` Manuscripts And Images

Import manuscript hierarchy and IIIF-backed item images.

Importer contract:
- Preserve ids for current items, historical items, descriptions, catalogue numbers, item parts, and images.
- Create the documented -1 item-part placeholder only if needed.
- Validate shortened shelfmark/current locus fields before insert.

Validation:
- All manuscript foreign keys are valid.
- Item image counts match the audit.
- Sample IIIF image paths resolve in the application.

Rollback: Delete imported manuscript rows in reverse dependency order or restore target backup.

### `06_scribes_hands` Scribes And Hands

Import scribes, hands, and image-hand links after item parts and images exist.

Importer contract:
- Preserve ids for scribes, scripts, hands, and hand-image links.
- Create documented placeholder scribe -1 only if needed.
- Map legacy display order into num/priority/is_default according to product policy.

Validation:
- Hand ordering works for sampled item parts.
- Audit mappings for scribes, hands, and hand-image links match accepted warnings.

Rollback: Delete hand-image links, hands, and scribes for the phase or restore backup.

### `07_image_text` Image Text

Import non-empty transcription/translation XML as target image text rows.

Importer contract:
- Import only rows with non-empty content.
- Do not preserve legacy XML ids unless a later importer design explicitly requires it.
- Leave review_assignee_id, status transitions, and content_dpt_legacy to current workflows.

Validation:
- Legacy text exclusions check reports matching non-empty XML and ImageText counts.
- Unique one-text-per-image/type constraint passes.

Rollback: Delete image text rows imported by the phase or restore target backup.

### `08_annotations` Annotations And Graph Details

Import image/text/editorial annotations and graph through tables after symbols, hands, and images.

Importer contract:
- Preserve legacy annotation ids for Graph rows.
- Filter graph components/features/positions consistently with omitted graph material.
- Require allograph and hand for image graphs; text/editorial links may follow accepted legacy shape.

Validation:
- Annotation shape check has no fail status.
- Graph component and position counts match accepted audit warnings.
- Sample image annotations render in viewer/API responses.

Rollback: Delete graph through rows first, then graph rows for the phase, or restore target backup.

### `09_publications` Publications And Carousel

Import public CMS records represented in the current application.

Importer contract:
- Use the approved author policy from phase 02.
- Preserve publication and carousel ids where the audit says ids are preserved.
- Re-key keyword/category joins through current tagulous tables.

Validation:
- Publication counts match the audit.
- Sample slugs, statuses, publication dates, and author displays are correct.

Rollback: Delete publication keyword links, publications, and carousel rows for the phase or restore backup.

### `10_target_only` Target-Only Current Data

Handle current-only tables without inventing unsupported legacy source mappings.

Importer contract:
- Do not derive edit events, status transitions, or worksets from legacy source data without a product decision.
- Create historical item date assessments only from approved current target metadata.
- Record skipped target-only tables in the manifest.

Validation:
- Target-only warnings in the audit are accepted and documented.
- No unsupported legacy source table is used for target-only workflow data.

Rollback: Delete current-only rows created during the phase or restore target backup.

### `11_final_validation` Final Validation

Prove the imported target is internally consistent and application-ready.

Importer contract:
- Run full audit_legacy_migration.
- Run sequence synchronization.
- Run focused tests and smoke checks.
- Rebuild Meilisearch indexes after target validation.

Validation:
- Audit has no fail status and all warnings are listed in the manifest.
- Foreign key checks and target constraints pass.
- Search indexes rebuild successfully.

Rollback: Restore target backup if validation fails after import phases have committed.

### `12_cutover` Deployment Cutover

Promote the validated target database as a deliberate deployment operation.

Importer contract:
- Run as a manual deployment job with explicit approval.
- Attach final manifest, final audit, and rollback instructions to the deployment record.
- Keep the legacy source database read-only until post-cutover acceptance is complete.

Validation:
- Application smoke checks pass.
- API docs and key public endpoints respond.
- Business owner signs off sampled migrated records.

Rollback: Restore the pre-cutover target dump and return traffic to the previous deployment.

## Deployment Integration

- CI should run unit tests for the audit/procedure modules.
- Pre-cutover should run `audit_legacy_migration`; fail status blocks the deployment.
  This refers to the populated target after import, not the expected empty-target baseline.
- Warning status requires a human to list accepted warnings in the manifest.
- `migrate_legacy_data` plans by default and writes only with `--execute`.
- The write import should run against a freshly migrated target unless `--allow-non-empty-target` is explicitly approved.
- Post-cutover should run sequence sync, focused tests, smoke checks, and search rebuild.

## Command Reference

### Generate the operator guide

```bash
./scripts/backend-compose-run.sh python -m commands.legacy_migration_procedure --output docs/operator-guide.md --manifest-template manifests/legacy-migration-manifest-template.json
```

### Generate the guide with a live read-only audit summary

```bash
./scripts/backend-compose-run.sh python -m commands.legacy_migration_procedure --with-live-audit --output docs/operator-guide.md --manifest-template manifests/legacy-migration-manifest-template.json
```

### Write the read-only audit report

```bash
./scripts/backend-compose-run.sh python -m commands.audit_legacy_migration --format markdown --output reports/legacy-migration-audit.md
```

### Plan the legacy import without writing data

```bash
./scripts/backend-compose-run.sh python -m commands.migrate_legacy_data --manifest reports/legacy-migration-import-dry-run.json
```

### Run the legacy import against a fresh target database

```bash
./scripts/backend-compose-run.sh python -m commands.migrate_legacy_data --execute --publication-author-username <target-author-username> --allow-warnings --manifest reports/legacy-migration-import-run.json
```

### Run strict audit in CI or pre-cutover

```bash
./scripts/backend-compose-run.sh python -m commands.audit_legacy_migration --fail-on-warning
```

### Synchronize target sequences after explicit ids

```bash
just sync-sequences
```

### Rebuild search after final validation

```bash
just sync-all-search-indexes
```

## Manifest

Use `manifests/legacy-migration-manifest-template.json` as the starting point for a real migration run. The completed manifest is the audit trail for backups, approvals, accepted warnings, phase results, validation evidence, and rollback references.

## Write Importer

Plan first. This connects to both databases and returns expected row counts without writing:

```bash
./scripts/backend-compose-run.sh python -m commands.migrate_legacy_data \
  --legacy-url "$LEGACY_DATABASE_URL" \
  --target-url "$TARGET_DATABASE_URL" \
  --manifest reports/legacy-migration-import-dry-run.json
```

A successful dry run proves that the import can be planned. It does not prove that inserts, foreign keys, unique constraints, or post-import comparisons will pass.

Execute only against a backed-up, freshly migrated target database:

```bash
./scripts/backend-compose-run.sh python -m commands.migrate_legacy_data --execute \
  --legacy-url "$LEGACY_DATABASE_URL" \
  --target-url "$TARGET_DATABASE_URL" \
  --publication-author-username <target-author-username> \
  --allow-warnings \
  --manifest reports/legacy-migration-import-run.json
```

The publication author username must already exist in the target database. `--allow-warnings` permits reviewed warning status but never permits fail status.

The command refuses same-database URLs, missing tables, and non-empty import targets by default. Use `--allow-non-empty-target` only for an approved recovery or incremental trial.
