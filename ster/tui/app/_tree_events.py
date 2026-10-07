"""Tree widget event handlers (highlight/select) and jumping the cursor to a given entity URI, including from the command-palette search."""

from __future__ import annotations

import time

from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from ster.nav.logic import DetailField

from .. import detail
from ._constants import _PROP_CREATE_ACTIONS
from ._detail import DETAIL_SETTLE_S
from ._helpers import _parse_add_prop, _parse_cta
from ._state import _AppState


class _TreeEventsMixin(_AppState):
    """Mixin: tree widget event handlers (highlight/select) and jumping the cursor to a given entity URI, including from the command-palette search."""

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        if event.node.tree.has_class("main-tree"):  # remember which main pane to return focus to
            self._active_main_tree_id = event.node.tree.id or "tree"
        uri = event.node.data
        # Property-tree headers ("Object/Datatype/Annotation Properties") and empty-section
        # call-to-action leaves carry a sentinel and have no detail panel — clear the pane.
        if uri and (_parse_add_prop(uri) is not None or _parse_cta(uri) is not None):
            self._show(None)
            return
        if uri == self._detail_uri:
            # Re-highlighting the entity already shown (e.g. a programmatic cursor move
            # after a mutation) must not rebuild the detail — that would drop the focus
            # _restore_focus just placed on a row. The explicit _show already refreshed it.
            return
        now = time.monotonic()
        sweeping = now - self._last_highlight < DETAIL_SETTLE_S  # a key held down, or tapped fast
        self._last_highlight = now
        if sweeping:
            self._defer_show(uri)  # the panel is drawn once, where the cursor stops
        else:
            self._show(uri)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:  # noqa: V105
        """Activating (Enter / click) an empty-section call-to-action runs its create flow."""
        action = _parse_cta(event.node.data)
        if action is not None:
            self._run_cta(action)

    def _run_cta(self, action: str) -> None:
        """Run a call-to-action's create flow. Property creates need no entity context; a
        class / scheme create runs via _run_field_action, so anchor it on the always-present
        section node (its uri is only a non-None target, unused by the top-level create)."""
        prop_type = _PROP_CREATE_ACTIONS.get(action)
        if prop_type is not None:
            self._open_property_create(prop_type)
            return
        self._detail_uri = (
            detail.OVERVIEW_URI if action == "create_owl_class" else detail.TAXONOMY_URI
        )
        self._run_field_action(
            DetailField("cta", "", "", editable=False, meta={"type": "action", "action": action})
        )

    def jump_to(self, uri: str) -> None:
        """Expand ancestors, move the cursor to *uri* (focusing the tree), show its detail."""
        if self._reveal_in_tree(uri, focus=True):
            self._show(uri)  # detail is independent of tree layout — show it now
        else:
            self.notify(f"Not in tree: {uri}", severity="warning")

    def _reveal_in_tree(self, uri: str, *, focus: bool) -> bool:
        """Expand *uri*'s ancestors and move the cursor onto its node. Returns False
        when *uri* has no tree node. *focus* steals keyboard focus to the tree — off
        for background refreshes so the user's current focus is preserved."""
        node = self._uri_nodes.get(uri)
        if node is None:
            return False
        tree = node.tree  # the pane the node lives in (main tree or the property tree)
        parent = node.parent
        while parent is not None:
            parent.expand()
            parent = parent.parent
        # expand() only takes effect on the next refresh, so move the cursor after it:
        self.call_after_refresh(self._focus_tree_node, tree, node, focus)
        return True

    def _focus_tree_node(self, tree: Tree, node: TreeNode, focus: bool = True) -> None:
        tree.move_cursor(node)
        tree.scroll_to_node(node)
        if focus:
            tree.focus()
