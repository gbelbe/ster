"""Clustering by a result column must survive places that have no row.

The map holds two kinds of point. A *result* row is something the query asked
for and has an index into the result table. A *context* place — a country pulled
in only so the results have something to group under — has ``row: null``, because
the query never returned it.

Grouping read ``rows[p.row][groupBy]`` for every visible point. For a context
place that is ``rows[null]``, i.e. ``undefined``, so the lookup threw a
TypeError out of draw() and the map came back empty with nothing on screen to
explain it — selecting "cluster by city" from the continent level blanked it.

Source assertions: they catch a missing guard, never a rendering fault. The
behaviour was also driven in a browser, where the exception was read from the
console before and confirmed absent after.
"""

from __future__ import annotations

import re

from ster import geo_map_html

PAGE = geo_map_html._PAGE


def test_a_row_lookup_never_indexes_the_table_with_a_null_row() -> None:
    """The exact expression that threw: rows[p.row][...] with no guard."""
    unguarded = re.findall(r"rows\[p\.row\]\[", PAGE)

    assert not unguarded, f"{len(unguarded)} unguarded row lookup(s) remain"


def test_a_place_with_no_row_resolves_to_null_rather_than_undefined() -> None:
    assert "const rowOf = p =>" in PAGE
    assert "p.row === null || p.row === undefined" in PAGE


def test_grouping_reads_the_whole_result_not_the_current_level() -> None:
    """Clustering by a column is an alternative to the hierarchy, not a filter
    inside it. Intersecting the two emptied the map at any level holding only
    context places — which is every level above the rows themselves.

    The other branch is placesToDraw(), not atLevel(), since the Levels/Everything
    switch chooses what the hierarchy shows; clustering still overrides both.
    """
    assert "groupBy !== null ? points.filter(p => rowOf(p) !== null) : placesToDraw()" in PAGE


def test_context_places_are_excluded_from_a_column_grouping() -> None:
    """They have no value in a result column, so they cannot be grouped by one."""
    assert "points.filter(p => rowOf(p) !== null)" in PAGE
