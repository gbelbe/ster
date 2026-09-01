"""The graph app must finish initialising for every shape of ontology.

``graph_app.js`` is one big IIFE, so a bare ``return`` anywhere at its top level
abandons the rest of the setup instead of skipping a step. The edge-type filter
loop used one when an edge type was absent, which silently disabled everything
declared after it — the panel navigation wrappers, the hover overlay that is the
only route to the detail panel, and the live-refresh subscription — for any file
without instanceOf, inScheme or datatypeProperty edges. A pure-SKOS thesaurus
has no instanceOf edges, so it lost all of it.

Observed on a 600-concept GEMET subset before the fix:
    ft_instanceOf: true      (the button exists, so it is the zero-edge branch)
    _sterNav:  undefined     (declared 5 lines later, never reached)
    _sterBack: undefined
"""

from __future__ import annotations

import re

from ster.viz_vowl import _app_js

# The loop that walks optional edge-type filter buttons.
_LOOP_START = "for(const [t,id] of [['instanceOf'"


def _filter_loop_body() -> str:
    js = _app_js()
    start = js.index(_LOOP_START)
    # The loop now lives inside wireEdgeTypeFilters, so its own brace is indented;
    # the first brace in column zero closes that function and bounds the body.
    end = js.index("\n}", start)
    return js[start:end]


def test_edge_type_filter_loop_exists() -> None:
    """Guards the other tests: they are meaningless if the loop is renamed."""
    assert _LOOP_START in _app_js()


def test_edge_type_filter_loop_never_returns() -> None:
    """A `return` here exits the whole IIFE, not just the loop."""
    assert "return" not in _filter_loop_body()


def test_edge_type_filter_loop_skips_with_continue() -> None:
    """Both the missing-button and zero-edge branches must skip, not abort."""
    assert _filter_loop_body().count("continue") == 2


def test_panel_wrappers_are_declared_after_the_filter_loop() -> None:
    """Documents the blast radius: these are what a bare `return` used to skip.

    If they ever move above the loop this test is redundant rather than wrong,
    but the ordering is what made the bug invisible — the graph still rendered.
    """
    js = _app_js()

    assert js.index("globalThis._sterNav=") > js.index(_LOOP_START)


def test_no_bare_return_at_the_iife_top_level() -> None:
    """The general form of the bug: an unindented `return` outside any function.

    Top-level statements sit in column zero, so a `return` there belongs to the
    IIFE itself and truncates initialisation.
    """
    offenders = [
        line
        for line in _app_js().splitlines()
        if re.match(r"^return\b", line) or re.match(r"^\s{0,1}return\b", line)
    ]

    assert offenders == []


def test_the_filter_wiring_is_its_own_function() -> None:
    """The structural fix, not just the `continue`.

    Keeping this inline in the IIFE is what made a single early exit able to
    truncate the whole file. In a function the blast radius of an early exit is
    the function. It also keeps the IIFE's cognitive complexity under the limit —
    replacing the two `return`s with `continue`s pushed it from 16 to 18, because
    a `continue` is a counted flow break and a `return` is not.
    """
    js = _app_js()

    assert "function wireEdgeTypeFilters(){" in js
    assert "\nwireEdgeTypeFilters();" in js, "defining it is not enough — it must be called"
    assert js.index("function wireEdgeTypeFilters(){") < js.index(_LOOP_START) + 1


def test_the_filter_wiring_runs_before_the_panel_wrappers() -> None:
    """Extracting it must not reorder initialisation."""
    js = _app_js()

    assert js.index("\nwireEdgeTypeFilters();") < js.index("globalThis._sterNav=")
