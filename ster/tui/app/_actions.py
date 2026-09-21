"""Miscellaneous top-level key bindings: help screen, copy-to-clipboard, opening the map/query views, and expand/collapse-all."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Literal

from textual.widgets import Tree

from ..detail_view import DetailRow
from ..help_screen import HelpScreen
from ._constants import _TREE_SELECTOR
from ._state import _AppState
from ._tree_widget import OntologyTree

if TYPE_CHECKING:  # pragma: no cover - typing only
    import rdflib

    from ...viz_shared import ReachFn

# Textual's own severity name, spelled once: three notifications in this module
# use it and the duplicate-literal rule counts the third as drift. Typed as the
# literal rather than as str, because notify() takes a Literal and a widened
# constant silently stops satisfying it.
_WARNING: Final[Literal["warning"]] = "warning"


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
        """The 'm' shortcut: map the selection, or everything that carries coordinates.

        A view, not a mutation. Three answers, in order.

        A file with no geography at all gets a warning and no window. An empty
        map is not an answer — it reads as a broken feature, and the reader
        cannot tell it apart from one that failed to load.

        A selection that can be put on a map opens focused on it. "Can be" is
        read through what it is linked to, not only what it carries: a brand
        holds no coordinates and its stores hold them all.

        A selection that reaches nothing placeable still opens the whole map,
        saying so. Refusing there would be worse than the map the reader asked
        for, and the file does have something to show.
        """
        from ster.geo_shapes import anything_located, located_from  # noqa: PLC0415
        from ster.store import full_graph_rdflib  # noqa: PLC0415

        from .. import query as _query

        if not _query.server_is_running():
            self.notify(_query.server_unavailable_reason(), severity=_WARNING)
            return

        # The session as one graph, not the file on disk: the same view the map
        # itself is built from, so what the reader is told matches what opens.
        graph = full_graph_rdflib(self.tax)
        if not anything_located(graph):
            self.notify(
                "Nothing in this file can be put on a map — no coordinates and no shapes.",
                severity=_WARNING,
            )
            return

        focus = self._map_focus_target(graph, located_from)
        url = _query.map_url("", focus)  # empty query → the server builds one
        if not _query.open_browser(url):
            self.notify("Couldn't open a browser for the map.", severity=_WARNING)
            return
        self.notify(f"Map opened in your browser — {url}")

    def action_open_timeline(self) -> None:
        """The 't' shortcut: put the selection on a time axis, or the whole file.

        The same three answers as :meth:`action_open_map`, and deliberately the
        same shape: a file with no dates gets a warning and no window, a
        selection that reaches something dated opens focused on it, and one that
        reaches nothing still opens the whole frieze rather than refusing.

        "Reaches" is read through what points at the selection, not only what it
        carries: a procedure holds no date of its own and its events hold them
        all.
        """
        from ster.store import full_graph_rdflib  # noqa: PLC0415
        from ster.time_shapes import anything_dated, dated_from  # noqa: PLC0415

        from .. import query as _query

        if not _query.server_is_running():
            self.notify(_query.server_unavailable_reason(), severity=_WARNING)
            return

        graph = full_graph_rdflib(self.tax)
        if not anything_dated(graph):
            self.notify(
                "Nothing in this file can be put on a timeline — no dates.",
                severity=_WARNING,
            )
            return

        focus = self._timeline_focus_target(graph, dated_from)
        url = _query.timeline_url("", focus)  # empty query → the server builds one
        if not _query.open_browser(url):
            self.notify("Couldn't open a browser for the timeline.", severity=_WARNING)
            return
        self.notify(f"Timeline opened in your browser — {url}")

    def _timeline_focus_target(self, graph: rdflib.Graph, dated_from: ReachFn) -> str | None:
        """The selected entity, when it can put anything on a time axis."""
        import rdflib  # noqa: PLC0415

        uri = self._detail_uri
        if not uri:
            return None
        if dated_from(graph, rdflib.URIRef(uri)):
            return uri
        self.notify(f"{uri.rsplit('#', 1)[-1]} has no dates — showing the whole file.")
        return None

    def _map_focus_target(self, graph: rdflib.Graph, located_from: ReachFn) -> str | None:
        """The selected entity, when it can put anything on a map.

        Returns None — and says why — when the selection reaches nothing
        placeable, so the caller opens the whole map rather than a blank one.
        """
        import rdflib  # noqa: PLC0415

        uri = self._detail_uri
        if not uri:
            return None
        if located_from(graph, rdflib.URIRef(uri)):
            return uri
        self.notify(f"{uri.rsplit('#', 1)[-1]} has nothing on the map — showing the whole file.")
        return None

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
