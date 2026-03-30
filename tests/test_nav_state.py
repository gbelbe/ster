"""Tests for ster/nav_state.py — pure state machine functions, no curses."""

from __future__ import annotations

import re

import pytest

from ster.nav_logic import TreeLine
from ster.nav_state import (
    DetailField,
    DetailState,
    SearchState,
    TreeState,
    _replace_search,
    _search_jump,
    clamp_scroll,
    navigate_detail,
    navigate_tree,
    search_update,
    update_search_results,
)

BASE = "https://example.org/test/"

# Key codes (matching constants in nav_state.py)
KEY_UP    = 259
KEY_DOWN  = 258
KEY_HOME  = 262
KEY_END   = 360
KEY_PPAGE = 339
KEY_NPAGE = 338
KEY_BACKSPACE = 263
KEY_ENTER = 343
KEY_BTAB  = 353
CTRL_D = 4
CTRL_U = 21


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_tree_state(n: int, cursor: int = 0, scroll: int = 0) -> TreeState:
    flat = [
        TreeLine(uri=f"{BASE}C{i}", depth=0, prefix="")
        for i in range(n)
    ]
    return TreeState(flat=flat, cursor=cursor, scroll=scroll)


def _make_detail_state(n: int, cursor: int = 0, scroll: int = 0) -> DetailState:
    fields = [
        DetailField(key=f"field:{i}", display=f"Field {i}", value=str(i), editable=True)
        for i in range(n)
    ]
    return DetailState(uri=BASE + "C", fields=fields, field_cursor=cursor, scroll=scroll)


# ── clamp_scroll ──────────────────────────────────────────────────────────────


def test_clamp_scroll_cursor_above():
    assert clamp_scroll(10, 5, 20) == 5


def test_clamp_scroll_cursor_below():
    assert clamp_scroll(0, 25, 20) == 6


def test_clamp_scroll_cursor_within():
    assert clamp_scroll(5, 10, 20) == 5


def test_clamp_scroll_zero_list_h():
    assert clamp_scroll(5, 10, 0) == 0


def test_clamp_scroll_negative_list_h():
    assert clamp_scroll(5, 10, -1) == 0


# ── navigate_tree ─────────────────────────────────────────────────────────────


def test_navigate_tree_down():
    state = _make_tree_state(5, cursor=0)
    new = navigate_tree(state, KEY_DOWN, 10)
    assert new.cursor == 1


def test_navigate_tree_down_j():
    state = _make_tree_state(5, cursor=0)
    new = navigate_tree(state, ord("j"), 10)
    assert new.cursor == 1


def test_navigate_tree_up():
    state = _make_tree_state(5, cursor=3)
    new = navigate_tree(state, KEY_UP, 10)
    assert new.cursor == 2


def test_navigate_tree_up_k():
    state = _make_tree_state(5, cursor=3)
    new = navigate_tree(state, ord("k"), 10)
    assert new.cursor == 2


def test_navigate_tree_home():
    state = _make_tree_state(5, cursor=4)
    new = navigate_tree(state, KEY_HOME, 10)
    assert new.cursor == 0


def test_navigate_tree_home_g():
    state = _make_tree_state(5, cursor=4)
    new = navigate_tree(state, ord("g"), 10)
    assert new.cursor == 0


def test_navigate_tree_end():
    state = _make_tree_state(5, cursor=0)
    new = navigate_tree(state, KEY_END, 10)
    assert new.cursor == 4


def test_navigate_tree_end_G():
    state = _make_tree_state(5, cursor=0)
    new = navigate_tree(state, ord("G"), 10)
    assert new.cursor == 4


def test_navigate_tree_page_up():
    state = _make_tree_state(20, cursor=10)
    new = navigate_tree(state, KEY_PPAGE, 5)
    assert new.cursor == 5


def test_navigate_tree_page_down():
    state = _make_tree_state(20, cursor=5)
    new = navigate_tree(state, KEY_NPAGE, 5)
    assert new.cursor == 10


def test_navigate_tree_ctrl_d():
    state = _make_tree_state(20, cursor=5)
    new = navigate_tree(state, CTRL_D, 10)
    assert new.cursor == 10


def test_navigate_tree_ctrl_u():
    state = _make_tree_state(20, cursor=10)
    new = navigate_tree(state, CTRL_U, 10)
    assert new.cursor == 5


def test_navigate_tree_at_top_boundary():
    state = _make_tree_state(5, cursor=0)
    new = navigate_tree(state, KEY_UP, 10)
    assert new.cursor == 0  # clamps at 0


def test_navigate_tree_at_bottom_boundary():
    state = _make_tree_state(5, cursor=4)
    new = navigate_tree(state, KEY_DOWN, 10)
    assert new.cursor == 4  # clamps at n-1


def test_navigate_tree_unhandled_key_returns_same_state():
    state = _make_tree_state(5, cursor=2)
    new = navigate_tree(state, ord("x"), 10)
    assert new is state  # exact same object


def test_navigate_tree_empty_flat():
    state = TreeState(flat=[], cursor=0, scroll=0)
    new = navigate_tree(state, KEY_DOWN, 10)
    assert new is state


def test_navigate_tree_scroll_adjusts():
    state = _make_tree_state(20, cursor=0, scroll=0)
    # Move to position 15 with list_h=5 — scroll should follow
    new = navigate_tree(state, KEY_END, 5)
    assert new.cursor == 19
    assert new.scroll >= 15


# ── navigate_detail ───────────────────────────────────────────────────────────


def test_navigate_detail_down():
    state = _make_detail_state(5, cursor=0)
    new = navigate_detail(state, KEY_DOWN, 10)
    assert new.field_cursor == 1


def test_navigate_detail_up():
    state = _make_detail_state(5, cursor=3)
    new = navigate_detail(state, KEY_UP, 10)
    assert new.field_cursor == 2


def test_navigate_detail_home():
    state = _make_detail_state(5, cursor=4)
    new = navigate_detail(state, KEY_HOME, 10)
    assert new.field_cursor == 0


def test_navigate_detail_end():
    state = _make_detail_state(5, cursor=0)
    new = navigate_detail(state, KEY_END, 10)
    assert new.field_cursor == 4


def test_navigate_detail_j_k():
    state = _make_detail_state(5, cursor=2)
    assert navigate_detail(state, ord("j"), 10).field_cursor == 3
    assert navigate_detail(state, ord("k"), 10).field_cursor == 1


def test_navigate_detail_at_boundaries():
    state = _make_detail_state(5, cursor=0)
    assert navigate_detail(state, KEY_UP, 10).field_cursor == 0
    state2 = _make_detail_state(5, cursor=4)
    assert navigate_detail(state2, KEY_DOWN, 10).field_cursor == 4


def test_navigate_detail_unhandled_key():
    state = _make_detail_state(5, cursor=2)
    new = navigate_detail(state, ord("x"), 10)
    assert new is state


def test_navigate_detail_empty_fields():
    state = DetailState(uri=BASE + "C", fields=[], field_cursor=0, scroll=0)
    new = navigate_detail(state, KEY_DOWN, 10)
    assert new is state


# ── search_update ─────────────────────────────────────────────────────────────


def test_search_update_typing_char():
    state = _make_tree_state(5)
    state = TreeState(
        flat=state.flat, cursor=0, scroll=0,
        search=SearchState(query="fo", active=True),
    )
    new = search_update(state, ord("o"))
    assert new.search.query == "foo"
    assert new.search.active is True


def test_search_update_backspace():
    state = _make_tree_state(5)
    state = TreeState(
        flat=state.flat, cursor=0, scroll=0,
        search=SearchState(query="foo", active=True),
    )
    new = search_update(state, KEY_BACKSPACE)
    assert new.search.query == "fo"


def test_search_update_backspace_127():
    state = _make_tree_state(5)
    state = TreeState(
        flat=state.flat, cursor=0, scroll=0,
        search=SearchState(query="foo", active=True),
    )
    new = search_update(state, 127)
    assert new.search.query == "fo"


def test_search_update_backspace_empty_query():
    state = _make_tree_state(5)
    state = TreeState(
        flat=state.flat, cursor=0, scroll=0,
        search=SearchState(query="", active=True),
    )
    new = search_update(state, KEY_BACKSPACE)
    assert new.search.query == ""


def test_search_update_escape_clears():
    state = _make_tree_state(5)
    state = TreeState(
        flat=state.flat, cursor=0, scroll=0,
        search=SearchState(query="test", active=True, matches=[1, 2]),
    )
    new = search_update(state, 27)  # Esc
    assert new.search.query == ""
    assert new.search.active is False
    assert new.search.matches == []


def test_search_update_enter_commits():
    state = _make_tree_state(5)
    state = TreeState(
        flat=state.flat, cursor=0, scroll=0,
        search=SearchState(query="test", active=True, matches=[1, 2]),
    )
    new = search_update(state, KEY_ENTER)
    assert new.search.active is False
    assert new.search.query == "test"  # query preserved


def test_search_update_newline_commits():
    state = _make_tree_state(5)
    state = TreeState(
        flat=state.flat, cursor=0, scroll=0,
        search=SearchState(query="test", active=True),
    )
    new = search_update(state, ord("\n"))
    assert new.search.active is False


def test_search_update_tab_jumps_next():
    state = _make_tree_state(10)
    state = TreeState(
        flat=state.flat, cursor=2, scroll=0,
        search=SearchState(query="x", active=True, matches=[2, 5, 8], current_idx=0),
    )
    new = search_update(state, 9)  # Tab
    assert new.search.current_idx == 1
    assert new.cursor == 5


def test_search_update_unhandled_key_returns_same():
    state = _make_tree_state(5)
    state = TreeState(
        flat=state.flat, cursor=0, scroll=0,
        search=SearchState(query="x", active=True),
    )
    new = search_update(state, 1)  # Ctrl+A — unhandled
    assert new is state


# ── update_search_results ─────────────────────────────────────────────────────


def test_update_search_results_sets_cursor():
    state = _make_tree_state(10)
    pattern = re.compile("x")
    new = update_search_results(state, [3, 7], pattern)
    assert new.search.matches == [3, 7]
    assert new.search.pattern is pattern
    assert new.cursor == 3  # first match


def test_update_search_results_empty_matches():
    state = _make_tree_state(10, cursor=5)
    new = update_search_results(state, [], None)
    assert new.search.matches == []
    assert new.cursor == 5  # unchanged


def test_update_search_results_clamps_idx():
    state = _make_tree_state(10)
    state = TreeState(
        flat=state.flat, cursor=0, scroll=0,
        search=SearchState(query="x", active=True, matches=[1, 2, 3], current_idx=5),
    )
    new = update_search_results(state, [1, 2], re.compile("x"))
    assert new.search.current_idx == 0  # clamped


# ── _search_jump ──────────────────────────────────────────────────────────────


def test_search_jump_forward():
    state = _make_tree_state(10)
    state = TreeState(
        flat=state.flat, cursor=2, scroll=0,
        search=SearchState(query="x", active=True, matches=[2, 5, 8], current_idx=0),
    )
    new = _search_jump(state, +1)
    assert new.search.current_idx == 1
    assert new.cursor == 5


def test_search_jump_backward():
    state = _make_tree_state(10)
    state = TreeState(
        flat=state.flat, cursor=5, scroll=0,
        search=SearchState(query="x", active=True, matches=[2, 5, 8], current_idx=1),
    )
    new = _search_jump(state, -1)
    assert new.search.current_idx == 0
    assert new.cursor == 2


def test_search_jump_wraps_forward():
    state = _make_tree_state(10)
    state = TreeState(
        flat=state.flat, cursor=8, scroll=0,
        search=SearchState(query="x", active=True, matches=[2, 5, 8], current_idx=2),
    )
    new = _search_jump(state, +1)
    assert new.search.current_idx == 0
    assert new.cursor == 2


def test_search_jump_wraps_backward():
    state = _make_tree_state(10)
    state = TreeState(
        flat=state.flat, cursor=2, scroll=0,
        search=SearchState(query="x", active=True, matches=[2, 5, 8], current_idx=0),
    )
    new = _search_jump(state, -1)
    assert new.search.current_idx == 2
    assert new.cursor == 8


def test_search_jump_no_matches():
    state = _make_tree_state(5)
    state = TreeState(
        flat=state.flat, cursor=2, scroll=0,
        search=SearchState(query="x", active=True, matches=[]),
    )
    new = _search_jump(state, +1)
    assert new is state
