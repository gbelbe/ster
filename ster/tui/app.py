"""The Textual ontology browser app.

Left: a `Tree` of Classes (with their individuals nested) / Properties / SKOS
schemes. Right: a progressive-disclosure detail panel. `/` (or ctrl+p) opens a
fuzzy command-palette search that jumps to any class / individual / property.

Browse-only for now — editing will route through ``TaxonomyService`` (the
command/service layer the curses viewer already uses).
"""

from __future__ import annotations

from functools import partial
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.command import Hit, Hits, Provider
from textual.containers import Horizontal
from textual.widgets import Footer, Header, Tree
from textual.widgets.tree import TreeNode

from ster.model import Taxonomy

from . import data, detail, edits
from .choice_modal import ChoiceModal
from .detail_view import PLACEHOLDER, DetailRow, DetailView
from .edit_modal import EditModal
from .picker_modal import PickerModal


class _StorePersistence:
    """Persistence port backed by ster.store (writes the .ttl on commit)."""

    def save(self, taxonomy: Taxonomy, path: Path) -> None:
        from ster import store

        store.save(taxonomy, path)


class EntitySearch(Provider):
    """Fuzzy 'jump to any class / individual / property' command-palette provider."""

    async def startup(self) -> None:
        self._rows = self.app.search_rows  # type: ignore[attr-defined]

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        jump = self.app.jump_to  # type: ignore[attr-defined]
        for label, uri, kind in self._rows:
            score = matcher.match(label)
            if score > 0:
                display = f"{data.ICON.get(kind, '')} {label}"
                yield Hit(
                    score, matcher.highlight(display), partial(jump, uri), text=label, help=kind
                )


class OntologyApp(App):
    """A modern, themeable ontology browser."""

    CSS = """
    Screen { background: $surface; }
    #body { height: 1fr; }
    #tree {
        width: 40%;
        min-width: 30;
        border-right: tall $primary-darken-1;
        padding: 0 1;
        background: $panel;
    }
    #detail { width: 1fr; padding: 1 2; }
    .section-header { margin-top: 1; }
    .detail-row { padding: 0 1; }
    .detail-row:focus { background: $accent 30%; }
    Tree > .tree--guides { color: $primary-darken-2; }
    Tree > .tree--guides-selected { color: $accent; }
    """

    BINDINGS = [
        Binding("slash", "command_palette", "Search"),
        Binding("e", "expand_all", "Expand all"),
        Binding("c", "collapse_all", "Collapse"),
        Binding("d", "toggle_dark", "Theme"),
        Binding("q", "quit", "Quit"),
    ]
    COMMANDS = App.COMMANDS | {EntitySearch}

    def __init__(
        self,
        taxonomy: Taxonomy,
        source: str = "ontology",
        lang: str = "en",
        path: Path | None = None,
    ) -> None:
        super().__init__()
        self.tax = taxonomy
        self.lang = lang
        self.source = source
        self._path = path
        self._service = self._make_service(taxonomy, path)
        self.search_rows = data.search_rows(taxonomy, lang)
        self._uri_nodes: dict[str, TreeNode] = {}
        self._detail_text = ""  # last-rendered detail markup (handy for tests)
        self._detail_uri: str | None = None  # entity currently shown in the detail pane

    def _make_service(self, taxonomy: Taxonomy, path: Path | None):  # type: ignore[no-untyped-def]
        """Build the TaxonomyService when editing a real file (None = read-only)."""
        if path is None:
            return None
        from ster.core.service import TaxonomyService
        from ster.core.validation import SkosValidatorAdapter
        from ster.workspace import TaxonomyWorkspace

        self._workspace = TaxonomyWorkspace.from_taxonomy(taxonomy, path)
        return TaxonomyService(self._workspace, _StorePersistence(), SkosValidatorAdapter())

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            yield Tree("ontology", id="tree")
            yield DetailView(id="detail")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "ster · ontology browser"
        self.sub_title = self.source
        tree = self.query_one("#tree", Tree)
        tree.show_root = False
        tree.guide_depth = 3
        self._build(tree)
        tree.focus()

    # ── tree building ─────────────────────────────────────────────────────────

    def _index(self, uri: str, node: TreeNode) -> None:
        self._uri_nodes.setdefault(uri, node)

    def _leaf(self, parent: TreeNode, uri: str, kind: str, suffix: str = "") -> TreeNode:
        text = f"{data.ICON.get(kind, '')} {data.label_of(self.tax, uri, self.lang)}{suffix}"
        node = parent.add_leaf(text, data=uri)
        self._index(uri, node)
        return node

    def _add_class(self, parent: TreeNode, uri: str) -> None:
        node = parent.add(
            f"{data.ICON['class']} {data.label_of(self.tax, uri, self.lang)}", data=uri
        )
        self._index(uri, node)
        for sub in data.subclasses(self.tax, uri, self.lang):
            self._add_class(node, sub)
        for ind in data.individuals_of(self.tax, uri, self.lang):
            self._leaf(node, ind, "individual")

    def _add_concept(self, parent: TreeNode, uri: str) -> None:
        node = parent.add(
            f"{data.ICON['concept']} {data.label_of(self.tax, uri, self.lang)}", data=uri
        )
        self._index(uri, node)
        for child in data.concept_children(self.tax, uri, self.lang):
            self._add_concept(node, child)

    def _build(self, tree: Tree) -> None:
        tax, root = self.tax, tree.root

        if tax.owl_classes:
            sec = root.add(f"{data.ICON['section']} Classes", data=None)
            for uri in data.class_roots(tax, self.lang):
                self._add_class(sec, uri)
            sec.expand()

        loose = data.untyped_individuals(tax, self.lang)
        if loose:
            sec = root.add(f"{data.ICON['section']} Individuals", data=None)
            for uri in loose:
                self._leaf(sec, uri, "individual")

        if tax.owl_properties:
            sec = root.add(f"{data.ICON['section']} Properties", data=None)
            for uri in data.properties(tax, self.lang):
                ptype = tax.owl_properties[uri].prop_type
                tag = f"  [dim]({ptype[:3]})[/dim]" if ptype else ""
                self._leaf(sec, uri, "property", suffix=tag)
            sec.expand()

        for s_uri in data.scheme_roots(tax, self.lang):
            sec = root.add(
                f"{data.ICON['scheme']} {data.label_of(tax, s_uri, self.lang)}", data=s_uri
            )
            self._index(s_uri, sec)
            for c_uri in data.concept_children(tax, s_uri, self.lang):
                self._add_concept(sec, c_uri)
            sec.expand()

    # ── interaction ─────────────────────────────────────────────────────────--

    def _show(self, uri: str | None) -> None:
        # _detail_text mirrors the rendered markup (used by tests + as a quick
        # text view); the DetailView builds the composed, focusable widgets.
        self._detail_uri = uri
        self._detail_text = detail.render_detail(self.tax, uri, self.lang) if uri else PLACEHOLDER
        self.query_one("#detail", DetailView).update_entity(self.tax, uri, self.lang)

    # ── mutation pipeline ───────────────────────────────────────────────────────

    def _rebuild_tree(self) -> None:
        tree = self.query_one("#tree", Tree)
        self._uri_nodes = {}
        tree.root.remove_children()
        self._build(tree)

    def _apply_command(self, command: object) -> None:
        """Execute *command* via TaxonomyService, then refresh tax + tree + detail."""
        if self._service is None or self._path is None:
            self.notify("Read-only session (no file loaded).", severity="warning")
            return
        result = self._service.execute(command)  # type: ignore[arg-type]
        if not result.ok:
            self.notify(result.error or "Command failed.", severity="error")
            return
        # The service swapped a fresh authority taxonomy into the workspace.
        self.tax = self._workspace.taxonomies[self._path]
        self.search_rows = data.search_rows(self.tax, self.lang)
        self._rebuild_tree()
        self._show(self._detail_uri)

    def on_detail_row_edit_requested(self, message: DetailRow.EditRequested) -> None:
        """A focusable detail row asked to be edited → open the modal → command."""
        field = message.field
        uri, path = self._detail_uri, self._path
        if self._service is None or uri is None or path is None:
            self.notify("Read-only session (no file loaded).", severity="warning")
            return

        def _on_submit(value: str | None) -> None:
            if value is None:
                return
            command = edits.edit_command(field, uri, path, value)
            if command is None:
                self.notify("This field isn't editable yet.", severity="warning")
                return
            self._apply_command(command)

        self.push_screen(EditModal(field.display, field.value), _on_submit)

    def on_detail_row_action_requested(self, message: DetailRow.ActionRequested) -> None:
        """An action row was activated → collect input (if needed) → run its command."""
        action = message.field.meta.get("action", "")
        uri, path = self._detail_uri, self._path
        if self._service is None or uri is None or path is None:
            self.notify("Read-only session (no file loaded).", severity="warning")
            return
        direct = edits.direct_command(message.field, uri, path)
        if direct is not None:  # meta-driven removal — run immediately
            self._apply_command(direct)
            return
        if action in edits.DELETE_CHOICES:
            self._confirm_delete(action, uri, path)
            return
        if action in edits.PICKER_ACTIONS:
            self._pick_relation(action, uri, path)
            return
        if action not in edits.INPUT_ACTIONS:
            self.notify("This action isn't wired up yet.", severity="warning")
            return
        prompt, prefill_kind = edits.INPUT_ACTIONS[action]
        prefill = self.tax.base_uri() if prefill_kind == "base_uri" else ""

        def _on_submit(value: str | None) -> None:
            if not value:
                return
            command = edits.action_command(action, uri, path, value, self.lang)
            if command is None:
                self.notify("Unsupported action.", severity="warning")
                return
            self._apply_command(command)

        self.push_screen(EditModal(prompt, prefill), _on_submit)

    def _confirm_delete(self, action: str, uri: str, path: Path) -> None:
        """Ask for the delete mode, then run the destructive command + navigate away."""
        label = data.label_of(self.tax, uri, self.lang)
        prompt = f"Delete «{label}»?"

        def _on_choice(mode: str | None) -> None:
            if mode is None:
                return
            command = edits.delete_command(action, uri, path, mode)
            if command is None:
                self.notify("Unsupported delete.", severity="warning")
                return
            self._apply_command(command)
            self._show(None)  # the entity is gone — clear the detail pane

        self.push_screen(ChoiceModal(prompt, edits.DELETE_CHOICES[action]), _on_choice)

    def _pick_relation(self, action: str, uri: str, path: Path) -> None:
        """Pick a target class for a relation action (e.g. add superclass) → command."""
        candidates = sorted(
            (
                (data.label_of(self.tax, u, self.lang), u)
                for u in self.tax.owl_classes
                if u != uri
            ),
            key=lambda t: t[0].lower(),
        )
        if not candidates:
            self.notify("No other classes to link to.", severity="warning")
            return

        def _on_pick(target: str | None) -> None:
            if target is None:
                return
            command = edits.relation_command(action, uri, path, target)
            if command is None:
                self.notify("Unsupported relation.", severity="warning")
                return
            self._apply_command(command)

        self.push_screen(PickerModal(edits.PICKER_ACTIONS[action], candidates), _on_pick)

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        self._show(event.node.data)

    def jump_to(self, uri: str) -> None:
        """Expand ancestors, move the cursor to *uri*, and show its detail."""
        tree = self.query_one("#tree", Tree)
        node = self._uri_nodes.get(uri)
        if node is None:
            self.notify(f"Not in tree: {uri}", severity="warning")
            return
        parent = node.parent
        while parent is not None:
            parent.expand()
            parent = parent.parent
        self._show(uri)  # detail is independent of tree layout — show it now
        # expand() only takes effect on the next refresh, so move the cursor after it:
        self.call_after_refresh(self._focus_tree_node, tree, node)

    def _focus_tree_node(self, tree: Tree, node: TreeNode) -> None:
        tree.move_cursor(node)
        tree.scroll_to_node(node)
        tree.focus()

    def action_expand_all(self) -> None:
        self.query_one("#tree", Tree).root.expand_all()

    def action_collapse_all(self) -> None:
        tree = self.query_one("#tree", Tree)
        for child in tree.root.children:
            child.collapse_all()
