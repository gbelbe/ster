"""Unit tests for auto-refreshing the dev pages after a commit.

Covers the pure version helper, the regenerate_dev_artifacts orchestration,
and the best-effort GitManager wrapper.
"""

from __future__ import annotations

from pathlib import Path

from ster.model import Label, LabelType, RDFClass, Taxonomy


def _write_onto(path: Path, *, version: str | None = None, term: str = "Animal") -> None:
    from ster.store import taxonomy_to_graph

    uri = "https://ex.org/onto"
    t = Taxonomy()
    t.ontology_uri = uri
    t.namespace_bindings[""] = uri + "#"
    if version is not None:
        t.version_info = version
    t.owl_classes[f"{uri}#{term}"] = RDFClass(
        uri=f"{uri}#{term}",
        labels=[Label(lang="en", value=term, type=LabelType.PREF)],
    )
    path.write_text(taxonomy_to_graph(t).serialize(format="turtle"))


# ── _dev_base_version (pure) ──────────────────────────────────────────────────


def test_dev_base_version_strips_local_part():
    from ster.publish import _dev_base_version

    assert _dev_base_version("2.5.0+20260101.abc1234") == "2.5.0"


def test_dev_base_version_plain():
    from ster.publish import _dev_base_version

    assert _dev_base_version("2.5.0") == "2.5.0"


def test_dev_base_version_none_defaults():
    from ster.publish import _dev_base_version

    assert _dev_base_version(None) == "0.1.0"


def test_dev_base_version_empty_defaults():
    from ster.publish import _dev_base_version

    assert _dev_base_version("") == "0.1.0"


# ── regenerate_dev_artifacts (orchestration) ─────────────────────────────────


def test_regenerate_dev_writes_ttl_and_html(tmp_path):
    from ster.publish import regenerate_dev_artifacts

    src = tmp_path / "onto.ttl"
    _write_onto(src, version="1.0.0")
    paths = regenerate_dev_artifacts(src, tmp_path / "ontology")

    dev = tmp_path / "ontology" / "dev"
    assert any(p.suffix == ".ttl" for p in paths)
    assert (dev / "index.html").exists()
    assert any(p.suffix == ".ttl" and p.parent == dev for p in paths)


def test_regenerate_dev_defaults_publish_dir_to_ontology(tmp_path):
    from ster.publish import regenerate_dev_artifacts

    src = tmp_path / "onto.ttl"
    _write_onto(src, version="1.0.0")
    paths = regenerate_dev_artifacts(src)  # publish_dir omitted

    expected = tmp_path / "ontology" / "dev"
    assert all(p.parent == expected for p in paths)
    assert (expected / "index.html").exists()


def test_regenerate_dev_ttl_contains_ontology_term(tmp_path):
    from ster.publish import regenerate_dev_artifacts

    src = tmp_path / "onto.ttl"
    _write_onto(src, version="1.0.0", term="Widget")
    paths = regenerate_dev_artifacts(src, tmp_path / "ontology")

    ttl = next(p for p in paths if p.suffix == ".ttl")
    assert "Widget" in ttl.read_text()


def test_regenerate_dev_does_not_modify_source(tmp_path):
    from ster.publish import regenerate_dev_artifacts

    src = tmp_path / "onto.ttl"
    _write_onto(src, version="1.0.0")
    before = src.read_bytes()
    regenerate_dev_artifacts(src, tmp_path / "ontology")
    assert src.read_bytes() == before


def test_regenerate_dev_missing_version_uses_default(tmp_path):
    from ster.publish import regenerate_dev_artifacts

    src = tmp_path / "onto.ttl"
    _write_onto(src, version=None)  # no owl:versionInfo
    paths = regenerate_dev_artifacts(src, tmp_path / "ontology")

    ttl = next(p for p in paths if p.suffix == ".ttl")
    assert "0.1.0" in ttl.read_text()  # default base stamped


# ── GitManager._refresh_dev_artifacts (best-effort wrapper) ──────────────────


def test_refresh_dev_swallows_errors(tmp_path, monkeypatch):
    import ster.publish as pub
    from ster.git.manager import GitManager

    src = tmp_path / "onto.ttl"
    _write_onto(src, version="1.0.0")

    def _boom(*_a, **_k):
        raise RuntimeError("render exploded")

    monkeypatch.setattr(pub, "regenerate_dev_artifacts", _boom)
    gm = GitManager(src)
    gm._refresh_dev_artifacts()  # must not raise


def test_refresh_dev_announces_on_success(tmp_path, monkeypatch):
    import ster.publish as pub
    from ster.git.manager import GitManager

    src = tmp_path / "onto.ttl"
    _write_onto(src, version="1.0.0")
    fake = tmp_path / "ontology" / "dev" / "onto.ttl"

    monkeypatch.setattr(pub, "regenerate_dev_artifacts", lambda *_a, **_k: [fake])
    gm = GitManager(src)
    gm._refresh_dev_artifacts()  # success branch, no raise
