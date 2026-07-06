"""Unit tests for ster.plugins.semanticlint.runner."""

from __future__ import annotations

from pathlib import Path

import pytest
from semanticlint.checks.base import Severity


@pytest.fixture(autouse=True)
def _isolate_quality(tmp_path, monkeypatch):
    """lint_overview reads the global quality.json — redirect it to a temp path so the
    tests use default thresholds, independent of the developer's real config."""
    from ster.plugins.semanticlint import config

    monkeypatch.setattr(config, "_config_path", lambda: tmp_path / "quality.json")

from ster.plugins.semanticlint.runner import (
    has_blocking_violations,
    lint_files,
    lint_overview,
    load_config,
)

_VALID_SKOS = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex:   <http://example.org/> .

ex:Scheme a skos:ConceptScheme ;
    skos:hasTopConcept ex:C1 .
ex:C1 a skos:Concept ;
    skos:inScheme ex:Scheme ;
    skos:topConceptOf ex:Scheme ;
    skos:prefLabel "Concept One"@en ;
    skos:definition "The first concept."@en .
"""

# SKO001 — duplicate prefLabel (ERROR)
_SKOS_ERROR = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex:   <http://example.org/> .

ex:Scheme a skos:ConceptScheme .
ex:C1 a skos:Concept ;
    skos:inScheme ex:Scheme ;
    skos:prefLabel "Concept One"@en ;
    skos:prefLabel "Also Concept One"@en .
"""

# SKO002 — missing prefLabel (WARNING)
_SKOS_WARNING = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex:   <http://example.org/> .

ex:Scheme a skos:ConceptScheme .
ex:C1 a skos:Concept ; skos:inScheme ex:Scheme .
"""


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "vocab.ttl"
    p.write_text(content, encoding="utf-8")
    return p


# ── lint_files ────────────────────────────────────────────────────────────────


def test_lint_clean_file_returns_no_violations(tmp_path: Path):
    from semanticlint.checks.base import CheckConfig

    path = _write(tmp_path, _VALID_SKOS)
    violations = lint_files([path], CheckConfig())
    assert violations == []


def test_lint_detects_skos_errors(tmp_path: Path):
    from semanticlint.checks.base import CheckConfig

    path = _write(tmp_path, _SKOS_ERROR)
    violations = lint_files([path], CheckConfig())
    assert any(v.check_id == "SKO001" for v in violations)
    assert any(v.severity == Severity.ERROR for v in violations)


def test_lint_detects_warnings(tmp_path: Path):
    from semanticlint.checks.base import CheckConfig

    path = _write(tmp_path, _SKOS_WARNING)
    violations = lint_files([path], CheckConfig())
    assert any(v.severity == Severity.WARNING for v in violations)


# ── semanticlint 0.5 SHACL integration ────────────────────────────────────────

_OWL_GAPS = """\
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <http://ex/> .
ex:O a owl:Ontology .
ex:Animal a owl:Class .                 # RDS001 — no rdfs:label
ex:hasOwner a owl:ObjectProperty .      # OWL001/OWL002 — no domain/range
ex:i a owl:NamedIndividual .            # OWL003 — no real type
"""


def test_lint_files_surfaces_shape_backed_checks_regression(tmp_path: Path):
    """Regression: OWL001/002/003 and RDS001 became SHACL shapes in semanticlint 0.5 and
    left the Python registry. lint_files must run the SHACL pass so they still surface —
    otherwise ster silently detects less after the upgrade."""
    from semanticlint.checks.base import CheckConfig

    path = _write(tmp_path, _OWL_GAPS)
    ids = {v.check_id for v in lint_files([path], CheckConfig())}
    assert {"OWL001", "OWL002", "OWL003", "RDS001"} <= ids


def test_lint_files_discovers_sibling_business_rules(tmp_path: Path):
    """A project-owned ``*.shapes.ttl`` next to the ontology is discovered and enforced."""
    from semanticlint.checks.base import CheckConfig

    (tmp_path / "zoo.shapes.ttl").write_text(
        "@prefix sh: <http://www.w3.org/ns/shacl#> .\n"
        "@prefix ex: <http://example.org/> .\n"
        "ex:PersonEmploymentShape a sh:NodeShape ; sh:targetClass ex:Person ;\n"
        '  sh:property [ sh:path ex:work_for ; sh:maxCount 1 ; sh:message "one dept" ] .\n'
    )
    onto = tmp_path / "zoo.ttl"
    onto.write_text(
        "@prefix ex: <http://example.org/> .\nex:alice a ex:Person ; ex:work_for ex:D1, ex:D2 .\n"
    )
    ids = {v.check_id for v in lint_files([onto], CheckConfig())}
    assert "PersonEmploymentShape" in ids


def test_lint_files_default_ignores_noisy_rdf006(tmp_path: Path):
    """RDF006 (base-URI consistency) is suppressed by default — a sibling-namespaced SKOS
    vocabulary is valid and must not be flagged."""
    from semanticlint.checks.base import CheckConfig

    path = _write(tmp_path, _VALID_SKOS)
    assert not any(v.check_id == "RDF006" for v in lint_files([path], CheckConfig()))


# ── lint_overview (plain-data adapter for the TUI) ────────────────────────────


def test_lint_overview_clean_file_has_zero_counts(tmp_path: Path):
    path = _write(tmp_path, _VALID_SKOS)
    counts, issues = lint_overview(path)
    assert counts == {"error": 0, "warning": 0, "info": 0}
    assert issues == []


def test_lint_overview_returns_plain_issue_dicts(tmp_path: Path):
    path = _write(tmp_path, _SKOS_ERROR)
    counts, issues = lint_overview(path)
    assert counts["error"] >= 1
    assert issues  # non-empty
    issue = issues[0]
    # Plain str-only payload — no semanticlint Violation/Severity leaking out.
    assert set(issue) == {"severity", "check_id", "message", "subject"}
    assert all(isinstance(v, str) for v in issue.values())
    assert any(i["check_id"] == "SKO001" for i in issues)


# ── load_config ───────────────────────────────────────────────────────────────


def test_load_config_defaults_when_no_file(tmp_path: Path):
    cfg, fail_on = load_config(tmp_path)
    assert fail_on == Severity.ERROR
    assert cfg.select == []
    assert cfg.ignore == []


def test_load_config_reads_fail_on_from_onto_ci_yml(tmp_path: Path):
    (tmp_path / "onto-ci.yml").write_text("fail_on: warning\n", encoding="utf-8")
    _, fail_on = load_config(tmp_path)
    assert fail_on == Severity.WARNING


def test_load_config_reads_quality_thresholds(tmp_path: Path):
    (tmp_path / "onto-ci.yml").write_text("quality:\n  min_label_coverage: 0.8\n", encoding="utf-8")
    cfg, _ = load_config(tmp_path)
    assert cfg.quality.get("min_label_coverage") == 0.8


# ── has_blocking_violations ───────────────────────────────────────────────────


def test_meets_threshold_error_on_error(tmp_path: Path):
    from semanticlint.checks.base import CheckConfig

    path = _write(tmp_path, _SKOS_ERROR)
    violations = lint_files([path], CheckConfig())
    assert has_blocking_violations(violations, Severity.ERROR) is True


def test_warning_does_not_block_at_error_threshold(tmp_path: Path):
    from semanticlint.checks.base import CheckConfig

    path = _write(tmp_path, _SKOS_WARNING)
    violations = lint_files([path], CheckConfig())
    assert has_blocking_violations(violations, Severity.ERROR) is False


def test_warning_blocks_at_warning_threshold(tmp_path: Path):
    from semanticlint.checks.base import CheckConfig

    path = _write(tmp_path, _SKOS_WARNING)
    violations = lint_files([path], CheckConfig())
    assert has_blocking_violations(violations, Severity.WARNING) is True


def test_no_violations_never_blocks():
    assert has_blocking_violations([], Severity.INFO) is False


def test_ignore_and_select_filter_checks(tmp_path) -> None:
    """ster enforces select/ignore (which semanticlint 0.3.0 parses but drops)."""
    from semanticlint.checks.base import CheckConfig

    from ster.plugins.semanticlint.runner import _check_included

    assert _check_included("SKO001", CheckConfig(ignore=["SKO001"])) is False
    assert _check_included("SKO001", CheckConfig(ignore=["SKO"])) is False  # prefix
    assert _check_included("OWL001", CheckConfig(ignore=["SKO"])) is True
    assert _check_included("QUA002", CheckConfig(select=["QUA"])) is True  # prefix select
    assert _check_included("SKO001", CheckConfig(select=["QUA"])) is False  # not selected
    assert _check_included("SKO001", CheckConfig()) is True  # no select/ignore → all
