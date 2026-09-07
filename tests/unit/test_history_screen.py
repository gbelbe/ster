"""The history screen: a commit list, a semantic view, and the raw text on ask."""

from __future__ import annotations

from ster.history import open_history
from ster.tui.history_screen import HistoryScreen
from tests._ontology_repo import ONTOLOGY, RepoBuilder

CLASS_A = "ex:A a owl:Class ."
CLASS_AB = "ex:A a owl:Class . ex:B a owl:Class ."


def _history(repo: RepoBuilder):
    repo.commit(ttl=CLASS_A, message="add A")
    repo.tag("v0.1")
    repo.commit(ttl=CLASS_AB, message="add B")
    return open_history(repo.path / ONTOLOGY)


async def test_the_list_holds_one_row_per_commit(ontology_repo: RepoBuilder) -> None:
    app = HistoryScreen(_history(ontology_repo))

    async with app.run_test():
        assert app.query_one("#commits").row_count == 2


async def test_a_release_tag_is_shown_beside_the_commit_it_marks(
    ontology_repo: RepoBuilder,
) -> None:
    app = HistoryScreen(_history(ontology_repo))

    async with app.run_test():
        table = app.query_one("#commits")
        cells = [table.get_row_at(i)[1] for i in range(table.row_count)]

    assert any("[v0.1]" in c for c in cells), cells


async def test_the_newest_commit_is_shown_on_open(ontology_repo: RepoBuilder) -> None:
    app = HistoryScreen(_history(ontology_repo))

    async with app.run_test():
        assert "ex:B" in str(app.query_one("#semantic").render())


async def test_the_raw_diff_is_put_away_on_open(ontology_repo: RepoBuilder) -> None:
    app = HistoryScreen(_history(ontology_repo))

    async with app.run_test():
        assert app.query_one("#raw").has_class("raw-hidden")


async def test_r_shows_the_raw_diff(ontology_repo: RepoBuilder) -> None:
    app = HistoryScreen(_history(ontology_repo))

    async with app.run_test() as pilot:
        await pilot.press("r")
        raw = app.query_one("#raw")

        assert not raw.has_class("raw-hidden")
        assert "diff --git" in str(raw.render())


async def test_r_again_puts_it_away(ontology_repo: RepoBuilder) -> None:
    app = HistoryScreen(_history(ontology_repo))

    async with app.run_test() as pilot:
        await pilot.press("r")
        await pilot.press("r")

        assert app.query_one("#raw").has_class("raw-hidden")


async def test_opening_the_screen_diffs_only_the_selected_commit(
    ontology_repo: RepoBuilder,
) -> None:
    """Two commits, one diff — the list must not pay for every revision."""
    history = _history(ontology_repo)
    app = HistoryScreen(history)

    async with app.run_test():
        pass

    assert history.computed == 1


async def test_moving_down_shows_the_older_commit(ontology_repo: RepoBuilder) -> None:
    app = HistoryScreen(_history(ontology_repo))

    async with app.run_test() as pilot:
        await pilot.press("down")

        assert "ex:A" in str(app.query_one("#semantic").render())
