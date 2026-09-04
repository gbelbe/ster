"""Prefix -> qname completion index, built from a loaded ``Taxonomy``.

Two related indexes live here: ``build_qname_index`` (flat prefix -> local
names, used by ``build_prefix_header``-style callers) and the richer
``build_uri_index`` (per-prefix classes/individuals/properties/hierarchy,
consumed by the editor's hierarchical QName popup in ``_autocomplete.py``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from ._types import UriIndex

_LIT_CLASS: Final = "Class"


if TYPE_CHECKING:
    from ..model import Taxonomy


_STANDARD_PREFIXES: dict[str, str] = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",  # NOSONAR - RDF namespace IRI
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",  # NOSONAR - RDF namespace IRI
    "owl": "http://www.w3.org/2002/07/owl#",  # NOSONAR - RDF namespace IRI
    "skos": "http://www.w3.org/2004/02/skos/core#",  # NOSONAR - RDF namespace IRI
    "dcterms": "http://purl.org/dc/terms/",  # NOSONAR - RDF namespace IRI
    "xsd": "http://www.w3.org/2001/XMLSchema#",  # NOSONAR - RDF namespace IRI
}


_STANDARD_QNAMES: dict[str, list[str]] = {
    "rdf": [
        "List",
        "Property",
        "first",
        "nil",
        "object",
        "predicate",
        "rest",
        "subject",
        "type",
        "value",
    ],
    "rdfs": [
        _LIT_CLASS,
        "Literal",
        "Resource",
        "comment",
        "domain",
        "isDefinedBy",
        "label",
        "range",
        "seeAlso",
        "subClassOf",
        "subPropertyOf",
    ],
    "owl": [
        _LIT_CLASS,
        "DatatypeProperty",
        "FunctionalProperty",
        "Individual",
        "NamedIndividual",
        "Nothing",
        "ObjectProperty",
        "Thing",
        "disjointWith",
        "equivalentClass",
        "inverseOf",
    ],
    "skos": [
        "Collection",
        "Concept",
        "ConceptScheme",
        "altLabel",
        "broadMatch",
        "broader",
        "broaderTransitive",
        "changeNote",
        "closeMatch",
        "definition",
        "editorialNote",
        "exactMatch",
        "example",
        "hasTopConcept",
        "hiddenLabel",
        "historyNote",
        "inScheme",
        "member",
        "narrowMatch",
        "narrower",
        "narrowerTransitive",
        "note",
        "prefLabel",
        "related",
        "relatedMatch",
        "scopeNote",
        "topConceptOf",
    ],
    "dcterms": [
        "contributor",
        "coverage",
        "created",
        "creator",
        "description",
        "format",
        "identifier",
        "language",
        "modified",
        "publisher",
        "rights",
        "source",
        "subject",
        "title",
        "type",
    ],
    "xsd": [
        "anyURI",
        "boolean",
        "date",
        "dateTime",
        "decimal",
        "double",
        "float",
        "integer",
        "langString",
        "string",
    ],
}


def build_prefix_header(namespace_bindings: dict[str, str]) -> str:
    """Build a SPARQL PREFIX block from *namespace_bindings* only.

    Emits exactly the prefixes declared in the loaded TTL file, sorted
    alphabetically.  No standard prefixes are added automatically.
    """
    return (
        "\n".join(f"PREFIX {pfx}: <{uri}>" for pfx, uri in sorted(namespace_bindings.items()))
        + "\n\n"
    )


def _add_standard_qnames_to_index(index: dict[str, list[str]], seen: set[tuple[str, str]]) -> None:
    for pfx, qnames in _STANDARD_QNAMES.items():
        for local in qnames:
            if (pfx, local) not in seen:
                seen.add((pfx, local))
                index.setdefault(pfx, []).append(local)


def build_qname_index(taxonomy: Taxonomy) -> dict[str, list[str]]:
    """Build a ``prefix → [local_name, ...]`` completion index.

    Includes local names extracted from every taxonomy node (classes, individuals,
    concepts, schemes, properties) plus well-known local names for all six standard
    prefixes.  Each list is deduplicated and sorted alphabetically.
    """
    ns_to_pfx: dict[str, str] = {uri: pfx for pfx, uri in taxonomy.namespace_bindings.items()}

    index: dict[str, list[str]] = {}
    seen: set[tuple[str, str]] = set()

    def _add_uri(uri: str) -> None:
        for ns, pfx in ns_to_pfx.items():
            if uri.startswith(ns):
                local = uri[len(ns) :]
                if local and (pfx, local) not in seen:
                    seen.add((pfx, local))
                    index.setdefault(pfx, []).append(local)
                return

    for uri in (
        *taxonomy.owl_classes,
        *taxonomy.owl_individuals,
        *taxonomy.concepts,
        *taxonomy.schemes,
        *taxonomy.owl_properties,
    ):
        _add_uri(uri)

    _add_standard_qnames_to_index(index, seen)

    for pfx in index:
        index[pfx] = sorted(index[pfx])

    return index


def _add_standard_qnames(
    all_map: dict[str, list[str]], cls_map: dict[str, list[str]], seen_all: set[tuple[str, str]]
) -> None:
    """Add owl:Class / rdfs:Class etc. well-known names to the "all" and "classes" buckets."""
    _STANDARD_CLASS_LOCALS: dict[str, list[str]] = {
        "owl": [_LIT_CLASS, "NamedIndividual", "Thing", "Nothing"],
        "rdfs": [_LIT_CLASS, "Resource"],
        "rdf": ["Property"],
    }
    for pfx, qnames in _STANDARD_QNAMES.items():
        cls_locals = set(_STANDARD_CLASS_LOCALS.get(pfx, []))
        for local in qnames:
            if (pfx, local) not in seen_all:
                seen_all.add((pfx, local))
                all_map.setdefault(pfx, []).append(local)
            if local in cls_locals and local not in cls_map.get(pfx, []):
                cls_map.setdefault(pfx, []).append(local)


def _add_uri_to_bucket(
    uri: str,
    bucket: dict[str, list[str]],
    ns_to_pfx: dict[str, str],
    all_map: dict[str, list[str]],
    seen_all: set[tuple[str, str]],
) -> None:
    for ns, pfx in ns_to_pfx.items():
        if uri.startswith(ns):
            local = uri[len(ns) :]
            if local:
                bucket.setdefault(pfx, []).append(local)
                if (pfx, local) not in seen_all:
                    seen_all.add((pfx, local))
                    all_map.setdefault(pfx, []).append(local)
            return


def _populate_uri_buckets(
    taxonomy: Taxonomy, ns_to_pfx: dict[str, str]
) -> tuple[dict[str, list[str]], dict[str, list[str]], dict[str, list[str]], dict[str, list[str]]]:
    """Bucket every URI by namespace-prefix, then fold in the well-known standard names."""
    all_map: dict[str, list[str]] = {}
    cls_map: dict[str, list[str]] = {}
    ind_map: dict[str, list[str]] = {}
    prop_map: dict[str, list[str]] = {}
    seen_all: set[tuple[str, str]] = set()

    for uri in taxonomy.owl_classes:
        _add_uri_to_bucket(uri, cls_map, ns_to_pfx, all_map, seen_all)
    for uri in taxonomy.owl_individuals:
        _add_uri_to_bucket(uri, ind_map, ns_to_pfx, all_map, seen_all)
    for uri in taxonomy.owl_properties:
        _add_uri_to_bucket(uri, prop_map, ns_to_pfx, all_map, seen_all)
    for uri in (*taxonomy.concepts, *taxonomy.schemes, *taxonomy.owl_properties):
        _add_uri_to_bucket(uri, all_map, ns_to_pfx, all_map, seen_all)

    _add_standard_qnames(all_map, cls_map, seen_all)

    return all_map, cls_map, ind_map, prop_map


def _namespace_and_local(uri: str, ns_to_pfx: dict[str, str]) -> tuple[str | None, str | None]:
    """(prefix, namespace) of the first namespace *uri* starts with, or (None, None)."""
    for namespace, p in ns_to_pfx.items():
        if uri.startswith(namespace):
            return p, namespace
    return None, None


def _record_class_in_hierarchy(
    uri: str,
    cls,
    ns_to_pfx: dict[str, str],
    roots_map: dict[str, list[str]],
    children_map: dict[str, dict[str, list[str]]],
) -> None:
    cpfx, cns = _namespace_and_local(uri, ns_to_pfx)
    if cpfx is None or cns is None:
        return
    local = uri[len(cns) :]
    if not local:
        return
    has_parent_in_ns = False
    for parent_uri in cls.sub_class_of:
        if parent_uri.startswith(cns):
            parent_local = parent_uri[len(cns) :]
            if parent_local:
                has_parent_in_ns = True
                children_map.setdefault(cpfx, {}).setdefault(parent_local, []).append(local)
    if not has_parent_in_ns:
        roots_map.setdefault(cpfx, []).append(local)


def _build_class_hierarchy(
    taxonomy: Taxonomy, ns_to_pfx: dict[str, str]
) -> tuple[dict[str, list[str]], dict[str, dict[str, list[str]]]]:
    """Roots (no parent in the same namespace) and parent→children maps, per prefix."""
    roots_map: dict[str, list[str]] = {}
    children_map: dict[str, dict[str, list[str]]] = {}

    for uri, cls in taxonomy.owl_classes.items():
        _record_class_in_hierarchy(uri, cls, ns_to_pfx, roots_map, children_map)

    return roots_map, children_map


def _record_individual_in_class_bucket(
    ind_uri: str,
    ind,
    ns_to_pfx: dict[str, str],
    ibc_map: dict[str, dict[str, list[str]]],
    untyped_ind_map: dict[str, list[str]],
) -> None:
    ipfx, ins = _namespace_and_local(ind_uri, ns_to_pfx)
    if ipfx is None or ins is None:
        return
    ind_local = ind_uri[len(ins) :]
    if not ind_local:
        return
    typed_in_ns = False
    for type_uri in ind.types:
        for namespace, _p in ns_to_pfx.items():
            if type_uri.startswith(namespace):
                class_local = type_uri[len(namespace) :]
                if class_local:
                    ibc_map.setdefault(ipfx, {}).setdefault(class_local, []).append(ind_local)
                    typed_in_ns = True
                break
    if not typed_in_ns:
        untyped_ind_map.setdefault(ipfx, []).append(ind_local)


def _build_individuals_by_class(
    taxonomy: Taxonomy, ns_to_pfx: dict[str, str]
) -> tuple[dict[str, dict[str, list[str]]], dict[str, list[str]]]:
    """class_local → [ind_locals] for same-NS typed individuals, plus untyped ones.

    Individuals whose types are all outside this namespace are tracked as
    "untyped" and shown at root level so they remain reachable.
    """
    ibc_map: dict[str, dict[str, list[str]]] = {}
    untyped_ind_map: dict[str, list[str]] = {}

    for ind_uri, ind in taxonomy.owl_individuals.items():
        _record_individual_in_class_bucket(ind_uri, ind, ns_to_pfx, ibc_map, untyped_ind_map)

    return ibc_map, untyped_ind_map


def _assemble_uri_index(
    all_map: dict[str, list[str]],
    cls_map: dict[str, list[str]],
    ind_map: dict[str, list[str]],
    prop_map: dict[str, list[str]],
    roots_map: dict[str, list[str]],
    children_map: dict[str, dict[str, list[str]]],
    ibc_map: dict[str, dict[str, list[str]]],
    untyped_ind_map: dict[str, list[str]],
) -> UriIndex:
    idx: UriIndex = {}
    all_pfxs = (
        set(all_map)
        | set(cls_map)
        | set(ind_map)
        | set(prop_map)
        | set(roots_map)
        | set(ibc_map)
        | set(untyped_ind_map)
    )
    for pfx in all_pfxs:
        idx[pfx] = {
            "all": sorted(set(all_map.get(pfx, []))),
            "classes": sorted(set(cls_map.get(pfx, []))),
            "individuals": sorted(set(ind_map.get(pfx, []))),
            "properties": sorted(set(prop_map.get(pfx, []))),
            "roots": sorted(set(roots_map.get(pfx, []))),
            "children": {
                parent: sorted(set(children))
                for parent, children in children_map.get(pfx, {}).items()
            },
            "individuals_by_class": {
                cls: sorted(set(inds)) for cls, inds in ibc_map.get(pfx, {}).items()
            },
            "untyped_individuals": sorted(set(untyped_ind_map.get(pfx, []))),
        }
    return idx


def build_uri_index(taxonomy: Taxonomy) -> UriIndex:
    """Build a prefix → {all, classes, individuals, roots, children} completion index.

    Each sub-list is sorted alphabetically.  Standard prefix well-known names
    are included under "all" and under "classes" where appropriate.

    ``roots``    — classes with no rdfs:subClassOf pointing to another class
                   in the same namespace (parentless classes surface at root level).
    ``children`` — mapping of parent local name → sorted list of direct child
                   local names within the same namespace.
    """
    ns_to_pfx: dict[str, str] = {uri: pfx for pfx, uri in taxonomy.namespace_bindings.items()}

    all_map, cls_map, ind_map, prop_map = _populate_uri_buckets(taxonomy, ns_to_pfx)
    roots_map, children_map = _build_class_hierarchy(taxonomy, ns_to_pfx)
    ibc_map, untyped_ind_map = _build_individuals_by_class(taxonomy, ns_to_pfx)

    return _assemble_uri_index(
        all_map, cls_map, ind_map, prop_map, roots_map, children_map, ibc_map, untyped_ind_map
    )
