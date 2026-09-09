"""Cache-miss / successful-fetch path for the vendored JS script-tag helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ster.viz_vowl import _js_assets


@pytest.mark.parametrize(
    "func_name,cdn_attr",
    [
        ("_cytoscape_script_tag", "_CY_CDN"),
        ("_d3_hierarchy_script_tag", "_D3_HIERARCHY_CDN"),
        ("_d3_path_script_tag", "_D3_PATH_CDN"),
        ("_d3_shape_script_tag", "_D3_SHAPE_CDN"),
        ("_layout_base_script_tag", "_LAYOUT_BASE_CDN"),
        ("_cose_base_script_tag", "_COSE_BASE_CDN"),
        ("_fcose_script_tag", "_FCOSE_CDN"),
        ("_expand_collapse_script_tag", "_EXPAND_COLLAPSE_CDN"),
    ],
)
def test_script_tag_fetches_and_caches_on_first_call(tmp_path, func_name, cdn_attr):
    """On a cache miss, the library is downloaded, written to the cache dir, and
    the returned tag inlines its contents (not just a src= to the CDN)."""
    with patch("ster.viz_vowl._query_result.Path.home", return_value=tmp_path):
        response = MagicMock()
        response.read.return_value = b"/* fake lib body */"
        response.__enter__ = lambda s: s
        response.__exit__ = MagicMock(return_value=False)
        with patch("ster.viz_vowl._js_assets.urllib.request.urlopen", return_value=response):
            tag = getattr(_js_assets, func_name)()

    assert "<script>" in tag
    assert "/* fake lib body */" in tag
    assert getattr(_js_assets, cdn_attr) not in tag  # inlined, not a src= reference
