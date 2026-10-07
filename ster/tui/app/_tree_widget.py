"""The left-pane ``Tree`` subclass: panel-layer/item-layer cursor styling
(dimming the header outside the item layer, keeping the cursor's own guide
column lit) and expand-to-materialize-deferred-children.
"""

from __future__ import annotations

from collections.abc import Callable

from rich.style import Style
from rich.text import Text
from textual import events
from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from ster.nav.logic import prop_comment

from ._constants import _DETAIL_SELECTOR

_RIGHT_BUTTON = 3  # the mouse button Textual numbers 3


class OntologyTree(Tree):
    """The left-pane tree. In the panel layer (cursor on the header) Tab and the arrows move
    between panels; Enter opens a pane and drops into its items, where the arrows navigate."""

    # The node whose guide column is currently lit (the cursor's parent).
    _branch_parent: TreeNode | None = None

    def watch_cursor_line(self, previous_line: int, line: int) -> None:
        super().watch_cursor_line(previous_line, line)
        self._light_branch_column()
        # Panel layer = cursor resting on the pane header (its main entity): no *item* is
        # selected, so the header's cursor is dimmed (only the pane border reads as active).
        # Deferred: toggling a class mid-cursor-watch invalidates the tree-line cache.
        self.call_after_refresh(self._sync_panel_layer_class)

    def _sync_panel_layer_class(self) -> None:
        # Dim the header only in the panel layer — cursor on the head *and* not entered. Once
        # entered, the head is a selected item and keeps its normal highlight.
        pid = self.id or "tree"
        entered = self.app._entered_pid == pid  # type: ignore[attr-defined]
        layer = self._cursor_on_main(pid) and not entered
        if (
            self.has_class("panel-layer") != layer
        ):  # most moves stay in the same layer: change nothing
            self.set_class(layer, "panel-layer")
            self.app._update_nav_hint()  # type: ignore[attr-defined]  # panel↔item layer changed

    def _light_branch_column(self) -> None:
        """Keep the guide column at the cursor's own level lit as it moves.

        Textual marks the *cursor node* selected, which lights up the guides
        *descending from* it — so the highlight vanishes the moment the cursor
        lands on a leaf. We move that flag onto the cursor's parent instead, so
        the vertical guide it shares with its siblings stays lit at the cursor's
        level. ``_selected`` is a pure rich-render hint (it drives the
        ``tree--guides-selected`` style), independent of node-selection events.
        """
        node = self.cursor_node
        parent = node.parent if node is not None else None
        # The hidden root's guide spans every line — lighting it would highlight
        # the whole tree, so top-level nodes get no branch column.
        if parent is self.root:
            parent = None
        if node is not None:
            node._selected = False  # undo Textual's descend-from-cursor highlight
        if parent is not self._branch_parent and self._branch_parent is not None:
            self._branch_parent._selected = False
            self._refresh_node(self._branch_parent)
        self._branch_parent = parent
        if parent is not None:
            parent._selected = True
            self._refresh_node(parent)

    def render_label(self, node: TreeNode, base_style: Style, style: Style) -> Text:
        """Pad childless (non-expandable) labels by the toggle-arrow width so they
        line up with the expandable siblings that do show a ``▶``/``▼`` arrow.

        Textual omits the arrow for non-expandable nodes (and renders no prefix),
        which would shift their text left out of alignment; the pad restores it.
        """
        label = super().render_label(node, base_style, style)
        if not node.allow_expand:
            label.pad_left(len(self.ICON_NODE))  # ICON_NODE = "▶ " → 2 cells
        return label

    def action_focus_detail(self) -> None:
        # Remember the pane *and* the item we crossed from: Tab in the detail toggles back to
        # this item, Escape pops up to the pane's header (panel layer).
        self.app._detail_source_pid = self.id or "tree"  # type: ignore[attr-defined]
        node = self.cursor_node
        self.app._detail_source_uri = node.data if node is not None else None  # type: ignore[attr-defined]
        rows = [r for r in self.app.query(f"{_DETAIL_SELECTOR} DetailRow") if r.can_focus]
        if rows:
            rows[0].focus()  # first actionable row (info-only rows are skipped)

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:  # noqa: V105
        """Materialize deferred collections and hierarchy children when opened."""
        self.app._load_deferred_individuals(event.node)  # type: ignore[attr-defined]
        self.app._load_deferred_tree_node(event.node)  # type: ignore[attr-defined]

    def _cursor_on_main(self, pid: str) -> bool:
        """True when the cursor sits on this pane's main entity (its overview row) — the
        'pane selected' state, as opposed to being down in the content."""
        overview = self.app._PANEL_OVERVIEW.get(pid)  # type: ignore[attr-defined]
        cur = self.cursor_node
        return overview is not None and cur is not None and cur.data == overview

    # Pane-navigation keys → handler. Each returns True when it consumed the key (so the
    # default tree behaviour is suppressed). Behaviour splits by *layer*:
    #   * panel layer (a pane is selected but not entered — cursor on its dimmed header):
    #       ↑/↓ and Tab/←/→ move between panels · Enter opens this pane (folding the others)
    #       and selects its head as the first item · Space folds/unfolds the pane.
    #   * item layer (the pane is entered — an item, incl. the head, is selected):
    #       ↑/↓ navigate the tree · Tab/←/→ cross to the detail pane · Escape exits to the
    #       panel layer. Space/Enter fall through to the tree.
    _PANE_KEYS: dict[str, Callable[[OntologyTree, str, bool], bool]] = {
        "tab": lambda self, pid, panel: self._pane_cross(pid, panel, True),
        "shift+tab": lambda self, pid, panel: self._pane_cross(pid, panel, False),
        "right": lambda self, pid, panel: self._pane_cross(pid, panel, True),
        "left": lambda self, pid, panel: self._pane_cross(pid, panel, False),
        "down": lambda self, pid, panel: self._pane_arrow(pid, panel, True),
        "up": lambda self, pid, panel: self._pane_arrow(pid, panel, False),
        "space": lambda self, pid, panel: self._pane_space(pid, panel),
        "enter": lambda self, pid, panel: self._pane_enter(pid, panel),
        "escape": lambda self, pid, panel: self._pane_escape(pid, panel),
    }

    def _in_panel_layer(self, pid: str) -> bool:
        """True when this pane is *selected but not entered* — the panel layer. Once entered
        (Enter), even the head reads as a selected item (the item layer)."""
        entered = self.app._entered_pid == pid  # type: ignore[attr-defined]
        return (self._cursor_on_main(pid) or self.has_class("folded")) and not entered

    def on_key(self, event: events.Key) -> None:  # noqa: V105
        pid = self.id or "tree"
        panel = self._in_panel_layer(pid)
        handler = self._PANE_KEYS.get(event.key)
        if handler is not None and handler(self, pid, panel):
            event.prevent_default()
            event.stop()

    def _pane_cross(self, pid: str, panel: bool, forward: bool) -> bool:
        """Tab / Shift-Tab / ← / →. Panel layer: cycle to the next / previous pane. Item
        layer: cross to the detail pane (either direction; a toggle with the detail)."""
        if panel:
            self.app._select_adjacent_panel(pid, 1 if forward else -1)  # type: ignore[attr-defined]
        else:
            self.action_focus_detail()
        return True

    def _pane_arrow(self, pid: str, panel: bool, forward: bool) -> bool:
        """↑/↓. Panel layer: move between panels. Item layer: let the tree navigate its
        items (return False → the default cursor movement runs)."""
        if panel:
            self.app._select_adjacent_panel(pid, 1 if forward else -1)  # type: ignore[attr-defined]
            return True
        return False

    def _pane_space(self, pid: str, panel: bool) -> bool:
        """Panel layer → fold/unfold the pane; item layer → let the tree fold the node."""
        if panel:
            self.app._toggle_full(pid)  # type: ignore[attr-defined]
            return True
        return False

    def _pane_enter(self, pid: str, panel: bool) -> bool:
        """Panel layer → open this pane: fold the others, unfold it to full, and select its
        head as the first item (the item layer). Item layer → fall through to the tree."""
        if panel:
            self.app._enter_panel_full(pid)  # type: ignore[attr-defined]
            return True
        return False

    def _pane_escape(self, pid: str, panel: bool) -> bool:
        """Item layer → exit back to the panel layer (deselect the item; dim the header)."""
        if not panel and self.app._PANEL_OVERVIEW.get(pid) is not None:  # type: ignore[attr-defined]
            self.app._select_panel(pid)  # type: ignore[attr-defined]
            return True
        return False

    def _clicked_line(self, event: events.Click) -> int | None:
        """The tree line a click landed on (from the event style meta, else the hover line)."""
        style = getattr(event, "style", None)
        line = style.meta.get("line") if style is not None else None
        return line if line is not None else self.hover_line

    def on_click(self, event: events.Click) -> None:
        """Separate the pane action from the tree action:

        * Right-click a node → its context menu (never toggles the tree).
        * Left-click the pane's main-entity (header) row → accordion the pane *only*; the base
          ``Tree._on_click`` is prevented so the header's tree node does not also fold/unfold.
        * Any other left-click keeps the default select / expand-collapse behaviour."""
        line = self._clicked_line(event)
        node = self.get_node_at_line(line) if line is not None and line >= 0 else None
        if event.button == _RIGHT_BUTTON:  # right-click → context menu
            self._open_context_menu_at(node, line, event)
        # A click on the pane's own chrome — its border, its border title, or the
        # empty space below the last row — lands on no node at all, so it used to
        # do nothing. That made the titled bar at the top of the box the one part
        # of it that looked clickable and was not. It accordions the pane too.
        elif event.button == 1 and (node is None or self._is_main_node(node)):
            self._accordion_click(line if node is not None else None, event)

    def _is_main_node(self, node: TreeNode | None) -> bool:
        """True when *node* is this pane's main-entity (header/overview) row."""
        overview = self.app._PANEL_OVERVIEW.get(self.id or "")  # type: ignore[attr-defined]
        return node is not None and overview is not None and node.data == overview

    def _open_context_menu_at(self, node: TreeNode | None, line: int | None, event) -> None:  # type: ignore[no-untyped-def]
        event.prevent_default()  # must not reach Tree._on_click (no toggle/select)
        uri = node.data if node else None
        if uri and line is not None:
            self.cursor_line = line
            self.app.open_context_menu(uri, (event.screen_x, event.screen_y))  # type: ignore[attr-defined]

    def _accordion_click(self, line: int | None, event) -> None:  # type: ignore[no-untyped-def]
        event.prevent_default()  # header click accordions the pane, not its tree node
        if line is not None:
            self.cursor_line = line  # select the header (highlight + show overview)
        pid = self.id or "tree"
        self.app._toggle_full(pid)  # type: ignore[attr-defined]
        self.app._show(self.app._PANEL_OVERVIEW[pid])  # type: ignore[attr-defined]

    def watch_hover_line(self, previous_line: int, line: int) -> None:
        """Tooltip while hovering a row: for a lint-flagged (red/orange) node, its issue
        counts; otherwise a property's rdfs:comment."""
        node = self.get_node_at_line(line) if line is not None and line >= 0 else None
        uri = node.data if node is not None else None
        self.tooltip = (self._hover_lint(uri) or self._hover_comment(uri)) if uri else None

    def _hover_lint(self, uri: str) -> str | None:
        """A one-line count of the entity's error/warning lint issues (the red/orange ones),
        e.g. "⊘ 2 errors · ⚠ 1 warning" — click the node to see the full list. None when the
        node has no such issues (or the plugin is off)."""
        from ster.plugins.semanticlint import report

        issues = self.app._lint_issues.get(uri, [])  # type: ignore[attr-defined]
        return report.issue_summary(issues)

    def _hover_comment(self, uri: str) -> str | None:
        """The rdfs:comment of the property at *uri* (else None) — no tooltip for other kinds."""
        prop = self.app.tax.owl_properties.get(uri)  # type: ignore[attr-defined]
        if prop is None or not prop.comments:
            return None
        return prop_comment(prop, self.app.lang)  # type: ignore[attr-defined]
