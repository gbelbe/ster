"""Shared URI-fragment logic for the New-TUI add / rename flows.

Every entity that has a URI is created and renamed the same way: the namespace
(base + ``#``/``/`` separator) is fixed and only the local *fragment* is edited.
These pure helpers decide what that fixed namespace is — used by
:class:`~ster.tui.uri_modal.UriModal`. No Textual import, so they unit-test as
plain functions.
"""

from __future__ import annotations

from ster.model import Taxonomy
from ster.operations import _ontology_separator

# Actions whose new entity is a SKOS concept (minted under its scheme's base);
# every other URI-creating action mints under the ontology base.
_CONCEPT_MINT_ACTIONS = frozenset({"add_narrower", "add_top_concept"})


def split_namespace(uri: str) -> tuple[str, str]:
    """Split *uri* at its last ``#`` or ``/`` into ``(namespace, local_name)``.

    The namespace keeps its trailing separator; a URI with no separator yields
    ``("", uri)``. This is the locked prefix when *renaming* an entity — so an
    entity in any namespace (including an imported/foreign one) edits only its
    local name.
    """
    idx = max(uri.rfind("#"), uri.rfind("/"))
    if idx < 0:
        return "", uri
    return uri[: idx + 1], uri[idx + 1 :]


def mint_base(taxonomy: Taxonomy, action: str, parent_uri: str) -> str:
    """The base URI (with trailing separator) a *new* entity of *action* mints under.

    SKOS concepts use their parent scheme's base; every other entity uses the
    ontology base + its detected separator. Falls back to ``taxonomy.base_uri()``
    when no ontology URI is set.
    """
    if action in _CONCEPT_MINT_ACTIONS:
        scheme = taxonomy.schemes.get(parent_uri)
        if scheme is not None and scheme.base_uri:
            return scheme.base_uri
        return taxonomy.base_uri()
    onto = taxonomy.ontology_uri or ""
    root = onto.rstrip("#/")
    if root and onto.startswith(("http://", "https://")):
        return root + _ontology_separator(taxonomy)
    return taxonomy.base_uri()
