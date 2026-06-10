"""Cross-layer rename front + URI resolution.

Detects which layer(s) own a URI and dispatches counting/renaming into the SKOS
and OWL layers. Part of the domain layer (docs/architecture/module-layout.md):
reached through ``ster.operations``, never imported directly by a front-end.
"""

from __future__ import annotations

from ..exceptions import ConceptNotFoundError, HandleNotFoundError, URIAlreadyExistsError
from ..handles import assign_handles
from ..model import Taxonomy
from .owl import count_owl_uri_references, rename_owl_uri
from .skos import count_concept_uri_references, rename_uri


def resolve(taxonomy: Taxonomy, handle_or_name: str) -> str:
    """Resolve a handle, local name, or full URI to a URI.

    Resolution order:
      1. Full URI (contains "://") — verified against known concepts/schemes.
      2. Handle (case-insensitive lookup in handle_index).
      3. Local name (matched against concept.local_name).

    Raises HandleNotFoundError if nothing matches.
    """
    uri = taxonomy.resolve(handle_or_name)
    if uri is None:
        raise HandleNotFoundError(handle_or_name)
    return uri


def expand_uri(taxonomy: Taxonomy, name_or_uri: str) -> str:
    """Return a full URI for a local name, expanding with the taxonomy's base URI.

    If name_or_uri already contains "://" it is returned as-is.
    Otherwise, the taxonomy's base URI is prepended.
    """
    if "://" in name_or_uri:
        return name_or_uri
    base = taxonomy.base_uri()
    if not base:
        raise HandleNotFoundError(
            f"Cannot expand {name_or_uri!r}: no base URI configured. "
            "Use a full URI or run 'ster init' to set one."
        )
    return base + name_or_uri


# ──────────────────────── common rename front ────────────────────────────────
# The generic flow — detect the layer(s) owning a URI, count affected
# statements, and rename — is identical for SKOS and OWL.  These dispatchers
# hide the SKOS-vs-OWL specifics so callers (e.g. the viewer) stay layer-
# agnostic; a node promoted to both layers is handled in both.


def _owns_owl(taxonomy: Taxonomy, uri: str) -> bool:
    return (
        uri in taxonomy.owl_classes
        or uri in taxonomy.owl_individuals
        or uri in taxonomy.owl_properties
    )


def count_uri_references(taxonomy: Taxonomy, uri: str) -> int:
    """Total statements affected by renaming *uri*, across every layer it owns.

    Dispatches to :func:`count_concept_uri_references` and/or
    :func:`count_owl_uri_references`; a promoted node sums both.
    """
    total = 0
    if uri in taxonomy.concepts:
        total += count_concept_uri_references(taxonomy, uri)
    if _owns_owl(taxonomy, uri):
        total += count_owl_uri_references(taxonomy, uri)
    return total


def rename_entity_uri(taxonomy: Taxonomy, old_uri: str, new_uri: str) -> None:
    """Rename *old_uri* to *new_uri* in every layer that owns it.

    Performs a single unified collision check (raising
    :class:`URIAlreadyExistsError` if *new_uri* is already taken in any layer)
    before delegating to the SKOS-specialized :func:`rename_uri` and/or the
    OWL-specialized :func:`rename_owl_uri`.  Raises
    :class:`ConceptNotFoundError` when *old_uri* exists in no layer.
    """
    in_concepts = old_uri in taxonomy.concepts
    in_owl = _owns_owl(taxonomy, old_uri)
    if not in_concepts and not in_owl:
        raise ConceptNotFoundError(old_uri)

    if new_uri in taxonomy.concepts or _owns_owl(taxonomy, new_uri):
        raise URIAlreadyExistsError(new_uri)

    if in_concepts:
        rename_uri(taxonomy, old_uri, new_uri)
    if in_owl:
        rename_owl_uri(taxonomy, old_uri, new_uri)

    assign_handles(taxonomy)
