"""BDD step definitions for tests/features/io/publish_open_browser.feature."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, scenarios, then, when

from ster.api import SSEBroadcaster, create_app
from ster.model import Label, RDFClass, Taxonomy
from ster.publish import open_dev_artifacts, served_artifact_urls

scenarios("../features/io/publish_open_browser.feature")

TOKEN = "test-token"
BASE = "http://127.0.0.1:8765"


@pytest.fixture
def ctx() -> dict:
    return {}


def _make_tax() -> Taxonomy:
    t = Taxonomy()
    t.ontology_uri = "https://ex.org/onto"
    t.owl_classes["https://ex.org/onto#A"] = RDFClass(
        uri="https://ex.org/onto#A", labels=[Label("en", "A")]
    )
    return t


@given("a dev publish wrote a Turtle file and an HTML page")
def given_dev_artifacts(ctx: dict, tmp_path: Path) -> None:
    pub = tmp_path / "ontology"
    dev = pub / "dev"
    dev.mkdir(parents=True)
    ttl = dev / "onto.ttl"
    ttl.write_text("@prefix : <https://ex.org/onto#> .")
    html = dev / "index.html"
    html.write_text("<html>doc</html>")
    ctx.update(pub=pub, ttl=ttl, html=html)


@when("I build the served URLs against the running server")
def when_build_urls(ctx: dict) -> None:
    ctx["urls"] = served_artifact_urls(BASE, ctx["pub"], [ctx["ttl"], ctx["html"]])


@when("I create the server with the publish directory mounted")
def when_create_server(ctx: dict) -> None:
    app = create_app(_make_tax(), TOKEN, SSEBroadcaster(), lambda t: None, publish_dir=ctx["pub"])
    ctx["client"] = TestClient(app)


@when("I open the dev artifacts with no server available")
def when_open_no_server(ctx: dict) -> None:
    opened: list[str] = []
    ctx["urls"] = open_dev_artifacts(ctx["pub"], [ctx["ttl"], ctx["html"]], None, opener=opened.append)
    ctx["opened"] = opened


@then("the URLs include the TTL and the HTML under /ontology/dev/")
def then_urls_include(ctx: dict) -> None:
    assert f"{BASE}/ontology/dev/onto.ttl" in ctx["urls"]
    assert f"{BASE}/ontology/dev/index.html" in ctx["urls"]


@then("the TTL URL comes before the HTML URL")
def then_ttl_first(ctx: dict) -> None:
    urls = ctx["urls"]
    assert urls.index(f"{BASE}/ontology/dev/onto.ttl") < urls.index(
        f"{BASE}/ontology/dev/index.html"
    )


@then("GET /ontology/dev/index.html returns the HTML page")
def then_get_html(ctx: dict) -> None:
    r = ctx["client"].get("/ontology/dev/index.html")
    assert r.status_code == 200
    assert "doc" in r.text


@then("GET the dev Turtle path returns the Turtle file")
def then_get_ttl(ctx: dict) -> None:
    r = ctx["client"].get("/ontology/dev/onto.ttl")
    assert r.status_code == 200
    assert "prefix" in r.text.lower()


@then("the opened URLs are file URLs for the TTL and the HTML")
def then_file_urls(ctx: dict) -> None:
    urls = ctx["urls"]
    assert ctx["opened"] == urls
    assert all(u.startswith("file://") for u in urls)
    assert urls[0].endswith("onto.ttl")
    assert urls[1].endswith("index.html")
