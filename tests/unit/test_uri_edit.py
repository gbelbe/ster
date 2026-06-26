"""Unit tests for the shared URI-fragment helpers (ster.tui.uri_edit)."""

from __future__ import annotations

from ster.model import ConceptScheme, RDFClass, Taxonomy
from ster.tui.uri_edit import mint_base, split_namespace

# ── split_namespace ───────────────────────────────────────────────────────────


def test_split_namespace_hash() -> None:
    assert split_namespace("https://ex.org/onto#Wheel") == ("https://ex.org/onto#", "Wheel")


def test_split_namespace_slash() -> None:
    assert split_namespace("https://ex.org/onto/Wheel") == ("https://ex.org/onto/", "Wheel")


def test_split_namespace_uses_the_last_separator() -> None:
    # A path with both kinds splits at the rightmost one (the local-name boundary).
    assert split_namespace("https://ex.org/path/onto#Wheel") == (
        "https://ex.org/path/onto#",
        "Wheel",
    )
    assert split_namespace("https://ex.org/a/b/c") == ("https://ex.org/a/b/", "c")


def test_split_namespace_no_separator() -> None:
    assert split_namespace("Wheel") == ("", "Wheel")


# ── mint_base ─────────────────────────────────────────────────────────────────


def _owl_tax(sep: str) -> Taxonomy:
    t = Taxonomy()
    t.ontology_uri = "https://ex.org/onto"
    t.owl_classes["https://ex.org/onto" + sep + "Seed"] = RDFClass(
        uri="https://ex.org/onto" + sep + "Seed"
    )
    return t


def test_mint_base_owl_uses_ontology_with_detected_hash() -> None:
    assert mint_base(_owl_tax("#"), "create_owl_class", "__overview__") == "https://ex.org/onto#"


def test_mint_base_owl_uses_ontology_with_detected_slash() -> None:
    assert (
        mint_base(_owl_tax("/"), "new_subclass", "https://ex.org/onto/Plant")
        == "https://ex.org/onto/"
    )


def test_mint_base_concept_uses_parent_scheme_base() -> None:
    t = Taxonomy()
    scheme = ConceptScheme(uri="https://ex.org/wind/scheme", base_uri="https://ex.org/wind/")
    t.schemes[scheme.uri] = scheme
    assert mint_base(t, "add_top_concept", scheme.uri) == "https://ex.org/wind/"


def test_mint_base_concept_falls_back_to_taxonomy_base() -> None:
    # add_narrower's parent is a concept (not a scheme) → use the taxonomy base,
    # which prioritises the primary scheme's base.
    t = Taxonomy()
    scheme = ConceptScheme(uri="https://ex.org/wind/scheme", base_uri="https://ex.org/wind/")
    t.schemes[scheme.uri] = scheme
    assert mint_base(t, "add_narrower", "https://ex.org/wind/Parent") == "https://ex.org/wind/"
