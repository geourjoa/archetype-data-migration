from commands.audit_legacy_migration import main as audit_main
from migration_toolkit.audit import (
    ENTITY_MAPPINGS,
    PUBLICATION_AUTHOR_POLICY_FALLBACK,
    AuditReport,
    CheckResult,
    IdComparison,
    MappingResult,
    PublicationAuthorPolicy,
    check_legacy_description_relationships,
    check_publication_author_mapping,
    compare_id_sets,
    legacy_url_from_env,
    render_json,
    render_markdown,
    target_url_from_env,
)


def test_compare_id_sets_exact_match():
    comparison = compare_id_sets({1, 2, 3}, {1, 2, 3})

    assert comparison.common_count == 3
    assert comparison.missing_in_target_count == 0
    assert comparison.extra_in_target_count == 0
    assert comparison.unexpected_missing_count == 0
    assert comparison.unexpected_extra_count == 0


def test_compare_id_sets_allows_known_target_extras_and_missing_ids():
    comparison = compare_id_sets(
        {1, 2, 3, 4},
        {1, 2, 4, -1},
        allowed_extra_target_ids={-1},
        allowed_missing_target_ids={3},
    )

    assert comparison.missing_in_target_count == 1
    assert comparison.extra_in_target_count == 1
    assert comparison.unexpected_missing_count == 0
    assert comparison.unexpected_extra_count == 0
    assert comparison.missing_sample == [3]
    assert comparison.extra_sample == [-1]


def test_compare_id_sets_reports_unexpected_differences():
    comparison = compare_id_sets({1, 2, 3}, {1, 4})

    assert comparison.common_count == 1
    assert comparison.missing_in_target_count == 2
    assert comparison.extra_in_target_count == 1
    assert comparison.unexpected_missing_count == 2
    assert comparison.unexpected_extra_count == 1


def test_render_markdown_includes_mapping_and_check_details():
    report = AuditReport(
        legacy_database="legacy_source",
        target_database="target_current",
        legacy_table_count=142,
        target_table_count=52,
        mappings=[
            MappingResult(
                key="example",
                title="Example entity",
                category="example",
                strategy="id-preserved",
                status="warn",
                legacy_count=2,
                target_count=3,
                notes="target has a known placeholder",
                id_comparison=IdComparison(
                    legacy_count=2,
                    target_count=3,
                    common_count=2,
                    missing_in_target_count=0,
                    extra_in_target_count=1,
                    unexpected_missing_count=0,
                    unexpected_extra_count=0,
                    missing_sample=[],
                    extra_sample=[-1],
                ),
            )
        ],
        checks=[
            CheckResult(
                key="authors",
                title="Author mapping",
                status="warn",
                summary="Needs username mapping.",
                details=[{"legacy_username": "legacy", "target_username": "target"}],
            )
        ],
    )

    rendered = render_markdown(report)

    assert "Status: `warn`" in rendered
    assert "| `warn` | Example entity | 2 | 3 | id-preserved |" in rendered
    assert "target has a known placeholder" in rendered
    assert '"legacy_username": "legacy"' in rendered


def test_render_json_is_machine_readable():
    report = AuditReport(
        legacy_database="legacy_source",
        target_database="target_current",
        legacy_table_count=142,
        target_table_count=52,
        mappings=[],
        checks=[],
    )

    rendered = render_json(report)

    assert '"legacy_database": "legacy_source"' in rendered
    assert '"status": "ok"' in rendered


def test_database_urls_default_from_environment(monkeypatch):
    monkeypatch.delenv("LEGACY_DATABASE_URL", raising=False)
    monkeypatch.delenv("TARGET_DATABASE_URL", raising=False)
    monkeypatch.delenv("LEGACY_DATABASE_NAME", raising=False)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://postgres:secret@postgres:5432/target_current",
    )

    assert target_url_from_env() == "postgresql://postgres:secret@postgres:5432/target_current"
    assert legacy_url_from_env() == "postgresql://postgres:secret@postgres:5432/legacy_source"


def test_explicit_database_urls_override_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:secret@postgres:5432/target_current")
    monkeypatch.setenv("TARGET_DATABASE_URL", "postgresql://postgres:other@postgres:5432/current")
    monkeypatch.setenv("LEGACY_DATABASE_URL", "postgresql://postgres:other@postgres:5432/legacy")

    assert target_url_from_env() == "postgresql://postgres:other@postgres:5432/current"
    assert legacy_url_from_env() == "postgresql://postgres:other@postgres:5432/legacy"


def test_legacy_url_can_derive_from_explicit_target_url(monkeypatch):
    monkeypatch.delenv("LEGACY_DATABASE_URL", raising=False)
    monkeypatch.delenv("TARGET_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LEGACY_DATABASE_NAME", raising=False)

    assert (
        legacy_url_from_env(base_url="postgresql://postgres:secret@postgres:5432/current")
        == "postgresql://postgres:secret@postgres:5432/legacy_source"
    )


def test_legacy_url_can_derive_from_custom_legacy_database_name(monkeypatch):
    monkeypatch.delenv("LEGACY_DATABASE_URL", raising=False)
    monkeypatch.setenv("LEGACY_DATABASE_NAME", "restored_legacy")

    assert (
        legacy_url_from_env(base_url="postgresql://postgres:secret@postgres:5432/current")
        == "postgresql://postgres:secret@postgres:5432/restored_legacy"
    )


def test_database_urls_fallback_to_postgres_environment(monkeypatch):
    monkeypatch.delenv("LEGACY_DATABASE_URL", raising=False)
    monkeypatch.delenv("TARGET_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LEGACY_DATABASE_NAME", raising=False)
    monkeypatch.delenv("TARGET_DATABASE_NAME", raising=False)
    monkeypatch.setenv("POSTGRES_USER", "postgres")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret value")
    monkeypatch.setenv("POSTGRES_HOST", "postgres")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_DB", "compose_target")

    assert target_url_from_env() == "postgresql://postgres:secret%20value@postgres:5432/compose_target"
    assert legacy_url_from_env() == "postgresql://postgres:secret%20value@postgres:5432/legacy_source"


def test_publication_author_fallback_policy_warns_with_evidence(monkeypatch):
    def fake_dict_rows(conn, query, params=None):
        query_text = str(query)
        if "FROM auth_user WHERE username" in query_text:
            return [{"id": 8, "username": "anthony"}]
        if "FROM blog_blogpost" in query_text:
            return [
                {"id": 2, "username": "sbrookes", "post_count": 36},
                {"id": 3, "username": "pstokes", "post_count": 13},
            ]
        if "FROM publications_publication" in query_text:
            return [{"id": 8, "username": "anthony", "post_count": 49}]
        raise AssertionError(f"Unexpected query: {query_text}")

    monkeypatch.setattr("migration_toolkit.audit._dict_rows", fake_dict_rows)

    result = check_publication_author_mapping(
        object(),
        object(),
        PublicationAuthorPolicy(
            mode=PUBLICATION_AUTHOR_POLICY_FALLBACK,
            fallback_author_username="anthony",
        ),
    )

    assert result.status == "warn"
    assert "Explicit fallback publication author policy applied" in result.summary
    assert result.details[0]["expected_target_author"] == {"id": 8, "username": "anthony"}
    assert len(result.details[0]["legacy_authors"]) == 2


def test_publication_author_fallback_policy_fails_on_mixed_target_authors(monkeypatch):
    def fake_dict_rows(conn, query, params=None):
        query_text = str(query)
        if "FROM auth_user WHERE id" in query_text:
            return [{"id": 8, "username": "anthony"}]
        if "FROM blog_blogpost" in query_text:
            return [{"id": 2, "username": "sbrookes", "post_count": 36}]
        if "FROM publications_publication" in query_text:
            return [
                {"id": 8, "username": "anthony", "post_count": 35},
                {"id": 9, "username": "other", "post_count": 1},
            ]
        raise AssertionError(f"Unexpected query: {query_text}")

    monkeypatch.setattr("migration_toolkit.audit._dict_rows", fake_dict_rows)

    result = check_publication_author_mapping(
        object(),
        object(),
        PublicationAuthorPolicy(
            mode=PUBLICATION_AUTHOR_POLICY_FALLBACK,
            fallback_author_id=8,
        ),
    )

    assert result.status == "fail"
    assert "other target authors are present" in result.summary


def test_historical_description_mapping_counts_only_supported_rows():
    mapping = next(mapping for mapping in ENTITY_MAPPINGS if mapping.key == "historical_item_descriptions")

    assert mapping.legacy_count_sql is not None
    assert mapping.legacy_ids_sql is not None
    assert "historical_item_id IS NOT NULL" in mapping.legacy_count_sql
    assert "digipal_historicalitem" in mapping.legacy_ids_sql


def test_legacy_description_relationship_check_warns_on_unsupported_rows(monkeypatch):
    def fake_dict_rows(conn, query, params=None):
        return [
            {
                "historical_only": 701,
                "text_only": 1,
                "both_links": 0,
                "neither_link": 1,
                "dangling_historical_item": 0,
            }
        ]

    monkeypatch.setattr("migration_toolkit.audit._dict_rows", fake_dict_rows)

    result = check_legacy_description_relationships(object())

    assert result.status == "warn"
    assert "701 legacy descriptions are supported" in result.summary
    assert "2 text-only, unattached, or dangling descriptions" in result.summary
    assert result.details[0]["unsupported_descriptions"] == 2


def test_legacy_description_relationship_check_ok_when_all_supported(monkeypatch):
    def fake_dict_rows(conn, query, params=None):
        return [
            {
                "historical_only": 703,
                "text_only": 0,
                "both_links": 0,
                "neither_link": 0,
                "dangling_historical_item": 0,
            }
        ]

    monkeypatch.setattr("migration_toolkit.audit._dict_rows", fake_dict_rows)

    result = check_legacy_description_relationships(object())

    assert result.status == "ok"
    assert result.details[0]["supported_historical_descriptions"] == 703


def test_audit_cli_accepts_publication_author_fallback_policy(monkeypatch, tmp_path):
    output_path = tmp_path / "audit.json"

    def fake_run_audit(legacy_url=None, target_url=None, publication_author_policy=None):
        assert publication_author_policy.mode == PUBLICATION_AUTHOR_POLICY_FALLBACK
        assert publication_author_policy.fallback_author_username == "anthony"
        return AuditReport(
            legacy_database="legacy_source",
            target_database="target_current",
            legacy_table_count=1,
            target_table_count=1,
            mappings=[],
            checks=[],
        )

    monkeypatch.setattr("commands.audit_legacy_migration.run_audit", fake_run_audit)

    assert (
        audit_main(
            [
                "--format",
                "json",
                "--output",
                str(output_path),
                "--publication-author-policy",
                "fallback",
                "--publication-author-username",
                "anthony",
            ]
        )
        == 0
    )
    assert '"status": "ok"' in output_path.read_text(encoding="utf-8")
