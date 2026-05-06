"""Unit tests for ster.lint_runner."""

from __future__ import annotations

from pathlib import Path

from semanticlint.checks.base import Severity

from ster.lint_runner import has_blocking_violations, lint_files, load_config

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
