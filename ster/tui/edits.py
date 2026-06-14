"""Map a detail-view field edit / action to a core ``Command``.

The Textual detail rows carry their ``DetailField``; when the user activates one,
this pure dispatch turns it into the right self-applying ``Command`` (executed by
``TaxonomyService``). Kept free of Textual so it is trivially unit-testable; it
grows one mapping per field/action as the per-entity phases land.

Five flavours, by how the value is collected:
- ``edit_command``     — editable value rows → text modal.
- ``action_command``   — constructive ``INPUT_ACTIONS`` → text modal.
- ``relation_command`` — ``PICKER_ACTIONS`` → entity picker (class or concept).
- ``delete_command``   — ``DELETE_CHOICES`` → choice modal.
- ``direct_command``   — meta-driven rows (remove X) → run immediately.
"""

from __future__ import annotations

from pathlib import Path

from ster.core.commands import (
    OntoSetMetadata,
    OntoSetPrefix,
    OwlAddIndividualType,
    OwlCreateIndividual,
    OwlCreateSubclass,
    OwlDeleteClass,
    OwlDeleteIndividual,
    OwlMoveClass,
    OwlRemoveIndividualType,
    OwlRemoveSuperclass,
    OwlSetComment,
    OwlSetLabel,
    RenameEntity,
    SkosAddConcept,
    SkosAddRelated,
    SkosMoveConcept,
    SkosRemoveConcept,
    SkosSetDefinition,
    SkosSetLabel,
    SkosSetSchemeField,
    SkosSetScopeNote,
)
from ster.nav.logic import DetailField

_OWL_LABEL_TYPES = frozenset({"rdf_label", "ind_label", "prop_label"})
# Ontology-overview metadata rows → OntoSetMetadata field_name.
_ONTO_META = {"ont_title": "title", "ont_label": "label", "ont_description": "description"}
# Scheme metadata rows → SkosSetSchemeField field_name.
_SCHEME_FIELDS = {
    "scheme_title": "title",
    "scheme_base_uri": "base_uri",
    "scheme_creator": "creator",
    "scheme_created": "created",
    "scheme_languages": "languages",
}


def edit_command(field: DetailField, uri: str, path: Path, value: str) -> object | None:
    """Return the Command for editing an editable value row, or None if unsupported."""
    ftype = field.meta.get("type")
    lang = field.meta.get("lang", "en")
    if ftype in _OWL_LABEL_TYPES:
        return OwlSetLabel(path, uri, lang, value)
    if ftype == "uri":
        return RenameEntity(path, uri, value)  # cascades across every layer + validated
    if ftype in _ONTO_META:
        return OntoSetMetadata(path, _ONTO_META[ftype], value)  # ontology-wide (uri ignored)
    if ftype in ("pref", "alt"):
        return SkosSetLabel(path, uri, lang, value, kind=ftype)
    if ftype == "def":
        return SkosSetDefinition(path, uri, lang, value)
    if ftype == "scope_note":
        return SkosSetScopeNote(path, uri, lang, value)
    if ftype in _SCHEME_FIELDS:
        return SkosSetSchemeField(path, uri, _SCHEME_FIELDS[ftype], value, field.meta.get("lang", ""))
    return None


# Action rows whose handler collects a single text/URI value via the edit modal.
# Maps action → (prompt, prefill-kind) where prefill-kind is "base_uri" or "".
INPUT_ACTIONS: dict[str, tuple[str, str]] = {
    "add_rdf_comment": ("rdfs:comment", ""),
    "add_ind_comment": ("rdfs:comment", ""),
    "new_subclass": ("New subclass URI", "base_uri"),
    "add_individual": ("New individual URI", "base_uri"),
    "edit_ontology_prefix": ("Ontology prefix", ""),
    "add_alt_label": ("New altLabel", ""),
    "add_scope_note": ("skos:scopeNote", ""),
    "add_narrower": ("New narrower concept URI", "base_uri"),
    "add_top_concept": ("New top-concept URI", "base_uri"),
}


def action_command(action: str, uri: str, path: Path, value: str, lang: str = "en") -> object | None:
    """Return the Command for a constructive action row given the typed *value*."""
    if action in ("add_rdf_comment", "add_ind_comment"):
        return OwlSetComment(path, uri, lang, value)
    if action == "new_subclass":
        return OwlCreateSubclass(path, value, uri)
    if action == "add_individual":
        return OwlCreateIndividual(path, value, uri)
    if action == "edit_ontology_prefix":
        return OntoSetPrefix(path, value)
    if action == "add_alt_label":
        return SkosSetLabel(path, uri, lang, value, kind="alt")
    if action == "add_scope_note":
        return SkosSetScopeNote(path, uri, lang, value)
    if action in ("add_narrower", "add_top_concept"):
        # uri = parent concept / scheme handle; the new concept starts label-less.
        return SkosAddConcept(path, value, {}, parent_handle=uri)
    return None


# Action rows that pick an existing entity (via PickerModal).
# Maps action → (prompt, candidate-kind "class" | "concept").
PICKER_ACTIONS: dict[str, tuple[str, str]] = {
    "link_superclass": ("Add a superclass — pick a class", "class"),
    "add_ind_type": ("Add a class membership — pick a class", "class"),
    "link_broader": ("Link to a broader concept — pick a concept", "concept"),
    "move": ("Move under a different parent — pick a concept", "concept"),
    "add_related": ("Add a related concept — pick a concept", "concept"),
}


def relation_command(action: str, source_uri: str, path: Path, target_uri: str) -> object | None:
    """Return the Command linking *source_uri* to the picked *target_uri*."""
    if action == "link_superclass":
        return OwlMoveClass(path, source_uri, target_uri, replace=False)  # additive
    if action == "add_ind_type":
        return OwlAddIndividualType(path, source_uri, target_uri)
    if action == "link_broader":
        return SkosMoveConcept(path, source_uri, target_uri, replace=False)  # extra parent
    if action == "move":
        return SkosMoveConcept(path, source_uri, target_uri, replace=True)  # re-parent
    if action == "add_related":
        return SkosAddRelated(path, source_uri, target_uri)
    return None


# Destructive action rows whose handler asks the user to pick an option first.
# Maps action → [(option label, value)]; the value is the delete mode / cascade flag.
DELETE_CHOICES: dict[str, list[tuple[str, str]]] = {
    "delete_class": [
        ("Keep subclasses & instances (re-link to parents)", "keep_all"),
        ("Delete subclasses too", "cascade_subclasses"),
        ("Delete the class and everything below it", "delete_all"),
    ],
    "delete_individual": [("Delete this individual", "delete")],
    "delete": [
        ("Keep narrower concepts (re-link to parents)", "keep"),
        ("Delete the concept and its descendants", "cascade"),
    ],
}


def delete_command(action: str, uri: str, path: Path, choice: str) -> object | None:
    """Return the destructive Command for *action* with the chosen option."""
    if action == "delete_class":
        return OwlDeleteClass(path, uri, choice)
    if action == "delete_individual":
        return OwlDeleteIndividual(path, uri)
    if action == "delete":
        return SkosRemoveConcept(path, uri, cascade=(choice == "cascade"))
    return None


def direct_command(field: DetailField, uri: str, path: Path) -> object | None:
    """Return the Command for a meta-driven row that runs immediately (no modal).

    These are targeted removals — the row already names the specific target via
    its meta (e.g. "✗ Remove subClassOf Mammal").
    """
    action = field.meta.get("action")
    if action == "remove_superclass":
        return OwlRemoveSuperclass(path, uri, field.meta["parent_uri"])
    if action == "remove_ind_type":
        return OwlRemoveIndividualType(path, uri, field.meta["type_uri"])
    return None
