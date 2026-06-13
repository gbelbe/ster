"""Map a detail-view field edit to a core ``Command``.

The Textual detail rows carry their ``DetailField``; when the user edits one,
this pure dispatch turns ``(field, uri, path, new_value)`` into the right
self-applying ``Command`` (executed by ``TaxonomyService``). Kept free of Textual
so it is trivially unit-testable; it grows one mapping per field type as the
per-entity phases land.
"""

from __future__ import annotations

from pathlib import Path

from ster.core.commands import (
    OwlCreateIndividual,
    OwlCreateSubclass,
    OwlDeleteClass,
    OwlSetComment,
    OwlSetLabel,
)
from ster.nav.logic import DetailField


def edit_command(field: DetailField, uri: str, path: Path, value: str) -> object | None:
    """Return the Command for editing *field* to *value*, or None if unsupported.

    (Phase 0 starts with the OWL ``rdfs:label`` row; later phases extend this.)
    """
    ftype = field.meta.get("type")
    if ftype == "rdf_label":
        return OwlSetLabel(path, uri, field.meta.get("lang", "en"), value)
    return None


# Action rows whose handler collects a single text/URI value via the edit modal.
# Maps action → (prompt, prefill-kind) where prefill-kind is "base_uri" or "".
INPUT_ACTIONS: dict[str, tuple[str, str]] = {
    "add_rdf_comment": ("rdfs:comment", ""),
    "new_subclass": ("New subclass URI", "base_uri"),
    "add_individual": ("New individual URI", "base_uri"),
}


def action_command(
    action: str, uri: str, path: Path, value: str, lang: str = "en"
) -> object | None:
    """Return the Command for a constructive action row given the typed *value*.

    *uri* is the entity the action was triggered from (the parent class for
    new_subclass / add_individual, or the comment target). Returns None for
    actions not yet wired (pickers, conversions, deletes — handled elsewhere).
    """
    if action == "add_rdf_comment":
        return OwlSetComment(path, uri, lang, value)
    if action == "new_subclass":
        return OwlCreateSubclass(path, value, uri)
    if action == "add_individual":
        return OwlCreateIndividual(path, value, uri)
    return None


# Destructive action rows whose handler asks the user to pick a mode first.
# Maps action → (prompt-template, [(option label, mode value)]).
DELETE_CHOICES: dict[str, list[tuple[str, str]]] = {
    "delete_class": [
        ("Keep subclasses & instances (re-link to parents)", "keep_all"),
        ("Delete subclasses too", "cascade_subclasses"),
        ("Delete the class and everything below it", "delete_all"),
    ],
}


def delete_command(action: str, uri: str, path: Path, mode: str) -> object | None:
    """Return the destructive Command for *action* with the chosen *mode*."""
    if action == "delete_class":
        return OwlDeleteClass(path, uri, mode)
    return None
