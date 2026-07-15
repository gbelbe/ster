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

# SPARQL 1.1 keywords + built-in functions, as individual upper-case words. ``a`` (the
# rdf:type shorthand) is added so it colours too.
_KEYWORDS: frozenset[str] = frozenset(
    [
        "SELECT",
        "CONSTRUCT",
        "DESCRIBE",
        "ASK",
        "WHERE",
        "PREFIX",
        "BASE",
        "FROM",
        "NAMED",
        "GRAPH",
        "OPTIONAL",
        "UNION",
        "MINUS",
        "FILTER",
        "BIND",
        "VALUES",
        "SERVICE",
        "SILENT",
        "GROUP",
        "BY",
        "HAVING",
        "ORDER",
        "ASC",
        "DESC",
        "LIMIT",
        "OFFSET",
        "DISTINCT",
        "REDUCED",
        "AS",
        "IN",
        "NOT",
        "EXISTS",
        "UNDEF",
        "TRUE",
        "FALSE",
        "A",
        "INSERT",
        "DELETE",
        "DATA",
        "WITH",
        "USING",
        "CLEAR",
        "DROP",
        "CREATE",
        "LOAD",
        "ADD",
        "MOVE",
        "COPY",
        "INTO",
        "TO",
        "DEFAULT",
        "ALL",
        "STR",
        "LANG",
        "LANGMATCHES",
        "DATATYPE",
        "BOUND",
        "IRI",
        "URI",
        "BNODE",
        "RAND",
        "ABS",
        "CEIL",
        "FLOOR",
        "ROUND",
        "CONCAT",
        "STRLEN",
        "UCASE",
        "LCASE",
        "ENCODE_FOR_URI",
        "CONTAINS",
        "STRSTARTS",
        "STRENDS",
        "STRBEFORE",
        "STRAFTER",
        "YEAR",
        "MONTH",
        "DAY",
        "HOURS",
        "MINUTES",
        "SECONDS",
        "TIMEZONE",
        "TZ",
        "NOW",
        "UUID",
        "STRUUID",
        "MD5",
        "SHA1",
        "SHA256",
        "SHA384",
        "SHA512",
        "COALESCE",
        "IF",
        "STRLANG",
        "STRDT",
        "SAMETERM",
        "ISIRI",
        "ISURI",
        "ISBLANK",
        "ISLITERAL",
        "ISNUMERIC",
        "REGEX",
        "SUBSTR",
        "REPLACE",
        "COUNT",
        "SUM",
        "MIN",
        "MAX",
        "AVG",
        "SAMPLE",
        "GROUP_CONCAT",
        "SEPARATOR",
    ]
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
