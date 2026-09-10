"""Two files, overlapping URIs: what is visible, and where an edit lands.

The scenario is the one an ontology split by *information type* produces — not
"these entities here, those there", but the same entity described from two
files. A vocabulary file carries labels and definitions; a data file carries
types and relations; both talk about ``ex:alpha``.

Deliberately tiny. Each file is a handful of triples so the whole module runs in
about a second, and a failure points at one statement rather than a haystack.

What these tests pin down, in order of how settled it is:

  * statements from both files are visible on the merged entity — object
    properties today, literals not yet (marked xfail below)
  * writing one file never moves the other file's statements into it, and never
    touches the other file
  * an entity a context file *defines* is still refused a write, because
    routing an edit to its home file is not built yet (also xfail)

The xfails are strict: when routing lands they fail loudly rather than sit
green and forgotten.
"""

from __future__ import annotations

import pytest
import rdflib
from fastapi.testclient import TestClient

from ster import store
from ster.api import SSEBroadcaster, create_app

E = "https://example.org/#"
TOKEN = "t"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

# ── the two files ────────────────────────────────────────────────────────────
# Same URIs, disjoint statements. ex:alpha is typed and related in data.ttl and
# described in vocab.ttl; ex:Brushes exists only in vocab.ttl.

DATA = """
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <https://example.org/#> .
ex:O a owl:Ontology ; rdfs:label "Data"@en .
ex:Shop  a owl:Class ; rdfs:label "Shop"@en .
ex:Paint a owl:Class ; rdfs:label "Paint"@en .
ex:sells a owl:ObjectProperty .
ex:alpha a owl:NamedIndividual, ex:Shop ; rdfs:label "Alpha"@en ; ex:sells ex:Paint .
"""

# Deliberately covers each shape a context statement can take: a label and a
# comment on entities the data file defines, a plain literal with no special
# meaning, an object property, a class declared in both files, and a subject
# nothing declares anywhere.
VOCAB = """
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <https://example.org/#> .
ex:V a owl:Ontology ; rdfs:label "Vocabulary"@en .
ex:Shop  rdfs:comment "A retail outlet"@en ; rdfs:label "Boutique"@fr .
ex:alpha rdfs:comment "The first shop"@en ; ex:sells ex:Brushes ; ex:code "A-1" .
ex:Brushes a owl:Class ; rdfs:label "Brushes"@en .
ex:Paint a owl:Class ; rdfs:subClassOf ex:Coating .
ex:ghost ex:mentions ex:nothing .
"""


@pytest.fixture
def files(tmp_path):
    data, vocab = tmp_path / "data.ttl", tmp_path / "vocab.ttl"
    data.write_text(DATA, encoding="utf-8")
    vocab.write_text(VOCAB, encoding="utf-8")
    return data, vocab


@pytest.fixture
def loaded(files):
    data, vocab = files
    return store.load(data, context=[vocab]), data, vocab


@pytest.fixture
def client(loaded):
    tax, data, vocab = loaded
    app = create_app(tax, TOKEN, SSEBroadcaster(), lambda t: None, file_path=data, context=[vocab])
    return TestClient(app)


def _graph(path) -> rdflib.Graph:
    g = rdflib.Graph()
    g.parse(path)
    return g


def _objects(path, subject, predicate) -> set[str]:
    return {
        str(o)
        for o in _graph(path).objects(rdflib.URIRef(E + subject), rdflib.URIRef(E + predicate))
    }


# ── 1. what the merge makes visible ──────────────────────────────────────────


def test_an_object_property_from_each_file_is_visible(loaded):
    """The whole point: one entity, statements from two files."""
    tax, _data, _vocab = loaded

    sells = {o.rsplit("#", 1)[-1] for p, o in tax.owl_individuals[E + "alpha"].property_values}

    assert sells == {"Paint", "Brushes"}


def test_an_entity_only_the_context_defines_is_present(loaded):
    tax, _data, vocab = loaded

    assert E + "Brushes" in tax.owl_classes
    assert tax.context_source[E + "Brushes"] == vocab


def test_the_context_statement_is_attributed_to_its_file(loaded):
    """Attribution is what lets the writer put it back where it came from."""
    tax, _data, vocab = loaded

    promoted = {tuple(str(t) for t in triple) for triple in tax.context_statements.get(vocab, [])}

    assert (E + "alpha", E + "sells", E + "Brushes") in promoted


def test_a_comment_from_the_vocabulary_file_is_visible(loaded):
    """The 'split the vocabulary out' case: labels and definitions live in one
    file, types and relations in another, and both describe the same entity."""
    tax, _data, _vocab = loaded

    assert [c.value for c in tax.owl_individuals[E + "alpha"].comments] == ["The first shop"]


# ── 2. writing one file leaves the other alone ───────────────────────────────


def test_editing_a_main_entity_writes_only_the_main_file(client, files):
    data, vocab = files
    before = vocab.read_text(encoding="utf-8")

    r = client.post(
        "/api/entity-label",
        json={"uri": E + "alpha", "lang": "en", "value": "Alpha Renamed"},
        headers=AUTH,
    )

    assert r.status_code == 200
    assert "Alpha Renamed" in data.read_text(encoding="utf-8")
    assert vocab.read_text(encoding="utf-8") == before


def test_the_context_statement_does_not_migrate_into_the_main_file(client, files):
    """alpha is defined in data.ttl, but `sells ex:Brushes` came from vocab.ttl.
    Saving data.ttl must not absorb it — that would dissolve the split."""
    data, _vocab = files

    client.post(
        "/api/entity-label",
        json={"uri": E + "alpha", "lang": "en", "value": "Alpha Renamed"},
        headers=AUTH,
    )

    assert _objects(data, "alpha", "sells") == {E + "Paint"}


def test_the_main_file_keeps_its_own_statement(client, files):
    """The mirror of the test above: excluding the other file's statements must
    not take the editable file's own with them."""
    data, _vocab = files

    client.post(
        "/api/entity-label",
        json={"uri": E + "alpha", "lang": "en", "value": "Alpha Renamed"},
        headers=AUTH,
    )

    assert E + "Paint" in _objects(data, "alpha", "sells")


def test_an_edit_does_not_pull_the_context_only_entity_in(client, files):
    """ex:Brushes belongs to vocab.ttl and must stay there."""
    data, _vocab = files

    client.post(
        "/api/entity-label",
        json={"uri": E + "alpha", "lang": "en", "value": "Alpha Renamed"},
        headers=AUTH,
    )

    assert (rdflib.URIRef(E + "Brushes"), None, None) not in _graph(data)


# ── 3. routing an edit to the file that owns it ──────────────────────────────


def test_a_context_owned_entity_is_refused_for_now(client):
    """Current, deliberate behaviour: no write reaches a file this session did
    not open. The test below is what should replace it."""
    r = client.post(
        "/api/entity-label",
        json={"uri": E + "Brushes", "lang": "en", "value": "Paint Brushes"},
        headers=AUTH,
    )

    assert r.status_code == 409


@pytest.mark.xfail(strict=True, reason="edit routing to the owning file is not built yet")
def test_editing_a_context_owned_entity_writes_to_its_own_file(client, files):
    data, vocab = files

    r = client.post(
        "/api/entity-label",
        json={"uri": E + "Brushes", "lang": "en", "value": "Paint Brushes"},
        headers=AUTH,
    )

    assert r.status_code == 200
    assert "Paint Brushes" in vocab.read_text(encoding="utf-8")
    assert "Paint Brushes" not in data.read_text(encoding="utf-8")


@pytest.mark.xfail(strict=True, reason="removing a promoted statement must write its own file")
def test_removing_a_context_statement_writes_the_context_file(client, files):
    """`alpha sells ex:Brushes` is a vocab.ttl statement about a data.ttl entity.
    Removing it must edit vocab.ttl, not data.ttl."""
    data, vocab = files

    r = client.post(
        "/api/relation/remove",
        json={"ind_uri": E + "alpha", "prop_uri": E + "sells", "target_uri": E + "Brushes"},
        headers=AUTH,
    )

    assert r.status_code == 200
    assert _objects(vocab, "alpha", "sells") == set()
    assert _objects(data, "alpha", "sells") == {E + "Paint"}


# ── 4. changing a statement the context file supplied ────────────────────────
#
# Attribution is recorded at load time against the exact term that was read.
# That is enough to keep an *unchanged* statement in its own file, and not
# enough the moment its value changes: the recorded triple is no longer in the
# model, so the writer finds nothing to exclude and the new value lands in the
# editable file instead. Ownership needs to be held per (subject, predicate),
# not per term — and saving has to be able to write the owning file.


@pytest.mark.xfail(strict=True, reason="editing a promoted label must rewrite its own file")
def test_renaming_a_label_the_vocabulary_owns_does_not_fork_it(client, files):
    """The bad outcome is not a misplaced triple, it is two of them: the new
    label in data.ttl and the old one still in vocab.ttl, so the entity ends up
    with two different English labels depending on which file you read."""
    data, vocab = files

    client.post(
        "/api/entity-label",
        json={"uri": E + "Brushes", "lang": "en", "value": "Paint Brushes"},
        headers=AUTH,
    )

    assert _objects(data, "Brushes", "label") == set()
    assert "Paint Brushes" in {v.split('"')[0] for v in _objects(vocab, "Brushes", "label")}


@pytest.mark.xfail(strict=True, reason="a new translation belongs beside the labels it joins")
def test_a_new_german_label_joins_the_others_in_the_vocabulary_file(loaded, files):
    """Adding a translation is the ordinary reason to open a vocabulary file.
    It must land beside the English one, not in the file holding the structure."""
    from ster.model import Label

    tax, _data, _vocab = loaded
    data, vocab = files

    tax.owl_classes[E + "Brushes"].labels.append(Label(lang="de", value="Pinsel"))
    store.save(tax, data)

    assert "Pinsel" not in data.read_text(encoding="utf-8")
    assert "Pinsel" in vocab.read_text(encoding="utf-8")


# ── 5. every shape a context statement can take ─────────────────────────────
#
# The merge has to place four kinds of statement and decline a fifth. Each is
# a distinct branch, and the one that declines is the one that matters most:
# a triple with nothing to attach to has to stay residue rather than vanish.


def test_a_label_from_the_context_file_lands_on_the_entity(loaded):
    """rdfs:label on an entity the *data* file defines — the vocabulary split."""
    tax, _data, _vocab = loaded

    langs = {lbl.lang: lbl.value for lbl in tax.owl_classes[E + "Shop"].labels}

    assert langs["en"] == "Shop"  # from data.ttl
    assert langs["fr"] == "Boutique"  # from vocab.ttl


def test_a_plain_literal_becomes_a_literal_value(loaded):
    """Not every literal is a label or a comment; the rest still have a home."""
    tax, _data, _vocab = loaded

    codes = [v for p, v, _lang in tax.owl_individuals[E + "alpha"].literal_values if "code" in p]

    assert codes == ["A-1"]


def test_a_class_declared_in_both_files_keeps_both_statements(loaded):
    """ex:Paint is a class in each file — the entity is not replaced, its lists
    are merged, and a plain-string list must deduplicate as cleanly as a
    dataclass one."""
    tax, _data, _vocab = loaded

    assert E + "Coating" in tax.owl_classes[E + "Paint"].sub_class_of


def test_a_statement_about_nothing_stays_residue(loaded):
    """ex:ghost is declared nowhere. There is no entity to attach it to, so it
    must be carried through untouched rather than dropped — the alternative is
    losing a triple because the model had no shelf for it."""
    tax, _data, vocab = loaded

    residue = [tuple(str(t) for t in tr) for tr in tax.context_residue.get(vocab, [])]

    assert (E + "ghost", E + "mentions", E + "nothing") in residue


def test_the_unattachable_triple_is_not_also_promoted(loaded):
    """It stays in exactly one place: residue, not both."""
    tax, _data, vocab = loaded

    promoted = [tuple(str(t) for t in tr) for tr in tax.context_statements.get(vocab, [])]

    assert (E + "ghost", E + "mentions", E + "nothing") not in promoted


@pytest.mark.xfail(
    strict=True, reason="writing a context file absorbs the editable file's statements"
)
def test_writing_the_context_file_keeps_only_its_own_statements(loaded, files):
    """The mirror of the exclusion rule, and it does not hold yet.

    Writing data.ttl correctly drops vocab.ttl's statements — that is the fix
    this module's earlier tests pin down. Writing vocab.ttl should drop
    data.ttl's by the same logic, and does not: the writer knows which
    statements belong to a *context* file and has no matching notion of which
    belong to the editable one, so `alpha sells ex:Paint` follows the model in.

    Harmless today because nothing writes a context file — routing an edit to
    its owning file is the xfail above. It stops being harmless the moment that
    lands, so it is recorded here rather than discovered then.
    """
    tax, _data, vocab = loaded

    store.save(tax, vocab)

    assert _objects(vocab, "alpha", "sells") == {E + "Brushes"}
