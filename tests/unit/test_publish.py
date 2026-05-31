"""Unit tests for ster/publish.py — core pipeline functions."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from ster.model import Label, LabelType, RDFClass, Taxonomy

if TYPE_CHECKING:
    from ster.publish import PublishContext


def _minimal_taxonomy(uri: str = "https://ex.org/onto") -> Taxonomy:
    t = Taxonomy()
    t.ontology_uri = uri
    t.namespace_bindings[""] = uri + "#"
    t.owl_classes[uri + "#Animal"] = RDFClass(
        uri=uri + "#Animal",
        labels=[Label(lang="en", value="Animal", type=LabelType.PREF)],
    )
    return t


def _write_ttl(path: Path, taxonomy: Taxonomy) -> None:
    from ster.store import taxonomy_to_graph

    g = taxonomy_to_graph(taxonomy)
    path.write_text(g.serialize(format="turtle"))


# ── build_version_string ──────────────────────────────────────────────────────


def test_build_version_string() -> None:
    from ster.publish import build_version_string

    result = build_version_string("1.2.0", "20260528", "abc1234")
    assert result == "1.2.0+20260528.abc1234"


def test_build_version_string_pads_sha() -> None:
    from ster.publish import build_version_string

    result = build_version_string("0.1.0", "20260101", "deadbeef")
    assert result == "0.1.0+20260101.deadbeef"


# ── bump_version ─────────────────────────────────────────────────────────────


def test_bump_version_patch() -> None:
    from ster.publish import bump_version

    assert bump_version("1.1.0", "patch") == "1.1.1"


def test_bump_version_minor() -> None:
    from ster.publish import bump_version

    assert bump_version("1.1.0", "minor") == "1.2.0"


def test_bump_version_major() -> None:
    from ster.publish import bump_version

    assert bump_version("1.1.0", "major") == "2.0.0"


def test_bump_version_strips_leading_v() -> None:
    from ster.publish import bump_version

    assert bump_version("v1.1.0", "patch") == "1.1.1"


def test_bump_version_patch_resets_none() -> None:
    from ster.publish import bump_version

    assert bump_version("1.1.9", "patch") == "1.1.10"


# ── patch_version_triples ─────────────────────────────────────────────────────


def test_patch_version_triples_sets_version_info(tmp_path: Path) -> None:
    from ster.publish import patch_version_triples

    t = _minimal_taxonomy()
    f = tmp_path / "onto.ttl"
    _write_ttl(f, t)
    patch_version_triples(f, "1.2.0+20260528.abc1234", "1.2.0")
    content = f.read_text()
    assert "1.2.0+20260528.abc1234" in content


def test_patch_version_triples_sets_version_iri(tmp_path: Path) -> None:
    from ster.publish import patch_version_triples

    t = _minimal_taxonomy()
    f = tmp_path / "onto.ttl"
    _write_ttl(f, t)
    patch_version_triples(f, "1.2.0+20260528.abc1234", "1.2.0")
    content = f.read_text()
    assert "https://ex.org/onto/1.2.0" in content


def test_patch_version_triples_sets_prior_version(tmp_path: Path) -> None:
    from ster.publish import patch_version_triples

    t = _minimal_taxonomy()
    t.prior_version = "https://ex.org/onto/1.1.0"
    f = tmp_path / "onto.ttl"
    _write_ttl(f, t)
    patch_version_triples(f, "1.2.0+20260528.abc1234", "1.2.0")
    content = f.read_text()
    assert "https://ex.org/onto/1.1.0" in content


def test_patch_version_triples_sets_dcterms_modified(tmp_path: Path) -> None:
    from ster.publish import patch_version_triples

    t = _minimal_taxonomy()
    f = tmp_path / "onto.ttl"
    _write_ttl(f, t)
    patch_version_triples(f, "1.2.0+20260528.abc1234", "1.2.0")
    content = f.read_text()
    today = datetime.date.today().isoformat()
    assert today in content


def test_patch_version_triples_roundtrips_via_rdflib(tmp_path: Path) -> None:
    from rdflib import Graph

    from ster.publish import patch_version_triples
    from ster.store import graph_to_taxonomy

    t = _minimal_taxonomy()
    f = tmp_path / "onto.ttl"
    _write_ttl(f, t)
    patch_version_triples(f, "1.2.0+20260528.abc1234", "1.2.0")
    g = Graph()
    g.parse(str(f), format="turtle")
    t2 = graph_to_taxonomy(g)
    assert t2.version_info == "1.2.0+20260528.abc1234"
    assert t2.version_iri == "https://ex.org/onto/1.2.0"


# ── write_stable_artifacts ────────────────────────────────────────────────────


def test_write_stable_artifacts_creates_versioned_dir(tmp_path: Path) -> None:
    from ster.publish import write_stable_artifacts

    t = _minimal_taxonomy()
    src = tmp_path / "onto.ttl"
    _write_ttl(src, t)
    pub = tmp_path / "ontology"
    write_stable_artifacts(src, pub, "1.2.0", "1.2.0+20260528.abc1234")
    assert (pub / "v1.2.0" / "onto.ttl").exists()


def test_write_stable_artifacts_creates_latest_dir(tmp_path: Path) -> None:
    from ster.publish import write_stable_artifacts

    t = _minimal_taxonomy()
    src = tmp_path / "onto.ttl"
    _write_ttl(src, t)
    pub = tmp_path / "ontology"
    write_stable_artifacts(src, pub, "1.2.0", "1.2.0+20260528.abc1234")
    assert (pub / "latest" / "onto.ttl").exists()


def test_write_stable_artifacts_overwrites_latest(tmp_path: Path) -> None:
    from ster.publish import write_stable_artifacts

    t = _minimal_taxonomy()
    src = tmp_path / "onto.ttl"
    _write_ttl(src, t)
    pub = tmp_path / "ontology"
    (pub / "latest").mkdir(parents=True)
    (pub / "latest" / "onto.ttl").write_text("old content")
    write_stable_artifacts(src, pub, "1.2.0", "1.2.0+20260528.abc1234")
    content = (pub / "latest" / "onto.ttl").read_text()
    assert "old content" not in content
    assert "1.2.0+20260528.abc1234" in content


# ── write_dev_artifacts ───────────────────────────────────────────────────────


def test_write_dev_artifacts_does_not_modify_source_file(tmp_path: Path) -> None:
    from ster.publish import write_dev_artifacts

    t = _minimal_taxonomy()
    src = tmp_path / "onto.ttl"
    _write_ttl(src, t)
    original = src.read_text()
    pub = tmp_path / "ontology"
    write_dev_artifacts(src, pub, "1.2.0+20260527.deadbeef")
    assert src.read_text() == original


def test_write_dev_artifacts_overwrites_dev_dir(tmp_path: Path) -> None:
    from ster.publish import write_dev_artifacts

    t = _minimal_taxonomy()
    src = tmp_path / "onto.ttl"
    _write_ttl(src, t)
    pub = tmp_path / "ontology"
    (pub / "dev").mkdir(parents=True)
    (pub / "dev" / "onto.ttl").write_text("old dev content")
    write_dev_artifacts(src, pub, "1.2.0+20260527.deadbeef")
    content = (pub / "dev" / "onto.ttl").read_text()
    assert "old dev content" not in content


def test_write_dev_artifacts_creates_dev_if_missing(tmp_path: Path) -> None:
    from ster.publish import write_dev_artifacts

    t = _minimal_taxonomy()
    src = tmp_path / "onto.ttl"
    _write_ttl(src, t)
    pub = tmp_path / "ontology"
    write_dev_artifacts(src, pub, "1.2.0+20260527.deadbeef")
    assert (pub / "dev" / "onto.ttl").exists()


# ── pre_flight ────────────────────────────────────────────────────────────────


def test_pre_flight_fails_on_missing_ontology_uri() -> None:
    from ster.publish import PublishError, pre_flight

    t = Taxonomy()
    with pytest.raises(PublishError, match="ontology URI"):
        pre_flight(t)


def test_pre_flight_passes_with_ontology_uri() -> None:
    from ster.publish import pre_flight

    t = _minimal_taxonomy()
    pre_flight(t)  # must not raise


# ── test helpers ──────────────────────────────────────────────────────────────


def _make_context(tmp_path: Path) -> PublishContext:
    """Build a minimal PublishContext backed by a real .ttl file."""
    from rdflib import Graph

    from ster.publish import PublishContext, _detect_format, _patch_version_in_graph
    from ster.store import graph_to_taxonomy

    t = _minimal_taxonomy()
    src = tmp_path / "onto.ttl"
    _write_ttl(src, t)
    g = Graph()
    g.parse(str(src), format=_detect_format(src))
    _patch_version_in_graph(g, "1.2.0+20260528.abc1234", "1.2.0")
    taxonomy = graph_to_taxonomy(g)
    return PublishContext(
        source_file=src,
        taxonomy=taxonomy,
        graph=g,
        version_str="1.2.0+20260528.abc1234",
        base_version="1.2.0",
    )


class _RecordingSerializer:
    """Fake serializer that records every call without side effects."""

    name = "recorder"

    def __init__(self, filename: str = "out.dat") -> None:
        self.calls: list[Path] = []
        self.filename = filename

    def write(self, ctx: PublishContext, dest_dir: Path) -> list[Path]:
        p = dest_dir / self.filename
        p.write_text("data")
        self.calls.append(dest_dir)
        return [p]


class _FailingSerializer:
    name = "failing"

    def write(self, ctx: PublishContext, dest_dir: Path) -> list[Path]:
        raise RuntimeError("boom")


# ── PublishContext ────────────────────────────────────────────────────────────


def test_publish_context_holds_source_file(tmp_path: Path) -> None:
    ctx = _make_context(tmp_path)
    assert ctx.source_file.name == "onto.ttl"


def test_publish_context_holds_version_str(tmp_path: Path) -> None:
    ctx = _make_context(tmp_path)
    assert ctx.version_str == "1.2.0+20260528.abc1234"


def test_publish_context_taxonomy_has_ontology_uri(tmp_path: Path) -> None:
    ctx = _make_context(tmp_path)
    assert ctx.taxonomy.ontology_uri == "https://ex.org/onto"


def test_publish_context_graph_is_not_empty(tmp_path: Path) -> None:
    ctx = _make_context(tmp_path)
    assert len(ctx.graph) > 0


# ── TurtleSerializer ──────────────────────────────────────────────────────────


def test_turtle_serializer_writes_file_to_dest_dir(tmp_path: Path) -> None:
    from ster.publish import TurtleSerializer

    dest = tmp_path / "out"
    dest.mkdir()
    paths = TurtleSerializer().write(_make_context(tmp_path), dest)
    assert len(paths) == 1
    assert paths[0].exists()


def test_turtle_serializer_uses_source_filename(tmp_path: Path) -> None:
    from ster.publish import TurtleSerializer

    dest = tmp_path / "out"
    dest.mkdir()
    paths = TurtleSerializer().write(_make_context(tmp_path), dest)
    assert paths[0].name == "onto.ttl"


def test_turtle_serializer_output_is_valid_turtle(tmp_path: Path) -> None:
    from rdflib import Graph

    from ster.publish import TurtleSerializer

    dest = tmp_path / "out"
    dest.mkdir()
    paths = TurtleSerializer().write(_make_context(tmp_path), dest)
    g = Graph()
    g.parse(str(paths[0]), format="turtle")
    assert len(g) > 0


def test_turtle_serializer_output_contains_version_string(tmp_path: Path) -> None:
    from ster.publish import TurtleSerializer

    dest = tmp_path / "out"
    dest.mkdir()
    paths = TurtleSerializer().write(_make_context(tmp_path), dest)
    assert "1.2.0+20260528.abc1234" in paths[0].read_text()


# ── HtmlSerializer ────────────────────────────────────────────────────────────


def test_html_serializer_returns_empty_list_when_pylode_missing(tmp_path: Path) -> None:
    import sys

    from ster.publish import HtmlSerializer

    ctx = _make_context(tmp_path)
    dest = tmp_path / "out"
    dest.mkdir()

    saved = sys.modules.pop("pylode", None)
    sys.modules["pylode"] = None  # type: ignore[assignment]
    try:
        paths = HtmlSerializer().write(ctx, dest)
    finally:
        if saved is not None:
            sys.modules["pylode"] = saved
        else:
            sys.modules.pop("pylode", None)

    assert paths == []


def test_html_serializer_does_not_raise_when_pylode_missing(tmp_path: Path) -> None:
    import sys

    from ster.publish import HtmlSerializer

    ctx = _make_context(tmp_path)
    dest = tmp_path / "out"
    dest.mkdir()

    saved = sys.modules.pop("pylode", None)
    sys.modules["pylode"] = None  # type: ignore[assignment]
    try:
        HtmlSerializer().write(ctx, dest)  # must not raise
    finally:
        if saved is not None:
            sys.modules["pylode"] = saved
        else:
            sys.modules.pop("pylode", None)


# ── _run_serializers ──────────────────────────────────────────────────────────


def test_run_serializers_calls_serializer_for_each_dir(tmp_path: Path) -> None:
    from ster.publish import _run_serializers

    ctx = _make_context(tmp_path)
    d1, d2 = tmp_path / "d1", tmp_path / "d2"
    rec = _RecordingSerializer()
    _run_serializers(ctx, [d1, d2], [rec])
    assert len(rec.calls) == 2
    assert d1 in rec.calls
    assert d2 in rec.calls


def test_run_serializers_creates_missing_dirs(tmp_path: Path) -> None:
    from ster.publish import _run_serializers

    ctx = _make_context(tmp_path)
    dest = tmp_path / "deep" / "nested"
    assert not dest.exists()
    _run_serializers(ctx, [dest], [_RecordingSerializer()])
    assert dest.is_dir()


def test_run_serializers_isolates_failing_serializer(tmp_path: Path) -> None:
    from ster.publish import _run_serializers

    ctx = _make_context(tmp_path)
    dest = tmp_path / "out"
    good = _RecordingSerializer()
    _run_serializers(ctx, [dest], [_FailingSerializer(), good])
    assert len(good.calls) == 1


def test_run_serializers_returns_all_written_paths(tmp_path: Path) -> None:
    from ster.publish import _run_serializers

    ctx = _make_context(tmp_path)
    d1, d2 = tmp_path / "d1", tmp_path / "d2"
    paths = _run_serializers(
        ctx, [d1, d2], [_RecordingSerializer("a.dat"), _RecordingSerializer("b.dat")]
    )
    assert len(paths) == 4  # 2 dirs × 2 serializers


def test_run_serializers_omits_failing_serializer_paths(tmp_path: Path) -> None:
    from ster.publish import _run_serializers

    ctx = _make_context(tmp_path)
    dest = tmp_path / "out"
    good = _RecordingSerializer()
    paths = _run_serializers(ctx, [dest], [_FailingSerializer(), good])
    assert all(p.name == "out.dat" for p in paths)


def test_run_serializers_empty_serializer_list_returns_empty(tmp_path: Path) -> None:
    from ster.publish import _run_serializers

    ctx = _make_context(tmp_path)
    dest = tmp_path / "out"
    paths = _run_serializers(ctx, [dest], [])
    assert paths == []


# ── _default_serializers ──────────────────────────────────────────────────────


def test_default_serializers_contains_turtle(tmp_path: Path) -> None:
    from ster.publish import TurtleSerializer, _default_serializers

    names = [s.name for s in _default_serializers()]
    assert "turtle" in names
    assert any(isinstance(s, TurtleSerializer) for s in _default_serializers())


def test_default_serializers_contains_html(tmp_path: Path) -> None:
    from ster.publish import HtmlSerializer, _default_serializers

    names = [s.name for s in _default_serializers()]
    assert "html" in names
    assert any(isinstance(s, HtmlSerializer) for s in _default_serializers())


def test_default_serializers_returns_new_list_each_call(tmp_path: Path) -> None:
    from ster.publish import _default_serializers

    assert _default_serializers() is not _default_serializers()


# ── ArtifactSerializer protocol ───────────────────────────────────────────────


def test_recording_serializer_satisfies_protocol(tmp_path: Path) -> None:
    from ster.publish import ArtifactSerializer

    assert isinstance(_RecordingSerializer(), ArtifactSerializer)


def test_failing_serializer_satisfies_protocol(tmp_path: Path) -> None:
    from ster.publish import ArtifactSerializer

    assert isinstance(_FailingSerializer(), ArtifactSerializer)


def test_turtle_serializer_satisfies_protocol(tmp_path: Path) -> None:
    from ster.publish import ArtifactSerializer, TurtleSerializer

    assert isinstance(TurtleSerializer(), ArtifactSerializer)


# ── custom serializers via write_stable_artifacts ─────────────────────────────


def test_write_stable_artifacts_accepts_custom_serializer(tmp_path: Path) -> None:
    from ster.publish import write_stable_artifacts

    t = _minimal_taxonomy()
    src = tmp_path / "onto.ttl"
    _write_ttl(src, t)
    pub = tmp_path / "ontology"
    rec = _RecordingSerializer("custom.dat")
    write_stable_artifacts(src, pub, "1.2.0", "1.2.0+20260528.abc1234", serializers=[rec])
    assert (pub / "v1.2.0" / "custom.dat").exists()
    assert (pub / "latest" / "custom.dat").exists()


def test_write_dev_artifacts_accepts_custom_serializer(tmp_path: Path) -> None:
    from ster.publish import write_dev_artifacts

    t = _minimal_taxonomy()
    src = tmp_path / "onto.ttl"
    _write_ttl(src, t)
    pub = tmp_path / "ontology"
    rec = _RecordingSerializer("custom.dat")
    write_dev_artifacts(src, pub, "1.2.0+20260527.deadbeef", serializers=[rec])
    assert (pub / "dev" / "custom.dat").exists()
