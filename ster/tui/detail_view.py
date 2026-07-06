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
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from ster.model import Taxonomy
from ster.nav.logic import DetailField

from .detail import DetailSection, build_sections, field_markup, group_sections

PLACEHOLDER = "[dim]Select a class, individual or property…[/dim]"


def _insert_issue_sections(
    sections: list[DetailSection], issue_fields: list | None
) -> list[DetailSection]:
    """Splice the plugin's quality sections (the 'Issues' summary + 'Quality issues'
    list) in just after the class's 'Property Fill' section — inside the Quality &
    Coverage box — when one is present; otherwise just after Identity (the first
    section), or at the top when there is none. No-op when there are no issue fields."""
    if not issue_fields:
        return sections
    issue_sections = group_sections(issue_fields)
    if not sections:
        return issue_sections
    # Prefer landing under "Property Fill" (inside the box); else fall back to Identity.
    anchor = next((i for i, s in enumerate(sections) if s.title == "Property Fill"), 0)
    return [*sections[: anchor + 1], *issue_sections, *sections[anchor + 1 :]]


# Hover help for action rows (mouse + keyboard discoverability). Anything not
# listed falls back to a generic hint; editable rows say "Enter to edit".
_ACTION_HELP = {
    "new_subclass": "Create a child class under this one",
    "add_individual": "Create an instance (individual) of this class",
    "link_superclass": "Add another parent class (polyhierarchy)",
    "remove_superclass": "Detach this parent class",
    "add_class_property": "Define a new property with this class as its domain",
    "class_to_individual": "Convert this class into an individual (punning)",
    "delete_class": "Delete this class — you'll choose what happens to its subclasses & instances",
    "add_ind_type": "Add a class membership (rdf:type) to this individual",
    "remove_ind_type": "Remove this class membership",
    "add_prop_value": "Add a property value — pick a property, then a value",
    "edit_prop_value": "Change this value to another individual",
    "remove_prop_value": "Remove this value",
    "edit_literal_value": "Edit this literal value",
    "remove_literal_value": "Remove this literal value",
    "individual_to_class": "Convert this individual into a class (punning)",
    "delete_individual": "Delete this individual",
    "add_prop_domain": "Add a class to this property's domain",
    "add_prop_range": "Add a class to this property's range",
    "remove_prop_domain": "Remove this domain class",
    "remove_prop_range": "Remove this range class",
    "delete_property": "Delete this property",
    "add_narrower": "Add a child (narrower) concept",
    "link_broader": "Link to a broader concept",
    "add_related": "Add a related concept",
    "move": "Move this concept under a different parent",
    "delete": "Delete this concept — you'll choose whether to keep its descendants",
    "add_top_concept": "Add a top concept to this scheme",
    "add_scheme": "Create a new SKOS concept scheme",
    "create_owl_class": "Create a new top-level OWL class",
    "edit_class": "Edit this class — URI, labels and comments in one modal",
    "create_owl_property": "Create a new OWL property",
    "edit_ontology_prefix": "Edit the ontology's namespace prefix",
    "edit_ontology_uri": "Rename the ontology base URI (cascades to every entity)",
    "edit_ontology_domain": "Change the ontology domain/host (cascades to every entity)",
    "edit_note": "Edit the markdown note",
    "delete_note": "Clear the note",
    "view_lint": "List these issues — Enter to open",
}


def _row_tooltip(field: DetailField) -> str | None:
    """Hover help for a row: edit hint, a per-action description, or a run hint."""
    if field.editable:
        return "Enter to edit"
    action = field.meta.get("action")
    if not action:
        return None
    return _ACTION_HELP.get(action, "Enter to run")


def _is_actionable(field: DetailField, delete_field: DetailField | None) -> bool:
    """True when a row does something on activation — so it takes keyboard /
    click focus. Pure information rows (stats, plain facts) are skipped by the
    arrows, Tab and clicks; only editable rows, action rows, and rows with an
    Edit/Delete submenu participate in navigation."""
    return bool(field.editable or field.meta.get("action") or delete_field is not None)


# Action rows (＋ add, ⊘ delete, ✎ rename, …) already render with their own
# leading glyph; these meta-types are left as-is.
_GLYPH_ACTION_TYPES = frozenset({"action", "action_add", "action_del"})


def _row_content(field: DetailField, actionable: bool) -> str:
    """The row's markup, prefixed with a small affordance icon when it is
    clickable but doesn't already carry an action glyph — so every clickable row
    is visibly interactive. Editable values get ``✎``; other clickable rows ``▸``.
    """
    markup = field_markup(field)
    if actionable and field.meta.get("type") not in _GLYPH_ACTION_TYPES:
        icon = "✎" if field.editable else "▸"
        return f"{icon} {markup}"
    return markup


def _rows_for(fields: list[DetailField]) -> list[DetailRow]:
    """Build a section's rows, folding each editable value's following "✕ remove"
    sibling into that row's Edit/Delete submenu (so it isn't a separate row)."""
    rows: list[DetailRow] = []
    i = 0
    while i < len(fields):
        f = fields[i]
        nxt = fields[i + 1] if i + 1 < len(fields) else None
        if f.editable and nxt is not None and nxt.meta.get("type") == "action_del":
            rows.append(DetailRow(f, delete_field=nxt))
            i += 2
        else:
            rows.append(DetailRow(f))
            i += 1
    return rows


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
        """Move focus to the previous/next *actionable* sibling row, wrapping.

        Information-only rows are non-focusable, so they're skipped here too."""
        rows = [r for r in self.app.query("#detail DetailRow") if r.can_focus]
        if rows and self in rows:  # wrap: up from the first → last, down from the last → first
            rows[(rows.index(self) + delta) % len(rows)].focus()

    def action_focus_tree(self) -> None:
        """Jump focus back to the tree (the left pane)."""
        trees = list(self.app.query("#tree"))
        if trees:
            trees[0].focus()

    class EditRequested(Message):
        """Posted when the user activates an edit-only value row (Enter)."""

        def __init__(self, field: DetailField) -> None:
            super().__init__()
            self.field = field

    class ActionRequested(Message):
        """Posted when the user activates an action row (Enter)."""

        def __init__(self, field: DetailField) -> None:
            super().__init__()
            self.field = field

    class MenuRequested(Message):
        """Posted when a value row that can be both edited and deleted is activated.

        The app shows an Edit / Delete submenu anchored at the row.
        """

        def __init__(
            self, field: DetailField, delete_field: DetailField, anchor: tuple[int, int]
        ) -> None:
            super().__init__()
            self.field = field
            self.delete_field = delete_field
            self.anchor = anchor

    def __init__(self, field: DetailField, delete_field: DetailField | None = None) -> None:
        # Only actionable rows take focus; info rows are skipped by arrows/Tab/click.
        actionable = _is_actionable(field, delete_field)
        super().__init__(_row_content(field, actionable))
        self.field = field
        self.delete_field = delete_field  # the paired "✕ remove" row, if any
        self.add_class("detail-row")
        self.can_focus = actionable
        if not actionable:
            self.add_class("info-row")
        color = field.meta.get("color")  # quality colour: red / orange / green
        if color in ("red", "orange", "green"):
            self.add_class(f"q-{color}")
        tip = _row_tooltip(field)
        if tip:
            self.tooltip = tip

    def _anchor(self) -> tuple[int, int]:
        return (self.region.x, self.region.y)

    def action_activate(self) -> None:
        if self.field.editable and self.delete_field is not None:
            self.post_message(self.MenuRequested(self.field, self.delete_field, self._anchor()))
        elif self.field.editable:
            self.post_message(self.EditRequested(self.field))
        elif self.field.meta.get("action"):
            self.post_message(self.ActionRequested(self.field))

    def on_click(self) -> None:
        self.action_activate()


def _section_widgets(sec: DetailSection) -> list[Widget]:
    """A section's header (if titled) followed by its focusable rows."""
    out: list[Widget] = []
    if sec.title:
        out.append(SectionHeader(sec.title, danger=sec.danger))
    out.extend(_rows_for(sec.fields))
    return out


def _collect_group_members(sections: list[DetailSection], start: int) -> tuple[list[Widget], int]:
    """Widgets for the sections from *start* up to (not incl.) the group-end marker;
    returns ``(widgets, index_after_the_end_marker)``."""
    members: list[Widget] = []
    i = start
    while i < len(sections) and not sections[i].group_end:
        members.extend(_section_widgets(sections[i]))
        i += 1
    return members, i + 1  # skip the group-end sentinel


def _grouped_widgets(sections: list[DetailSection]) -> list[Widget]:
    """Flatten sections to widgets, wrapping each group span in a bordered, titled box."""
    widgets: list[Widget] = []
    i = 0
    while i < len(sections):
        sec = sections[i]
        if sec.group:
            members, i = _collect_group_members(sections, i + 1)
            box = Vertical(*members, classes="detail-group")
            box.border_title = sec.title
            widgets.append(box)
        else:
            widgets.extend(_section_widgets(sec))
            i += 1
    return widgets


def _graph_action_row(tax: Taxonomy, uri: str) -> DetailRow | None:
    """A highlighted, focusable '» Open Graph View' row leading the detail pane for the
    entities a focused graph supports (OWL classes & individuals); None otherwise."""
    from .data import kind_of

    if kind_of(tax, uri) not in ("class", "individual"):
        return None
    field = DetailField(
        "action:open_graph_view",
        "» Open Graph View",
        "",
        editable=False,
        meta={"type": "action", "action": "view_focused_graph", "uri": uri},
    )
    row = DetailRow(field)
    row.add_class("graph-action")  # accent-highlighted, per the header affordance
    return row


class DetailView(VerticalScroll):
    """Compose an entity's detail into section headers + focusable field rows."""

    can_focus = True  # so clicking the (empty) pane can still select it

    def compose(self):  # type: ignore[no-untyped-def]
        yield Static(PLACEHOLDER)

    def on_click(self) -> None:
        """Click blank pane space to select this window: focus a row, else the pane."""
        rows = [r for r in self.query(DetailRow) if r.can_focus]
        if not rows:
            self.focus()  # nothing actionable (placeholder / info-only) — select the pane
        elif not isinstance(self.app.focused, DetailRow):
            rows[0].focus()  # a row click self-focuses; blank space → first actionable row

    def update_entity(
        self,
        tax: Taxonomy,
        uri: str | None,
        lang: str = "en",
        activity: dict | None = None,
        lint: dict | None = None,
        configured_langs: list[str] | None = None,
        metadata: dict | None = None,
        issue_fields: list | None = None,
        quality_block: bool = True,
    ) -> None:
        """Rebuild the pane to show *uri* (or a placeholder when None). *issue_fields*
        (the semanticlint plugin's per-entity 'Quality issues' rows) are inserted right
        after the Identity section when present."""
        self.remove_children()
        if uri is None:
            self.mount(Static(PLACEHOLDER))
            return
        sections = build_sections(
            tax, uri, lang, activity, lint, configured_langs, metadata, quality_block
        )
        sections = _insert_issue_sections(sections, issue_fields)
        widgets = _grouped_widgets(sections)
        graph_row = _graph_action_row(tax, uri)  # leads the pane for classes/individuals
        if graph_row is not None:
            widgets = [graph_row, *widgets]
        self.mount(*widgets) if widgets else self.mount(Static(PLACEHOLDER))
