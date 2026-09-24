"""Whether a predicate is an annotation property — the one part of the retired
"Import External Ontology" module that ster still uses (the TUI asks it before
offering to declare an undeclared predicate).

Answered from the file itself and a list of well-known predicates only. It used
to also read ontologies downloaded by the import screen; with that feature gone,
the answer never depends on a cache or the network.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from rdflib.namespace import DCTERMS, FOAF, RDFS, SKOS

from ster.annotation_properties import WELL_KNOWN_ANNOTATION_PROPS, is_annotation_property
from ster.model import Taxonomy

LOCAL = "https://example.org/kai#"


def _with_property(uri: str, prop_type: str) -> Taxonomy:
    taxonomy = Taxonomy()
    prop = MagicMock()
    prop.prop_type = prop_type
    taxonomy.owl_properties[uri] = prop
    return taxonomy


@pytest.mark.parametrize(
    "predicate",
    [f"{FOAF}depiction", f"{SKOS}scopeNote", f"{RDFS}label", f"{DCTERMS}license"],
)
def test_well_known_annotation_property(predicate):
    assert is_annotation_property(Taxonomy(), predicate)


def test_locally_declared_annotation_property():
    uri = f"{LOCAL}myAnno"
    assert is_annotation_property(_with_property(uri, "AnnotationProperty"), uri)


def test_locally_declared_other_property_is_not_annotation():
    uri = f"{LOCAL}knows"
    assert not is_annotation_property(_with_property(uri, "ObjectProperty"), uri)


def test_unknown_predicate_is_not_annotation():
    assert not is_annotation_property(Taxonomy(), f"{LOCAL}bespoke")


def test_a_bound_namespace_is_no_longer_looked_up_anywhere():
    """Binding a vocabulary's prefix used to send ster to its downloaded copy.
    Now a predicate from it counts only if it is well known or declared here."""
    taxonomy = Taxonomy()
    taxonomy.namespace_bindings["ex"] = "https://vocab.example/"

    assert not is_annotation_property(taxonomy, "https://vocab.example/remark")


def test_annotation_check_never_reads_the_cache_or_network():
    with (
        patch("urllib.request.urlopen", side_effect=AssertionError("network")),
        patch("builtins.open", side_effect=AssertionError("file read")),
    ):
        assert not is_annotation_property(Taxonomy(), f"{LOCAL}bespoke")
        assert is_annotation_property(Taxonomy(), f"{SKOS}prefLabel")


def test_the_well_known_list_keeps_every_vocabulary_it_had():
    """Moving the list must not have dropped any family of predicates."""
    namespaces = {
        uri.rsplit("#", 1)[0] if "#" in uri else uri.rsplit("/", 1)[0]
        for uri in WELL_KNOWN_ANNOTATION_PROPS
    }

    assert len(WELL_KNOWN_ANNOTATION_PROPS) == 56
    assert len(namespaces) == 8
