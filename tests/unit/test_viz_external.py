"""Unit tests for external-node type detection in viz.build_graph."""

from __future__ import annotations

from ster.model import OWLIndividual, RDFClass, Taxonomy

_FOAF_NS = "http://xmlns.com/foaf/0.1/"
_KAI_NS = "http://example.org/kai#"


def _taxonomy_with_external() -> Taxonomy:
    t = Taxonomy()
    t.namespace_bindings = {"foaf": _FOAF_NS}
    local_cls = RDFClass(uri=f"{_KAI_NS}Person")
    ext_cls = RDFClass(uri=f"{_FOAF_NS}Person")
    t.owl_classes[local_cls.uri] = local_cls
    t.owl_classes[ext_cls.uri] = ext_cls
    local_ind = OWLIndividual(uri=f"{_KAI_NS}Alice", types=[local_cls.uri])
    ext_ind = OWLIndividual(uri=f"{_FOAF_NS}Bob", types=[ext_cls.uri])
    t.owl_individuals[local_ind.uri] = local_ind
    t.owl_individuals[ext_ind.uri] = ext_ind
    return t


def test_build_graph_external_class_type():
    from ster.viz import build_graph

    t = _taxonomy_with_external()
    data = build_graph(t)
    node = next(n for n in data["nodes"] if n["id"] == f"{_FOAF_NS}Person")
    assert node["type"] == "external-class"


def test_build_graph_local_class_type():
    from ster.viz import build_graph

    t = _taxonomy_with_external()
    data = build_graph(t)
    node = next(n for n in data["nodes"] if n["id"] == f"{_KAI_NS}Person")
    assert node["type"] == "class"


def test_build_graph_external_individual_type():
    from ster.viz import build_graph

    t = _taxonomy_with_external()
    data = build_graph(t)
    node = next(n for n in data["nodes"] if n["id"] == f"{_FOAF_NS}Bob")
    assert node["type"] == "external-individual"


def test_build_graph_external_class_label_has_prefix():
    from ster.viz import build_graph

    t = _taxonomy_with_external()
    data = build_graph(t)
    node = next(n for n in data["nodes"] if n["id"] == f"{_FOAF_NS}Person")
    assert "foaf" in node["label"] or "foaf" in node["fullLabel"]
