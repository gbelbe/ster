"""Which file a statement in the session graph came from.

ster models one flat graph (no named graphs), so provenance is answered from the
side tables the loader fills while merging read-only context files. Everything
those tables do not claim belongs to the editable file.
"""

from __future__ import annotations

from rdflib import Literal, URIRef
from rdflib.namespace import RDF, SKOS

from ster import store

NS = "https://example.org/p#"
_HEAD = f"@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n@prefix ex: <{NS}> .\n"
_PREF_EN = (URIRef(NS + "Farm"), SKOS.prefLabel, Literal("Farm", lang="en"))
_PREF_FR = (URIRef(NS + "Farm"), SKOS.prefLabel, Literal("Ferme", lang="fr"))


def _write(tmp_path, name: str, body: str):
    path = tmp_path / name
    path.write_text(_HEAD + body, encoding="utf-8")
    return path


def _session(tmp_path, context_body: str | None = None):
    main = _write(tmp_path, "vocab.ttl", 'ex:Farm a skos:Concept ; skos:prefLabel "Farm"@en .\n')
    context = [_write(tmp_path, "labels.ttl", context_body)] if context_body else []
    return main, context, store.load(main, context=context)


def test_a_statement_only_the_main_file_makes_belongs_to_the_main_file(tmp_path) -> None:
    main, _, tax = _session(tmp_path, 'ex:Farm skos:prefLabel "Ferme"@fr .\n')

    assert store.provenance(tax).file_of(_PREF_EN) == main


def test_a_statement_a_context_file_adds_belongs_to_that_file(tmp_path) -> None:
    _, [labels], tax = _session(tmp_path, 'ex:Farm skos:prefLabel "Ferme"@fr .\n')

    assert store.provenance(tax).file_of(_PREF_FR) == labels


def test_an_entity_only_a_context_file_defines_belongs_to_that_file(tmp_path) -> None:
    _, [labels], tax = _session(tmp_path, "ex:Field a skos:Concept .\n")

    assert store.provenance(tax).file_of((URIRef(NS + "Field"), RDF.type, SKOS.Concept)) == labels


def test_unmodelled_context_statements_belong_to_their_file(tmp_path) -> None:
    """A predicate ster does not model lands in the context file's residue."""
    _, [labels], tax = _session(tmp_path, "ex:Farm ex:surveyedBy ex:Team .\n")
    triple = (URIRef(NS + "Farm"), URIRef(NS + "surveyedBy"), URIRef(NS + "Team"))

    assert store.provenance(tax).file_of(triple) == labels


def test_a_statement_both_files_make_belongs_to_the_main_file(tmp_path) -> None:
    """The loader counts a shared statement as the editable file's own; so do we."""
    main, _, tax = _session(tmp_path, 'ex:Farm skos:prefLabel "Farm"@en .\n')

    assert store.provenance(tax).file_of(_PREF_EN) == main


def test_without_context_files_everything_belongs_to_the_main_file(tmp_path) -> None:
    main, _, tax = _session(tmp_path)
    prov = store.provenance(tax)

    assert prov.files == (main,)
    assert prov.file_of(_PREF_EN) == main


def test_files_list_the_main_file_first_then_context_files_in_load_order(tmp_path) -> None:
    main = _write(tmp_path, "vocab.ttl", "ex:Farm a skos:Concept .\n")
    first = _write(tmp_path, "b.ttl", 'ex:Farm skos:altLabel "B"@en .\n')
    second = _write(tmp_path, "a.ttl", "ex:Field a skos:Concept .\n")
    tax = store.load(main, context=[first, second])

    assert store.provenance(tax).files == (main, first, second)
