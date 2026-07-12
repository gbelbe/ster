"""Config-driven per-language ``rdfs:label`` SHACL shapes, authored by ster.

semanticlint 0.5 generates a per-language shape only for concept ``skos:prefLabel``
(QUA003, from ``quality["languages"]``). It has no equivalent for OWL class or
property ``rdfs:label`` — and the library is a pinned dependency we cannot extend.

So ster *authors* those shapes here (in memory) and hands them to semanticlint's
``run_shapes(extra_shapes=…)`` — exactly the seam it already uses for local
``*.shapes.ttl`` business rules. pySHACL runs them; ster never computes the
violations itself. This mirrors semanticlint's own ``shacl/builder.py`` for QUA003.
"""

from __future__ import annotations

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.collection import Collection
from rdflib.namespace import OWL, RDF, RDFS, SH  # noqa: N811 — SH is the SHACL namespace

_SLINT = Namespace("https://semanticlint.org/ns#")
_SHAPE_PREFIX = "urn:ster:langshape:"

# label-type → (target class IRIs, semanticlint check id, human noun for the message).
_LABEL_TYPES: dict[str, tuple[tuple[URIRef, ...], str, str]] = {
    "class": ((OWL.Class, RDFS.Class), "STER001", "Class"),
    "property": (
        (OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty),
        "STER002",
        "Property",
    ),
}


def build_label_language_shapes(class_langs: list[str], property_langs: list[str]) -> Graph:
    """A SHACL shapes graph requiring an ``rdfs:label`` in each listed language on every
    class / property. Empty when both lists are empty (no requirement → no shapes)."""
    graph = Graph()
    for label_type, langs in (("class", class_langs), ("property", property_langs)):
        for lang in langs:
            _add_shape(graph, label_type, lang)
    return graph


def _add_shape(graph: Graph, label_type: str, lang: str) -> None:
    """One NodeShape: every *label_type* target must carry an ``rdfs:label`` in *lang*
    (``sh:languageIn`` + ``sh:qualifiedMinCount 1``), a Warning when absent."""
    targets, check_id, noun = _LABEL_TYPES[label_type]
    shape = URIRef(f"{_SHAPE_PREFIX}{label_type}:{lang}")
    graph.add((shape, RDF.type, SH.NodeShape))
    graph.add((shape, _SLINT.checkId, Literal(check_id)))
    for target in targets:
        graph.add((shape, SH.targetClass, target))

    prop = BNode()
    graph.add((shape, SH.property, prop))
    graph.add((prop, SH.path, RDFS.label))
    graph.add((prop, SH.qualifiedMinCount, Literal(1)))
    graph.add((prop, SH.severity, SH.Warning))
    graph.add((prop, SH.message, Literal(f"{noun} missing rdfs:label in language '{lang}'")))

    qualified = BNode()
    graph.add((prop, SH.qualifiedValueShape, qualified))
    lang_list = BNode()
    graph.add((qualified, SH.languageIn, lang_list))
    Collection(graph, lang_list, [Literal(lang)])
