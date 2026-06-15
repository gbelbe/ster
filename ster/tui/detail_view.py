"""Composed detail view for the Textual TUI.

The detail pane is built from real widgets — one per section header and one
*focusable* row per ``DetailField`` — rather than a single Rich-markup blob.
This is the foundation of the generic "block" model: focusable rows let later
phases attach inline edit / action behaviour per row, and specialised block
widgets can replace ``DetailRow`` without touching the entities that compose them.

See docs/architecture/textual-tui-refactor.md.
"""

from __future__ import annotations

from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Static

from ster.model import Taxonomy
from ster.nav.logic import DetailField

from .detail import build_sections, field_markup

PLACEHOLDER = "[dim]Select a class, individual or property…[/dim]"


class SectionHeader(Static):
    """A non-focusable section title (e.g. 'Identity', 'Danger Zone')."""

    def __init__(self, title: str, *, danger: bool = False) -> None:
        style = "bold red" if danger else "bold"
        super().__init__(f"[{style}]{title}[/]")
        self.title_text = title  # plain title, for queries/tests
        self.add_class("section-header")


class DetailRow(Static):
    """A focusable detail field row; carries its ``DetailField`` for later actions.

    Arrow keys move between rows (``up``/``down``) and back to the tree (``left``),
    so the whole UI is navigable without reaching for Tab.
    """

    can_focus = True
    BINDINGS = [
        Binding("enter", "activate", "Edit / run"),
        Binding("down", "focus_row(1)", "Next", show=False),
        Binding("up", "focus_row(-1)", "Prev", show=False),
        Binding("left", "focus_tree", "Tree", show=False),
    ]

    def action_focus_row(self, delta: int) -> None:
        """Move focus to the previous/next sibling row, wrapping around the ends."""
        rows = list(self.app.query("#detail DetailRow"))
        if rows:  # wrap: up from the first row → last, down from the last → first
            rows[(rows.index(self) + delta) % len(rows)].focus()

    def action_focus_tree(self) -> None:
        """Jump focus back to the tree (the left pane)."""
        trees = list(self.app.query("#tree"))
        if trees:
            trees[0].focus()

    class EditRequested(Message):
        """Posted when the user activates an editable value row (Enter)."""

        def __init__(self, field: DetailField) -> None:
            super().__init__()
            self.field = field

    class ActionRequested(Message):
        """Posted when the user activates an action row (Enter)."""

        def __init__(self, field: DetailField) -> None:
            super().__init__()
            self.field = field

    def __init__(self, field: DetailField) -> None:
        super().__init__(field_markup(field))
        self.field = field
        self.add_class("detail-row")

    def action_activate(self) -> None:
        if self.field.editable:
            self.post_message(self.EditRequested(self.field))
        elif self.field.meta.get("action"):
            self.post_message(self.ActionRequested(self.field))


class DetailView(VerticalScroll):
    """Compose an entity's detail into section headers + focusable field rows."""

    def compose(self):  # type: ignore[no-untyped-def]
        yield Static(PLACEHOLDER)

    def update_entity(self, tax: Taxonomy, uri: str | None, lang: str = "en") -> None:
        """Rebuild the pane to show *uri* (or a placeholder when None)."""
        self.remove_children()
        if uri is None:
            self.mount(Static(PLACEHOLDER))
            return
        widgets: list[Static] = []
        for sec in build_sections(tax, uri, lang):
            if sec.title:
                widgets.append(SectionHeader(sec.title, danger=sec.danger))
            widgets.extend(DetailRow(f) for f in sec.fields)
        self.mount(*widgets) if widgets else self.mount(Static(PLACEHOLDER))
