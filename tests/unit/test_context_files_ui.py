"""The interface has to say which entities are read-only.

The data layer already refuses to persist edits to a context entity, but a row
that cannot be edited must not *look* like one that can — otherwise the refusal
arrives only after the user has tried.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ster import cli
from ster.model import Concept, ConceptScheme, Label, LabelType, Taxonomy
from ster.viz_vowl import _app_js, build_vowl_graph

NS = "https://example.org/t#"


def _lbl(v: str) -> Label:
    return Label(lang="en", value=v, type=LabelType.PREF)


@pytest.fixture
def mixed() -> Taxonomy:
    """One editable concept, one merged from a context file."""
    tax = Taxonomy()
    tax.schemes[NS + "S"] = ConceptScheme(uri=NS + "S", labels=[_lbl("Scheme")])
    tax.concepts[NS + "Mine"] = Concept(uri=NS + "Mine", labels=[_lbl("Mine")])
    tax.concepts[NS + "Theirs"] = Concept(uri=NS + "Theirs", labels=[_lbl("Theirs")])
    tax.context_source[NS + "Theirs"] = Path("/tmp/places.ttl")
    return tax


# ── the file picker ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("", []),
        ("none", []),
        ("n", []),
        ("all", ["a.ttl", "b.ttl", "c.ttl"]),
        ("1,3", ["a.ttl", "c.ttl"]),
        ("1 3", ["a.ttl", "c.ttl"]),
        ("2", ["b.ttl"]),
    ],
)
def test_context_choice_parsing(answer, expected):
    options = [Path("a.ttl"), Path("b.ttl"), Path("c.ttl")]

    assert [p.name for p in cli._workspace_ui.parse_context_choice(answer, options)] == expected


def test_context_choice_ignores_junk_rather_than_refusing():
    """One typo should not discard the files that were named clearly."""
    options = [Path("a.ttl"), Path("b.ttl")]

    assert [p.name for p in cli._workspace_ui.parse_context_choice("x,2", options)] == ["b.ttl"]


def test_context_choice_ignores_out_of_range():
    assert cli._workspace_ui.parse_context_choice("9", [Path("a.ttl")]) == []


def test_context_choice_deduplicates():
    options = [Path("a.ttl"), Path("b.ttl")]

    assert [p.name for p in cli._workspace_ui.parse_context_choice("1,1", options)] == ["a.ttl"]


def test_no_prompt_when_there_is_nothing_else_to_offer(monkeypatch):
    """The single-file case must stay exactly as it was."""
    asked = []
    monkeypatch.setattr(cli.Prompt, "ask", lambda *a, **k: asked.append(1) or "all")

    result = cli._workspace_ui.prompt_for_context_files(Path("only.ttl"), [Path("only.ttl")])

    assert result == []
    assert asked == [], "no question when there is no choice"


def test_prompt_offers_the_other_files(monkeypatch):
    monkeypatch.setattr(cli.Prompt, "ask", lambda *a, **k: "all")

    result = cli._workspace_ui.prompt_for_context_files(
        Path("a.ttl"), [Path("a.ttl"), Path("b.ttl")]
    )

    assert [p.name for p in result] == ["b.ttl"], "the editable file is not its own context"


# ── the graph ─────────────────────────────────────────────────────────────────


def test_graph_flags_context_entities(mixed):
    nodes = {n["id"]: n for n in build_vowl_graph(mixed)["nodes"]}

    assert nodes[NS + "Theirs"]["readOnly"] == 1
    assert nodes[NS + "Mine"]["readOnly"] == 0


def test_graph_flags_nothing_without_context():
    tax = Taxonomy()
    tax.concepts[NS + "Mine"] = Concept(uri=NS + "Mine", labels=[_lbl("Mine")])

    assert all(n["readOnly"] == 0 for n in build_vowl_graph(tax)["nodes"])


def test_app_js_styles_read_only_nodes():
    js = _app_js().replace(" ", "")

    assert "selector:'node[readOnly=1]'" in js
    assert "'border-style':'dashed'" in js


def test_app_js_carries_the_flag_into_cytoscape():
    assert "readOnly:n.readOnly||0" in _app_js().replace(" ", "")


def test_app_js_legend_explains_the_style():
    """A dashed border means nothing without a legend row naming it."""
    assert "read-only (context file)" in _app_js()


# ── the tree and the edit guard ───────────────────────────────────────────────


def _two_file_app(tmp_path):
    """An app whose taxonomy has one editable and one context-file concept."""
    from ster import store
    from ster.tui.app import OntologyApp

    primary = tmp_path / "primary.ttl"
    primary.write_text(
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
        f"@prefix ex: <{NS}> .\n"
        "ex:Scheme a skos:ConceptScheme .\n"
        'ex:Mine a skos:Concept ; skos:prefLabel "Mine"@en ; skos:inScheme ex:Scheme .\n',
        encoding="utf-8",
    )
    context = tmp_path / "places.ttl"
    context.write_text(
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
        f"@prefix ex: <{NS}> .\n"
        # Its own scheme, so the context concept is rendered in the tree. A concept
        # that only declares broader into the editable file is reachable in the
        # graph but not yet in the tree, which walks narrower downward.
        "ex:Theirs_S a skos:ConceptScheme .\n"
        'ex:Theirs a skos:Concept ; skos:prefLabel "Theirs"@en ; skos:inScheme ex:Theirs_S .\n',
        encoding="utf-8",
    )
    tax = store.load(primary, context=[context])
    return OntologyApp(tax, source="primary.ttl", path=primary), context


def test_tree_locks_only_the_context_rows(tmp_path) -> None:
    """The glyph is the whole point: an uneditable row must look uneditable."""
    import asyncio

    app, _context = _two_file_app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            def walk(node):
                yield node
                for child in node.children:
                    yield from walk(child)

            labels = {str(n.label): n.data for n in walk(app.query_one("#tree").root)}
            locked = [t for t, uri in labels.items() if uri in {NS + "Theirs", NS + "Theirs_S"}]
            unlocked = [t for t, uri in labels.items() if uri in {NS + "Mine", NS + "S"}]
            assert locked and all("🔒" in t for t in locked)
            assert unlocked and all("🔒" not in t for t in unlocked)

    asyncio.run(scenario())


def test_editing_a_context_entity_is_refused_and_names_the_file(tmp_path) -> None:
    """Refusing is not enough — the message has to say where the entity lives."""
    import asyncio

    app, context = _two_file_app(tmp_path)
    notes: list[str] = []

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.notify = lambda msg, **kw: notes.append(msg)  # type: ignore[assignment]
            app._show(NS + "Theirs")
            await pilot.pause()
            from ster.tui.detail_view import DetailRow

            rows = [r for r in app.query(DetailRow) if r.field.meta.get("type")]
            if rows:
                app._open_edit_modal(rows[0].field)
            await pilot.pause()

    asyncio.run(scenario())
    assert any(context.name in n for n in notes), notes
