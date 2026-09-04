"""Opening the VOWL graph viewer in the browser, including reclaiming a stuck port."""

from __future__ import annotations

from ster.nav.logic import DetailField

from ._state import _AppState


class _GraphMixin(_AppState):
    """Mixin: opening the VOWL graph viewer in the browser, including reclaiming a stuck port."""

    def _open_graph(self, action: str, field: DetailField) -> None:
        """Detail-pane / context-menu graph action → the shared graph opener."""
        if action == "view_focused_graph":
            target = field.meta.get("uri") or self._detail_uri
            if not target:
                self.notify("No entity to focus the graph on.", severity="warning")
                return
            self._show_graph(target)
        else:
            self._show_graph(None)

    def action_open_graph(self) -> None:
        """The 'g' shortcut: open (or update) the graph from the tree selection —
        focused on the selected OWL class/individual, else the whole-ontology graph."""
        self._show_graph(self._graph_focus_target())

    def _graph_focus_target(self) -> str | None:
        """The entity to centre the graph on for 'g': the selected class or individual,
        a linked concept's focus class, else None (→ the global graph)."""
        uri = self._detail_uri
        if uri and (uri in self.tax.owl_classes or uri in self.tax.owl_individuals):
            return uri
        concept = self.tax.concepts.get(uri) if uri else None
        if concept is not None and concept.focus:  # a foaf:focus-linked concept → its class
            return concept.focus
        return None

    def _show_graph(self, target: str | None) -> None:
        """Open (or update) the VOWL graph in the browser — focused on *target* when given.

        A view, not a mutation. When the live-server port is already held by a previous
        graph process, reclaim it (close that process) and open — no prompt, since
        re-opening the graph should simply replace the old window — see
        :meth:`_reclaim_port_and_open`. (``fastapi``/``uvicorn`` are core deps, so the live
        server itself is always available; the only blocker is a busy port.)
        """
        from ster import viz_vowl

        if not viz_vowl.is_live_server():
            holder = viz_vowl.port_holder()
            if holder is not None:
                self._reclaim_port_and_open(holder, target)
                return
        self._open_graph_now(target)

    def _open_graph_now(self, target: str | None) -> None:
        """Open the graph browser tab now (the live server when the port is free, else the
        static offline snapshot), reporting the URL or any failure."""
        from ster import viz_vowl

        try:
            if target is not None:
                url = viz_vowl.open_focused_in_browser(self.tax, target, self._path)
            else:
                url = viz_vowl.open_in_browser(self.tax, self._path)
            self.notify(f"Graph opened in your browser — {url}")
        except Exception as exc:  # surfacing beats crashing the UI for a view action
            self.notify(f"Couldn't open the graph: {exc}", severity="error")

    def _reclaim_port_and_open(self, holder: tuple[int, str], target: str | None) -> None:
        """A previous graph window/process holds the live-server port — close it, then
        open the graph. No prompt: re-opening the graph just replaces the old window. If
        the process can't be closed, ``_open_graph_now`` still opens a read-only snapshot
        (the port is busy), so the view always appears — it never hangs on a modal."""
        from ster import viz_vowl

        pid, _desc = holder
        if viz_vowl.free_port(pid):
            self.notify(f"Closed the previous graph window (PID {pid}).")
        else:
            self.notify(
                f"Couldn't close the previous graph process (PID {pid}) — "
                "opening a read-only snapshot instead.",
                severity="warning",
            )
        self._open_graph_now(target)
