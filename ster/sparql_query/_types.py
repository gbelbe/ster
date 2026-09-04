"""Shared value types for the SPARQL query engine.

``QueryResult`` and ``PresetQuery`` are the small data carriers every other
submodule in this package builds on; ``UriIndex`` is the shape of the
prefix -> names completion index built by ``_uri_index.py`` and consumed by
``_autocomplete.py``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class QueryResult:
    """Normalised result from any SPARQL query type."""

    columns: list[str]
    rows: list[list[str]]  # every cell is a plain string
    error: str = ""
    query_type: str = "SELECT"  # SELECT | ASK | CONSTRUCT | DESCRIBE


@dataclass
class PresetQuery:
    label: str
    description: str
    sparql: str


UriIndex = dict[str, dict[str, list[str] | dict[str, list[str]]]]
