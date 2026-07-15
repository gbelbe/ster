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

from dataclasses import dataclass, field

# Characters that delimit SPARQL identifiers (``:`` is handled separately as a qname sep).
WORD_SEPS = frozenset(" \t\n\r{}()<>,;|@?$\"'=!*+/#^&[]\\")

# Block keywords expand to '… {\n  \n}'; FILTER/BIND expand to '…()'.
_BRACE_EXPAND = frozenset({"WHERE", "OPTIONAL", "UNION", "GRAPH", "MINUS", "SERVICE"})
_PAREN_EXPAND = frozenset({"FILTER", "BIND"})


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
    line = text[: pos].rsplit("\n", 1)[-1]
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

    ``?s a :`` → the object of ``a``/``rdf:type`` is a *type-object* (a class); ``?s :`` is
    the *predicate* (a property); the first token is the *subject*."""
    before = text[:token_start]
    if before.count("{") <= before.count("}"):
        return "object"
    sep = max((before.rfind(c) for c in "{}."), default=-1)
    if before.rfind(";") > sep:  # ';' continues the subject → a fresh predicate
        return "predicate"
    toks = before[sep + 1 :].split()
    if not toks:
        return "subject"
    if len(toks) == 1:
        return "predicate"
    return "type-object" if toks[1] == "a" or toks[1].endswith(":type") else "object"


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


def suggest(
    text: str, cursor: int, index: EntityIndex, keywords: list[str], limit: int = 12
) -> list[Completion]:
    """Completions for the cursor: entity local names inside a known ``prefix:`` token
    (ranked by triple slot), else position-aware SPARQL keywords for the partial word
    being typed (empty when nothing applies)."""
    qn = qname_at_cursor(text, cursor, set(index.prefixes))
    if qn is not None:
        prefix, partial = qn
        token_start = cursor - len(partial) - 1 - len(prefix)  # start of 'prefix:'
        slot = triple_slot(text, token_start)
        return _entity_completions(index, prefix, partial, slot, limit)
    word, _ = current_word(text, cursor)
    if word:
        return _keyword_completions(text, cursor, word, keywords, limit)
    return []
