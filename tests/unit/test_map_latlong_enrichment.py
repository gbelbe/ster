"""A query that selects ?lat and ?long still gets what the ontology says about each entity: its picture, its facets, its logos.

``locate`` took the coordinates from the columns and returned at once, so a store query with ``?lat ?long`` was drawn
as plain dots while the same stores, asked for without coordinates, came out as their pictures. The page is JavaScript
in a Python string, so the function runs under node with the server call stubbed.
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
STORE = "https://example.org/s#store-1"

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def _locate(
    columns: list[str], rows: list[list[str]], known: list[dict]
) -> tuple[list[dict], list[list[str]]]:
    """Run the page's own `locate` against a stubbed server that knows *known*; also say what it was asked."""
    page = render_map_html(_DEFAULT_MAP_QUERY, "tok")
    source = re.search(
        r"async function locate\(cols, data\) \{.*?\n\}\n(?=\nlet overlayLayers)", page, flags=re.S
    )
    assert source, "the page no longer defines locate"
    program = f"""
      const asked = [];
      const isUri = v => typeof v === 'string' && /^(https?:|urn:)/.test(v);
      const num = v => {{ const n = Number(v); return Number.isFinite(n) ? n : null; }};
      const short = v => String(v).split(/[#/]/).filter(Boolean).pop();
      const plain = v => String(v);
      const locateOnServer = async uris => {{ asked.push(uris); return {json.dumps(known)}; }};
      {source.group(0)}
      locate({json.dumps(columns)}, {json.dumps(rows)}).then(out => console.log(JSON.stringify([out, asked])));
    """
    out = subprocess.run([NODE, "-e", program], capture_output=True, text=True, check=True)  # type: ignore[list-item]
    return json.loads(out.stdout)


KNOWN = [
    {
        "uri": STORE,
        "lat": 1.0,
        "long": 2.0,
        "icon": "data:image/svg+xml,pin",
        "facets": {"C": ["V"]},
        "badges": [{"uri": "b"}],
    }
]


def test_a_row_with_coordinates_and_an_entity_gets_its_picture_facets_and_logos():
    points, _asked = _locate(
        ["store", "label", "lat", "long"], [[STORE, "Store 1", "50.5", "3.1"]], KNOWN
    )
    [point] = points
    assert point["icon"] == "data:image/svg+xml,pin"
    assert point["facets"] == {"C": ["V"]}
    assert point["badges"] == [{"uri": "b"}]


def test_the_coordinates_stay_the_ones_in_the_columns():
    points, _ = _locate(
        ["store", "label", "lat", "long"], [[STORE, "Store 1", "50.5", "3.1"]], KNOWN
    )
    assert (points[0]["lat"], points[0]["long"]) == (50.5, 3.1)  # not the server's 1.0, 2.0
    assert points[0]["label"] == "Store 1"


def test_the_server_is_asked_once_about_the_distinct_entities():
    rows = [[STORE, "a", "50.5", "3.1"], [STORE, "b", "50.6", "3.2"]]
    _, asked = _locate(["store", "label", "lat", "long"], rows, KNOWN)
    assert asked == [[STORE]]


def test_a_row_the_server_does_not_know_stays_a_plain_point():
    other = "https://example.org/s#unknown"
    points, _ = _locate(["store", "label", "lat", "long"], [[other, "x", "50.5", "3.1"]], KNOWN)
    assert "icon" not in points[0]


def test_bare_coordinates_with_no_entity_ask_the_server_nothing():
    points, asked = _locate(["label", "lat", "long"], [["somewhere", "50.5", "3.1"]], KNOWN)
    assert asked == []
    assert len(points) == 1


def test_a_row_without_usable_coordinates_is_still_dropped():
    points, _ = _locate(["store", "lat", "long"], [[STORE, "n/a", "3.1"]], KNOWN)
    assert points == []
