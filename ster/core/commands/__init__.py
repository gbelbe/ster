"""Command vocabulary — self-applying dataclasses, grouped by ontology layer.

Each command is *intent* (serializable fields) plus a thin ``apply`` delegating
to ``ster.operations``. The service stays generic (calls ``command.apply``), so
adding an action is one dataclass in the matching layer module:

- :mod:`ster.core.commands.owl`   — ``owl:Class`` actions (``Owl*``)
- :mod:`ster.core.commands.skos`  — ``skos:Concept`` actions (``Skos*``)
- :mod:`ster.core.commands.cross` — layer-agnostic, URI-identified actions

The ``Skos``/``Owl`` name prefixes keep the two layers from being mixed up. This
package re-exports every command so call sites can ``from ster.core.commands
import …`` regardless of which layer module a command lives in.
"""

from __future__ import annotations

from .base import Command
from .cross import RenameEntity
from .onto import OntoRenameUri
from .owl import OwlDeleteClass, OwlMoveClass
from .skos import (
    SkosAddRelated,
    SkosCreateScheme,
    SkosMoveConcept,
    SkosRemoveConcept,
    SkosRemoveDefinition,
    SkosRemoveLabel,
    SkosRemoveScopeNote,
    SkosSetDefinition,
    SkosSetLabel,
    SkosSetScopeNote,
)

__all__ = [
    "Command",
    "OntoRenameUri",
    "OwlDeleteClass",
    "OwlMoveClass",
    "RenameEntity",
    "SkosAddRelated",
    "SkosCreateScheme",
    "SkosMoveConcept",
    "SkosRemoveConcept",
    "SkosRemoveDefinition",
    "SkosRemoveLabel",
    "SkosRemoveScopeNote",
    "SkosSetDefinition",
    "SkosSetLabel",
    "SkosSetScopeNote",
]
