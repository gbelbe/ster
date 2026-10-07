"""A place that totals something has that number printed on it, not only in its tooltip.

The page is JavaScript inside a Python string, so these assert on its source (as the neighbouring map tests do)
and run the one pure function, ``figureOf``, under node, which is where the rule lives.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from ster.api import _DEFAULT_MAP_QUERY
from ster.geo_map_html import render_map_html

NODE = shutil.which("node")


def _page() -> str:
    return render_map_html(_DEFAULT_MAP_QUERY, "tok")


def _figure_of(total: float, measured: bool) -> str | None:
    """Run the page's own figureOf with a fixed number formatter."""
    source = re.search(r"function figureOf\(.*?\n\}\n", _page(), flags=re.S)
    assert source, "the page no longer defines figureOf"
    program = f"const fmt = new Intl.NumberFormat('en'); {source.group(0)} console.log(JSON.stringify(figureOf({json.dumps(total)}, {json.dumps(measured)})));"
    out = subprocess.run([NODE, "-e", program], capture_output=True, text=True, check=True)  # type: ignore[list-item]
    return json.loads(out.stdout)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_a_total_is_printed_when_a_measure_was_chosen():
    assert _figure_of(1, True) == "1"
    assert _figure_of(1234, True) == "1,234"
    assert _figure_of(0, True) == "0"


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_without_a_measure_only_an_aggregate_is_printed():
    assert _figure_of(1, False) is None  # one row counting nothing
    assert _figure_of(2, False) == "2"  # a cluster of rows
    assert _figure_of(48, False) == "48"


def test_the_number_is_drawn_above_the_shapes_and_the_dots():
    body = _page()
    assert "const figures = [];" in body
    assert "layer = L.featureGroup([...marks, ...figures]).addTo(map);" in body
    assert "className: 'figure-label'" in body


def test_a_place_drawn_as_its_own_picture_is_not_labelled_but_an_outline_with_a_flag_is():
    body = _page()
    assert (
        "const drawnAsPicture = lone !== null && !!lone.icon && !(shapeMode && lone.shape);" in body
    )
    assert "if (figure !== null && !drawnAsPicture)" in body


def test_the_label_is_readable_on_pale_and_dark_shapes_and_does_not_catch_clicks():
    body = _page()
    assert ".figure-label { pointer-events:none; }" in body
    assert "background:rgba(0,0,0,.62)" in body
    assert "interactive: false" in body


def test_a_number_is_lifted_clear_of_the_logos_a_place_carries():
    body = _page()
    assert "const FIGURE_LIFT = 36;" in body
    assert "members.some(m => (m.badges || []).length > 0) ? FIGURE_LIFT : 0" in body
    assert "iconAnchor: [0, lift]" in body
