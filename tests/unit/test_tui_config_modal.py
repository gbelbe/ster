"""Tests for the global Config modal (auto-saving) + per-file configured languages."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.app import App
from textual.widgets import Button, Checkbox, Input, Select

from ster import store
from ster.metadata_coverage import MetaProp
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
    monkeypatch.setattr(
        prefs, "_entity_metadata_props_path", lambda: tmp_path / "entity_metaprops.json"
    )
    monkeypatch.setattr(api_server, "_SERVER_CONFIG_FILE", tmp_path / "server_config.json")
    monkeypatch.setattr(api_server, "_TOKEN_FILE", tmp_path / "api_token")
    from ster.plugins.semanticlint import config as sl_config

    monkeypatch.setattr(sl_config, "_config_path", lambda: tmp_path / "quality.json")


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
    props = [MetaProp("http://x/a", "ex:a"), MetaProp("http://x/b", "ex:b (hint)")]
    save_metadata_props(props)
    assert load_metadata_props() == props


def test_app_metadata_props_default_to_builtin_catalog(tmp_path) -> None:
    from ster.nav.logic import default_annotation_catalog

    app, _src = _app(tmp_path)
    assert app.metadata_props == default_annotation_catalog()  # built-ins when unconfigured


def test_app_metadata_props_load_from_prefs(tmp_path) -> None:
    from ster.nav.prefs import save_metadata_props

    save_metadata_props([MetaProp("http://x/custom", "ex:custom")])
    app, _src = _app(tmp_path)
    assert app.metadata_props == [MetaProp("http://x/custom", "ex:custom")]


def test_annotation_catalog_options_honours_passed_catalog() -> None:
    from ster.model import OntologyAnnotation, Taxonomy
    from ster.nav.logic import annotation_catalog_options

    t = Taxonomy()
    t.ontology_annotations.append(OntologyAnnotation("http://x/a", "v"))  # already present
    catalog = [MetaProp("http://x/a", "ex:a"), MetaProp("http://x/custom", "ex:custom")]
    opts = annotation_catalog_options(t, catalog)
    assert opts == [("http://x/custom", "ex:custom")]  # present one filtered out


def test_suggest_label_prefixes_known_namespaces() -> None:
    from ster.tui.config_modal import suggest_label

    assert suggest_label("http://purl.org/dc/terms/rights") == "dcterms:rights"
    assert suggest_label("http://example.org/x#foo") == "foo"  # unknown → local name


# ── Default-properties tab (metadata catalog editor) ───────────────────────────


def _ont_catalog(modal):  # noqa: ANN001 - test helper
    from ster.tui.config_modal import _MetaCatalog

    return modal.query_one("#cfg-ont-meta", _MetaCatalog)


def _entity_catalog(modal):  # noqa: ANN001 - test helper
    from ster.tui.config_modal import _MetaCatalog

    return modal.query_one("#cfg-entity-meta", _MetaCatalog)


def _headers(modal):  # noqa: ANN001 - test helper
    """The two collapsible group headers, in DOM order [Ontology, Entity]."""
    from textual.widgets._collapsible import CollapsibleTitle

    return list(modal.query(CollapsibleTitle))


def test_props_tab_lists_the_catalog_and_adds_custom(tmp_path) -> None:
    async def scenario() -> None:
        from ster.tui.config_modal import _MetaCheckbox

        app, _src = _app(tmp_path)
        async with app.run_test(size=(120, 48)) as pilot:
            modal = await _open_app_config(pilot, app)
            catalog = _ont_catalog(modal)
            boxes = catalog.query(_MetaCheckbox)
            assert len(boxes) == len(app.metadata_props)  # one checkbox per predicate
            assert all(cb.value for cb in boxes)  # all ticked by default
            catalog.query_one(".cfg-mp-uri", Input).value = "http://x/custom"
            await catalog.add_typed()
            await pilot.pause()
            preds = {(cb.predicate, cb.label_text) for cb in catalog.query(_MetaCheckbox)}
            assert ("http://x/custom", "custom") in preds  # added + auto-labelled, ticked

    _run(scenario)


def test_adding_a_property_persists_and_reaches_the_picker(tmp_path) -> None:
    async def scenario() -> None:
        from ster.nav.logic import annotation_catalog_options
        from ster.nav.prefs import load_metadata_props

        app, _src = _app(tmp_path)
        async with app.run_test(size=(120, 48)) as pilot:
            modal = await _open_app_config(pilot, app)
            catalog = _ont_catalog(modal)
            catalog.query_one(".cfg-mp-uri", Input).value = "http://x/custom"
            catalog.query_one(".cfg-mp-label", Input).value = "ex:custom"
            await catalog.add_typed()  # auto-saves → app persists
            for _ in range(3):
                await pilot.pause()
        # Persisted globally, loaded into the app, and offered by the picker.
        assert MetaProp("http://x/custom", "ex:custom") in (load_metadata_props() or [])
        assert MetaProp("http://x/custom", "ex:custom") in app.metadata_props
        opts = annotation_catalog_options(app.tax, app.metadata_props)
        assert ("http://x/custom", "ex:custom") in opts

    _run(scenario)


def test_unticking_a_property_removes_it_from_the_catalog(tmp_path) -> None:
    async def scenario() -> None:
        from ster.tui.config_modal import _MetaCheckbox

        app, _src = _app(tmp_path)
        async with app.run_test(size=(120, 48)) as pilot:
            modal = await _open_app_config(pilot, app)
            first = _ont_catalog(modal).query(_MetaCheckbox).first()
            excluded = first.predicate
            first.value = False  # untick → excluded from the catalog (auto-saves)
            for _ in range(3):
                await pilot.pause()
        assert excluded not in {mp.predicate for mp in app.metadata_props}

    _run(scenario)


def test_item_list_roves_with_arrows_and_space_toggles(tmp_path) -> None:
    """After entering a group with Right, Up/Down rove the checkboxes and Space
    toggles the highlighted one."""

    async def scenario() -> None:
        from ster.tui.config_modal import _MetaCheckbox

        app, _src = _app(tmp_path)
        async with app.run_test(size=(120, 48)) as pilot:
            modal = await _open_app_config(pilot, app)
            catalog = _ont_catalog(modal)
            _headers(modal)[0].focus()  # land on the Ontology group header
            await pilot.pause()
            await pilot.press("right")  # drill into the item list → first checkbox
            await pilot.pause()
            first = catalog.query(_MetaCheckbox).first()
            assert first.has_class("mp-current")  # highlighted
            assert first.value is True
            await pilot.press("space")  # toggle it off
            await pilot.pause()
            assert first.value is False
            await pilot.press("down")  # rove to the next property
            await pilot.pause()
            assert list(catalog.query(_MetaCheckbox))[1].has_class("mp-current")

    _run(scenario)


def test_up_at_top_of_item_list_returns_to_its_header(tmp_path) -> None:
    async def scenario() -> None:
        app, _src = _app(tmp_path)
        async with app.run_test(size=(120, 48)) as pilot:
            modal = await _open_app_config(pilot, app)
            _headers(modal)[0].focus()
            await pilot.pause()
            await pilot.press("right")  # → first item
            await pilot.press("up")  # at the top → back to the group header
            await pilot.pause()
            assert app.focused is _headers(modal)[0]

    _run(scenario)


def test_left_in_item_list_returns_to_its_header(tmp_path) -> None:
    async def scenario() -> None:
        app, _src = _app(tmp_path)
        async with app.run_test(size=(120, 48)) as pilot:
            modal = await _open_app_config(pilot, app)
            _headers(modal)[0].focus()
            await pilot.pause()
            await pilot.press("right")  # → into the item list
            await pilot.press("left")  # back out to the group header
            await pilot.pause()
            assert app.focused is _headers(modal)[0]

    _run(scenario)


# ── entity-metadata catalog (second group) ─────────────────────────────────────


def test_entity_metadata_props_round_trip_and_default(tmp_path) -> None:
    from ster.nav.prefs import load_entity_metadata_props, save_entity_metadata_props

    assert load_entity_metadata_props() is None  # never configured → caller uses defaults
    props = [MetaProp("http://x/e1", "ex:e1"), MetaProp("http://x/e2", "ex:e2")]
    save_entity_metadata_props(props)
    assert load_entity_metadata_props() == props
    # The two catalogs are stored independently — saving entity props leaves the
    # ontology catalog untouched.
    from ster.nav.prefs import load_metadata_props

    assert load_metadata_props() is None


def test_app_entity_metadata_props_default_to_builtin_catalog(tmp_path) -> None:
    from ster.nav.logic import default_entity_annotation_catalog

    app, _src = _app(tmp_path)
    assert app.entity_metadata_props == default_entity_annotation_catalog()


def test_app_entity_metadata_props_load_from_prefs(tmp_path) -> None:
    from ster.nav.prefs import save_entity_metadata_props

    save_entity_metadata_props([MetaProp("http://x/custom", "ex:custom")])
    app, _src = _app(tmp_path)
    assert app.entity_metadata_props == [MetaProp("http://x/custom", "ex:custom")]


def test_annotation_tab_renamed_and_has_two_foldable_groups(tmp_path) -> None:
    """The tab is "Annotation properties" and holds two collapsible groups —
    Ontology Metadata and Entity metadata — each its own catalog editor."""

    async def scenario() -> None:
        from textual.widgets import Collapsible, TabbedContent

        from ster.tui.config_modal import _MetaCatalog

        app, _src = _app(tmp_path)
        async with app.run_test(size=(120, 48)) as pilot:
            modal = await _open_app_config(pilot, app)
            pane = modal.query_one(TabbedContent).get_pane("cfg-tab-props")
            assert str(pane._title) == "Annotation properties"
            titles = {c.title for c in modal.query(Collapsible)}
            assert {"Ontology Metadata", "Entity metadata"} <= titles
            # Two independent catalog editors, each with its own add row.
            assert len(modal.query(_MetaCatalog)) == 2
            assert _ont_catalog(modal).query_one(".cfg-mp-uri")
            assert _entity_catalog(modal).query_one(".cfg-mp-uri")

    _run(scenario)


def test_adding_to_entity_group_persists_to_entity_catalog_only(tmp_path) -> None:
    """A predicate added in the Entity group lands in the entity catalog and is
    saved there — the ontology catalog is left unchanged (and vice-versa)."""

    async def scenario() -> None:
        from ster.nav.prefs import load_entity_metadata_props, load_metadata_props

        app, _src = _app(tmp_path)
        async with app.run_test(size=(120, 48)) as pilot:
            modal = await _open_app_config(pilot, app)
            entity = _entity_catalog(modal)
            entity.query_one(".cfg-mp-uri", Input).value = "http://x/entity-only"
            entity.query_one(".cfg-mp-label", Input).value = "ex:entityOnly"
            await entity.add_typed()
            for _ in range(3):
                await pilot.pause()
        # Saved to the entity catalog + app state, absent from the ontology one.
        assert MetaProp("http://x/entity-only", "ex:entityOnly") in app.entity_metadata_props
        assert MetaProp("http://x/entity-only", "ex:entityOnly") in (
            load_entity_metadata_props() or []
        )
        assert "http://x/entity-only" not in {mp.predicate for mp in app.metadata_props}
        assert "http://x/entity-only" not in {mp.predicate for mp in (load_metadata_props() or [])}

    _run(scenario)


def test_unticking_in_entity_group_drops_from_entity_catalog_only(tmp_path) -> None:
    async def scenario() -> None:
        from ster.tui.config_modal import _MetaCheckbox

        app, _src = _app(tmp_path)
        async with app.run_test(size=(120, 48)) as pilot:
            modal = await _open_app_config(pilot, app)
            first = _entity_catalog(modal).query(_MetaCheckbox).first()
            excluded = first.predicate
            first.value = False  # untick in the entity group → drops from entity catalog
            for _ in range(3):
                await pilot.pause()
        from ster.nav.logic import default_annotation_catalog

        assert excluded not in {mp.predicate for mp in app.entity_metadata_props}
        assert app.metadata_props == default_annotation_catalog()  # ontology catalog untouched

    _run(scenario)


def test_down_on_header_moves_to_the_next_group(tmp_path) -> None:
    """On a group header, Down moves to the next group's header."""

    async def scenario() -> None:
        app, _src = _app(tmp_path)
        async with app.run_test(size=(120, 48)) as pilot:
            modal = await _open_app_config(pilot, app)
            headers = _headers(modal)
            headers[0].focus()
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()
            assert app.focused is headers[1]

    _run(scenario)


def test_up_on_header_moves_to_the_previous_group(tmp_path) -> None:
    """On a group header, Up moves back to the previous group's header."""

    async def scenario() -> None:
        app, _src = _app(tmp_path)
        async with app.run_test(size=(120, 48)) as pilot:
            modal = await _open_app_config(pilot, app)
            headers = _headers(modal)
            headers[1].focus()
            await pilot.pause()
            await pilot.press("up")
            await pilot.pause()
            assert app.focused is headers[0]

    _run(scenario)


def test_up_on_first_header_returns_to_the_tab_bar(tmp_path) -> None:
    async def scenario() -> None:
        from textual.widgets import Tabs

        app, _src = _app(tmp_path)
        async with app.run_test(size=(120, 48)) as pilot:
            modal = await _open_app_config(pilot, app)
            _headers(modal)[0].focus()
            await pilot.pause()
            await pilot.press("up")  # at the first group → back to the tab bar
            await pilot.pause()
            assert isinstance(app.focused, Tabs)

    _run(scenario)


def test_right_on_header_enters_the_item_list(tmp_path) -> None:
    """On a group header, Right drills into that group's item list (first item)."""

    async def scenario() -> None:
        from ster.tui.config_modal import _MetaCheckbox

        app, _src = _app(tmp_path)
        async with app.run_test(size=(120, 48)) as pilot:
            modal = await _open_app_config(pilot, app)
            catalog = _entity_catalog(modal)
            _headers(modal)[1].focus()  # Entity group header
            await pilot.pause()
            await pilot.press("right")
            await pilot.pause()
            assert app.focused is catalog
            assert catalog.current_item() is catalog.query(_MetaCheckbox).first()

    _run(scenario)


def test_down_on_last_item_moves_to_the_next_group(tmp_path) -> None:
    """Down on the last item (the ＋ button) of a group moves to the next group's header."""

    async def scenario() -> None:
        app, _src = _app(tmp_path)
        async with app.run_test(size=(120, 48)) as pilot:
            modal = await _open_app_config(pilot, app)
            ont, headers = _ont_catalog(modal), _headers(modal)
            headers[0].focus()
            await pilot.pause()
            await pilot.press("right")  # enter the Ontology group's items
            await pilot.pause()
            ont._cursor = len(ont._items()) - 1  # jump the cursor onto the ＋ button
            await pilot.press("down")  # past the bottom → the next group
            await pilot.pause()
            assert app.focused is headers[1]  # Entity group header

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
            await pilot.press("space")  # → Plugins tab
            await pilot.pause()
            assert modal.query_one(TabbedContent).active == "cfg-tab-plugins"
            await pilot.press("space")  # …and wrap back to General
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


# ── annotation-property verification on add ────────────────────────────────────


def test_known_annotation_predicate_is_added_without_warning(tmp_path) -> None:
    """Typing a well-known annotation predicate adds it straight away — no warning."""

    async def scenario() -> None:
        from ster.tui.choice_modal import ChoiceModal
        from ster.tui.config_modal import _MetaCheckbox

        app, _src = _app(tmp_path)
        async with app.run_test(size=(120, 48)) as pilot:
            modal = await _open_app_config(pilot, app)
            catalog = _entity_catalog(modal)
            uri = "http://xmlns.com/foaf/0.1/depiction"  # well-known annotation prop
            catalog.query_one(".cfg-mp-uri", Input).value = uri
            await catalog._submit()
            await pilot.pause()
            assert not isinstance(app.screen, ChoiceModal)  # no confirmation needed
            assert uri in {cb.predicate for cb in catalog.query(_MetaCheckbox)}

    _run(scenario)


def test_unknown_predicate_warns_then_confirm_adds_and_declares(tmp_path) -> None:
    """An unknown predicate triggers a confirmation modal; confirming adds it to the
    catalog AND declares it locally as an owl:AnnotationProperty (persisted)."""

    async def scenario() -> None:
        from ster.tui.choice_modal import ChoiceModal
        from ster.tui.config_modal import _MetaCheckbox

        app, src = _app(tmp_path)
        async with app.run_test(size=(120, 48)) as pilot:
            modal = await _open_app_config(pilot, app)
            catalog = _entity_catalog(modal)
            uri = "https://example.org/onto#myAnno"
            catalog.query_one(".cfg-mp-uri", Input).value = uri
            await catalog._submit()
            await pilot.pause()
            assert isinstance(app.screen, ChoiceModal)  # warning shown
            app.screen.dismiss("use")  # confirm
            for _ in range(5):
                await pilot.pause()
            assert uri in {cb.predicate for cb in catalog.query(_MetaCheckbox)}  # added
            prop = app.tax.owl_properties.get(uri)  # declared locally...
            assert prop is not None and prop.prop_type == "AnnotationProperty"
        assert uri in store.load(src).owl_properties  # ...and persisted to disk

    _run(scenario)


def test_unknown_predicate_cancel_does_not_add(tmp_path) -> None:
    """Cancelling the warning leaves the catalog and ontology untouched."""

    async def scenario() -> None:
        from ster.tui.choice_modal import ChoiceModal
        from ster.tui.config_modal import _MetaCheckbox

        app, _src = _app(tmp_path)
        async with app.run_test(size=(120, 48)) as pilot:
            modal = await _open_app_config(pilot, app)
            catalog = _entity_catalog(modal)
            uri = "https://example.org/onto#nope"
            catalog.query_one(".cfg-mp-uri", Input).value = uri
            await catalog._submit()
            await pilot.pause()
            assert isinstance(app.screen, ChoiceModal)
            app.screen.dismiss(None)  # Escape / Cancel
            for _ in range(4):
                await pilot.pause()
            assert uri not in {cb.predicate for cb in catalog.query(_MetaCheckbox)}
            assert uri not in app.tax.owl_properties

    _run(scenario)


# ── new local annotation property (button → create modal) ──────────────────────

_BASE = "https://example.org/zoo/"  # demo.ttl base IRI


def test_each_group_offers_an_add_local_annotation_property_button(tmp_path) -> None:
    """Both groups expose a single 'Add local annotation property' button wired to
    the ontology base IRI — and no inline create fields."""

    async def scenario() -> None:
        app, _src = _app(tmp_path)
        async with app.run_test(size=(120, 48)) as pilot:
            modal = await _open_app_config(pilot, app)
            for catalog in (_ont_catalog(modal), _entity_catalog(modal)):
                btn = catalog.query_one(".cfg-mp-new", Button)
                assert "Add local annotation property" in str(btn.label)
                assert catalog._base_uri == _BASE  # wired to the base IRI
                assert not catalog.query(".cfg-mp-new-name")  # no inline form fields

    _run(scenario)


def test_add_local_button_opens_the_creation_modal(tmp_path) -> None:
    """Pressing the button opens the (placeholder) property-creation modal."""

    async def scenario() -> None:
        from ster.tui.local_property_modal import LocalPropertyModal

        app, _src = _app(tmp_path)
        async with app.run_test(size=(120, 48)) as pilot:
            modal = await _open_app_config(pilot, app)
            catalog = _entity_catalog(modal)
            btn = catalog.query_one(".cfg-mp-new", Button)
            await catalog._on_new(Button.Pressed(btn))  # press the button
            await pilot.pause()
            assert isinstance(app.screen, LocalPropertyModal)
            assert app.screen._base_uri == _BASE  # modal told the fixed prefix

    _run(scenario)


def test_modal_result_declares_in_ttl_and_ticks_into_group(tmp_path) -> None:
    """A confirmed create result writes a local owl:AnnotationProperty (with label +
    comment) to the open .ttl and adds it ticked to that group's catalog."""

    async def scenario() -> None:
        from ster.tui.config_modal import _MetaCheckbox

        app, src = _app(tmp_path)
        async with app.run_test(size=(120, 48)) as pilot:
            modal = await _open_app_config(pilot, app)
            catalog = _entity_catalog(modal)
            await catalog._on_new_property(
                {"name": "reviewedBy", "label": "Reviewed by", "comment": "QA reviewer"}
            )
            for _ in range(5):
                await pilot.pause()
            uri = f"{_BASE}reviewedBy"
            ticked = {cb.predicate for cb in catalog.query(_MetaCheckbox) if cb.value}
            assert uri in ticked  # added + ticked to the catalog
            prop = app.tax.owl_properties.get(uri)  # declared locally...
            assert prop is not None and prop.prop_type == "AnnotationProperty"
        saved = store.load(src).owl_properties.get(uri)  # ...and persisted
        assert saved is not None and saved.prop_type == "AnnotationProperty"
        assert any(lbl.value == "Reviewed by" for lbl in saved.labels)
        assert any(c.value == "QA reviewer" for c in saved.comments)

    _run(scenario)


def test_modal_result_works_in_the_ontology_group_too(tmp_path) -> None:
    """Both groups can mint a local property, not just the entity one."""

    async def scenario() -> None:
        from ster.tui.config_modal import _MetaCheckbox

        app, _src = _app(tmp_path)
        async with app.run_test(size=(120, 48)) as pilot:
            modal = await _open_app_config(pilot, app)
            catalog = _ont_catalog(modal)
            await catalog._on_new_property({"name": "curatedBy"})
            for _ in range(5):
                await pilot.pause()
            uri = f"{_BASE}curatedBy"
            assert uri in {cb.predicate for cb in catalog.query(_MetaCheckbox)}
            assert app.tax.owl_properties[uri].prop_type == "AnnotationProperty"

    _run(scenario)


def test_modal_result_label_defaults_to_the_name(tmp_path) -> None:
    """With the label omitted, the rdfs:label defaults to the predicate name."""

    async def scenario() -> None:
        app, src = _app(tmp_path)
        async with app.run_test(size=(120, 48)) as pilot:
            modal = await _open_app_config(pilot, app)
            await _entity_catalog(modal)._on_new_property({"name": "approvedBy"})
            for _ in range(5):
                await pilot.pause()
        saved = store.load(src).owl_properties.get(f"{_BASE}approvedBy")
        assert saved is not None
        assert any(lbl.value == "approvedBy" for lbl in saved.labels)  # defaulted

    _run(scenario)


def test_cancelling_the_modal_creates_nothing(tmp_path) -> None:
    """A cancelled modal (None result) adds no checkbox and declares nothing."""

    async def scenario() -> None:
        from ster.tui.config_modal import _MetaCheckbox

        app, _src = _app(tmp_path)
        async with app.run_test(size=(120, 48)) as pilot:
            modal = await _open_app_config(pilot, app)
            catalog = _entity_catalog(modal)
            before = len(catalog.query(_MetaCheckbox))
            await catalog._on_new_property(None)  # cancelled
            await catalog._on_new_property({"name": "   "})  # whitespace name
            for _ in range(3):
                await pilot.pause()
            assert len(catalog.query(_MetaCheckbox)) == before
            assert not [u for u in app.tax.owl_properties if u.startswith(_BASE + " ")]

    _run(scenario)


def test_add_local_button_absent_without_an_open_file(tmp_path) -> None:
    """A read-only session (no file / no base IRI) offers no create button."""

    async def scenario() -> None:
        host = _Host()
        async with host.run_test(size=(120, 48)) as pilot:
            modal = ConfigModal("en", ["en"], ["en"], can_declare=False, base_uri="")
            await host.push_screen(modal)
            await pilot.pause()
            assert not modal.query(".cfg-mp-new")  # no create button anywhere

    _run(scenario)


# ── Semantic Lint plugin tab ────────────────────────────────────────────────────


def test_semanticlint_tab_appears_only_when_the_plugin_is_enabled(tmp_path) -> None:
    async def scenario() -> None:
        from ster import plugins

        plugins.set_enabled("semanticlint", True)  # prefs are isolated by the fixture
        app, _src = _app(tmp_path)
        async with app.run_test(size=(120, 48)) as pilot:
            modal = await _open_app_config(pilot, app)
            assert modal.query("#cfg-tab-semanticlint")  # tab present
            assert modal.query("#cfg-slfeat-icons")  # feature toggle present

    _run(scenario)


def test_toggling_the_plugin_adds_and_removes_its_tab(tmp_path) -> None:
    async def scenario() -> None:
        from textual.widgets import Checkbox

        app, _src = _app(tmp_path)
        async with app.run_test(size=(120, 48)) as pilot:
            modal = await _open_app_config(pilot, app)
            assert not modal.query("#cfg-tab-semanticlint")  # off by default
            modal.query_one("#cfg-plugin-semanticlint", Checkbox).value = True
            await pilot.pause()
            assert modal.query("#cfg-tab-semanticlint")  # appeared live
            modal.query_one("#cfg-plugin-semanticlint", Checkbox).value = False
            await pilot.pause()
            assert not modal.query("#cfg-tab-semanticlint")  # removed live

    _run(scenario)


def test_semanticlint_thresholds_and_features_persist_to_quality_json(tmp_path) -> None:
    async def scenario() -> None:
        from textual.widgets import Checkbox, Input

        from ster import plugins
        from ster.plugins.semanticlint import config

        plugins.set_enabled("semanticlint", True)
        app, _src = _app(tmp_path)
        async with app.run_test(size=(120, 48)) as pilot:
            modal = await _open_app_config(pilot, app)
            modal.query_one("#cfg-slfeat-icons", Checkbox).value = False
            modal.query_one("#cfg-slthr-min_label_coverage", Input).value = "0.5"
            for _ in range(3):
                await pilot.pause()
        saved = config.load_config()
        assert saved["features"]["icons"] is False
        assert saved["quality"]["min_label_coverage"] == 0.5

    _run(scenario)
