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

from .base import ChangeSet, Command
from .cross import (
    AddSchemaMedia,
    DemotePunToConcept,
    PromoteConceptToClass,
    RemoveLanguage,
    RemoveSchemaMedia,
    RenameEntity,
    TagIndividuals,
)
from .onto import (
    OntoRemoveAnnotation,
    OntoRenameUri,
    OntoSetAnnotation,
    OntoSetMetadata,
    OntoSetPrefix,
)
from .owl import (
    OwlAddExternalSuperclass,
    OwlAddIndividualType,
    OwlAddProperty,
    OwlAddPropertyClass,
    OwlChangeIndividualType,
    OwlConvertClassToIndividual,
    OwlConvertIndividualToClass,
    OwlCreateClass,
    OwlCreateIndividual,
    OwlCreateIndividualFull,
    OwlCreateProperty,
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
    OwlSaveClass,
    OwlSaveIndividual,
    OwlSaveProperty,
    OwlSetComment,
    OwlSetIndividualLiteral,
    OwlSetIndividualValue,
    OwlSetLabel,
    OwlSetNote,
)
from .skos import (
    SkosAddConcept,
    SkosAddMappingLink,
    SkosAddRelated,
    SkosCreateScheme,
    SkosMoveConcept,
    SkosRemoveConcept,
    SkosRemoveDefinition,
    SkosRemoveLabel,
    SkosRemoveMappingLink,
    SkosRemoveScheme,
    SkosRemoveScopeNote,
    SkosSetDefinition,
    SkosSetLabel,
    SkosSetSchemeField,
    SkosSetScopeNote,
)

__all__ = [
    "AddSchemaMedia",
    "DemotePunToConcept",
    "PromoteConceptToClass",
    "TagIndividuals",
    "ChangeSet",
    "Command",
    "OntoRenameUri",
    "OntoRemoveAnnotation",
    "OntoSetAnnotation",
    "OntoSetMetadata",
    "OntoSetPrefix",
    "OwlAddExternalSuperclass",
    "OwlAddIndividualType",
    "OwlAddProperty",
    "OwlChangeIndividualType",
    "OwlAddPropertyClass",
    "OwlConvertClassToIndividual",
    "OwlConvertIndividualToClass",
    "OwlCreateClass",
    "OwlCreateProperty",
    "OwlCreateIndividual",
    "OwlCreateIndividualFull",
    "OwlCreateSubclass",
    "OwlDeleteClass",
    "OwlDeleteIndividual",
    "OwlDeleteProperty",
    "OwlMoveClass",
    "OwlRemoveIndividualLiteral",
    "OwlRemoveIndividualType",
    "OwlRemoveIndividualValue",
    "OwlRemovePropertyClass",
    "OwlRemoveSuperclass",
    "OwlSaveClass",
    "OwlSaveProperty",
    "OwlSaveIndividual",
    "OwlSetComment",
    "OwlSetIndividualLiteral",
    "OwlSetIndividualValue",
    "OwlSetLabel",
    "OwlSetNote",
    "RemoveLanguage",
    "RemoveSchemaMedia",
    "RenameEntity",
    "SkosAddConcept",
    "SkosAddMappingLink",
    "SkosAddRelated",
    "SkosCreateScheme",
    "SkosMoveConcept",
    "SkosRemoveConcept",
    "SkosRemoveDefinition",
    "SkosRemoveLabel",
    "SkosRemoveMappingLink",
    "SkosRemoveScheme",
    "SkosRemoveScopeNote",
    "SkosSetDefinition",
    "SkosSetLabel",
    "SkosSetSchemeField",
    "SkosSetScopeNote",
]
