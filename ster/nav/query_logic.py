"""Pure SPARQL query helpers and autocomplete logic — no curses dependency."""

from __future__ import annotations

from .state import QueryState

# Characters that delimit SPARQL identifiers for word-boundary detection
_SPARQL_WORD_SEPS = frozenset(" \t\n\r{}()<>,;|@?$\"'=!*+/#^&[]\\")

# Keywords that expand to '… {\n  \n}' when inserted from the popup
_BRACE_EXPAND_KEYWORDS = frozenset(
    {
        "WHERE",
        "OPTIONAL",
        "UNION",
        "GRAPH",
        "MINUS",
        "SERVICE",
    }
)

# Keywords that expand to '…()' when inserted from the popup
_PAREN_EXPAND_KEYWORDS = frozenset({"FILTER", "BIND"})


def _sparql_current_word(buffer: str, pos: int) -> tuple[str, int]:
    """Return *(word, word_start)* for the identifier ending at *pos*."""
    i = pos
    while i > 0 and buffer[i - 1] not in _SPARQL_WORD_SEPS:
        i -= 1
    return buffer[i:pos], i


def _sparql_kw_candidates(word: str) -> list[str]:
    """Return SPARQL keywords whose uppercase form starts with *word* (max 9)."""
    from .. import sparql_query as _sq

    if not word:
        return []
    wu = word.upper()
    return [kw for kw in _sq.SPARQL_KEYWORDS if kw.startswith(wu)][:9]


def _clause_expand(keyword: str, indent: int = 0) -> str | None:
    """Return the expansion string for a SPARQL block keyword, or None.

    ``WHERE`` / ``OPTIONAL`` / ``UNION`` / ``GRAPH`` / ``MINUS`` / ``SERVICE``
    expand to ``KEYWORD {\\n<indent+2>\\n<indent>}``.
    ``FILTER`` / ``BIND`` expand to ``KEYWORD()``.
    All other keywords return ``None``.
    """
    kw_upper = keyword.upper()
    if kw_upper in _BRACE_EXPAND_KEYWORDS:
        inner = " " * (indent + 2)
        closing = " " * indent
        return f"{keyword} {{\n{inner}\n{closing}}}"
    if kw_upper in _PAREN_EXPAND_KEYWORDS:
        return f"{keyword}()"
    return None


def _auto_close_bracket(buffer: str, pos: int, ch: str) -> tuple[str, int]:
    """Insert a bracket pair and position the cursor inside.

    ``{`` inserts ``{\\n<indent+2>\\n<indent>}`` with the cursor on the inner line.
    ``(`` inserts ``()`` with the cursor between the parens.
    Any other character is inserted literally.
    """
    if ch == "{":
        line_start = buffer.rfind("\n", 0, pos) + 1
        line_text = buffer[line_start:pos]
        indent = len(line_text) - len(line_text.lstrip(" \t"))
        inner = " " * (indent + 2)
        closing = " " * indent
        insert = "{\n" + inner + "\n" + closing + "}"
        new_buf = buffer[:pos] + insert + buffer[pos:]
        new_pos = pos + 2 + len(inner)  # past '{\n' + inner indent
        return new_buf, new_pos
    if ch == "(":
        new_buf = buffer[:pos] + "()" + buffer[pos:]
        return new_buf, pos + 1
    new_buf = buffer[:pos] + ch + buffer[pos:]
    return new_buf, pos + 1


def _qname_prefix_at_cursor(buffer: str, pos: int, known_prefixes: set[str]) -> str | None:
    """Return the prefix name if the last character inserted was ``:`` after a known prefix.

    E.g. if ``buffer[..pos]`` ends with ``kai:``, returns ``"kai"``.
    Returns ``None`` if no known prefix matches.
    """
    if pos == 0 or buffer[pos - 1] != ":":
        return None
    i = pos - 1  # position of ':'
    while i > 0 and buffer[i - 1] not in _SPARQL_WORD_SEPS and buffer[i - 1] != ":":
        i -= 1
    prefix_name = buffer[i : pos - 1]
    return prefix_name if prefix_name in known_prefixes else None


def _sparql_kw_insert(qs: QueryState, keyword: str) -> None:
    """Replace the partial word before the cursor with *keyword*.

    Block keywords (WHERE, OPTIONAL, …) are automatically expanded to
    include an indented brace block; FILTER / BIND get ``()``.
    """
    _word, word_start = _sparql_current_word(qs.query_buffer, qs.query_pos)
    line_start = qs.query_buffer.rfind("\n", 0, word_start) + 1
    line_text = qs.query_buffer[line_start:word_start]
    indent = len(line_text) - len(line_text.lstrip(" \t"))
    expansion = _clause_expand(keyword, indent)
    if expansion is not None:
        qs.query_buffer = qs.query_buffer[:word_start] + expansion + qs.query_buffer[qs.query_pos :]
        if keyword.upper() in _BRACE_EXPAND_KEYWORDS:
            # cursor on the inner indented line: past 'KEYWORD {\n' + inner indent
            inner_len = indent + 2
            qs.query_pos = word_start + len(keyword) + 3 + inner_len  # 3 = ' {\n'
        else:
            # FILTER()/BIND(): cursor between the parens
            qs.query_pos = word_start + len(keyword) + 1
    else:
        qs.query_buffer = qs.query_buffer[:word_start] + keyword + qs.query_buffer[qs.query_pos :]
        qs.query_pos = word_start + len(keyword)


def _ac_matches(label: str, q: str) -> bool:
    """Return True if *q* is a prefix of *label* or of any word in *label*.

    Empty query matches everything. Comparison is case-insensitive.
    """
    if not q:
        return True
    q_lower = q.lower()
    label_lower = label.lower()
    if label_lower.startswith(q_lower):
        return True
    return any(word.startswith(q_lower) for word in label_lower.split())


def _qn_clamp_scroll(cursor: int, scroll: int, window_h: int) -> int:
    """Return an updated scroll so *cursor* is within the visible window.

    The window shows items ``[scroll, scroll + window_h)``.  If the cursor is
    above the window, scroll snaps up.  If below, scroll advances so the cursor
    is the last visible item.
    """
    if cursor < scroll:
        return cursor
    if cursor >= scroll + window_h:
        return cursor - window_h + 1
    return scroll


def _query_pos_up(buffer: str, pos: int) -> int:
    """Move cursor position up one logical line, preserving column."""
    before = buffer[:pos]
    lines_before = before.split("\n")
    col = len(lines_before[-1])
    if len(lines_before) <= 1:
        return 0
    prev_line = lines_before[-2]
    prefix_len = sum(len(ln) + 1 for ln in lines_before[:-2])
    return prefix_len + min(col, len(prev_line))


def _query_pos_down(buffer: str, pos: int) -> int:
    """Move cursor position down one logical line, preserving column."""
    before = buffer[:pos]
    lines_before = before.split("\n")
    col = len(lines_before[-1])
    rest = buffer[pos:]
    nl_idx = rest.find("\n")
    if nl_idx == -1:
        return len(buffer)  # already on last line
    next_start = pos + nl_idx + 1
    nl_end = buffer.find("\n", next_start)
    next_line_len = (nl_end - next_start) if nl_end >= 0 else (len(buffer) - next_start)
    return next_start + min(col, next_line_len)
