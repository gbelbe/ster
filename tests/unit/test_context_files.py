"""Unit tests for read-only context files.

One file is editable; the others are loaded so the connected graph is visible.
The load has to merge them, and the save has to un-merge them again — that
asymmetry is where this feature can lose data, so it carries most of the tests.
"""

from __future__ import annotations

import pytest

from ster import store
from ster.model import Taxonomy

NS = "https://example.org/t#"

PRIMARY = f"""\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix ex: <{NS}> .
ex:Scheme a skos:ConceptScheme .
ex:Tent a skos:Concept ; skos:prefLabel "Tent"@en ; skos:inScheme ex:Scheme .
ex:Shelter a owl:Class .
"""

CONTEXT = f"""\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix ex: <{NS}> .
ex:Alps a skos:Concept ; skos:prefLabel "Alps"@en .
ex:Place a owl:Class .
ex:Matterhorn a owl:NamedIndividual, ex:Place .
"""


@pytest.fixture
def files(tmp_path):
    primary = tmp_path / "primary.ttl"
    primary.write_text(PRIMARY, encoding="utf-8")
    context = tmp_path / "context.ttl"
    context.write_text(CONTEXT, encoding="utf-8")
    return primary, context


# ── loading ───────────────────────────────────────────────────────────────────


def test_context_entities_join_the_taxonomy(files):
    primary, context = files

    tax = store.load(primary, context=[context])

    assert NS + "Tent" in tax.concepts
    assert NS + "Alps" in tax.concepts, "the whole point is seeing the connected graph"


def test_context_entities_of_every_kind_are_merged(files):
    primary, context = files

    tax = store.load(primary, context=[context])

    assert NS + "Place" in tax.owl_classes
    assert NS + "Matterhorn" in tax.owl_individuals


def test_context_entities_are_marked_with_their_source(files):
    primary, context = files

    tax = store.load(primary, context=[context])

    assert tax.context_source[NS + "Alps"] == context
    assert tax.context_source[NS + "Place"] == context


def test_primary_entities_are_not_marked(files):
    primary, context = files

    tax = store.load(primary, context=[context])

    assert NS + "Tent" not in tax.context_source
    assert NS + "Shelter" not in tax.context_source


def test_loading_without_context_marks_nothing(files):
    primary, _context = files

    assert store.load(primary).context_source == {}


def test_file_path_stays_the_editable_file(files):
    primary, context = files

    assert store.load(primary, context=[context]).file_path == primary


def test_a_uri_in_both_files_keeps_the_editable_one(files):
    """Editable wins: the copy you can change is the one you must be shown."""
    primary, context = files
    context.write_text(
        CONTEXT + 'ex:Tent a skos:Concept ; skos:prefLabel "Tent from context"@en .\n',
        encoding="utf-8",
    )

    tax = store.load(primary, context=[context])

    assert tax.concepts[NS + "Tent"].pref_label("en") == "Tent"
    assert NS + "Tent" not in tax.context_source, "still editable"


# ── editability ───────────────────────────────────────────────────────────────


def test_is_editable_distinguishes_the_two(files):
    primary, context = files

    tax = store.load(primary, context=[context])

    assert store.is_editable(tax, NS + "Tent")
    assert not store.is_editable(tax, NS + "Alps")


def test_an_unknown_uri_counts_as_editable(files):
    """A URI ster has never seen belongs to whatever you are about to write."""
    primary, context = files

    assert store.is_editable(store.load(primary, context=[context]), NS + "Nope")


# ── saving: the part that can lose data ───────────────────────────────────────


def test_saving_does_not_absorb_context_entities(files):
    primary, context = files
    tax = store.load(primary, context=[context])

    store.save(tax, primary)

    written = primary.read_text(encoding="utf-8")
    assert "Tent" in written
    for absorbed in ("Alps", "Place", "Matterhorn"):
        assert absorbed not in written, f"{absorbed} came from the context file"


def test_saving_leaves_the_context_file_byte_identical(files):
    primary, context = files
    before = context.read_bytes()
    tax = store.load(primary, context=[context])

    store.save(tax, primary)

    assert context.read_bytes() == before


def test_a_saved_file_reloads_to_the_same_editable_entities(files):
    """Round-trip: nothing editable is lost by excluding the context."""
    primary, context = files
    tax = store.load(primary, context=[context])
    editable = {u for u in tax.concepts if u not in tax.context_source}

    store.save(tax, primary)

    assert set(store.load(primary).concepts) == editable


def test_saving_a_taxonomy_with_no_context_is_unchanged(files):
    """The single-file path must not shift behaviour."""
    primary, _context = files
    tax = store.load(primary)

    store.save(tax, primary)

    assert set(store.load(primary).concepts) == set(tax.concepts)


def test_taxonomy_to_graph_omits_context_entities(files):
    primary, context = files
    tax = store.load(primary, context=[context])

    graph = store.taxonomy_to_graph(tax)

    subjects = {str(s) for s in graph.subjects()}
    assert NS + "Tent" in subjects
    assert NS + "Alps" not in subjects


def test_context_source_defaults_to_empty_on_a_bare_taxonomy():
    assert Taxonomy().context_source == {}


def test_a_cross_file_link_is_readable_from_the_context_side(tmp_path):
    """The child states its own broader, which is what the graph draws edges from.

    The reciprocal narrower is deliberately *not* synthesised on the editable
    concept: saving would then write it into the user's file, referencing an
    entity that vanishes when the file is opened alone.
    """
    primary = tmp_path / "primary.ttl"
    primary.write_text(PRIMARY, encoding="utf-8")
    context = tmp_path / "context.ttl"
    context.write_text(
        f"@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
        f"@prefix ex: <{NS}> .\n"
        f'ex:Bivvy a skos:Concept ; skos:prefLabel "Bivvy"@en ; skos:broader ex:Tent .\n',
        encoding="utf-8",
    )

    tax = store.load(primary, context=[context])

    assert NS + "Tent" in tax.concepts[NS + "Bivvy"].broader
    assert NS + "Bivvy" not in tax.concepts[NS + "Tent"].narrower


def test_a_cross_file_link_never_reaches_the_editable_file(tmp_path):
    """The editable file must not gain references to entities it cannot see."""
    primary = tmp_path / "primary.ttl"
    primary.write_text(PRIMARY, encoding="utf-8")
    context = tmp_path / "context.ttl"
    context.write_text(
        f"@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
        f"@prefix ex: <{NS}> .\n"
        f'ex:Bivvy a skos:Concept ; skos:prefLabel "Bivvy"@en ; skos:broader ex:Tent .\n',
        encoding="utf-8",
    )
    tax = store.load(primary, context=[context])

    store.save(tax, primary)

    assert "Bivvy" not in primary.read_text(encoding="utf-8")
