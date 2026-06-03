"""BDD step definitions for auto-refreshing the dev pages on commit."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("../features/io/dev_auto_refresh.feature")


@pytest.fixture
def ctx():
    return {}


def _write_onto(path: Path, *, version: str | None, term: str = "Animal") -> None:
    from ster.model import Label, LabelType, RDFClass, Taxonomy
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


@given("an ontology file with a version")
def given_onto_with_version(ctx, tmp_path):
    src = tmp_path / "onto.ttl"
    _write_onto(src, version="1.0.0")
    ctx["src"] = src
    ctx["publish_dir"] = tmp_path / "ontology"


@given(parsers.parse('an ontology file containing a class "{term}"'))
def given_onto_with_term(ctx, tmp_path, term):
    src = tmp_path / "onto.ttl"
    _write_onto(src, version="1.0.0", term=term)
    ctx["src"] = src
    ctx["publish_dir"] = tmp_path / "ontology"


@given("an ontology file with no version set")
def given_onto_no_version(ctx, tmp_path):
    src = tmp_path / "onto.ttl"
    _write_onto(src, version=None)
    ctx["src"] = src
    ctx["publish_dir"] = tmp_path / "ontology"


@when("the dev artifacts are regenerated for it")
def when_regenerate(ctx):
    from ster.publish import regenerate_dev_artifacts

    ctx["before"] = ctx["src"].read_bytes()
    ctx["paths"] = regenerate_dev_artifacts(ctx["src"], ctx["publish_dir"])


@then("ontology/dev/ contains a Turtle file and an HTML page")
def then_dev_has_ttl_and_html(ctx):
    dev = ctx["publish_dir"] / "dev"
    assert any(p.suffix == ".ttl" and p.parent == dev for p in ctx["paths"])
    assert (dev / "index.html").exists()


@then(parsers.parse('the dev Turtle file mentions "{term}"'))
def then_dev_ttl_mentions(ctx, term):
    ttl = next(p for p in ctx["paths"] if p.suffix == ".ttl")
    assert term in ttl.read_text()


@then("the source file content is unchanged")
def then_source_unchanged(ctx):
    assert ctx["src"].read_bytes() == ctx["before"]
