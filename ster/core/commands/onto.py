"""Ontology-level commands — act on the ontology base URI (cross-cutting).

Renaming the base URI propagates to every local entity (classes, individuals,
properties). The domain-rename flow reduces to this command (it computes a new
base URI and renames to it), so both share one command.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...model import Taxonomy
from ...operations import rename_ontology_uri


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
