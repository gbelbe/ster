"""Typed state machine for TaxonomyViewer.

Each viewer mode has its own dataclass carrying exactly the state it needs.
The ``ViewerState`` union type and ``Effect`` types allow the update functions
to be pure (no curses, no I/O) and therefore fully unit-testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path

from .nav_logic import DetailField, TreeLine

# ── Search state (embedded in TreeState) ──────────────────────────────────────


@dataclass
class SearchState:
    query: str = ""
    active: bool = False  # True while the user is typing in the search bar
    matches: list[int] = dc_field(default_factory=list)  # indices into TreeState.flat
    current_idx: int = 0  # which match the cursor sits on
    pattern: re.Pattern | None = None


# ── Per-mode states ────────────────────────────────────────────────────────────


@dataclass
class TreeState:
    flat: list[TreeLine] = dc_field(default_factory=list)
    cursor: int = 0
    scroll: int = 0
    folded: set[str] = dc_field(default_factory=set)
    search: SearchState = dc_field(default_factory=SearchState)


@dataclass
class WelcomeState:
    pass


@dataclass
class DetailState:
    uri: str = ""
    fields: list[DetailField] = dc_field(default_factory=list)
    field_cursor: int = 0
    scroll: int = 0


@dataclass
class CreateState:
    parent_uri: str | None = None
    fields: list[DetailField] = dc_field(default_factory=list)
    cursor: int = 0
    scroll: int = 0
    error: str = ""
    came_from_tree: bool = False  # True when triggered from tree mode (cancel → tree)
    # Add-concept step: "choose" | "prompt_review" | "ai_pick" | "form"
    # Default "form" keeps all existing call-sites unchanged.
    step: str = "form"
    ai_candidates: list[str] = dc_field(default_factory=list)
    ai_checked: list[bool] = dc_field(default_factory=list)  # parallel to ai_candidates
    ai_seen: list[str] = dc_field(default_factory=list)
    ai_generating: bool = False
    ai_cursor: int = 0
    ai_scroll: int = 0
    ai_prompt_preview: str = ""


@dataclass
class SchemeCreateState:
    fields: list[DetailField] = dc_field(default_factory=list)
    cursor: int = 0
    scroll: int = 0
    error: str = ""
    came_from_tree: bool = False  # True when triggered from tree mode (cancel → tree)


@dataclass
class EditState:
    buffer: str = ""
    pos: int = 0
    field: DetailField | None = None
    # None → return to detail; CreateState/SchemeCreateState → return to that form
    return_to: CreateState | SchemeCreateState | None = None


@dataclass
class ConfirmDeleteState:
    uri: str = ""


@dataclass
class MovePickState:
    source_uri: str = ""
    is_link: bool = False  # kept for compat; prefer pick_type
    pick_type: str = "move"  # "move" | "link_broader" | "add_related"
    candidates: list[tuple[str, str]] = dc_field(default_factory=list)  # (uri, label)
    filter_text: str = ""
    cursor: int = 0
    scroll: int = 0


@dataclass
class LangPickState:
    options: list[str] = dc_field(default_factory=list)
    cursor: int = 0
    scroll: int = 0


@dataclass
class MapSchemePickState:
    source_uri: str = ""
    map_type: str = ""
    candidates: list[tuple[str, str]] = dc_field(default_factory=list)
    cursor: int = 0
    scroll: int = 0


@dataclass
class MapConceptPickState:
    source_uri: str = ""
    map_type: str = ""
    target_scheme: str = ""
    candidates: list[tuple[str, str]] = dc_field(default_factory=list)
    filter_text: str = ""
    cursor: int = 0
    scroll: int = 0


@dataclass
class AiInstallState:
    """Confirmation overlay: install the llm package, then resume an action."""

    pending_action: str = ""  # action to trigger after successful install
    installing: bool = False  # True while pip is running
    done: bool = False  # True after successful install
    lines: list[str] = dc_field(default_factory=list)  # pip output lines
    error: str = ""


@dataclass
class AiSetupState:
    """Guided model setup wizard: mode → provider → model → key? → done.

    online_providers / offline_providers are fetched once when the wizard opens
    via ai.discover_models() and stored here so navigation is instant.
    Each entry: (provider_id, display_label, [(model_id, display_label)]).
    """

    step: str = (
        "mode"  # "mode" | "provider" | "model" | "key" | "done"  (mode "copypaste" → skips to done)
    )
    mode: str = ""  # "online" | "offline"
    # Pre-fetched provider + model data (populated at wizard open time)
    online_providers: list[tuple[str, str, list[tuple[str, str]]]] = dc_field(default_factory=list)
    offline_providers: list[tuple[str, str, list[tuple[str, str]]]] = dc_field(default_factory=list)
    # Navigation
    provider_cursor: int = 0
    provider_scroll: int = 0
    model_cursor: int = 0
    model_scroll: int = 0
    # Selections
    selected_provider_id: str = ""
    selected_model_id: str = ""
    key_name: str = ""
    # API key text input
    buffer: str = ""
    pos: int = 0
    error: str = ""
    pending_action: str = ""  # action to resume after setup completes
    # Plugin install sub-step (used when step == "install_plugin")
    available_plugins: list[tuple[str, str, str]] = dc_field(default_factory=list)
    plugin_cursor: int = 0
    plugin_scroll: int = 0
    plugin_installing: bool = False
    plugin_done: bool = False
    plugin_error: str = ""
    plugin_lines: list[str] = dc_field(default_factory=list)
    selected_plugin_pkg: str = ""
    selected_plugin_label: str = ""


@dataclass
class BatchConceptDraft:
    """Evolving data for one concept being built in the batch creation wizard."""

    name: str  # original AI-suggested name (used as URI slug)
    pref_label: str  # editable preferred label
    alt_labels: list[str] = dc_field(default_factory=list)  # AI-suggested alt labels
    alt_checked: list[bool] = dc_field(default_factory=list)  # True = include in concept
    definition: str = ""  # AI-suggested / user-edited definition
    # Per-draft generation flags (polled from the main loop)
    alts_generating: bool = False
    def_generating: bool = False
    alts_error: str = ""
    def_error: str = ""


@dataclass
class BatchCreateState:
    """Wizard state for creating multiple AI-selected concepts in one flow.

    Steps per concept: "label" → "alt_labels" → "definition" → "confirm"
    After all concepts: recap → done
    """

    parent_uri: str | None = None
    came_from_tree: bool = False
    drafts: list[BatchConceptDraft] = dc_field(default_factory=list)
    current: int = 0  # index of concept currently being edited
    step: str = "label"  # "label" | "alt_labels" | "definition" | "confirm" | "recap"
    # label step — inline text buffer
    label_buffer: str = ""
    label_pos: int = 0
    # alt_labels step — cursor over checkbox rows + "Done" action
    alt_cursor: int = 0
    alt_scroll: int = 0
    # definition step — inline text buffer
    def_pos: int = 0
    # confirm step — shown after each concept is created
    confirm_cursor: int = 0  # 0 = Continue, 1 = Stop
    # recap step
    recap_cursor: int = 0
    recap_scroll: int = 0
    error: str = ""


ViewerState = (
    TreeState
    | WelcomeState
    | DetailState
    | EditState
    | CreateState
    | SchemeCreateState
    | BatchCreateState
    | ConfirmDeleteState
    | MovePickState
    | LangPickState
    | MapSchemePickState
    | MapConceptPickState
    | AiInstallState
    | AiSetupState
)


# ── Effects ────────────────────────────────────────────────────────────────────
# Pure functions return a list of Effects instead of executing side effects
# directly. The curses loop (TaxonomyViewer._execute) runs them.


@dataclass(frozen=True)
class Rebuild:
    """Rebuild the flat tree (after fold/unfold, taxonomy mutation, etc.)."""


@dataclass(frozen=True)
class SaveFile:
    uri: str | None = None
    path: Path | None = None


@dataclass(frozen=True)
class StageGit:
    pass


@dataclass(frozen=True)
class Quit:
    pass


Effect = Rebuild | SaveFile | StageGit | Quit


# ── Tree navigation (pure — no curses, no taxonomy access) ────────────────────


def navigate_tree(state: TreeState, key: int, list_h: int) -> TreeState:
    """Handle cursor-movement and fold-toggle keys in tree mode.

    Pure: only moves the cursor / adjusts scroll. Returns the updated state.
    Caller is responsible for clamping scroll and executing side-effect keys.

    Key codes deliberately use integer literals to avoid importing curses here.
    """
    n = len(state.flat)
    if n == 0:
        return state

    cursor = state.cursor

    # ── numeric curses key constants (portable across platforms) ──────────────
    KEY_UP = 259  # curses.KEY_UP
    KEY_DOWN = 258  # curses.KEY_DOWN
    KEY_HOME = 262  # curses.KEY_HOME
    KEY_END = 360  # curses.KEY_END
    KEY_PPAGE = 339  # curses.KEY_PPAGE (Page Up)
    KEY_NPAGE = 338  # curses.KEY_NPAGE (Page Down)

    if key in (KEY_UP, ord("k")):
        cursor = max(0, cursor - 1)
    elif key in (KEY_DOWN, ord("j")):
        cursor = min(n - 1, cursor + 1)
    elif key in (KEY_HOME, ord("g")):
        cursor = 0
    elif key in (KEY_END, ord("G")):
        cursor = n - 1
    elif key == KEY_PPAGE:
        cursor = max(0, cursor - list_h)
    elif key == KEY_NPAGE:
        cursor = min(n - 1, cursor + list_h)
    elif key == 4:  # Ctrl+D — half-page down
        cursor = min(n - 1, cursor + list_h // 2)
    elif key == 21:  # Ctrl+U — half-page up
        cursor = max(0, cursor - list_h // 2)
    else:
        return state  # unhandled key — caller deals with it

    # Adjust scroll so cursor stays visible
    scroll = clamp_scroll(state.scroll, cursor, list_h)
    return TreeState(
        flat=state.flat,
        cursor=cursor,
        scroll=scroll,
        folded=state.folded,
        search=state.search,
    )


def search_update(state: TreeState, key: int) -> TreeState:
    """Handle search-bar keypresses when search is active.

    Pure. Returns updated TreeState. Does NOT compile the regex — caller
    computes the pattern and match list and passes it back via update_search().
    """
    KEY_BACKSPACE = 263  # curses.KEY_BACKSPACE
    KEY_ENTER = 343  # curses.KEY_ENTER
    KEY_DOWN = 258
    KEY_UP = 259
    KEY_BTAB = 353  # curses.KEY_BTAB (Shift+Tab)

    s = state.search

    if key == 27:  # Esc
        new_search = SearchState()
        return TreeState(
            flat=state.flat,
            cursor=state.cursor,
            scroll=state.scroll,
            folded=state.folded,
            search=new_search,
        )

    if key in (KEY_BACKSPACE, 127, 8):
        new_query = s.query[:-1] if s.query else ""
        return _replace_search(
            state,
            SearchState(
                query=new_query,
                active=True,
                matches=s.matches,
                current_idx=s.current_idx,
                pattern=s.pattern,
            ),
        )

    if key in (KEY_ENTER, ord("\n"), ord("\r")):
        # Commit — deactivate typing, keep highlights, open detail
        return _replace_search(
            state,
            SearchState(
                query=s.query,
                active=False,
                matches=s.matches,
                current_idx=s.current_idx,
                pattern=s.pattern,
            ),
        )

    if key in (9, KEY_DOWN):  # Tab / ↓ — next match
        return _search_jump(state, +1)

    if key in (KEY_BTAB, KEY_UP):  # Shift+Tab / ↑ — prev
        return _search_jump(state, -1)

    if 32 <= key < 256:
        new_query = s.query + chr(key)
        return _replace_search(
            state,
            SearchState(
                query=new_query,
                active=True,
                matches=s.matches,
                current_idx=s.current_idx,
                pattern=s.pattern,
            ),
        )

    return state


def update_search_results(
    state: TreeState, matches: list[int], pattern: re.Pattern | None
) -> TreeState:
    """Inject computed search results (match indices + compiled pattern) into state."""
    s = state.search
    new_idx = s.current_idx
    if matches and (new_idx >= len(matches)):
        new_idx = 0

    cursor = matches[new_idx] if matches else state.cursor
    scroll = clamp_scroll(state.scroll, cursor, max(1, len(state.flat)))
    return TreeState(
        flat=state.flat,
        cursor=cursor,
        scroll=scroll,
        folded=state.folded,
        search=SearchState(
            query=s.query, active=s.active, matches=matches, current_idx=new_idx, pattern=pattern
        ),
    )


def navigate_detail(state: DetailState, key: int, list_h: int) -> DetailState:
    """Move the field cursor in detail mode. Pure."""
    n = len(state.fields)
    if n == 0:
        return state

    KEY_UP = 259
    KEY_DOWN = 258
    KEY_HOME = 262
    KEY_END = 360

    fc = state.field_cursor
    if key in (KEY_UP, ord("k")):
        fc = max(0, fc - 1)
    elif key in (KEY_DOWN, ord("j")):
        fc = min(n - 1, fc + 1)
    elif key in (KEY_HOME, ord("g")):
        fc = 0
    elif key in (KEY_END, ord("G")):
        fc = n - 1
    else:
        return state

    scroll = clamp_scroll(state.scroll, fc, list_h)
    return DetailState(uri=state.uri, fields=state.fields, field_cursor=fc, scroll=scroll)


# ── Scroll helper ─────────────────────────────────────────────────────────────


def clamp_scroll(scroll: int, cursor: int, list_h: int) -> int:
    """Ensure *cursor* is visible within [scroll, scroll+list_h)."""
    if list_h <= 0:
        return 0
    if cursor < scroll:
        return cursor
    if cursor >= scroll + list_h:
        return cursor - list_h + 1
    return scroll


# ── Internal helpers ──────────────────────────────────────────────────────────


def _replace_search(state: TreeState, new_search: SearchState) -> TreeState:
    return TreeState(
        flat=state.flat,
        cursor=state.cursor,
        scroll=state.scroll,
        folded=state.folded,
        search=new_search,
    )


def _search_jump(state: TreeState, direction: int) -> TreeState:
    s = state.search
    if not s.matches:
        return state
    new_idx = (s.current_idx + direction) % len(s.matches)
    cursor = s.matches[new_idx]
    scroll = clamp_scroll(state.scroll, cursor, max(1, len(state.flat)))
    return TreeState(
        flat=state.flat,
        cursor=cursor,
        scroll=scroll,
        folded=state.folded,
        search=SearchState(
            query=s.query,
            active=s.active,
            matches=s.matches,
            current_idx=new_idx,
            pattern=s.pattern,
        ),
    )
