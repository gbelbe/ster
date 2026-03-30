"""Tests for html_export — pyLODE integration, language detection, switcher injection."""

from __future__ import annotations

import pathlib
from unittest.mock import MagicMock, patch

import pytest

from ster.html_export import (
    _available_languages,
    _inject_switcher,
    _lang_switcher_html,
    _patch_missing_pyproject,
    generate_html,
)
from ster.model import Concept, ConceptScheme, Definition, Label, Taxonomy

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
