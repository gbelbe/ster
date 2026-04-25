"""Pure SPARQL query helpers and autocomplete logic — no curses dependency."""

from __future__ import annotations

from .state import QueryState

# Characters that delimit SPARQL identifiers for word-boundary detection
_SPARQL_WORD_SEPS = frozenset(" \t\n\r{}()<>,;|@?$\"'=!*+/#^&[]\\")


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


def _sparql_kw_insert(qs: QueryState, keyword: str) -> None:
    """Replace the partial word before the cursor with *keyword*."""
    _word, word_start = _sparql_current_word(qs.query_buffer, qs.query_pos)
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
