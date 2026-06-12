"""The Textual ontology browser app.

Left: a `Tree` of Classes (with their individuals nested) / Properties / SKOS
schemes. Right: a progressive-disclosure detail panel. `/` (or ctrl+p) opens a
fuzzy command-palette search that jumps to any class / individual / property.

Browse-only for now — editing will route through ``TaxonomyService`` (the
command/service layer the curses viewer already uses).
"""

from __future__ import annotations

from functools import partial

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.command import Hit, Hits, Provider
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Footer, Header, Static, Tree
from textual.widgets.tree import TreeNode

from ster.model import Taxonomy

from . import data


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
    #detail-pane { width: 1fr; }
    #detail { padding: 1 2; }
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

    def __init__(self, taxonomy: Taxonomy, source: str = "ontology", lang: str = "en") -> None:
        super().__init__()
        self.tax = taxonomy
        self.lang = lang
        self.source = source
        self.search_rows = data.search_rows(taxonomy, lang)
        self._uri_nodes: dict[str, TreeNode] = {}
        self._detail_text = ""  # last-rendered detail markup (handy for tests)

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            yield Tree("ontology", id="tree")
            with VerticalScroll(id="detail-pane"):
                yield Static("[dim]Select a class, individual or property…[/dim]", id="detail")
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
        markup = (
            data.detail_markup(self.tax, uri, self.lang)
            if uri
            else "[dim]Select a class, individual or property…[/dim]"
        )
        self._detail_text = markup
        self.query_one("#detail", Static).update(markup)

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
