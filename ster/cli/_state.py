"""Shared in-process mutable CLI state (module-level singletons)."""

from __future__ import annotations

from pathlib import Path

session_file: Path | None = None  # in-process cache
ci_check_done: bool = False  # guard: prompt at most once per process
rdfxml_checked: bool = False  # guard: RDF/XML conversion prompt fires once per process
converted_from: Path | None = None  # original RDF/XML path when a TTL was auto-converted
