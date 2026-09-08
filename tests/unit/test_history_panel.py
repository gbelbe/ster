"""The semantic history, as something you can actually read.

The commit list carried a date and a subject in 44 columns, which truncated the
subject to the point of uselessness and never said who made the commit. And the
date alone cannot separate two commits landing on one afternoon — exactly when
a reader is trying to work out what happened in which order.
"""

from __future__ import annotations

from ster.history import HistoryRow
from ster.tui.history_screen import HistoryScreen, _short_author


def _row(**kw) -> HistoryRow:
    base = {
        "sha": "a" * 40,
        "short_sha": "aaaaaaa",
        "author": "Gaetan Belbeoc'h",
        "date": "2026-05-06T22:42:57+02:00",
        "subject": "feat(store): never lose a triple the model cannot describe",
    }
    return HistoryRow(**{**base, **kw})


def test_the_timestamp_carries_the_time() -> None:
    """Two commits in one afternoon have to be tellable apart."""
    assert _row().when == "2026-05-06 22:42"


def test_the_day_is_still_available_for_narrow_places() -> None:
    assert _row().day == "2026-05-06"


def test_a_committer_fits_the_column() -> None:
    assert _short_author("Gaetan Belbeoc'h") == "Gaetan B."
    assert _short_author("Bo") == "Bo"


def test_a_one_word_name_is_not_mangled() -> None:
    assert _short_author("Aristotelis") == "Aristotelis"


def test_a_very_long_single_word_is_cut_not_dotted() -> None:
    """There is no surname to abbreviate to."""
    assert _short_author("A" * 30) == "A" * 14


def test_the_list_names_who_as_well_as_when_and_what() -> None:
    css_and_source = HistoryScreen.CSS
    from pathlib import Path

    source = Path(HistoryScreen.__module__.replace(".", "/") + ".py")
    text = source.read_text(encoding="utf-8") if source.exists() else ""

    assert 'table.add_columns("when", "who", "commit")' in text
    assert "#commits { width: 52%" in css_and_source


def test_both_columns_run_the_full_height() -> None:
    """A pane that stops short leaves the reader scrolling a stub."""
    assert "#commits { width: 52%; height: 1fr;" in HistoryScreen.CSS
    assert "#panes { width: 1fr; height: 1fr; }" in HistoryScreen.CSS
