"""BDD step definitions for live-refresh SSE scenarios."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, scenarios, then, when

from ster.api import SSEBroadcaster

scenarios("../features/api/live_refresh.feature")

NS = "https://example.org/onto#"
TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _make_app(bc=None):
    from ster.api import SSEBroadcaster, create_app
    from ster.model import Label, LabelType, RDFClass, Taxonomy

    t = Taxonomy()
    t.namespace_bindings[""] = NS
    for name in ("Animal", "Dog"):
        t.owl_classes[NS + name] = RDFClass(
            uri=NS + name,
            labels=[Label(lang="en", value=name, type=LabelType.PREF)],
        )
    if bc is None:
        bc = SSEBroadcaster()
    app = create_app(t, TOKEN, bc, lambda _: None)
    return app, bc


@pytest.fixture
def ctx():
    app, bc = _make_app()
    return {"client": TestClient(app), "broadcaster": bc, "response": None}


# ── Given ─────────────────────────────────────────────────────────────────────


@given("the API server is running with the Animal/Dog/Tool ontology")
def given_server(ctx):
    pass  # handled by fixture


@given("a broadcaster spy is active", target_fixture="ctx")
def given_broadcaster_spy():
    import asyncio

    bc = SSEBroadcaster()
    q: asyncio.Queue = asyncio.Queue()
    bc._queues.append(q)
    app, _ = _make_app(bc=bc)
    return {"client": TestClient(app), "broadcaster": bc, "spy_queue": q, "response": None}


@given("an SSE broadcaster with one connected listener")
def given_broadcaster_listener(ctx):
    ctx["received"] = []

    async def _collect():
        async for chunk in ctx["broadcaster"].subscribe():
            ctx["received"].append(chunk)
            return

    ctx["_collect_coro"] = _collect


# ── When ──────────────────────────────────────────────────────────────────────


@when("I GET /api/graph")
def when_get_graph(ctx):
    ctx["response"] = ctx["client"].get("/api/graph", headers=AUTH)


@when("I GET /api/events with the token as query param")
def when_get_events(ctx):
    from unittest.mock import patch

    async def _one_shot():
        yield 'data: {"type": "test"}\n\n'

    with patch.object(SSEBroadcaster, "subscribe", return_value=_one_shot()):
        ctx["response"] = ctx["client"].get(f"/api/events?token={TOKEN}")


@when("the broadcaster is notified of a change")
def when_broadcaster_notified(ctx):
    async def _run():
        task = asyncio.create_task(ctx["_collect_coro"]())
        await asyncio.sleep(0.01)
        await ctx["broadcaster"]._broadcast()
        await asyncio.wait_for(task, timeout=2.0)

    asyncio.run(_run())


# ── Then ──────────────────────────────────────────────────────────────────────


@then("the response status is 200")
def then_200(ctx):
    assert ctx["response"].status_code == 200


@then('the response contains a "nodes" list')
def then_has_nodes(ctx):
    assert "nodes" in ctx["response"].json()


@then('the response contains an "edges" list')
def then_has_edges(ctx):
    assert "edges" in ctx["response"].json()


@then('the Content-Type header contains "text/event-stream"')
def then_sse_content_type(ctx):
    assert "text/event-stream" in ctx["response"].headers["content-type"]


@then('the listener receives an "updated" event')
def then_listener_updated(ctx):
    assert any('"updated"' in chunk for chunk in ctx["received"])


@when('I POST /api/individuals with class "Dog" and label "Fido"')
def when_post_fido(ctx):
    ctx["response"] = ctx["client"].post(
        "/api/individuals",
        json={"class_uri": NS + "Dog", "labels": [{"lang": "en", "value": "Fido"}]},
        headers=AUTH,
    )


@then("the broadcaster was notified once")
def then_broadcaster_notified_once(ctx):
    q = ctx["spy_queue"]
    assert not q.empty()
    assert q.get_nowait() == "updated"
