"""Unit tests for CLI RDF/XML conversion prompts."""

from __future__ import annotations

from unittest.mock import patch

from rdflib import Graph
from typer.testing import CliRunner

import ster.cli as cli_module
from ster import store
from ster.cli import _maybe_backconvert, app

runner = CliRunner()

_RDF_XML = """\
<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about="https://example.org/subject">
    <ns0:predicate xmlns:ns0="https://example.org/" rdf:resource="https://example.org/object"/>
  </rdf:Description>
</rdf:RDF>
"""

_TTL = "@prefix ex: <https://example.org/> .\nex:subject ex:predicate ex:object .\n"


# ── ster convert command ──────────────────────────────────────────────────────


def test_cmd_convert_rdf_to_ttl(tmp_path):
    src = tmp_path / "onto.rdf"
    src.write_text(_RDF_XML)
    result = runner.invoke(app, ["convert", str(src)])
    assert result.exit_code == 0
    assert (tmp_path / "onto.ttl").exists()


def test_cmd_convert_owl_to_ttl(tmp_path):
    src = tmp_path / "onto.owl"
    src.write_text(_RDF_XML)
    result = runner.invoke(app, ["convert", str(src)])
    assert result.exit_code == 0
    assert (tmp_path / "onto.ttl").exists()


def test_cmd_convert_explicit_output(tmp_path):
    src = tmp_path / "onto.rdf"
    src.write_text(_RDF_XML)
    dst = tmp_path / "result.ttl"
    result = runner.invoke(app, ["convert", str(src), str(dst)])
    assert result.exit_code == 0
    assert dst.exists()


def test_cmd_convert_output_is_valid_turtle(tmp_path):
    src = tmp_path / "onto.rdf"
    src.write_text(_RDF_XML)
    runner.invoke(app, ["convert", str(src)])
    g = Graph()
    g.parse(str(tmp_path / "onto.ttl"), format="turtle")
    assert len(g) > 0


def test_cmd_convert_unsupported_extension_fails(tmp_path):
    src = tmp_path / "data.csv"
    src.write_text("not rdf")
    result = runner.invoke(app, ["convert", str(src)])
    assert result.exit_code != 0


def test_cmd_convert_prints_success_message(tmp_path):
    src = tmp_path / "onto.rdf"
    src.write_text(_RDF_XML)
    result = runner.invoke(app, ["convert", str(src)])
    assert result.exit_code == 0
    assert "onto.ttl" in result.output


# ── _maybe_prompt_rdfxml_convert ─────────────────────────────────────────────


def test_prompt_shown_for_rdfxml_path(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_module, "_rdfxml_checked", False)
    monkeypatch.setattr(cli_module, "_converted_from", None)
    src = tmp_path / "onto.owl"
    src.write_text(_RDF_XML)

    with patch("ster.cli.Confirm.ask", return_value=False) as mock_ask:
        cli_module._maybe_prompt_rdfxml_convert(src)

    mock_ask.assert_called_once()


def test_no_prompt_for_ttl_path(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_module, "_rdfxml_checked", False)
    src = tmp_path / "onto.ttl"
    src.write_text(_TTL)

    with patch("ster.cli.Confirm.ask") as mock_ask:
        cli_module._maybe_prompt_rdfxml_convert(src)

    mock_ask.assert_not_called()


def test_prompt_not_repeated_when_already_checked(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_module, "_rdfxml_checked", True)
    src = tmp_path / "onto.owl"
    src.write_text(_RDF_XML)

    with patch("ster.cli.Confirm.ask") as mock_ask:
        cli_module._maybe_prompt_rdfxml_convert(src)

    mock_ask.assert_not_called()


def test_accept_conversion_creates_ttl(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_module, "_rdfxml_checked", False)
    monkeypatch.setattr(cli_module, "_converted_from", None)
    src = tmp_path / "onto.owl"
    src.write_text(_RDF_XML)

    with patch("ster.cli.Confirm.ask", return_value=True):
        result = cli_module._maybe_prompt_rdfxml_convert(src)

    assert result == tmp_path / "onto.ttl"
    assert (tmp_path / "onto.ttl").exists()


def test_accept_conversion_sets_converted_from(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_module, "_rdfxml_checked", False)
    monkeypatch.setattr(cli_module, "_converted_from", None)
    src = tmp_path / "onto.owl"
    src.write_text(_RDF_XML)

    with patch("ster.cli.Confirm.ask", return_value=True):
        cli_module._maybe_prompt_rdfxml_convert(src)

    assert cli_module._converted_from == src


def test_decline_conversion_returns_original(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_module, "_rdfxml_checked", False)
    monkeypatch.setattr(cli_module, "_converted_from", None)
    src = tmp_path / "onto.owl"
    src.write_text(_RDF_XML)

    with patch("ster.cli.Confirm.ask", return_value=False):
        result = cli_module._maybe_prompt_rdfxml_convert(src)

    assert result == src
    assert cli_module._converted_from is None


def test_decline_conversion_no_ttl_created(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_module, "_rdfxml_checked", False)
    src = tmp_path / "onto.owl"
    src.write_text(_RDF_XML)

    with patch("ster.cli.Confirm.ask", return_value=False):
        cli_module._maybe_prompt_rdfxml_convert(src)

    assert not (tmp_path / "onto.ttl").exists()


# ── _maybe_backconvert ────────────────────────────────────────────────────────


def test_backconvert_not_triggered_when_hash_unchanged(tmp_path):
    ttl = tmp_path / "onto.ttl"
    ttl.write_text(_TTL)
    original = tmp_path / "onto.owl"
    original.write_text(_RDF_XML)
    current_hash = store.file_hash(ttl)

    with patch("ster.cli.Confirm.ask") as mock_ask:
        _maybe_backconvert(ttl, current_hash, original)

    mock_ask.assert_not_called()


def test_backconvert_triggered_when_hash_changed(tmp_path):
    ttl = tmp_path / "onto.ttl"
    ttl.write_text(_TTL)
    original = tmp_path / "onto.owl"
    original.write_text(_RDF_XML)

    with patch("ster.cli.Confirm.ask", return_value=False) as mock_ask:
        _maybe_backconvert(ttl, "stale-hash", original)

    mock_ask.assert_called_once()


def test_backconvert_accepted_overwrites_original(tmp_path):
    ttl = tmp_path / "onto.ttl"
    ttl.write_text(_TTL)
    original = tmp_path / "onto.owl"
    original.write_text(_RDF_XML)

    with patch("ster.cli.Confirm.ask", return_value=True):
        _maybe_backconvert(ttl, "stale-hash", original)

    g = Graph()
    g.parse(str(original), format="xml")
    assert len(g) > 0


def test_backconvert_declined_leaves_original(tmp_path):
    ttl = tmp_path / "onto.ttl"
    ttl.write_text(_TTL)
    original = tmp_path / "onto.owl"
    original.write_text(_RDF_XML)
    original_content = original.read_text()

    with patch("ster.cli.Confirm.ask", return_value=False):
        _maybe_backconvert(ttl, "stale-hash", original)

    assert original.read_text() == original_content


def test_load_safe_returns_taxonomy_on_valid_file(tmp_path):
    from ster.cli import _load_safe

    f = tmp_path / "onto.ttl"
    f.write_text(_TTL)
    result = _load_safe(f)
    assert result is not None


def test_load_safe_returns_none_on_corrupt_file(tmp_path):
    from ster.cli import _load_safe

    f = tmp_path / "onto.ttl"
    f.write_text("this is not valid rdf at all !!!")
    result = _load_safe(f)
    assert result is None


def test_load_safe_returns_none_on_missing_file(tmp_path):
    from ster.cli import _load_safe

    result = _load_safe(tmp_path / "nonexistent.ttl")
    assert result is None


def test_load_warns_on_format_mismatch(tmp_path, monkeypatch):
    """_load prints a warning when file content format differs from its extension."""
    from ster.cli import _load

    f = tmp_path / "onto.ttl"
    f.write_text(_RDF_XML)
    output: list[str] = []
    monkeypatch.setattr(
        cli_module,
        "console",
        type(
            "C",
            (),
            {
                "print": lambda self, *a, **k: output.append(str(a[0])),
                "status": lambda self, *a, **k: __import__("contextlib").nullcontext(),
            },
        )(),
    )
    taxonomy = _load(f)
    assert taxonomy is not None
    assert any(
        "xml" in line.lower() or "rdf" in line.lower() or "mismatch" in line.lower() or "⚠" in line
        for line in output
    )


def test_backconvert_prompt_mentions_original_name(tmp_path):
    ttl = tmp_path / "onto.ttl"
    ttl.write_text(_TTL)
    original = tmp_path / "onto.owl"
    original.write_text(_RDF_XML)

    with patch("ster.cli.Confirm.ask", return_value=False) as mock_ask:
        _maybe_backconvert(ttl, "stale-hash", original)

    prompt_text = mock_ask.call_args[0][0]
    assert "onto.owl" in prompt_text
