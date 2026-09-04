"""Editor smart-completion helpers: cursor context, prefixes, qnames, variables.

Everything the SPARQL editor widget needs to offer context-aware
autocomplete: detecting whether the cursor sits at a predicate/object/class
position (``_sparql_context_at_cursor``), filtering qname candidates against
a ``UriIndex`` (``qname_candidates`` / ``qname_level_candidates``), and
scanning a buffer for declared prefixes / used ``?variables`` / result URIs.
"""

from __future__ import annotations

import re
from typing import Final

from ._types import UriIndex

_LIT_CLASS: Final = "class"
_LIT_PROPERTIES: Final = "properties"
_LIT_PROPERTY: Final = "property"


_CLASS_PREDICATES: frozenset[str] = frozenset(
    {
        "a",
        "rdf:type",
        "rdfs:subClassOf",
        "rdfs:domain",
        "rdfs:range",
        "owl:equivalentClass",
        "owl:disjointWith",
        "owl:unionOf",
        "owl:intersectionOf",
        "owl:complementOf",
    }
)


_LAST_TOKEN_RE = re.compile(r"(\S+)\s+$")


_PREFIX_DECL_RE = re.compile(r"(?i)\bPREFIX\s+(\w+)\s*:")


_TRIPLE_SEP_RE = re.compile(r"[{.;,]")


def _last_triple_separator(stripped: str) -> tuple[str | None, str]:
    """(separator char, text after it) for the last triple-pattern separator, if any."""
    last_sep: re.Match[str] | None = None
    for m in _TRIPLE_SEP_RE.finditer(stripped):
        last_sep = m
    if last_sep is not None:
        return last_sep.group(), stripped[last_sep.end() :]
    return None, stripped


def _triple_position_flags(sep_char: str | None, n: int) -> tuple[bool, bool]:
    """(at_predicate, at_object) for the triple position after *sep_char*, given *n* tokens."""
    # Semicolon reuses the subject; n=0 means we are typing the predicate.
    if sep_char == ";":
        return n == 0, n >= 1
    # Comma reuses subject+predicate; we are always typing an object.
    if sep_char == ",":
        return False, True
    # { or . or no separator: subject=pos1, predicate=pos2, object=pos3+
    return n == 1, n >= 2


def _strip_trailing_token(text: str) -> str:
    r"""*text* with any trailing non-whitespace run (the in-progress token) removed.

    A plain loop instead of ``re.sub(r"\S+$", "", text)`` — Sonar flags unbounded
    regex quantifiers as a potential ReDoS hotspot even when, as here, there's no
    backtracking risk (a single unanchored-at-the-front ``\S+``); doing it without
    a regex sidesteps the question entirely.
    """
    i = len(text)
    while i > 0 and not text[i - 1].isspace():
        i -= 1
    return text[:i]


def _sparql_context_at_cursor(buffer: str, pos: int) -> str:
    """Return the autocomplete context at the cursor position.

    Returns ``"property"`` at predicate position, ``"class"`` when the
    preceding token is a class-expecting predicate, and ``"any"`` elsewhere.

    Algorithm: strip the in-progress token, find the last triple-pattern
    separator (``{`` ``.`` ``;`` ``,``), count whitespace-separated tokens
    after it, then derive the triple position (subject/predicate/object).
    """
    before = buffer[:pos]
    stripped = _strip_trailing_token(before)

    sep_char, after_sep = _last_triple_separator(stripped)
    tokens = after_sep.split()
    at_predicate, at_object = _triple_position_flags(sep_char, len(tokens))
    last_token = tokens[-1] if tokens else None

    if at_object:
        if last_token and last_token in _CLASS_PREDICATES:
            return _LIT_CLASS
        return "any"

    if at_predicate:
        # If the single preceding token is itself a class predicate, it is
        # acting as the predicate (not the subject) and we are at object position.
        if last_token and last_token in _CLASS_PREDICATES:
            return _LIT_CLASS
        return _LIT_PROPERTY

    return "any"


def parse_buffer_prefixes(buffer: str) -> set[str]:
    """Return the set of prefix names declared with PREFIX in *buffer*."""
    return {m.group(1) for m in _PREFIX_DECL_RE.finditer(buffer)}


def _sparql_pfx_candidates(known_prefixes: set[str], filter_text: str) -> list[str]:
    """Return prefix names from *known_prefixes* that start with *filter_text*.

    Match is case-insensitive; result is sorted alphabetically.
    """
    f = filter_text.lower()
    return sorted(p for p in known_prefixes if p.lower().startswith(f))


def qname_candidates(idx: UriIndex, prefix: str, filter_text: str, context: str) -> list[str]:
    """Return filtered, alphabetically-sorted local names for *prefix*.

    *context* is ``"class"``, ``"property"``, or ``"any"``.  ``"class"``
    restricts to the classes bucket; ``"property"`` to the properties bucket;
    ``"any"`` returns everything.  Filter is applied case-insensitively as a
    prefix match.
    """
    if context == _LIT_CLASS:
        bucket_key = "classes"
    elif context == _LIT_PROPERTY:
        bucket_key = _LIT_PROPERTIES
    else:
        bucket_key = "all"
    names = idx.get(prefix, {}).get(bucket_key, [])
    f = filter_text.lower()
    return [n for n in names if n.lower().startswith(f)]


def qname_level_candidates(
    idx: UriIndex,
    prefix: str,
    parent_local: str,
    filter_text: str,
    context: str,
) -> list[tuple[str, bool]]:
    """Return candidates for one level of the hierarchical QName popup.

    *parent_local* is the local name of the class currently being browsed
    (empty string = root level).  Each result is a ``(local_name, has_children)``
    tuple so the caller can display a ``▶`` marker.

    At root level in ``"class"`` context only root classes are shown.
    In ``"any"`` context individuals are also included (at root level only).
    At any non-root level only the direct children of *parent_local* are shown.
    Filter is applied case-insensitively as a prefix match.
    """
    if prefix not in idx:
        return []
    entry = idx[prefix]
    children_map: dict[str, list[str]] = entry.get("children", {})  # type: ignore[assignment]

    if context == _LIT_PROPERTY:
        # Properties are a flat list; no hierarchy, no children markers.
        props: list[str] = list(entry.get(_LIT_PROPERTIES, []))  # type: ignore[arg-type]
        f = filter_text.lower()
        return [(name, False) for name in sorted(props) if name.lower().startswith(f)]

    ibc: dict[str, list[str]] = entry.get("individuals_by_class", {})  # type: ignore[assignment]

    def _has_drillable_content(name: str) -> bool:
        """True when a class name has subclasses or individuals — warrants a ▶."""
        return bool(children_map.get(name)) or bool(ibc.get(name))

    if parent_local:
        # Drill-down: subclasses of parent + individuals typed as parent class.
        names_set: set[str] = set(children_map.get(parent_local, []))
        for ind in ibc.get(parent_local, []):
            names_set.add(ind)
        names = sorted(names_set)
        f = filter_text.lower()
        # Individuals are leaves; subclasses get ▶ if they have further content.
        return [
            (name, name not in ibc.get(parent_local, []) and _has_drillable_content(name))
            for name in names
            if name.lower().startswith(f)
        ]

    # Root level
    if context == "any":
        # Class roots + properties + untyped individuals (typed individuals are
        # only reachable by drilling into their class).
        roots: list[str] = list(entry.get("roots", []))  # type: ignore[arg-type]
        props_at_root: list[str] = list(entry.get(_LIT_PROPERTIES, []))  # type: ignore[arg-type]
        untyped: list[str] = list(entry.get("untyped_individuals", []))  # type: ignore[arg-type]
        seen: set[str] = set(roots)
        for name in (*props_at_root, *untyped):
            if name not in seen:
                roots.append(name)
                seen.add(name)
        names = roots
    else:
        names = list(entry.get("roots", []))  # type: ignore[arg-type]

    f = filter_text.lower()
    return [
        (name, _has_drillable_content(name)) for name in sorted(names) if name.lower().startswith(f)
    ]


def extract_query_variables(buffer: str) -> list[str]:
    """Return a sorted, deduplicated list of ``?variable`` names in *buffer*."""
    return sorted(set(re.findall(r"\?([A-Za-z_]\w*)", buffer)))


def extract_result_uris(rows: list[list[str]]) -> set[str]:
    """Collect every URI-like value from SELECT result rows.

    Scans all columns of all rows; any cell that starts with ``http://`` or
    ``https://`` is treated as a URI.  Returns an empty set for literal-only
    or empty result sets.
    """
    uris: set[str] = set()
    for row in rows:
        for cell in row:
            if cell.startswith(
                "http://"  # NOSONAR - scheme prefix, not a URL
            ) or cell.startswith("https://"):
                uris.add(cell)
    return uris
