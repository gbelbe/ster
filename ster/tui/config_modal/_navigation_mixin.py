"""``ConfigModal`` mixin: cross-tab keyboard navigation — the tab bar, the
collapsible group headers on the Annotation properties tab, and initial focus."""

from __future__ import annotations

from textual.widgets import Collapsible, TabbedContent, TabPane, Tabs
from textual.widgets._collapsible import CollapsibleTitle

from ._metadata_catalog import _MetaCatalog
from ._state import _ModalState


class _NavigationMixin(_ModalState):
    """Tab-bar and collapsible-header keyboard navigation, plus initial focus."""

    def _tab_ids(self) -> list[str]:
        """The ids of the currently-mounted tabs, in order (plugin tabs are dynamic)."""
        return [pane.id for pane in self.query(TabPane) if pane.id]

    def on_mount(self) -> None:
        self.query_one("#cfg-box").border_title = "Configuration"
        self.query_one("#cfg-server").border_title = "Local server (ster serve)"
        self.query_one("#cfg-langs").border_title = "Configured languages"
        # Land on the tab bar: space switches tabs, then Tab/arrows enter the items.
        self.query_one(Tabs).focus()
        self._ready = True

    def on_key(self, event) -> None:  # type: ignore[no-untyped-def]
        """Tab bar: space cycles tabs, down enters the active tab. Collapsible
        headers: Up/Down move between groups, Right drills into the item list. Text
        inputs / checkboxes / the catalog groups consume these keys themselves, so
        this only fires while focus is on the tab bar or a group header."""
        focused = self.focused
        if isinstance(focused, Tabs):
            self._tabbar_key(event)
        elif isinstance(focused, CollapsibleTitle):
            self._header_key(event, focused)

    def _tabbar_key(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.key == "space":
            tabs = self.query_one(TabbedContent)
            order = self._tab_ids()
            if tabs.active in order:
                tabs.active = order[(order.index(tabs.active) + 1) % len(order)]
                event.stop()
        elif event.key == "down":
            self.focus_next()  # tab bar → first item of the active tab
            event.stop()

    def _header_key(self, event, title: CollapsibleTitle) -> None:  # type: ignore[no-untyped-def]
        titles = list(self.query(CollapsibleTitle))
        i = titles.index(title)
        if event.key == "down":
            if i + 1 < len(titles):
                titles[i + 1].focus()  # → next group header
            event.stop()
        elif event.key == "up":
            (titles[i - 1] if i > 0 else self.query_one(Tabs)).focus()  # ← prev group / tab bar
            event.stop()
        elif event.key == "right":
            self._enter_group(title)  # → drill into this group's item list
            event.stop()

    def _enter_group(self, title: CollapsibleTitle) -> None:
        """Open (if folded) and focus the catalog under *title*, landing on its first item."""
        node: object = title.parent
        while node is not None and not isinstance(node, Collapsible):
            node = node.parent  # type: ignore[attr-defined]
        if not isinstance(node, Collapsible):
            return
        catalog = node.query_one(_MetaCatalog)
        if node.collapsed:
            node.collapsed = False
            self.call_after_refresh(self._focus_catalog, catalog)
        else:
            self._focus_catalog(catalog)

    @staticmethod
    def _focus_catalog(catalog: _MetaCatalog) -> None:
        catalog.focus()
        catalog._enter()
