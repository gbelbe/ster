"""Moving between entities stays responsive: the overview's coverage is remembered, the detail panel waits for
a held arrow key to stop, and a move that stays in the same layer touches no class.

Each remembered thing must also *not* go stale, so every cache here has a test that changes what it depends on.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from ster import store
from ster.metadata_coverage import MetaProp
from ster.model import Taxonomy
from ster.tui.app import OntologyApp
from ster.tui.app._detail import DETAIL_SETTLE_S

from .test_app_create_reveal import (  # noqa: F401 - the fixture is used by name
    DEMO,
    ZOO,
    _isolate_prefs,
)

COMPUTED_TWICE = 2  # the first answer, and the one after what it depends on changed
SWEEP_MOVES = 4  # entities crossed while a key is held down


def _app(tmp_path: Path) -> OntologyApp:
    src = tmp_path / "o.ttl"
    src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    return OntologyApp(store.load(src), source="o.ttl", path=src)


# ------------------------------------------------------------------ the coverage is remembered, never stale


def _counting(monkeypatch) -> list[int]:
    import ster.metadata_coverage as coverage

    calls: list[int] = []
    real = coverage.overview_coverage

    def counted(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(coverage, "overview_coverage", counted)
    return calls


def test_the_coverage_is_computed_once_while_nothing_changes(tmp_path, monkeypatch):
    calls = _counting(monkeypatch)
    app = _app(tmp_path)
    first = app._metadata_coverage()
    assert app._metadata_coverage() is first
    assert len(calls) == 1


def test_an_invalidation_makes_it_recompute(tmp_path, monkeypatch):
    calls = _counting(monkeypatch)
    app = _app(tmp_path)
    app._metadata_coverage()
    app._invalidate_lint()  # called after every edit, reload and settings change
    app._metadata_coverage()
    assert len(calls) == COMPUTED_TWICE


def test_a_new_taxonomy_makes_it_recompute(tmp_path, monkeypatch):
    """An edit or a reload swaps in a new taxonomy object: the old answer is about another model."""
    calls = _counting(monkeypatch)
    app = _app(tmp_path)
    app._metadata_coverage()
    app.tax = store.load(tmp_path / "o.ttl")  # same content, new object
    app._metadata_coverage()
    assert len(calls) == COMPUTED_TWICE


def test_other_catalogs_make_it_recompute(tmp_path, monkeypatch):
    calls = _counting(monkeypatch)
    app = _app(tmp_path)
    app._metadata_coverage()
    app.entity_metadata_props = [MetaProp("http://purl.org/dc/terms/creator", "creator")]
    app._metadata_coverage()
    assert len(calls) == COMPUTED_TWICE


def test_an_entity_added_in_place_makes_it_recompute(tmp_path, monkeypatch):
    from ster.model import RDFClass

    calls = _counting(monkeypatch)
    app = _app(tmp_path)
    app._metadata_coverage()
    app.tax.owl_classes[ZOO + "Extra"] = RDFClass(uri=ZOO + "Extra")
    app._metadata_coverage()
    assert len(calls) == COMPUTED_TWICE


def test_the_remembered_answer_is_the_one_a_fresh_computation_gives(tmp_path):
    from ster.metadata_coverage import overview_coverage

    app = _app(tmp_path)
    app._metadata_coverage()
    assert app._metadata_coverage() == overview_coverage(
        app.tax, app.metadata_props, app.entity_metadata_props
    )


# ------------------------------------------------------------------ the detail panel waits for a sweep to end


def _spy_show(app: OntologyApp) -> list[str | None]:
    shown: list[str | None] = []
    real = app._show

    def spy(uri):
        shown.append(uri)
        return real(uri)

    app._show = spy  # type: ignore[method-assign]
    return shown


def test_a_slow_move_draws_its_panel_at_once(tmp_path):
    app = _app(tmp_path)

    async def scenario():
        async with app.run_test(size=(120, 44)) as pilot:
            await pilot.pause()
            app.query("OntologyTree").first().focus()
            await pilot.pause()
            shown = _spy_show(app)
            await pilot.press("down")
            await pilot.pause()
            return shown, app._pending_show

    shown, pending = asyncio.run(scenario())
    assert len(shown) == 1  # drawn on the move, nothing waiting
    assert pending is None


def test_a_sweep_draws_one_panel_where_it_stops(tmp_path, settle):
    app = _app(tmp_path)

    async def scenario():
        async with app.run_test(size=(120, 44)) as pilot:
            await pilot.pause()
            tree = app.query("OntologyTree").first()
            tree.focus()
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()
            shown = _spy_show(app)
            for _ in range(4):  # a key held down: the moves arrive faster than a panel can be built
                tree.action_cursor_down()
            await pilot.pause()
            during = (list(shown), app._detail_uri)  # the selection already moved; the panel waits
            assert await settle(pilot, lambda: app._pending_show is None)
            return during, shown, app._detail_uri

    (during_shown, during_uri), shown, final_uri = asyncio.run(scenario())
    assert len(shown) < SWEEP_MOVES  # not one build per entity crossed
    assert shown[-1] == final_uri  # and the last one is where the cursor rests
    assert (
        during_uri == final_uri
    )  # the selection had already arrived when the panel was still waiting
    assert [
        u for u in during_shown if u is not None
    ] == []  # and no entity panel had been built yet


def test_an_explicit_show_cancels_a_waiting_one(tmp_path):
    app = _app(tmp_path)

    async def scenario():
        async with app.run_test(size=(120, 44)) as pilot:
            await pilot.pause()
            app._defer_show(ZOO + "Dog")
            assert app._pending_show == (ZOO + "Dog",)
            app._show(ZOO + "Cat")
            await pilot.pause(DETAIL_SETTLE_S * 3)
            return app._pending_show, app._detail_uri

    pending, uri = asyncio.run(scenario())
    assert pending is None
    assert uri == ZOO + "Cat"  # the earlier wait did not overwrite the later choice


def test_the_selection_moves_at_once_even_while_the_panel_waits(tmp_path):
    app = _app(tmp_path)

    async def scenario():
        async with app.run_test(size=(120, 44)) as pilot:
            await pilot.pause()
            app._defer_show(ZOO + "Dog")
            return app._detail_uri

    assert asyncio.run(scenario()) == ZOO + "Dog"


from ster.tui.app._constants import _DETAIL_SELECTOR  # noqa: E402


def test_a_wait_that_outlives_the_screen_draws_nothing_and_does_not_raise(tmp_path):
    app = _app(tmp_path)

    async def scenario():
        async with app.run_test(size=(120, 44)) as pilot:
            await pilot.pause()
            await app.query_one(_DETAIL_SELECTOR).remove()  # what a closing app leaves behind
            app._pending_show = (ZOO + "Dog",)
            app._flush_show()
            return app._pending_show

    assert asyncio.run(scenario()) is None


# ------------------------------------------------------------------ a move within a layer changes no class


def test_a_move_that_stays_in_one_layer_does_not_touch_the_class_or_the_hint(tmp_path):
    app = _app(tmp_path)

    async def scenario():
        async with app.run_test(size=(120, 44)) as pilot:
            await pilot.pause()
            tree = app.query("OntologyTree").first()
            tree.focus()
            await pilot.pause()
            await pilot.press("down", "down")
            await pilot.pause()
            hints = []
            real = app._update_nav_hint
            app._update_nav_hint = lambda: (hints.append(1), real())[1]  # type: ignore[method-assign]
            tree._sync_panel_layer_class()  # nothing changed since the last sync
            return hints

    assert asyncio.run(scenario()) == []


def test_a_change_of_layer_still_updates_the_hint(tmp_path):
    app = _app(tmp_path)

    async def scenario():
        async with app.run_test(size=(120, 44)) as pilot:
            await pilot.pause()
            tree = app.query("OntologyTree").first()
            tree.focus()
            await pilot.pause()
            had = tree.has_class("panel-layer")
            hints = []
            real = app._update_nav_hint
            app._update_nav_hint = lambda: (hints.append(1), real())[1]  # type: ignore[method-assign]
            tree.set_class(not had, "panel-layer")  # as if the layer had just changed
            tree._sync_panel_layer_class()
            return had, tree.has_class("panel-layer"), hints

    had, now, hints = asyncio.run(scenario())
    assert now == had  # put back to what the cursor says
    assert hints == [1]  # and the hint followed


def test_an_empty_taxonomy_still_has_a_coverage(tmp_path):
    app = OntologyApp(Taxonomy(), source="x.ttl")
    assert app._metadata_coverage() is not None
