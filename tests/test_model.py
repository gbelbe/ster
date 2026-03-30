"""Tests for the pure domain model."""

from ster.model import Concept, ConceptScheme, Label, LabelType, Taxonomy

BASE = "https://example.org/test/"


def test_concept_pref_label_by_lang():
    c = Concept(
        uri=BASE + "Foo",
        labels=[
            Label(lang="en", value="Foo"),
            Label(lang="fr", value="Truc"),
        ],
    )
    assert c.pref_label("en") == "Foo"
    assert c.pref_label("fr") == "Truc"


def test_concept_pref_label_fallback_to_first():
    c = Concept(
        uri=BASE + "Foo",
        labels=[Label(lang="fr", value="Truc")],
    )
    assert c.pref_label("en") == "Truc"


def test_concept_pref_label_fallback_to_local_name():
    c = Concept(uri=BASE + "MyLocal")
    assert c.pref_label() == "MyLocal"


def test_concept_local_name_fragment():
    c = Concept(uri="https://example.org/ns#MyThing")
    assert c.local_name == "MyThing"


def test_concept_local_name_path():
    c = Concept(uri="https://example.org/ns/MyThing")
    assert c.local_name == "MyThing"


def test_concept_pref_labels_dict():
    c = Concept(
        uri=BASE + "X",
        labels=[
            Label(lang="en", value="English"),
            Label(lang="fr", value="French"),
            Label(lang="en", value="Alt-en", type=LabelType.ALT),
        ],
    )
    pref = c.pref_labels()
    assert pref == {"en": "English", "fr": "French"}


def test_concept_alt_labels_dict():
    c = Concept(
        uri=BASE + "X",
        labels=[
            Label(lang="en", value="Main", type=LabelType.PREF),
            Label(lang="en", value="Alt1", type=LabelType.ALT),
            Label(lang="en", value="Alt2", type=LabelType.ALT),
            Label(lang="fr", value="AltFr", type=LabelType.ALT),
        ],
    )
    alts = c.alt_labels()
    assert alts["en"] == ["Alt1", "Alt2"]
    assert alts["fr"] == ["AltFr"]


def test_taxonomy_resolve_by_handle():
    t = Taxonomy(
        concepts={BASE + "Foo": Concept(uri=BASE + "Foo")},
        handle_index={"FOO": BASE + "Foo"},
    )
    assert t.resolve("FOO") == BASE + "Foo"
    assert t.resolve("foo") == BASE + "Foo"  # case-insensitive


def test_taxonomy_resolve_by_uri():
    t = Taxonomy(
        concepts={BASE + "Foo": Concept(uri=BASE + "Foo")},
        handle_index={"FOO": BASE + "Foo"},
    )
    assert t.resolve(BASE + "Foo") == BASE + "Foo"


def test_taxonomy_resolve_missing():
    t = Taxonomy()
    assert t.resolve("NOPE") is None


def test_taxonomy_uri_to_handle():
    t = Taxonomy(
        concepts={BASE + "Foo": Concept(uri=BASE + "Foo")},
        handle_index={"FOO": BASE + "Foo"},
    )
    assert t.uri_to_handle(BASE + "Foo") == "FOO"
    assert t.uri_to_handle(BASE + "Missing") is None


def test_concept_scheme_title_fallback():
    s = ConceptScheme(uri=BASE + "MyScheme")
    assert s.title() == "MyScheme"


def test_concept_scheme_title_by_lang():
    s = ConceptScheme(
        uri=BASE + "S",
        labels=[
            Label(lang="en", value="English Title"),
            Label(lang="fr", value="Titre Français"),
        ],
    )
    assert s.title("en") == "English Title"
    assert s.title("fr") == "Titre Français"
