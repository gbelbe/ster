"""Reading the tracked RDF file as it stood at a revision."""

from __future__ import annotations

from pathlib import Path

from rdflib import Graph

from semanticdiff.git_log import read_blob

_FORMATS = {
    ".ttl": "turtle",
    ".n3": "n3",
    ".nt": "nt",
    ".nq": "nquads",
    ".trig": "trig",
    ".rdf": "xml",
    ".owl": "xml",
    ".xml": "xml",
    ".jsonld": "json-ld",
}


class UnreadableRevisionError(RuntimeError):
    """The file exists at that revision but does not parse as RDF."""


def graph_at_rev(repo: Path, rev: str, path: str) -> Graph | None:
    """The parsed graph at `rev`, or None when the file does not exist there."""
    blob = read_blob(repo, rev, path)
    if blob is None:
        return None
    graph = Graph()
    try:
        graph.parse(data=blob, format=_FORMATS.get(Path(path).suffix.lower(), "turtle"))
    except Exception as exc:
        raise UnreadableRevisionError(f"{path} at {rev} does not parse: {exc}") from exc
    return graph
