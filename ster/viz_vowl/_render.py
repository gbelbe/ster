"""Top-level render/open/push entry points (render_vowl_html, open_in_browser, push_update, open_focused_in_browser, ensure_published_server) and their small path/write helpers."""

from __future__ import annotations

import html as _html
import json
import re
import urllib.parse
import urllib.request
import webbrowser
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
from . import _detail, _graph_builders, _html_template, _js_assets, _query_result, _server

_LIT_UTF_8: Final = "utf-8"
_LIT_LOCAL_SERVER: Final = (
    "http://127.0.0.1:"  # NOSONAR - local-only address, not a network destination
)


def _graph_path(file_path: Path | None) -> Path:
    cache = _query_result._ster_cache_dir()
    stem = file_path.stem if file_path else "graph"
    return cache / f"{stem}_vowl.html"


_SHOW_ALL_BTN_HTML = (
    '<span style="color:#cbd5e1"> │ </span>'
    '<button class="ftbtn active" '
    "onclick=\"location.href=location.pathname+'?full=1'\">"
    "Show all nodes</button>"
)


def render_vowl_html(
    taxonomy: Taxonomy,
    file_path: Path | None,
    api_token: str = "",
    root_uri: str | None = None,
    full: bool = False,
) -> str:
    """Return the rendered VOWL HTML string.

    When *api_token* is non-empty the page connects to the SSE stream so the
    Graph view refreshes automatically whenever the ontology file changes.
    When *root_uri* is given a focused subgraph centred on that class is
    rendered. Otherwise the default is root-level only (schemes, root
    classes, top concepts) when a server backs the page — *full* opts back
    into the unscoped graph, and a "Show all nodes" button offers the same.
    """
    title = _ontology_title(taxonomy, file_path)
    show_all_btn = ""
    if root_uri:
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
        graph = _detail.collapse_individuals(_graph_builders.build_default_vowl_graph(taxonomy))
        scoped = (
            len(taxonomy.owl_classes) + len(taxonomy.concepts)
            > _graph_builders.CLASS_COLLAPSE_LIMIT
        )
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
            graph = _detail.collapse_individuals(graph)
    meta = _taxonomy_meta(taxonomy, file_path)
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


def _write_html(taxonomy: Taxonomy, file_path: Path | None, out_path: Path) -> None:
    out_path.write_text(render_vowl_html(taxonomy, file_path), encoding=_LIT_UTF_8)


def _data_path(out_path: Path) -> Path:
    stem = out_path.stem.removesuffix("_vowl")
    return out_path.with_name(stem + "_data.json")


def _detail_path(out_path: Path) -> Path:
    stem = out_path.stem.removesuffix("_vowl")
    return out_path.with_name(stem + "_detail.json")


def _write_data_json(taxonomy: Taxonomy, out_path: Path) -> None:
    """Write companion JSON polled by the browser for static-mode live updates.

    Detail is excluded: this file is re-fetched every 2.5s to compare a version
    stamp, so anything carried here is paid for on every tick.
    """
    import time as _t  # noqa: PLC0415

    graph = _detail.strip_detail(_graph_builders.build_vowl_graph(taxonomy))
    graph["_v"] = str(int(_t.time()))
    _data_path(out_path).write_text(json.dumps(graph, ensure_ascii=False), encoding=_LIT_UTF_8)
    _detail_path(out_path).write_text(
        json.dumps(_detail.build_detail_map(taxonomy), ensure_ascii=False), encoding=_LIT_UTF_8
    )


def ensure_published_server(taxonomy: Taxonomy, file_path: Path | None = None) -> str | None:
    """Ensure the live API server is running and return its base URL.

    Starts the FastAPI server (with the ``/ontology`` publish mount) if it is not
    already up, without opening the graph page. Returns the base URL, e.g.
    ``http://127.0.0.1:8765``, or ``None`` when the ``ster[api]`` extra is not
    installed (so callers can fall back to ``file://``).
    """
    if not _server._start_api_server(taxonomy, file_path):
        return None
    from ..api_server import load_server_config  # noqa: PLC0415

    url, port = load_server_config()
    return f"{url}:{port}"


def open_in_browser(
    taxonomy: Taxonomy,
    file_path: Path | None = None,
    on_change_fn: Any = None,
) -> str:
    """Open the VOWL graph in the browser.

    Starts the live FastAPI server (SSE push refresh) — ``fastapi``/``uvicorn`` are core
    deps, so this works unless the configured port is busy, in which case it falls back
    to a static HTTP server.

    *on_change_fn* (optional) is called after any API mutation (e.g. individual
    creation) so the caller can rebuild its display tree.
    """
    if _server._start_api_server(taxonomy, file_path, on_change_fn):
        from ..api_server import load_server_config  # noqa: PLC0415

        _url, _port = load_server_config()
        url = f"{_url}:{_port}/"
        webbrowser.open(url)
        return url
    # Fallback: static file server
    _server._file_path = file_path
    _server._out_path = _graph_path(file_path)
    _write_html(taxonomy, file_path, _server._out_path)
    _write_data_json(taxonomy, _server._out_path)
    port = _server._ensure_server(_server._out_path.parent)
    url = f"{_LIT_LOCAL_SERVER}{port}/{_server._out_path.name}"
    webbrowser.open(url)
    return url


def push_update(taxonomy: Taxonomy) -> None:
    """Push an updated taxonomy to all connected viewers."""
    from ..api_server import is_running, push_taxonomy  # noqa: PLC0415

    if is_running():
        push_taxonomy(taxonomy)
        return
    if _server._out_path is not None:
        _write_html(taxonomy, _server._file_path, _server._out_path)
        _write_data_json(taxonomy, _server._out_path)


def open_focused_in_browser(
    taxonomy: Taxonomy, root_uri: str, file_path: Path | None = None
) -> str:
    """Open a focused VOWL graph centred on *root_uri* in the browser."""
    from ..api_server import is_running  # noqa: PLC0415

    if is_running():
        from ..api_server import load_server_config  # noqa: PLC0415

        _url, _port = load_server_config()
        url = f"{_url}:{_port}/?root={urllib.parse.quote(root_uri, safe='')}"
        webbrowser.open(url)
        return url
    # Fallback: static focused file
    root_cls = taxonomy.owl_classes.get(root_uri)
    root_label = root_cls.label("en") if root_cls else _local(root_uri)
    safe_label = re.sub(r"[^A-Za-z0-9_-]", "_", root_label)
    stem = (file_path.stem if file_path else "graph") + f"_focused_{safe_label}"
    cache = _query_result._ster_cache_dir()
    out = cache / f"{stem}_vowl.html"
    out.write_text(render_vowl_html(taxonomy, file_path, root_uri=root_uri), encoding=_LIT_UTF_8)
    port = _server._ensure_server(out.parent)
    url = f"{_LIT_LOCAL_SERVER}{port}/{out.name}"
    webbrowser.open(url)
    return url
