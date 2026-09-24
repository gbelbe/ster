"""Whether a predicate is an annotation property.

Asked by the TUI before it offers to declare a predicate the file uses but never
declares: an annotation predicate goes in the Annotation group, and anything
else is flagged as untyped.

Answered from the file itself and from a list of predicates that are annotation
properties by definition in widely used vocabularies. Nothing is fetched or read
from a cache: the answer depends on the file alone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from rdflib.namespace import DC, DCTERMS, FOAF, OWL, RDFS, SDO, SKOS, VANN

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .model import Taxonomy

# Shared by Dublin Core terms, Dublin Core elements and schema.org.
_DESCRIPTION: Final = "description"

WELL_KNOWN_ANNOTATION_PROPS: Final[frozenset[str]] = frozenset(
    {
        *(f"{RDFS}{p}" for p in ("label", "comment", "seeAlso", "isDefinedBy")),
        *(
            f"{SKOS}{p}"
            for p in (
                "note",
                "scopeNote",
                "definition",
                "example",
                "editorialNote",
                "changeNote",
                "historyNote",
                "prefLabel",
                "altLabel",
                "hiddenLabel",
                "notation",
            )
        ),
        *(
            f"{OWL}{p}"
            for p in (
                "versionInfo",
                "deprecated",
                "priorVersion",
                "backwardCompatibleWith",
                "incompatibleWith",
            )
        ),
        *(
            f"{DCTERMS}{p}"
            for p in (
                "title",
                _DESCRIPTION,
                "creator",
                "contributor",
                "publisher",
                "created",
                "modified",
                "date",
                "source",
                "license",
                "rights",
                "subject",
                "language",
                "identifier",
                "abstract",
                "bibliographicCitation",
            )
        ),
        *(f"{DC}{p}" for p in ("title", _DESCRIPTION, "creator", "subject", "rights")),
        *(f"{FOAF}{p}" for p in ("depiction", "homepage", "name", "page", "logo", "maker")),
        *(
            f"{VANN}{p}"
            for p in ("preferredNamespacePrefix", "preferredNamespaceUri", "example", "usageNote")
        ),
        *(f"{SDO}{p}" for p in ("image", _DESCRIPTION, "name", "sameAs", "url")),
    }
)


def is_annotation_property(taxonomy: Taxonomy, predicate: str) -> bool:
    """True when *predicate* is declared ``owl:AnnotationProperty`` in the file,
    or is a well-known annotation predicate. Otherwise False — the caller warns
    and may declare it locally."""
    prop = taxonomy.owl_properties.get(predicate)
    if prop is not None and prop.prop_type == "AnnotationProperty":
        return True
    return predicate in WELL_KNOWN_ANNOTATION_PROPS
