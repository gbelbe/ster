"""Node labels are plain black, and every fill is light enough to carry them.

The old fills assumed a 2.5px white text-outline behind every label — that
outline was doing the legibility work, and once it went four of the six fills
failed WCAG AA against black text:

    class        #3c6ebf  4.17:1  →  #a9c7ea  12.0:1
    root class   (as class)       →  #93b8e4  10.2:1
    scheme       #7c3aed  3.69:1  →  #cbb8f9  11.8:1
    top concept  #0e7490  3.92:1  →  #8fd6ef  13.0:1
    concept      #166534  2.95:1  →  #9fe3b6  14.1:1
    individual   #7fb8e0  9.83:1  →  #c6e2f5  15.6:1

Each type's original hue moved to its border, so the types stay as
distinguishable as they were while the fills went pale enough to read on.
"""

from __future__ import annotations

import re

import pytest

from ster.viz_vowl import _app_js

_AA_NORMAL_TEXT = 4.5


def _relative_luminance(hex_colour: str) -> float:
    raw = hex_colour.lstrip("#")
    channels = [int(raw[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_with_black(hex_colour: str) -> float:
    return (_relative_luminance(hex_colour) + 0.05) / 0.05


def _fills() -> dict[str, str]:
    js = _app_js()
    out: dict[str, str] = {}
    for selector, fill in re.findall(
        r"selector:'node\[type=\"(\w+)\"\][^']*',style:\{[^}]*'background-color':'(#[0-9a-fA-F]{6})'",
        js,
    ):
        out.setdefault(selector, fill)
    return out


def test_the_white_outline_is_gone():
    """It was propping up four failing fills."""
    assert "text-outline" not in _app_js()


def test_labels_are_plain_black():
    assert "'color':'#000000'" in _app_js().replace(" ", "")


@pytest.mark.parametrize("node_type", ["class", "individual", "scheme", "topconcept", "concept"])
def test_every_fill_carries_black_text(node_type):
    fill = _fills()[node_type]

    assert _contrast_with_black(fill) >= _AA_NORMAL_TEXT, f"{node_type} {fill}"


def test_the_root_class_fill_also_passes():
    js = _app_js().replace(" ", "")
    match = re.search(r"rootClass=1\]',style:\{[^}]*'background-color':'(#[0-9a-fA-F]{6})'", js)

    assert match is not None
    assert _contrast_with_black(match.group(1)) >= _AA_NORMAL_TEXT


def test_the_type_hues_survive_on_the_borders():
    """Pale fills would make every node look alike if the hue went with them."""
    js = _app_js().replace(" ", "")

    assert "'background-color':'#a9c7ea','border-color':'#3c6ebf'" in js
    assert "'background-color':'#9fe3b6','border-color':'#166534'" in js
