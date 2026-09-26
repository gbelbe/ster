"""The history screen: how a commit is presented, and how the screen is wired.

Presentation is pure — a row in, a Rich renderable out — so it is asserted
directly on rendered text. The app tests cover wiring only: what is listed, what
is put away, and that a revision is read once and off the UI thread.
"""

from __future__ import annotations

import io

from rich.console import Console

from ster.plugins.semanticdiff.history import open_history
from ster.plugins.semanticdiff.screen import HistoryScreen, _changes, _diff_text, _heading
from tests._ontology_repo import ONTOLOGY, RepoBuilder

CLASS_A = 'ex:A a owl:Class ; rdfs:label "Alpha"@en .'
CLASS_AB = 'ex:A a owl:Class ; rdfs:label "Alpha"@en . ex:B a owl:Class .'


def _history(repo: RepoBuilder):
    repo.commit(ttl=CLASS_A, message="add Alpha")
    repo.tag("v0.1")
    repo.commit(ttl=CLASS_AB, message="add B")
    return open_history(repo.path / ONTOLOGY)


def _render(renderable) -> str:
    console = Console(width=200, file=io.StringIO(), no_color=True)
    console.print(renderable)
    return console.file.getvalue()


# ── the heading: what it says it did, then who did it ─────────────────────────


def test_the_heading_shows_the_subject_and_its_metadata(ontology_repo: RepoBuilder) -> None:
    history = _history(ontology_repo)

    shown = _render(_heading(history.rows[0]))

    assert "add B" in shown
    assert "Ada Lovelace" in shown
    assert history.rows[0].short_sha in shown


def test_the_heading_marks_a_tagged_release(ontology_repo: RepoBuilder) -> None:
    history = _history(ontology_repo)
    tagged = next(r for r in history.rows if r.tags)

    assert "v0.1" in _render(_heading(tagged))


def test_the_subject_and_the_metadata_are_on_separate_lines(
    ontology_repo: RepoBuilder,
) -> None:
    """The complaint was that description and metadata ran together."""
    history = _history(ontology_repo)

    lines = [ln for ln in _render(_heading(history.rows[0])).splitlines() if ln.strip()]

    assert any("add B" in ln and "Ada Lovelace" not in ln for ln in lines)


# ── the change list ───────────────────────────────────────────────────────────


def test_a_change_kind_is_named_in_words(ontology_repo: RepoBuilder) -> None:
    """A reader should not have to learn a key of +/-/~ glyphs first."""
    history = _history(ontology_repo)

    shown = _render(_changes(history, history.rows[0].sha))

    assert "added" in shown
    assert "class" in shown
    assert "ex:B" in shown


def test_a_label_is_shown_beside_its_identifier(ontology_repo: RepoBuilder) -> None:
    history = _history(ontology_repo)

    shown = _render(_changes(history, history.rows[1].sha))

    assert "Alpha" in shown
    assert "ex:A" in shown


def test_a_formatting_only_commit_says_it_was_reformatted(
    ontology_repo: RepoBuilder,
) -> None:
    ontology_repo.commit(ttl=CLASS_A, message="first")
    ontology_repo.commit(ttl='ex:A rdfs:label "Alpha"@en ; a owl:Class .', message="reformat")
    history = open_history(ontology_repo.path / ONTOLOGY)

    assert "reformatted" in _render(_changes(history, history.rows[0].sha))


def test_an_unreadable_revision_says_it_does_not_parse(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(ttl=CLASS_A, message="good")
    ontology_repo.commit(raw="not turtle {{{", message="broken")
    history = open_history(ontology_repo.path / ONTOLOGY)

    assert "does not parse" in _render(_changes(history, history.rows[0].sha))


def test_bulk_individuals_are_counted_against_their_class() -> None:
    from semanticdiff.render.rows import Row
    from semanticdiff.vocabulary import ChangeKind, EntityKind

    from ster.plugins.semanticdiff.screen import _change_name

    row = Row(
        kind=ChangeKind.ADDED,
        entity=EntityKind.INDIVIDUAL,
        name="294 individuals",
        count=294,
        of_class="City",
    )

    shown = _render(_change_name(row))

    assert "294 individuals" in shown
    assert "City" in shown


# ── the raw diff ──────────────────────────────────────────────────────────────


def test_added_and_removed_lines_are_told_apart() -> None:
    coloured = _diff_text("diff --git a/o.ttl b/o.ttl\n@@ -1 +1 @@\n-old\n+new\n")

    styles = {str(span.style) for span in coloured.spans}

    assert "green" in styles
    assert "red" in styles


# ── wiring ────────────────────────────────────────────────────────────────────


async def test_the_list_holds_one_row_per_commit(ontology_repo: RepoBuilder) -> None:
    app = HistoryScreen(_history(ontology_repo))

    async with app.run_test():
        assert app.query_one("#commits").row_count == 2


async def test_a_release_tag_is_shown_in_the_list(ontology_repo: RepoBuilder) -> None:
    app = HistoryScreen(_history(ontology_repo))

    async with app.run_test():
        table = app.query_one("#commits")
        # index 2: the list is when · who · commit, and the tag rides the commit cell
        cells = [str(table.get_row_at(i)[2]) for i in range(table.row_count)]

    assert any("v0.1" in c for c in cells), cells


async def test_the_raw_diff_is_put_away_on_open(ontology_repo: RepoBuilder) -> None:
    app = HistoryScreen(_history(ontology_repo))

    async with app.run_test():
        assert app.query_one("#raw").has_class("hidden-pane")


async def test_r_shows_the_raw_diff_and_r_again_puts_it_away(
    ontology_repo: RepoBuilder,
) -> None:
    app = HistoryScreen(_history(ontology_repo))

    async with app.run_test() as pilot:
        await pilot.press("r")
        assert not app.query_one("#raw").has_class("hidden-pane")
        await pilot.press("r")
        assert app.query_one("#raw").has_class("hidden-pane")


async def test_a_revision_is_read_off_the_ui_thread(ontology_repo: RepoBuilder) -> None:
    """Selecting must not block: the diff lands from a worker, not inline.

    The worker's *existence* is the property under test. Asserting it had not
    finished yet — ``history.computed == 0`` — asserted instead that the worker
    was slow, which is scheduling luck rather than a design guarantee, and it
    failed on a loaded runner roughly half the time. That the read really goes
    through the worker is covered by the test below, which waits for it.
    """
    history = _history(ontology_repo)
    app = HistoryScreen(history)

    async with app.run_test():
        assert app.workers


async def test_only_the_selected_commit_is_ever_read(ontology_repo: RepoBuilder) -> None:
    history = _history(ontology_repo)
    app = HistoryScreen(history)

    async with app.run_test() as pilot:
        for _ in range(20):
            await pilot.pause()
            if history.computed:
                break

    assert history.computed == 1
