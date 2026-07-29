from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from ster import store

_VALID_TTL = (
    "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
    "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
    "@prefix ex: <https://example.org/> .\n"
    "ex:Scheme a skos:ConceptScheme .\n"
    "ex:Concept a skos:Concept ; skos:inScheme ex:Scheme .\n"
)


def test_parse_into_uses_oxigraph(tmp_path: Path):
    """Verify that _parse_into attempts to use Oxigraph for non-NT formats."""
    ttl = tmp_path / "test.ttl"
    ttl.write_text(_VALID_TTL)

    with patch("ster.store.Graph") as mock_graph_cls:
        # Mock Graph(store="Oxigraph")
        mock_oxigraph = MagicMock()
        # First call returns Oxigraph, second (if any) returns normal Graph
        mock_graph_cls.side_effect = [mock_oxigraph, MagicMock()]

        store._parse_into("turtle", ttl)

        # Verify it was instantiated with Oxigraph
        mock_graph_cls.assert_any_call(store="Oxigraph")
        assert mock_oxigraph.parse.called


def test_parse_into_oxigraph_fallback(tmp_path: Path):
    """Verify that _parse_into falls back to standard Graph if Oxigraph fails."""
    ttl = tmp_path / "test.ttl"
    ttl.write_text(_VALID_TTL)

    with patch("ster.store.Graph") as mock_graph_cls:
        # First call (Oxigraph) fails (e.g. pyoxigraph not installed or ValueError)
        mock_normal = MagicMock()
        mock_graph_cls.side_effect = [ValueError("failed to load Oxigraph store"), mock_normal]

        store._parse_into("turtle", ttl)

        # Should have fallen back to normal Graph
        mock_graph_cls.assert_any_call()
        assert mock_normal.parse.called
