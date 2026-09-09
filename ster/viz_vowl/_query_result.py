"""SPARQL query-result subgraph + its browser-preview helpers."""

from __future__ import annotations

import html as _html
import itertools
import webbrowser
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from ..model import Taxonomy, is_builtin_uri
from ..viz import (
    _detail_class,
    _detail_concept,
    _detail_individual,
    _detail_scheme,
    _label_for,  # noqa: F401  (re-exported for potential callers)
    _ontology_title,
    _taxonomy_meta,
)
from . import _detail, _html_template, _js_assets, _render, _server

_LIT_LOCAL_SERVER: Final = (
    "http://127.0.0.1:"  # NOSONAR - local-only address, not a network destination
)
_LIT_LABEL: Final = "label"
_LIT_SOURCE: Final = "source"
_LIT_TARGET: Final = "target"


def _add_result_node(
    uri: str,
    label: str,
    node_type: str,
    detail: dict | None,
    uris: set[str],
    seen: set[str],
    nodes: list[dict],
    taxonomy: Taxonomy,
) -> None:
    if uri in uris and uri not in seen:
        seen.add(uri)
        nodes.append(
            {
                "id": uri,
                _LIT_LABEL: label,
                "type": node_type,
                "detail": detail or {},
                "readOnly": 1 if uri in taxonomy.context_source else 0,
                "rootClass": 0,
            }
        )


def _add_query_result_nodes(
    taxonomy: Taxonomy, uris: set[str], nodes: list[dict], seen: set[str]
) -> None:
    for uri, cls in taxonomy.owl_classes.items():
        _add_result_node(
            uri, cls.label("en"), "class", _detail_class(cls, taxonomy), uris, seen, nodes, taxonomy
        )
    for uri, ind in taxonomy.owl_individuals.items():
        _add_result_node(
            uri,
            ind.label("en"),
            "individual",
            _detail_individual(ind, taxonomy),
            uris,
            seen,
            nodes,
            taxonomy,
        )
    for uri, scheme in taxonomy.schemes.items():
        _add_result_node(
            uri,
            scheme.title("en"),
            "scheme",
            _detail_scheme(scheme, taxonomy),
            uris,
            seen,
            nodes,
            taxonomy,
        )
    top_concept_uris = {u for u, c in taxonomy.concepts.items() if c.top_concept_of}
    for uri, concept in taxonomy.concepts.items():
        ntype = "topconcept" if uri in top_concept_uris else "concept"
        _add_result_node(
            uri,
            concept.pref_label("en"),
            ntype,
            _detail_concept(concept, taxonomy),
            uris,
            seen,
            nodes,
            taxonomy,
        )


def _add_query_result_subclass_edges(
    taxonomy: Taxonomy, seen: set[str], edges: list[dict], eid_counter: Iterator[int]
) -> None:
    for uri, cls in taxonomy.owl_classes.items():
        if uri not in seen:
            continue
        for parent in cls.sub_class_of:
            if not is_builtin_uri(parent) and parent in seen:
                edges.append(
                    {
                        "id": f"e{next(eid_counter)}",
                        _LIT_SOURCE: uri,
                        _LIT_TARGET: parent,
                        "type": "subClassOf",
                        _LIT_LABEL: "",
                    }
                )


def _add_query_result_instance_edges(
    taxonomy: Taxonomy, seen: set[str], edges: list[dict], eid_counter: Iterator[int]
) -> None:
    for uri, ind in taxonomy.owl_individuals.items():
        if uri not in seen:
            continue
        for type_uri in ind.types:
            if not is_builtin_uri(type_uri) and type_uri in seen:
                edges.append(
                    {
                        "id": f"e{next(eid_counter)}",
                        _LIT_SOURCE: uri,
                        _LIT_TARGET: type_uri,
                        "type": "instanceOf",
                        _LIT_LABEL: "",
                    }
                )


def _add_query_result_concept_edges(
    taxonomy: Taxonomy, seen: set[str], edges: list[dict], eid_counter: Iterator[int]
) -> None:
    for uri, concept in taxonomy.concepts.items():
        if uri not in seen:
            continue
        for broader_uri in concept.broader:
            if broader_uri in seen:
                edges.append(
                    {
                        "id": f"e{next(eid_counter)}",
                        _LIT_SOURCE: uri,
                        _LIT_TARGET: broader_uri,
                        "type": "broader",
                        _LIT_LABEL: "",
                    }
                )
        if concept.top_concept_of and concept.top_concept_of in seen:
            edges.append(
                {
                    "id": f"e{next(eid_counter)}",
                    _LIT_SOURCE: uri,
                    _LIT_TARGET: concept.top_concept_of,
                    "type": "inScheme",
                    _LIT_LABEL: "",
                }
            )


def build_query_result_graph(taxonomy: Taxonomy, uris: set[str]) -> dict:
    """Build a graph containing only the taxonomy nodes in *uris*.

    Edges are included only when both endpoints appear in *uris*.
    Always returns force layout.
    """
    nodes: list[dict] = []
    seen: set[str] = set()
    eid_counter = itertools.count()

    _add_query_result_nodes(taxonomy, uris, nodes, seen)

    edges: list[dict] = []
    _add_query_result_subclass_edges(taxonomy, seen, edges, eid_counter)
    _add_query_result_instance_edges(taxonomy, seen, edges, eid_counter)
    _add_query_result_concept_edges(taxonomy, seen, edges, eid_counter)

    return {"nodes": nodes, "edges": edges, "layout": "cose"}


def _build_query_result_html(
    taxonomy: Taxonomy,
    uris: set[str],
    file_path: Path | None = None,
    full_graph_link: str = "",
) -> tuple[dict, str]:
    """Return (graph_dict, html_str) for a query result viz, or raise ValueError."""
    graph = build_query_result_graph(taxonomy, uris)
    if not graph["nodes"]:
        raise ValueError("No taxonomy nodes matched the query result URIs.")
    title = _ontology_title(taxonomy, file_path) + " — Query results"
    meta = _taxonomy_meta(taxonomy, file_path)
    show_all_btn = (
        f'<span style="color:#cbd5e1"> │ </span>'
        f'<button class="ftbtn active" onclick="window.location.href=\'{full_graph_link}\'">'
        f"Show all nodes</button>"
        if full_graph_link
        else ""
    )
    html = (
        _html_template._HTML_TEMPLATE.replace("__TITLE__", _html.escape(title))
        .replace("__CY_SCRIPT__", _js_assets._cytoscape_script_tag())
        .replace("__LAYOUT_BASE_SCRIPT__", _js_assets._layout_base_script_tag())
        .replace("__COSE_BASE_SCRIPT__", _js_assets._cose_base_script_tag())
        .replace("__FCOSE_SCRIPT__", _js_assets._fcose_script_tag())
        .replace("__EXPAND_COLLAPSE_SCRIPT__", _js_assets._expand_collapse_script_tag())
        .replace("__D3_SCRIPT__", _js_assets._d3_hierarchy_script_tag())
        .replace("__D3_PATH_SCRIPT__", _js_assets._d3_path_script_tag())
        .replace("__D3_SHAPE_SCRIPT__", _js_assets._d3_shape_script_tag())
        .replace("__STER_DATA_SCRIPT__", _detail._data_script(graph, meta, ""))
        .replace("__STER_APP_JS__", _js_assets._app_js())
        .replace("__STER_TREEMAP_JS__", _js_assets._treemap_js())
        .replace("__SHOW_ALL_BTN__", show_all_btn)
        .replace("__OFFLINE_BANNER__", _detail._offline_banner(""))
    )
    return graph, html


def open_query_result_in_browser(
    taxonomy: Taxonomy,
    uris: set[str],
    file_path: Path | None = None,
) -> tuple[str, Path]:
    """Open a VOWL graph of the SPARQL query result nodes in the browser.

    Only taxonomy nodes whose URI appears in *uris* are rendered.
    Raises ``ValueError`` when none of the URIs match any node.
    Returns ``(url, out_path)`` so callers can track the file for later refresh.
    """
    cache = _ster_cache_dir()
    # Write the full ontology graph so the "Show all nodes" button has a target.
    full_path = _render._graph_path(file_path)
    _render._write_html(taxonomy, file_path, full_path)
    port = _server._ensure_server(cache)
    full_graph_link = f"/{full_path.name}"
    _graph, html = _build_query_result_html(taxonomy, uris, file_path, full_graph_link)
    stem = (file_path.stem if file_path else "query") + "_sparql_result"
    out = cache / f"{stem}_vowl.html"
    out.write_text(html, encoding="utf-8")
    url = f"{_LIT_LOCAL_SERVER}{port}/{out.name}"
    webbrowser.open(url)
    return url, out


def refresh_query_result_in_browser(
    taxonomy: Taxonomy,
    uris: set[str],
    out: Path,
) -> None:
    """Rewrite an existing query-result viz file and bring the browser tab to front.

    Raises ``ValueError`` when none of the URIs match any taxonomy node.
    The *out* path must be the file previously returned by
    ``open_query_result_in_browser``.
    """
    stem_guess = out.name.replace("_sparql_result_vowl.html", "_vowl.html")
    full_candidate = out.parent / stem_guess
    full_graph_link = f"/{full_candidate.name}" if full_candidate.exists() else ""
    _graph, html = _build_query_result_html(taxonomy, uris, full_graph_link=full_graph_link)
    out.write_text(html, encoding="utf-8")
    port = _server._ensure_server(out.parent)
    url = f"{_LIT_LOCAL_SERVER}{port}/{out.name}"
    webbrowser.open(url)


def _ster_cache_dir() -> Path:
    """``~/.cache/ster``, created on demand — the one place shared by every
    vendored-library download (:func:`_js_assets._cytoscape_script_tag` and friends) and
    every generated-file cache (:func:`_render._graph_path` and friends), so the
    ``".cache"``/``"ster"`` path components live in exactly one spot.
    """
    cache_dir = Path.home() / ".cache" / "ster"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir
