"""Read-only context assembly for the MCP server.

Pure functions over a :class:`~ster.model.Taxonomy` that return plain,
JSON-ready dicts — what an agent needs to answer "what is this ontology, what
am I looking at, and what does it contain?".

Deliberately free of any MCP/protocol import: the protocol lives in
``ster/mcp_server.py``, so everything here is testable without a transport and
without the SDK. Nothing in this module mutates the taxonomy.
"""

from __future__ import annotations

import re
import time
from collections import Counter
from functools import lru_cache
from typing import Any, Final, TypedDict, Unpack

from .model import Taxonomy, is_builtin_uri
from .query_trace import Event, get_recorder

# Entity kinds, in the order a URI is looked up. A dispatch table rather than an
# if/elif chain so adding a kind is one row.
_KINDS: tuple[tuple[str, str], ...] = (
    ("concept", "concepts"),
    ("class", "owl_classes"),
    ("individual", "owl_individuals"),
    ("property", "owl_properties"),
    ("scheme", "schemes"),
)

# Each model class spells its display label differently.
_LABELLERS = {
    "concept": lambda obj, lang: obj.pref_label(lang),
    "class": lambda obj, lang: obj.label(lang),
    "individual": lambda obj, lang: obj.label(lang),
    "property": lambda obj, lang: obj.label(lang),
    "scheme": lambda obj, lang: obj.title(lang),
}

# SPARQL forms that would modify the store. The server is read-only, so these
# are refused before the query ever reaches rdflib.
_WRITE_KEYWORDS = (
    "insert",
    "delete",
    "drop",
    "clear",
    "load",
    "create",
    "add",
    "move",
    "copy",
)

_TRACE_RESULT_LIMIT = 20


def kind_of(taxonomy: Taxonomy, uri: str) -> str | None:
    """The entity kind for *uri*, or None when the URI is not in the taxonomy."""
    for kind, attr in _KINDS:
        if uri in getattr(taxonomy, attr):
            return kind
    return None


def _obj(taxonomy: Taxonomy, uri: str, kind: str) -> Any:
    attr = next(a for k, a in _KINDS if k == kind)
    return getattr(taxonomy, attr)[uri]


def label_of(taxonomy: Taxonomy, uri: str, lang: str = "en") -> str:
    """Display label for *uri*, falling back to its local name."""
    kind = kind_of(taxonomy, uri)
    if kind is None:
        return uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
    return _LABELLERS[kind](_obj(taxonomy, uri, kind), lang)


def _ref(taxonomy: Taxonomy, uri: str, lang: str) -> dict[str, str]:
    """A compact {uri, label} pointer — how neighbours are reported."""
    return {"uri": uri, "label": label_of(taxonomy, uri, lang)}


def parents_of(taxonomy: Taxonomy, uri: str, kind: str) -> list[str]:
    """Broader concepts (SKOS) or superclasses (OWL); built-ins excluded."""
    if kind == "concept":
        return list(taxonomy.concepts[uri].broader)
    if kind == "class":
        return [p for p in taxonomy.owl_classes[uri].sub_class_of if not is_builtin_uri(p)]
    return []


def children_of(taxonomy: Taxonomy, uri: str, kind: str) -> list[str]:
    """Narrower concepts (SKOS) or direct subclasses (OWL)."""
    if kind == "concept":
        return list(taxonomy.concepts[uri].narrower)
    if kind == "class":
        return [u for u, cls in taxonomy.owl_classes.items() if uri in cls.sub_class_of]
    return []


def _texts(items: list[Any], lang: str) -> list[str]:
    """Values of Label/Definition entries, preferring *lang* but never empty-handed."""
    preferred = [i.value for i in items if i.lang == lang and i.value]
    return preferred or [i.value for i in items if i.value]


def _descriptions(obj: Any, lang: str) -> list[str]:
    """skos:definition or rdfs:comment text, whichever the entity carries."""
    return _texts(getattr(obj, "definitions", None) or getattr(obj, "comments", []) or [], lang)


def entity(taxonomy: Taxonomy, uri: str, lang: str = "en") -> dict[str, Any]:
    """Full detail for one *uri*.

    Unknown URIs return an ``error`` payload rather than raising — an agent
    guessing a URI should get a usable answer, not a protocol-level failure.
    """
    kind = kind_of(taxonomy, uri)
    if kind is None:
        return {"error": "unknown_uri", "uri": uri}
    obj = _obj(taxonomy, uri, kind)
    return {
        "uri": uri,
        "kind": kind,
        "label": _LABELLERS[kind](obj, lang),
        "labels": _texts(getattr(obj, "labels", []), lang),
        "descriptions": _descriptions(obj, lang),
        "parents": [_ref(taxonomy, p, lang) for p in parents_of(taxonomy, uri, kind)],
        "children": [_ref(taxonomy, c, lang) for c in children_of(taxonomy, uri, kind)],
        "types": list(getattr(obj, "types", [])),
    }


def overview(taxonomy: Taxonomy, lang: str = "en") -> dict[str, Any]:
    """Orientation: what this graph is and how much of each thing it holds.

    Read from the store SPARQL runs against, so a figure here is the one a query returns.
    """
    from .graph_overview import graph_overview  # noqa: PLC0415

    return graph_overview(taxonomy, lang)


def search(
    taxonomy: Taxonomy, query: str, limit: int = 20, lang: str = "en"
) -> list[dict[str, str]]:
    """Case-insensitive label substring search across every entity kind."""
    needle = query.strip().lower()
    if not needle:
        return []
    hits: list[dict[str, str]] = []
    for kind, attr in _KINDS:
        for uri in getattr(taxonomy, attr):
            label = _LABELLERS[kind](_obj(taxonomy, uri, kind), lang)
            if needle in label.lower() or needle in uri.lower():
                hits.append({"uri": uri, "label": label, "kind": kind})
                if len(hits) >= limit:
                    return hits
    return hits


# ── Vocabulary probe ─────────────────────────────────────────────────────────
#
# What an agent must know before it can write a query that returns anything:
# which predicate carries a label here, how the hierarchy is asserted, and which
# language tags exist. Guessing any of these is the usual cause of an empty
# result, so ster answers them from the file instead of leaving them to chance.


@lru_cache(maxsize=1)
def _terms() -> dict[str, tuple[str, ...]]:
    """The W3C term URIs the probe looks for, taken from rdflib.

    Sourced from rdflib rather than spelled out here so there is one definition
    of each namespace and no chance of a typo in a literal. Lazy for the same
    reason as run_sparql: importing rdflib is slow and the TUI must not pay for
    it just to start.

    Label and hierarchy terms are ordered most-specific first; only those the
    file actually uses are reported.
    """
    from rdflib.namespace import DC, DCTERMS, OWL, RDFS, SKOS  # noqa: PLC0415

    return {
        "label": (
            str(SKOS.prefLabel),
            str(RDFS.label),
            str(DCTERMS.title),
            str(DC.title),
            str(SKOS.altLabel),
        ),
        "hierarchy": (
            str(SKOS.broader),
            str(SKOS.narrower),
            str(RDFS.subClassOf),
            str(RDFS.subPropertyOf),
        ),
        "concept_types": (str(SKOS.Concept),),
        "class_types": (str(OWL.Class), str(RDFS.Class)),
    }


def _shape_of(type_uris: set[str]) -> str:
    """Whether this file is a SKOS taxonomy, an OWL ontology, or both.

    Decides `skos:broader` vs `rdfs:subClassOf` for the agent — the second most
    common cause of a query that parses fine and returns nothing.
    """
    terms = _terms()
    has_concepts = any(t in type_uris for t in terms["concept_types"])
    has_classes = any(t in type_uris for t in terms["class_types"])
    if has_concepts and has_classes:
        return "mixed"
    if has_concepts:
        return "skos"
    if has_classes:
        return "owl"
    return "unknown"


def _ranked(counter: Any, normalize: Any) -> list[dict[str, Any]]:
    """Counter → [{uri, prefixed, count}], most-used first."""
    return [
        {"uri": str(uri), "prefixed": normalize(uri), "count": count}
        for uri, count in counter.most_common()
    ]


def _used_namespaces(graph: Any, used: set[str]) -> dict[str, str]:
    """Prefix bindings the file actually uses.

    rdflib binds ~30 namespaces into every graph by default; returning them all
    would bury the handful this ontology is written in. Prefix bindings are also
    invisible to SPARQL, so this is the only way an agent can learn them.
    """
    out: dict[str, str] = {}
    for prefix, uri in graph.namespaces():
        text = str(uri)
        if any(u.startswith(text) for u in used):
            out[str(prefix)] = text
    return out


def _languages(graph: Any) -> list[str]:
    """Every language tag on a literal, sorted."""
    from rdflib.term import Literal  # noqa: PLC0415

    return sorted(
        {obj.language for obj in graph.objects() if isinstance(obj, Literal) and obj.language}
    )


def vocabulary(taxonomy: Taxonomy) -> dict[str, Any]:
    """The file's real vocabulary — call before composing SPARQL against it.

    Reads the parsed graph rather than the in-memory taxonomy: a query runs
    against the file, so the predicates on disk are the ones that matter.

    Memoised on the taxonomy. The graph underneath was already cached, but
    counting every predicate and type across it costs ~100ms on a 22k-triple
    ontology and both tool descriptions tell an agent to call this *before*
    each query — so the guidance made it a hot path and nothing was holding the
    answer. Same lifetime as the other per-model caches: a reload or a mutation
    builds a new Taxonomy and the count goes with the old one.
    """
    cached = getattr(taxonomy, "_ster_vocabulary", None)
    if cached is not None:
        return cached  # type: ignore[return-value]
    computed = _compute_vocabulary(taxonomy)
    try:
        taxonomy._ster_vocabulary = computed  # type: ignore[attr-defined]
    except AttributeError:  # a model that refuses attributes — recompute instead
        pass
    return computed


def _compute_vocabulary(taxonomy: Taxonomy) -> dict[str, Any]:
    """The uncached walk; see :func:`vocabulary`."""
    if taxonomy.file_path is None:
        return {"error": "no_source_file", "message": "The taxonomy has no file to query."}

    # Lazy, like run_sparql: rdflib is heavy and the TUI must not pay for it.
    from rdflib.namespace import RDF  # noqa: PLC0415

    from .sparql_query import load_graph_cached  # noqa: PLC0415
    from .store import source_files  # noqa: PLC0415

    # Deliberately the files, not the model: vocabulary answers "what is in this
    # document" — which prefixes it binds, which predicates it actually uses —
    # and that is a question about the text on disk. The map's own reads go
    # through the model instead; see _graph_for_locate.
    graph = load_graph_cached(source_files(taxonomy))
    normalize = graph.namespace_manager.normalizeUri

    predicates = Counter(graph.predicates())
    types = Counter(graph.objects(None, RDF.type))
    predicate_uris = {str(p) for p in predicates}
    type_uris = {str(t) for t in types}

    used = predicate_uris | type_uris | {str(s) for s in graph.subjects()}
    return {
        "shape": _shape_of(type_uris),
        "namespaces": _used_namespaces(graph, used),
        "predicates": _ranked(predicates, normalize),
        "label_predicates": [normalize(p) for p in _terms()["label"] if p in predicate_uris],
        "hierarchy_predicates": [
            normalize(p) for p in _terms()["hierarchy"] if p in predicate_uris
        ],
        "types": _ranked(types, normalize),
        "languages": _languages(graph),
    }


def is_read_only_sparql(query: str) -> bool:
    """False when *query* contains a SPARQL Update form.

    Keyword-based on purpose: the server must refuse writes before rdflib parses
    anything. Matching is word-boundary anchored so a URI or a label containing
    e.g. "created" is not mistaken for a CREATE.
    """
    stripped = re.sub(r"#[^\n]*", " ", query)  # drop comments
    stripped = re.sub(r"[\"'][^\"']*[\"']", " ", stripped)  # drop string literals
    # `[^<>]`, not `[^>]`: with only `>` excluded, an unterminated run of `<`
    # makes every start position rescan to the end of the string before failing,
    # which is quadratic — 40k of them took 1.4s, and this reads a request body.
    # Excluding `<` too lets each attempt fail at the next one, and it is the
    # more accurate rule anyway: a SPARQL IRI cannot contain either bracket.
    stripped = re.sub(r"<[^<>]*>", " ", stripped)  # drop URIs
    return not any(re.search(rf"\b{kw}\b", stripped, flags=re.IGNORECASE) for kw in _WRITE_KEYWORDS)


# How many rows run_sparql hands an agent by default, and the most it may ask
# for. Every row lands in the model's context window: an unbounded SELECT over
# a real export (tens of thousands of rows) floods it, so the agent is given a
# page and told the total instead — enough to see it should aggregate.
SPARQL_ROW_LIMIT: Final = 200
SPARQL_ROW_LIMIT_MAX: Final = 1000
# How long an agent's query may run. A normal query on a real export answers in
# milliseconds; this is a thousand times that, so only a runaway join reaches it,
# and the agent gets an error it can act on instead of a server that hangs.
SPARQL_TIMEOUT_S: Final = 10.0


class PayloadOptions(TypedDict, total=False):
    """How a SPARQL answer is bounded: the timeline's dates, the row cap, the deadline.

    A parameter object so each new bound lands here, typed and named, rather
    than as one more positional every caller has to place in the right slot.
    """

    after: str | None
    before: str | None
    limit: int | None
    timeout: float | None
    # who is asking, recorded in the query trace (see ster.query_trace)
    agent_session_id: str | None
    agent_question: str | None
    token_usage: dict[str, Any] | None
    agent_session_question: str | None
    agent: dict[str, str] | None  # which agent and model asked, see ster.query_trace.agent


def sparql_payload(
    taxonomy: Taxonomy,
    query: str,
    view: str | None = None,
    base: str | None = None,
    **options: Unpack[PayloadOptions],
) -> dict[str, Any]:
    """Run a read-only SPARQL query and shape the answer for the wire.

    The single implementation behind both transports: ``POST /api/sparql_query`` and
    the MCP ``run_sparql`` tool call this, so a protocol is a way in and not a
    place where behaviour lives. Anything that should hold for one — the
    read-only guard, and whatever access control is layered on later — holds for
    the other by construction rather than by being remembered twice.

    *limit* caps the rows returned, not the rows computed: ``row_count`` stays
    the full count and any view is built from the full result. ``None`` (the
    REST endpoint, whose own page shows the table) returns every row.

    *timeout* (seconds) runs the query where it can be stopped; past it the
    answer is a ``timeout`` error. ``None`` runs it in-process, without a deadline.
    """
    recorder = get_recorder()
    trace = recorder.start_run(
        query,
        transport="shared_sparql",
        query_type="raw_sparql",
        agent_session_id=options.get("agent_session_id"),
        agent_question=options.get("agent_question"),
        token_usage=options.get("token_usage"),
        agent_session_question=options.get("agent_session_question"),
        agent=options.get("agent"),
    )
    started = time.perf_counter()
    step_id = "raw-sparql"
    recorder.record(
        Event(
            event="step_planned",
            run_id=trace.run_id,
            trace_id=trace.trace_id,
            sequence=2,
            step_id=step_id,
            payload={
                "step_kind": "raw_sparql_execution",
                "objective": "Execute the supplied read-only SPARQL query.",
                "natural_language": "Run the user's SPARQL query against the open graph.",
            },
        )
    )
    if not is_read_only_sparql(query):
        recorder.record(
            Event(
                event="step_failed",
                run_id=trace.run_id,
                trace_id=trace.trace_id,
                sequence=3,
                step_id=step_id,
                payload={"status": "failed", "error_code": "read_only"},
            )
        )
        recorder.finish(trace, status="failed", error_code="read_only")
        return {
            "error": "read_only",
            "message": "This server accepts SELECT/ASK queries only.",
            "trace": _trace_payload(trace, recorder),
        }

    recorder.record(
        Event(
            event="query_generated",
            run_id=trace.run_id,
            trace_id=trace.trace_id,
            sequence=3,
            step_id=step_id,
            payload={"query_id": f"{trace.run_id}:raw-sparql", "query": query},
        )
    )
    recorder.record(
        Event(
            event="step_started",
            run_id=trace.run_id,
            trace_id=trace.trace_id,
            sequence=4,
            step_id=step_id,
        )
    )

    # Imported lazily: sparql_query pulls in rdflib, which is heavy to import.
    from .sparql_query import run_query_on_taxonomy  # noqa: PLC0415

    result = run_query_on_taxonomy(taxonomy, query, options.get("timeout"))
    if result.error:
        code = "timeout" if result.timed_out else "query_error"
        recorder.record(
            Event(
                event="step_failed",
                run_id=trace.run_id,
                trace_id=trace.trace_id,
                sequence=5,
                step_id=step_id,
                payload={
                    "status": "failed",
                    "error_code": code,
                    "error_message": result.error,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                },
            )
        )
        recorder.finish(trace, status="failed", error_code=code)
        return {"error": code, "message": result.error, "trace": _trace_payload(trace, recorder)}
    payload: dict[str, Any] = {
        "columns": result.columns,
        "rows": result.rows,
        "row_count": len(result.rows),
        "query_type": result.query_type,
    }
    recorder.record(
        Event(
            event="step_completed",
            run_id=trace.run_id,
            trace_id=trace.trace_id,
            sequence=5,
            step_id=step_id,
            payload={
                "status": "completed",
                "query_id": f"{trace.run_id}:raw-sparql",
                "query": query,
                "result_id": f"{trace.run_id}:raw-sparql-result",
                "row_count": len(result.rows),
                "columns": result.columns,
                "result_rows": result.rows[:_TRACE_RESULT_LIMIT],
                "result_truncated": len(result.rows) > _TRACE_RESULT_LIMIT,
                "domain_bindings": _trace_bindings(taxonomy, result),
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                "token_usage": options.get("token_usage"),
            },
        )
    )
    recorder.finish(trace, status="completed", row_count=len(result.rows))
    payload["trace"] = _trace_payload(trace, recorder)
    limit = options.get("limit")
    if limit is not None:
        _cap_rows(payload, limit)
    # *view* is handled here rather than in either caller, for the reason this
    # function exists: a protocol is a way in, not a place where behaviour
    # lives. Putting it in the MCP tool alone would have given the agent a
    # capability the REST endpoint does not have.
    from .view_links import DateRange, annotate  # noqa: PLC0415

    dates = DateRange(options.get("after"), options.get("before"))
    return annotate(payload, taxonomy, result, query, view, base, dates)


def _trace_payload(trace, recorder) -> dict[str, Any]:
    """Return stable trace IDs without exposing local storage to callers."""
    if not recorder.enabled():
        return {"enabled": False}
    return {
        "run_id": trace.run_id,
        "trace_id": trace.trace_id,
        "enabled": recorder.enabled(),
    }


def _trace_bindings(taxonomy: Taxonomy, result: Any) -> list[dict[str, Any]]:
    """Describe URI-valued result cells without coupling the trace core to Taxonomy."""
    bindings: list[dict[str, Any]] = []
    for row in result.rows:
        for column, value in zip(result.columns, row, strict=False):
            if not _is_uri(value):
                continue
            kind = kind_of(taxonomy, value)
            item: dict[str, Any] = {
                "variable": column,
                "value": value,
                "term_type": "uri",
                "label": label_of(taxonomy, value),
            }
            if kind is not None:
                item["kind"] = kind
                item["rdf_types"] = list(getattr(_obj(taxonomy, value, kind), "types", []))
            bindings.append(item)
    return bindings


def _is_uri(value: str) -> bool:
    return value.startswith(("http://", "https://", "urn:"))


def query_trace(run_id: str, export: bool = False) -> dict[str, Any]:
    """Inspect or export a trace from the active JSONL recorder."""
    from .query_trace import get_recorder
    from .query_trace.answers import answer_for_run
    from .query_trace.jsonl import read_events
    from .query_trace.materialize import materialize_events
    from .query_trace.validation import validate_events

    recorder = get_recorder()
    path_for = getattr(recorder, "path_for", None)
    if path_for is None:
        return {"error": "trace_unavailable", "message": "Query tracing is not enabled."}
    try:
        path = path_for(run_id)
        events = list(read_events(path))
    except (FileNotFoundError, ValueError) as exc:
        return {"error": "trace_not_found", "message": str(exc)}
    errors = validate_events(events)
    if errors:
        return {"error": "invalid_trace", "errors": errors}
    first, last = events[0], events[-1]
    result: dict[str, Any] = {
        "run_id": run_id,
        "trace_id": first.trace_id,
        "question": first.payload.get("question", ""),
        "agent_question": first.payload.get("agent_question"),
        "agent_session_question": first.payload.get("agent_session_question"),
        "status": last.payload.get("status", "failed"),
        "event_count": len(events),
        "steps": sorted({event.step_id for event in events if event.step_id}),
    }
    if export:
        result["format"] = "trig"
        answer = answer_for_run(path.parent, run_id)
        result["trig"] = materialize_events(events, answer).serialize(format="trig")
    return result


def _cap_rows(payload: dict[str, Any], limit: int) -> None:
    """Keep the first *limit* rows (clamped to 1..SPARQL_ROW_LIMIT_MAX) and say so."""
    limit = max(1, min(limit, SPARQL_ROW_LIMIT_MAX))
    total = payload["row_count"]
    # Keys appear only when rows were cut, so an answer that fits is identical
    # to the REST endpoint's — the two transports must keep agreeing.
    if total > limit:
        payload["truncated"] = True
        payload["rows"] = payload["rows"][:limit]
        payload["truncation_hint"] = (
            f"{total} rows matched; only the first {limit} are returned. Narrow the "
            "query with filters, or aggregate (COUNT, GROUP BY) instead of listing — "
            f"or pass a larger limit (at most {SPARQL_ROW_LIMIT_MAX})."
        )


class SparqlOptions(PayloadOptions, total=False):
    """Everything about a run_sparql call but the taxonomy and the query."""

    view: str | None
    base: str | None


def run_sparql(taxonomy: Taxonomy, query: str, **options: Unpack[SparqlOptions]) -> dict[str, Any]:
    """MCP's name for :func:`sparql_payload` — kept so the tool schema is stable.

    *view* is advisory: the rows come back whether or not a map or graph can be
    built from them, and an unbuildable view is reported as a reason rather than
    raised. A failed view is not a failed query.

    *after*/*before* only ever narrow the ``timeline`` view — a query naming
    entities is still what decides *which* entities are on it; these decide
    which of their moments are, the distinction :func:`ster.time_shapes.timeline_items`
    exists to make.

    *limit* defaults to SPARQL_ROW_LIMIT: an agent always gets a bounded answer,
    with ``truncated`` and the full ``row_count`` telling it when there is more.
    *timeout* defaults to SPARQL_TIMEOUT_S, for the same reason: an agent's query
    must not be able to hold the server.
    """
    defaults = SparqlOptions(limit=SPARQL_ROW_LIMIT, timeout=SPARQL_TIMEOUT_S)
    with_default: SparqlOptions = {**defaults, **options}
    return sparql_payload(taxonomy, query, **with_default)


_TIMELINE_ITEM_LIMIT = 200
_LIT_COUNT: Final = "count"


def _timeline_url(focus: str = "") -> str:
    """The running server's timeline page, or an empty string when unavailable."""
    from urllib.parse import quote  # noqa: PLC0415

    try:
        from .api_server import load_server_config  # noqa: PLC0415

        url, port = load_server_config()
    except Exception:  # noqa: BLE001 - a missing server must not fail the answer
        return ""
    page = f"{url}:{port}/timeline"
    return f"{page}?focus={quote(focus)}" if focus else page


def timeline(
    taxonomy: Taxonomy,
    uri: str = "",
    limit: int = _TIMELINE_ITEM_LIMIT,
    after: str | None = None,
    before: str | None = None,
) -> dict[str, Any]:
    """Moments in the file, or those the optional URI stands over.

    *after*/*before* bound which **moments** come back, not which entities are
    considered — the same rule :func:`sparql_payload` follows, for the same
    reason: an entity dated twice can be in range on one date and not the other.
    """
    import rdflib  # noqa: PLC0415

    from .store import full_graph_rdflib  # noqa: PLC0415
    from .time_shapes import (  # noqa: PLC0415
        anything_dated,
        dated_from,
        is_dated,
        span_of,
        timeline_items,
    )

    graph = full_graph_rdflib(taxonomy)
    if not anything_dated(graph):
        return {
            "items": [],
            _LIT_COUNT: 0,
            "span": None,
            "url": "",
            "note": "no dates in this file",
        }
    uris = (
        dated_from(graph, rdflib.URIRef(uri))
        if uri
        else sorted(
            {
                str(subject)
                for subject in graph.subjects()
                if isinstance(subject, rdflib.URIRef) and is_dated(graph, subject)
            }
        )
    )
    items = timeline_items(graph, uris, after, before)
    return {
        "items": items[: max(1, limit)],
        _LIT_COUNT: len(items),
        "truncated": len(items) > limit,
        "span": span_of(items),
        "url": _timeline_url(uri),
    }
