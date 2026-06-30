"""SKOS-layer commands — act on ``skos:Concept`` entities (broader/related/labels/notes)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...model import LabelType, Taxonomy
from ...operations import (
    add_broader_link,
    add_concept,
    add_concept_mapping_link,
    add_related,
    create_scheme,
    move_concept,
    remove_concept,
    remove_concept_mapping_link,
    remove_definition,
    remove_label,
    remove_scheme,
    remove_scope_note,
    set_definition,
    set_label,
    set_scheme_field,
    set_scope_note,
)

# ── move / link ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SkosMoveConcept:
    """Set a SKOS concept's ``skos:broader``.

    ``replace=True`` (default) moves it under *new_parent_uri* as its sole parent,
    or to the scheme top when ``None``. ``replace=False`` *adds* an extra parent,
    keeping the existing ones (polyhierarchy).
    """

    target_path: Path
    source_uri: str
    new_parent_uri: str | None
    replace: bool = True

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        if self.replace:
            move_concept(taxonomy, self.source_uri, self.new_parent_uri)
        elif self.new_parent_uri:
            add_broader_link(taxonomy, self.source_uri, self.new_parent_uri)
        return (self.source_uri,)


@dataclass(frozen=True)
class SkosRemoveConcept:
    """Delete a SKOS concept; ``cascade=True`` also removes its descendants."""

    target_path: Path
    uri: str
    cascade: bool = False

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        return tuple(sorted(remove_concept(taxonomy, self.uri, cascade=self.cascade)))


@dataclass(frozen=True)
class SkosRemoveScheme:
    """Delete a SKOS concept scheme. ``cascade=True`` also removes its concepts;
    otherwise the concepts survive (their top-concept link to it is cleared)."""

    target_path: Path
    uri: str
    cascade: bool = False

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        return tuple(sorted(remove_scheme(taxonomy, self.uri, cascade=self.cascade)))


@dataclass(frozen=True)
class SkosAddMappingLink:
    """Add one directional cross-scheme mapping link to a concept's mapping list.

    *attr* is the Python mapping attribute (``exact_match`` etc.). The inverse link
    on the target's file is a separate command — the viewer orchestrates both.
    """

    target_path: Path
    concept_uri: str
    attr: str
    target_uri: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        add_concept_mapping_link(taxonomy, self.concept_uri, self.attr, self.target_uri)
        return (self.concept_uri,)


@dataclass(frozen=True)
class SkosRemoveMappingLink:
    """Remove one directional cross-scheme mapping link from a concept's mapping list."""

    target_path: Path
    concept_uri: str
    attr: str
    target_uri: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        remove_concept_mapping_link(taxonomy, self.concept_uri, self.attr, self.target_uri)
        return (self.concept_uri,)


@dataclass(frozen=True)
class SkosAddRelated:
    """Add a symmetric ``skos:related`` link between two concepts."""

    target_path: Path
    source_uri: str
    related_uri: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        add_related(taxonomy, self.source_uri, self.related_uri)
        return (self.source_uri, self.related_uri)


# ── create ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SkosCreateScheme:
    """Create a new ``skos:ConceptScheme``. *languages* is the scheme's declared langs."""

    target_path: Path
    uri: str
    labels: dict[str, str]
    base_uri: str = ""
    languages: tuple[str, ...] = ()

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        create_scheme(
            taxonomy,
            self.uri,
            labels=dict(self.labels),
            base_uri=self.base_uri,
            languages=list(self.languages),
        )
        return (self.uri,)


@dataclass(frozen=True)
class SkosSetSchemeField:
    """Set one field of a ``skos:ConceptScheme`` (title/desc/base_uri/creator/created/languages)."""

    target_path: Path
    scheme_uri: str
    field_name: str
    value: str
    lang: str = ""

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        set_scheme_field(taxonomy, self.scheme_uri, self.field_name, self.value, self.lang)
        return (self.scheme_uri,)


@dataclass(frozen=True)
class SkosAddConcept:
    """Add a new ``skos:Concept``. *parent_handle* may be a concept or scheme
    handle/URI (None → top concept of the primary scheme)."""

    target_path: Path
    uri: str
    pref_labels: dict[str, str]
    parent_handle: str | None = None
    definitions: dict[str, str] | None = None

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        add_concept(
            taxonomy,
            self.uri,
            dict(self.pref_labels),
            parent_handle=self.parent_handle,
            definitions=dict(self.definitions) if self.definitions else None,
        )
        return (self.uri,)


# ── set field ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SkosSetLabel:
    """Set a concept label for *lang*. ``kind`` is ``"pref"`` (replaces) or ``"alt"`` (adds)."""

    target_path: Path
    uri: str
    lang: str
    value: str
    kind: str = "pref"

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        label_type = LabelType.PREF if self.kind == "pref" else LabelType.ALT
        set_label(taxonomy, self.uri, self.lang, self.value, label_type)
        return (self.uri,)


@dataclass(frozen=True)
class SkosSetDefinition:
    """Set a concept's ``skos:definition`` for *lang* (replaces that language)."""

    target_path: Path
    uri: str
    lang: str
    value: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        set_definition(taxonomy, self.uri, self.lang, self.value)
        return (self.uri,)


@dataclass(frozen=True)
class SkosSetScopeNote:
    """Set a concept's ``skos:scopeNote`` for *lang* (replaces that language)."""

    target_path: Path
    uri: str
    lang: str
    value: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        set_scope_note(taxonomy, self.uri, self.lang, self.value)
        return (self.uri,)


# ── remove field ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SkosRemoveLabel:
    """Remove a concept label (``kind`` ``"pref"``/``"alt"``) matching *lang* + *value*."""

    target_path: Path
    uri: str
    lang: str
    value: str
    kind: str = "alt"

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        label_type = LabelType.PREF if self.kind == "pref" else LabelType.ALT
        remove_label(taxonomy, self.uri, self.lang, self.value, label_type)
        return (self.uri,)


@dataclass(frozen=True)
class SkosRemoveDefinition:
    """Remove a concept's ``skos:definition`` for *lang*."""

    target_path: Path
    uri: str
    lang: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        remove_definition(taxonomy, self.uri, self.lang)
        return (self.uri,)


@dataclass(frozen=True)
class SkosRemoveScopeNote:
    """Remove a concept's matching ``skos:scopeNote`` (*lang* + *value*)."""

    target_path: Path
    uri: str
    lang: str
    value: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        remove_scope_note(taxonomy, self.uri, self.lang, self.value)
        return (self.uri,)
