"""Unit tests for SPARQL modal — viz refresh helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ster.model import RDFClass, Taxonomy
from ster.viz_vowl import refresh_query_result_in_browser

_KAI_NS = "https://ex.org/kai/"
_PORT = 18765


def _tax_with_individual() -> tuple[Taxonomy, str]:
    tax = Taxonomy()
    uri = _KAI_NS + "Digital"
    tax.owl_classes[uri] = RDFClass(uri=uri)
    return tax, uri


# ── refresh_query_result_in_browser ──────────────────────────────────────────


def test_refresh_writes_html_to_existing_path(tmp_path: Path) -> None:
    tax, uri = _tax_with_individual()
    out = tmp_path / "result.html"
    out.write_text("old", encoding="utf-8")
    with (
        patch("ster.viz_vowl.webbrowser.open"),
        patch("ster.viz_vowl._ensure_server", return_value=_PORT),
    ):
        refresh_query_result_in_browser(tax, {uri}, out)
    assert out.read_text(encoding="utf-8") != "old"
    assert "<html" in out.read_text(encoding="utf-8").lower()


def test_refresh_calls_webbrowser_open(tmp_path: Path) -> None:
    tax, uri = _tax_with_individual()
    out = tmp_path / "result.html"
    out.write_text("old", encoding="utf-8")
    mock_open = MagicMock()
    with (
        patch("ster.viz_vowl.webbrowser.open", mock_open),
        patch("ster.viz_vowl._ensure_server", return_value=_PORT),
    ):
        refresh_query_result_in_browser(tax, {uri}, out)
    mock_open.assert_called_once()
    url = mock_open.call_args[0][0]
    assert str(_PORT) in url
    assert out.name in url


def test_refresh_no_matching_uris_raises_value_error(tmp_path: Path) -> None:
    tax = Taxonomy()
    out = tmp_path / "result.html"
    out.write_text("old", encoding="utf-8")
    with pytest.raises(ValueError, match="No taxonomy nodes"):
        refresh_query_result_in_browser(tax, {"https://unknown/X"}, out)


def test_refresh_preserves_given_path(tmp_path: Path) -> None:
    tax, uri = _tax_with_individual()
    out = tmp_path / "my_custom_result.html"
    out.write_text("x", encoding="utf-8")
    with (
        patch("ster.viz_vowl.webbrowser.open"),
        patch("ster.viz_vowl._ensure_server", return_value=_PORT),
    ):
        refresh_query_result_in_browser(tax, {uri}, out)
    assert out.exists()
    assert not (tmp_path / "other.html").exists()
