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


def _edit(ctx: dict, do: EditCoro) -> None:
    async def scenario() -> None:
        app = OntologyApp(store.load(ctx["src"]), source="zoo.ttl", path=ctx["src"])
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await do(app, pilot)
            for _ in range(4):
                await pilot.pause()
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


async def _submit_text(app, pilot, value: str) -> None:  # noqa: ANN001
    from textual.widgets import Input

    app.screen.query_one("#edit-input", Input).value = value
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
        await _activate(app, pilot, _by_action("new_subclass"))
        await _submit_text(app, pilot, ZOO + child)

    _edit(ctx, do)


@when(parsers.parse('I add the superclass "{parent}" to the class "{name}"'))
def when_add_superclass(ctx: dict, parent: str, name: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(ZOO + name)
        await pilot.pause()
        await _activate(app, pilot, _by_action("link_superclass"))
        await _pick(app, pilot, ZOO + parent)

    _edit(ctx, do)


@when(parsers.parse('I remove the superclass "{parent}" from the class "{name}"'))
def when_remove_superclass(ctx: dict, parent: str, name: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(ZOO + name)
        await pilot.pause()
        await _activate(
            app,
            pilot,
            lambda f: (
                f.meta.get("action") == "remove_superclass"
                and f.meta.get("parent_uri") == ZOO + parent
            ),
        )

    _edit(ctx, do)


@when(parsers.parse('I delete the class "{name}" choosing "{mode}"'))
def when_delete_class(ctx: dict, name: str, mode: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(ZOO + name)
        await pilot.pause()
        await _activate(app, pilot, _by_action("delete_class"))
        await pilot.click(f"#opt-{mode}")

    _edit(ctx, do)


# ── when (individuals) ──────────────────────────────────────────────────────--


@when(parsers.parse('I add an individual "{ind}" of the class "{name}"'))
def when_add_individual(ctx: dict, ind: str, name: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(ZOO + name)
        await pilot.pause()
        await _activate(app, pilot, _by_action("add_individual"))
        await _submit_text(app, pilot, ZOO + ind)

    _edit(ctx, do)


@when(parsers.parse('I add the type "{cls}" to the individual "{ind}"'))
def when_add_type(ctx: dict, cls: str, ind: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(ZOO + ind)
        await pilot.pause()
        await _activate(app, pilot, _by_action("add_ind_type"))
        await _pick(app, pilot, ZOO + cls)

    _edit(ctx, do)


@when(parsers.parse('I remove the type "{cls}" from the individual "{ind}"'))
def when_remove_type(ctx: dict, cls: str, ind: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(ZOO + ind)
        await pilot.pause()
        await _activate(
            app,
            pilot,
            lambda f: (
                f.meta.get("action") == "remove_ind_type" and f.meta.get("type_uri") == ZOO + cls
            ),
        )

    _edit(ctx, do)


@when(parsers.parse('I delete the individual "{ind}"'))
def when_delete_individual(ctx: dict, ind: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(ZOO + ind)
        await pilot.pause()
        await _activate(app, pilot, _by_action("delete_individual"))
        await pilot.click("#opt-delete")

    _edit(ctx, do)


# ── when (ontology overview) ────────────────────────────────────────────────--


@when(parsers.parse('I set the ontology title to "{title}"'))
def when_set_ont_title(ctx: dict, title: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(detail.OVERVIEW_URI)
        await pilot.pause()
        await _activate(app, pilot, lambda f: f.meta.get("type") == "ont_title")
        await _submit_text(app, pilot, title)

    _edit(ctx, do)


@when(parsers.parse('I set the ontology prefix to "{prefix}"'))
def when_set_ont_prefix(ctx: dict, prefix: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(detail.OVERVIEW_URI)
        await pilot.pause()
        await _activate(app, pilot, _by_action("edit_ontology_prefix"))
        await _submit_text(app, pilot, prefix)

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
        await _activate(app, pilot, _by_action("delete_property"))
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


# ── when (rich content, notes, individual values) ───────────────────────────--


@when(parsers.parse('I add the image "{url}" to the individual "{ind}"'))
def when_add_image(ctx: dict, url: str, ind: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(ZOO + ind)
        await pilot.pause()
        await _activate(app, pilot, _by_action("add_schema_image"))
        await _submit_text(app, pilot, url)

    _edit(ctx, do)


@when(parsers.parse('I set the note of the class "{name}" to "{note}"'))
def when_set_note(ctx: dict, name: str, note: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(ZOO + name)
        await pilot.pause()
        await _activate(app, pilot, _by_action("edit_note"))
        await _submit_text(app, pilot, note)

    _edit(ctx, do)


@when(parsers.parse('I remove the value "{val}" of property "{prop}" from the individual "{ind}"'))
def when_remove_value(ctx: dict, val: str, prop: str, ind: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(ZOO + ind)
        await pilot.pause()
        await _activate(
            app,
            pilot,
            lambda f: (
                f.meta.get("action") == "remove_prop_value"
                and f.meta.get("prop_uri") == ZOO + prop
                and f.meta.get("val_uri") == ZOO + val
            ),
        )

    _edit(ctx, do)


# ── then (rich content, notes, individual values) ───────────────────────────--


@when(parsers.parse('I change the value of property "{prop}" on "{ind}" from "{old}" to "{new}"'))
def when_change_value(ctx: dict, prop: str, ind: str, old: str, new: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(ZOO + ind)
        await pilot.pause()
        await _activate(
            app,
            pilot,
            lambda f: (
                f.meta.get("action") == "edit_prop_value"
                and f.meta.get("prop_uri") == ZOO + prop
                and f.meta.get("val_uri") == ZOO + old
            ),
        )
        await _pick(app, pilot, ZOO + new)

    _edit(ctx, do)


@then(parsers.parse('the individual "{ind}" has the value "{val}" for property "{prop}"'))
def then_individual_has_value(ctx: dict, ind: str, val: str, prop: str) -> None:
    pairs = ctx["tax"].owl_individuals[ZOO + ind].property_values
    assert (ZOO + prop, ZOO + val) in pairs
    assert (ZOO + prop, ZOO + val) in ctx["saved"].owl_individuals[ZOO + ind].property_values


@then(parsers.parse('the individual "{ind}" has the image "{url}"'))
def then_individual_has_image(ctx: dict, ind: str, url: str) -> None:
    assert url in ctx["tax"].owl_individuals[ZOO + ind].schema_images
    assert url in ctx["saved"].owl_individuals[ZOO + ind].schema_images


@then(parsers.parse('the class "{name}" has the note "{note}"'))
def then_class_has_note(ctx: dict, name: str, note: str) -> None:
    assert note in ctx["tax"].owl_classes[ZOO + name].note
    assert note in ctx["saved"].owl_classes[ZOO + name].note


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
        await _activate(app, pilot, _by_action("individual_to_class"))
        await pilot.click(f"#opt-{choice}")

    _edit(ctx, do)


@when(parsers.parse('I convert the class "{cls}" to an individual choosing "{choice}"'))
def when_convert_class_to_ind(ctx: dict, cls: str, choice: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(ZOO + cls)
        await pilot.pause()
        await _activate(app, pilot, _by_action("class_to_individual"))
        await pilot.click(f"#opt-{choice}")

    _edit(ctx, do)


# ── when (create from overview) ─────────────────────────────────────────────--


@when(parsers.parse('I create the OWL class "{name}" from the overview'))
def when_create_class(ctx: dict, name: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(detail.OVERVIEW_URI)
        await pilot.pause()
        await _activate(app, pilot, _by_action("create_owl_class"))
        await _submit_text(app, pilot, ZOO + name)

    _edit(ctx, do)


@when(parsers.parse('I create the OWL property "{name}" from the overview'))
def when_create_property(ctx: dict, name: str) -> None:
    async def do(app, pilot):  # noqa: ANN001
        app._show(detail.OVERVIEW_URI)
        await pilot.pause()
        await _activate(app, pilot, _by_action("create_owl_property"))
        await _submit_text(app, pilot, ZOO + name)

    _edit(ctx, do)


@then(parsers.parse('the property "{prop}" exists'))
def then_property_exists(ctx: dict, prop: str) -> None:
    assert ZOO + prop in ctx["tax"].owl_properties
    assert ZOO + prop in ctx["saved"].owl_properties


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
        await _activate(app, pilot, _by_action("delete"))
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
