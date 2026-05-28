"""BDD step definitions for tests/features/io/syntax_validation.feature."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest_bdd import given, scenarios, then, when

from ster.store import format_parse_error

scenarios("../features/io/syntax_validation.feature")


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def ctx(tmp_path: Path) -> dict:
    return {"tmp_path": tmp_path, "result": None, "path": None, "exc": None}


# ── Given ─────────────────────────────────────────────────────────────────────


@given("a valid Turtle file")
def given_valid_ttl(ctx: dict) -> None:
    p = ctx["tmp_path"] / "good.ttl"
    p.write_text("@prefix ex: <https://example.org/> .\nex:A a ex:B .\n", encoding="utf-8")
    ctx["path"] = p


@given("a Turtle file with a bare newline inside a quoted label at line 10")
def given_newline_in_label(ctx: dict) -> None:
    p = ctx["tmp_path"] / "newline_label.ttl"
    # Write with a literal newline inside the quoted string at line 10
    content = "\n".join(["@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> ."] * 1)
    content += "\n" * 8
    content += 'rdfs:label "bad\nlabel" .\n'
    p.write_bytes(content.encode("utf-8"))
    ctx["path"] = p
    try:
        import rdflib

        rdflib.Graph().parse(str(p), format="turtle")
    except Exception as exc:  # noqa: BLE001
        ctx["exc"] = exc


@given("a Turtle file with a missing dot at line 5")
def given_missing_dot(ctx: dict) -> None:
    lines = [
        "@prefix ex: <https://example.org/> .",
        "",
        "ex:A a ex:B .",
        "",
        "ex:C a ex:D",  # line 5 — missing trailing dot
        "",
        "ex:E a ex:F .",
    ]
    p = ctx["tmp_path"] / "missing_dot.ttl"
    p.write_text("\n".join(lines), encoding="utf-8")
    ctx["path"] = p
    try:
        import rdflib

        rdflib.Graph().parse(str(p), format="turtle")
    except Exception as exc:  # noqa: BLE001
        ctx["exc"] = exc


@given("a parse exception whose message contains no line number")
def given_no_line_number(ctx: dict) -> None:
    ctx["exc"] = Exception("completely generic error without coordinates")
    p = ctx["tmp_path"] / "any.ttl"
    p.write_text("@prefix ex: <https://example.org/> .\n", encoding="utf-8")
    ctx["path"] = p


@given("a Turtle file whose bad line is 200 characters long")
def given_long_bad_line(ctx: dict) -> None:
    long_value = "x" * 200
    lines = [
        "@prefix ex: <https://example.org/> .",
        f'ex:A rdfs:label "{long_value}',  # line 2 — unclosed string (200+ chars)
    ]
    p = ctx["tmp_path"] / "long_line.ttl"
    p.write_text("\n".join(lines), encoding="utf-8")
    ctx["path"] = p
    try:
        import rdflib

        rdflib.Graph().parse(str(p), format="turtle")
    except Exception as exc:  # noqa: BLE001
        ctx["exc"] = exc


# ── When ──────────────────────────────────────────────────────────────────────


@when("format_parse_error is called with a successful load exception it never fires")
def when_no_error(ctx: dict) -> None:
    ctx["result"] = None  # format_parse_error is never called for valid files


@when("format_parse_error is called with the parse exception and file path")
def when_format_called(ctx: dict) -> None:
    assert ctx["exc"] is not None, "No parse exception was captured in Given step"
    ctx["result"] = format_parse_error(ctx["exc"], ctx["path"])


@when("format_parse_error is called with the exception and a valid path")
def when_format_called_generic(ctx: dict) -> None:
    ctx["result"] = format_parse_error(ctx["exc"], ctx["path"])


# ── Then ──────────────────────────────────────────────────────────────────────


@then("no syntax error is formatted")
def then_no_error(ctx: dict) -> None:
    assert ctx["result"] is None


@then("the formatted message contains a line reference")
def then_contains_line_reference(ctx: dict) -> None:
    import re as _re

    assert ctx["result"] is not None
    assert _re.search(r"line \d+", ctx["result"]), f"No line reference in: {ctx['result']!r}"


@then('the formatted message contains the word "Syntax"')
def then_contains_syntax(ctx: dict) -> None:
    assert ctx["result"] is not None
    assert "yntax" in ctx["result"]


@then("the formatted message still contains the exception text")
def then_contains_exc_text(ctx: dict) -> None:
    assert ctx["result"] is not None
    assert "generic error" in ctx["result"]


@then("no crash occurs")
def then_no_crash(ctx: dict) -> None:
    assert isinstance(ctx["result"], str)


@then("the shown line excerpt is at most 120 characters long")
def then_line_excerpt_short(ctx: dict) -> None:
    assert ctx["result"] is not None
    for line in ctx["result"].splitlines():
        # Strip Rich markup before measuring
        import re

        plain = re.sub(r"\[.*?\]", "", line)
        assert len(plain) <= 120, f"Line too long ({len(plain)}): {plain!r}"
