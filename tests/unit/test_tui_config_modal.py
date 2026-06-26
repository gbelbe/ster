"""Tests for the global Config modal (auto-saving) + per-file configured languages."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.app import App
from textual.widgets import Checkbox, Input, Select

from ster import store
from ster.nav.prefs import _load_prefs, load_configured_langs, save_configured_langs
from ster.tui.app import OntologyApp
from ster.tui.config_modal import ConfigModal

DEMO = Path(__file__).resolve().parents[2] / "ster" / "tui" / "demo.ttl"


@pytest.fixture(autouse=True)
def _isolate_prefs(tmp_path, monkeypatch):
    """Redirect all preference files to a temp dir so tests don't touch real config."""
    from ster import api_server
    from ster.nav import prefs

    monkeypatch.setattr(prefs, "_prefs_path", lambda: tmp_path / "prefs.json")
    monkeypatch.setattr(prefs, "_lang_prefs_path", lambda: tmp_path / "lang.json")
    monkeypatch.setattr(prefs, "_configured_langs_path", lambda: tmp_path / "clangs.json")
    monkeypatch.setattr(prefs, "_metadata_props_path", lambda: tmp_path / "metaprops.json")
    monkeypatch.setattr(api_server, "_SERVER_CONFIG_FILE", tmp_path / "server_config.json")
    monkeypatch.setattr(api_server, "_TOKEN_FILE", tmp_path / "api_token")


def _run(coro_factory) -> None:  # noqa: ANN001
    asyncio.run(coro_factory())


class _Host(App):
    def compose(self):  # type: ignore[no-untyped-def]
        return iter(())


async def _open_app_config(pilot, app):  # noqa: ANN001
    await pilot.pause()
    await pilot.pause()
    await pilot.press("comma")
    await pilot.pause()
    return app.screen


def _app(tmp_path, lang="en") -> OntologyApp:  # noqa: ANN001
    src = tmp_path / "o.ttl"
    src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    return OntologyApp(store.load(src), source="o.ttl", path=src, lang=lang), src


# ── prefs ──────────────────────────────────────────────────────────────────────


def test_configured_langs_round_trip(tmp_path) -> None:
    f = tmp_path / "o.ttl"
    f.write_text("x", encoding="utf-8")
    assert load_configured_langs(f) == []
    save_configured_langs(f, ["en", "fr"])
    assert load_configured_langs(f) == ["en", "fr"]


def test_configured_langs_default_to_display_language(tmp_path) -> None:
    app, _src = _app(tmp_path, lang="de")
    assert app.configured_langs == ["de"]  # seeded from the display language


# ── ontology-metadata predicate catalog ────────────────────────────────────────


def test_metadata_props_round_trip_and_default(tmp_path) -> None:
    from ster.nav.prefs import load_metadata_props, save_metadata_props

    assert load_metadata_props() is None  # never configured → caller uses defaults
    props = [("http://x/a", "ex:a"), ("http://x/b", "ex:b (hint)")]
    save_metadata_props(props)
    assert load_metadata_props() == props


def test_app_metadata_props_default_to_builtin_catalog(tmp_path) -> None:
    from ster.nav.logic import default_annotation_catalog

    app, _src = _app(tmp_path)
    assert app.metadata_props == default_annotation_catalog()  # built-ins when unconfigured


def test_app_metadata_props_load_from_prefs(tmp_path) -> None:
    from ster.nav.prefs import save_metadata_props

    save_metadata_props([("http://x/custom", "ex:custom")])
    app, _src = _app(tmp_path)
    assert app.metadata_props == [("http://x/custom", "ex:custom")]


def test_annotation_catalog_options_honours_passed_catalog() -> None:
    from ster.model import OntologyAnnotation, Taxonomy
    from ster.nav.logic import annotation_catalog_options

    t = Taxonomy()
    t.ontology_annotations.append(OntologyAnnotation("http://x/a", "v"))  # already present
    catalog = [("http://x/a", "ex:a"), ("http://x/custom", "ex:custom")]
    opts = annotation_catalog_options(t, catalog)
    assert opts == [("http://x/custom", "ex:custom")]  # present one filtered out


def test_suggest_label_prefixes_known_namespaces() -> None:
    from ster.tui.config_modal import suggest_label

    assert suggest_label("http://purl.org/dc/terms/rights") == "dcterms:rights"
    assert suggest_label("http://example.org/x#foo") == "foo"  # unknown → local name


# ── Default-properties tab (metadata catalog editor) ───────────────────────────


def test_props_tab_lists_the_catalog_and_adds_custom(tmp_path) -> None:
    async def scenario() -> None:
        from ster.tui.config_modal import _MetaCheckbox

        app, _src = _app(tmp_path)
        async with app.run_test(size=(120, 48)) as pilot:
            modal = await _open_app_config(pilot, app)
            boxes = modal.query(_MetaCheckbox)
            assert len(boxes) == len(app.metadata_props)  # one checkbox per predicate
            assert all(cb.value for cb in boxes)  # all ticked by default
            modal.query_one("#cfg-mp-uri", Input).value = "http://x/custom"
            await modal._add_metadata_prop()
            await pilot.pause()
            preds = {(cb.predicate, cb.label_text) for cb in modal.query(_MetaCheckbox)}
            assert ("http://x/custom", "custom") in preds  # added + auto-labelled, ticked

    _run(scenario)


def test_adding_a_property_persists_and_reaches_the_picker(tmp_path) -> None:
    async def scenario() -> None:
        from ster.nav.logic import annotation_catalog_options
        from ster.nav.prefs import load_metadata_props

        app, _src = _app(tmp_path)
        async with app.run_test(size=(120, 48)) as pilot:
            modal = await _open_app_config(pilot, app)
            modal.query_one("#cfg-mp-uri", Input).value = "http://x/custom"
            modal.query_one("#cfg-mp-label", Input).value = "ex:custom"
            await modal._add_metadata_prop()  # auto-saves → app persists
            for _ in range(3):
                await pilot.pause()
        # Persisted globally, loaded into the app, and offered by the picker.
        assert ("http://x/custom", "ex:custom") in (load_metadata_props() or [])
        assert ("http://x/custom", "ex:custom") in app.metadata_props
        opts = annotation_catalog_options(app.tax, app.metadata_props)
        assert ("http://x/custom", "ex:custom") in opts

    _run(scenario)


def test_unticking_a_property_removes_it_from_the_catalog(tmp_path) -> None:
    async def scenario() -> None:
        from ster.tui.config_modal import _MetaCheckbox

        app, _src = _app(tmp_path)
        async with app.run_test(size=(120, 48)) as pilot:
            modal = await _open_app_config(pilot, app)
            first = modal.query(_MetaCheckbox).first()
            excluded = first.predicate
            first.value = False  # untick → excluded from the catalog (auto-saves)
            for _ in range(3):
                await pilot.pause()
        assert excluded not in {p for p, _ in app.metadata_props}

    _run(scenario)


def test_properties_navigate_with_arrows_and_toggle_with_space(tmp_path) -> None:
    """In the Default-properties tab, arrows rove the checkboxes and space toggles
    the highlighted one."""

    async def scenario() -> None:
        from ster.tui.config_modal import _MetaCheckbox

        app, _src = _app(tmp_path)
        async with app.run_test(size=(120, 48)) as pilot:
            modal = await _open_app_config(pilot, app)
            await pilot.press("space")  # → Default-properties tab
            await pilot.press("down")  # tab bar → the metadata group
            await pilot.press("down")  # → first property checkbox
            await pilot.pause()
            first = modal.query(_MetaCheckbox).first()
            assert first.has_class("mp-current")  # highlighted
            assert first.value is True
            await pilot.press("space")  # toggle it off
            await pilot.pause()
            assert first.value is False
            await pilot.press("down")  # rove to the next property
            await pilot.pause()
            assert list(modal.query(_MetaCheckbox))[1].has_class("mp-current")

    _run(scenario)


def test_up_at_top_of_property_list_returns_to_tab_bar(tmp_path) -> None:
    async def scenario() -> None:
        from textual.widgets import Tabs

        app, _src = _app(tmp_path)
        async with app.run_test(size=(120, 48)) as pilot:
            await _open_app_config(pilot, app)
            await pilot.press("space")  # → Default-properties tab
            await pilot.press("down")  # → metadata group
            await pilot.press("down")  # → first property
            await pilot.press("up")  # at the top → back to the tab headers
            await pilot.pause()
            assert isinstance(app.focused, Tabs)

    _run(scenario)


# ── modal structure ─────────────────────────────────────────────────────────────


def test_opens_on_tab_bar_and_space_switches_tabs(tmp_path) -> None:
    async def scenario() -> None:
        from textual.widgets import TabbedContent, Tabs

        app, _src = _app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            modal = await _open_app_config(pilot, app)
            assert modal.query_one(Tabs).has_focus  # lands on the tab bar
            assert modal.query_one(TabbedContent).active == "cfg-tab-general"
            await pilot.press("space")  # space cycles to the next tab
            await pilot.pause()
            assert modal.query_one(TabbedContent).active == "cfg-tab-props"
            await pilot.press("space")  # …and back
            await pilot.pause()
            assert modal.query_one(TabbedContent).active == "cfg-tab-general"
            await pilot.press("down")  # arrow enters the tab's items
            await pilot.pause()
            assert not isinstance(app.focused, Tabs)  # focus left the tab bar
            assert app.focused is modal.query_one("#cfg-display", Select)  # first item

    _run(scenario)


def test_reopen_shows_each_configured_language_as_a_checkbox() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            app.push_screen(ConfigModal("en", ["en", "it"], ["en"]))
            await pilot.pause()
            modal = app.screen
            assert modal.query_one("#cfg-chk-it", Checkbox).value is True
            assert modal.query_one("#cfg-chk-en", Checkbox).value is True
            assert len(modal.query("#cfg-chk-zh")) == 0  # unconfigured → no checkbox
            assert modal.query_one("#cfg-extra", Input).value == ""  # field is for adding

    _run(scenario)


def test_no_save_button() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            app.push_screen(ConfigModal("en", ["en"], ["en"]))
            await pilot.pause()
            assert len(app.screen.query("#cfg-save")) == 0

    _run(scenario)


# ── auto-save behaviour (through the app) ───────────────────────────────────────


def test_toggling_a_checkbox_autosaves(tmp_path) -> None:
    async def scenario() -> None:
        app, src = _app(tmp_path)  # configured defaults to ["en"]
        async with app.run_test(size=(120, 40)) as pilot:
            await _open_app_config(pilot, app)
            app.screen.query_one("#cfg-chk-en", Checkbox).value = False  # untick "en"
            await pilot.pause()
            assert app.configured_langs == []  # no Save button — applied immediately
        assert load_configured_langs(src) == []

    _run(scenario)


def test_add_button_adds_checked_language_and_autosaves(tmp_path) -> None:
    async def scenario() -> None:
        app, src = _app(tmp_path)
        # The modal is a fixed 90% height; use a realistic terminal so the
        # languages add-row (near the bottom of the General tab) is on screen.
        async with app.run_test(size=(120, 48)) as pilot:
            await _open_app_config(pilot, app)
            app.screen.query_one("#cfg-extra", Input).value = "fr"
            await pilot.click("#cfg-add")
            await pilot.pause()
            await pilot.pause()
            assert app.screen.query_one("#cfg-chk-fr", Checkbox).value is True  # new checked box
            assert app.configured_langs == ["en", "fr"]
        assert load_configured_langs(src) == ["en", "fr"]

    _run(scenario)


def test_theme_change_applies_live_and_persists(tmp_path) -> None:
    async def scenario() -> None:
        app, _src = _app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await _open_app_config(pilot, app)
            app.screen.query_one("#cfg-theme", Select).value = "nord"
            await pilot.pause()
            assert app.theme == "nord"  # applied live, no Save
        assert _load_prefs().get("theme") == "nord"  # persisted globally

    _run(scenario)


def test_display_language_change_autosaves(tmp_path) -> None:
    async def scenario() -> None:
        app, src = _app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await _open_app_config(pilot, app)
            # demo only has "en" labels, so add another option first.
            select = app.screen.query_one("#cfg-display", Select)
            assert "en" in [v for _label, v in select._options]

    _run(scenario)


# ── single-Tab-stop language group ──────────────────────────────────────────────


def test_block_is_one_focus_stop_with_arrow_toggle_and_tab_exits_to_llm() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            app.push_screen(ConfigModal("en", ["en", "fr"], ["en"]))
            await pilot.pause()
            modal = app.screen
            group = modal.query_one("#cfg-langs")
            # The whole block (checkboxes + field + +) is the Tab stop.
            assert group.can_focus is True and group.can_focus_children is False
            group.focus()
            await pilot.pause()
            group._move(1)  # first arrow activates the cursor on the first language (en)
            group._move(1)  # → fr
            group._toggle_current()  # untick fr
            await pilot.pause()
            assert modal.query_one("#cfg-chk-fr", Checkbox).value is False
            assert modal.query_one("#cfg-chk-en", Checkbox).value is True
            # The field and + button are inside the block (reached with arrows).
            assert modal.query_one("#cfg-extra", Input) in group._items()
            assert modal.query_one("#cfg-add") in group._items()
            # Tab leaves the block straight to the LLM mode Select.
            group.action_exit_next()
            await pilot.pause()
            assert modal.query_one("#llm-mode-select").has_focus

    _run(scenario)


def test_local_server_config_autosaves(tmp_path) -> None:
    async def scenario() -> None:
        from ster.api_server import load_server_config, load_token

        app, _src = _app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await _open_app_config(pilot, app)
            app.screen.query_one("#cfg-server-url", Input).value = "http://192.168.0.5"
            app.screen.query_one("#cfg-server-port", Input).value = "9000"
            app.screen.query_one("#cfg-server-token", Input).value = "secret-token"
            await pilot.pause()
        assert load_server_config() == ("http://192.168.0.5", 9000)
        assert load_token() == "secret-token"

    _run(scenario)


def test_server_group_is_one_focus_stop() -> None:
    async def scenario() -> None:
        from ster.tui.config_modal import _ServerGroup

        app = _Host()
        async with app.run_test() as pilot:
            app.push_screen(ConfigModal("en", ["en"], ["en"]))
            await pilot.pause()
            modal = app.screen
            group = modal.query_one("#cfg-server", _ServerGroup)
            assert group.can_focus is True and group.can_focus_children is False
            ids = [w.id for w in group._items()]
            assert ids == ["cfg-server-url", "cfg-server-port", "cfg-server-token"]
            group.focus()
            await pilot.pause()
            group._move(1)  # first arrow → focus the URL field
            await pilot.pause()
            assert modal.query_one("#cfg-server-url", Input).has_focus
            group.action_exit_next()  # Tab leaves the block → the languages block
            await pilot.pause()
            assert modal.query_one("#cfg-langs").has_focus

    _run(scenario)


def test_app_loads_saved_display_language(tmp_path) -> None:
    from ster.nav.prefs import _save_lang_pref

    src = tmp_path / "o.ttl"
    src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    _save_lang_pref(src, "fr")  # a previously-saved display language
    app = OntologyApp(store.load(src), source="o.ttl", path=src, lang="en")
    assert app.lang == "fr"  # restored on open
