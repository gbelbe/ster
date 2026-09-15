"""The graph view's default payload: roots only above a threshold.

Same shape as the individual-collapse story in test_graph_collapse.py, one
level up the tree: a large ontology's *classes* (and SKOS *concepts*)
rendered all at once is the "unusable on large ontologies" complaint the
graph editor initiative exists to fix (see
docs/architecture/graph-editor.md). Below CLASS_COLLAPSE_LIMIT nothing
changes — a small ontology is legible whole.
"""

from __future__ import annotations

import rdflib

from ster import store
from ster.model import OWLIndividual
from ster.viz_vowl import (
    CLASS_COLLAPSE_LIMIT,
    build_default_vowl_graph,
    build_vowl_graph,
    collapse_individuals,
    render_vowl_html,
)

NS = "https://example.org/dg#"


def _owl_taxonomy(root_count: int, children_per_root: int, tmp_path):
    """*root_count* root classes, each with *children_per_root* subclasses."""
    ttl = [
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        f"@prefix ex: <{NS}> .",
    ]
    for r in range(root_count):
        ttl.append(f'ex:Root{r} a owl:Class ; rdfs:label "Root{r}"@en .')
        for c in range(children_per_root):
            ttl.append(
                f"ex:Root{r}Child{c} a owl:Class ; "
                f'rdfs:label "Root{r}Child{c}"@en ; rdfs:subClassOf ex:Root{r} .'
            )
    path = tmp_path / "g.ttl"
    path.write_text("\n".join(ttl))
    rdflib.Graph().parse(str(path))  # fail loudly here rather than inside ster
    return store.load(str(path))


def _skos_taxonomy(top_count: int, narrower_per_top: int, tmp_path):
    """*top_count* top concepts, each with *narrower_per_top* narrower concepts."""
    ttl = [
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .",
        f"@prefix ex: <{NS}> .",
        "ex:Scheme a skos:ConceptScheme .",
    ]
    for t in range(top_count):
        ttl.append(
            f"ex:Top{t} a skos:Concept ; skos:inScheme ex:Scheme ; "
            f'skos:topConceptOf ex:Scheme ; skos:prefLabel "Top{t}"@en .'
        )
        for n in range(narrower_per_top):
            ttl.append(
                f"ex:Top{t}Narrower{n} a skos:Concept ; skos:inScheme ex:Scheme ; "
                f'skos:broader ex:Top{t} ; skos:prefLabel "Top{t}Narrower{n}"@en .'
            )
    path = tmp_path / "g.ttl"
    path.write_text("\n".join(ttl))
    rdflib.Graph().parse(str(path))  # fail loudly here rather than inside ster
    return store.load(str(path))


def test_a_small_ontology_is_returned_whole(tmp_path) -> None:
    """Below the threshold, build_default_vowl_graph is build_vowl_graph."""
    taxonomy = _owl_taxonomy(3, 4, tmp_path)  # 15 classes, well under the limit

    default_graph = build_default_vowl_graph(taxonomy)
    full_graph = build_vowl_graph(taxonomy)

    assert len(default_graph["nodes"]) == len(full_graph["nodes"])
    assert {n["id"] for n in default_graph["nodes"]} == {n["id"] for n in full_graph["nodes"]}


def test_a_large_ontology_is_scoped_to_root_classes(tmp_path) -> None:
    root_count = CLASS_COLLAPSE_LIMIT + 10
    taxonomy = _owl_taxonomy(root_count, 3, tmp_path)

    graph = build_default_vowl_graph(taxonomy)

    class_nodes = [n for n in graph["nodes"] if n["type"] == "class"]
    assert len(class_nodes) == root_count
    assert all(n["rootClass"] == 1 for n in class_nodes)


def test_a_large_taxonomy_is_scoped_to_top_concepts(tmp_path) -> None:
    top_count = CLASS_COLLAPSE_LIMIT + 10
    taxonomy = _skos_taxonomy(top_count, 3, tmp_path)

    graph = build_default_vowl_graph(taxonomy)

    concept_nodes = [n for n in graph["nodes"] if n["type"] in ("concept", "topconcept")]
    assert len(concept_nodes) == top_count
    assert all(n["type"] == "topconcept" for n in concept_nodes)
    scheme_nodes = [n for n in graph["nodes"] if n["type"] == "scheme"]
    assert len(scheme_nodes) == 1


def _mixed(owl_roots, owl_children, skos_tops, skos_narrower, tmp_path):
    """One file holding both an OWL ontology and a SKOS scheme."""
    owl = _owl_taxonomy(owl_roots, owl_children, tmp_path / "o")
    skos = _skos_taxonomy(skos_tops, skos_narrower, tmp_path / "s")
    for uri, concept in skos.concepts.items():
        owl.concepts[uri] = concept
    for uri, scheme in skos.schemes.items():
        owl.schemes[uri] = scheme
    return owl


def test_a_big_scheme_does_not_scope_away_a_small_ontology(tmp_path) -> None:
    """The budget is per half, not shared.

    An OWL ontology and a SKOS scheme are drawn in two separate tabs, so neither
    can crowd the other on screen. Summing them meant that opening a large
    taxonomy beside a small metamodel collapsed the metamodel to its root
    classes — hiding an ontology that was perfectly legible and had not grown.
    """
    tmp_path.joinpath("o").mkdir()
    tmp_path.joinpath("s").mkdir()
    taxonomy = _mixed(3, 4, CLASS_COLLAPSE_LIMIT + 10, 3, tmp_path)  # 15 classes, 604 concepts

    graph = build_default_vowl_graph(taxonomy)

    class_nodes = [n for n in graph["nodes"] if n["type"] == "class"]
    assert len(class_nodes) == 15, "every class survives — the classes did not grow"
    assert not all(n.get("rootClass") == 1 for n in class_nodes), "not scoped to roots"


def test_the_big_half_is_still_scoped_in_that_same_graph(tmp_path) -> None:
    """Keeping the small half whole must not un-scope the large one."""
    tmp_path.joinpath("o").mkdir()
    tmp_path.joinpath("s").mkdir()
    top_count = CLASS_COLLAPSE_LIMIT + 10
    taxonomy = _mixed(3, 4, top_count, 3, tmp_path)

    graph = build_default_vowl_graph(taxonomy)

    concept_nodes = [n for n in graph["nodes"] if n["type"] in ("concept", "topconcept")]
    assert len(concept_nodes) == top_count
    assert all(n["type"] == "topconcept" for n in concept_nodes)


def test_the_kept_half_keeps_its_edges(tmp_path) -> None:
    """Root-only scoping drops subclass and property edges with the nodes; the
    half that is kept whole must keep the structure that makes it worth seeing."""
    tmp_path.joinpath("o").mkdir()
    tmp_path.joinpath("s").mkdir()
    taxonomy = _mixed(3, 4, CLASS_COLLAPSE_LIMIT + 10, 3, tmp_path)

    graph = build_default_vowl_graph(taxonomy)

    assert any(e["type"] == "subClassOf" for e in graph["edges"])


def test_the_kept_half_can_still_be_dug_into(tmp_path) -> None:
    """Keeping the class half whole must not strand its individuals.

    A class becomes expandable by carrying an ``individualCount``, and that count
    is computed by ``collapse_individuals`` from the instanceOf edges in the
    graph. Build the class half without individuals and there is nothing to
    count, so every class reports nothing and 22,146 individuals sit behind
    classes that look empty.
    """
    tmp_path.joinpath("o").mkdir()
    tmp_path.joinpath("s").mkdir()
    taxonomy = _mixed(3, 4, CLASS_COLLAPSE_LIMIT + 10, 3, tmp_path)
    root = next(iter(taxonomy.owl_classes))
    for i in range(5):
        uri = f"{NS}ind{i}"
        taxonomy.owl_individuals[uri] = OWLIndividual(uri=uri, types=[root])

    graph = build_default_vowl_graph(taxonomy)

    assert any(e["type"] == "instanceOf" for e in graph["edges"]), "individuals reach the graph"
    collapsed = collapse_individuals(graph, limit=1)
    counts = {n["id"]: n.get("individualCount") for n in collapsed["nodes"]}
    assert counts.get(root) == 5


def test_a_big_ontology_beside_a_small_scheme_scopes_the_other_way(tmp_path) -> None:
    """The rule is symmetric."""
    tmp_path.joinpath("o").mkdir()
    tmp_path.joinpath("s").mkdir()
    root_count = CLASS_COLLAPSE_LIMIT + 10
    taxonomy = _mixed(root_count, 3, 4, 2, tmp_path)

    graph = build_default_vowl_graph(taxonomy)

    class_nodes = [n for n in graph["nodes"] if n["type"] == "class"]
    assert all(n["rootClass"] == 1 for n in class_nodes), "the big half is scoped"
    concept_nodes = [n for n in graph["nodes"] if n["type"] in ("concept", "topconcept")]
    assert any(n["type"] == "concept" for n in concept_nodes), "the small half is whole"


def test_scoping_only_computes_detail_for_kept_roots(tmp_path) -> None:
    """The point of scoping before adding nodes: never pay for what's dropped."""
    root_count = CLASS_COLLAPSE_LIMIT + 10
    taxonomy = _owl_taxonomy(root_count, 3, tmp_path)

    graph = build_default_vowl_graph(taxonomy)

    # root_count roots, none of their 3*root_count children.
    assert len(graph["nodes"]) == root_count


def test_scoped_page_offers_a_show_all_button(tmp_path) -> None:
    taxonomy = _owl_taxonomy(CLASS_COLLAPSE_LIMIT + 10, 3, tmp_path)

    page = render_vowl_html(taxonomy, tmp_path / "g.ttl", api_token="live-token")

    assert "Show all nodes" in page


def test_small_page_does_not_offer_a_show_all_button(tmp_path) -> None:
    taxonomy = _owl_taxonomy(3, 4, tmp_path)

    page = render_vowl_html(taxonomy, tmp_path / "g.ttl", api_token="live-token")

    assert "Show all nodes" not in page


def test_full_true_opts_back_into_the_unscoped_graph(tmp_path) -> None:
    root_count = CLASS_COLLAPSE_LIMIT + 10
    taxonomy = _owl_taxonomy(root_count, 3, tmp_path)

    page = render_vowl_html(taxonomy, tmp_path / "g.ttl", api_token="live-token", full=True)

    assert "Show all nodes" not in page
    assert page.count('"type": "class"') + page.count('"type":"class"') == root_count * 4


def test_offline_export_is_never_scoped(tmp_path) -> None:
    """No click-to-expand endpoint without a server, so it always gets everything."""
    root_count = CLASS_COLLAPSE_LIMIT + 10
    taxonomy = _owl_taxonomy(root_count, 3, tmp_path)

    page = render_vowl_html(taxonomy, tmp_path / "g.ttl", api_token="")

    assert "Show all nodes" not in page
    assert page.count('"type": "class"') + page.count('"type":"class"') == root_count * 4
