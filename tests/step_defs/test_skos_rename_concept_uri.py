"""BDD step definitions for tests/features/skos/rename_concept_uri.feature."""

from __future__ import annotations

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster.model import Concept, Label, LabelType, Taxonomy
from ster.operations import rename_uri

scenarios("../features/skos/rename_concept_uri.feature")

BASE = "https://example.org/onto#"


def _u(name: str) -> str:
    return BASE + name


@pytest.fixture
def ctx() -> dict:
    return {}


# ── Given ─────────────────────────────────────────────────────────────────────


@given(parsers.parse('a taxonomy with concepts "{a}" and "{b}"'))
def given_two_concepts(ctx: dict, a: str, b: str) -> None:
    t = Taxonomy()
    for name in (a, b):
        t.concepts[_u(name)] = Concept(
            uri=_u(name), labels=[Label("en", name, LabelType.PREF)]
        )
    ctx["taxonomy"] = t


@given(parsers.parse('"{src}" has broadMatch "{tgt}"'))
def given_broad_match(ctx: dict, src: str, tgt: str) -> None:
    ctx["taxonomy"].concepts[_u(src)].broad_match.append(_u(tgt))


@given(parsers.parse('"{src}" has narrowMatch "{tgt}"'))
def given_narrow_match(ctx: dict, src: str, tgt: str) -> None:
    ctx["taxonomy"].concepts[_u(src)].narrow_match.append(_u(tgt))


@given(parsers.parse('"{src}" has relatedMatch "{tgt}"'))
def given_related_match(ctx: dict, src: str, tgt: str) -> None:
    ctx["taxonomy"].concepts[_u(src)].related_match.append(_u(tgt))


@given(parsers.parse('"{src}" has exactMatch "{tgt}"'))
def given_exact_match(ctx: dict, src: str, tgt: str) -> None:
    ctx["taxonomy"].concepts[_u(src)].exact_match.append(_u(tgt))


@given(parsers.parse('"{src}" has closeMatch "{tgt}"'))
def given_close_match(ctx: dict, src: str, tgt: str) -> None:
    ctx["taxonomy"].concepts[_u(src)].close_match.append(_u(tgt))


@given(parsers.parse('"{src}" has an external exactMatch "{ext}"'))
def given_external_exact_match(ctx: dict, src: str, ext: str) -> None:
    ctx["taxonomy"].concepts[_u(src)].exact_match.append(ext)


# ── When ──────────────────────────────────────────────────────────────────────


@when(parsers.parse('I rename concept "{old}" to "{new}"'))
def when_rename_concept(ctx: dict, old: str, new: str) -> None:
    rename_uri(ctx["taxonomy"], _u(old), _u(new))


# ── Then ──────────────────────────────────────────────────────────────────────


@then(parsers.parse('"{src}" broadMatch contains "{tgt}"'))
def then_broad_contains(ctx: dict, src: str, tgt: str) -> None:
    assert _u(tgt) in ctx["taxonomy"].concepts[_u(src)].broad_match


@then(parsers.parse('"{src}" broadMatch does not contain "{tgt}"'))
def then_broad_not_contains(ctx: dict, src: str, tgt: str) -> None:
    assert _u(tgt) not in ctx["taxonomy"].concepts[_u(src)].broad_match


@then(parsers.parse('"{src}" narrowMatch contains "{tgt}"'))
def then_narrow_contains(ctx: dict, src: str, tgt: str) -> None:
    assert _u(tgt) in ctx["taxonomy"].concepts[_u(src)].narrow_match


@then(parsers.parse('"{src}" narrowMatch does not contain "{tgt}"'))
def then_narrow_not_contains(ctx: dict, src: str, tgt: str) -> None:
    assert _u(tgt) not in ctx["taxonomy"].concepts[_u(src)].narrow_match


@then(parsers.parse('"{src}" relatedMatch contains "{tgt}"'))
def then_related_contains(ctx: dict, src: str, tgt: str) -> None:
    assert _u(tgt) in ctx["taxonomy"].concepts[_u(src)].related_match


@then(parsers.parse('"{src}" relatedMatch does not contain "{tgt}"'))
def then_related_not_contains(ctx: dict, src: str, tgt: str) -> None:
    assert _u(tgt) not in ctx["taxonomy"].concepts[_u(src)].related_match


@then(parsers.parse('"{src}" exactMatch contains "{tgt}"'))
def then_exact_contains(ctx: dict, src: str, tgt: str) -> None:
    assert _u(tgt) in ctx["taxonomy"].concepts[_u(src)].exact_match


@then(parsers.parse('"{src}" exactMatch does not contain "{tgt}"'))
def then_exact_not_contains(ctx: dict, src: str, tgt: str) -> None:
    assert _u(tgt) not in ctx["taxonomy"].concepts[_u(src)].exact_match


@then(parsers.parse('"{src}" closeMatch contains "{tgt}"'))
def then_close_contains(ctx: dict, src: str, tgt: str) -> None:
    assert _u(tgt) in ctx["taxonomy"].concepts[_u(src)].close_match


@then(parsers.parse('"{src}" closeMatch does not contain "{tgt}"'))
def then_close_not_contains(ctx: dict, src: str, tgt: str) -> None:
    assert _u(tgt) not in ctx["taxonomy"].concepts[_u(src)].close_match


@then(parsers.parse('"{src}" exactMatch contains the external URI "{ext}"'))
def then_exact_contains_external(ctx: dict, src: str, ext: str) -> None:
    assert ext in ctx["taxonomy"].concepts[_u(src)].exact_match
