import json

import pytest

from commands.migrate_legacy_data import main as migrate_main
from migration_toolkit.importer import (
    ImportReport,
    LegacyMigrationImportError,
    PhaseResult,
    audit_failure_summary,
    expand_phases,
    legacy_image_path,
    parse_annotation,
    parse_date_weights,
    source_profile_blockers,
    source_profile_warnings,
)


def test_expand_phases_defaults_to_full_order():
    phases = expand_phases(("all",))

    assert phases[0] == "core_vocabularies"
    assert phases[-1] == "target_only"
    assert "annotations" in phases


def test_expand_phases_rejects_mixed_all():
    with pytest.raises(LegacyMigrationImportError):
        expand_phases(("all", "manuscripts"))


def test_parse_date_weights_prefers_years_from_date_text():
    assert parse_date_weights("24 May 1153 X 1159") == (1153, 1159)
    assert parse_date_weights("X 8 March 1185") == (1185, 1185)


def test_parse_date_weights_falls_back_to_legacy_weights():
    assert parse_date_weights("", min_weight=1100, max_weight=1125, weight=None) == (1100, 1125)
    assert parse_date_weights(None, weight=1099) == (1099, 1099)
    assert parse_date_weights(None) == (0, 0)


def test_legacy_image_path_converts_iip_tif_paths():
    assert legacy_image_path("jp2/BLno1/path/k90069_51.tif") == "BLno1/path/k90069_51.jp2"
    assert legacy_image_path(None, "already.jp2") == "already.jp2"


def test_parse_annotation_accepts_legacy_python_dict_strings():
    assert parse_annotation("{'shapes': [{'type': 'rect'}]}") == {"shapes": [{"type": "rect"}]}
    assert parse_annotation("not parseable") == {"legacy_raw": "not parseable"}


def test_migrate_legacy_data_cli_renders_report(monkeypatch, capsys):
    def fake_run_import(options):
        assert options.execute is False
        assert options.phases == ("manuscripts",)
        return ImportReport(
            dry_run=True,
            legacy_database="legacy_source",
            target_database="new_target",
            phases=[
                PhaseResult(
                    key="manuscripts",
                    status="ok",
                    started_at="2026-06-09T00:00:00+00:00",
                    finished_at="2026-06-09T00:00:01+00:00",
                    rows_planned={"manuscripts_itemimage": 2},
                    rows_imported={},
                )
            ],
            target_row_counts_before={},
            target_row_counts_after={},
        )

    monkeypatch.setattr("commands.migrate_legacy_data.run_import", fake_run_import)

    assert migrate_main(["--phase", "manuscripts"]) == 0
    output = capsys.readouterr().out
    data = json.loads(output)

    assert data["dry_run"] is True
    assert data["phases"][0]["rows_planned"] == {"manuscripts_itemimage": 2}
    assert data["source_profile"] == {}


def test_source_profile_warnings_describe_unsupported_source_shapes():
    profile = {
        "description_relationships": {
            "counts": {
                "historical_only": 10,
                "text_only": 2,
                "both_links": 1,
                "neither_link": 3,
                "dangling_historical_item": 4,
            },
            "samples": {},
        },
        "allograph_character_integrity": {"missing_character_count": 5, "sample": []},
    }

    warnings = source_profile_warnings(profile)

    assert len(warnings) == 5
    assert "text-only rows" in warnings[0]
    assert "missing character links" in warnings[-1]


def test_source_profile_blockers_apply_to_selected_phases():
    profile = {
        "description_relationships": {
            "counts": {
                "historical_only": 10,
                "text_only": 2,
                "both_links": 0,
                "neither_link": 0,
                "dangling_historical_item": 0,
            },
            "samples": {},
        },
        "allograph_character_integrity": {"missing_character_count": 1, "sample": []},
    }

    assert source_profile_blockers(profile, ("image_text",)) == []
    assert len(source_profile_blockers(profile, ("manuscripts",))) == 1
    assert len(source_profile_blockers(profile, ("symbols",))) == 1
    assert len(source_profile_blockers(profile, ("symbols", "manuscripts"))) == 2


def test_import_report_status_warns_on_source_warnings():
    report = ImportReport(
        dry_run=True,
        legacy_database="legacy_source",
        target_database="new_target",
        phases=[],
        target_row_counts_before={},
        target_row_counts_after={},
        source_warnings=["unsupported source shape"],
    )

    assert report.status == "warn"


def test_audit_failure_summary_includes_failed_mapping_counts():
    summary = audit_failure_summary(
        {
            "mappings": [
                {
                    "key": "historical_item_descriptions",
                    "status": "fail",
                    "id_comparison": {
                        "unexpected_missing_count": 356,
                        "unexpected_extra_count": 0,
                    },
                }
            ],
            "checks": [
                {
                    "key": "annotation_shape",
                    "status": "fail",
                    "summary": "Some annotations are missing links.",
                }
            ],
        }
    )

    assert "historical_item_descriptions" in summary
    assert "unexpected missing: 356" in summary
    assert "annotation_shape" in summary
