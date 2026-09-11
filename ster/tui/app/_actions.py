"""Miscellaneous top-level key bindings: help screen, copy-to-clipboard, opening the map/query views, and expand/collapse-all."""

from __future__ import annotations

from textual.widgets import Tree

from ..detail_view import DetailRow
from ..help_screen import HelpScreen
from ._constants import _TREE_SELECTOR
from ._state import _AppState
from ._tree_widget import OntologyTree


class _ActionsMixin(_AppState):
    """Mixin: miscellaneous top-level key bindings: help screen, copy-to-clipboard, opening the map/query views, and expand/collapse-all."""

    def action_open_query(self) -> None:
        """Open the SPARQL query workspace over the live taxonomy. On close, make sure the
        browser behind it is painted (it may have been deferred when we opened into query)."""
        from ..query_screen import QueryScreen

        self.push_screen(QueryScreen(self.tax), lambda _result: self._ensure_browser_ready())

    def action_help(self) -> None:
        """Open the keys-and-actions help overlay."""
        self.push_screen(HelpScreen())

    def action_copy(self) -> None:
        """Ctrl+C / Cmd+C: copy the current text selection, or — with nothing selected — the
        value under the focus (a tree node's URI, or a detail row's value). Copies to the
        system clipboard (OSC 52, so it works over SSH too) and confirms with a toast."""
        text = self.screen.get_selected_text() or self._focused_copy_value()
        if not text:
            return
        from ..clipboard import copy_to_system_clipboard

        self.copy_to_clipboard(text)  # OSC 52 — reaches the *client* clipboard over SSH
        local = copy_to_system_clipboard(text)  # local OS clipboard — when OSC 52 is ignored
        shown = text if len(text) <= 60 else text[:57] + "…"
        where = "" if local else "  (OSC 52 — enable clipboard access in your terminal)"
        self.notify(f"Copied: {shown}{where}", timeout=3)

    def _focused_copy_value(self) -> str | None:
        """The value worth copying under the focus: a detail row's value, or a tree node's
        URI (sentinels / headers have no copyable value)."""
        focused = self.focused
        if isinstance(focused, DetailRow):
            return focused.field.value or None
        if isinstance(focused, OntologyTree):
            node = focused.cursor_node
            data = node.data if node is not None else None
            if isinstance(data, str) and data.startswith(
                (
                    "http://",  # NOSONAR - scheme prefix, not a URL
                    "https://",
                )
            ):
                return data
        return None

    def action_open_map(self) -> None:
        """The 'm' shortcut: map everything in the file that carries coordinates.

        A view, not a mutation. The page's default query asks for anything with
        WGS84 coordinates, so concepts, classes and individuals all appear —
        what is mapped depends on the data, not the kind of entity.
        """
        from .. import query as _query

        if not _query.server_is_running():
            self.notify(_query.server_unavailable_reason(), severity="warning")
            return
        url = _query.map_url("")  # empty query → the server's "anything located" default
        if not _query.open_browser(url):
            self.notify("Couldn't open a browser for the map.", severity="warning")
            return
        self.notify(f"Map opened in your browser — {url}")

    def _active_tree(self) -> Tree:
        """The tree the expand/collapse shortcuts act on: whichever pane is focused
        (unified, ontology, or properties), falling back to the unified main tree."""
        focused = self.focused
        for tree_id in ("#ont-tree", "#prop-tree"):
            if focused is self.query_one(tree_id, Tree):
                return focused  # type: ignore[return-value]
        return self.query_one(_TREE_SELECTOR, Tree)

    def _focus_main_tree(self) -> None:
        """Return focus to the main pane the user was last in (unified or ontology) —
        e.g. after closing the context menu or stepping left out of the detail pane."""
        self.query_one(f"#{self._active_main_tree_id}", Tree).focus()

    def action_expand_all(self) -> None:
        self._active_tree().root.expand_all()

    def action_collapse_all(self) -> None:
        for child in self._active_tree().root.children:
            child.collapse_all()
