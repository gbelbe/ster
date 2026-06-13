"""Map a detail-view field edit to a core ``Command``.

The Textual detail rows carry their ``DetailField``; when the user edits one,
this pure dispatch turns ``(field, uri, path, new_value)`` into the right
self-applying ``Command`` (executed by ``TaxonomyService``). Kept free of Textual
so it is trivially unit-testable; it grows one mapping per field type as the
per-entity phases land.
"""

from __future__ import annotations

from pathlib import Path

from ster.core.commands import OwlSetLabel
from ster.nav.logic import DetailField


def edit_command(field: DetailField, uri: str, path: Path, value: str) -> object | None:
    """Return the Command for editing *field* to *value*, or None if unsupported.

    (Phase 0 starts with the OWL ``rdfs:label`` row; later phases extend this.)
    """
    ftype = field.meta.get("type")
    if ftype == "rdf_label":
        return OwlSetLabel(path, uri, field.meta.get("lang", "en"), value)
    return None
