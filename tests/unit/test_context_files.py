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


# ── saving: statements merged onto an entity the editable file defines ────────
#
# Root cause of the regressions below: _merge_context has two paths that attach a
# context file's statements to an entity the editable file already defines.
# _promote_residue records each promotion in `context_statements`, so the writer
# strips it again; _merge_statements_onto recorded nothing, so the writer could
# not tell those statements apart from the editable file's own and wrote them out.


def test_context_statements_on_a_shared_entity_do_not_leak_on_save_regression(files):
    """A context file's label must not be written into the file the user edits.

    The whole point of a read-only context is that the two files stay separate.
    Merging the statement so it is queryable is right; emitting it into the other
    file is not.
    """
    primary, context = files
    context.write_text(
        CONTEXT
        + 'ex:Tent a skos:Concept ; skos:prefLabel "Tent from context"@en ;\n'
        + '    skos:definition "Portable shelter."@en .\n',
        encoding="utf-8",
    )
    tax = store.load(primary, context=[context])

    store.save(tax, primary)

    written = primary.read_text(encoding="utf-8")
    assert "Tent from context" not in written, "the context file's label leaked"
    assert "Portable shelter." not in written, "the context file's definition leaked"
    assert "Tent" in written, "the editable file lost its own label"


def test_a_leaked_label_would_make_the_editable_file_invalid_skos_regression(files):
    """The leak does not only move data — it authors a SKOS violation.

    Two prefLabels in one language on one concept (SKO001) in a file that had
    exactly one before ster opened it.
    """
    primary, context = files
    context.write_text(
        CONTEXT + 'ex:Tent a skos:Concept ; skos:prefLabel "Tent from context"@en .\n',
        encoding="utf-8",
    )
    tax = store.load(primary, context=[context])

    store.save(tax, primary)

    reloaded = store.load(primary)
    english_prefs = [
        label
        for label in reloaded.concepts[NS + "Tent"].labels
        if label.lang == "en" and label.type.value == "pref"
    ]
    assert len(english_prefs) == 1, f"one prefLabel@en expected, got {english_prefs}"


def test_context_statements_on_a_shared_entity_stay_visible_in_the_model(files):
    """Stripping them from the *written file* must not hide them from the model.

    Guards the competitor-set behaviour: a context file saying something new
    about a known entity is the ordinary case, and the merged graph is what makes
    it queryable.
    """
    primary, context = files
    context.write_text(
        CONTEXT + 'ex:Tent a skos:Concept ; skos:definition "Portable shelter."@en .\n',
        encoding="utf-8",
    )

    tax = store.load(primary, context=[context])

    definitions = [d.value for d in tax.concepts[NS + "Tent"].definitions]
    assert "Portable shelter." in definitions


def test_a_statement_both_files_assert_survives_the_save(files):
    """Only what the context file *adds* is stripped.

    A triple the editable file asserts in its own right must survive, even when
    the context file happens to assert it too — over-stripping silently deletes
    the user's data.
    """
    primary, context = files
    context.write_text(
        CONTEXT + "ex:Tent a skos:Concept ; skos:inScheme ex:Scheme .\n",
        encoding="utf-8",
    )
    tax = store.load(primary, context=[context])

    store.save(tax, primary)

    written = primary.read_text(encoding="utf-8")
    assert "inScheme" in written, "a statement the editable file owns was stripped"
    assert "Tent" in written


def test_two_context_files_both_stay_out_of_the_editable_file(files, tmp_path):
    primary, context = files
    second = tmp_path / "second.ttl"
    second.write_text(
        f"""\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <{NS}> .
ex:Tent a skos:Concept ; skos:definition "From the second file."@en .
""",
        encoding="utf-8",
    )
    context.write_text(
        CONTEXT + 'ex:Tent a skos:Concept ; skos:prefLabel "Tent from context"@en .\n',
        encoding="utf-8",
    )
    tax = store.load(primary, context=[context, second])

    store.save(tax, primary)

    written = primary.read_text(encoding="utf-8")
    assert "Tent from context" not in written
    assert "From the second file." not in written


def test_a_shared_entity_round_trips_without_growing(files):
    """Load → save → load → save must reach a fixed point, not accrete statements."""
    primary, context = files
    context.write_text(
        CONTEXT + 'ex:Tent a skos:Concept ; skos:prefLabel "Tent from context"@en .\n',
        encoding="utf-8",
    )

    store.save(store.load(primary, context=[context]), primary)
    once = primary.read_text(encoding="utf-8")
    store.save(store.load(primary, context=[context]), primary)
    twice = primary.read_text(encoding="utf-8")

    assert once == twice


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
