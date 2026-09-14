"""Full-graph and class-links VOWL graph builders (build_vowl_graph, build_focused_vowl_graph, build_class_links_graph)."""

from __future__ import annotations

import itertools
from collections import deque
from collections.abc import Iterator
from typing import Final

from ..model import OWLProperty, Taxonomy, is_builtin_uri
from ..viz import (
    _detail_class,
    _detail_concept,
    _detail_individual,
    _detail_scheme,
    _label_for,  # noqa: F401  (re-exported for potential callers)
    _local,
)

_LIT_OBJECTPROPERTY: Final = "ObjectProperty"
_LIT_CLASS: Final = "class"
_LIT_EDGES: Final = "edges"
_LIT_LABEL: Final = "label"
_LIT_LAYOUT: Final = "layout"
_LIT_NODES: Final = "nodes"
_LIT_OBJECT_PROPERTY_CAMEL: Final = "objectProperty"
_LIT_ROOTCLASS: Final = "rootClass"
_LIT_SOURCE: Final = "source"
_LIT_SUBCLASSOF: Final = "subClassOf"
_LIT_TARGET: Final = "target"


def _add_node(
    nodes: list[dict],
    seen_nodes: set[str],
    taxonomy: Taxonomy,
    uri: str,
    label: str,
    node_type: str,
    detail: dict | None = None,
) -> None:
    if uri not in seen_nodes:
        seen_nodes.add(uri)
        nodes.append(
            {
                "id": uri,
                _LIT_LABEL: label,
                "type": node_type,
                "detail": detail or {},
                "readOnly": 1 if uri in taxonomy.context_source else 0,
                _LIT_ROOTCLASS: 0,
            }
        )


def _add_owl_class_nodes(taxonomy: Taxonomy, nodes: list[dict], seen_nodes: set[str]) -> None:
    for uri, cls in taxonomy.owl_classes.items():
        _add_node(
            nodes,
            seen_nodes,
            taxonomy,
            uri,
            cls.label("en"),
            _LIT_CLASS,
            _detail_class(cls, taxonomy),
        )


def _add_owl_individual_nodes(taxonomy: Taxonomy, nodes: list[dict], seen_nodes: set[str]) -> None:
    for uri, ind in taxonomy.owl_individuals.items():
        _add_node(
            nodes,
            seen_nodes,
            taxonomy,
            uri,
            ind.label("en"),
            "individual",
            _detail_individual(ind, taxonomy),
        )


def _add_subclass_edges(
    taxonomy: Taxonomy, edges: list[dict], seen_nodes: set[str], eid_counter: Iterator[int]
) -> None:
    for uri, cls in taxonomy.owl_classes.items():
        for parent in cls.sub_class_of:
            if not is_builtin_uri(parent) and parent in seen_nodes:
                edges.append(
                    {
                        "id": f"e{next(eid_counter)}",
                        _LIT_SOURCE: uri,
                        _LIT_TARGET: parent,
                        "type": _LIT_SUBCLASSOF,
                        _LIT_LABEL: "",
                    }
                )


def _add_object_property_edge_if_seen(
    prop: OWLProperty,
    plabel: str,
    domain_uri: str,
    range_uri: str,
    edges: list[dict],
    seen_nodes: set[str],
    eid_counter: Iterator[int],
) -> None:
    if domain_uri not in seen_nodes or range_uri not in seen_nodes:
        return
    e: dict = {
        "id": f"e{next(eid_counter)}",
        _LIT_SOURCE: domain_uri,
        _LIT_TARGET: range_uri,
        "type": _LIT_OBJECT_PROPERTY_CAMEL,
        _LIT_LABEL: plabel,
    }
    if prop.is_functional:
        e["cardinality"] = "0..1"
    edges.append(e)


def _add_object_property_edges(
    taxonomy: Taxonomy, edges: list[dict], seen_nodes: set[str], eid_counter: Iterator[int]
) -> None:
    for prop in taxonomy.owl_properties.values():
        if prop.prop_type != _LIT_OBJECTPROPERTY:
            continue
        plabel = prop.label("en")
        for domain_uri in prop.domains:
            for range_uri in prop.ranges:
                _add_object_property_edge_if_seen(
                    prop, plabel, domain_uri, range_uri, edges, seen_nodes, eid_counter
                )


def _add_datatype_property_nodes_and_edges(
    taxonomy: Taxonomy,
    nodes: list[dict],
    edges: list[dict],
    seen_nodes: set[str],
    eid_counter: Iterator[int],
) -> None:
    for prop in taxonomy.owl_properties.values():
        if prop.prop_type != "DatatypeProperty":
            continue
        plabel = prop.label("en")
        for domain_uri in prop.domains:
            if domain_uri not in seen_nodes:
                continue
            for range_uri in prop.ranges:
                if range_uri in seen_nodes:
                    continue
                _add_node(nodes, seen_nodes, taxonomy, range_uri, _local(range_uri), "datatype")
                edges.append(
                    {
                        "id": f"e{next(eid_counter)}",
                        _LIT_SOURCE: domain_uri,
                        _LIT_TARGET: range_uri,
                        "type": "datatypeProperty",
                        _LIT_LABEL: plabel,
                    }
                )


def _add_individual_type_edges(
    taxonomy: Taxonomy,
    nodes: list[dict],
    edges: list[dict],
    seen_nodes: set[str],
    eid_counter: Iterator[int],
) -> None:
    for uri, ind in taxonomy.owl_individuals.items():
        for type_uri in ind.types:
            if is_builtin_uri(type_uri):
                continue
            if type_uri not in seen_nodes:
                _add_node(nodes, seen_nodes, taxonomy, type_uri, _local(type_uri), _LIT_CLASS, {})
            edges.append(
                {
                    "id": f"e{next(eid_counter)}",
                    _LIT_SOURCE: uri,
                    _LIT_TARGET: type_uri,
                    "type": "instanceOf",
                    _LIT_LABEL: "",
                }
            )


def _add_skos_scheme_nodes(taxonomy: Taxonomy, nodes: list[dict], seen_nodes: set[str]) -> None:
    for uri, scheme in taxonomy.schemes.items():
        _add_node(
            nodes,
            seen_nodes,
            taxonomy,
            uri,
            scheme.title("en"),
            "scheme",
            _detail_scheme(scheme, taxonomy),
        )


def _add_skos_concept_nodes(taxonomy: Taxonomy, nodes: list[dict], seen_nodes: set[str]) -> None:
    top_concept_uris: set[str] = {u for u, c in taxonomy.concepts.items() if c.top_concept_of}
    for uri, concept in taxonomy.concepts.items():
        ntype = "topconcept" if uri in top_concept_uris else "concept"
        _add_node(
            nodes,
            seen_nodes,
            taxonomy,
            uri,
            concept.pref_label("en"),
            ntype,
            _detail_concept(concept, taxonomy),
        )


def _add_skos_broader_edges(
    taxonomy: Taxonomy, edges: list[dict], seen_nodes: set[str], eid_counter: Iterator[int]
) -> None:
    for uri, concept in taxonomy.concepts.items():
        for broader_uri in concept.broader:
            if broader_uri in seen_nodes and uri in seen_nodes:
                edges.append(
                    {
                        "id": f"e{next(eid_counter)}",
                        _LIT_SOURCE: uri,
                        _LIT_TARGET: broader_uri,
                        "type": "broader",
                        _LIT_LABEL: "",
                    }
                )
        if concept.top_concept_of and concept.top_concept_of in seen_nodes:
            edges.append(
                {
                    "id": f"e{next(eid_counter)}",
                    _LIT_SOURCE: uri,
                    _LIT_TARGET: concept.top_concept_of,
                    "type": "inScheme",
                    _LIT_LABEL: "",
                }
            )


def _mark_root_classes(taxonomy: Taxonomy, nodes: list[dict]) -> None:
    non_root = {
        cls_uri
        for cls_uri, cls in taxonomy.owl_classes.items()
        for p in cls.sub_class_of
        if not is_builtin_uri(p) and p in taxonomy.owl_classes
    }
    for n in nodes:
        if n["type"] == _LIT_CLASS:
            n[_LIT_ROOTCLASS] = 0 if n["id"] in non_root else 1


def build_vowl_graph(taxonomy: Taxonomy) -> dict:
    """Serialise *taxonomy* into a Cytoscape.js-compatible {nodes, edges, layout} payload.

    Entities merged from a read-only context file carry ``readOnly: 1`` so the
    browser can show that they belong to another file — a node you cannot edit
    must not look like one you can.
    """
    nodes: list[dict] = []
    edges: list[dict] = []
    seen_nodes: set[str] = set()
    eid_counter = itertools.count()

    _add_owl_class_nodes(taxonomy, nodes, seen_nodes)
    _add_owl_individual_nodes(taxonomy, nodes, seen_nodes)
    _add_subclass_edges(taxonomy, edges, seen_nodes, eid_counter)
    _add_object_property_edges(taxonomy, edges, seen_nodes, eid_counter)
    _add_datatype_property_nodes_and_edges(taxonomy, nodes, edges, seen_nodes, eid_counter)
    _add_individual_type_edges(taxonomy, nodes, edges, seen_nodes, eid_counter)
    _add_skos_scheme_nodes(taxonomy, nodes, seen_nodes)
    _add_skos_concept_nodes(taxonomy, nodes, seen_nodes)
    _add_skos_broader_edges(taxonomy, edges, seen_nodes, eid_counter)
    _mark_root_classes(taxonomy, nodes)

    return {_LIT_NODES: nodes, _LIT_EDGES: edges, _LIT_LAYOUT: "cose"}


def _root_class_uris(taxonomy: Taxonomy) -> set[str]:
    """Class URIs never named as a (non-builtin) subclass's parent."""
    non_root = {
        cls_uri
        for cls_uri, cls in taxonomy.owl_classes.items()
        for p in cls.sub_class_of
        if not is_builtin_uri(p) and p in taxonomy.owl_classes
    }
    return set(taxonomy.owl_classes) - non_root


# Above this many classes — or this many concepts — that half of the default
# view shows roots only. Mirrors INDIVIDUAL_COLLAPSE_LIMIT's reasoning exactly,
# one level up the tree: below the threshold a taxonomy is legible whole, and
# scoping it would only hide things (see
# test_a_small_ontology_is_left_whole_on_the_page_too).
#
# The budget is per half, not shared. An OWL ontology and a SKOS scheme are
# drawn in two separate tabs, so neither can crowd the other on screen, and a
# shared budget meant that opening a 1,373-concept taxonomy alongside a
# 23-class metamodel collapsed the metamodel to 19 root classes — hiding an
# ontology that was perfectly legible and had not grown at all.
CLASS_COLLAPSE_LIMIT = 150


def build_default_vowl_graph(taxonomy: Taxonomy) -> dict:
    """Root-level overview: schemes, root classes and top concepts only.

    ``build_vowl_graph`` renders every class, property, and concept at once —
    legible for a small ontology, a wall of dots for a large one (the graph
    view's reported "unusable on large ontologies" problem — see
    docs/architecture/graph-editor.md). Above ``CLASS_COLLAPSE_LIMIT`` this
    renders roots only, each explorable via the same click-to-expand
    endpoints already used elsewhere (``/api/class-links``,
    ``/api/concept-relations``) to reveal their children on demand. Below it,
    unchanged: the full graph, same as ``build_vowl_graph``.

    Root/top-concept detection is done on bare URIs before any node is built,
    so — unlike filtering ``build_vowl_graph``'s output after the fact — the
    (potentially expensive) per-node detail lookup only ever runs for the
    roots actually kept, not for every class/concept in the file.

    Each half is judged on its own size: a large scheme no longer scopes away a
    small ontology it merely sits beside.
    """
    classes_fit = len(taxonomy.owl_classes) <= CLASS_COLLAPSE_LIMIT
    concepts_fit = len(taxonomy.concepts) <= CLASS_COLLAPSE_LIMIT
    if classes_fit and concepts_fit:
        return build_vowl_graph(taxonomy)

    nodes: list[dict] = []
    edges: list[dict] = []
    seen_nodes: set[str] = set()
    eid_counter = itertools.count()

    if classes_fit:
        _add_owl_class_nodes(taxonomy, nodes, seen_nodes)
        _add_subclass_edges(taxonomy, edges, seen_nodes, eid_counter)
        _add_object_property_edges(taxonomy, edges, seen_nodes, eid_counter)
        _add_datatype_property_nodes_and_edges(taxonomy, nodes, edges, seen_nodes, eid_counter)
        _mark_root_classes(taxonomy, nodes)
    else:
        _add_root_class_nodes(taxonomy, nodes, seen_nodes)

    _add_skos_scheme_nodes(taxonomy, nodes, seen_nodes)
    if concepts_fit:
        _add_skos_concept_nodes(taxonomy, nodes, seen_nodes)
    else:
        _add_top_concept_nodes(taxonomy, nodes, seen_nodes)
    _add_skos_broader_edges(taxonomy, edges, seen_nodes, eid_counter)

    return {_LIT_NODES: nodes, _LIT_EDGES: edges, _LIT_LAYOUT: "cose"}


def _add_root_class_nodes(taxonomy: Taxonomy, nodes: list[dict], seen_nodes: set[str]) -> None:
    """The class half, scoped: roots only, each explorable via /api/class-links."""
    for uri in _root_class_uris(taxonomy):
        cls = taxonomy.owl_classes[uri]
        _add_node(
            nodes,
            seen_nodes,
            taxonomy,
            uri,
            cls.label("en"),
            _LIT_CLASS,
            _detail_class(cls, taxonomy),
        )
    for n in nodes:
        if n["type"] == _LIT_CLASS:
            n[_LIT_ROOTCLASS] = 1


def _add_top_concept_nodes(taxonomy: Taxonomy, nodes: list[dict], seen_nodes: set[str]) -> None:
    """The concept half, scoped: top concepts only, explorable via
    /api/concept-relations."""
    for uri, concept in taxonomy.concepts.items():
        if not concept.top_concept_of:
            continue
        _add_node(
            nodes,
            seen_nodes,
            taxonomy,
            uri,
            concept.pref_label("en"),
            "topconcept",
            _detail_concept(concept, taxonomy),
        )


def _included_class_closure(taxonomy: Taxonomy, root_uri: str) -> set[str]:
    """BFS-collect *root_uri* plus every transitive subclass."""
    children_of: dict[str, list[str]] = {u: [] for u in taxonomy.owl_classes}
    for uri, cls in taxonomy.owl_classes.items():
        for parent in cls.sub_class_of:
            if parent in children_of:
                children_of[parent].append(uri)

    included: set[str] = set()
    queue: deque[str] = deque([root_uri])
    while queue:
        uri = queue.popleft()
        if uri in included:
            continue
        included.add(uri)
        queue.extend(children_of.get(uri, []))
    return included


def _add_focused_class_nodes(
    taxonomy: Taxonomy, included_classes: set[str], nodes: list[dict], seen_nodes: set[str]
) -> None:
    for cls_uri in included_classes:
        cls = taxonomy.owl_classes[cls_uri]
        _add_node(
            nodes,
            seen_nodes,
            taxonomy,
            cls_uri,
            cls.label("en"),
            _LIT_CLASS,
            _detail_class(cls, taxonomy),
        )


def _add_focused_subclass_edges(
    taxonomy: Taxonomy, included_classes: set[str], edges: list[dict], eid_counter: Iterator[int]
) -> None:
    for cls_uri in included_classes:
        cls = taxonomy.owl_classes[cls_uri]
        for parent_uri in cls.sub_class_of:
            if parent_uri in included_classes:
                edges.append(
                    {
                        "id": f"e{next(eid_counter)}",
                        _LIT_SOURCE: cls_uri,
                        _LIT_TARGET: parent_uri,
                        "type": _LIT_SUBCLASSOF,
                        _LIT_LABEL: "",
                    }
                )


def _add_focused_object_property_edge(
    prop: OWLProperty,
    plabel: str,
    domain_uri: str,
    range_uri: str,
    seen_nodes: set[str],
    edges: list[dict],
    eid_counter: Iterator[int],
) -> None:
    if range_uri not in seen_nodes:
        return
    ef: dict = {
        "id": f"e{next(eid_counter)}",
        _LIT_SOURCE: domain_uri,
        _LIT_TARGET: range_uri,
        "type": _LIT_OBJECT_PROPERTY_CAMEL,
        _LIT_LABEL: plabel,
    }
    if prop.is_functional:
        ef["cardinality"] = "0..1"
    edges.append(ef)


def _add_focused_object_property_edges(
    taxonomy: Taxonomy,
    included_classes: set[str],
    seen_nodes: set[str],
    edges: list[dict],
    eid_counter: Iterator[int],
) -> None:
    for prop in taxonomy.owl_properties.values():
        if prop.prop_type != _LIT_OBJECTPROPERTY:
            continue
        plabel = prop.label("en")
        for domain_uri in prop.domains:
            if domain_uri not in included_classes:
                continue
            for range_uri in prop.ranges:
                _add_focused_object_property_edge(
                    prop, plabel, domain_uri, range_uri, seen_nodes, edges, eid_counter
                )


def _add_focused_datatype_property_nodes_and_edges(
    taxonomy: Taxonomy,
    included_classes: set[str],
    nodes: list[dict],
    seen_nodes: set[str],
    edges: list[dict],
    eid_counter: Iterator[int],
) -> None:
    for prop in taxonomy.owl_properties.values():
        if prop.prop_type != "DatatypeProperty":
            continue
        plabel = prop.label("en")
        for domain_uri in prop.domains:
            if domain_uri not in included_classes:
                continue
            for range_uri in prop.ranges:
                if range_uri in seen_nodes:
                    continue
                _add_node(nodes, seen_nodes, taxonomy, range_uri, _local(range_uri), "datatype")
                edges.append(
                    {
                        "id": f"e{next(eid_counter)}",
                        _LIT_SOURCE: domain_uri,
                        _LIT_TARGET: range_uri,
                        "type": "datatypeProperty",
                        _LIT_LABEL: plabel,
                    }
                )


def _add_focused_property_edges(
    taxonomy: Taxonomy,
    included_classes: set[str],
    nodes: list[dict],
    seen_nodes: set[str],
    edges: list[dict],
    eid_counter: Iterator[int],
) -> None:
    _add_focused_object_property_edges(taxonomy, included_classes, seen_nodes, edges, eid_counter)
    _add_focused_datatype_property_nodes_and_edges(
        taxonomy, included_classes, nodes, seen_nodes, edges, eid_counter
    )


def _add_focused_individual_nodes_and_edges(
    taxonomy: Taxonomy,
    included_classes: set[str],
    nodes: list[dict],
    seen_nodes: set[str],
    edges: list[dict],
    eid_counter: Iterator[int],
) -> None:
    for ind_uri, ind in taxonomy.owl_individuals.items():
        for type_uri in ind.types:
            if type_uri in included_classes:
                _add_node(
                    nodes,
                    seen_nodes,
                    taxonomy,
                    ind_uri,
                    ind.label("en"),
                    "individual",
                    _detail_individual(ind, taxonomy),
                )
                edges.append(
                    {
                        "id": f"e{next(eid_counter)}",
                        _LIT_SOURCE: ind_uri,
                        _LIT_TARGET: type_uri,
                        "type": "instanceOf",
                        _LIT_LABEL: "",
                    }
                )
                break


def _mark_focused_root_classes(
    taxonomy: Taxonomy, included_classes: set[str], nodes: list[dict]
) -> None:
    non_root_f = {
        u
        for u in included_classes
        if any(
            p in included_classes
            for p in taxonomy.owl_classes[u].sub_class_of
            if not is_builtin_uri(p)
        )
    }
    for n in nodes:
        if n["type"] == _LIT_CLASS:
            n[_LIT_ROOTCLASS] = 0 if n["id"] in non_root_f else 1


def build_focused_vowl_graph(taxonomy: Taxonomy, root_uri: str) -> dict:
    """Serialise a focused subgraph rooted at *root_uri* into Cytoscape payload.

    Collects the root class, all transitive subclasses, and individuals of those
    classes.  Property edges between included nodes are also included.
    """
    if root_uri not in taxonomy.owl_classes:
        return {_LIT_NODES: [], _LIT_EDGES: [], _LIT_LAYOUT: "preset"}

    included_classes = _included_class_closure(taxonomy, root_uri)

    nodes: list[dict] = []
    edges: list[dict] = []
    seen_nodes: set[str] = set()
    eid_counter = itertools.count()

    _add_focused_class_nodes(taxonomy, included_classes, nodes, seen_nodes)
    _add_focused_subclass_edges(taxonomy, included_classes, edges, eid_counter)
    _add_focused_property_edges(taxonomy, included_classes, nodes, seen_nodes, edges, eid_counter)
    _add_focused_individual_nodes_and_edges(
        taxonomy, included_classes, nodes, seen_nodes, edges, eid_counter
    )
    _mark_focused_root_classes(taxonomy, included_classes, nodes)

    return {_LIT_NODES: nodes, _LIT_EDGES: edges, _LIT_LAYOUT: "cose"}


class _ClassLinksGraph:
    """Mutable accumulator (nodes/edges/dedup state) for one class-links subgraph."""

    def __init__(self, taxonomy: Taxonomy) -> None:
        self.taxonomy = taxonomy
        self.nodes: list[dict] = []
        self.edges: list[dict] = []
        self.seen_nodes: set[str] = set()
        self.seen_subclass_edges: set[tuple[str, str]] = set()
        self._eid_counter = itertools.count()

    def eid(self) -> str:
        return f"e{next(self._eid_counter)}"

    def add_class(self, uri: str, superclass: int = 0) -> None:
        if uri in self.seen_nodes or is_builtin_uri(uri):
            return
        self.seen_nodes.add(uri)
        cls = self.taxonomy.owl_classes.get(uri)
        label = cls.label("en") if cls else _local(uri)
        detail = _detail_class(cls, self.taxonomy) if cls else {}
        self.nodes.append(
            {
                "id": uri,
                _LIT_LABEL: label,
                "type": _LIT_CLASS,
                "detail": detail,
                _LIT_ROOTCLASS: 0,
                "superclass": superclass,
            }
        )


def _link_class_pair(
    g: _ClassLinksGraph, class_uri: str, plabel: str, d: str, r: str, linked: set[str]
) -> None:
    if is_builtin_uri(d) or is_builtin_uri(r):
        return
    if d == class_uri and r != class_uri:
        g.add_class(r, superclass=0)
        linked.add(r)
        g.edges.append(
            {
                "id": g.eid(),
                _LIT_SOURCE: d,
                _LIT_TARGET: r,
                "type": _LIT_OBJECT_PROPERTY_CAMEL,
                _LIT_LABEL: plabel,
            }
        )
    elif r == class_uri and d != class_uri:
        g.add_class(d, superclass=0)
        linked.add(d)
        g.edges.append(
            {
                "id": g.eid(),
                _LIT_SOURCE: d,
                _LIT_TARGET: r,
                "type": _LIT_OBJECT_PROPERTY_CAMEL,
                _LIT_LABEL: plabel,
            }
        )


def _add_object_property_linked_classes(
    g: _ClassLinksGraph, taxonomy: Taxonomy, class_uri: str, subclass_only: bool
) -> set[str]:
    """Add every class linked to *class_uri* by an object property, either direction."""
    linked: set[str] = set()
    # In subclass-only mode the T-Box object-property links between classes are
    # omitted (used when exploration started from an individual — the object
    # properties are already shown between the individuals at the A-Box level).
    props = [] if subclass_only else list(taxonomy.owl_properties.values())
    for prop in props:
        if prop.prop_type != _LIT_OBJECTPROPERTY:
            continue
        plabel = prop.label("en")
        for d in prop.domains:
            for r in prop.ranges:
                _link_class_pair(g, class_uri, plabel, d, r, linked)
    return linked


def _queue_superclass_parents(
    g: _ClassLinksGraph, taxonomy: Taxonomy, cur: str, stack: list[str]
) -> None:
    cls = taxonomy.owl_classes.get(cur)
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
                    "type": _LIT_SUBCLASSOF,
                    _LIT_LABEL: "",
                }
            )
        stack.append(parent)


def _add_class_links_superclass_trail(
    g: _ClassLinksGraph, taxonomy: Taxonomy, class_uri: str, linked: set[str]
) -> None:
    """Add the transitive subClassOf trail above the focus class and every linked class."""
    non_superclass = {class_uri, *linked}
    stack = [class_uri, *linked]
    visited: set[str] = set()
    while stack:
        cur = stack.pop()
        if cur in visited or is_builtin_uri(cur):
            continue
        visited.add(cur)
        g.add_class(cur, superclass=0 if cur in non_superclass else 1)
        _queue_superclass_parents(g, taxonomy, cur, stack)


def build_class_links_graph(
    taxonomy: Taxonomy, class_uri: str, subclass_only: bool = False
) -> dict:
    """Serialise the linked-classes neighbourhood of *class_uri* into a payload.

    Centred on one class, the subgraph contains:
      * the focus class;
      * its transitive ``subClassOf`` superclass trail (ancestor classes flagged
        ``superclass=1``, with ``subClassOf`` edges);
      * every class connected by an object property — both where the focus is the
        property's domain (``focus --prop--> range``) and where it is the range
        (``domain --prop--> focus``), as directed, property-labelled edges.

    Returns an empty payload when *class_uri* is not a known class.  Layout is
    always ``cose``.
    """
    if class_uri not in taxonomy.owl_classes:
        return {_LIT_NODES: [], _LIT_EDGES: [], _LIT_LAYOUT: "cose"}

    g = _ClassLinksGraph(taxonomy)
    g.add_class(class_uri, superclass=0)

    linked = _add_object_property_linked_classes(g, taxonomy, class_uri, subclass_only)
    _add_class_links_superclass_trail(g, taxonomy, class_uri, linked)

    return {_LIT_NODES: g.nodes, _LIT_EDGES: g.edges, _LIT_LAYOUT: "cose"}
