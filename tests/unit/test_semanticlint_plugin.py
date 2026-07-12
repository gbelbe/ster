"""Unit tests for the semanticlint plugin's pure helpers + global config."""

from __future__ import annotations

import pytest

from ster.plugins.semanticlint import config, report


@pytest.fixture(autouse=True)
def _isolate_quality(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_config_path", lambda: tmp_path / "quality.json")


# ── report (pure grouping) ──────────────────────────────────────────────────────

_ISSUES = [
    {"severity": "warning", "check_id": "OWL001", "message": "no domain", "subject": "u:P"},
    {"severity": "error", "check_id": "SKO001", "message": "dup", "subject": "u:C"},
    {"severity": "info", "check_id": "QUA002", "message": "def", "subject": "u:C"},
    {"severity": "error", "check_id": "RDF001", "message": "syntax", "subject": ""},  # global
]


def test_issues_by_subject_drops_subjectless_issues() -> None:
    grouped = report.issues_by_subject(_ISSUES)
    assert set(grouped) == {"u:P", "u:C"}  # the empty-subject global one is excluded
    assert len(grouped["u:C"]) == 2


def test_worst_by_subject_picks_the_most_severe() -> None:
    worst = report.worst_by_subject(_ISSUES)
    assert worst == {"u:P": "warning", "u:C": "error"}  # error beats info for u:C


def test_worst_severity_of_empty_is_none() -> None:
    assert report.worst_severity([]) is None


# ── config (global quality.json) ────────────────────────────────────────────────


def test_load_config_fills_defaults() -> None:
    cfg = config.load_config()
    assert cfg["fail_on"] == "error"
    assert cfg["quality"]["min_label_coverage"] == 1.0
    assert cfg["features"] == {
        "icons": True,
        "detail": True,
        "quality_block": True,
        "enforce": False,  # write-side authoring, opt-in
    }


def test_save_config_merges_and_round_trips() -> None:
    config.save_config({"fail_on": "warning"})
    config.save_config({"quality": {"min_label_coverage": 0.5}})
    cfg = config.load_config()
    assert cfg["fail_on"] == "warning"  # first write preserved
    assert cfg["quality"]["min_label_coverage"] == 0.5
    assert cfg["quality"]["min_definition_coverage"] == 0.5  # default kept


def test_feature_toggle_round_trips() -> None:
    assert config.feature_enabled("icons") is True
    config.set_feature("icons", False)
    assert config.feature_enabled("icons") is False
    assert config.feature_enabled("detail") is True  # untouched


def test_build_check_config_uses_thresholds() -> None:
    config.save_config({"quality": {"languages": ["en", "fr"]}})
    cc = config.build_check_config()
    assert cc.quality["languages"] == ["en", "fr"]


def test_quality_summary_fields_counts_by_severity() -> None:
    from ster.tui.plugins.semanticlint_ui import hooks

    fields = hooks.quality_summary_fields({"error": 2, "warning": 1, "info": 0}, title="Q")
    by_key = {f.key: f.value for f in fields}
    assert by_key.get("stq:error") == "2" and by_key.get("stq:warning") == "1"


def test_quality_summary_fields_clean_shows_no_issues_row() -> None:
    from ster.tui.plugins.semanticlint_ui import hooks

    fields = hooks.quality_summary_fields({}, title="Q")
    assert any(f.key == "stq:clean" for f in fields)


# ── quality.json ↔ onto-ci.yml alignment ────────────────────────────────────────


def test_build_check_config_includes_select_and_ignore() -> None:
    config.save_config({"select": ["SKO", "OWL"], "ignore": ["QUA002"]})
    cc = config.build_check_config()
    assert cc.select == ["SKO", "OWL"] and cc.ignore == ["QUA002"]


def test_fail_on_severity_maps_and_defaults() -> None:
    from semanticlint.checks.base import Severity

    config.save_config({"fail_on": "warning"})
    assert config.fail_on_severity() == Severity.WARNING
    config.save_config({"fail_on": "bogus"})
    assert config.fail_on_severity() == Severity.ERROR  # unknown → error


def test_write_onto_ci_exports_shared_keys_only(tmp_path) -> None:
    import yaml

    config.save_config(
        {
            "fail_on": "warning",
            "select": ["SKO"],
            "ignore": ["QUA002"],
            "quality": {"min_label_coverage": 0.5, "languages": ["en", "fr"]},
        }
    )
    path = config.write_onto_ci(tmp_path)
    assert path == tmp_path / "onto-ci.yml"
    data = yaml.safe_load(path.read_text())
    assert data["fail_on"] == "warning"
    assert data["select"] == ["SKO"] and data["ignore"] == ["QUA002"]
    assert data["quality"]["min_label_coverage"] == 0.5
    assert "features" not in data  # UI-only block is not exported to CI


# ── per-language rdfs:label shapes (STER001 class / STER002 property) ────────────

from pathlib import Path  # noqa: E402

_DEMO = Path(__file__).resolve().parents[2] / "ster" / "tui" / "demo.ttl"


def test_build_label_language_shapes_empty_when_no_languages_required() -> None:
    from ster.plugins.semanticlint.language_shapes import build_label_language_shapes

    assert len(build_label_language_shapes([], [])) == 0  # no requirement → no shapes


def test_build_label_language_shapes_emits_a_shape_per_language() -> None:
    from ster.plugins.semanticlint.language_shapes import build_label_language_shapes

    graph = build_label_language_shapes(["en", "fr"], ["fr"])
    assert len(graph) > 0
    assert "language 'fr'" in graph.serialize(format="turtle")


def test_class_and_property_label_language_shapes_flag_missing_languages() -> None:
    """A class / property lacking an rdfs:label in a required language yields a per-entity
    STER001 / STER002 warning (subject = the entity); none when no language is required."""
    from semanticlint.checks.base import CheckConfig

    from ster.plugins.semanticlint.runner import lint_files

    cfg = CheckConfig(quality={"class_label_languages": ["fr"], "property_label_languages": ["fr"]})
    hits = {(v.check_id, str(v.subject).rsplit("/", 1)[-1]) for v in lint_files([_DEMO], cfg)}
    assert ("STER001", "Dog") in hits  # class Dog has only an en rdfs:label
    assert ("STER002", "hasOwner") in hits  # property hasOwner too

    baseline = CheckConfig(quality={"class_label_languages": [], "property_label_languages": []})
    assert not any(v.check_id in {"STER001", "STER002"} for v in lint_files([_DEMO], baseline))
