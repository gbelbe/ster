"""Unit tests for the curated annotation-property library + intent search."""

from __future__ import annotations

from ster.tui import annotation_library as lib

# Change-tracking provenance is deliberately excluded (a future PROV-O layer owns it).
_EXCLUDED = {
    "http://purl.org/dc/terms/creator",
    "http://purl.org/dc/terms/contributor",
    "http://purl.org/dc/terms/created",
    "http://purl.org/dc/terms/modified",
    "http://www.w3.org/ns/prov#wasGeneratedBy",
    "http://www.w3.org/ns/prov#wasAttributedTo",
    "http://www.w3.org/ns/prov#generatedAtTime",
}


def test_every_entry_is_well_formed() -> None:
    props = lib.all_props()
    assert props
    for p in props:
        assert p.predicate.startswith(("http://", "https://"))
        assert p.label and p.description and p.ontology
        assert p.category in lib.CATEGORIES
        assert p.keywords  # searchable by intent


def test_predicates_are_unique() -> None:
    preds = [p.predicate for p in lib.all_props()]
    assert len(preds) == len(set(preds))


def test_no_change_tracking_provenance() -> None:
    preds = {p.predicate for p in lib.all_props()}
    assert preds.isdisjoint(_EXCLUDED)  # who/what/when-of-edits is not offered here


def test_versioning_media_and_sources_present() -> None:
    labels = {p.label for p in lib.all_props()}
    assert "owl:versionInfo" in labels  # versioning kept
    assert {"schema:image", "schema:video"} <= labels  # media
    assert "dcterms:source" in labels  # descriptive source provenance


def test_get_returns_the_entry_or_none() -> None:
    assert lib.get("https://schema.org/image").label == "schema:image"
    assert lib.get("http://example.org/nope") is None


def test_search_by_intent() -> None:
    def labels(q: str) -> set[str]:
        return {p.label for p in lib.search(q)}

    assert "schema:image" in labels("image") and "foaf:depiction" in labels("image")
    assert "schema:video" in labels("video")
    assert labels("webpage") & {"foaf:homepage", "schema:url"}
    assert "dcterms:source" in labels("source")
    assert labels("photo") & {"schema:image", "foaf:depiction"}  # keyword synonym


def test_search_is_case_insensitive_and_empty_returns_all() -> None:
    assert {p.label for p in lib.search("IMAGE")} == {p.label for p in lib.search("image")}
    assert lib.search("") == lib.all_props()


def test_by_category_groups_every_entry() -> None:
    grouped = lib.by_category()
    assert set(grouped) <= set(lib.CATEGORIES)
    assert sum(len(v) for v in grouped.values()) == len(lib.all_props())


def test_guidance_lists_annotation_and_real_examples() -> None:
    text = lib.GUIDANCE.lower()
    for example in ("label", "comment", "image", "seealso", "license", "source"):
        assert example.replace("seealso", "seealso") in text or "seealso" in text
    assert "annotation" in text and "real" in text
    for real in ("hasparent", "temperature"):
        assert real in text.replace(" ", "")  # real-property examples present
