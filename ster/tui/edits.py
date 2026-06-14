"""Map a detail-view field edit / action to a core ``Command``.

The Textual detail rows carry their ``DetailField``; when the user activates one,
this pure dispatch turns it into the right self-applying ``Command`` (executed by
``TaxonomyService``). Kept free of Textual so it is trivially unit-testable.

Each of the five flavours is a **registry table** keyed by field-type or action,
mapping to a small factory. Adding a new operation is one table row — no growing
``if/elif`` chain, so every dispatcher stays at complexity ~2 regardless of how
many entities/operations land:

- ``edit_command``     — editable value rows → text modal.        (keyed by meta ``type``)
- ``action_command``   — constructive ``INPUT_ACTIONS`` → text modal.   (keyed by ``action``)
- ``relation_command`` — ``PICKER_ACTIONS`` → entity picker (class or concept). (by ``action``)
- ``delete_command``   — ``DELETE_CHOICES`` → choice modal.        (keyed by ``action``)
- ``direct_command``   — meta-driven rows (remove X) → run immediately. (keyed by ``action``)
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ster.core.commands import (
    AddSchemaMedia,
    OntoSetMetadata,
    OntoSetPrefix,
    OwlAddIndividualType,
    OwlAddProperty,
    OwlAddPropertyClass,
    OwlConvertClassToIndividual,
    OwlConvertIndividualToClass,
    OwlCreateIndividual,
    OwlCreateSubclass,
    OwlDeleteClass,
    OwlDeleteIndividual,
    OwlDeleteProperty,
    OwlMoveClass,
    OwlRemoveIndividualLiteral,
    OwlRemoveIndividualType,
    OwlRemoveIndividualValue,
    OwlRemovePropertyClass,
    OwlRemoveSuperclass,
    OwlSetComment,
    OwlSetIndividualLiteral,
    OwlSetIndividualValue,
    OwlSetLabel,
    OwlSetNote,
    RemoveSchemaMedia,
    RenameEntity,
    SkosAddConcept,
    SkosAddRelated,
    SkosCreateScheme,
    SkosMoveConcept,
    SkosRemoveConcept,
    SkosSetDefinition,
    SkosSetLabel,
    SkosSetSchemeField,
    SkosSetScopeNote,
)
from ster.nav.logic import DetailField

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

# ── edit_command — editable value rows (keyed by meta "type") ───────────────────

_EditFactory = Callable[[DetailField, str, Path, str, str], object]


def _onto_meta_factory(field_name: str) -> _EditFactory:
    """Closure over the OntoSetMetadata field_name (ontology-wide; uri ignored)."""
    return lambda f, u, p, v, lang: OntoSetMetadata(p, field_name, v)


def _scheme_field_factory(field_name: str) -> _EditFactory:
    """Closure over the SkosSetSchemeField field_name."""
    return lambda f, u, p, v, lang: SkosSetSchemeField(p, u, field_name, v, f.meta.get("lang", ""))


def _build_edit_registry() -> dict[str, _EditFactory]:
    reg: dict[str, _EditFactory] = {
        "rdf_label": lambda f, u, p, v, lang: OwlSetLabel(p, u, lang, v),
        "ind_label": lambda f, u, p, v, lang: OwlSetLabel(p, u, lang, v),
        "prop_label": lambda f, u, p, v, lang: OwlSetLabel(p, u, lang, v),
        "uri": lambda f, u, p, v, lang: RenameEntity(p, u, v),  # cascades across every layer
        "pref": lambda f, u, p, v, lang: SkosSetLabel(p, u, lang, v, kind="pref"),
        "alt": lambda f, u, p, v, lang: SkosSetLabel(p, u, lang, v, kind="alt"),
        "def": lambda f, u, p, v, lang: SkosSetDefinition(p, u, lang, v),
        "scope_note": lambda f, u, p, v, lang: SkosSetScopeNote(p, u, lang, v),
    }
    reg.update({ftype: _onto_meta_factory(name) for ftype, name in _ONTO_META.items()})
    reg.update({ftype: _scheme_field_factory(name) for ftype, name in _SCHEME_FIELDS.items()})
    return reg


_EDIT_REGISTRY = _build_edit_registry()


def edit_command(field: DetailField, uri: str, path: Path, value: str) -> object | None:
    """Return the Command for editing an editable value row, or None if unsupported."""
    factory = _EDIT_REGISTRY.get(field.meta.get("type", ""))
    return factory(field, uri, path, value, field.meta.get("lang", "en")) if factory else None


# ── action_command — constructive text-input rows (keyed by "action") ───────────

# Action rows whose handler collects a single text/URI value via the edit modal.
# Maps action → (prompt, prefill-kind) where prefill-kind is "base_uri" or "".
INPUT_ACTIONS: dict[str, tuple[str, str]] = {
    "add_rdf_comment": ("rdfs:comment", ""),
    "add_ind_comment": ("rdfs:comment", ""),
    "add_prop_comment": ("rdfs:comment", ""),
    "add_rdf_label": ("New rdfs:label", ""),
    "add_ind_label": ("New rdfs:label", ""),
    "add_prop_label": ("New rdfs:label", ""),
    "new_subclass": ("New subclass URI", "base_uri"),
    "add_individual": ("New individual URI", "base_uri"),
    "edit_ontology_prefix": ("Ontology prefix", ""),
    "create_owl_class": ("New OWL class URI", "base_uri"),
    "create_owl_property": ("New OWL property URI", "base_uri"),
    "add_pref_label": ("New prefLabel", ""),
    "add_alt_label": ("New altLabel", ""),
    "add_def": ("skos:definition", ""),
    "add_scope_note": ("skos:scopeNote", ""),
    "add_narrower": ("New narrower concept URI", "base_uri"),
    "add_top_concept": ("New top-concept URI", "base_uri"),
    "add_schema_image": ("schema:image URL", ""),
    "add_schema_video": ("schema:video URL", ""),
    "add_schema_url": ("schema:url (external link)", ""),
    "edit_note": ("Note (markdown)", ""),
}

_ActionFactory = Callable[[str, Path, str, str], object]

_ACTION_REGISTRY: dict[str, _ActionFactory] = {
    "add_rdf_comment": lambda u, p, v, lang: OwlSetComment(p, u, lang, v),
    "add_ind_comment": lambda u, p, v, lang: OwlSetComment(p, u, lang, v),
    "add_prop_comment": lambda u, p, v, lang: OwlSetComment(p, u, lang, v),
    "add_rdf_label": lambda u, p, v, lang: OwlSetLabel(p, u, lang, v),
    "add_ind_label": lambda u, p, v, lang: OwlSetLabel(p, u, lang, v),
    "add_prop_label": lambda u, p, v, lang: OwlSetLabel(p, u, lang, v),
    "new_subclass": lambda u, p, v, lang: OwlCreateSubclass(p, v, u),
    "add_individual": lambda u, p, v, lang: OwlCreateIndividual(p, v, u),
    "edit_ontology_prefix": lambda u, p, v, lang: OntoSetPrefix(p, v),
    # create from the overview: u is the overview sentinel (ignored), v is the new URI.
    "create_owl_class": lambda u, p, v, lang: OwlCreateSubclass(p, v, None),  # top-level class
    "create_owl_property": lambda u, p, v, lang: OwlAddProperty(p, v, "ObjectProperty", "", lang),
    "add_pref_label": lambda u, p, v, lang: SkosSetLabel(p, u, lang, v, kind="pref"),
    "add_alt_label": lambda u, p, v, lang: SkosSetLabel(p, u, lang, v, kind="alt"),
    "add_def": lambda u, p, v, lang: SkosSetDefinition(p, u, lang, v),
    "add_scope_note": lambda u, p, v, lang: SkosSetScopeNote(p, u, lang, v),
    # uri = parent concept / scheme handle; the new concept starts label-less.
    "add_narrower": lambda u, p, v, lang: SkosAddConcept(p, v, {}, parent_handle=u),
    "add_top_concept": lambda u, p, v, lang: SkosAddConcept(p, v, {}, parent_handle=u),
    "add_schema_image": lambda u, p, v, lang: AddSchemaMedia(p, u, "image", v),
    "add_schema_video": lambda u, p, v, lang: AddSchemaMedia(p, u, "video", v),
    "add_schema_url": lambda u, p, v, lang: AddSchemaMedia(p, u, "url", v),
    "edit_note": lambda u, p, v, lang: OwlSetNote(p, u, v),
}


def action_command(
    action: str, uri: str, path: Path, value: str, lang: str = "en"
) -> object | None:
    """Return the Command for a constructive action row given the typed *value*."""
    factory = _ACTION_REGISTRY.get(action)
    return factory(uri, path, value, lang) if factory else None


# ── relation_command — picker-driven links (keyed by "action") ──────────────────

# Action rows that pick an existing entity (via PickerModal).
# Maps action → (prompt, candidate-kind "class" | "concept").
PICKER_ACTIONS: dict[str, tuple[str, str]] = {
    "link_superclass": ("Add a superclass — pick a class", "class"),
    "add_ind_type": ("Add a class membership — pick a class", "class"),
    "add_prop_domain": ("Add a domain class — pick a class", "class"),
    "add_prop_range": ("Add a range class — pick a class", "class"),
    "link_broader": ("Link to a broader concept — pick a concept", "concept"),
    "move": ("Move under a different parent — pick a concept", "concept"),
    "add_related": ("Add a related concept — pick a concept", "concept"),
}

_RelationFactory = Callable[[str, Path, str], object]

_RELATION_REGISTRY: dict[str, _RelationFactory] = {
    "link_superclass": lambda s, p, t: OwlMoveClass(p, s, t, replace=False),  # additive
    "add_ind_type": lambda s, p, t: OwlAddIndividualType(p, s, t),
    "add_prop_domain": lambda s, p, t: OwlAddPropertyClass(p, s, "domain", t),
    "add_prop_range": lambda s, p, t: OwlAddPropertyClass(p, s, "range", t),
    "link_broader": lambda s, p, t: SkosMoveConcept(p, s, t, replace=False),  # extra parent
    "move": lambda s, p, t: SkosMoveConcept(p, s, t, replace=True),  # re-parent
    "add_related": lambda s, p, t: SkosAddRelated(p, s, t),
}


def relation_command(action: str, source_uri: str, path: Path, target_uri: str) -> object | None:
    """Return the Command linking *source_uri* to the picked *target_uri*."""
    factory = _RELATION_REGISTRY.get(action)
    return factory(source_uri, path, target_uri) if factory else None


# ── delete_command — destructive choice-driven rows (keyed by "action") ─────────

# Destructive action rows whose handler asks the user to pick an option first.
# Maps action → [(option label, value)]; the value is the delete mode / cascade flag.
DELETE_CHOICES: dict[str, list[tuple[str, str]]] = {
    "delete_class": [
        ("Keep subclasses & instances (re-link to parents)", "keep_all"),
        ("Delete subclasses too", "cascade_subclasses"),
        ("Delete the class and everything below it", "delete_all"),
    ],
    "delete_individual": [("Delete this individual", "delete")],
    "delete_property": [
        ("Delete declaration only", "decl"),
        ("Delete and strip its values from every individual", "strip"),
    ],
    "delete": [
        ("Keep narrower concepts (re-link to parents)", "keep"),
        ("Delete the concept and its descendants", "cascade"),
    ],
}

_DeleteFactory = Callable[[str, Path, str], object]

_DELETE_REGISTRY: dict[str, _DeleteFactory] = {
    "delete_class": lambda u, p, c: OwlDeleteClass(p, u, c),
    "delete_individual": lambda u, p, c: OwlDeleteIndividual(p, u),
    "delete_property": lambda u, p, c: OwlDeleteProperty(p, u, clear_values=(c == "strip")),
    "delete": lambda u, p, c: SkosRemoveConcept(p, u, cascade=(c == "cascade")),
}


def delete_command(action: str, uri: str, path: Path, choice: str) -> object | None:
    """Return the destructive Command for *action* with the chosen option."""
    factory = _DELETE_REGISTRY.get(action)
    return factory(uri, path, choice) if factory else None


# ── direct_command — meta-driven removals that run immediately (keyed by action) ─

_DirectFactory = Callable[[DetailField, str, Path], object]

_DIRECT_REGISTRY: dict[str, _DirectFactory] = {
    "remove_superclass": lambda f, u, p: OwlRemoveSuperclass(p, u, f.meta["parent_uri"]),
    "remove_ind_type": lambda f, u, p: OwlRemoveIndividualType(p, u, f.meta["type_uri"]),
    "remove_prop_domain": lambda f, u, p: OwlRemovePropertyClass(
        p, u, "domain", f.meta["domain_uri"]
    ),
    "remove_prop_range": lambda f, u, p: OwlRemovePropertyClass(p, u, "range", f.meta["range_uri"]),
    "remove_prop_value": lambda f, u, p: OwlRemoveIndividualValue(
        p, u, f.meta["prop_uri"], f.meta["val_uri"]
    ),
    "remove_literal_value": lambda f, u, p: OwlRemoveIndividualLiteral(
        p, u, f.meta["prop_uri"], f.meta["val_str"], f.meta["lang_or_dt"]
    ),
    "delete_note": lambda f, u, p: OwlSetNote(p, u, ""),  # clear the note
    "remove_schema_image": lambda f, u, p: RemoveSchemaMedia(p, u, "image", f.meta["url"]),
    "remove_schema_video": lambda f, u, p: RemoveSchemaMedia(p, u, "video", f.meta["url"]),
    "remove_schema_url": lambda f, u, p: RemoveSchemaMedia(p, u, "url", f.meta["url"]),
}


def direct_command(field: DetailField, uri: str, path: Path) -> object | None:
    """Return the Command for a meta-driven row that runs immediately (no modal).

    These are targeted removals — the row already names the specific target via
    its meta (e.g. "✗ Remove subClassOf Mammal").
    """
    factory = _DIRECT_REGISTRY.get(field.meta.get("action", ""))
    return factory(field, uri, path) if factory else None


# ── meta-aware edits — change one existing individual value (row carries meta) ──

# These rows name the operation's fixed parameters via their meta (which
# predicate / value / prop-type / range). A modal collects the new text value;
# the command reads the meta. action → (prompt, prefill-source): the prefill
# source is a meta-key holding the current value, or the sentinel "base_uri".
META_INPUT_ACTIONS: dict[str, tuple[str, str]] = {
    "edit_literal_value": ("New literal value", "val_str"),
    "add_class_property": ("New property URI", "base_uri"),
}


def meta_input_command(
    field: DetailField, uri: str, path: Path, value: str, lang: str = "en"
) -> object | None:
    """Return the Command for a meta-aware text edit (change a literal / add a class property)."""
    action = field.meta.get("action")
    if action == "edit_literal_value":
        return OwlSetIndividualLiteral(
            path,
            uri,
            field.meta["prop_uri"],
            field.meta["val_str"],
            value,
            field.meta["lang_or_dt"],
        )
    if action == "add_class_property":
        # The row fixes prop_type + datatype range; value is the new property URI,
        # domain is the class. Label defaults to the URI's local name (curses parity).
        label = value.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        return OwlAddProperty(
            path,
            value,
            field.meta.get("prop_type", "ObjectProperty"),
            label,
            lang,
            field.meta.get("class_uri") or uri,
            field.meta.get("range_uri"),
        )
    return None


# action → (prompt, candidate-kind) — picks an entity, command reads the meta.
META_PICKER_ACTIONS: dict[str, tuple[str, str]] = {
    "edit_prop_value": ("Change the value — pick an individual", "individual"),
}


# Chained flows — collected over more than one modal (the app orchestrates the
# steps; these builders produce the final command once every input is known).
CHAINED_ACTIONS = frozenset({"add_prop_value"})  # → app._add_property_value
SCHEME_ACTIONS = frozenset({"add_scheme"})  # → app._create_scheme


def add_object_value_command(uri: str, path: Path, prop_uri: str, target_uri: str) -> object:
    """A new object-property value (no old value to replace)."""
    return OwlSetIndividualValue(path, uri, prop_uri, target_uri, "")


def add_literal_value_command(uri: str, path: Path, prop_uri: str, value: str) -> object:
    """A new literal-property value (no datatype/lang tag)."""
    return OwlSetIndividualLiteral(path, uri, prop_uri, "", value, "")


def _namespace_of(uri: str) -> str:
    """The base URI a scheme mints children under — its URI up to the last # or /."""
    for sep in ("#", "/"):
        if sep in uri:
            return uri.rsplit(sep, 1)[0] + sep
    return uri


def create_scheme_command(path: Path, uri: str, title: str, lang: str) -> object:
    """Create a new ``skos:ConceptScheme`` titled *title* in *lang*."""
    return SkosCreateScheme(path, uri, {lang: title}, _namespace_of(uri), (lang,))


def meta_relation_command(
    field: DetailField, uri: str, path: Path, target_uri: str
) -> object | None:
    """Return the Command for a meta-aware picker edit (e.g. change an object value)."""
    if field.meta.get("action") == "edit_prop_value":
        return OwlSetIndividualValue(
            path, uri, field.meta["prop_uri"], target_uri, field.meta["val_uri"]
        )
    return None


# ── convert_command — class ↔ individual punning (choice + live parent list) ────

# Conversions need the entity's live parent classes to offer "re-type instances",
# so the choice list is built dynamically and the command takes that parent tuple.
CONVERT_ACTIONS = frozenset({"class_to_individual", "individual_to_class"})


def convert_choices(action: str, parents: tuple[str, ...]) -> list[tuple[str, str]]:
    """The confirmation options for a punning conversion (mirrors the curses viewer)."""
    if action == "individual_to_class":
        return [("Convert to an OWL class", "go")]
    # class → individual: what becomes of individuals typed by this class?
    options = [("Delete instances typed by this class", "delete")]
    if parents:
        options.append(("Re-type instances to its parent class(es)", "reattach"))
    return options


def convert_command(
    action: str, uri: str, path: Path, choice: str, parents: tuple[str, ...]
) -> object | None:
    """Return the punning conversion Command for *action* with the chosen option."""
    if action == "individual_to_class":
        return OwlConvertIndividualToClass(path, uri)
    if action == "class_to_individual":
        reattach = parents if choice == "reattach" else None
        return OwlConvertClassToIndividual(path, uri, reattach)
    return None
