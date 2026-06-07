"""BDD step definitions for tests/features/ci/publish.feature."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("../features/ci/publish.feature")

NS = "https://ex.org/onto#"


# ── shared fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def ctx(tmp_path: Path) -> dict:
    return {"tmp_path": tmp_path}


def _minimal_taxonomy(uri: str = "https://ex.org/onto") -> object:
    from ster.model import Label, LabelType, RDFClass, Taxonomy

    t = Taxonomy()
    t.ontology_uri = uri
    t.namespace_bindings[""] = uri + "#"
    t.owl_classes[uri + "#Animal"] = RDFClass(
        uri=uri + "#Animal",
        labels=[Label(lang="en", value="Animal", type=LabelType.PREF)],
    )
    return t


def _write_ttl(path: Path, taxonomy: object) -> None:
    from ster.store import taxonomy_to_graph

    g = taxonomy_to_graph(taxonomy)
    path.write_text(g.serialize(format="turtle"))


# ── Model + store ─────────────────────────────────────────────────────────────


@given(parsers.parse('a taxonomy with ontology URI "{uri}" and version_info "{vi}"'))
def given_taxonomy_version_info(ctx: dict, uri: str, vi: str) -> None:
    from ster.model import Taxonomy

    t = Taxonomy()
    t.ontology_uri = uri
    t.version_info = vi
    ctx["taxonomy"] = t


@given(parsers.parse('a taxonomy with version_iri "{viri}"'))
def given_taxonomy_version_iri(ctx: dict, viri: str) -> None:
    from ster.model import Taxonomy

    t = Taxonomy()
    t.ontology_uri = "https://ex.org/onto"
    t.version_iri = viri
    ctx["taxonomy"] = t


@given(parsers.parse('a taxonomy with prior_version "{pv}"'))
def given_taxonomy_prior_version(ctx: dict, pv: str) -> None:
    from ster.model import Taxonomy

    t = Taxonomy()
    t.ontology_uri = "https://ex.org/onto"
    t.prior_version = pv
    ctx["taxonomy"] = t


@when("I save and reload the taxonomy")
def when_save_reload(ctx: dict) -> None:
    from rdflib import Graph

    from ster.store import graph_to_taxonomy, taxonomy_to_graph

    g = taxonomy_to_graph(ctx["taxonomy"])
    ttl = g.serialize(format="turtle")
    g2 = Graph()
    g2.parse(data=ttl, format="turtle")
    ctx["taxonomy"] = graph_to_taxonomy(g2)


@then(parsers.parse('taxonomy.version_info is "{value}"'))
def then_version_info(ctx: dict, value: str) -> None:
    assert ctx["taxonomy"].version_info == value


@then(parsers.parse('taxonomy.version_iri is "{value}"'))
def then_version_iri(ctx: dict, value: str) -> None:
    assert ctx["taxonomy"].version_iri == value


@then(parsers.parse('taxonomy.prior_version is "{value}"'))
def then_prior_version(ctx: dict, value: str) -> None:
    assert ctx["taxonomy"].prior_version == value


# ── build_version_string ──────────────────────────────────────────────────────


@given(parsers.parse('base version "{base}", date "{date}", sha "{sha}"'))
def given_version_parts(ctx: dict, base: str, date: str, sha: str) -> None:
    ctx["base"] = base
    ctx["date"] = date
    ctx["sha"] = sha


@when("I build the version string")
def when_build_version(ctx: dict) -> None:
    from ster.publish import build_version_string

    ctx["result"] = build_version_string(ctx["base"], ctx["date"], ctx["sha"])


@then(parsers.parse('the result is "{expected}"'))
def then_result(ctx: dict, expected: str) -> None:
    assert ctx["result"] == expected


# ── bump_version ──────────────────────────────────────────────────────────────


@given(parsers.parse('current version "{version}"'))
def given_current_version(ctx: dict, version: str) -> None:
    ctx["version"] = version


@when(parsers.parse('I bump with kind "{kind}"'))
def when_bump_version(ctx: dict, kind: str) -> None:
    from ster.publish import bump_version

    ctx["bumped"] = bump_version(ctx["version"], kind)


@then(parsers.parse('the bumped result is "{expected}"'))
def then_bumped_result(ctx: dict, expected: str) -> None:
    assert ctx["bumped"] == expected


# ── patch_version_triples ─────────────────────────────────────────────────────


@given(parsers.parse('a taxonomy file with ontology URI "{uri}"'))
def given_taxonomy_file(ctx: dict, uri: str) -> None:
    t = _minimal_taxonomy(uri)
    f = ctx["tmp_path"] / "onto.ttl"
    _write_ttl(f, t)
    ctx["file"] = f
    ctx["taxonomy"] = t


@given(parsers.parse('a taxonomy file with ontology URI "{uri}" and prior_version "{pv}"'))
def given_taxonomy_file_with_prior(ctx: dict, uri: str, pv: str) -> None:
    t = _minimal_taxonomy(uri)
    t.prior_version = pv
    f = ctx["tmp_path"] / "onto.ttl"
    _write_ttl(f, t)
    ctx["file"] = f
    ctx["taxonomy"] = t


@given(parsers.parse('a source taxonomy file at path "{name}"'))
def given_source_taxonomy_file(ctx: dict, name: str) -> None:
    t = _minimal_taxonomy()
    f = ctx["tmp_path"] / name
    _write_ttl(f, t)
    ctx["file"] = f
    ctx["original_content"] = f.read_text()


@when(parsers.parse('I patch version "{version}" with base "{base}"'))
def when_patch_version(ctx: dict, version: str, base: str) -> None:
    from ster.publish import patch_version_triples

    patch_version_triples(ctx["file"], version, base)


@when("I run write_dev_artifacts")
def when_write_dev(ctx: dict) -> None:
    from ster.publish import write_dev_artifacts

    pub = ctx["tmp_path"] / "ontology"
    src = ctx.get("file") or ctx.get("src")
    assert src is not None
    write_dev_artifacts(src, pub, "1.2.0+20260527.deadbeef")
    ctx["pub"] = pub


@then(parsers.parse('the file contains owl:versionInfo "{value}"'))
def then_file_contains_version_info(ctx: dict, value: str) -> None:
    assert value in ctx["file"].read_text()


@then(parsers.parse('the file contains owl:versionIRI "{value}"'))
def then_file_contains_version_iri(ctx: dict, value: str) -> None:
    assert value in ctx["file"].read_text()


@then(parsers.parse('the file contains owl:priorVersion "{value}"'))
def then_file_contains_prior(ctx: dict, value: str) -> None:
    assert value in ctx["file"].read_text()


@then("the file contains a dcterms:modified date")
def then_file_contains_modified(ctx: dict) -> None:
    import datetime

    today = datetime.date.today().isoformat()
    assert today in ctx["file"].read_text()


@then("the source file is unchanged")
def then_source_unchanged(ctx: dict) -> None:
    assert ctx["file"].read_text() == ctx["original_content"]


# ── artifact generation ───────────────────────────────────────────────────────


@given(parsers.parse('publish_dir and version "{version}"'))
def given_publish_dir_and_version(ctx: dict, version: str) -> None:
    t = _minimal_taxonomy()
    src = ctx["tmp_path"] / "onto.ttl"
    _write_ttl(src, t)
    ctx["src"] = src
    ctx["version"] = version
    ctx["pub"] = ctx["tmp_path"] / "ontology"


@given('publish_dir with existing "latest/onto.ttl"')
def given_publish_dir_with_latest(ctx: dict) -> None:
    t = _minimal_taxonomy()
    src = ctx["tmp_path"] / "onto.ttl"
    _write_ttl(src, t)
    ctx["src"] = src
    pub = ctx["tmp_path"] / "ontology"
    (pub / "latest").mkdir(parents=True)
    (pub / "latest" / "onto.ttl").write_text("old content")
    ctx["pub"] = pub


@given('publish_dir with existing "dev/onto.ttl"')
def given_publish_dir_with_dev(ctx: dict) -> None:
    t = _minimal_taxonomy()
    src = ctx["tmp_path"] / "onto.ttl"
    _write_ttl(src, t)
    ctx["src"] = src
    ctx["file"] = src
    pub = ctx["tmp_path"] / "ontology"
    (pub / "dev").mkdir(parents=True)
    (pub / "dev" / "onto.ttl").write_text("old dev content")
    ctx["pub"] = pub


@given("publish_dir with no dev directory")
def given_publish_dir_no_dev(ctx: dict) -> None:
    t = _minimal_taxonomy()
    src = ctx["tmp_path"] / "onto.ttl"
    _write_ttl(src, t)
    ctx["src"] = src
    ctx["file"] = src
    ctx["pub"] = ctx["tmp_path"] / "ontology"


@when(parsers.parse('I write stable artifacts for "{version_str}"'))
def when_write_stable(ctx: dict, version_str: str) -> None:
    from ster.publish import write_stable_artifacts

    base = version_str.split("+")[0]
    write_stable_artifacts(ctx["src"], ctx["pub"], base, version_str)


@then(parsers.parse('the versioned TTL exists under "{dir_name}"'))
def then_versioned_ttl_exists(ctx: dict, dir_name: str) -> None:
    assert (ctx["pub"] / dir_name / "onto.ttl").exists()


@then(parsers.parse('"{rel_path}" contains "{text}"'))
def then_file_contains_text(ctx: dict, rel_path: str, text: str) -> None:
    full = ctx["pub"] / rel_path
    assert text in full.read_text()


@then(parsers.parse('"{rel_path}" exists with updated content'))
def then_dev_ttl_exists(ctx: dict, rel_path: str) -> None:
    full = ctx["pub"] / rel_path
    assert full.exists()
    assert "old dev content" not in full.read_text()


@then(parsers.parse('"{rel_path}" exists'))
def then_rel_path_exists(ctx: dict, rel_path: str) -> None:
    assert (ctx["pub"] / rel_path).exists()


# ── pre_flight ────────────────────────────────────────────────────────────────


@given("a taxonomy with no ontology URI set")
def given_no_ontology_uri(ctx: dict) -> None:
    from ster.model import Taxonomy

    ctx["taxonomy"] = Taxonomy()


@when("I run pre_flight check")
def when_pre_flight(ctx: dict) -> None:
    from ster.publish import PublishError, pre_flight

    try:
        pre_flight(ctx["taxonomy"])
        ctx["error"] = None
    except PublishError as e:
        ctx["error"] = e


@then(parsers.parse('pre_flight raises PublishError mentioning "{text}"'))
def then_pre_flight_error(ctx: dict, text: str) -> None:
    assert ctx["error"] is not None
    assert text in str(ctx["error"])


# ── FastAPI serving ───────────────────────────────────────────────────────────


@given(parsers.parse('a running API with publish_dir containing "{rel_path}"'))
def given_api_with_publish_dir(ctx: dict, rel_path: str) -> None:
    from ster.api import SSEBroadcaster, create_app
    from ster.model import Taxonomy

    pub = ctx["tmp_path"] / "published"
    parts = rel_path.split("/")
    subdir = pub / "/".join(parts[:-1])
    subdir.mkdir(parents=True, exist_ok=True)
    (pub / rel_path).write_text(
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n<https://ex.org/onto> a owl:Ontology ."
    )

    t = Taxonomy()
    t.ontology_uri = "https://ex.org/onto"
    app = create_app(t, "token", SSEBroadcaster(), lambda _: None, publish_dir=pub)
    ctx["client"] = TestClient(app, raise_server_exceptions=False)


@when(parsers.parse('I GET "{route}"'))
def when_get(ctx: dict, route: str) -> None:
    ctx["response"] = ctx["client"].get(route)


@then(parsers.parse("the response status is {status:d}"))
def then_status(ctx: dict, status: int) -> None:
    assert ctx["response"].status_code == status, ctx["response"].text
