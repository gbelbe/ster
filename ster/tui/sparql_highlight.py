"""Pure regex-based SPARQL syntax highlighter for the query editor.

No maintained tree-sitter SPARQL grammar exists (tree-sitter-sparql 0.1.0 doesn't
build), so instead of an AST we tokenise each line with one regex and map every
token to a Textual TextArea highlight name (``keyword``, ``string``, ``comment``,
``number``, ``variable.builtin``, ``link.uri``, ``type``, ``operator``,
``punctuation.bracket`` / ``.delimiter``). Kept Textual-free so it is fully
unit-testable; :class:`~ster.tui.sparql_editor.SparqlEditor` feeds the spans into
``_build_highlight_map``.
"""

from __future__ import annotations

import re

from ster.sparql_query import SPARQL_KEYWORDS

# Every upper-cased word SPARQL_KEYWORDS names, split apart wherever it holds
# a multi-word phrase ("GROUP BY", "NOT EXISTS", ...) — this tokeniser only
# ever sees one word at a time, so the phrase itself never matches, but each
# of its words already does on its own (SPARQL_KEYWORDS lists "GROUP" and "BY"
# too, not just "GROUP BY"). Deriving from that one list, rather than keeping
# a second hand-copied set here, is what SPARQL_KEYWORDS's own docstring
# points at: before this the two had already drifted — GROUP, BY, ORDER, NOT,
# INTO, TO and DEFAULT coloured here but were silently absent from
# autocomplete, because nothing tied the two lists together.
_KEYWORDS: frozenset[str] = frozenset(
    word.upper() for phrase in SPARQL_KEYWORDS for word in phrase.split()
)

# One regex, alternation ordered by priority (comment/string/iri before words).
_TOKEN_RE = re.compile(
    r"(?P<comment>#[^\n]*)"
    r"|(?P<string>\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')"
    r"|(?P<iri><[^>\s]*>)"
    r"|(?P<var>[?$][A-Za-z_]\w*)"
    r"|(?P<number>\d+\.\d+|\d+)"
    r"|(?P<qname>[A-Za-z_][\w.\-]*:[A-Za-z0-9_.\-]*|:[A-Za-z0-9_.\-]*)"
    r"|(?P<word>[A-Za-z_]\w*)"
    r"|(?P<op>&&|\|\||[=!<>]=?|[+\-*/])"
    r"|(?P<bracket>[{}()\[\]])"
    r"|(?P<delim>[.;,])"
)

# Token group → Textual TextArea highlight name (styled by the editor's theme).
_NAME: dict[str, str] = {
    "comment": "comment",
    "string": "string",
    "iri": "link.uri",
    "var": "variable.builtin",
    "number": "number",
    "qname": "type",
    "op": "operator",
    "bracket": "punctuation.bracket",
    "delim": "punctuation.delimiter",
}


def spans(line: str) -> list[tuple[int, int, str]]:
    """``(start_col, end_col, highlight_name)`` for every SPARQL token in *line*."""
    out: list[tuple[int, int, str]] = []
    for match in _TOKEN_RE.finditer(line):
        kind = match.lastgroup
        if kind == "word":
            name = "keyword" if match.group().upper() in _KEYWORDS else None
        else:
            name = _NAME.get(kind or "")
        if name is not None:
            out.append((match.start(), match.end(), name))
    return out
