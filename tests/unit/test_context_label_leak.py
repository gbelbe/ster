"""A context file's rdfs:label on a SKOS entity must not leak into the editable file.

Root cause of the regression these lock in: merging promotes a context file's
residue onto the entity it describes, and ``rdfs:label`` lands in the entity's
``labels`` list. On a class, property or individual that list is written back
as ``rdfs:label``. On a Concept or ConceptScheme it holds *SKOS* labels and is
written back as ``skos:prefLabel`` — so the statement changed meaning, and the
writer, which strips context statements from the editable file by exact match
on the recorded ``rdfs:label`` triple, never matched the ``skos:prefLabel`` it
emitted. Saving wrote the context file's label into the user's own file.

The fix leaves an ``rdfs:label`` on a SKOS entity as context residue: still
read, still queryable, still ``rdfs:label``, never written to the editable file.
"""

from __future__ import annotations

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDFS, SKOS

from ster import store

NS = "https://example.org/leak#"
_HEAD = (
    "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
    "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
    "@prefix owl:  <http://www.w3.org/2002/07/owl#> .\n"
    f"@prefix ex:   <{NS}> .\n"
)
FARM = URIRef(NS + "Farm")


def _session(tmp_path, main_body: str, context_body: str):
    main = tmp_path / "vocab.ttl"
    main.write_text(_HEAD + main_body, encoding="utf-8")
    labels = tmp_path / "labels.ttl"
    labels.write_text(_HEAD + context_body, encoding="utf-8")
    return main, store.load(main, context=[labels])


def _saved(main, tax) -> Graph:
    store.save(tax, main)
    return Graph().parse(main, format="turtle")


def test_a_context_rdfs_label_on_a_concept_is_not_saved_into_the_main_file_regression(
    tmp_path,
) -> None:
    main, tax = _session(tmp_path, "ex:Farm a skos:Concept .\n", 'ex:Farm rdfs:label "Farm" .\n')

    saved = _saved(main, tax)

    assert (FARM, SKOS.prefLabel, Literal("Farm")) not in saved
    assert (FARM, RDFS.label, Literal("Farm")) not in saved


def test_a_context_rdfs_label_on_a_concept_scheme_is_not_saved_into_the_main_file(
    tmp_path,
) -> None:
    scheme = URIRef(NS + "Scheme")
    main, tax = _session(
        tmp_path, "ex:Scheme a skos:ConceptScheme .\n", 'ex:Scheme rdfs:label "Scheme"@en .\n'
    )

    saved = _saved(main, tax)

    assert not list(saved.triples((scheme, None, Literal("Scheme", lang="en"))))


def test_a_context_rdfs_label_on_a_concept_is_still_read_as_rdfs_label(tmp_path) -> None:
    """Not converted into a SKOS label: the session sees exactly what the file says."""
    _, tax = _session(tmp_path, "ex:Farm a skos:Concept .\n", 'ex:Farm rdfs:label "Farm"@fr .\n')

    graph = store.full_graph_rdflib(tax)

    assert (FARM, RDFS.label, Literal("Farm", lang="fr")) in graph
    assert (FARM, SKOS.prefLabel, Literal("Farm", lang="fr")) not in graph


def test_the_main_file_s_own_concept_labels_survive_the_save(tmp_path) -> None:
    main, tax = _session(
        tmp_path,
        'ex:Farm a skos:Concept ; skos:prefLabel "Farm"@en .\n',
        'ex:Farm rdfs:label "Ferme"@fr .\n',
    )

    saved = _saved(main, tax)

    assert (FARM, SKOS.prefLabel, Literal("Farm", lang="en")) in saved
    assert (FARM, SKOS.prefLabel, Literal("Ferme", lang="fr")) not in saved


def test_a_context_rdfs_label_on_a_class_still_attaches_and_is_not_saved(tmp_path) -> None:
    """Unchanged: a class writes labels back as rdfs:label, so promotion is faithful."""
    shop = URIRef(NS + "Shop")
    main, tax = _session(tmp_path, "ex:Shop a owl:Class .\n", 'ex:Shop rdfs:label "Shop"@en .\n')

    assert [label.value for label in tax.owl_classes[NS + "Shop"].labels] == ["Shop"]
    assert (shop, RDFS.label, Literal("Shop", lang="en")) not in _saved(main, tax)


def test_a_concept_class_pun_takes_the_context_label_on_its_class(tmp_path) -> None:
    """A punned URI has a home that writes rdfs:label; the label goes there."""
    main, tax = _session(
        tmp_path, "ex:Farm a skos:Concept, owl:Class .\n", 'ex:Farm rdfs:label "Farm"@en .\n'
    )

    assert [label.value for label in tax.owl_classes[NS + "Farm"].labels] == ["Farm"]
    assert tax.concepts[NS + "Farm"].labels == []
    assert not list(_saved(main, tax).triples((FARM, None, Literal("Farm", lang="en"))))
