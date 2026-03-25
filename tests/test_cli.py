"""Tests for CLI helper functions."""
from __future__ import annotations
import pytest
from ster.cli import _humanize


@pytest.mark.parametrize("name,expected", [
    ("SpadeRudder", "Spade Rudder"),
    ("trimTabOnRudder", "Trim Tab On Rudder"),
    ("HTTP", "HTTP"),
    ("myConceptName", "My Concept Name"),
    ("https://example.org/ns/SpadeRudder", "Spade Rudder"),
    ("https://example.org/ns#SpadeRudder", "Spade Rudder"),
    ("SimpleName", "Simple Name"),
    ("alreadylower", "Alreadylower"),
])
def test_humanize(name, expected):
    assert _humanize(name) == expected
