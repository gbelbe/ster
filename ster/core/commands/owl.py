"""OWL-layer commands — act on ``owl:Class`` entities (``rdfs:subClassOf``)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...exceptions import CircularHierarchyError, ClassNotFoundError, URIAlreadyExistsError
from ...handles import assign_handles
from ...model import RDFClass, Taxonomy
from ...operations import (
    add_external_superclass,
    add_individual_type,
    add_owl_individual,
    add_owl_property,
    add_property_class,
    add_subclass_of,
    clear_property_values,
    convert_class_to_individual,
    convert_individual_to_class,
    delete_owl_class,
    delete_owl_individual,
    delete_owl_property,
    remove_entity_annotation,
    remove_individual_literal,
    remove_individual_property_value,
    remove_individual_type,
    remove_owl_comment,
    remove_owl_label,
    remove_property_class,
    remove_subclass_of,
    rename_entity_uri,
    set_entity_annotation,
    set_individual_literal,
    set_individual_property_value,
    set_owl_comment,
    set_owl_label,
    set_owl_note,
)

_LangPairs = tuple[tuple[str, str], ...]  # ((lang, value), …) — frozen-friendly


def _set_localized(taxonomy: Taxonomy, uri: str, pairs: _LangPairs, *, kind: str) -> None:
    """Apply a label/comment desired-state: a non-empty value upserts, an empty one
    removes that language's entry. *kind* is ``"label"`` or ``"comment"``."""
    set_fn = set_owl_label if kind == "label" else set_owl_comment
    remove_fn = remove_owl_label if kind == "label" else remove_owl_comment
    for lang, value in pairs:
        if value:
            set_fn(taxonomy, uri, lang, value)
        else:
            remove_fn(taxonomy, uri, lang)


@dataclass(frozen=True)
class OwlMoveClass:
    """Reparent an OWL class via ``rdfs:subClassOf``.

    ``replace=True`` sets *new_parent_uri* as the sole superclass (or detaches to
    the top when ``None``); ``replace=False`` adds it (polyhierarchy).
    """

    target_path: Path
    source_uri: str
    new_parent_uri: str | None
    replace: bool = True

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        rdf_class = taxonomy.owl_classes.get(self.source_uri)
        if rdf_class is None:
            raise ClassNotFoundError(self.source_uri)
        if self.replace:
            rdf_class.sub_class_of = [self.new_parent_uri] if self.new_parent_uri else []
        elif self.new_parent_uri:
            add_subclass_of(taxonomy, self.source_uri, self.new_parent_uri)
        return (self.source_uri,)


@dataclass(frozen=True)
class OwlDeleteClass:
    """Delete an OWL class. ``mode`` is ``keep_all`` / ``cascade_subclasses`` / ``delete_all``."""

    target_path: Path
    class_uri: str
    mode: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        delete_owl_class(taxonomy, self.class_uri, mode=self.mode)
        return (self.class_uri,)


@dataclass(frozen=True)
class OwlCreateSubclass:
    """Create an OWL class (if absent) and link it under *parent_uri* (rdfs:subClassOf).

    A circular or missing-parent link is ignored — the class is still created (the
    inline handler swallowed those errors too).
    """

    target_path: Path
    class_uri: str
    parent_uri: str | None

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        if self.class_uri not in taxonomy.owl_classes:
            if taxonomy.uri_taken(self.class_uri):  # a concept/individual/property owns it
                raise URIAlreadyExistsError(self.class_uri)
            taxonomy.owl_classes[self.class_uri] = RDFClass(uri=self.class_uri)
        if self.parent_uri:
            try:
                add_subclass_of(taxonomy, self.class_uri, self.parent_uri)
            except (CircularHierarchyError, ClassNotFoundError):
                pass
        assign_handles(taxonomy)
        return (self.class_uri,)


@dataclass(frozen=True)
class OwlCreateClass:
    """Create an OWL class (under *parent_uri*, or top-level) with its rdfs:label /
    rdfs:comment in one step. Empty values are skipped (no blank labels)."""

    target_path: Path
    class_uri: str
    parent_uri: str | None = None
    labels: _LangPairs = ()
    comments: _LangPairs = ()

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        if self.class_uri not in taxonomy.owl_classes:
            if taxonomy.uri_taken(self.class_uri):  # a concept/individual/property owns it
                raise URIAlreadyExistsError(self.class_uri)
            taxonomy.owl_classes[self.class_uri] = RDFClass(uri=self.class_uri)
        if self.parent_uri:
            try:
                add_subclass_of(taxonomy, self.class_uri, self.parent_uri)
            except (CircularHierarchyError, ClassNotFoundError):
                pass
        for lang, value in self.labels:
            if value:
                set_owl_label(taxonomy, self.class_uri, lang, value)
        for lang, value in self.comments:
            if value:
                set_owl_comment(taxonomy, self.class_uri, lang, value)
        assign_handles(taxonomy)
        return (self.class_uri,)


@dataclass(frozen=True)
class OwlSaveClass:
    """Edit an existing class: rename it when *new_uri* differs (cascading across
    references), then apply the label/comment desired-state — non-empty values
    upsert, empty ones clear that language."""

    target_path: Path
    old_uri: str
    new_uri: str
    labels: _LangPairs = ()
    comments: _LangPairs = ()

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        uri = self.old_uri
        if self.new_uri and self.new_uri != self.old_uri:
            rename_entity_uri(taxonomy, self.old_uri, self.new_uri)
            uri = self.new_uri
        _set_localized(taxonomy, uri, self.labels, kind="label")
        _set_localized(taxonomy, uri, self.comments, kind="comment")
        assign_handles(taxonomy)
        return (uri,)


@dataclass(frozen=True)
class OwlSaveProperty:
    """Edit an existing property: rename it when *new_uri* differs (cascading across
    references), apply the rdfs:label / rdfs:comment desired-state (empty clears a
    language), and replace its domain / range with *domains* / *ranges* (desired state;
    empty tuples clear them)."""

    target_path: Path
    old_uri: str
    new_uri: str
    labels: _LangPairs = ()
    comments: _LangPairs = ()
    domains: tuple[str, ...] = ()
    ranges: tuple[str, ...] = ()

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        uri = self.old_uri
        if self.new_uri and self.new_uri != self.old_uri:
            rename_entity_uri(taxonomy, self.old_uri, self.new_uri)
            uri = self.new_uri
        _set_localized(taxonomy, uri, self.labels, kind="label")
        _set_localized(taxonomy, uri, self.comments, kind="comment")
        prop = taxonomy.owl_properties.get(uri)
        if prop is not None:
            prop.domains = list(self.domains)
            prop.ranges = list(self.ranges)
        assign_handles(taxonomy)
        return (uri,)


@dataclass(frozen=True)
class OwlCreateIndividual:
    """Create an OWL individual, typed as *class_uri* when given (no-op if present)."""

    target_path: Path
    uri: str
    class_uri: str | None

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        add_owl_individual(taxonomy, self.uri, self.class_uri)
        assign_handles(taxonomy)
        return (self.uri,)


_ValuePairs = tuple[tuple[str, str], ...]  # ((prop_uri, value), …)


def _apply_individual_values(
    taxonomy: Taxonomy, uri: str, obj_values: _ValuePairs, lit_values: _ValuePairs
) -> None:
    """Set an individual's object- and literal-property values (skipping empty ones)."""
    for prop_uri, target in obj_values:
        if target:
            set_individual_property_value(taxonomy, uri, prop_uri, target, "")
    for prop_uri, value in lit_values:
        if value:
            set_individual_literal(taxonomy, uri, prop_uri, "", value, "")


@dataclass(frozen=True)
class OwlCreateIndividualFull:
    """Create an OWL individual with its type, ``rdfs:label`` / ``rdfs:comment`` and
    property values in one step — the add-individual modal's command. Empty values
    are skipped."""

    target_path: Path
    uri: str
    type_uri: str | None = None
    labels: _LangPairs = ()
    comments: _LangPairs = ()
    obj_values: _ValuePairs = ()
    lit_values: _ValuePairs = ()

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        add_owl_individual(taxonomy, self.uri, self.type_uri)
        for lang, value in self.labels:
            if value:
                set_owl_label(taxonomy, self.uri, lang, value)
        for lang, value in self.comments:
            if value:
                set_owl_comment(taxonomy, self.uri, lang, value)
        _apply_individual_values(taxonomy, self.uri, self.obj_values, self.lit_values)
        assign_handles(taxonomy)
        return (self.uri,)


@dataclass(frozen=True)
class OwlSaveIndividual:
    """Edit an existing individual: rename it when *new_uri* differs (cascading across
    references), then apply the label/comment desired-state — non-empty values upsert,
    empty ones clear that language. Types and property values are left untouched
    (managed via the per-row actions)."""

    target_path: Path
    old_uri: str
    new_uri: str
    labels: _LangPairs = ()
    comments: _LangPairs = ()

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        uri = self.old_uri
        if self.new_uri and self.new_uri != self.old_uri:
            rename_entity_uri(taxonomy, self.old_uri, self.new_uri)
            uri = self.new_uri
        _set_localized(taxonomy, uri, self.labels, kind="label")
        _set_localized(taxonomy, uri, self.comments, kind="comment")
        assign_handles(taxonomy)
        return (uri,)


@dataclass(frozen=True)
class OwlAddProperty:
    """Create an OWL property. A bare property passes prop_type='ObjectProperty'
    with an empty label and no domain/range — matching ``OWLProperty(uri=…)``."""

    target_path: Path
    uri: str
    prop_type: str
    label: str
    lang: str
    domain_uri: str | None = None
    range_uri: str | None = None

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        add_owl_property(
            taxonomy,
            self.uri,
            self.prop_type,
            self.label,
            self.lang,
            self.domain_uri,
            self.range_uri,
        )
        assign_handles(taxonomy)
        return (self.uri,)


@dataclass(frozen=True)
class OwlSetLabel:
    """Set an OWL class/individual/property ``rdfs:label`` for *lang*.

    A non-empty value upserts; an empty one *removes* that language's label
    (clearing the field deletes the triple rather than leaving ``rdfs:label ""``,
    which would still count as "labelled"). Mirrors the batch ``_set_localized``."""

    target_path: Path
    uri: str
    lang: str
    value: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        if self.value:
            set_owl_label(taxonomy, self.uri, self.lang, self.value)
        else:
            remove_owl_label(taxonomy, self.uri, self.lang)
        return (self.uri,)


@dataclass(frozen=True)
class OwlSetComment:
    """Set an OWL class/individual/property ``rdfs:comment`` for *lang*.

    A non-empty value upserts; an empty one *removes* that language's comment
    (clearing the field deletes the triple). Mirrors the batch ``_set_localized``."""

    target_path: Path
    uri: str
    lang: str
    value: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        if self.value:
            set_owl_comment(taxonomy, self.uri, self.lang, self.value)
        else:
            remove_owl_comment(taxonomy, self.uri, self.lang)
        return (self.uri,)


@dataclass(frozen=True)
class OwlSetNote:
    """Set (or clear, with ``""``) the editor note on an OWL class/individual/property."""

    target_path: Path
    uri: str
    note: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        set_owl_note(taxonomy, self.uri, self.note)
        return (self.uri,)


@dataclass(frozen=True)
class OwlAddExternalSuperclass:
    """Add an external ``rdfs:subClassOf`` to a class, stubbing the external class + namespace."""

    target_path: Path
    source_uri: str
    ext_class_uri: str
    namespace: str = ""
    prefix: str = ""

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        add_external_superclass(
            taxonomy, self.source_uri, self.ext_class_uri, self.namespace, self.prefix
        )
        assign_handles(taxonomy)
        return (self.source_uri,)


@dataclass(frozen=True)
class OwlSetIndividualLiteral:
    """Edit one of an individual's literal property values (replace in place or append)."""

    target_path: Path
    ind_uri: str
    prop_uri: str
    old_value: str
    new_value: str
    lang_or_dt: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        set_individual_literal(
            taxonomy,
            self.ind_uri,
            self.prop_uri,
            self.old_value,
            self.new_value,
            self.lang_or_dt,
        )
        return (self.ind_uri,)


@dataclass(frozen=True)
class EntitySetAnnotation:
    """Add (or replace) one configured annotation on an OWL class / property / individual.

    *is_iri* picks IRI vs literal storage; *old_value* names the entry to replace when the
    predicate already carries a value (empty appends a new one)."""

    target_path: Path
    entity_uri: str
    predicate: str
    value: str
    is_iri: bool = False
    lang: str = ""
    old_value: str = ""

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        set_entity_annotation(
            taxonomy,
            self.entity_uri,
            self.predicate,
            self.value,
            is_iri=self.is_iri,
            lang=self.lang,
            old_value=self.old_value,
        )
        return (self.entity_uri,)


@dataclass(frozen=True)
class EntityRemoveAnnotation:
    """Remove one (predicate, value) annotation from an OWL class / property / individual."""

    target_path: Path
    entity_uri: str
    predicate: str
    value: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        remove_entity_annotation(taxonomy, self.entity_uri, self.predicate, self.value)
        return (self.entity_uri,)


@dataclass(frozen=True)
class OwlCreateProperty:
    """Create an OWL property of *prop_type* (``ObjectProperty`` / ``DatatypeProperty`` /
    ``AnnotationProperty``) with its rdfs:label / rdfs:comment (per language), and optional
    domain / range, in one step. Empty label/comment values are skipped."""

    target_path: Path
    prop_uri: str
    labels: _LangPairs = ()
    comments: _LangPairs = ()
    domain_uri: str | None = None
    range_uri: str | None = None
    prop_type: str = "ObjectProperty"

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        if self.prop_uri not in taxonomy.owl_properties:
            add_owl_property(
                taxonomy,
                self.prop_uri,
                self.prop_type,
                "",  # labels are set below (one per language)
                "en",
                self.domain_uri,
                self.range_uri,
            )
        _set_localized(taxonomy, self.prop_uri, self.labels, kind="label")
        _set_localized(taxonomy, self.prop_uri, self.comments, kind="comment")
        assign_handles(taxonomy)
        return (self.prop_uri,)


@dataclass(frozen=True)
class OwlAddPropertyClass:
    """Add a class to a property's domain or range (*slot* ∈ ``domain``/``range``)."""

    target_path: Path
    prop_uri: str
    slot: str
    class_uri: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        add_property_class(taxonomy, self.prop_uri, self.slot, self.class_uri)
        return (self.prop_uri,)


@dataclass(frozen=True)
class OwlRemovePropertyClass:
    """Remove a class from a property's domain or range."""

    target_path: Path
    prop_uri: str
    slot: str
    class_uri: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        remove_property_class(taxonomy, self.prop_uri, self.slot, self.class_uri)
        return (self.prop_uri,)


@dataclass(frozen=True)
class OwlRemoveSuperclass:
    """Detach one ``rdfs:subClassOf`` parent from a class."""

    target_path: Path
    child_uri: str
    parent_uri: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        remove_subclass_of(taxonomy, self.child_uri, self.parent_uri)
        return (self.child_uri,)


@dataclass(frozen=True)
class OwlDeleteIndividual:
    """Delete an OWL individual."""

    target_path: Path
    uri: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        delete_owl_individual(taxonomy, self.uri)
        return (self.uri,)


@dataclass(frozen=True)
class OwlRemoveIndividualValue:
    """Remove a ``(prop, value)`` object-property pair from an individual."""

    target_path: Path
    ind_uri: str
    prop_uri: str
    val_uri: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        remove_individual_property_value(taxonomy, self.ind_uri, self.prop_uri, self.val_uri)
        return (self.ind_uri,)


@dataclass(frozen=True)
class OwlRemoveIndividualLiteral:
    """Remove a ``(prop, value, lang/dt)`` literal triple from an individual."""

    target_path: Path
    ind_uri: str
    prop_uri: str
    val_str: str
    lang_or_dt: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        remove_individual_literal(
            taxonomy, self.ind_uri, self.prop_uri, self.val_str, self.lang_or_dt
        )
        return (self.ind_uri,)


@dataclass(frozen=True)
class OwlConvertClassToIndividual:
    """Convert an OWL class into an individual (punning).

    *reattach_to* re-types individuals that were typed as the class; ``None`` deletes them.
    """

    target_path: Path
    uri: str
    reattach_to: tuple[str, ...] | None = None

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        convert_class_to_individual(
            taxonomy, self.uri, list(self.reattach_to) if self.reattach_to is not None else None
        )
        assign_handles(taxonomy)
        return (self.uri,)


@dataclass(frozen=True)
class OwlConvertIndividualToClass:
    """Convert an OWL individual into a class (punning)."""

    target_path: Path
    uri: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        convert_individual_to_class(taxonomy, self.uri)
        assign_handles(taxonomy)
        return (self.uri,)


@dataclass(frozen=True)
class OwlAddIndividualType:
    """Add an ``rdf:type`` (class) to an individual."""

    target_path: Path
    ind_uri: str
    type_uri: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        add_individual_type(taxonomy, self.ind_uri, self.type_uri)
        return (self.ind_uri,)


@dataclass(frozen=True)
class OwlSetIndividualValue:
    """Add or replace an object-property ``(prop, value)`` pair on an individual."""

    target_path: Path
    ind_uri: str
    prop_uri: str
    new_val_uri: str
    old_val_uri: str = ""

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        set_individual_property_value(
            taxonomy, self.ind_uri, self.prop_uri, self.new_val_uri, self.old_val_uri
        )
        return (self.ind_uri,)


@dataclass(frozen=True)
class OwlRemoveIndividualType:
    """Remove an ``rdf:type`` from an individual."""

    target_path: Path
    ind_uri: str
    type_uri: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        remove_individual_type(taxonomy, self.ind_uri, self.type_uri)
        return (self.ind_uri,)


@dataclass(frozen=True)
class OwlChangeIndividualType:
    """Re-classify an individual: drop *old_type_uri*, add *new_type_uri* (a no-op when
    they are the same). Backs the editable ``instanceOf`` row (✎ → pick a class)."""

    target_path: Path
    ind_uri: str
    old_type_uri: str
    new_type_uri: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        if self.new_type_uri != self.old_type_uri:
            remove_individual_type(taxonomy, self.ind_uri, self.old_type_uri)
            add_individual_type(taxonomy, self.ind_uri, self.new_type_uri)
        return (self.ind_uri,)


@dataclass(frozen=True)
class OwlDeleteProperty:
    """Delete an OWL property. ``clear_values=True`` first strips its values from
    every individual; ``clear_values=False`` deletes the declaration only."""

    target_path: Path
    prop_uri: str
    clear_values: bool = False

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        if self.clear_values:
            clear_property_values(taxonomy, self.prop_uri)
        delete_owl_property(taxonomy, self.prop_uri)
        return (self.prop_uri,)
