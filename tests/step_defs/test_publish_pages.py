"""BDD step definitions for listing published pages on the publish screen."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("../features/io/publish_pages.feature")


@pytest.fixture
def ctx():
    return {}


def _make_group(publish_dir: Path, group: str) -> None:
    d = publish_dir / group
    d.mkdir(parents=True, exist_ok=True)
    (d / "onto.ttl").write_text("# ttl")
    (d / "index.html").write_text("<html></html>")


@given('a publish directory with dev, latest and version "1.0.0" pages')
def given_dev_latest_version(ctx, tmp_path):
    pub = tmp_path / "ontology"
    for g in ("dev", "latest", "v1.0.0"):
        _make_group(pub, g)
    ctx["pub"] = pub


@given(parsers.parse('a publish directory with versions "{a}" and "{b}" and "{c}"'))
def given_versions(ctx, tmp_path, a, b, c):
    pub = tmp_path / "ontology"
    for v in (a, b, c):
        _make_group(pub, f"v{v}")
    ctx["pub"] = pub


@given("a publish directory with only latest pages")
def given_only_latest(ctx, tmp_path):
    pub = tmp_path / "ontology"
    _make_group(pub, "latest")
    ctx["pub"] = pub


@when("I discover the published pages")
def when_discover(ctx):
    from ster.publish import discover_published_pages

    ctx["pages"] = discover_published_pages(ctx["pub"])


@when(parsers.parse('I build the publish menu against server "{base}"'))
def when_build_menu(ctx, base):
    from ster.publish import build_publish_menu, discover_published_pages

    ctx["rows"] = build_publish_menu(discover_published_pages(ctx["pub"]), base, ctx["pub"])


@then(parsers.parse('the groups listed are "{expected}"'))
def then_groups(ctx, expected):
    want = [g.strip() for g in expected.split(",")]
    seen = list(dict.fromkeys(p.group for p in ctx["pages"]))
    assert seen == want


@then(parsers.parse('the version groups in order are "{expected}"'))
def then_version_groups(ctx, expected):
    want = [g.strip() for g in expected.split(",")]
    seen = [g for g in dict.fromkeys(p.group for p in ctx["pages"]) if g.startswith("v")]
    assert seen == want


@then("the first row publishes a new stable version")
def then_first_row_stable(ctx):
    assert ctx["rows"][0].action == "publish_stable"


@then(parsers.parse('every page row label contains "{fragment}"'))
def then_rows_contain(ctx, fragment):
    open_rows = [r for r in ctx["rows"] if r.action == "open"]
    assert open_rows
    assert all(fragment in r.label for r in open_rows)
