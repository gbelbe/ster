"""Cytoscape/D3 JS dependency script tags and inline app JS."""

from __future__ import annotations

import functools
import urllib.parse
import urllib.request
from typing import Final

from ..viz import (
    _label_for,  # noqa: F401  (re-exported for potential callers)
)
from . import _query_result

_LIT_SRC_CLOSE: Final = '"></script>'
_LIT_SCRIPT_CLOSE: Final = "</script>"
_LIT_SCRIPT_SRC: Final = '<script src="'
_LIT_SCRIPT_OPEN: Final = "<script>"


_CY_VERSION = "3.29.2"

_CY_CDN = f"https://cdnjs.cloudflare.com/ajax/libs/cytoscape/{_CY_VERSION}/cytoscape.min.js"

_CY_CACHE_FILE = "cytoscape.min.js"  # stored under ~/.cache/ster/


def _cytoscape_script_tag() -> str:
    """Return an inline <script> tag with Cytoscape.js, downloading once to ~/.cache/ster.

    This is the *vendored library* layer, kept deliberately separate from ster's
    own graph code (:func:`_app_js`): swapping the library here — e.g. on a
    version bump — must never touch the application layer.
    """
    cache_dir = _query_result._ster_cache_dir()
    cy_path = cache_dir / _CY_CACHE_FILE
    if not cy_path.exists():
        try:
            with urllib.request.urlopen(_CY_CDN, timeout=15) as resp:  # type: ignore[attr-defined]
                cy_path.write_bytes(resp.read())
        except Exception:
            return f"{_LIT_SCRIPT_SRC}{_CY_CDN}{_LIT_SRC_CLOSE}"
    return f"{_LIT_SCRIPT_OPEN}{cy_path.read_text()}{_LIT_SCRIPT_CLOSE}"


_D3_HIERARCHY_VERSION = "3.1.2"

_D3_HIERARCHY_CDN = (
    f"https://cdn.jsdelivr.net/npm/d3-hierarchy@{_D3_HIERARCHY_VERSION}/dist/d3-hierarchy.min.js"
)

_D3_HIERARCHY_CACHE_FILE = "d3-hierarchy.min.js"  # stored under ~/.cache/ster/


def _d3_hierarchy_script_tag() -> str:
    """Return an inline <script> tag with d3-hierarchy, downloading once to ~/.cache/ster.

    Mirrors :func:`_cytoscape_script_tag` exactly: the vendored library stays
    separate from ster's own treemap code (:func:`_treemap_js`), so a version
    bump here can never touch the application layer, and the treemap keeps
    working offline once this file is cached.
    """
    cache_dir = _query_result._ster_cache_dir()
    d3_path = cache_dir / _D3_HIERARCHY_CACHE_FILE
    if not d3_path.exists():
        try:
            with urllib.request.urlopen(_D3_HIERARCHY_CDN, timeout=15) as resp:  # type: ignore[attr-defined]
                d3_path.write_bytes(resp.read())
        except Exception:
            return f"{_LIT_SCRIPT_SRC}{_D3_HIERARCHY_CDN}{_LIT_SRC_CLOSE}"
    return f"{_LIT_SCRIPT_OPEN}{d3_path.read_text()}{_LIT_SCRIPT_CLOSE}"


_D3_PATH_VERSION = "3.1.0"

_D3_PATH_CDN = f"https://cdn.jsdelivr.net/npm/d3-path@{_D3_PATH_VERSION}/dist/d3-path.min.js"

_D3_PATH_CACHE_FILE = "d3-path.min.js"  # stored under ~/.cache/ster/


def _d3_path_script_tag() -> str:
    """Return an inline <script> tag with d3-path, downloading once to ~/.cache/ster.

    Mirrors :func:`_d3_hierarchy_script_tag`. Exists solely as d3-shape's own
    dependency (see :func:`_d3_shape_script_tag`) — nothing in ster's own code
    calls into it directly.
    """
    cache_dir = _query_result._ster_cache_dir()
    d3_path_path = cache_dir / _D3_PATH_CACHE_FILE
    if not d3_path_path.exists():
        try:
            with urllib.request.urlopen(_D3_PATH_CDN, timeout=15) as resp:  # type: ignore[attr-defined]
                d3_path_path.write_bytes(resp.read())
        except Exception:
            return f"{_LIT_SCRIPT_SRC}{_D3_PATH_CDN}{_LIT_SRC_CLOSE}"
    return f"{_LIT_SCRIPT_OPEN}{d3_path_path.read_text()}{_LIT_SCRIPT_CLOSE}"


_D3_SHAPE_VERSION = "3.2.0"

_D3_SHAPE_CDN = f"https://cdn.jsdelivr.net/npm/d3-shape@{_D3_SHAPE_VERSION}/dist/d3-shape.min.js"

_D3_SHAPE_CACHE_FILE = "d3-shape.min.js"  # stored under ~/.cache/ster/


def _d3_shape_script_tag() -> str:
    """Return an inline <script> tag with d3-shape, downloading once to ~/.cache/ster.

    Mirrors :func:`_d3_hierarchy_script_tag`. The treemap app used to hand-roll
    its own radial/horizontal link-path construction to avoid this dependency;
    that reimplementation is exactly what produced the "teardrop" curve bug
    (interpolating control points at the wrong midpoint), which d3-shape's own
    ``linkRadial``/``linkHorizontal`` never had. Since d3-hierarchy is already
    vendored for the layout math, pulling in this small, dependency-free sibling
    module for the one thing it does better costs little and removes a whole
    class of bug the hand-rolled version already hit once.
    """
    cache_dir = _query_result._ster_cache_dir()
    d3_path = cache_dir / _D3_SHAPE_CACHE_FILE
    if not d3_path.exists():
        try:
            with urllib.request.urlopen(_D3_SHAPE_CDN, timeout=15) as resp:  # type: ignore[attr-defined]
                d3_path.write_bytes(resp.read())
        except Exception:
            return f"{_LIT_SCRIPT_SRC}{_D3_SHAPE_CDN}{_LIT_SRC_CLOSE}"
    return f"{_LIT_SCRIPT_OPEN}{d3_path.read_text()}{_LIT_SCRIPT_CLOSE}"


_LAYOUT_BASE_VERSION = "2.0.1"

_LAYOUT_BASE_CDN = f"https://cdn.jsdelivr.net/npm/layout-base@{_LAYOUT_BASE_VERSION}/layout-base.js"

_LAYOUT_BASE_CACHE_FILE = "layout-base.js"  # stored under ~/.cache/ster/


def _layout_base_script_tag() -> str:
    """Return an inline <script> tag with layout-base, downloading once to ~/.cache/ster.

    A dependency of cose-base/fcose (see :func:`_fcose_script_tag`) — nothing in
    ster's own code calls into it directly. Mirrors :func:`_cytoscape_script_tag`.
    """
    cache_dir = _query_result._ster_cache_dir()
    lb_path = cache_dir / _LAYOUT_BASE_CACHE_FILE
    if not lb_path.exists():
        try:
            with urllib.request.urlopen(_LAYOUT_BASE_CDN, timeout=15) as resp:  # type: ignore[attr-defined]
                lb_path.write_bytes(resp.read())
        except Exception:
            return f"{_LIT_SCRIPT_SRC}{_LAYOUT_BASE_CDN}{_LIT_SRC_CLOSE}"
    return f"{_LIT_SCRIPT_OPEN}{lb_path.read_text()}{_LIT_SCRIPT_CLOSE}"


_COSE_BASE_VERSION = "2.2.0"

_COSE_BASE_CDN = f"https://cdn.jsdelivr.net/npm/cose-base@{_COSE_BASE_VERSION}/cose-base.js"

_COSE_BASE_CACHE_FILE = "cose-base.js"  # stored under ~/.cache/ster/


def _cose_base_script_tag() -> str:
    """Return an inline <script> tag with cose-base, downloading once to ~/.cache/ster.

    A dependency of fcose (see :func:`_fcose_script_tag`), which itself depends
    on :func:`_layout_base_script_tag` — load order matters, see
    :func:`_cytoscape_script_tag` for the vendored-library rationale.
    """
    cache_dir = _query_result._ster_cache_dir()
    cb_path = cache_dir / _COSE_BASE_CACHE_FILE
    if not cb_path.exists():
        try:
            with urllib.request.urlopen(_COSE_BASE_CDN, timeout=15) as resp:  # type: ignore[attr-defined]
                cb_path.write_bytes(resp.read())
        except Exception:
            return f"{_LIT_SCRIPT_SRC}{_COSE_BASE_CDN}{_LIT_SRC_CLOSE}"
    return f"{_LIT_SCRIPT_OPEN}{cb_path.read_text()}{_LIT_SCRIPT_CLOSE}"


_FCOSE_VERSION = "2.2.0"

_FCOSE_CDN = f"https://cdn.jsdelivr.net/npm/cytoscape-fcose@{_FCOSE_VERSION}/cytoscape-fcose.js"

_FCOSE_CACHE_FILE = "cytoscape-fcose.js"  # stored under ~/.cache/ster/


def _fcose_script_tag() -> str:
    """Return an inline <script> tag with cytoscape-fcose (fast Compound Spring
    Embedder), downloading once to ~/.cache/ster.

    The graph view's default `cose` layout costs grow far faster than linearly
    in node count (see docs/architecture/graph-editor.md) — fcose is the
    same lab's (iVis-at-Bilkent) purpose-built replacement for large/compound
    graphs. Must load after :func:`_layout_base_script_tag` and
    :func:`_cose_base_script_tag`, its own dependencies; registers itself on
    `cytoscape` automatically in a plain-script context (no `cytoscape.use()`
    call needed).
    """
    cache_dir = _query_result._ster_cache_dir()
    fc_path = cache_dir / _FCOSE_CACHE_FILE
    if not fc_path.exists():
        try:
            with urllib.request.urlopen(_FCOSE_CDN, timeout=15) as resp:  # type: ignore[attr-defined]
                fc_path.write_bytes(resp.read())
        except Exception:
            return f"{_LIT_SCRIPT_SRC}{_FCOSE_CDN}{_LIT_SRC_CLOSE}"
    return f"{_LIT_SCRIPT_OPEN}{fc_path.read_text()}{_LIT_SCRIPT_CLOSE}"


_EXPAND_COLLAPSE_VERSION = "4.1.1"

_EXPAND_COLLAPSE_CDN = (
    "https://cdn.jsdelivr.net/npm/cytoscape-expand-collapse@"
    f"{_EXPAND_COLLAPSE_VERSION}/cytoscape-expand-collapse.js"
)

_EXPAND_COLLAPSE_CACHE_FILE = "cytoscape-expand-collapse.js"  # stored under ~/.cache/ster/


def _expand_collapse_script_tag() -> str:
    """Return an inline <script> tag with cytoscape-expand-collapse, downloading
    once to ~/.cache/ster.

    Lets a compound node (a class, standing in for its subtree) fold/unfold on
    the canvas — the class-hierarchy equivalent of the individual-collapsing
    the graph view already does (see docs/architecture/graph-editor.md).
    """
    cache_dir = _query_result._ster_cache_dir()
    ec_path = cache_dir / _EXPAND_COLLAPSE_CACHE_FILE
    if not ec_path.exists():
        try:
            with urllib.request.urlopen(_EXPAND_COLLAPSE_CDN, timeout=15) as resp:  # type: ignore[attr-defined]
                ec_path.write_bytes(resp.read())
        except Exception:
            return f"{_LIT_SCRIPT_SRC}{_EXPAND_COLLAPSE_CDN}{_LIT_SRC_CLOSE}"
    return f"{_LIT_SCRIPT_OPEN}{ec_path.read_text()}{_LIT_SCRIPT_CLOSE}"


@functools.lru_cache(maxsize=1)
def _app_js() -> str:
    """Return ster's graph *application* layer (interaction, styling, filtering,
    live update, detail panels) as JavaScript source.

    Lives in the versioned repo asset ``ster/assets/graph_app.js`` so it is fully
    decoupled from the vendored Cytoscape library: a library upgrade can never
    overwrite it. The code uses only the public ``cytoscape(...)`` factory and
    reads its per-render data from the injected ``window.__STER_GRAPH__`` global.
    """
    from importlib.resources import files  # noqa: PLC0415

    return (files("ster") / "assets" / "graph_app.js").read_text(encoding="utf-8")


@functools.lru_cache(maxsize=1)
def _treemap_js() -> str:
    """Return ster's treemap *application* layer (render/zoom/search/filter/detail)
    as JavaScript source, fully decoupled from the vendored d3-hierarchy library —
    mirrors :func:`_app_js`. Reads its per-render data from
    ``window.__STER_GRAPH__.taxonomy``.
    """
    from importlib.resources import files  # noqa: PLC0415

    return (files("ster") / "assets" / "taxonomy_app.js").read_text(encoding="utf-8")
