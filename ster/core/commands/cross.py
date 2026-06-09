"""Cross-layer commands — identified by URI, layer-agnostic by design."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...model import Taxonomy
from ...operations import rename_entity_uri


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
