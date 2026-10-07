"""Primitives every visualisation needs — graph, map, timeline.

The three views ask the same four questions of an entity before they can draw
it: what is it called, what does it look like, what kind of thing is it, and
what stands over it. Each view answering them for itself is how
``geo_shapes._facet_classes`` and a timeline's own type walk end up being the
same twenty lines written twice, drifting apart on the first bug fix.

Nothing here knows what a map or a frieze is. A view imports from this module;
this module imports from no view — the layering ``geo_results`` already keeps
over ``geo_shapes``, applied one level up so a second view costs no third copy.

Also home to the *vendored asset* helper, because "download a library once into
``~/.cache/ster`` and inline it" is a rule about how ster ships pages, not about
any one library.
"""

from __future__ import annotations

import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path

import rdflib
from rdflib.namespace import RDF, RDFS, SKOS

from .model import is_builtin_uri

# Cell prefixes that make a SPARQL result string a URI. Results arrive as plain
# strings, so this is the only thing separating an identifier from a label.
URI_SCHEMES = ("http://", "https://", "urn:")  # NOSONAR - scheme prefixes, not URLs

# The id of the <style> a page gains in embed mode, so a test (or a person reading the source)
# can tell an embedded page from a normal one.
EMBED_STYLE_ID = "ster-embed"


def embed_style(hidden: tuple[str, ...]) -> str:
    """The <style> that hides a page's own chrome when it is shown inside another page.

    ``?embed=1`` on ``/map`` and ``/timeline`` asks for it. The page keeps working exactly as before
    (same query, same token, same script); only what surrounds the drawing is hidden, because the
    page that frames it supplies its own. ``!important`` so a rule the page adds later cannot bring
    the chrome back, and the style lives in the head so it applies before anything is drawn.
    """
    return f'<style id="{EMBED_STYLE_ID}">{",".join(hidden)}{{display:none !important}}</style>'


def ster_cache_dir() -> Path:
    """The directory vendored libraries and generated pages live in."""
    path = Path.home() / ".cache" / "ster"
    path.mkdir(parents=True, exist_ok=True)
    return path


def vendored(filename: str, url: str, timeout: int = 20) -> str | None:
    """A third-party asset's text, fetched once and cached, or None when offline.

    None rather than an exception: a page that falls back to a CDN tag still
    renders, and a view that cannot reach the network is not a broken view.
    """
    path = ster_cache_dir() / filename
    if not path.exists():
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
                path.write_bytes(response.read())
        except Exception:  # noqa: BLE001 — a missing asset must not fail the page
            return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def local_name(uri: str) -> str:
    """The readable tail of a URI — what to show when nothing else names it."""
    for separator in ("#", "/"):
        if separator in uri:
            return uri.rsplit(separator, 1)[-1]
    return uri


def is_uri(cell: str) -> bool:
    """Whether a result cell should be treated as an identifier."""
    return bool(cell) and cell.startswith(URI_SCHEMES)


def label_of(graph: rdflib.Graph, node: rdflib.term.Node) -> str:
    """The entity's own label, SKOS first, falling back to the URI's tail.

    ``skos:prefLabel`` before ``rdfs:label`` because a file carrying both means
    the first as the name and the second as a technical caption.
    """
    for predicate in (SKOS.prefLabel, RDFS.label):
        value = graph.value(node, predicate)
        if value is not None:
            return str(value)
    return local_name(str(node))


def image_of(graph: rdflib.Graph, node: rdflib.term.Node) -> str:
    """The first picture this entity offers, whatever vocabulary named it."""
    from .store import IMAGE_PREDICATES  # noqa: PLC0415

    return next(
        (str(o) for p in IMAGE_PREDICATES for o in graph.objects(node, rdflib.URIRef(p))),
        "",
    )


def _superclasses(graph: rdflib.Graph, cls: rdflib.term.Node) -> set[str]:
    """Every class above *cls*, transitively, guarded against a cyclic file."""
    seen: set[str] = set()
    frontier = [cls]
    while frontier:
        current = frontier.pop()
        for parent in graph.objects(current, RDFS.subClassOf):
            if isinstance(parent, rdflib.URIRef) and str(parent) not in seen:
                seen.add(str(parent))
                frontier.append(parent)
    return seen


def most_specific_types(graph: rdflib.Graph, node: rdflib.term.Node) -> list[str]:
    """*node*'s modelled classes, minus any another declared class implies.

    Every one, not just the deepest: an individual is often classified on more
    than one axis at once and neither subsumes the other, so both are useful.
    A class is dropped only when a sibling declaration already implies it, since
    offering Person beside Employee adds a filter that says less.
    """
    declared = [
        cls
        for cls in graph.objects(node, RDF.type)
        if isinstance(cls, rdflib.URIRef) and not is_builtin_uri(str(cls))
    ]
    implied: set[str] = set()
    for cls in declared:
        implied |= _superclasses(graph, cls) - {str(cls)}
    return sorted({str(c) for c in declared} - implied)


def _unseen(graph: rdflib.Graph, node: rdflib.term.Node, seen: set[str]) -> Iterator[rdflib.URIRef]:
    """Subjects pointing at *node* that no earlier level has claimed."""
    for subject in graph.subjects(None, node):
        if isinstance(subject, rdflib.URIRef) and str(subject) not in seen:
            seen.add(str(subject))
            yield subject


# Two shapes, and they are genuinely different jobs.
#
# KeepPredicate asks one node a yes/no question — carries a geometry, carries a
# date — and is what the walk below filters on.
#
# ReachFn is a whole walk: the entities a node stands over that satisfy such a
# predicate. `located_from` and `dated_from` are the two, and the views take one
# as a parameter so the same code serves the map and the timeline.
#
# Both were previously spelled `object`, which made every call site carry a
# `type: ignore[operator]` — the annotation admitting it was wrong, rather than
# the call being unsafe.
KeepPredicate = Callable[[rdflib.Graph, rdflib.term.Node], bool]
ReachFn = Callable[[rdflib.Graph, rdflib.URIRef], list[str]]


def reachable_inward(
    graph: rdflib.Graph,
    node: rdflib.URIRef,
    keep: KeepPredicate,
    depth: int,
) -> list[str]:
    """Entities *node* stands over that satisfy *keep* — itself, and its referrers.

    Inward only, and that direction is the whole design: following links outward
    walks up the model and back down somebody else's branch, so "this brand's
    geography" came back owning every rival's estate. What points *at* a thing
    is about that thing; what a thing points at is somebody else's business.

    *keep* is a predicate function over a node — carries a geometry, carries a
    date — so the walk is written once and each view says what it is looking for.
    """
    seen = {str(node)}
    found = [str(node)] if keep(graph, node) else []
    frontier: list[rdflib.term.Node] = [node]
    for _ in range(max(0, depth)):
        nxt: list[rdflib.term.Node] = []
        for current in frontier:
            for subject in _unseen(graph, current, seen):
                if keep(graph, subject):
                    found.append(str(subject))
                nxt.append(subject)
        frontier = nxt
        if not frontier:
            break
    return found
