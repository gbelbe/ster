"""Format conversion between RDF serialisations (used by the RDF/XML→TTL working-copy flow)."""

from __future__ import annotations

from pathlib import Path

from ._format import _detect_format
from ._graph_io import _parse_graph


def convert(input_path: Path, output_path: Path) -> Path:
    """Load *input_path* and serialise to *output_path* (formats from extensions)."""
    out_fmt = _detect_format(output_path)
    g = _parse_graph(input_path)
    g.serialize(destination=str(output_path), format=out_fmt)
    return output_path


def convert_to_ttl(input_path: Path, output_path: Path | None = None) -> Path:
    """Convert *input_path* to Turtle, writing to *output_path* (default: same stem + .ttl)."""
    if output_path is None:
        output_path = input_path.with_suffix(".ttl")
    return convert(input_path, output_path)
