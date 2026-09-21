"""Unit tests for the working-file role swap (``ster.working_file``).

The swap is deliberately a pure function over paths: which file is writable is
a *session* fact, not a taxonomy mutation, so it needs no model, no service and
no TUI to decide — which is what lets the BDD scenarios run headless.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ster.working_file import UnknownWorkingFile, switch_roles

GEAR = Path("gear.ttl")
PLACES = Path("places.ttl")
META = Path("meta.ttl")


def test_switch_promotes_chosen_file():
    editable, _ = switch_roles(PLACES, loaded=[GEAR, PLACES])
    assert editable == PLACES


def test_switch_demotes_current_to_context():
    _, context = switch_roles(PLACES, loaded=[GEAR, PLACES])
    assert GEAR in context


def test_switch_preserves_other_context_files():
    _, context = switch_roles(PLACES, loaded=[GEAR, PLACES, META])
    assert set(context) == {GEAR, META}


def test_switch_to_current_file_is_a_noop():
    editable, context = switch_roles(GEAR, loaded=[GEAR, PLACES])
    assert (editable, context) == (GEAR, [PLACES])


def test_switch_to_unknown_file_raises():
    with pytest.raises(UnknownWorkingFile):
        switch_roles(Path("absent.ttl"), loaded=[GEAR, PLACES])


def test_switch_context_order_is_stable():
    """The menu is rebuilt from this list on every open; a set would reshuffle
    the rows between openings and make the control feel unreliable."""
    _, first = switch_roles(PLACES, loaded=[GEAR, PLACES, META])
    _, second = switch_roles(PLACES, loaded=[GEAR, PLACES, META])
    assert first == second == [GEAR, META]
