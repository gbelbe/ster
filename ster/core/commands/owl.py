"""OWL-layer commands — act on ``owl:Class`` entities (``rdfs:subClassOf``)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...exceptions import ClassNotFoundError
from ...model import Taxonomy
from ...operations import (
    add_subclass_of,
    clear_property_values,
    delete_owl_class,
    delete_owl_property,
)


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
