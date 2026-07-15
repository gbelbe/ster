"""Pure SPARQL completion logic for the New-TUI query editor.

No Textual, no curses, no rdflib — just strings and a prebuilt :class:`EntityIndex`
(built once by the rdflib adapter in :mod:`ster.tui.query`). Given the query text
and cursor, :func:`suggest` decides *what* to offer:

* SPARQL **keywords** while typing a word (position-aware — see :func:`context_at`),
  block keywords (WHERE/OPTIONAL/…) expand to an indented ``{ }`` and FILTER/BIND to ``()``.
* **entities** — class / individual / property / concept local names — right after a
  known ``prefix:`` qname.

Kept pure so it is exhaustively unit-testable; the Textual editor renders these
:class:`Completion` rows in a native OptionList popup.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Characters that delimit SPARQL identifiers (``:`` is handled separately as a qname sep).
WORD_SEPS = frozenset(" \t\n\r{}()<>,;|@?$\"'=!*+/#^&[]\\")

# Block keywords expand to '… {\n  \n}'; FILTER/BIND expand to '…()'.
_BRACE_EXPAND = frozenset({"WHERE", "OPTIONAL", "UNION", "GRAPH", "MINUS", "SERVICE"})
_PAREN_EXPAND = frozenset({"FILTER", "BIND"})

# Predicates whose object is a class (so a qname there is ranked classes-first).
_CLASS_PREDICATES = frozenset(
    {"a", "rdf:type", "rdfs:subClassOf", "rdfs:domain", "rdfs:range", "owl:equivalentClass"}
)

_VAR_RE = re.compile(r"[?$]([A-Za-z_][A-Za-z0-9_]*)")


def extract_variables(text: str) -> list[str]:
    """Sorted, unique ``?var`` / ``$var`` names used in *text* (without the sigil)."""
    return sorted(set(_VAR_RE.findall(text)))


@dataclass(frozen=True)
class Completion:
    """One suggestion: *insert* replaces the partial token; *cursor_offset* is where the
    caret lands within *insert* (e.g. inside an expanded ``{ }``)."""

    insert: str
    label: str
    kind: str  # keyword | class | individual | property | concept
    cursor_offset: int = -1  # -1 → end of insert

    def caret(self) -> int:
        return len(self.insert) if self.cursor_offset < 0 else self.cursor_offset


@dataclass
class EntityIndex:
    """Per-prefix local names by kind, plus the prefix→namespace map. Built once (rdflib)."""

    prefixes: dict[str, str] = field(default_factory=dict)
    classes: dict[str, list[str]] = field(default_factory=dict)
    individuals: dict[str, list[str]] = field(default_factory=dict)
    properties: dict[str, list[str]] = field(default_factory=dict)
    concepts: dict[str, list[str]] = field(default_factory=dict)


# ── word / qname scanning ─────────────────────────────────────────────────────


def current_word(text: str, pos: int) -> tuple[str, int]:
    """The identifier ending at *pos* and its start index."""
    i = pos
    while i > 0 and text[i - 1] not in WORD_SEPS and text[i - 1] != ":":
        i -= 1
    return text[i:pos], i


def qname_at_cursor(text: str, pos: int, known_prefixes: set[str]) -> tuple[str, str] | None:
    """If the cursor sits in a ``prefix:local`` token with a *known* prefix, return
    ``(prefix, partial_local)``; else ``None``. Handles both ``kai:`` and ``kai:Pers``."""
    i = pos
    while i > 0 and text[i - 1] not in WORD_SEPS and text[i - 1] != ":":
        i -= 1
    if i == 0 or text[i - 1] != ":":
        return None
    colon = i - 1
    j = colon
    while j > 0 and text[j - 1] not in WORD_SEPS and text[j - 1] != ":":
        j -= 1
    prefix = text[j:colon]
    return (prefix, text[i:pos]) if prefix in known_prefixes else None


# ── keyword insertion (with block expansion) ──────────────────────────────────


def keyword_insertion(keyword: str, indent: int = 0) -> tuple[str, int]:
    """The text to insert for *keyword* and the caret offset within it. Block keywords
    expand to an indented ``{ }`` (caret on the inner line); FILTER/BIND to ``()``."""
    ku = keyword.upper()
    if ku in _BRACE_EXPAND:
        inner = " " * (indent + 2)
        text = f"{keyword} {{\n{inner}\n{' ' * indent}}}"
        return text, len(keyword) + 3 + len(inner)  # past 'KW {\n' + inner indent
    if ku in _PAREN_EXPAND:
        return f"{keyword}()", len(keyword) + 1
    return keyword, len(keyword)


def keyword_candidates(word: str, keywords: list[str]) -> list[str]:
    """Keywords whose uppercase form starts with *word* (case-insensitive)."""
    if not word:
        return []
    wu = word.upper()
    return [kw for kw in keywords if kw.upper().startswith(wu)]


# ── position context ──────────────────────────────────────────────────────────


def _line_indent(text: str, pos: int) -> int:
    line = text[:pos].rsplit("\n", 1)[-1]
    return len(line) - len(line.lstrip(" \t"))


def context_at(text: str, cursor: int) -> str:
    """A coarse cursor context: ``prologue`` | ``projection`` | ``where`` | ``predicate``.

    Heuristic (partial queries don't parse): brace depth locates the WHERE body; within it
    the *current triple* starts after the last ``{ } . ;`` — a subject already present there
    (or a ``;`` continuation) puts the cursor in the predicate slot."""
    before = text[:cursor]
    if before.count("{") > before.count("}"):
        sep = max((before.rfind(c) for c in "{};."), default=-1)
        if sep >= 0 and before[sep] == ";":  # ';' continues the same subject → predicate
            return "predicate"
        return "predicate" if before[sep + 1 :].split() else "where"
    upper = before.upper()
    if any(kw in upper for kw in ("SELECT", "ASK", "CONSTRUCT", "DESCRIBE")):
        return "projection"
    return "prologue"


# ── triple slot (for entity ranking) ─────────────────────────────────────────


def triple_slot(text: str, token_start: int) -> str:
    """The slot of the entity token starting at *token_start* within a WHERE triple:
    ``subject`` | ``predicate`` | ``type-object`` | ``object`` (``object`` outside a body).

    ``?s a :`` → the object of ``a`` / ``rdfs:domain`` … is a *type-object* (a class); ``?s :``
    is the *predicate* (a property); the first token is the *subject*."""
    before = text[:token_start]
    if before.count("{") <= before.count("}"):
        return "object"
    sep = max((before.rfind(c) for c in "{}."), default=-1)
    if before.rfind(";") > sep:  # ';' continues the subject → a fresh predicate slot
        return "predicate"
    toks = before[sep + 1 :].split()
    if not toks:
        return "subject"
    if len(toks) == 1 and before.rfind(",") <= sep:  # subject present, no ',' → predicate
        return "predicate"
    predicate = toks[1] if len(toks) >= 2 else None  # 2nd token of the triple
    return "type-object" if predicate in _CLASS_PREDICATES else "object"


# ── suggestion ────────────────────────────────────────────────────────────────

# Entity kinds to offer, ordered by the triple slot (ranking, not a hard filter).
_KIND_ORDER = {
    "subject": ("class", "individual", "concept", "property"),
    "predicate": ("property", "class", "individual", "concept"),
    "type-object": ("class", "individual", "concept", "property"),
    "object": ("class", "individual", "concept", "property"),
}

# Query-form / prologue keywords — only sensible before the graph pattern.
_PROLOGUE_KEYWORDS = frozenset({"PREFIX", "BASE", "SELECT", "CONSTRUCT", "ASK", "DESCRIBE"})


def _entity_completions(
    index: EntityIndex, prefix: str, partial: str, ctx: str, limit: int
) -> list[Completion]:
    buckets = {
        "class": index.classes,
        "individual": index.individuals,
        "property": index.properties,
        "concept": index.concepts,
    }
    pl = partial.lower()
    out: list[Completion] = []
    for kind in _KIND_ORDER.get(ctx, _KIND_ORDER["object"]):
        for local in buckets[kind].get(prefix, []):
            if local.lower().startswith(pl):
                out.append(Completion(local, f"{prefix}:{local}", kind))
    return out[:limit]


def _keyword_completions(
    text: str, cursor: int, word: str, keywords: list[str], limit: int
) -> list[Completion]:
    indent = _line_indent(text, cursor)
    in_body = context_at(text, cursor) in ("where", "predicate")
    out: list[Completion] = []
    for kw in keyword_candidates(word, keywords):
        if in_body and kw.upper() in _PROLOGUE_KEYWORDS:
            continue  # position-aware: no SELECT/PREFIX/… inside a graph pattern
        insert, caret = keyword_insertion(kw, indent)
        out.append(Completion(insert, kw, "keyword", caret))
    return out[:limit]


def replace_start(text: str, cursor: int, prefixes: set[str]) -> int:
    """The index where an accepted completion should start replacing: the partial local
    name (keeping ``prefix:``) inside a known qname, else the start of the current word."""
    qn = qname_at_cursor(text, cursor, prefixes)
    if qn is not None:
        return cursor - len(qn[1])  # replace only the partial local, keep 'prefix:'
    return current_word(text, cursor)[1]


def _variable_completions(text: str, partial: str, limit: int) -> list[Completion]:
    pl = partial.lower()
    names = [n for n in extract_variables(text) if n.lower().startswith(pl) and n != partial]
    return [Completion(n, f"?{n}", "variable") for n in names][:limit]


def suggest(
    text: str, cursor: int, index: EntityIndex, keywords: list[str], limit: int = 12
) -> list[Completion]:
    """Completions for the cursor, by what is being typed:

    * a ``?`` / ``$`` **variable** → other variables already used in the query (never keywords);
    * inside a known ``prefix:`` token → **entities**, ranked by the triple slot;
    * a bare word → position-aware **keywords**.
    """
    word, word_start = current_word(text, cursor)
    if word_start > 0 and text[word_start - 1] in "?$":  # typing a variable name
        return _variable_completions(text, word, limit)
    qn = qname_at_cursor(text, cursor, set(index.prefixes))
    if qn is not None:
        prefix, partial = qn
        token_start = cursor - len(partial) - 1 - len(prefix)  # start of 'prefix:'
        return _entity_completions(index, prefix, partial, triple_slot(text, token_start), limit)
    if word:
        return _keyword_completions(text, cursor, word, keywords, limit)
    return []
