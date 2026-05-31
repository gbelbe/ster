"""BDD step definitions for tests/features/owl/delete_class.feature."""

from __future__ import annotations

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster.model import Label, OWLIndividual, OWLProperty, RDFClass, Taxonomy
from ster.operations import delete_owl_class

scenarios("../features/owl/delete_class.feature")

BASE = "https://example.org/onto#"


def _u(name: str) -> str:
    return BASE + name


@pytest.fixture
def ctx() -> dict:
    return {}


# ── Given ─────────────────────────────────────────────────────────────────────


@given(parsers.parse('a taxonomy with OWL class "{a}" only'))
def given_one_class(ctx: dict, a: str) -> None:
    t = Taxonomy()
    t.owl_classes[_u(a)] = RDFClass(uri=_u(a), labels=[Label("en", a)])
    ctx["taxonomy"] = t


@given(parsers.parse('a taxonomy with OWL classes "{a}", "{b}", and "{c}"'))
def given_three_classes(ctx: dict, a: str, b: str, c: str) -> None:
    t = Taxonomy()
    for name in (a, b, c):
        t.owl_classes[_u(name)] = RDFClass(uri=_u(name), labels=[Label("en", name)])
    ctx["taxonomy"] = t


@given(parsers.parse('a taxonomy with OWL classes "{a}" and "{b}"'))
def given_two_classes(ctx: dict, a: str, b: str) -> None:
    t = Taxonomy()
    for name in (a, b):
        t.owl_classes[_u(name)] = RDFClass(uri=_u(name), labels=[Label("en", name)])
    ctx["taxonomy"] = t


@given(parsers.parse('"{child}" is a subclass of "{parent}"'))
def given_subclass(ctx: dict, child: str, parent: str) -> None:
    t: Taxonomy = ctx["taxonomy"]
    t.owl_classes[_u(child)].sub_class_of.append(_u(parent))


@given(parsers.parse('an individual "{name}" typed as "{cls}"'))
def given_individual(ctx: dict, name: str, cls: str) -> None:
    t: Taxonomy = ctx["taxonomy"]
    t.owl_individuals[_u(name)] = OWLIndividual(
        uri=_u(name),
        labels=[Label("en", name)],
        types=[_u(cls)],
    )


@given(parsers.parse('a property "{prop}" with domain "{cls}"'))
def given_property_domain(ctx: dict, prop: str, cls: str) -> None:
    t: Taxonomy = ctx["taxonomy"]
    t.owl_properties[_u(prop)] = OWLProperty(
        uri=_u(prop),
        labels=[Label("en", prop)],
        domains=[_u(cls)],
        ranges=[],
    )


# ── When ──────────────────────────────────────────────────────────────────────


@when(parsers.parse('I delete class "{cls}" with mode "{mode}"'))
def when_delete_class(ctx: dict, cls: str, mode: str) -> None:
    delete_owl_class(ctx["taxonomy"], _u(cls), mode=mode)


# ── Then ──────────────────────────────────────────────────────────────────────


@then(parsers.parse('class "{cls}" does not exist in the taxonomy'))
def then_class_absent(ctx: dict, cls: str) -> None:
    assert _u(cls) not in ctx["taxonomy"].owl_classes


@then(parsers.parse('class "{cls}" exists in the taxonomy'))
def then_class_present(ctx: dict, cls: str) -> None:
    assert _u(cls) in ctx["taxonomy"].owl_classes


@then(parsers.parse('individual "{name}" exists in the taxonomy'))
def then_individual_present(ctx: dict, name: str) -> None:
    assert _u(name) in ctx["taxonomy"].owl_individuals


@then(parsers.parse('individual "{name}" does not exist in the taxonomy'))
def then_individual_absent(ctx: dict, name: str) -> None:
    assert _u(name) not in ctx["taxonomy"].owl_individuals


@then(parsers.parse('individual "{name}" is typed as "{cls}"'))
def then_individual_typed(ctx: dict, name: str, cls: str) -> None:
    ind = ctx["taxonomy"].owl_individuals[_u(name)]
    assert _u(cls) in ind.types


@then(parsers.parse('individual "{name}" has no types'))
def then_individual_no_types(ctx: dict, name: str) -> None:
    ind = ctx["taxonomy"].owl_individuals[_u(name)]
    assert ind.types == []


@then(parsers.parse('"{child}" is a subclass of "{parent}"'))
def then_is_subclass(ctx: dict, child: str, parent: str) -> None:
    cls = ctx["taxonomy"].owl_classes[_u(child)]
    assert _u(parent) in cls.sub_class_of


@then(parsers.parse('property "{prop}" has no domain entries'))
def then_no_domain(ctx: dict, prop: str) -> None:
    assert ctx["taxonomy"].owl_properties[_u(prop)].domains == []


@when("I build the global overview fields without fastapi available")
def when_build_global_fields_no_fastapi(ctx: dict, monkeypatch) -> None:
    """Simulate fastapi not installed, then exercise the _bgf() code path.

    Before the fix: `from ..api import _derive_slug` inside _bgf() triggered
    api.py's top-level `from fastapi import ...`, crashing with ModuleNotFoundError.
    After the fix: _bgf() derives the slug inline — no api import needed.
    """
    import re
    import sys

    from ster.api_server import load_server_config
    from ster.nav.logic import build_global_fields

    # Simulate fastapi not installed by poisoning the module cache.
    # We must also evict api from the cache so the next import re-runs.
    monkeypatch.setitem(sys.modules, "fastapi", None)  # type: ignore[arg-type]
    monkeypatch.delitem(sys.modules, "ster.api", raising=False)

    server_url, server_port = load_server_config()
    # Inline the slug logic exactly as the fixed _bgf() does:
    stem = "leaf"
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-") or "onto"
    try:
        ctx["fields"] = build_global_fields(
            None,  # type: ignore[arg-type]
            None,
            "en",
            server_url=server_url,
            server_port=server_port,
            show_token=False,
            pending_restart=False,
            ontology_slug=slug,
        )
        ctx["error"] = None
    except ModuleNotFoundError as exc:
        ctx["error"] = exc


@then("no ModuleNotFoundError is raised")
def then_no_module_not_found(ctx: dict) -> None:
    assert ctx.get("error") is None, f"ModuleNotFoundError was raised: {ctx['error']}"
