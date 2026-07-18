"""The paradigm-agnostic integrated tree (``ster.tui.data.integrated_tree``).

One builder must produce the right forest for all four real-world shapes — a
pure ontology, a pure taxonomy, a disjoint mix, and a punned mix — with no
"mode" flag. These tests pin the tree *structure* (parent/children/roots) for
each case, especially the one-way SKOS→OWL bridge under a pun.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ster import store
from ster.tui import data
from ster.tui.data import ONTOLOGY_ROOT

E = "https://ex.org/"

_HEADER = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <https://ex.org/> .
"""

# 1) full ontology — pure OWL/RDFS: a class chain + a typed individual, no SKOS.
PURE_ONTOLOGY = (
    _HEADER
    + """
ex:Animal a owl:Class .
ex:Mammal a owl:Class ; rdfs:subClassOf ex:Animal .
ex:Dog    a owl:Class ; rdfs:subClassOf ex:Mammal .
ex:rex    a owl:NamedIndividual, ex:Dog .
"""
)

# 2) full taxonomy — pure SKOS: a scheme with a broader/narrower concept chain.
PURE_TAXONOMY = (
    _HEADER
    + """
ex:scheme a skos:ConceptScheme ; skos:hasTopConcept ex:Animal .
ex:Animal a skos:Concept ; skos:topConceptOf ex:scheme ; skos:inScheme ex:scheme .
ex:Mammal a skos:Concept ; skos:broader ex:Animal ; skos:inScheme ex:scheme .
"""
)

# 3) disjoint — a SKOS scheme and an OWL class tree that share no URIs (no puns).
DISJOINT = (
    _HEADER
    + """
ex:scheme  a skos:ConceptScheme ; skos:hasTopConcept ex:Animal .
ex:Animal  a skos:Concept ; skos:topConceptOf ex:scheme ; skos:inScheme ex:scheme .
ex:Mammal  a skos:Concept ; skos:broader ex:Animal ; skos:inScheme ex:scheme .
ex:Vehicle a owl:Class .
ex:Car     a owl:Class ; rdfs:subClassOf ex:Vehicle .
"""
)

# 4) mixed — a pun (Animal is Concept *and* Class) with a narrower concept
# (Mammal via broader) AND a pure subclass (Dog via subClassOf) that must bridge
# up under it; Cat is an unrelated top class → the owl:Thing root.
MIXED = (
    _HEADER
    + """
ex:scheme a skos:ConceptScheme ; skos:hasTopConcept ex:Animal .
ex:Animal a skos:Concept, owl:Class ; skos:topConceptOf ex:scheme ; skos:inScheme ex:scheme .
ex:Mammal a skos:Concept ; skos:broader ex:Animal ; skos:inScheme ex:scheme .
ex:Dog    a owl:Class ; rdfs:subClassOf ex:Animal .
ex:Cat    a owl:Class .
ex:rex    a owl:NamedIndividual, ex:Dog .
"""
)


def _tax(tmp_path: Path, ttl: str):
    src = tmp_path / "o.ttl"
    src.write_text(ttl, encoding="utf-8")
    return store.load(src)


def test_pure_ontology_is_a_single_owl_thing_tree(tmp_path):
    tree = data.integrated_tree(_tax(tmp_path, PURE_ONTOLOGY))
    assert tree.roots == [ONTOLOGY_ROOT]  # no scheme at all
    assert tree.children[ONTOLOGY_ROOT] == [E + "Animal"]
    assert tree.children[E + "Animal"] == [E + "Mammal"]
    assert tree.children[E + "Mammal"] == [E + "Dog"]
    assert tree.children[E + "Dog"] == [E + "rex"]  # individual nests under its class
    assert tree.parent[E + "Animal"] == ONTOLOGY_ROOT


def test_pure_taxonomy_is_a_single_scheme_tree(tmp_path):
    tree = data.integrated_tree(_tax(tmp_path, PURE_TAXONOMY))
    assert tree.roots == [E + "scheme"]  # no owl:Thing root — nothing needs it
    assert ONTOLOGY_ROOT not in tree.children
    assert tree.children[E + "scheme"] == [E + "Animal"]
    assert tree.children[E + "Animal"] == [E + "Mammal"]


def test_disjoint_yields_two_separate_roots_with_no_cross_edges(tmp_path):
    tree = data.integrated_tree(_tax(tmp_path, DISJOINT))
    assert tree.roots == [E + "scheme", ONTOLOGY_ROOT]  # schemes first, then owl:Thing
    # SKOS branch
    assert tree.children[E + "scheme"] == [E + "Animal"]
    assert tree.parent[E + "Mammal"] == E + "Animal"
    # OWL branch — entirely separate
    assert tree.children[ONTOLOGY_ROOT] == [E + "Vehicle"]
    assert tree.parent[E + "Car"] == E + "Vehicle"
    # no bridge: the OWL classes never touch the SKOS spine
    assert E + "Vehicle" not in tree.children[E + "scheme"]


def test_mixed_pun_bridges_owl_subclass_up_under_the_concept(tmp_path):
    tree = data.integrated_tree(_tax(tmp_path, MIXED))
    assert tree.roots == [E + "scheme", ONTOLOGY_ROOT]
    # the pun sits on the SKOS spine (topConceptOf), not under owl:Thing
    assert tree.parent[E + "Animal"] == E + "scheme"
    # THE BRIDGE: the narrower concept *and* the pure subclass both hang under
    # the pun, label-sorted (Dog < Mammal).
    assert tree.children[E + "Animal"] == [E + "Dog", E + "Mammal"]
    assert tree.parent[E + "Dog"] == E + "Animal"  # subClassOf → broader spine
    assert tree.children[E + "Dog"] == [E + "rex"]
    # a non-pun top class stays on the owl:Thing root
    assert tree.children[ONTOLOGY_ROOT] == [E + "Cat"]


# ── edge cases: nothing is ever dropped ────────────────────────────────────────

# A lone SKOS concept with no scheme in the file (store leaves top_concept_of
# unset) → surfaced on the owl:Thing root, never dropped. A property (which the
# tree does not place) resolves there too instead of crashing.
EDGE = (
    _HEADER
    + """
ex:Orphan a skos:Concept .
ex:prop   a owl:ObjectProperty .
"""
)


def test_scheme_less_concept_lands_on_the_ontology_root(tmp_path):
    tax = _tax(tmp_path, EDGE)
    assert not tax.schemes  # no scheme at all → nothing adopts the concept
    assert tax.concepts[E + "Orphan"].top_concept_of is None
    assert data.effective_parent(tax, E + "Orphan") == ONTOLOGY_ROOT


def test_non_placed_uri_falls_back_to_the_ontology_root(tmp_path):
    """A property (or any node the tree does not place) resolves to the root, never crashes."""
    tax = _tax(tmp_path, EDGE)
    assert data.effective_parent(tax, E + "prop") == ONTOLOGY_ROOT


@pytest.mark.parametrize("ttl", [PURE_ONTOLOGY, PURE_TAXONOMY, DISJOINT, MIXED])
def test_every_node_is_reachable_from_a_root(tmp_path, ttl):
    """No node is ever dropped: walking down from the roots reaches every placed node."""
    tree = data.integrated_tree(_tax(tmp_path, ttl))
    seen: set[str] = set()
    stack = list(tree.roots)
    while stack:
        node = stack.pop()
        seen.add(node)
        stack.extend(tree.children.get(node, []))
    assert set(tree.parent) <= seen  # every placed node was reached
