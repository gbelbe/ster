"""Step definitions for changing which file is the working file."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenarios, then, when

from ster import api_server, store
from ster.working_file import WorkingFileError, switch

scenarios("../features/io/working_file.feature")

NS = "https://example.org/t#"
TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

GEAR = f"""\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <{NS}> .
ex:Scheme a skos:ConceptScheme .
ex:Tent a skos:Concept ; skos:prefLabel "Tent"@en ; skos:inScheme ex:Scheme .
"""

PLACES = f"""\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <{NS}> .
ex:PlaceScheme a skos:ConceptScheme .
ex:Alps a skos:Concept ; skos:prefLabel "Alps"@en ; skos:inScheme ex:PlaceScheme .
"""


def uri(name: str) -> str:
    return NS + name


@pytest.fixture
def ctx(tmp_path):
    return {"tmp_path": tmp_path, "pending": None, "refusal": None}


# ── Given ─────────────────────────────────────────────────────────────────────


@given('a gear file defining "Tent"')
def given_gear(ctx):
    path = ctx["tmp_path"] / "gear.ttl"
    path.write_text(GEAR, encoding="utf-8")
    ctx["gear"] = path


@given('a places file defining "Alps"')
def given_places(ctx):
    path = ctx["tmp_path"] / "places.ttl"
    path.write_text(PLACES, encoding="utf-8")
    ctx["places"] = path


@given("both files are open with the gear file as the working file")
def given_open(ctx):
    ctx["editable"] = ctx["gear"]
    ctx["loaded"] = [ctx["gear"], ctx["places"]]
    ctx["tax"] = store.load(ctx["gear"], context=[ctx["places"]])


@given(parsers.parse('"{name}" has been relabelled "{label}" without saving yet'))
def given_pending_edit(ctx, name, label):
    """An edit held in memory, exactly as the editor holds one between its
    debounced background saves."""
    concept = ctx["tax"].concepts[uri(name)]
    concept.labels[0].value = label
    ctx["pending"] = ctx["editable"]


@given("the places file has been deleted from disk")
def given_places_deleted(ctx):
    ctx["places"].unlink()


# ── When ──────────────────────────────────────────────────────────────────────


def _flush(ctx):
    """The editor's ``_flush_save``: persist a pending edit to the file that is
    writable *now*."""

    def flush() -> None:
        if ctx["pending"] is not None:
            store.save(ctx["tax"], ctx["pending"])
            ctx["pending"] = None

    return flush


def _load(ctx):
    def load(editable: Path, context: list[Path]):
        ctx["reloaded"] = True
        return store.load(editable, context=context)

    return load


def _apply(ctx):
    def apply(taxonomy, editable: Path, context: list[Path]) -> None:
        ctx["tax"] = taxonomy
        ctx["editable"] = editable
        ctx["context"] = context
        api_server.publish_working_file(taxonomy, editable, context)

    return apply


def _switch_to(ctx, chosen: Path) -> None:
    ctx["reloaded"] = False
    try:
        ctx["outcome"] = switch(
            chosen,
            current=ctx["editable"],
            loaded=ctx["loaded"],
            flush=_flush(ctx),
            load=_load(ctx),
            apply=_apply(ctx),
        )
    except WorkingFileError as exc:
        ctx["refusal"] = str(exc)


@when("the places file is made the working file")
def when_switch_places(ctx):
    _switch_to(ctx, ctx["places"])


@when("the gear file is made the working file")
def when_switch_gear(ctx):
    _switch_to(ctx, ctx["gear"])


@when(parsers.parse('"{name}" is relabelled "{label}"'))
def when_relabel(ctx, name, label):
    ctx["tax"].concepts[uri(name)].labels[0].value = label


@when("the taxonomy is saved")
def when_save(ctx):
    store.save(ctx["tax"], ctx["editable"])


@when(parsers.parse('the API renames "{name}" to "{label}"'))
def when_api_rename(ctx, name, label):
    response = _api(ctx).post(
        "/api/entity-label",
        json={"uri": uri(name), "lang": "en", "value": label},
        headers=AUTH,
    )
    assert response.status_code == 200, response.text


# ── the API harness ───────────────────────────────────────────────────────────


def _api(ctx) -> TestClient:
    """A server publishing this session, kept in step with every switch."""
    if "client" not in ctx:
        from ster.api import SSEBroadcaster, create_app

        def save_fn(tax) -> None:
            target = app.state._ster["file_path"]
            if target is not None:
                store.save(tax, target)

        app = create_app(
            ctx["tax"],
            TOKEN,
            SSEBroadcaster(),
            save_fn,
            file_path=ctx["editable"],
            context=[p for p in ctx["loaded"] if p != ctx["editable"]],
        )
        app.state._ster["broadcaster"] = SSEBroadcaster()
        api_server._bg.app = app
        api_server._bg.broadcaster = app.state._ster["broadcaster"]
        api_server._bg.loop = None
        ctx["app"] = app
        ctx["client"] = TestClient(app)
        # A switch that already happened has to reach a server started after it.
        api_server.publish_working_file(ctx["tax"], ctx["editable"], ctx.get("context", []))
    return ctx["client"]


# ── Then ──────────────────────────────────────────────────────────────────────


@then(parsers.parse('"{name}" is editable'))
def then_editable(ctx, name):
    assert store.is_editable(ctx["tax"], uri(name))


@then(parsers.parse('"{name}" is still editable'))
def then_still_editable(ctx, name):
    assert store.is_editable(ctx["tax"], uri(name))


@then(parsers.parse('"{name}" is read-only'))
def then_read_only(ctx, name):
    assert not store.is_editable(ctx["tax"], uri(name))


@then(parsers.parse('"{name}" reports the gear file as its source'))
def then_source_is_gear(ctx, name):
    assert ctx["tax"].context_source[uri(name)] == ctx["gear"]


@then(parsers.parse('both "{first}" and "{second}" are in the taxonomy'))
def then_both_present(ctx, first, second):
    assert uri(first) in ctx["tax"].concepts
    assert uri(second) in ctx["tax"].concepts


@then(parsers.parse('the places file defines "{label}"'))
def then_places_defines(ctx, label):
    assert label in ctx["places"].read_text(encoding="utf-8")


@then(parsers.parse('the places file does not define "{label}"'))
def then_places_lacks(ctx, label):
    assert label not in ctx["places"].read_text(encoding="utf-8")


@then(parsers.parse('the gear file defines "{label}"'))
def then_gear_defines(ctx, label):
    assert label in ctx["gear"].read_text(encoding="utf-8")


@then("the gear file is unchanged")
def then_gear_unchanged(ctx):
    assert "Tent" in ctx["gear"].read_text(encoding="utf-8")
    assert "Alpes" not in ctx["gear"].read_text(encoding="utf-8")


@then("the taxonomy is not reloaded")
def then_not_reloaded(ctx):
    assert ctx["outcome"].reloaded is False
    assert ctx["reloaded"] is False


@then(parsers.parse('the API refuses to write to "{name}"'))
def then_api_refuses(ctx, name):
    response = _api(ctx).post(
        "/api/entity-label",
        json={"uri": uri(name), "lang": "en", "value": "nope"},
        headers=AUTH,
    )
    assert response.status_code == 409


@then(parsers.parse('the API accepts a write to "{name}"'))
def then_api_accepts(ctx, name):
    response = _api(ctx).post(
        "/api/entity-label",
        json={"uri": uri(name), "lang": "en", "value": "Alpes"},
        headers=AUTH,
    )
    assert response.status_code == 200, response.text


@then("the switch is refused with a message naming the places file")
def then_refused(ctx):
    assert ctx["refusal"] is not None
    assert "places.ttl" in ctx["refusal"]


@pytest.fixture(autouse=True)
def _reset_background_server():
    yield
    api_server._bg.reset()
