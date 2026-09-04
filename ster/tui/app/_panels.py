"""Panel-layer navigation: switching between/folding the three left panes, tracking focus layer (panel/item/detail), and the bottom-border nav hint."""

from __future__ import annotations

from typing import Final

from textual import events
from textual.app import ScreenStackError
from textual.css.query import NoMatches
from textual.widgets import Static, Tree
from textual.widgets.tree import TreeNode

from .. import data, detail
from ..detail_view import DetailRow, DetailView
from ._constants import _DETAIL_SELECTOR
from ._helpers import _cta_uri, _nav_hint
from ._state import _AppState
from ._tree_widget import OntologyTree

_LIT_ONT_TREE: Final = "ont-tree"
_LIT_PROP_TREE: Final = "prop-tree"


class _PanelsMixin(_AppState):
    """Mixin: panel-layer navigation: switching between/folding the three left panes, tracking focus layer (panel/item/detail), and the bottom-border nav hint."""

    def _update_lang_indicator(self) -> None:
        """Refresh the bottom-right status with the current display language."""
        indicators = self.query("#lang-indicator")
        if indicators:
            indicators.first(Static).update(f"selected language: {self.lang}")

    _PANEL_IDS = ("tree", _LIT_ONT_TREE, _LIT_PROP_TREE)

    # The main-entity overview each pane shows when it becomes the active one.
    _PANEL_OVERVIEW = {
        "tree": detail.TAXONOMY_URI,
        _LIT_ONT_TREE: detail.OVERVIEW_URI,
        _LIT_PROP_TREE: detail.PROPERTIES_URI,
    }

    def _default_folded(self) -> set[str]:
        """The opening fold state from the file's content: a pure taxonomy folds the ontology
        and properties panes; a pure ontology folds the taxonomy pane; a mix opens all three."""
        has_tax = data.has_taxonomy_content(self.tax)
        has_ont = data.has_ontology_content(self.tax, self.lang)
        if has_tax and not has_ont:
            return {_LIT_ONT_TREE, _LIT_PROP_TREE}
        if has_ont and not has_tax:
            return {"tree"}
        return set()

    def _apply_layout(self) -> None:
        """Fold every pane in ``_folded_panels`` to its titled border bar; the rest share the
        column equally (1fr each)."""
        for pid in self._PANEL_IDS:
            self.query_one(f"#{pid}", Tree).set_class(pid in self._folded_panels, "folded")

    def _panel_main_node(self, pid: str) -> TreeNode | None:
        """The pane's main-entity node — its overview row."""
        overview = self._PANEL_OVERVIEW.get(pid)
        return self._uri_nodes.get(overview) if overview else None

    def _toggle_full(self, pid: str) -> None:
        """Accordion toggle: make *pid* the only open pane (fold the other two), or — when it
        already is — restore the balanced 1/3 layout."""
        others = set(self._PANEL_IDS) - {pid}
        self._folded_panels = set() if self._folded_panels == others else others
        self._apply_layout()

    def _refresh_pane_layer(self, pid: str) -> None:
        """Re-sync a pane's header dimming + border hint after an entered-state change that
        may not have moved the cursor (Enter / Escape both rest on the head)."""
        self.query_one(f"#{pid}", OntologyTree)._sync_panel_layer_class()

    def _select_panel(self, pid: str) -> None:
        """Select a pane (the panel layer): focus it, rest the cursor on its dimmed header, and
        print that pane's overview. No item is entered."""
        self._entered_pid = None
        tree = self.query_one(f"#{pid}", Tree)
        tree.focus()
        node = self._panel_main_node(pid)
        if node is not None:
            tree.move_cursor(node)
        overview = self._PANEL_OVERVIEW.get(pid)
        if overview is not None:  # show it even when the cursor was already on the main entity
            self._show(overview)
        self._refresh_pane_layer(pid)

    def _select_adjacent_panel(self, pid: str, step: int) -> None:
        """Select the next (step=1) / previous (step=-1) pane — Tab / Shift-Tab."""
        nxt = self._PANEL_IDS[(self._PANEL_IDS.index(pid) + step) % len(self._PANEL_IDS)]
        self._select_panel(nxt)

    def _back_to_panel_selection(self) -> None:
        """Escape from the detail pane: re-select the left panel it was reached from (cursor
        on its header — the panel layer), so Tab cycles panels again."""
        pid = self._detail_source_pid if self._detail_source_pid in self._PANEL_IDS else "tree"
        self._select_panel(pid)

    def _hint_target_and_context(self):  # type: ignore[no-untyped-def]
        """The pane widget the border hint belongs on, and its navigation layer — from the
        focused widget: a tree (panel / item by its cursor), or the detail pane."""
        try:
            focused = self.focused
            if isinstance(focused, OntologyTree):
                return focused, ("panel" if focused.has_class("panel-layer") else "item")
            if isinstance(focused, DetailRow):
                return self.query(_DETAIL_SELECTOR).first(), "detail"
            if isinstance(focused, DetailView):
                return focused, "detail"
            return None, None
        except (ScreenStackError, NoMatches):  # pragma: no cover
            # Handle cases where the app is starting up/shutting down (no screen stack)
            # or widgets are missing during a transition.
            return None, None

    def _update_nav_hint(self) -> None:
        """Show the contextual key hint on the focused pane's bottom border; clear the rest,
        so exactly one hint shows and it always matches the current layer."""
        target, context = self._hint_target_and_context()
        hint = _nav_hint(context)
        # Use query instead of query_one for #detail to avoid NoMatches during transitions/modals
        for pane in (*self.query(OntologyTree), *self.query(_DETAIL_SELECTOR)):
            pane.border_subtitle = hint if pane is target else ""

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        """Refresh the contextual key hint whenever focus crosses panes or reaches the detail."""
        self._update_nav_hint()

    def _return_to_source_item(self) -> None:
        """Tab from the detail pane: toggle back to the exact tree item it was reached from
        (the item layer). Falls back to the pane header if that item is gone."""
        pid = self._detail_source_pid if self._detail_source_pid in self._PANEL_IDS else "tree"
        node = self._uri_nodes.get(self._detail_source_uri) if self._detail_source_uri else None
        if node is None:
            self._select_panel(pid)
            return
        self._entered_pid = pid  # back in the item layer
        tree = self.query_one(f"#{pid}", Tree)
        tree.focus()
        tree.move_cursor(node)
        self._refresh_pane_layer(pid)

    def _enter_panel_full(self, pid: str) -> None:
        """Enter a pane from the panel layer (Enter): fold the other panes so this one opens to
        full height, and select its head as the first item (the item layer). The head has its
        own overview detail, so it navigates to the detail pane like any other item."""
        self._entered_pid = pid
        self._folded_panels = set(self._PANEL_IDS) - {pid}
        self._apply_layout()
        tree = self.query_one(f"#{pid}", Tree)
        tree.focus()
        node = self._panel_main_node(pid)
        if node is not None:
            tree.move_cursor(node)  # the head becomes the selected item
        self._refresh_pane_layer(pid)

    def _cta(self, parent: TreeNode, label: str, action: str) -> None:
        """Add a dim call-to-action leaf under an *empty* section — activating it (Enter /
        click) runs *action*'s create flow. Shown only while the section is empty."""
        parent.add(f"[dim green]{label}[/dim green]", data=_cta_uri(action))
