"""Detail-map helpers (strip_detail, node_detail, build_detail_map) and the data/offline-banner script builders."""

from __future__ import annotations

import json
from typing import Any, Final

from ..model import Taxonomy
from ..viz import (
    _detail_class,
    _detail_concept,
    _detail_individual,
    _detail_scheme,
    _label_for,  # noqa: F401  (re-exported for potential callers)
)
from . import _graph_builders

_LIT_DETAIL: Final = "detail"


def strip_detail(graph: dict) -> dict:
    """Return *graph* without per-node ``detail``, which the page fetches on click.

    Detail (labels, comments, description, relations) is only ever read by the
    side panel for one node at a time, yet it is 91% of the payload — a 5.6k-node
    thesaurus ships 17.2MB where the graph itself is 1.6MB. Splitting it out is
    what keeps the first render, and the 2.5s static-mode refresh poll, small.

    The graph is mutated in place: callers build it purely to serialise it.
    """
    for node in graph.get("nodes", []):
        node.pop(_LIT_DETAIL, None)
    return graph


def node_detail(taxonomy: Taxonomy, uri: str) -> dict:
    """The detail payload for a single *uri*, or ``{}`` when it is not an entity.

    The lookup order matches ``add_node`` in :func:`_graph_builders.build_vowl_graph`, which keeps
    the first kind it sees — so a URI that is both an OWL class and a SKOS concept
    resolves the same way here as it does in the graph.
    """
    if (cls := taxonomy.owl_classes.get(uri)) is not None:
        return _detail_class(cls, taxonomy)
    if (individual := taxonomy.owl_individuals.get(uri)) is not None:
        return _detail_individual(individual, taxonomy)
    if (scheme := taxonomy.schemes.get(uri)) is not None:
        return _detail_scheme(scheme, taxonomy)
    if (concept := taxonomy.concepts.get(uri)) is not None:
        return _detail_concept(concept, taxonomy)
    return {}


def build_detail_map(taxonomy: Taxonomy) -> dict[str, dict]:
    """``{uri: detail}`` for every entity — the static-mode companion to the graph.

    A page served without the live API has no endpoint to ask, so it fetches this
    once, on the first node click, instead of carrying it from the start.
    """
    graph = _graph_builders.build_vowl_graph(taxonomy)
    return {n["id"]: n[_LIT_DETAIL] for n in graph["nodes"] if n.get(_LIT_DETAIL)}


def _data_script(graph: dict, meta: dict, api_token: str, taxonomy: dict | None = None) -> str:
    """Return the per-render *data injection* layer.

    Keeps ontology data out of both the library and the app code: the app reads
    everything from ``window.__STER_GRAPH__``. ``taxonomy`` (the treemap payload)
    is omitted entirely when there is no SKOS content, so the boot script can
    tell "no taxonomy" apart from "empty taxonomy" with a single key check.
    """
    payload: dict[str, Any] = {"data": strip_detail(graph), "meta": meta, "token": api_token}
    if taxonomy is not None:
        payload["taxonomy"] = taxonomy
    return "<script>window.__STER_GRAPH__=" + json.dumps(payload, ensure_ascii=False) + ";</script>"


def _offline_banner(api_token: str) -> str:
    """Return an in-page notice shown only when no live server backs the page.

    The explore / extend-relations hover actions are driven by the live API server
    (keyed off the page token). ``fastapi``/``uvicorn`` are core dependencies, so the
    only thing that stops the live server is the configured port already being in use —
    then the page is a static snapshot and those actions are unavailable. The banner
    says so, so the degraded mode is never silent. When a real token is present (live
    server) nothing is shown.
    """
    if api_token:
        return ""
    return (
        '<div id="offline-banner"><span>⚠ Live server not running — showing a '
        "static snapshot; explore / extend relations is unavailable. The configured "
        "port is in use by another process — close it (or change the port in Config) "
        "and reopen the graph.</span>"
        '<button id="offline-banner-close" title="Dismiss">×</button></div>'
    )


def is_live_server() -> bool:
    """True when the live FastAPI server backs the graph (vs a static snapshot)."""
    from ..api_server import is_running  # noqa: PLC0415

    return is_running()


def _server_host_port(host: str | None, port: int | None) -> tuple[str, int]:
    """Fill in *host*/*port* from the saved server config when not supplied."""
    if host is not None and port is not None:
        return host, port
    from ..api_server import load_server_config  # noqa: PLC0415

    url, cfg_port = load_server_config()
    return host or url.split("://", 1)[-1], port or cfg_port
