"""The CLI never prints an empty tree for a file ster could not model."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from ster.cli import app

_runner = CliRunner()

_CAPABILITY_TTL = """\
@prefix ex: <https://example.com/business-capability/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .

ex:one a ex:BusinessCapability ;
    skos:prefLabel "Collect Supplier Information" .

ex:two a ex:BusinessCapability ;
    skos:prefLabel "Calculate Costs" .
"""

_READABLE_TTL = """\
@prefix ex: <https://example.com/taxonomy/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .

ex:tent a skos:Concept ;
    skos:prefLabel "Tent"@en .
"""


@pytest.fixture
def capability_file(tmp_path: Path) -> Path:
    path = tmp_path / "business_capabilities.ttl"
    path.write_text(_CAPABILITY_TTL)
    return path


@pytest.fixture
def readable_file(tmp_path: Path) -> Path:
    path = tmp_path / "gear.ttl"
    path.write_text(_READABLE_TTL)
    return path


@pytest.fixture(autouse=True)
def _no_cache(monkeypatch) -> None:
    """Each tmp_path file is new, but never share a binary cache across tests."""
    monkeypatch.setenv("STER_NO_CACHE", "1")


def test_show_plain_reports_and_exits_non_zero(capability_file: Path) -> None:
    result = _runner.invoke(app, ["show", "--plain", str(capability_file)])
    assert result.exit_code != 0
    assert "recognised no entity" in result.output


def test_message_names_the_undeclared_type_and_its_count(capability_file: Path) -> None:
    result = _runner.invoke(app, ["show", "--plain", str(capability_file)])
    assert "BusinessCapability" in result.output
    assert "2" in result.output


def test_message_contains_the_turtle_to_paste(capability_file: Path) -> None:
    result = _runner.invoke(app, ["show", "--plain", str(capability_file)])
    assert "a owl:Class ." in result.output
    assert "@prefix owl:" in result.output


def test_validate_reports_instead_of_zero_concepts(capability_file: Path) -> None:
    result = _runner.invoke(app, ["validate", str(capability_file)])
    assert result.exit_code != 0
    assert "No issues found" not in result.output


def test_handles_reports_instead_of_an_empty_table(capability_file: Path) -> None:
    result = _runner.invoke(app, ["handles", str(capability_file)])
    assert result.exit_code != 0
    assert "recognised no entity" in result.output


def test_empty_file_says_it_has_no_triples(tmp_path: Path) -> None:
    path = tmp_path / "empty.ttl"
    path.write_text("")
    result = _runner.invoke(app, ["show", "--plain", str(path)])
    assert result.exit_code != 0
    assert "no triples" in result.output


def test_readable_file_still_exits_zero(readable_file: Path) -> None:
    result = _runner.invoke(app, ["show", "--plain", str(readable_file)])
    assert result.exit_code == 0
    assert "Tent" in result.output
