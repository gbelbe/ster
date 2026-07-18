"""Cross-layer commands — identified by URI, layer-agnostic by design."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...model import Taxonomy
from ...operations import (
    add_schema_media,
    demote_pun_to_concept,
    promote_concept_to_class,
    remove_language,
    remove_schema_media,
    rename_entity_uri,
    tag_individual_with_concept,
)


@dataclass(frozen=True)
class RenameEntity:
    """Rename *old_uri* to *new_uri* in every layer that owns it (SKOS and/or OWL).

    Deliberately not layer-prefixed: ``operations.rename_entity_uri`` dispatches
    across concepts, classes, properties and individuals, with a single collision
    check — a URI rename is the same intent regardless of layer.
    """

    target_path: Path
    old_uri: str
    new_uri: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        rename_entity_uri(taxonomy, self.old_uri, self.new_uri)
        return (self.new_uri,)


@dataclass(frozen=True)
class AddSchemaMedia:
    """Append a schema:image/video/url URL to a concept/class/individual (*kind* ∈ image/video/url)."""

    target_path: Path
    uri: str
    kind: str
    url: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        add_schema_media(taxonomy, self.uri, self.kind, self.url)
        return (self.uri,)


@dataclass(frozen=True)
class RemoveSchemaMedia:
    """Remove a schema:image/video/url URL from a concept/class/individual."""

    target_path: Path
    uri: str
    kind: str
    url: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        remove_schema_media(taxonomy, self.uri, self.kind, self.url)
        return (self.uri,)


@dataclass(frozen=True)
class PromoteConceptToClass:
    """Give a concept an ``owl:Class`` facet (concept → pun) — see
    ``operations.promote_concept_to_class``."""

    target_path: Path
    uri: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        promote_concept_to_class(taxonomy, self.uri)
        return (self.uri,)


@dataclass(frozen=True)
class DemotePunToConcept:
    """Remove a pun's ``owl:Class`` facet (pun → concept) — see
    ``operations.demote_pun_to_concept``."""

    target_path: Path
    uri: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        demote_pun_to_concept(taxonomy, self.uri)
        return (self.uri,)


@dataclass(frozen=True)
class TagIndividuals:
    """Tag many individuals with one concept in a single step (bulk ``dct:subject`` →
    *concept_uri*). One command = one undo/save unit; bad targets are skipped."""

    target_path: Path
    ind_uris: tuple[str, ...]
    concept_uri: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        for ind_uri in self.ind_uris:
            tag_individual_with_concept(taxonomy, ind_uri, self.concept_uri)
        return self.ind_uris


@dataclass(frozen=True)
class RemoveLanguage:
    """Strip every language-tagged literal in *lang* across all entities.

    Used when a language is removed from the configured set and the user chooses
    to delete its data (labels, comments, definitions, scope notes, descriptions).
    """

    target_path: Path
    lang: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        remove_language(taxonomy, self.lang)
        return ()
