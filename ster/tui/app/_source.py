"""The right pane's source face: the selected entity as Turtle.

Reading the file as code rather than through the composed detail panel. The two
share one slot via a ``ContentSwitcher``, so this mixin owns only the switch,
the graph the text is cut from, and keeping that graph honest when the model
changes underneath it.

**Why the graph is cached, and why it is built late.** The text comes from the
session's whole graph — the model plus its residue plus any context files —
because that is the only view in which "what points at this entity" is
answerable. Building it costs a full model→graph pass, far too much to repeat
on every arrow keypress down a tree. So it is built on first use and kept until
an edit invalidates it, and it is never built at all for a reader who does not
open the pane: a cost nobody pays until they ask for it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.widgets import ContentSwitcher

from ..source_view import SourceView
from ._constants import _RIGHT_SELECTOR, _SOURCE_SELECTOR
from ._state import _AppState

if TYPE_CHECKING:
    from pathlib import Path

    import rdflib

    from ster.store import Provenance


class _SourceMixin(_AppState):
    """Mixin: the Turtle view of the selected entity, in the right-hand slot."""

    def _source_graph(self) -> rdflib.Graph:
        """The session as one graph, built once and kept until an edit lands."""
        from ster.store import full_graph_rdflib  # noqa: PLC0415

        if self._source_graph_cache is None:
            self._source_graph_cache = full_graph_rdflib(self.tax)
        return self._source_graph_cache

    def _source_provenance(self) -> Provenance:
        """Which file each statement came from — built with the graph, dropped with it."""
        from ster.store import provenance  # noqa: PLC0415

        if self._source_provenance_cache is None:
            self._source_provenance_cache = provenance(self.tax)
        return self._source_provenance_cache

    def _source_locate(self, path: Path, uri: str) -> list[int]:
        """Where *uri* starts its statements in *path* — each file read once.

        Kept with the graph and dropped with it: an edit saved to disk moves
        lines, and a stale number would send the reader to the wrong place.
        """
        from ster.source_lines import SourceLines  # noqa: PLC0415

        if path not in self._source_lines_cache:
            self._source_lines_cache[path] = SourceLines.from_file(path)
        lines = self._source_lines_cache[path]
        return lines.starts(uri) if lines is not None else []

    def _invalidate_source(self) -> None:
        """Drop the cached graph: the next look recomputes it.

        Remembered scroll positions go with it. They are line offsets, and after
        an edit the same number points at a different statement, so restoring one
        would quietly put the reader somewhere they never were. The entity on
        screen is the exception — the refresh below re-remembers where it is,
        because throwing the reader to the top of the file for an edit they just
        made themselves is the more jarring half of the trade.
        """
        self._source_graph_cache = None
        self._source_provenance_cache = None
        self._source_lines_cache = {}
        try:
            self.query_one(_SOURCE_SELECTOR, SourceView).forget_scroll()
        except Exception:  # noqa: BLE001 — before mount there is nothing to forget
            pass
        if self._source_showing:
            self._refresh_source(self._detail_uri)

    def _source_visible(self) -> bool:
        return bool(self._source_showing)

    def _refresh_source(self, uri: str | None) -> None:
        """Put *uri*'s Turtle in the pane. Cheap to call when the pane is hidden."""
        if not self._source_showing:
            return  # nothing on screen to update, and the graph is not worth building
        from ster.entity_source import entity_source  # noqa: PLC0415

        view = self.query_one(_SOURCE_SELECTOR, SourceView)
        source = (
            entity_source(
                self._source_graph(),
                uri,
                provenance=self._source_provenance(),
                locate=self._source_locate,
            )
            if uri
            else None
        )
        view.show(uri, source)
        view.border_title = self._source_title(uri, source)

    def _source_title(self, uri: str | None, source: object | None) -> str:
        """``Source`` plus what is in it — the inbound count is the pane's own news."""
        if uri is None or source is None:
            return "Source"
        incoming = getattr(source, "incoming", 0)
        omitted = getattr(source, "omitted", 0)
        if not incoming:
            return "Source"
        shown = incoming - omitted
        return (
            f"Source — {shown} of {incoming} inbound" if omitted else f"Source — {incoming} inbound"
        )

    def action_toggle_source(self) -> None:
        """``r``: swap the right pane's face, and move nothing else.

        Not the tree cursor, not the focus. Switching how the right pane draws
        the selection is not a navigation, and treating it as one costs the
        reader the place they were working — the whole point of the pane is to
        step down the tree with the source beside it.

        So focus is left wherever it is, which is normally the tree: the arrows
        keep walking entities and the pane keeps up.
        """
        switcher = self.query_one(_RIGHT_SELECTOR, ContentSwitcher)
        view = self.query_one(_SOURCE_SELECTOR, SourceView)
        self._source_showing = not self._source_showing
        if self._source_showing:
            switcher.current = "source"
            self._refresh_source(self._detail_uri)
            return
        view.remember_scroll()
        # Focus only needs rescuing when it is inside the pane about to be
        # hidden, which happens only if the reader put it there deliberately.
        # Back to the tree *item* — _back_to_panel_selection would drop the
        # cursor on the panel header, which is what Escape means, not ``r``.
        focused = self.focused
        if focused is not None and view in focused.ancestors_with_self:
            self._return_to_source_item()
        switcher.current = "detail"
