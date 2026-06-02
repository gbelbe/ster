"""Unit tests for opening dev-channel artifacts on the running web server.

After a dev publish the written TTL and HTML artifacts are opened in the browser
via the graph server's ``/ontology`` static mount (served URLs), falling back to
``file://`` when no server is available.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ster.api import SSEBroadcaster, create_app
from ster.model import Label, RDFClass, Taxonomy
from ster.publish import open_dev_artifacts, served_artifact_urls

TOKEN = "test-token"


def _make_tax() -> Taxonomy:
    t = Taxonomy()
    t.ontology_uri = "https://ex.org/onto"
    t.owl_classes["https://ex.org/onto#A"] = RDFClass(
        uri="https://ex.org/onto#A", labels=[Label("en", "A")]
    )
    return t


def _dev_artifacts(tmp_path: Path) -> tuple[Path, Path, Path]:
    pub = tmp_path / "ontology"
    dev = pub / "dev"
    dev.mkdir(parents=True)
    ttl = dev / "onto.ttl"
    ttl.write_text("@prefix : <https://ex.org/onto#> .")
    html = dev / "index.html"
    html.write_text("<html>doc</html>")
    return pub, ttl, html


# ── served_artifact_urls (pure) ──────────────────────────────────────────────────


def test_served_artifact_urls_maps_ttl_and_html(tmp_path: Path):
    pub, ttl, html = _dev_artifacts(tmp_path)
    urls = served_artifact_urls("http://127.0.0.1:8765", pub, [ttl, html])
    assert "http://127.0.0.1:8765/ontology/dev/onto.ttl" in urls
    assert "http://127.0.0.1:8765/ontology/dev/index.html" in urls


def test_served_artifact_urls_ttl_before_html(tmp_path: Path):
    pub, ttl, html = _dev_artifacts(tmp_path)
    # HTML listed first in the artifacts, but TTL must come first in the output.
    urls = served_artifact_urls("http://127.0.0.1:8765/", pub, [html, ttl])
    assert urls[0].endswith("/ontology/dev/onto.ttl")
    assert urls[1].endswith("/ontology/dev/index.html")


def test_served_artifact_urls_ignores_other_and_empty(tmp_path: Path):
    pub, ttl, _html = _dev_artifacts(tmp_path)
    other = pub / "dev" / "meta.json"
    other.write_text("{}")
    assert served_artifact_urls("http://h", pub, [other]) == []
    assert served_artifact_urls("http://h", pub, []) == []


# ── create_app static mount ──────────────────────────────────────────────────────


def test_create_app_serves_published_dev_html(tmp_path: Path):
    pub, _ttl, _html = _dev_artifacts(tmp_path)
    app = create_app(_make_tax(), TOKEN, SSEBroadcaster(), lambda t: None, publish_dir=pub)
    r = TestClient(app).get("/ontology/dev/index.html")
    assert r.status_code == 200
    assert "doc" in r.text


def test_create_app_serves_published_dev_ttl(tmp_path: Path):
    pub, _ttl, _html = _dev_artifacts(tmp_path)
    app = create_app(_make_tax(), TOKEN, SSEBroadcaster(), lambda t: None, publish_dir=pub)
    r = TestClient(app).get("/ontology/dev/onto.ttl")
    assert r.status_code == 200
    assert "prefix" in r.text.lower()


# ── open_dev_artifacts (orchestration with injected opener) ──────────────────────


def test_open_dev_artifacts_opens_served_urls(tmp_path: Path):
    pub, ttl, html = _dev_artifacts(tmp_path)
    opened: list[str] = []
    urls = open_dev_artifacts(pub, [ttl, html], "http://127.0.0.1:8765", opener=opened.append)
    assert opened == urls
    assert urls[0].endswith("/ontology/dev/onto.ttl")
    assert urls[1].endswith("/ontology/dev/index.html")


def test_open_dev_artifacts_falls_back_to_file_urls(tmp_path: Path):
    pub, ttl, html = _dev_artifacts(tmp_path)
    opened: list[str] = []
    urls = open_dev_artifacts(pub, [ttl, html], None, opener=opened.append)
    assert opened == urls
    assert all(u.startswith("file://") for u in urls)
    assert urls[0].endswith("onto.ttl")
    assert urls[1].endswith("index.html")


def test_open_dev_artifacts_no_artifacts_opens_nothing(tmp_path: Path):
    pub, _ttl, _html = _dev_artifacts(tmp_path)
    opened: list[str] = []
    assert open_dev_artifacts(pub, [], "http://127.0.0.1:8765", opener=opened.append) == []
    assert opened == []
