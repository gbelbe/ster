"""Right-click context menus adapt to the *node kind* (``edits.menu_kind`` +
``edits.context_actions``). The pivotal case is a pun: it must resolve to the
combined ``"promoted"`` menu (both the SKOS and OWL grow-forks), not the
class-only menu that ``data.kind_of`` — which checks classes first — returns.
"""

from __future__ import annotations

from pathlib import Path

from ster import store
from ster.tui import edits

E = "https://ex.org/"

TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <https://ex.org/> .

ex:scheme a skos:ConceptScheme ; skos:hasTopConcept ex:Animal .
ex:Animal a skos:Concept, owl:Class ; skos:topConceptOf ex:scheme ; skos:inScheme ex:scheme .
ex:Mammal a skos:Concept ; skos:broader ex:Animal ; skos:inScheme ex:scheme .
ex:Vehicle a owl:Class .
ex:rex a owl:NamedIndividual, ex:Vehicle .
ex:hasPart a owl:ObjectProperty .
"""


def _tax(tmp_path: Path):
    src = tmp_path / "o.ttl"
    src.write_text(TTL, encoding="utf-8")
    return store.load(src)


def _actions(tmp_path, uri):
    tax = _tax(tmp_path)
    return [a for _label, a in edits.context_actions(edits.menu_kind(tax, uri))]


def test_menu_kind_resolves_each_node_to_its_rdf_kind(tmp_path):
    tax = _tax(tmp_path)
    assert edits.menu_kind(tax, E + "Animal") == "promoted"  # pun, NOT "class"
    assert edits.menu_kind(tax, E + "Mammal") == "concept"
    assert edits.menu_kind(tax, E + "Vehicle") == "class"
    assert edits.menu_kind(tax, E + "rex") == "individual"
    assert edits.menu_kind(tax, E + "hasPart") == "property"
    assert edits.menu_kind(tax, E + "scheme") == "scheme"


def test_pun_menu_carries_both_the_skos_and_owl_grow_forks(tmp_path):
    """The defining pun behaviour: its menu can grow *both* hierarchies."""
    actions = _actions(tmp_path, E + "Animal")
    assert "new_subclass" in actions  # OWL inheritance fork
    assert "add_narrower" in actions  # SKOS grouping fork
    assert "add_individual" in actions  # it is a class → can hold individuals


def test_pure_class_menu_has_class_actions_and_no_skos_actions(tmp_path):
    actions = _actions(tmp_path, E + "Vehicle")
    assert "new_subclass" in actions
    assert "add_individual" in actions
    assert "add_narrower" not in actions  # a pure class has no SKOS side
    assert "add_related" not in actions


def test_pure_concept_menu_has_skos_actions_and_no_class_actions(tmp_path):
    actions = _actions(tmp_path, E + "Mammal")
    assert "add_narrower" in actions
    assert "add_related" in actions
    assert "new_subclass" not in actions  # a pure concept has no OWL side
    assert "add_individual" not in actions


def test_scheme_and_individual_menus_are_distinct(tmp_path):
    assert "add_top_concept" in _actions(tmp_path, E + "scheme")
    assert "add_ind_type" in _actions(tmp_path, E + "rex")


def test_concept_can_be_promoted_and_a_pun_can_be_demoted(tmp_path):
    """The toggle is offered on the right node: promote on a plain concept, demote on a pun."""
    assert "promote" in _actions(tmp_path, E + "Mammal")  # plain concept → offer promote
    assert "demote" not in _actions(tmp_path, E + "Mammal")
    assert "demote" in _actions(tmp_path, E + "Animal")  # pun → offer demote
    assert "promote" not in _actions(tmp_path, E + "Animal")
