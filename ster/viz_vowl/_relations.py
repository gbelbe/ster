"""Concept/individual relations subgraph builders."""

from __future__ import annotations

import itertools
from typing import Final

from ..model import RDFClass, Taxonomy, is_builtin_uri
from ..viz import (
    _detail_class,
    _detail_concept,
    _detail_individual,
    _label_for,  # noqa: F401  (re-exported for potential callers)
    _local,
)

_LIT_EDGES: Final = "edges"
_LIT_LABEL: Final = "label"
_LIT_LAYOUT: Final = "layout"
_LIT_NODES: Final = "nodes"
_LIT_ROOT_CLASS: Final = "rootClass"
_LIT_SOURCE: Final = "source"
_LIT_TARGET: Final = "target"


# Most individuals any one class hands back when expanded. A class holding a
# thousand shops would otherwise reintroduce the freeze one click later.
CLASS_EXPAND_LIMIT = 200


def class_individuals(taxonomy: Taxonomy, class_uri: str, limit: int = CLASS_EXPAND_LIMIT) -> dict:
    """The individuals of one class, capped, as nodes and instanceOf edges.

    ``total`` is how many the class holds and ``shown`` how many came back, so
    the page can say what it withheld rather than quietly truncating.
    """
    members = [
        (uri, ind) for uri, ind in taxonomy.owl_individuals.items() if class_uri in ind.types
    ]
    members.sort(key=lambda pair: pair[1].label("en") or pair[0])
    shown = members[:limit]
    return {
        _LIT_NODES: [
            {
                "id": uri,
                _LIT_LABEL: ind.label("en"),
                "type": "individual",
                "readOnly": 0,
                _LIT_ROOT_CLASS: 0,
            }
            for uri, ind in shown
        ],
        _LIT_EDGES: [
            {
                "id": f"x{i}",
                _LIT_SOURCE: uri,
                _LIT_TARGET: class_uri,
                "type": "instanceOf",
                _LIT_LABEL: "",
            }
            for i, (uri, _ind) in enumerate(shown)
        ],
        "total": len(members),
        "shown": len(shown),
    }


def build_concept_relations_graph(taxonomy: Taxonomy, concept_uri: str) -> dict:
    """Serialise the SKOS neighbourhood of *concept_uri* into a payload.

    Centred on one concept, the subgraph contains:
      * the focus concept;
      * its full broader chain, so the focus keeps its place in the hierarchy
        rather than floating free — the same context the class explorer gives
        through the subClassOf trail;
      * its direct narrower concepts, which is what digging down means here.

    Only *direct* narrower are included: pulling the whole subtree would hand
    back most of the thesaurus for a top concept, which is the hairball the
    explorer exists to avoid. Extending from a narrower node walks one more
    level, so depth stays a decision the reader makes per step.

    Returns an empty payload when *concept_uri* is not a known concept.
    """
    if concept_uri not in taxonomy.concepts:
        return {_LIT_NODES: [], _LIT_EDGES: [], _LIT_LAYOUT: "preset"}

    pairs = _broader_chain(taxonomy, concept_uri)
    pairs += [(child, concept_uri) for child in sorted(_direct_narrower(taxonomy, concept_uri))]

    seen: set[str] = set()
    nodes: list[dict] = []
    for uri in [concept_uri, *(u for pair in pairs for u in pair)]:
        if uri not in seen:
            seen.add(uri)
            nodes.append(_concept_node(taxonomy, uri))
    edges = [
        {"id": f"e{i}", _LIT_SOURCE: source, _LIT_TARGET: target, "type": "broader", _LIT_LABEL: ""}
        for i, (source, target) in enumerate(pairs)
    ]
    return {_LIT_NODES: nodes, _LIT_EDGES: edges, _LIT_LAYOUT: "cose"}


def _concept_node(taxonomy: Taxonomy, uri: str) -> dict:
    concept = taxonomy.concepts[uri]
    return {
        "id": uri,
        _LIT_LABEL: concept.pref_label("en"),
        "type": "topconcept" if concept.top_concept_of else "concept",
        "detail": _detail_concept(concept, taxonomy),
        _LIT_ROOT_CLASS: 0,
    }


def _broader_chain(taxonomy: Taxonomy, uri: str) -> list[tuple[str, str]]:
    """(child, parent) pairs walking root-ward from *uri*.

    Cycle-safe: a thesaurus with a broader-loop stops instead of hanging.
    """
    pairs: list[tuple[str, str]] = []
    current, walked = uri, {uri}
    while True:
        parents = (p for p in taxonomy.concepts[current].broader if p in taxonomy.concepts)
        nxt = next((p for p in parents if p not in walked), None)
        if nxt is None:
            return pairs
        pairs.append((current, nxt))
        walked.add(nxt)
        current = nxt


def _direct_narrower(taxonomy: Taxonomy, uri: str) -> set[str]:
    """Children of *uri*, however the file states the relation.

    A thesaurus may assert only ``narrower`` on the parent or only ``broader`` on
    the child; digging down has to work either way.
    """
    children = set(taxonomy.concepts[uri].narrower)
    children.update(u for u, c in taxonomy.concepts.items() if uri in c.broader)
    return {c for c in children if c in taxonomy.concepts}


class _RelationsGraph:
    """Mutable accumulator (nodes/edges/dedup state) for one relations subgraph."""

    def __init__(self, taxonomy: Taxonomy) -> None:
        self.taxonomy = taxonomy
        self.nodes: list[dict] = []
        self.edges: list[dict] = []
        self.seen_nodes: set[str] = set()
        self.seen_subclass_edges: set[tuple[str, str]] = set()
        self._eid_counter = itertools.count()

    def eid(self) -> str:
        return f"e{next(self._eid_counter)}"

    def add_node(
        self,
        uri: str,
        label: str,
        node_type: str,
        detail: dict | None = None,
        superclass: int = 0,
    ) -> None:
        if uri not in self.seen_nodes:
            self.seen_nodes.add(uri)
            self.nodes.append(
                {
                    "id": uri,
                    _LIT_LABEL: label,
                    "type": node_type,
                    "detail": detail or {},
                    "readOnly": 1 if uri in self.taxonomy.context_source else 0,
                    _LIT_ROOT_CLASS: 0,
                    "superclass": superclass,
                }
            )

    def add_individual(self, uri: str) -> None:
        ind = self.taxonomy.owl_individuals[uri]
        self.add_node(uri, ind.label("en"), "individual", _detail_individual(ind, self.taxonomy))

    def prop_label(self, prop_uri: str) -> str:
        prop = self.taxonomy.owl_properties.get(prop_uri)
        return prop.label("en") if prop else _local(prop_uri)


def _add_outgoing_relation_edges(
    g: _RelationsGraph, taxonomy: Taxonomy, ind_uri: str, related: set[str]
) -> None:
    """focus --prop--> target (object-property values to individuals)."""
    for prop_uri, val_uri in taxonomy.owl_individuals[ind_uri].property_values:
        if val_uri in taxonomy.owl_individuals:
            g.add_individual(val_uri)
            related.add(val_uri)
            g.edges.append(
                {
                    "id": g.eid(),
                    _LIT_SOURCE: ind_uri,
                    _LIT_TARGET: val_uri,
                    "type": "objectProperty",
                    _LIT_LABEL: g.prop_label(prop_uri),
                }
            )


def _add_incoming_relation_edges(
    g: _RelationsGraph, taxonomy: Taxonomy, ind_uri: str, related: set[str]
) -> None:
    """source --prop--> focus."""
    for src_uri, src in taxonomy.owl_individuals.items():
        if src_uri == ind_uri:
            continue
        for prop_uri, val_uri in src.property_values:
            if val_uri == ind_uri:
                g.add_individual(src_uri)
                related.add(src_uri)
                g.edges.append(
                    {
                        "id": g.eid(),
                        _LIT_SOURCE: src_uri,
                        _LIT_TARGET: ind_uri,
                        "type": "objectProperty",
                        _LIT_LABEL: g.prop_label(prop_uri),
                    }
                )


def _direct_types_of(taxonomy: Taxonomy, uris: set[str]) -> set[str]:
    """Class URIs that are the direct rdf:type of some individual in *uris*."""
    return {
        t for x_uri in uris for t in taxonomy.owl_individuals[x_uri].types if not is_builtin_uri(t)
    }


def _queue_ancestor_parents(
    g: _RelationsGraph, cls: RDFClass | None, cur: str, stack: list[str]
) -> None:
    for parent in cls.sub_class_of if cls else []:
        if is_builtin_uri(parent):
            continue
        if (cur, parent) not in g.seen_subclass_edges:
            g.seen_subclass_edges.add((cur, parent))
            g.edges.append(
                {
                    "id": g.eid(),
                    _LIT_SOURCE: cur,
                    _LIT_TARGET: parent,
                    "type": "subClassOf",
                    _LIT_LABEL: "",
                }
            )
        stack.append(parent)


def _add_class_with_ancestors(
    g: _RelationsGraph, taxonomy: Taxonomy, cls_uri: str, direct_types: set[str]
) -> None:
    """Add *cls_uri* and its transitive ``subClassOf`` ancestors as a trail.

    Each ancestor becomes a class node and each step a ``subClassOf`` edge
    (child → parent).  Builtin URIs are skipped, ancestor nodes and edges are
    de-duplicated, and subclass cycles terminate via the visited set.
    """
    stack = [cls_uri]
    visited: set[str] = set()
    while stack:
        cur = stack.pop()
        if cur in visited or is_builtin_uri(cur):
            continue
        visited.add(cur)
        cls = taxonomy.owl_classes.get(cur)
        label = cls.label("en") if cls else _local(cur)
        detail = _detail_class(cls, taxonomy) if cls else {}
        g.add_node(cur, label, "class", detail, superclass=0 if cur in direct_types else 1)
        _queue_ancestor_parents(g, cls, cur, stack)


def _add_type_edges_and_ancestors(
    g: _RelationsGraph, taxonomy: Taxonomy, uris: set[str], direct_types: set[str]
) -> None:
    """rdf:type (and the superclass trail above each class) for each of *uris*."""
    for x_uri in uris:
        for type_uri in taxonomy.owl_individuals[x_uri].types:
            if is_builtin_uri(type_uri):
                continue
            _add_class_with_ancestors(g, taxonomy, type_uri, direct_types)
            g.edges.append(
                {
                    "id": g.eid(),
                    _LIT_SOURCE: x_uri,
                    _LIT_TARGET: type_uri,
                    "type": "instanceOf",
                    _LIT_LABEL: "",
                }
            )


def build_individual_relations_graph(taxonomy: Taxonomy, ind_uri: str) -> dict:
    """Serialise the object-property neighbourhood of *ind_uri* into a payload.

    Centred on one individual, the subgraph contains:
      * the focus individual;
      * every individual linked to it by an object property in **either**
        direction (incoming ``S --prop--> focus`` and outgoing
        ``focus --prop--> T``), each as a directed, property-labelled edge;
      * the class(es) the focus belongs to (``instanceOf`` edges);
      * the class(es) of every related individual.

    Datatype / literal assertions are ignored. Returns an empty payload when
    *ind_uri* is not a known individual.  Layout is always ``cose``.
    """
    if ind_uri not in taxonomy.owl_individuals:
        return {_LIT_NODES: [], _LIT_EDGES: [], _LIT_LAYOUT: "cose"}

    g = _RelationsGraph(taxonomy)
    g.add_individual(ind_uri)

    related: set[str] = set()
    _add_outgoing_relation_edges(g, taxonomy, ind_uri, related)
    _add_incoming_relation_edges(g, taxonomy, ind_uri, related)

    all_uris = {ind_uri, *related}
    direct_types = _direct_types_of(taxonomy, all_uris)
    _add_type_edges_and_ancestors(g, taxonomy, all_uris, direct_types)

    return {_LIT_NODES: g.nodes, _LIT_EDGES: g.edges, _LIT_LAYOUT: "cose"}
