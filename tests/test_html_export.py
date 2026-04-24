"""Tests for html_export — pyLODE integration, language detection, switcher injection."""

from __future__ import annotations

import json
import pathlib
from unittest.mock import MagicMock, patch

import pytest

from ster.html_export import (
    _available_languages,
    _bc,
    _entity_kind,
    _esc,
    _full_graph_json,
    _inject_switcher,
    _lang_switcher_html,
    _md_to_html,
    _neighborhood_json,
    _patch_missing_pyproject,
    _render_description,
    _render_ext_links,
    _render_hero_img,
    _render_videos,
    _sbox,
    _slug,
    _tcard,
    _video_embed_info,
    detect_profile,
    generate_html,
)
from ster.model import (
    Concept,
    ConceptScheme,
    Definition,
    Label,
    OWLIndividual,
    RDFClass,
    Taxonomy,
)

BASE = "https://example.org/test/"


# ── _patch_missing_pyproject ──────────────────────────────────────────────────


def test_patch_restores_original():
    original = pathlib.Path.open
    with _patch_missing_pyproject():
        patched = pathlib.Path.open
        assert patched is not original
    assert pathlib.Path.open is original


def test_patch_returns_stub_for_missing_pyproject(tmp_path):
    missing = tmp_path / "pyproject.toml"
    assert not missing.exists()
    with _patch_missing_pyproject():
        f = missing.open("rb")
        content = f.read()
    assert b"pylode" in content


def test_patch_text_mode_for_missing_pyproject(tmp_path):
    missing = tmp_path / "pyproject.toml"
    with _patch_missing_pyproject():
        f = missing.open("r")
        content = f.read()
    assert "pylode" in content


def test_patch_leaves_existing_files_alone(tmp_path):
    real = tmp_path / "real.txt"
    real.write_text("hello")
    with _patch_missing_pyproject():
        assert real.read_text() == "hello"


def test_patch_leaves_existing_pyproject_alone(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "myapp"\n')
    with _patch_missing_pyproject():
        content = pyproject.read_text()
    assert "myapp" in content


# ── _available_languages ──────────────────────────────────────────────────────


def _make_multilang_taxonomy() -> Taxonomy:
    t = Taxonomy()
    scheme = ConceptScheme(
        uri=BASE + "Scheme",
        labels=[
            Label(lang="en", value="Test"),
            Label(lang="fr", value="Essai"),
        ],
        descriptions=[Definition(lang="de", value="Beschreibung")],
    )
    concept = Concept(
        uri=BASE + "Top",
        labels=[
            Label(lang="en", value="Top"),
            Label(lang="es", value="Arriba"),
        ],
        definitions=[Definition(lang="fr", value="La racine")],
    )
    t.schemes[scheme.uri] = scheme
    t.concepts[concept.uri] = concept
    return t


def test_available_languages_collects_all():
    t = _make_multilang_taxonomy()
    langs = _available_languages(t)
    assert "en" in langs
    assert "fr" in langs
    assert "de" in langs
    assert "es" in langs


def test_available_languages_sorted():
    t = _make_multilang_taxonomy()
    langs = _available_languages(t)
    assert langs == sorted(langs)


def test_available_languages_no_duplicates():
    t = _make_multilang_taxonomy()
    langs = _available_languages(t)
    assert len(langs) == len(set(langs))


def test_available_languages_empty_taxonomy():
    langs = _available_languages(Taxonomy())
    assert langs == []


# ── _lang_switcher_html ───────────────────────────────────────────────────────


def test_switcher_marks_current():
    html = _lang_switcher_html("test", "en", ["en", "fr"])
    assert "ster-current" in html
    assert "EN" in html


def test_switcher_links_other_languages():
    html = _lang_switcher_html("test", "en", ["en", "fr", "de"])
    assert 'href="test_fr.html"' in html
    assert 'href="test_de.html"' in html


def test_switcher_single_language():
    html = _lang_switcher_html("doc", "en", ["en"])
    assert "ster-current" in html
    assert "href=" not in html


def test_switcher_contains_css():
    html = _lang_switcher_html("doc", "en", ["en"])
    assert "#ster-lang-bar" in html


# ── _inject_switcher ──────────────────────────────────────────────────────────


def test_inject_after_body_tag():
    html = "<html><body><p>Hello</p></body></html>"
    result = _inject_switcher(html, "doc", "en", ["en", "fr"])
    body_pos = result.lower().find("<body>")
    bar_pos = result.find("ster-lang-bar")
    assert body_pos < bar_pos


def test_inject_fallback_no_body_tag():
    html = "<p>No body tag</p>"
    result = _inject_switcher(html, "doc", "en", ["en"])
    assert "ster-lang-bar" in result
    assert result.startswith("#ster-lang-bar") or "ster-lang-bar" in result[:200]


def test_inject_case_insensitive_body():
    html = "<HTML><BODY><p>content</p></BODY></HTML>"
    result = _inject_switcher(html, "doc", "en", ["en"])
    assert "ster-lang-bar" in result


# ── generate_html ─────────────────────────────────────────────────────────────


@pytest.fixture
def ttl_file(tmp_path):
    content = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix t:    <https://example.org/test/> .

t:Scheme a skos:ConceptScheme ;
    skos:prefLabel "Test"@en , "Essai"@fr ;
    skos:hasTopConcept t:Top .

t:Top a skos:Concept ;
    skos:inScheme t:Scheme ;
    skos:prefLabel "Top"@en , "Haut"@fr .
"""
    p = tmp_path / "tax.ttl"
    p.write_text(content, encoding="utf-8")
    return p


def _make_mock_vocpub(html_content: str = "<html><body>content</body></html>"):
    mock_cls = MagicMock()
    mock_instance = MagicMock()
    mock_instance.make_html.return_value = html_content
    mock_cls.return_value = mock_instance
    return mock_cls


def test_generate_html_single_language(tmp_path, ttl_file):
    output_dir = tmp_path / "out"
    mock_vp_cls = _make_mock_vocpub("<html><body>vocab</body></html>")

    with _patch_missing_pyproject():
        try:
            import pylode  # noqa: F401

            pylode_available = True
        except ImportError:
            pylode_available = False

    if not pylode_available:
        pytest.skip("pylode not installed")

    with patch("pylode.VocPub", mock_vp_cls):
        created = generate_html(ttl_file, output_dir, languages=["en"])

    assert len(created) == 1
    assert created[0].name == "tax.html"
    assert created[0].exists()


def test_generate_html_multiple_languages(tmp_path, ttl_file):
    with _patch_missing_pyproject():
        try:
            import pylode  # noqa: F401

            pylode_available = True
        except ImportError:
            pylode_available = False

    if not pylode_available:
        pytest.skip("pylode not installed")

    output_dir = tmp_path / "out"
    mock_vp_cls = _make_mock_vocpub("<html><body>vocab</body></html>")

    with patch("pylode.VocPub", mock_vp_cls):
        created = generate_html(ttl_file, output_dir, languages=["en", "fr"])

    assert len(created) == 2
    names = {p.name for p in created}
    assert "tax_en.html" in names
    assert "tax_fr.html" in names


def test_generate_html_creates_output_dir(tmp_path, ttl_file):
    with _patch_missing_pyproject():
        try:
            import pylode  # noqa: F401

            pylode_available = True
        except ImportError:
            pylode_available = False

    if not pylode_available:
        pytest.skip("pylode not installed")

    output_dir = tmp_path / "deep" / "nested" / "out"
    assert not output_dir.exists()
    mock_vp_cls = _make_mock_vocpub("<html><body>content</body></html>")

    with patch("pylode.VocPub", mock_vp_cls):
        generate_html(ttl_file, output_dir, languages=["en"])

    assert output_dir.exists()


def test_generate_html_without_pylode_raises(tmp_path, ttl_file, monkeypatch):
    """generate_html raises RuntimeError when pylode cannot be imported."""
    import sys

    # Setting sys.modules["pylode"] = None makes any `import pylode` raise ImportError
    saved = sys.modules.get("pylode", ...)
    sys.modules["pylode"] = None  # type: ignore[assignment]
    try:
        with pytest.raises(RuntimeError, match="pyLODE"):
            generate_html(ttl_file, tmp_path / "out", languages=["en"])
    finally:
        if saved is ...:
            del sys.modules["pylode"]
        else:
            sys.modules["pylode"] = saved


def test_generate_html_vocpub_type_error_fallback(tmp_path, ttl_file):
    """Older VocPub without default_language triggers TypeError → fallback call."""
    with _patch_missing_pyproject():
        try:
            import pylode  # noqa: F401

            pylode_available = True
        except ImportError:
            pylode_available = False

    if not pylode_available:
        pytest.skip("pylode not installed")

    def vp_side_effect(**kwargs):
        if "default_language" in kwargs:
            raise TypeError("unexpected keyword argument")
        inst = MagicMock()
        inst.make_html.return_value = "<html><body>fallback</body></html>"
        return inst

    mock_vp_cls = MagicMock(side_effect=vp_side_effect)

    with patch("pylode.VocPub", mock_vp_cls):
        created = generate_html(ttl_file, tmp_path / "out", languages=["en"])

    assert len(created) == 1


def test_generate_html_defaults_to_en_when_no_labels(tmp_path):
    """If taxonomy has no labels with languages, fallback to ['en']."""
    with _patch_missing_pyproject():
        try:
            import pylode  # noqa: F401

            pylode_available = True
        except ImportError:
            pylode_available = False

    if not pylode_available:
        pytest.skip("pylode not installed")

    bare_ttl = tmp_path / "bare.ttl"
    bare_ttl.write_text(
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
        "@prefix t: <https://x.org/> .\n"
        "t:S a skos:ConceptScheme .\n",
        encoding="utf-8",
    )
    mock_vp_cls = _make_mock_vocpub("<html><body>x</body></html>")
    output_dir = tmp_path / "out2"

    with patch("pylode.VocPub", mock_vp_cls):
        created = generate_html(bare_ttl, output_dir)

    # Should produce exactly one file with the "en" fallback
    assert len(created) == 1


# ── detect_profile ────────────────────────────────────────────────────────────


def test_detect_profile_vocpub(tmp_path):
    ttl = tmp_path / "skos.ttl"
    ttl.write_text(
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
        "@prefix t: <https://ex.org/> .\n"
        "t:S a skos:ConceptScheme .\n"
    )
    assert detect_profile(ttl) == "vocpub"


def test_detect_profile_ontpub(tmp_path):
    ttl = tmp_path / "owl.ttl"
    ttl.write_text(
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix t: <https://ex.org/> .\n"
        "t:O a owl:Ontology .\n"
    )
    assert detect_profile(ttl) == "ontpub"


def test_detect_profile_both(tmp_path):
    ttl = tmp_path / "both.ttl"
    ttl.write_text(
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
        "@prefix t: <https://ex.org/> .\n"
        "t:O a owl:Ontology .\n"
        "t:S a skos:ConceptScheme .\n"
    )
    assert detect_profile(ttl) == "both"


# ── _video_embed_info ─────────────────────────────────────────────────────────


def test_video_embed_info_youtube_standard():
    result = _video_embed_info("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert result is not None
    embed, thumb, platform = result
    assert "dQw4w9WgXcQ" in embed
    assert "img.youtube.com" in thumb
    assert platform == "youtube"


def test_video_embed_info_youtube_short_url():
    result = _video_embed_info("https://youtu.be/dQw4w9WgXcQ")
    assert result is not None
    _, _, platform = result
    assert platform == "youtube"


def test_video_embed_info_youtube_shorts():
    result = _video_embed_info("https://www.youtube.com/shorts/dQw4w9WgXcQ")
    assert result is not None
    _, _, platform = result
    assert platform == "youtube"


def test_video_embed_info_vimeo():
    result = _video_embed_info("https://vimeo.com/123456789")
    assert result is not None
    embed, thumb, platform = result
    assert "player.vimeo.com" in embed
    assert thumb == ""
    assert platform == "vimeo"


def test_video_embed_info_unknown_returns_none():
    assert _video_embed_info("https://example.com/video.mp4") is None


# ── _md_to_html ───────────────────────────────────────────────────────────────


def test_md_to_html_with_plain_text():
    result = _md_to_html("Hello world")
    assert "Hello world" in result


def test_md_to_html_fallback_no_markdown(monkeypatch):
    import sys

    saved = sys.modules.get("markdown", ...)
    sys.modules["markdown"] = None  # type: ignore[assignment]
    try:
        result = _md_to_html("<b>bold</b> & special")
        # Fallback escapes HTML
        assert "&lt;" in result or "bold" in result
    finally:
        if saved is ...:
            sys.modules.pop("markdown", None)
        else:
            sys.modules["markdown"] = saved


# ── _entity_kind ──────────────────────────────────────────────────────────────

_OWL_BASE = "https://example.org/owl/"


def _make_owl_taxonomy() -> Taxonomy:
    t = Taxonomy()
    t.concepts[_OWL_BASE + "Top"] = Concept(
        uri=_OWL_BASE + "Top", top_concept_of=_OWL_BASE + "Scheme"
    )
    t.concepts[_OWL_BASE + "Child"] = Concept(uri=_OWL_BASE + "Child")
    t.schemes[_OWL_BASE + "Scheme"] = ConceptScheme(uri=_OWL_BASE + "Scheme")
    t.owl_classes[_OWL_BASE + "AClass"] = RDFClass(uri=_OWL_BASE + "AClass")
    t.owl_individuals[_OWL_BASE + "AnInd"] = OWLIndividual(uri=_OWL_BASE + "AnInd")
    return t


def test_entity_kind_topconcept():
    assert _entity_kind(_make_owl_taxonomy(), _OWL_BASE + "Top") == "topconcept"


def test_entity_kind_concept():
    assert _entity_kind(_make_owl_taxonomy(), _OWL_BASE + "Child") == "concept"


def test_entity_kind_class():
    assert _entity_kind(_make_owl_taxonomy(), _OWL_BASE + "AClass") == "class"


def test_entity_kind_individual():
    assert _entity_kind(_make_owl_taxonomy(), _OWL_BASE + "AnInd") == "individual"


def test_entity_kind_scheme():
    assert _entity_kind(_make_owl_taxonomy(), _OWL_BASE + "Scheme") == "scheme"


def test_entity_kind_unknown_defaults_class():
    assert _entity_kind(Taxonomy(), "https://unknown.org/X") == "class"


# ── _full_graph_json ──────────────────────────────────────────────────────────


def test_full_graph_json_nodes_present():
    t = _make_owl_taxonomy()
    data = json.loads(_full_graph_json(t, {}, lambda uri: uri.rsplit("/", 1)[-1]))
    node_ids = {n["id"] for n in data["nodes"]}
    assert _OWL_BASE + "Top" in node_ids
    assert _OWL_BASE + "AClass" in node_ids
    assert _OWL_BASE + "AnInd" in node_ids


def test_full_graph_json_broader_link():
    t = Taxonomy()
    t.concepts["A"] = Concept(uri="A", broader=["B"])
    t.concepts["B"] = Concept(uri="B")
    data = json.loads(_full_graph_json(t, {}, lambda uri: uri))
    assert any(lk["source"] == "A" and lk["target"] == "B" for lk in data["links"])


def test_full_graph_json_class_hierarchy_link():
    t = Taxonomy()
    t.owl_classes["Child"] = RDFClass(uri="Child", sub_class_of=["Parent"])
    t.owl_classes["Parent"] = RDFClass(uri="Parent")
    data = json.loads(_full_graph_json(t, {}, lambda uri: uri))
    assert any(lk["source"] == "Child" and lk["target"] == "Parent" for lk in data["links"])


def test_full_graph_json_individual_type_link():
    t = Taxonomy()
    t.owl_classes["MyClass"] = RDFClass(uri="MyClass")
    t.owl_individuals["Inst"] = OWLIndividual(uri="Inst", types=["MyClass"])
    data = json.loads(_full_graph_json(t, {}, lambda uri: uri))
    assert any(lk["source"] == "Inst" and lk["target"] == "MyClass" for lk in data["links"])


def test_full_graph_json_root_class_flag():
    t = Taxonomy()
    t.owl_classes["Root"] = RDFClass(uri="Root")
    t.owl_classes["Child"] = RDFClass(uri="Child", sub_class_of=["Root"])
    data = json.loads(_full_graph_json(t, {}, lambda uri: uri))
    root = next(n for n in data["nodes"] if n["id"] == "Root")
    child = next(n for n in data["nodes"] if n["id"] == "Child")
    assert root["rootClass"] is True
    assert child["rootClass"] is False


def test_full_graph_json_image_from_concept():
    t = Taxonomy()
    t.concepts["C"] = Concept(uri="C", schema_images=["http://img.example.org/pic.png"])
    data = json.loads(_full_graph_json(t, {}, lambda uri: uri))
    node = next(n for n in data["nodes"] if n["id"] == "C")
    assert node["img"] == "http://img.example.org/pic.png"


def test_full_graph_json_image_from_class():
    t = Taxonomy()
    t.owl_classes["Cls"] = RDFClass(uri="Cls", schema_images=["http://img.example.org/cls.png"])
    data = json.loads(_full_graph_json(t, {}, lambda uri: uri))
    node = next(n for n in data["nodes"] if n["id"] == "Cls")
    assert node["img"] == "http://img.example.org/cls.png"


def test_full_graph_json_image_from_individual():
    t = Taxonomy()
    t.owl_individuals["Ind"] = OWLIndividual(
        uri="Ind", schema_images=["http://img.example.org/ind.png"]
    )
    data = json.loads(_full_graph_json(t, {}, lambda uri: uri))
    node = next(n for n in data["nodes"] if n["id"] == "Ind")
    assert node["img"] == "http://img.example.org/ind.png"


def test_full_graph_json_slug_map():
    t = Taxonomy()
    t.concepts["A"] = Concept(uri="A")
    data = json.loads(_full_graph_json(t, {"A": "a.html"}, lambda uri: uri))
    node = next(n for n in data["nodes"] if n["id"] == "A")
    assert node["href"] == "a.html"


def test_full_graph_json_missing_slug_defaults_hash():
    t = Taxonomy()
    t.concepts["A"] = Concept(uri="A")
    data = json.loads(_full_graph_json(t, {}, lambda uri: uri))
    node = next(n for n in data["nodes"] if n["id"] == "A")
    assert node["href"] == "#"


# ── _neighborhood_json ────────────────────────────────────────────────────────


def test_neighborhood_json_concept_neighbours():
    t = Taxonomy()
    t.concepts["A"] = Concept(uri="A", broader=["B"], narrower=["C"], related=["D"])
    for uri in ("B", "C", "D"):
        t.concepts[uri] = Concept(uri=uri)
    data = json.loads(_neighborhood_json(t, "A", {}, lambda uri: uri))
    node_ids = {n["id"] for n in data["nodes"]}
    assert node_ids == {"A", "B", "C", "D"}
    focus = next(n for n in data["nodes"] if n["id"] == "A")
    assert focus["focus"] is True


def test_neighborhood_json_class_subclasses_and_individuals():
    t = Taxonomy()
    t.owl_classes["Parent"] = RDFClass(uri="Parent")
    t.owl_classes["Child"] = RDFClass(uri="Child", sub_class_of=["Parent"])
    t.owl_individuals["Inst"] = OWLIndividual(uri="Inst", types=["Parent"])
    data = json.loads(_neighborhood_json(t, "Parent", {}, lambda uri: uri))
    node_ids = {n["id"] for n in data["nodes"]}
    assert "Child" in node_ids
    assert "Inst" in node_ids


def test_neighborhood_json_class_sub_class_of():
    t = Taxonomy()
    t.owl_classes["Child"] = RDFClass(uri="Child", sub_class_of=["Parent"])
    t.owl_classes["Parent"] = RDFClass(uri="Parent")
    data = json.loads(_neighborhood_json(t, "Child", {}, lambda uri: uri))
    node_ids = {n["id"] for n in data["nodes"]}
    assert "Parent" in node_ids


def test_neighborhood_json_individual():
    t = Taxonomy()
    t.owl_classes["MyClass"] = RDFClass(uri="MyClass")
    t.owl_individuals["Inst"] = OWLIndividual(
        uri="Inst", types=["MyClass"], property_values=[("prop", "OtherInst")]
    )
    t.owl_individuals["OtherInst"] = OWLIndividual(uri="OtherInst")
    data = json.loads(_neighborhood_json(t, "Inst", {}, lambda uri: uri))
    node_ids = {n["id"] for n in data["nodes"]}
    assert "MyClass" in node_ids
    assert "OtherInst" in node_ids


def test_neighborhood_json_unknown_uri():
    t = Taxonomy()
    data = json.loads(_neighborhood_json(t, "https://unknown.org/X", {}, lambda uri: uri))
    assert len(data["nodes"]) == 1
    assert data["nodes"][0]["focus"] is True


# ── _slug ─────────────────────────────────────────────────────────────────────


def test_slug_hash_separator():
    assert _slug("https://example.org/ns#MyClass") == "MyClass"


def test_slug_slash_separator():
    assert _slug("https://example.org/ns/MyClass") == "MyClass"


def test_slug_no_separator():
    assert _slug("PlainName") == "PlainName"


def test_slug_sanitizes_special_chars():
    result = _slug("https://example.org/My Class!")
    assert " " not in result
    assert "!" not in result


# ── _esc ──────────────────────────────────────────────────────────────────────


def test_esc_angle_brackets():
    assert "&lt;" in _esc("<script>")
    assert "&gt;" in _esc("<script>")


def test_esc_ampersand():
    assert "&amp;" in _esc("A & B")


# ── _render_hero_img ──────────────────────────────────────────────────────────


def test_render_hero_img_empty():
    concept = Concept(uri="X")
    assert _render_hero_img(concept) == ""


def test_render_hero_img_with_image():
    concept = Concept(uri="X", schema_images=["https://img.example.org/pic.jpg"])
    result = _render_hero_img(concept)
    assert 'class="entity-img"' in result
    assert "pic.jpg" in result


# ── _render_description ───────────────────────────────────────────────────────


def test_render_description_matching_lang():
    concept = Concept(
        uri="X",
        definitions=[
            Definition(lang="en", value="English def"),
            Definition(lang="fr", value="French def"),
        ],
    )
    result = _render_description(concept, "en")
    assert "English def" in result
    assert 'class="desc"' in result


def test_render_description_fallback_to_first_def():
    concept = Concept(uri="X", definitions=[Definition(lang="fr", value="French def")])
    result = _render_description(concept, "en")
    assert "French def" in result


def test_render_description_comments_lang_match():
    cls = RDFClass(
        uri="X",
        comments=[
            Definition(lang="de", value="German comment"),
            Definition(lang="en", value="English comment"),
        ],
    )
    result = _render_description(cls, "en")
    assert "English comment" in result


def test_render_description_comments_fallback_to_first():
    cls = RDFClass(uri="X", comments=[Definition(lang="de", value="Only German")])
    result = _render_description(cls, "en")
    assert "Only German" in result


def test_render_description_empty_entity():
    assert _render_description(Concept(uri="X"), "en") == ""


# ── _render_videos ────────────────────────────────────────────────────────────


def test_render_videos_empty():
    assert _render_videos(Concept(uri="X")) == ""


def test_render_videos_youtube():
    concept = Concept(uri="X", schema_videos=["https://www.youtube.com/watch?v=dQw4w9WgXcQ"])
    result = _render_videos(concept)
    assert "video-facade" in result
    assert "youtube.com/embed" in result


def test_render_videos_vimeo_no_thumb():
    concept = Concept(uri="X", schema_videos=["https://vimeo.com/123456789"])
    result = _render_videos(concept)
    assert "video-facade" in result
    assert "background:#111" in result


def test_render_videos_unknown_url_skipped():
    concept = Concept(uri="X", schema_videos=["https://example.com/video.mp4"])
    assert _render_videos(concept) == ""


def test_render_videos_includes_script():
    concept = Concept(uri="X", schema_videos=["https://www.youtube.com/watch?v=dQw4w9WgXcQ"])
    result = _render_videos(concept)
    assert "<script>" in result


# ── _render_ext_links ─────────────────────────────────────────────────────────


def test_render_ext_links_empty():
    assert _render_ext_links(Concept(uri="X")) == ""


def test_render_ext_links_short_url():
    concept = Concept(uri="X", schema_urls=["https://example.org"])
    result = _render_ext_links(concept)
    assert "link-card" in result
    assert "https://example.org" in result


def test_render_ext_links_long_url_truncated():
    long_url = "https://example.org/" + "x" * 60
    concept = Concept(uri="X", schema_urls=[long_url])
    result = _render_ext_links(concept)
    assert "…" in result


def test_render_ext_links_multiple():
    concept = Concept(uri="X", schema_urls=["https://a.org", "https://b.org"])
    result = _render_ext_links(concept)
    assert result.count("link-card") == 2


# ── _tcard ────────────────────────────────────────────────────────────────────


def test_tcard_without_image():
    result = _tcard("My Label", "Class", "page.html")
    assert "My Label" in result
    assert "Class" in result
    assert 'href="page.html"' in result
    assert "<img" not in result


def test_tcard_with_image():
    result = _tcard("My Label", "Class", "page.html", "img.jpg")
    assert "<img" in result
    assert "img.jpg" in result


def test_tcard_escapes_html():
    result = _tcard("<b>Label</b>", "Class", "page.html")
    assert "&lt;b&gt;" in result


# ── _sbox ─────────────────────────────────────────────────────────────────────


def test_sbox_empty_returns_empty():
    assert _sbox("Title", []) == ""


def test_sbox_with_items():
    result = _sbox("Related", [("Item A", "a.html"), ("Item B", "b.html")])
    assert "Related" in result
    assert "Item A" in result
    assert "a.html" in result
    assert 'class="sbox"' in result


def test_sbox_escapes_html():
    result = _sbox("<Title>", [("<Item>", "x.html")])
    assert "&lt;Title&gt;" in result
    assert "&lt;Item&gt;" in result


# ── _bc ───────────────────────────────────────────────────────────────────────


def test_bc_single_no_href():
    result = _bc([("Current", None)])
    assert 'class="cur"' in result
    assert "Current" in result


def test_bc_multiple_with_hrefs():
    result = _bc([("Home", "index.html"), ("Current", None)])
    assert 'href="index.html"' in result
    assert "sep" in result
    assert 'class="cur"' in result


def test_bc_all_with_hrefs():
    result = _bc([("A", "a.html"), ("B", "b.html")])
    assert 'href="a.html"' in result
    assert 'href="b.html"' in result
    assert "sep" in result


def test_bc_empty():
    assert _bc([]) == ""
