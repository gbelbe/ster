"""Tests for handle generation."""
from ster.handles import derive_candidate, extract_local_name, handle_for_uri, assign_handles
from ster.model import Concept, ConceptScheme, Label, Taxonomy

BASE = "https://example.org/test/"


# ── extract_local_name ────────────────────────────────────────────────────────

def test_extract_local_name_fragment():
    assert extract_local_name("https://example.org/ns#BoatChar") == "BoatChar"


def test_extract_local_name_path():
    assert extract_local_name("https://example.org/ns/BoatChar") == "BoatChar"


def test_extract_local_name_trailing_slash():
    assert extract_local_name("https://example.org/ns/BoatChar/") == "BoatChar"


def test_extract_local_name_bare():
    assert extract_local_name("BoatChar") == "BoatChar"


# ── derive_candidate ─────────────────────────────────────────────────────────

def test_derive_candidate_pascal_case():
    assert derive_candidate("BoatCharacteristic") == "BC"


def test_derive_candidate_three_words():
    assert derive_candidate("RudderCompensationType") == "RCT"


def test_derive_candidate_single_word():
    result = derive_candidate("Concept")
    assert result == "CON"


def test_derive_candidate_single_short():
    result = derive_candidate("BC")
    assert result == "BC"


def test_derive_candidate_all_caps():
    result = derive_candidate("HTTP")
    assert len(result) >= 1


# ── handle_for_uri ────────────────────────────────────────────────────────────

def test_handle_for_uri_unique():
    used: set[str] = set()
    h = handle_for_uri(BASE + "BoatCharacteristic", used)
    assert h == "BC"


def test_handle_for_uri_collision():
    used = {"BC"}
    h = handle_for_uri(BASE + "BoatCharacteristic", used)
    assert h == "BC2"


def test_handle_for_uri_multiple_collisions():
    used = {"BC", "BC2", "BC3"}
    h = handle_for_uri(BASE + "BoatCharacteristic", used)
    assert h == "BC4"


# ── assign_handles ────────────────────────────────────────────────────────────

def test_assign_handles_unique():
    t = Taxonomy(
        schemes={BASE + "Scheme": ConceptScheme(uri=BASE + "Scheme")},
        concepts={
            BASE + "BoatCharacteristic": Concept(uri=BASE + "BoatCharacteristic"),
            BASE + "BackstayPresence": Concept(uri=BASE + "BackstayPresence"),
        },
    )
    assign_handles(t)
    handles = list(t.handle_index.keys())
    assert len(handles) == len(set(handles)), "Handles must be unique"
    assert len(handles) == 3  # 1 scheme + 2 concepts


def test_assign_handles_deterministic():
    """Same taxonomy → same handles on repeated calls."""
    t = Taxonomy(
        concepts={
            BASE + "Alpha": Concept(uri=BASE + "Alpha"),
            BASE + "BetaGamma": Concept(uri=BASE + "BetaGamma"),
        },
    )
    assign_handles(t)
    first = dict(t.handle_index)
    assign_handles(t)
    second = dict(t.handle_index)
    assert first == second


def test_assign_handles_scheme_and_concept_no_collision():
    """A scheme and a concept with the same acronym must get distinct handles."""
    t = Taxonomy(
        schemes={BASE + "BetaCharacteristic": ConceptScheme(uri=BASE + "BetaCharacteristic")},
        concepts={BASE + "BoatConcept": Concept(uri=BASE + "BoatConcept")},
    )
    assign_handles(t)
    values = list(t.handle_index.values())
    assert len(values) == len(set(values))
