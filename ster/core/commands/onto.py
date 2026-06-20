"""Ontology-level commands — act on the ontology base URI (cross-cutting).

Renaming the base URI propagates to every local entity (classes, individuals,
properties). The domain-rename flow reduces to this command (it computes a new
base URI and renames to it), so both share one command.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...domain.onto import add_ontology_annotation, remove_ontology_annotation
from ...model import Taxonomy
from ...operations import rename_ontology_uri, set_ontology_metadata, set_ontology_prefix


@dataclass(frozen=True)
class OntoRenameUri:
    """Rename the ontology base URI to *new_uri* + *new_sep* (``"#"`` or ``"/"``).

    Propagates the change to every local entity URI; external namespaces are left
    untouched. Returns no single affected URI — the change is ontology-wide.
    """

    target_path: Path
    new_uri: str
    new_sep: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        rename_ontology_uri(taxonomy, self.new_uri, self.new_sep)
        return ()


@dataclass(frozen=True)
class OntoSetMetadata:
    """Set an ontology metadata field (``label`` / ``title`` / ``description``).

    A blank value clears the field. Ontology-wide, so it reports no affected URI.
    """

    target_path: Path
    field_name: str
    value: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        set_ontology_metadata(taxonomy, self.field_name, self.value)
        return ()


@dataclass(frozen=True)
class OntoSetPrefix:
    """Set the ontology namespace prefix (bind to the base, or rename the existing one)."""

    target_path: Path
    new_prefix: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        set_ontology_prefix(taxonomy, self.new_prefix)
        return ()


@dataclass(frozen=True)
class OntoSetAnnotation:
    """Set (replace) one annotation value on the owl:Ontology node.

    *predicate* is the full predicate URI. *old_value* identifies which value to
    replace when the predicate is multi-valued; empty means "set the first/only
    value". *new_value* is the replacement text.
    """

    target_path: Path
    predicate: str
    old_value: str
    new_value: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        add_ontology_annotation(taxonomy, self.predicate, self.new_value, old_value=self.old_value)
        return ()


@dataclass(frozen=True)
class OntoRemoveAnnotation:
    """Remove one annotation value from the owl:Ontology node.

    When *predicate* is multi-valued, only the entry with *value* is removed.
    """

    target_path: Path
    predicate: str
    value: str

    def apply(self, taxonomy: Taxonomy) -> tuple[str, ...]:
        remove_ontology_annotation(taxonomy, self.predicate, self.value)
        return ()
