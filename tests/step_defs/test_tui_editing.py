"""BDD step defs for editing in the New-TUI (tests/features/tui/editing.feature).

Each ``When`` runs one Pilot session on a writable copy of the demo ontology,
performs the edit through the *real* UI path (focus the detail row → activate →
fill the modal / picker), then captures the resulting in-memory taxonomy and the
re-loaded file so the ``Then`` steps can assert both committed and persisted.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster import store
from ster.tui import detail
from ster.tui.app import OntologyApp

scenarios("../features/tui/editing.feature")

DEMO = Path(__file__).resolve().parents[1].parent / "ster" / "tui" / "demo.ttl"
ZOO = "https://example.org/zoo/"
SK = "https://example.org/sk/"

SKOS_TTL = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix sk: <https://example.org/sk/> .

sk:Scheme a skos:ConceptScheme ; dcterms:title "Things"@en ; skos:hasTopConcept sk:Top .
sk:Top a skos:Concept ; skos:inScheme sk:Scheme ; skos:topConceptOf sk:Scheme ;
    skos:prefLabel "Top"@en ; skos:definition "Root."@en ; skos:narrower sk:Child .
sk:Child a skos:Concept ; skos:inScheme sk:Scheme ; skos:prefLabel "Child"@en ;
    skos:broader sk:Top .
sk:Sibling a skos:Concept ; skos:inScheme sk:Scheme ; skos:topConceptOf sk:Scheme ;
    skos:prefLabel "Sibling"@en .
"""


@pytest.fixture
def ctx(tmp_path: Path) -> dict:
    src = tmp_path / "zoo.ttl"
    src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    return {"src": src}


# ── harness ─────────────────────────────────────────────────────────────────--

EditCoro = Callable[[OntologyApp, object], Awaitable[None]]


def _entity_uris(tax) -> set:  # noqa: ANN001
    return (
        set(tax.owl_classes)
        | set(tax.owl_individuals)
        | set(tax.owl_properties)
        | set(tax.schemes)
        | set(tax.concepts)
    )


def _tree_entity_uris(app) -> set:  # noqa: ANN001
    from textual.widgets import Tree

    entities = _entity_uris(app.tax)
    out: set = set()

    def walk(node):  # noqa: ANN001
        if node.data in entities:
            out.add(node.data)
        for child in node.children:
            walk(child)

    for tid in ("#tree", "#prop-tree"):
        walk(app.query_one(tid, Tree).root)
    return out


def _edit(ctx: dict, do: EditCoro) -> None:
    async def scenario() -> None:
        app = OntologyApp(store.load(ctx["src"]), source="zoo.ttl", path=ctx["src"])
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await do(app, pilot)
            for _ in range(4):
                await pilot.pause()
            ctx["tree_uris"] = _tree_entity_uris(app)  # tree nodes after the (targeted) rebuild
            ctx["tax_entities"] = _entity_uris(app.tax)
            app._flush_save()  # edits persist on a background worker → flush before reading disk
            ctx["tax"] = app.tax
            ctx["saved"] = store.load(ctx["src"])
            ctx["overview"] = detail.render_detail(app.tax, detail.OVERVIEW_URI, "en")

    asyncio.run(scenario())


async def _activate(app, pilot, predicate) -> None:  # noqa: ANN001
    """Focus the first detail row matching *predicate* and press Enter."""
    from ster.tui.detail_view import DetailRow

    row = next(r for r in app.query(DetailRow) if predicate(r.field))
    row.focus()
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()


async def _menu_action(app, pilot, action: str) -> None:  # noqa: ANN001
    """Dispatch a right-click context-menu action (delete / convert) on the shown entity
    — these moved off the detail panel to the context menu."""
    from ster.nav.logic import DetailField

    app._run_field_action(
        DetailField("ctx", "", "", editable=False, meta={"type": "action", "action": action})
    )
    await pilot.pause()


async def _activate_menu(app, pilot, predicate, choice: str) -> None:  # noqa: ANN001
    """Open a value row's Edit/Delete submenu and pick *choice* ("edit"|"delete").

    Rows that are both editable and deletable (e.g. ontology annotations) now open
    a submenu on Enter instead of editing directly.
    """
    from ster.tui.context_menu import ContextMenu
    from ster.tui.detail_view import DetailRow

    row = next(r for r in app.query(DetailRow) if predicate(r.field))
    row.focus()
    await pilot.pause()
    await pilot.press("enter")  # opens the Edit/Delete submenu
    await pilot.pause()
    menu = app.query_one("#ctx-menu", ContextMenu)
    menu.highlighted = 0 if choice == "edit" else 1
    await pilot.press("enter")
    await pilot.pause()
    if choice == "delete":  # a value delete now asks to confirm first
        await pilot.click("#opt-ok")
        await pilot.pause()


async def _submit_text(app, pilot, value: str) -> None:  # noqa: ANN001
    from textual.css.query import NoMatches
    from textual.widgets import Input, TextArea

    # Long-text edits (comments, definitions, notes, datatype/annotation literals) open
    # the multi-line Markdown editor: set the TextArea text and Esc to auto-save + close.
    try:
        area = app.screen.query_one("#edit-area", TextArea)
        area.text = value
        await pilot.press("escape")  # auto-save + close the multi-line editor
        return
    except NoMatches:
        pass
    # Creating a class opens the full ClassModal (shared EntityFormModal URI = #ef-uri);
    # an individual opens the full IndividualModal (#ind-uri); URI flows open the
    # fragment-locking UriModal (#uri-input); other single-line edits use EditModal
    # (#edit-input). The full URI starts with the locked base, so assigning the whole
    # value leaves the prefix intact in every case.
    for sel in ("#ef-uri", "#ind-uri", "#uri-input", "#edit-input"):
        try:
            inp = app.screen.query_one(sel, Input)
            break
        except NoMatches:
            continue
    inp.value = value
    await pilot.press("enter")


async def _pick(app, pilot, target_uri: str) -> None:  # noqa: ANN001
    from textual.widgets import OptionList

    modal = app.screen
    idx = next(i for i, (_, uri) in enumerate(modal._options) if uri == target_uri)
    modal.query_one(OptionList).highlighted = idx
    await pilot.press("enter")


def _by_action(action: str):  # noqa: ANN201
    return lambda f: f.meta.get("action") == action


# ── given ───────────────────────────────────────────────────────────────────--


@given("the zoo ontology is open for editing")
def given_open(ctx: dict) -> None:
    pass  # the writable copy is prepared by the ctx fixture; the app opens per-edit


@given("a SKOS taxonomy is open for editing")
def given_skos(ctx: dict) -> None:
    ctx["src"].write_text(SKOS_TTL, encoding="utf-8")  # swap the writable copy to SKOS


# ── when (classes) ────────────────────────────────────────────────────────────


@when(parsers.parse('I rename the class "{name}" to "{new}"'))
def when_rename(ctx: dict, name: str, new: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(ZOO + name)
        await pilot.pause()
        await _activate(app, pilot, lambda f: f.meta.get("type") == "uri")
        await _submit_text(app, pilot, ZOO + new)

    _edit(ctx, do)


@when(parsers.parse('I set the label of the class "{name}" to "{label}"'))
def when_set_label(ctx: dict, name: str, label: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(ZOO + name)
        await pilot.pause()
        await _activate(app, pilot, lambda f: f.meta.get("type") == "rdf_label")
        await _submit_text(app, pilot, label)

    _edit(ctx, do)


@when(parsers.parse('I add a subclass "{child}" under the class "{name}"'))
def when_add_subclass(ctx: dict, child: str, name: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(ZOO + name)
        await pilot.pause()
        await _menu_action(app, pilot, "new_subclass")
        await _submit_text(app, pilot, ZOO + child)

    _edit(ctx, do)


@when(parsers.parse('I add the superclass "{parent}" to the class "{name}"'))
def when_add_superclass(ctx: dict, parent: str, name: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(ZOO + name)
        await pilot.pause()
        await _menu_action(app, pilot, "link_superclass")
        await _pick(app, pilot, ZOO + parent)

    _edit(ctx, do)


@when(parsers.parse('I delete the class "{name}" choosing "{mode}"'))
def when_delete_class(ctx: dict, name: str, mode: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(ZOO + name)
        await pilot.pause()
        await _menu_action(app, pilot, "delete_class")
        await pilot.click(f"#opt-{mode}")

    _edit(ctx, do)


# ── when (individuals) ──────────────────────────────────────────────────────--


@when(parsers.parse('I add an individual "{ind}" of the class "{name}"'))
def when_add_individual(ctx: dict, ind: str, name: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(ZOO + name)
        await pilot.pause()
        await _menu_action(app, pilot, "add_individual")
        await _submit_text(app, pilot, ZOO + ind)

    _edit(ctx, do)


@when(parsers.parse('I add the type "{cls}" to the individual "{ind}"'))
def when_add_type(ctx: dict, cls: str, ind: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(ZOO + ind)
        await pilot.pause()
        await _menu_action(app, pilot, "add_ind_type")  # add via the right-click context menu
        await _pick(app, pilot, ZOO + cls)

    _edit(ctx, do)


@when(parsers.parse('I remove the type "{cls}" from the individual "{ind}"'))
def when_remove_type(ctx: dict, cls: str, ind: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(ZOO + ind)
        await pilot.pause()
        # The remove folds into the instanceOf row's Edit/Delete menu → pick Delete.
        await _activate_menu(
            app,
            pilot,
            lambda f: f.meta.get("type") == "ind_type" and f.meta.get("uri") == ZOO + cls,
            "delete",
        )

    _edit(ctx, do)


@when(parsers.parse('I delete the individual "{ind}"'))
def when_delete_individual(ctx: dict, ind: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(ZOO + ind)
        await pilot.pause()
        await _menu_action(app, pilot, "delete_individual")
        await pilot.click("#opt-delete")

    _edit(ctx, do)


# ── when (ontology overview) ────────────────────────────────────────────────--


@when(parsers.parse('I set the ontology title to "{title}"'))
def when_set_ont_title(ctx: dict, title: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(detail.OVERVIEW_URI)
        await pilot.pause()
        # In the new-TUI overview, the title field is a generic ont_annotation row
        # keyed by the dcterms:title predicate — editable + deletable → submenu.
        await _activate_menu(
            app,
            pilot,
            lambda f: (
                f.meta.get("type") == "ont_annotation" and "title" in f.meta.get("predicate", "")
            ),
            "edit",
        )
        await _submit_text(app, pilot, title)

    _edit(ctx, do)


@when(parsers.parse('I set the ontology prefix to "{prefix}"'))
def when_set_ont_prefix(ctx: dict, prefix: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        from textual.widgets import Input

        app._show(detail.OVERVIEW_URI)
        await pilot.pause()
        await _activate(app, pilot, _by_action("edit_ontology_uri"))  # identity modal
        modal = app.screen
        modal.query_one("#oi-prefix", Input).value = prefix
        modal._submit()  # URI unchanged → prefix set directly (no confirm)
        await pilot.pause()

    _edit(ctx, do)


# ── then ────────────────────────────────────────────────────────────────────--


@then(parsers.parse('the ontology overview shows "{text}"'))
def then_overview_shows(ctx: dict, text: str) -> None:
    assert text in ctx["overview"]


@then(parsers.parse('the saved file declares the prefix "{prefix}"'))
def then_file_has_prefix(ctx: dict, prefix: str) -> None:
    assert f"@prefix {prefix}:" in ctx["src"].read_text(encoding="utf-8")


@then(parsers.parse('the class "{name}" exists'))
def then_class_exists(ctx: dict, name: str) -> None:
    assert ZOO + name in ctx["tax"].owl_classes
    assert ZOO + name in ctx["saved"].owl_classes  # persisted


@then(parsers.parse('the class "{name}" no longer exists'))
def then_class_gone(ctx: dict, name: str) -> None:
    assert ZOO + name not in ctx["tax"].owl_classes
    assert ZOO + name not in ctx["saved"].owl_classes


# ── when (section-header context menus) ─────────────────────────────────────────

_HEADER_CREATE_ACTION = {
    "ObjectProperty": "create_object_property",
    "DatatypeProperty": "create_datatype_property",
    "AnnotationProperty": "create_annotation_property",
}


@when(parsers.parse('I add a "{prop_type}" named "{frag}" from its properties header context menu'))
@when(
    parsers.parse('I add an "{prop_type}" named "{frag}" from its properties header context menu')
)
def when_add_property_from_header(ctx: dict, prop_type: str, frag: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        from ster.tui.app import _add_prop_uri
        from ster.tui.context_menu import ContextMenu

        app.open_context_menu(_add_prop_uri(prop_type))  # right-click the header
        await pilot.pause()
        app.on_context_menu_chosen(ContextMenu.Chosen(_HEADER_CREATE_ACTION[prop_type]))
        await pilot.pause()
        await _submit_text(app, pilot, ZOO + frag)

    _edit(ctx, do)


@then(parsers.parse('the property "{frag}" is a "{prop_type}"'))
def then_property_is_type(ctx: dict, frag: str, prop_type: str) -> None:
    for tax in (ctx["tax"], ctx["saved"]):  # in memory and persisted
        prop = tax.owl_properties.get(ZOO + frag)
        assert prop is not None and prop.prop_type == prop_type


@then("the tree still matches the taxonomy")
def then_tree_matches_taxonomy(ctx: dict) -> None:
    assert ctx["tree_uris"] == ctx["tax_entities"]  # targeted rebuild left no drift


@then(parsers.parse('the class "{name}" has the label "{label}"'))
def then_class_label(ctx: dict, name: str, label: str) -> None:
    labels = {lbl.value for lbl in ctx["tax"].owl_classes[ZOO + name].labels}
    assert label in labels
    assert label in {lbl.value for lbl in ctx["saved"].owl_classes[ZOO + name].labels}


@then(parsers.parse('the class "{name}" is a subclass of "{parent}"'))
def then_is_subclass(ctx: dict, name: str, parent: str) -> None:
    assert ZOO + parent in ctx["tax"].owl_classes[ZOO + name].sub_class_of
    assert ZOO + parent in ctx["saved"].owl_classes[ZOO + name].sub_class_of


@then(parsers.parse('the class "{name}" is not a subclass of "{parent}"'))
def then_not_subclass(ctx: dict, name: str, parent: str) -> None:
    assert ZOO + parent not in ctx["tax"].owl_classes[ZOO + name].sub_class_of
    assert ZOO + parent not in ctx["saved"].owl_classes[ZOO + name].sub_class_of


@then(parsers.parse('the individual "{ind}" exists'))
def then_individual_exists(ctx: dict, ind: str) -> None:
    assert ZOO + ind in ctx["tax"].owl_individuals
    assert ZOO + ind in ctx["saved"].owl_individuals


@then(parsers.parse('the individual "{ind}" no longer exists'))
def then_individual_gone(ctx: dict, ind: str) -> None:
    assert ZOO + ind not in ctx["tax"].owl_individuals
    assert ZOO + ind not in ctx["saved"].owl_individuals


@then(parsers.parse('the individual "{ind}" has type "{cls}"'))
def then_individual_has_type(ctx: dict, ind: str, cls: str) -> None:
    assert ZOO + cls in ctx["tax"].owl_individuals[ZOO + ind].types
    assert ZOO + cls in ctx["saved"].owl_individuals[ZOO + ind].types


@then(parsers.parse('the individual "{ind}" does not have type "{cls}"'))
def then_individual_no_type(ctx: dict, ind: str, cls: str) -> None:
    assert ZOO + cls not in ctx["tax"].owl_individuals[ZOO + ind].types
    assert ZOO + cls not in ctx["saved"].owl_individuals[ZOO + ind].types


# ── when (OWL properties) ───────────────────────────────────────────────────--


@when(parsers.parse('I add the domain class "{cls}" to the property "{prop}"'))
def when_add_prop_domain(ctx: dict, cls: str, prop: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(ZOO + prop)
        await pilot.pause()
        await _activate(app, pilot, _by_action("add_prop_domain"))
        await _pick(app, pilot, ZOO + cls)

    _edit(ctx, do)


@when(parsers.parse('I add the range class "{cls}" to the property "{prop}"'))
def when_add_prop_range(ctx: dict, cls: str, prop: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(ZOO + prop)
        await pilot.pause()
        await _activate(app, pilot, _by_action("add_prop_range"))
        await _pick(app, pilot, ZOO + cls)

    _edit(ctx, do)


@when(parsers.parse('I remove the domain class "{cls}" from the property "{prop}"'))
def when_remove_prop_domain(ctx: dict, cls: str, prop: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(ZOO + prop)
        await pilot.pause()
        await _activate(
            app,
            pilot,
            lambda f: (
                f.meta.get("action") == "remove_prop_domain"
                and f.meta.get("domain_uri") == ZOO + cls
            ),
        )

    _edit(ctx, do)


@when(parsers.parse('I delete the property "{prop}" choosing "{choice}"'))
def when_delete_property(ctx: dict, prop: str, choice: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(ZOO + prop)
        await pilot.pause()
        await _menu_action(app, pilot, "delete_property")
        await pilot.click(f"#opt-{choice}")

    _edit(ctx, do)


# ── then (OWL properties) ───────────────────────────────────────────────────--


@then(parsers.parse('the property "{prop}" has domain "{cls}"'))
def then_prop_has_domain(ctx: dict, prop: str, cls: str) -> None:
    assert ZOO + cls in ctx["tax"].owl_properties[ZOO + prop].domains
    assert ZOO + cls in ctx["saved"].owl_properties[ZOO + prop].domains


@then(parsers.parse('the property "{prop}" does not have domain "{cls}"'))
def then_prop_no_domain(ctx: dict, prop: str, cls: str) -> None:
    assert ZOO + cls not in ctx["tax"].owl_properties[ZOO + prop].domains
    assert ZOO + cls not in ctx["saved"].owl_properties[ZOO + prop].domains


@then(parsers.parse('the property "{prop}" has range "{cls}"'))
def then_prop_has_range(ctx: dict, prop: str, cls: str) -> None:
    assert ZOO + cls in ctx["tax"].owl_properties[ZOO + prop].ranges
    assert ZOO + cls in ctx["saved"].owl_properties[ZOO + prop].ranges


@then(parsers.parse('the property "{prop}" no longer exists'))
def then_prop_gone(ctx: dict, prop: str) -> None:
    assert ZOO + prop not in ctx["tax"].owl_properties
    assert ZOO + prop not in ctx["saved"].owl_properties


# ── when (add class property, add individual value) ─────────────────────────--


@when(parsers.parse('I add an object property "{prop}" on the class "{cls}"'))
def when_add_class_property(ctx: dict, prop: str, cls: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        # Object properties are created from the Object Properties tree section's
        # add modal (URI + domain), not the class detail's removed "+ Add" rows.
        app._open_object_property_create()
        await pilot.pause()
        modal = app.screen
        modal._uri.value = ZOO + prop
        modal._domain.value = ZOO + cls  # domain class
        modal._submit()

    _edit(ctx, do)


@when(parsers.parse('I add the value "{val}" for property "{prop}" on the individual "{ind}"'))
def when_add_prop_value(ctx: dict, val: str, prop: str, ind: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(ZOO + ind)
        await pilot.pause()
        await _menu_action(app, pilot, "add_prop_value")  # add via the right-click context menu
        await _pick(app, pilot, ZOO + prop)  # step 1: pick the property
        await pilot.pause()
        await _pick(app, pilot, ZOO + val)  # step 2: pick the object individual

    _edit(ctx, do)


# ── when (rich content, notes, individual values) ───────────────────────────--


# (schema:image add + markdown note were removed from the detail view — no steps.)


@when(parsers.parse('I remove the value "{val}" of property "{prop}" from the individual "{ind}"'))
def when_remove_value(ctx: dict, val: str, prop: str, ind: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(ZOO + ind)
        await pilot.pause()
        # The remove folds into the value row's Edit/Delete menu → pick Delete.
        await _activate_menu(
            app,
            pilot,
            lambda f: (
                f.meta.get("type") == "ind_prop_val"
                and f.meta.get("prop_uri") == ZOO + prop
                and f.meta.get("val_uri") == ZOO + val
            ),
            "delete",
        )

    _edit(ctx, do)


# ── then (rich content, notes, individual values) ───────────────────────────--


@when(parsers.parse('I change the value of property "{prop}" on "{ind}" from "{old}" to "{new}"'))
def when_change_value(ctx: dict, prop: str, ind: str, old: str, new: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(ZOO + ind)
        await pilot.pause()
        # The value row is editable (✎) → open its Edit/Delete menu, pick Edit, then
        # pick the new target in the picker.
        await _activate_menu(
            app,
            pilot,
            lambda f: (
                f.meta.get("type") == "ind_prop_val"
                and f.meta.get("prop_uri") == ZOO + prop
                and f.meta.get("val_uri") == ZOO + old
            ),
            "edit",
        )
        await _pick(app, pilot, ZOO + new)

    _edit(ctx, do)


@then(parsers.parse('the individual "{ind}" has the value "{val}" for property "{prop}"'))
def then_individual_has_value(ctx: dict, ind: str, val: str, prop: str) -> None:
    pairs = ctx["tax"].owl_individuals[ZOO + ind].property_values
    assert (ZOO + prop, ZOO + val) in pairs
    assert (ZOO + prop, ZOO + val) in ctx["saved"].owl_individuals[ZOO + ind].property_values


@then(parsers.parse('the individual "{ind}" no longer has the value "{val}" for property "{prop}"'))
def then_individual_no_value(ctx: dict, ind: str, val: str, prop: str) -> None:
    pairs = ctx["tax"].owl_individuals[ZOO + ind].property_values
    assert (ZOO + prop, ZOO + val) not in pairs
    saved_pairs = ctx["saved"].owl_individuals[ZOO + ind].property_values
    assert (ZOO + prop, ZOO + val) not in saved_pairs


# ── when (punning conversions) ──────────────────────────────────────────────--


@when(parsers.parse('I convert the individual "{ind}" to a class choosing "{choice}"'))
def when_convert_ind_to_class(ctx: dict, ind: str, choice: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(ZOO + ind)
        await pilot.pause()
        await _menu_action(app, pilot, "individual_to_class")
        await pilot.click(f"#opt-{choice}")

    _edit(ctx, do)


@when(parsers.parse('I convert the class "{cls}" to an individual choosing "{choice}"'))
def when_convert_class_to_ind(ctx: dict, cls: str, choice: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(ZOO + cls)
        await pilot.pause()
        await _menu_action(app, pilot, "class_to_individual")
        await pilot.click(f"#opt-{choice}")

    _edit(ctx, do)


# ── when / then (ontology base-URI / domain rename) ─────────────────────────--


@when(parsers.parse('I change the ontology base URI to "{base}"'))
def when_change_base_uri(ctx: dict, base: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        from urllib.parse import urlsplit

        from textual.widgets import Input, RadioButton

        app._show(detail.OVERVIEW_URI)
        await pilot.pause()
        await _activate(app, pilot, _by_action("edit_ontology_uri"))  # identity modal
        # Decompose the target into the modal's independent fields.
        sep = base[-1] if base[-1:] in "#/" else "#"
        parts = urlsplit(base.rstrip("#/"))
        modal = app.screen
        modal.query_one("#oi-domain", Input).value = parts.netloc
        modal.query_one("#oi-path", Input).value = parts.path.strip("/")
        list(modal.query(RadioButton))[1 if sep == "/" else 0].value = True
        await pilot.pause()
        modal._submit()  # → impact-confirm modal
        await pilot.pause()
        await pilot.press("enter")  # confirm the rename (first button focused)
        await pilot.pause()

    _edit(ctx, do)


@when(parsers.parse('I change the ontology domain to "{domain}"'))
def when_change_domain(ctx: dict, domain: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        from textual.widgets import Input

        app._show(detail.OVERVIEW_URI)
        await pilot.pause()
        await _activate(app, pilot, _by_action("edit_ontology_uri"))  # identity modal
        modal = app.screen
        modal.query_one("#oi-domain", Input).value = domain  # edit only the host
        modal._submit()
        await pilot.pause()
        await pilot.press("enter")  # confirm the cascade
        await pilot.pause()

    _edit(ctx, do)


@then(parsers.parse('a class exists at "{full_uri}"'))
def then_class_exists_at(ctx: dict, full_uri: str) -> None:
    assert full_uri in ctx["tax"].owl_classes
    assert full_uri in ctx["saved"].owl_classes


@then(parsers.parse('no class exists at "{full_uri}"'))
def then_no_class_at(ctx: dict, full_uri: str) -> None:
    assert full_uri not in ctx["tax"].owl_classes
    assert full_uri not in ctx["saved"].owl_classes


# ── when (create from tree action nodes) ────────────────────────────────────--


async def _select_tree_action(app, pilot, action: str) -> None:  # noqa: ANN001
    """Trigger a section-header create action via its right-click context menu (the
    former ＋Add tree leaves were removed once the headers became right-clickable)."""
    from ster.tui import detail
    from ster.tui.context_menu import ContextMenu

    anchor = {"create_owl_class": detail.OVERVIEW_URI, "add_scheme": detail.TAXONOMY_URI}[action]
    app.open_context_menu(anchor)  # right-click the Ontology / Taxonomy header
    await pilot.pause()
    app.on_context_menu_chosen(ContextMenu.Chosen(action))
    await pilot.pause()
    await pilot.pause()  # extra pause so the modal has time to appear


@when(parsers.parse('I create the OWL class "{name}" from the tree'))
def when_create_class(ctx: dict, name: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        await _select_tree_action(app, pilot, "create_owl_class")
        await _submit_text(app, pilot, ZOO + name)

    _edit(ctx, do)


@when(parsers.parse('I create the scheme "{name}" titled "{title}" from the tree'))
def when_create_scheme(ctx: dict, name: str, title: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        await _select_tree_action(app, pilot, "add_scheme")
        await _submit_text(app, pilot, title)  # step 1: title
        await pilot.pause()
        await _submit_text(app, pilot, ZOO + name)  # step 2: URI

    _edit(ctx, do)


@then(parsers.parse('the property "{prop}" exists'))
def then_property_exists(ctx: dict, prop: str) -> None:
    assert ZOO + prop in ctx["tax"].owl_properties
    assert ZOO + prop in ctx["saved"].owl_properties


@then(parsers.parse('the scheme "{name}" exists'))
def then_scheme_exists(ctx: dict, name: str) -> None:
    assert ZOO + name in ctx["tax"].schemes
    assert ZOO + name in ctx["saved"].schemes


# ── when (SKOS concepts) ────────────────────────────────────────────────────--


@when(parsers.parse('I set the prefLabel of the concept "{name}" to "{value}"'))
def when_set_pref(ctx: dict, name: str, value: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(SK + name)
        await pilot.pause()
        await _activate(app, pilot, lambda f: f.meta.get("type") == "pref")
        await _submit_text(app, pilot, value)

    _edit(ctx, do)


@when(parsers.parse('I set the definition of the concept "{name}" to "{value}"'))
def when_set_def(ctx: dict, name: str, value: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(SK + name)
        await pilot.pause()
        await _activate(app, pilot, lambda f: f.meta.get("type") == "def")
        await _submit_text(app, pilot, value)

    _edit(ctx, do)


@when(parsers.parse('I add a definition "{value}" to the concept "{name}"'))
def when_add_def(ctx: dict, value: str, name: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(SK + name)
        await pilot.pause()
        await _activate(app, pilot, _by_action("add_def"))
        await _submit_text(app, pilot, value)

    _edit(ctx, do)


@when(parsers.parse('I add a narrower concept "{child}" under the concept "{name}"'))
def when_add_narrower(ctx: dict, child: str, name: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(SK + name)
        await pilot.pause()
        await _activate(app, pilot, _by_action("add_narrower"))
        await _submit_text(app, pilot, SK + child)

    _edit(ctx, do)


@when(parsers.parse('I relate the concept "{name}" to the concept "{other}"'))
def when_relate(ctx: dict, name: str, other: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(SK + name)
        await pilot.pause()
        await _activate(app, pilot, _by_action("add_related"))
        await _pick(app, pilot, SK + other)

    _edit(ctx, do)


@when(parsers.parse('I delete the concept "{name}" choosing "{choice}"'))
def when_delete_concept(ctx: dict, name: str, choice: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(SK + name)
        await pilot.pause()
        await _menu_action(app, pilot, "delete")
        await pilot.click(f"#opt-{choice}")

    _edit(ctx, do)


# ── when (SKOS schemes) ─────────────────────────────────────────────────────--


@when(parsers.parse('I set the title of the scheme to "{value}"'))
def when_set_scheme_title(ctx: dict, value: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(SK + "Scheme")
        await pilot.pause()
        await _activate(app, pilot, lambda f: f.meta.get("type") == "scheme_title")
        await _submit_text(app, pilot, value)

    _edit(ctx, do)


@when(parsers.parse('I add a top concept "{name}" to the scheme'))
def when_add_top_concept(ctx: dict, name: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(SK + "Scheme")
        await pilot.pause()
        await _activate(app, pilot, _by_action("add_top_concept"))
        await _submit_text(app, pilot, SK + name)

    _edit(ctx, do)


# ── then (SKOS) ─────────────────────────────────────────────────────────────--


@then(parsers.parse('the concept "{name}" has prefLabel "{value}"'))
def then_concept_pref(ctx: dict, name: str, value: str) -> None:
    assert value in {label.value for label in ctx["tax"].concepts[SK + name].labels}
    assert value in {label.value for label in ctx["saved"].concepts[SK + name].labels}


@then(parsers.parse('the concept "{name}" has definition "{value}"'))
def then_concept_def(ctx: dict, name: str, value: str) -> None:
    assert value in {d.value for d in ctx["tax"].concepts[SK + name].definitions}
    assert value in {d.value for d in ctx["saved"].concepts[SK + name].definitions}


@then(parsers.parse('the concept "{name}" exists'))
def then_concept_exists(ctx: dict, name: str) -> None:
    assert SK + name in ctx["tax"].concepts
    assert SK + name in ctx["saved"].concepts


@then(parsers.parse('the concept "{name}" no longer exists'))
def then_concept_gone(ctx: dict, name: str) -> None:
    assert SK + name not in ctx["tax"].concepts
    assert SK + name not in ctx["saved"].concepts


@then(parsers.parse('the concept "{name}" is related to "{other}"'))
def then_concept_related(ctx: dict, name: str, other: str) -> None:
    assert SK + other in ctx["tax"].concepts[SK + name].related
    assert SK + other in ctx["saved"].concepts[SK + name].related


@then(parsers.parse('the scheme has title "{value}"'))
def then_scheme_title(ctx: dict, value: str) -> None:
    assert ctx["tax"].schemes[SK + "Scheme"].title("en") == value
    assert ctx["saved"].schemes[SK + "Scheme"].title("en") == value


# ── Phase 15: generic ontology annotation overview ──────────────────────────--

DCT = "http://purl.org/dc/terms/"

ANNOTATED_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix zoo: <https://example.org/zoo/> .

<https://example.org/onto> a owl:Ontology ;
    rdfs:label "Zoo Ontology" ;
    dcterms:creator "Alice" ;
    dcterms:creator "Charlie" ;
    dcterms:license <https://creativecommons.org/licenses/by/4.0/> .

zoo:Animal a owl:Class ; rdfs:label "Animal"@en .
"""


@pytest.fixture
def ctx_annotated(tmp_path: Path) -> dict:
    src = tmp_path / "annotated.ttl"
    src.write_text(ANNOTATED_TTL, encoding="utf-8")
    return {"src": src}


@given("an annotated ontology is open for editing")
def given_annotated(ctx_annotated: dict, ctx: dict) -> None:  # noqa: ARG001
    ctx.update(ctx_annotated)


@when("I open the ontology overview")
def when_open_overview(ctx: dict) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(detail.OVERVIEW_URI)
        await pilot.pause()

    _edit(ctx, do)


@then(parsers.parse('the overview shows an annotation row for "{predicate_label}"'))
def then_overview_shows_annotation_row(ctx: dict, predicate_label: str) -> None:
    from ster import store
    from ster.nav.logic import build_tui_ontology_overview_fields

    tax = store.load(ctx["src"])
    fields = build_tui_ontology_overview_fields(tax, "en")
    assert any(predicate_label in f.display for f in fields), (
        f"No annotation row for '{predicate_label}' in overview. "
        f"Rows: {[f.display for f in fields]}"
    )


@then("no class rows appear in the overview")
def then_no_class_rows(ctx: dict) -> None:
    from ster import store
    from ster.nav.logic import build_tui_ontology_overview_fields

    tax = store.load(ctx["src"])
    fields = build_tui_ontology_overview_fields(tax, "en")
    class_uris = set(tax.owl_classes)
    assert not any(f.value in class_uris for f in fields)


@then("no property rows appear in the overview")
def then_no_property_rows(ctx: dict) -> None:
    from ster import store
    from ster.nav.logic import build_tui_ontology_overview_fields

    tax = store.load(ctx["src"])
    fields = build_tui_ontology_overview_fields(tax, "en")
    assert not any(f.meta.get("type") == "property_row" for f in fields)


@when(parsers.parse('I edit the annotation "{predicate_label}" to "{new_value}"'))
def when_edit_annotation(ctx: dict, predicate_label: str, new_value: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(detail.OVERVIEW_URI)
        await pilot.pause()
        await _activate_menu(
            app,
            pilot,
            lambda f: f.meta.get("type") == "ont_annotation" and predicate_label in f.display,
            "edit",
        )
        await _submit_text(app, pilot, new_value)

    _edit(ctx, do)


@then(parsers.parse('the ontology annotation "{predicate_label}" has value "{value}"'))
def then_annotation_has_value(ctx: dict, predicate_label: str, value: str) -> None:
    local_name = predicate_label.split(":")[-1]
    pred = next(a.predicate for a in ctx["tax"].ontology_annotations if local_name in a.predicate)
    values_in_mem = {a.value for a in ctx["tax"].ontology_annotations if a.predicate == pred}
    values_saved = {a.value for a in ctx["saved"].ontology_annotations if a.predicate == pred}
    assert value in values_in_mem, f"Expected '{value}' in {values_in_mem}"
    assert value in values_saved, f"Expected '{value}' in saved {values_saved}"


@when(parsers.parse('I remove the annotation "{predicate_label}" with value "{value}"'))
def when_remove_annotation(ctx: dict, predicate_label: str, value: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(detail.OVERVIEW_URI)
        await pilot.pause()
        # The "✕ remove" row is folded into the value row's submenu → pick Delete.
        await _activate_menu(
            app,
            pilot,
            lambda f: (
                f.meta.get("type") == "ont_annotation"
                and predicate_label in f.display
                and f.meta.get("old_value") == value
            ),
            "delete",
        )

    _edit(ctx, do)


@then(parsers.parse('the ontology annotation "{predicate_label}" no longer has value "{value}"'))
def then_annotation_no_value(ctx: dict, predicate_label: str, value: str) -> None:
    local_name = predicate_label.split(":")[-1]
    values = {a.value for a in ctx["tax"].ontology_annotations if local_name in a.predicate}
    assert value not in values


@then(parsers.parse('the ontology annotation "{predicate_label}" still has value "{value}"'))
def then_annotation_still_has_value(ctx: dict, predicate_label: str, value: str) -> None:
    local_name = predicate_label.split(":")[-1]
    values = {a.value for a in ctx["tax"].ontology_annotations if local_name in a.predicate}
    assert value in values


@when(parsers.parse('I add the annotation "{predicate_label}" with value "{value}"'))
def when_add_annotation(ctx: dict, predicate_label: str, value: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        from textual.widgets import OptionList

        app._show(detail.OVERVIEW_URI)
        await pilot.pause()
        await _activate(app, pilot, lambda f: f.meta.get("action") == "add_ont_annotation")
        # Step 1: picker — find the entry matching predicate_label
        await pilot.pause()
        modal = app.screen
        idx = next(i for i, (label, _pred) in enumerate(modal._options) if predicate_label in label)
        modal.query_one(OptionList).highlighted = idx
        await pilot.press("enter")
        await pilot.pause()
        # Step 2: text input for the value
        await _submit_text(app, pilot, value)

    _edit(ctx, do)
