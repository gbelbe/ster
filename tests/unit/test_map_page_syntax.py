"""The map page's script must parse.

`geo_map_html` is a few hundred lines of JavaScript living inside a Python
string, so nothing on the way to the browser ever parses it: ruff and mypy see
an opaque literal, and the page's own tests match substrings, which a broken
file still contains. A malformed comment shipped that way once — the closing
`*/` of one block left in the middle of the next, so every declaration after it
was bare text. The page served 200, the header and the buttons rendered from the
static markup, and the map came up empty with no console error anyone thought to
look for.

One `node --check` closes that hole for the whole file, not just for the feature
that exposed it. Skipped where node is absent rather than failed: it is a
sharper instrument than the suite can require everywhere.
"""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from ster.api import _DEFAULT_MAP_QUERY
from ster.geo_map_html import render_map_html
from tests._rendered_page import main_inline_script

# The page's own inline script: <script> blocks that pull a src are the CDN's.


def _inline_script(page: str) -> str:
    return main_inline_script(page, "map")


@pytest.mark.parametrize("show_all", [False, True])
def test_the_map_page_script_parses(tmp_path, show_all: bool) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; the syntax check needs a JS parser")

    script = tmp_path / "page.js"
    script.write_text(_inline_script(render_map_html(_DEFAULT_MAP_QUERY, "tok", show_all=show_all)))

    done = subprocess.run(  # noqa: S603
        [node, "--check", str(script)], capture_output=True, text=True, check=False
    )

    assert done.returncode == 0, f"the map page's script does not parse:\n{done.stderr}"


def test_every_comment_block_in_the_page_is_closed() -> None:
    """The specific trap, named so it fails with a useful message rather than as
    a parse error a hundred lines further down."""
    script = _inline_script(render_map_html(_DEFAULT_MAP_QUERY, "tok"))
    stripped = re.sub(r"/\*.*?\*/", "", script, flags=re.S)

    assert "*/" not in stripped, "a stray */ — some comment block was closed twice"
    assert "/*" not in stripped, "an unclosed /* comment block"
