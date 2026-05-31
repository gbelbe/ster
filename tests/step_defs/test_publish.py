"""BDD step definitions for tests/features/ci/publish.feature."""

from __future__ import annotations

import json
import subprocess
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


# ── state file ────────────────────────────────────────────────────────────────


@given("a fresh publish state")
def given_fresh_state(ctx: dict) -> None:
    from ster.publish_state import init_state

    state = init_state(
        ctx["tmp_path"], "stable", "1.2.0+20260528.abc1234", "1.2.0", None, "onto.ttl", "ontology"
    )
    ctx["state"] = state


@when(parsers.parse('I record step "{step}" as done'))
def when_record_step_done(ctx: dict, step: str) -> None:
    from ster.publish_state import record_step

    record_step(ctx["tmp_path"], ctx["state"], step, "done")


@when(parsers.parse('I record step "{step}" as failed'))
def when_record_step_failed(ctx: dict, step: str) -> None:
    from ster.publish_state import record_step

    record_step(ctx["tmp_path"], ctx["state"], step, "failed")


@then(parsers.parse('the state file contains step "{step}" with value "{value}"'))
def then_state_step(ctx: dict, step: str, value: str) -> None:
    from ster.publish_state import STATE_FILE

    data = json.loads((ctx["tmp_path"] / STATE_FILE).read_text())
    assert data["steps"][step] == value


@given("a completed publish state")
def given_completed_state(ctx: dict) -> None:
    from ster.publish_state import init_state

    state = init_state(
        ctx["tmp_path"], "stable", "1.2.0+20260528.abc1234", "1.2.0", None, "onto.ttl", "ontology"
    )
    ctx["state"] = state


@given(parsers.parse('a completed stable publish of version "{version}"'))
def given_stable_publish(ctx: dict, version: str) -> None:
    from ster.publish_state import init_state

    state = init_state(
        ctx["tmp_path"], "stable", version, version.split("+")[0], None, "onto.ttl", "ontology"
    )
    ctx["state"] = state


@when("I finalise the state")
def when_finalise(ctx: dict) -> None:
    from ster.publish_state import finalise_state

    finalise_state(ctx["tmp_path"], ctx["state"], commit_sha="abc123")


@then(parsers.parse('"{filename}" does not exist'))
def then_file_not_exist(ctx: dict, filename: str) -> None:
    assert not (ctx["tmp_path"] / filename).exists()


@then(parsers.parse('"{filename}" exists with status "{status}"'))
def then_file_exists_status(ctx: dict, filename: str, status: str) -> None:
    f = ctx["tmp_path"] / filename
    assert f.exists()
    data = json.loads(f.read_text())
    assert data["status"] == status


@then(parsers.parse('"{filename}" contains channel "{channel}"'))
def then_file_contains_channel(ctx: dict, filename: str, channel: str) -> None:
    data = json.loads((ctx["tmp_path"] / filename).read_text())
    assert data["channel"] == channel


@then(parsers.parse('"{filename}" contains version "{version}"'))
def then_file_contains_version(ctx: dict, filename: str, version: str) -> None:
    data = json.loads((ctx["tmp_path"] / filename).read_text())
    assert data["version"] == version


# ── rollback ──────────────────────────────────────────────────────────────────


@given("write_artifacts completed but git_commit failed")
def given_write_failed_at_commit(ctx: dict) -> None:
    from ster.publish_state import init_state, record_step

    t = _minimal_taxonomy()
    src = ctx["tmp_path"] / "onto.ttl"
    _write_ttl(src, t)
    pub = ctx["tmp_path"] / "ontology"
    (pub / "v1.2.0").mkdir(parents=True)
    (pub / "v1.2.0" / "onto.ttl").write_text("artifact")
    ctx["pub"] = pub
    state = init_state(
        ctx["tmp_path"], "stable", "1.2.0+20260528.abc1234", "1.2.0", None, str(src), str(pub)
    )
    record_step(ctx["tmp_path"], state, "write_artifacts", "done")
    record_step(ctx["tmp_path"], state, "git_commit", "failed")
    ctx["state"] = state
    ctx["src"] = src


@given("git_commit completed but git_tag failed")
def given_commit_failed_at_tag(ctx: dict, tmp_path: Path) -> None:
    subprocess.run(["git", "init", str(tmp_path / "repo")], capture_output=True)
    repo = tmp_path / "repo"
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@test.com"], capture_output=True
    )
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], capture_output=True)
    (repo / "file.txt").write_text("initial")
    subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "initial"], capture_output=True)
    (repo / "file.txt").write_text("publish commit")
    subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "release(onto): v1.2.0"], capture_output=True
    )
    r = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True
    )
    commit_sha = r.stdout.strip()

    from ster.publish_state import init_state, record_step

    state = init_state(
        ctx["tmp_path"], "stable", "1.2.0+20260528.abc1234", "1.2.0", None, "onto.ttl", "ontology"
    )
    state["rollback"]["commit_sha"] = commit_sha
    state["rollback"]["repo_dir"] = str(repo)
    record_step(ctx["tmp_path"], state, "git_commit", "done")
    record_step(ctx["tmp_path"], state, "git_tag", "failed")
    ctx["state"] = state
    ctx["repo"] = repo


@when("I roll back")
def when_rollback(ctx: dict) -> None:
    from ster.publish_state import rollback

    rollback(ctx["tmp_path"], ctx["state"])


@then(parsers.parse('the versioned dir "{version_dir}" does not exist'))
def then_versioned_dir_not_exist(ctx: dict, version_dir: str) -> None:
    assert not (ctx["pub"] / version_dir).exists()


@then("git log does not show the publish commit")
def then_git_log_no_commit(ctx: dict) -> None:
    repo = ctx["repo"]
    r = subprocess.run(["git", "-C", str(repo), "log", "--oneline"], capture_output=True, text=True)
    assert "release(onto): v1.2.0" not in r.stdout


# ── detect_state ──────────────────────────────────────────────────────────────


@given(parsers.parse('"{filename}" exists with status "{status}"'))
def given_state_file_exists(ctx: dict, filename: str, status: str) -> None:
    (ctx["tmp_path"] / filename).write_text(
        json.dumps({"status": status, "channel": "stable", "version": "1.2.0", "steps": {}})
    )


@given("no state file exists")
def given_no_state_file(ctx: dict) -> None:
    pass


@when("I detect the publish state")
def when_detect_state(ctx: dict) -> None:
    from ster.publish_state import detect_state

    status, data = detect_state(ctx["tmp_path"])
    ctx["detected_status"] = status
    ctx["detected_data"] = data


@then(parsers.parse('the detected status is "{status}"'))
def then_detected_status(ctx: dict, status: str) -> None:
    assert ctx["detected_status"] == status


# ── resume ────────────────────────────────────────────────────────────────────


@given(
    parsers.parse('a state file with "pre_flight" done and "lint" done and "patch_version" pending')
)
def given_state_with_done_steps(ctx: dict) -> None:
    from ster.publish_state import init_state, record_step

    state = init_state(
        ctx["tmp_path"], "stable", "1.2.0+20260528.abc1234", "1.2.0", None, "onto.ttl", "ontology"
    )
    record_step(ctx["tmp_path"], state, "pre_flight", "done")
    record_step(ctx["tmp_path"], state, "lint", "done")
    ctx["state"] = state


@when("I resume the publish")
def when_resume(ctx: dict) -> None:
    from ster.publish_state import resume_from

    ctx["remaining"] = resume_from(ctx["state"], ["pre_flight", "lint", "patch_version"])


@then(parsers.parse('"{step}" is not re-executed'))
def then_step_not_re_executed(ctx: dict, step: str) -> None:
    assert step not in ctx["remaining"]


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
