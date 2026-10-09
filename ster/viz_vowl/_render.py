"""Top-level render/open/push entry points: render_vowl_html, open_in_browser,
push_update, open_focused_in_browser, ensure_published_server.

Every "open" here requires ster's live server. There is no static, read-only
fallback: a caller that cannot start the server gets a clear error naming why
(see ``ster.viz_vowl._server.unavailable_reason``) rather than a page that
silently lost its interactivity."""

from __future__ import annotations

import html as _html
import urllib.parse
import urllib.request
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from ..model import Taxonomy
from ..taxonomy_treemap import build_taxonomy_treemap, has_taxonomy
from ..viz import (
    _label_for,  # noqa: F401  (re-exported for potential callers)
    _local,
    _ontology_title,
    _taxonomy_meta,
)
from . import _detail, _graph_builders, _html_template, _js_assets, _server

_LIT_UTF_8: Final = "utf-8"


# Raises the spinner before navigating: the unscoped graph is the slowest thing
# the view can be asked for — the server rebuilds it, then the browser parses and
# lays out every node — and without this the button simply appeared to do nothing
# for several seconds.
_SHOW_ALL_BTN_HTML = (
    '<span style="color:#cbd5e1"> │ </span>'
    '<button class="ftbtn active" '
    "onclick=\"if(globalThis.showSpinner)showSpinner('Loading every node\\u2026');"
    "location.href=location.pathname+'?full=1'\">"
    "Show all nodes</button>"
)


def render_vowl_html(
    taxonomy: Taxonomy,
    file_path: Path | None,
    api_token: str = "",
    root_uri: str | None = None,
    full: bool = False,
    sparql: str = "",
) -> str:
    """Return the rendered VOWL HTML string.

    When *api_token* is non-empty the page connects to the SSE stream so the
    Graph view refreshes automatically whenever the ontology file changes.
    When *root_uri* is given a focused subgraph centred on that class is
    rendered. Otherwise the default is root-level only (schemes, root
    classes, top concepts) when a server backs the page — *full* opts back
    into the unscoped graph, and a "Show all nodes" button offers the same.
    """
    from ..api_server import load_graph_viz_config  # noqa: PLC0415 - avoids an import cycle

    # Read once per render, not per builder call: the thresholds are a user
    # setting (ster setup → Graph Viz), and one page should be laid out by one
    # consistent set of them even if the file changes underneath.
    _viz_limits = load_graph_viz_config()
    title = _ontology_title(taxonomy, file_path)
    show_all_btn = ""
    if sparql.strip():
        # A query replaces the model walk entirely, exactly as /api/graph?q does
        # — same payload, so the page renders it without knowing which produced
        # it. Not scoped and not collapsed: you asked for these triples, so
        # holding some of them back would answer a question you did not ask.
        from ._from_query import graph_from_query  # noqa: PLC0415

        graph = graph_from_query(taxonomy, sparql)
    elif root_uri:
        root_cls = taxonomy.owl_classes.get(root_uri)
        root_label = root_cls.label("en") if root_cls else _local(root_uri)
        title = f"{title} — {root_label}"
        graph = _graph_builders.build_focused_vowl_graph(taxonomy, root_uri)
    elif api_token and not full:
        # Root-level overview: a large ontology rendered whole is a wall of
        # dots, not a graph (see docs/architecture/graph-editor.md). Only
        # done when a server backs the page — the offline/static export has
        # no click-to-expand endpoint, so it always gets the full graph
        # below, same as it always has. build_default_vowl_graph is itself
        # a no-op below CLASS_COLLAPSE_LIMIT (small ontology, nothing to
        # scope) — the button mirrors that, and individuals still get
        # collapsed below their own separate threshold either way.
        graph = _detail.collapse_individuals(
            _graph_builders.build_default_vowl_graph(taxonomy, _viz_limits["classCollapse"]),
            _viz_limits["individualCollapse"],
        )
        scoped = len(taxonomy.owl_classes) + len(taxonomy.concepts) > _viz_limits["classCollapse"]
        show_all_btn = _SHOW_ALL_BTN_HTML if scoped else ""
    else:
        graph = _graph_builders.build_vowl_graph(taxonomy)
        # The page embeds this payload; /api/graph is only asked on later refresh
        # ticks, so collapsing there alone left the first render carrying every
        # individual — the whole cost the collapse exists to avoid.
        #
        # Only when a server backs the page: a class hands its individuals over
        # through /api/class-individuals, and an offline export has no endpoint
        # to ask, so collapsing one would put them out of reach for good.
        if api_token:
            graph = _detail.collapse_individuals(graph, _viz_limits["individualCollapse"])
    meta = _taxonomy_meta(taxonomy, file_path)
    # Only the full-file graph remembers where nodes were left (ster.graph_layout):
    # a focused graph or a query result is a temporary view, and a static page
    # has no server to remember with.
    meta["rememberLayout"] = bool(api_token) and not sparql and not root_uri
    treemap = build_taxonomy_treemap(taxonomy) if has_taxonomy(taxonomy) else None
    return (
        _html_template._HTML_TEMPLATE.replace("__TITLE__", _html.escape(title))
        .replace("__CY_SCRIPT__", _js_assets._cytoscape_script_tag())
        .replace("__LAYOUT_BASE_SCRIPT__", _js_assets._layout_base_script_tag())
        .replace("__COSE_BASE_SCRIPT__", _js_assets._cose_base_script_tag())
        .replace("__FCOSE_SCRIPT__", _js_assets._fcose_script_tag())
        .replace("__EXPAND_COLLAPSE_SCRIPT__", _js_assets._expand_collapse_script_tag())
        .replace("__D3_SCRIPT__", _js_assets._d3_hierarchy_script_tag())
        .replace("__D3_PATH_SCRIPT__", _js_assets._d3_path_script_tag())
        .replace("__D3_SHAPE_SCRIPT__", _js_assets._d3_shape_script_tag())
        .replace("__STER_DATA_SCRIPT__", _detail._data_script(graph, meta, api_token, treemap))
        .replace("__STER_APP_JS__", _js_assets._app_js())
        .replace("__STER_TREEMAP_JS__", _js_assets._treemap_js())
        .replace("__SHOW_ALL_BTN__", show_all_btn)
        .replace("__OFFLINE_BANNER__", _detail._offline_banner(api_token))
    )


def ensure_published_server(taxonomy: Taxonomy, file_path: Path | None = None) -> str | None:
    """Ensure the live API server is running and return its base URL.

    Starts the FastAPI server if it is not
    already up, without opening the graph page. Returns the base URL, e.g.
    ``http://127.0.0.1:8765``, or ``None`` when the ``ster[api]`` extra is not
    installed (so callers can fall back to ``file://``).
    """
    if not _server._start_api_server(taxonomy, file_path):
        return None
    from ..api_server import load_server_config  # noqa: PLC0415

    url, port = load_server_config()
    return f"{url}:{port}"


def ensure_live_server(
    taxonomy: Taxonomy,
    file_path: Path | None = None,
    on_change_fn: Any = None,
    confirm: Callable[[str], bool] | None = None,
) -> None:
    """Make sure a live server shows *taxonomy*, resolving a held port if it is ours to.

    Starting is tried first, so the common case costs nothing. Only when that
    fails is the port claimed (:func:`ster.viz_vowl._claim.claim_port`): a server
    already showing this file is reused, a stale ``ster serve`` is replaced, and
    an interactive session or foreign process is left alone. Raises
    :class:`RuntimeError` with the reason when no server can be had.
    """
    if _server._start_api_server(taxonomy, file_path, on_change_fn):
        return
    from . import _claim  # noqa: PLC0415

    claim = _claim.claim_port(file_path, confirm)
    if claim.outcome == _claim.REUSE:
        return
    if claim.outcome == _claim.FREE and _server._start_api_server(
        taxonomy, file_path, on_change_fn
    ):
        return
    raise RuntimeError(claim.message or _server.unavailable_reason())


def open_in_browser(
    taxonomy: Taxonomy,
    file_path: Path | None = None,
    on_change_fn: Any = None,
) -> str:
    """Open the VOWL graph in the browser.

    Starts the live FastAPI server (SSE push refresh) — ``fastapi``/``uvicorn`` are
    core deps, so this only fails when the configured port is already held by
    something else. Raises :class:`RuntimeError` in that case, naming what holds
    the port when known (:func:`ster.viz_vowl._server.unavailable_reason`),
    rather than opening a read-only copy with no explanation.

    *on_change_fn* (optional) is called after any API mutation (e.g. individual
    creation) so the caller can rebuild its display tree.
    """
    ensure_live_server(taxonomy, file_path, on_change_fn)
    from ..api_server import load_server_config  # noqa: PLC0415

    _url, _port = load_server_config()
    url = f"{_url}:{_port}/"
    webbrowser.open(url)
    return url


def push_update(taxonomy: Taxonomy) -> None:
    """Push an updated taxonomy to every connected viewer.

    A no-op when no live server is running — there is nothing to push to.
    """
    from ..api_server import is_running, push_taxonomy  # noqa: PLC0415

    if is_running():
        push_taxonomy(taxonomy)


def open_focused_in_browser(
    taxonomy: Taxonomy, root_uri: str, file_path: Path | None = None
) -> str:
    """Open a focused VOWL graph centred on *root_uri* in the browser.

    Requires ster's live server, exactly like :func:`open_in_browser` — starting
    it here (rather than only checking whether it already happens to be up)
    means a focused graph opens from a cold start too, not only when something
    else already started the server first.
    """
    ensure_live_server(taxonomy, file_path)
    from ..api_server import load_server_config  # noqa: PLC0415

    _url, _port = load_server_config()
    url = f"{_url}:{_port}/?root={urllib.parse.quote(root_uri, safe='')}"
    webbrowser.open(url)
    return url
