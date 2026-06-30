"""The Textual ontology browser & editor app.

Left: a `Tree` of Classes (with their individuals nested) / Properties / SKOS
schemes. Right: a progressive-disclosure detail panel. `/` (or ctrl+p) opens a
fuzzy command-palette search that jumps to any class / individual / property.

Editing routes through ``TaxonomyService`` (the command/service layer the curses
viewer also uses): activate a detail row (Enter) to edit a value or run an
action; every mutation is validated and written back to the file.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path

from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.command import Hit, Hits, Provider
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Footer, Header, Tree
from textual.widgets.tree import TreeNode

from ster.model import Taxonomy
from ster.nav.logic import DetailField

from . import data, detail, edits, uri_edit
from .choice_modal import ChoiceModal
from .context_menu import ContextMenu
from .detail_view import PLACEHOLDER, DetailRow, DetailView
from .edit_modal import EditModal
from .help_screen import HelpScreen
from .ontology_identity_modal import OntologyIdentityModal
from .picker_modal import PickerModal
from .theme import STER_THEME, THEME_CYCLE
from .uri_modal import UriModal

# Sentinel URI prefix for tree action nodes (create class/scheme/concept).
# Format:  "__action:<action>[:<extra>]__"
# The <extra> field carries context (e.g. the scheme URI for add_top_concept).
_ACTION_PREFIX = "__action:"
_ACTION_SUFFIX = "__"


def _action_uri(action: str, extra: str = "") -> str:
    return f"{_ACTION_PREFIX}{action}:{extra}{_ACTION_SUFFIX}"


def _parse_action_uri(uri: str) -> tuple[str, str] | None:
    """Return (action, extra) if *uri* is an action sentinel, else None."""
    if uri.startswith(_ACTION_PREFIX) and uri.endswith(_ACTION_SUFFIX):
        inner = uri[len(_ACTION_PREFIX) : -len(_ACTION_SUFFIX)]
        action, _, extra = inner.partition(":")
        return action, extra
    return None


class OntologyTree(Tree):
    """The left-pane tree. `right` jumps into the detail pane; up/down wrap around."""

    _LAST_LINE = 2_000_000_000  # any out-of-range line clamps to the last visible one

    BINDINGS = [Binding("right", "focus_detail", "Detail", show=False)]

    # The node whose guide column is currently lit (the cursor's parent).
    _branch_parent: TreeNode | None = None

    def watch_cursor_line(self, previous_line: int, line: int) -> None:
        super().watch_cursor_line(previous_line, line)
        self._light_branch_column()

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
        rows = [r for r in self.app.query("#detail DetailRow") if r.can_focus]
        if rows:
            rows[0].focus()  # first actionable row (info-only rows are skipped)

    def action_cursor_down(self) -> None:
        before = self.cursor_line
        super().action_cursor_down()
        if self.cursor_line == before:  # already at the bottom → wrap to the top
            self.cursor_line = 0

    def action_cursor_up(self) -> None:
        before = self.cursor_line
        super().action_cursor_up()
        if self.cursor_line == before:  # already at the top → wrap to the bottom
            self.cursor_line = self._LAST_LINE  # clamped to the last visible line

    def on_click(self, event: events.Click) -> None:
        """Right-click a node → open its context menu (left-click is Tree's default)."""
        if event.button != 3:  # 3 = right button
            return
        style = getattr(event, "style", None)
        line = style.meta.get("line") if style is not None else None  # the clicked tree line
        if line is None:
            line = self.hover_line
        node = self.get_node_at_line(line) if line is not None and line >= 0 else None
        uri = node.data if node else None
        if uri:
            self.cursor_line = line  # select the right-clicked node visually
            self.app.open_context_menu(uri, (event.screen_x, event.screen_y))  # type: ignore[attr-defined]


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
    /* Muted UI colours use a dim $foreground tint, NOT $panel: some themes
       (e.g. solarized-light) make $panel ≈ the surface, which hides borders,
       guides and titles. A foreground alpha is visible against any background. */
    * {
        scrollbar-background: $surface;
        scrollbar-color: $foreground 30%;
        scrollbar-color-hover: $primary;
        scrollbar-color-active: $secondary;
    }
    /* No `background` here: an app-level `Screen` rule overrides each modal's
       translucent dim and makes it opaque (hiding the TUI). Modals own their
       background via ModalBase; the panes below cover the main screen anyway. */
    Screen { layers: base overlay; }
    /* Left-align the header title (default is centred). */
    HeaderTitle { content-align: left middle; padding-left: 1; }
    #body { height: 1fr; }
    #nav { width: 25%; min-width: 24; }

    /* Each pane is a rounded, titled box whose border lights up when focused —
       so you always see which pane you're in and what it holds. */
    #tree, #prop-tree, #detail {
        border: round $foreground 40%;
        border-title-color: $foreground 70%;
        background: $surface;
        color: $foreground;
    }
    #tree { height: 1fr; padding: 0 1; }
    /* Properties keep their own pane (1/4 height) so they stay visible even when
       the class hierarchy is fully expanded. */
    #prop-tree { height: 25%; padding: 0 1; }
    #detail { width: 1fr; padding: 1 2; }
    #tree:focus-within, #prop-tree:focus-within, #detail:focus-within {
        border: round $primary;
        border-title-color: $primary;
    }

    .section-header { margin-top: 1; }
    .detail-row { padding: 0 1; }
    .detail-row:focus { background: $primary 20%; }
    /* $boost is a translucent overlay → invisible on light themes; use a solid
       accent tint so the mouse-over highlight shows in every theme. */
    .detail-row:hover { background: $secondary 20%; }
    /* Information-only rows are not interactive — no hover affordance. */
    .detail-row.info-row:hover { background: transparent; }
    /* Quality colours — one definition for every %-indicator + errors/warnings.
       Change a colour here and every indicator updates at once. */
    .detail-row.q-red    { color: #d70000; }
    .detail-row.q-orange { color: #d75f00; }
    .detail-row.q-green  { color: #00875f; }

    /* Hierarchy guide lines: a dim foreground tint so the tree structure stays
       visible in every theme (selected/hover branches pick up the accents). */
    Tree > .tree--guides { color: $foreground 45%; }
    Tree > .tree--guides-selected { color: $secondary; }
    Tree > .tree--guides-hover { color: $primary; }
    /* Selected node stays readable even when the tree loses focus: a tint of
       $secondary with the theme's normal text colour (not `auto`, which could
       resolve to white on a light accent). Focused = full-strength accent. */
    Tree > .tree--cursor { text-style: bold; background: $secondary 40%; color: $foreground; }
    Tree:focus > .tree--cursor { background: $secondary; color: auto; }

    /* Give the footer a neutral surface background (not the theme's $primary,
       which is blue on solarized-light → invisible key hints) with readable text. */
    Footer { background: $surface; color: $foreground; }
    FooterKey { background: $surface; color: $foreground; }
    FooterKey:hover { background: $boost; }
    /* Footer key hints read as actionable (and are clickable). */
    FooterKey > .footer-key--key { color: $secondary; text-style: bold; }
    FooterKey > .footer-key--description { color: $foreground; }

    /* Notifications: a left accent bar, colour-coded by severity. */
    Toast { border-left: wide $primary; }
    Toast.-warning { border-left: wide $secondary; }
    Toast.-error { border-left: wide $error; }

    /* Hover tooltips: a clear bordered popover. $background contrasts with the
       $surface panes it floats over, and the $primary border delimits it. */
    Tooltip {
        background: $background;
        color: $foreground;
        border: round $primary;
        padding: 0 1;
        max-width: 60%;
    }
    """

    BINDINGS = [
        Binding("slash", "command_palette", "Search"),
        Binding("full_stop", "context_menu", "Actions"),
        Binding("e", "expand_all", "Expand all"),
        Binding("c", "collapse_all", "Collapse"),
        Binding("d", "cycle_theme", "Theme"),
        Binding("comma", "open_config", "Config"),
        Binding("question_mark", "help", "Help"),
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
        self.register_theme(STER_THEME)  # available alongside every built-in theme
        from ster.nav.prefs import _load_prefs

        self.theme = _load_prefs().get("theme") or "solarized-light"  # saved pref, else default
        self.tax = taxonomy
        if path is not None:
            from ster.nav.prefs import _load_lang_pref

            lang = _load_lang_pref(path) or lang  # restore the saved display language
        self.lang = lang
        self.source = source
        self._path = path
        self.configured_langs = self._load_configured_langs(path, lang)
        self.metadata_props = self._load_metadata_props()  # ontology-metadata catalog
        self.entity_metadata_props = self._load_entity_metadata_props()  # entity-metadata catalog
        self._service = self._make_service(taxonomy, path)
        self.search_rows = data.search_rows(taxonomy, lang)
        self._uri_nodes: dict[str, TreeNode] = {}
        self._detail_text = ""  # last-rendered detail markup (handy for tests)
        self._detail_uri: str | None = None  # entity currently shown in the detail pane
        self._activity_cache: dict | None = None  # lazily-computed git activity (per session)
        self._activity_computed = False
        # Lazily-computed semanticlint result (per session): (counts, issues).
        self._lint_cache: tuple[dict, list] | None = None
        self._lint_computed = False
        # The value row whose Edit/Delete submenu is open (set while it is shown).
        self._row_menu_field: DetailField | None = None
        self._row_menu_delete: DetailField | None = None
        self._row_menu_origin: Widget | None = None  # row to refocus after the submenu

    def _load_metadata_props(self) -> list[tuple[str, str]]:
        """The configured ontology-metadata predicate catalog (built-in defaults
        when the user has never customised it)."""
        from ster.nav.logic import default_annotation_catalog
        from ster.nav.prefs import load_metadata_props

        return load_metadata_props() or default_annotation_catalog()

    def _load_entity_metadata_props(self) -> list[tuple[str, str]]:
        """The configured entity-metadata predicate catalog (built-in defaults when
        the user has never customised it)."""
        from ster.nav.logic import default_entity_annotation_catalog
        from ster.nav.prefs import load_entity_metadata_props

        return load_entity_metadata_props() or default_entity_annotation_catalog()

    def _load_configured_langs(self, path: Path | None, lang: str) -> list[str]:
        """Per-file configured languages, defaulting to the display language."""
        if path is None:
            return [lang]
        from ster.nav.prefs import load_configured_langs

        return load_configured_langs(path) or [lang]

    def action_open_config(self) -> None:
        """Open the global configuration modal (it auto-saves via ConfigModal.Changed)."""
        from ster.ontology_imports import is_annotation_property

        from .config_modal import ConfigModal

        available = data.languages_in_use(self.tax)
        themes = sorted(self.available_themes)
        self.push_screen(
            ConfigModal(
                self.lang,
                self.configured_langs,
                available,
                themes,
                self.theme,
                metadata_props=self.metadata_props,
                entity_metadata_props=self.entity_metadata_props,
                annotation_verifier=lambda uri: is_annotation_property(self.tax, uri),
                can_declare=self._service is not None and self._path is not None,
                base_uri=self.tax.base_uri(),
            )
        )

    def on_config_modal_changed(self, message) -> None:  # type: ignore[no-untyped-def]
        """A setting changed in the config modal → apply it live and persist."""
        self._apply_config(message.result)

    def on_declare_annotation_property(self, message) -> None:  # type: ignore[no-untyped-def]
        """A config-modal predicate was confirmed despite not being a known annotation
        property → declare it locally as an ``owl:AnnotationProperty`` (skip if it is
        already a property of some kind)."""
        uri = message.uri
        if self._path is None or uri in self.tax.owl_properties:
            return
        from ster.core.commands import OwlAddProperty, OwlSetComment

        label = getattr(message, "label", "")
        self._apply_command(OwlAddProperty(self._path, uri, "AnnotationProperty", label, self.lang))
        comment = getattr(message, "comment", "")
        if comment:
            self._apply_command(OwlSetComment(self._path, uri, self.lang, comment))

    def _apply_config(self, result: dict) -> None:
        """Apply + persist the chosen languages and theme. Re-renders the detail
        whenever the configured set changes (so new add-label rows appear), and
        offers to purge data for any language that was removed."""
        new_lang = result["display"] or self.lang
        display_changed = new_lang != self.lang
        removed = sorted(set(self.configured_langs) - set(result["configured"]))
        langs_changed = set(self.configured_langs) != set(result["configured"])
        self.configured_langs = result["configured"]  # exact selection (may be empty)
        self.lang = new_lang
        theme = result.get("theme")
        if theme and theme in self.available_themes:
            self.theme = theme  # live preview
        self._persist_config(result, new_lang)

        if display_changed:
            self.search_rows = data.search_rows(self.tax, self.lang)
            self._rebuild_tree()
        if display_changed or langs_changed:
            self._show(self._detail_uri)  # reflect the new configured-language rows
        for lang in removed:
            self._maybe_purge_language(lang)

    def _persist_config(self, result: dict, new_lang: str) -> None:
        """Save the config modal's settings (theme + metadata catalog globally,
        display + configured languages per-file)."""
        from ster.nav.prefs import (
            _save_lang_pref,
            _save_prefs,
            save_configured_langs,
            save_entity_metadata_props,
            save_metadata_props,
        )

        _save_prefs({"theme": self.theme})  # theme is a global preference
        if "metadata_props" in result:  # the configurable "Add metadata" catalog (global)
            self.metadata_props = [tuple(p) for p in result["metadata_props"]]
            save_metadata_props(self.metadata_props)
        if "entity_metadata_props" in result:  # the entity-metadata catalog (global)
            self.entity_metadata_props = [tuple(p) for p in result["entity_metadata_props"]]
            save_entity_metadata_props(self.entity_metadata_props)
        if self._path is not None:
            _save_lang_pref(self._path, new_lang)
            save_configured_langs(self._path, self.configured_langs)

    def _maybe_purge_language(self, lang: str) -> None:
        """A configured language was removed: if the file still has data in it,
        ask whether to delete every ⟨lang⟩ literal or keep it."""
        from ster.operations import language_in_use

        if self._service is None or self._path is None or not language_in_use(self.tax, lang):
            return
        path = self._path
        prompt = f"Delete all “{lang}” labels, comments, definitions & scope notes?"

        def _on_choice(choice: str | None) -> None:
            if choice == "delete":
                from ster.core.commands import RemoveLanguage

                self._apply_command(RemoveLanguage(path, lang))

        self.push_screen(
            ChoiceModal(
                prompt, [("Delete all", "delete"), ("Keep them in the file", "keep")], danger=True
            ),
            _on_choice,
        )

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
            with Vertical(id="nav"):
                yield OntologyTree("ontology", id="tree")
                yield OntologyTree("properties", id="prop-tree")
            yield DetailView(id="detail")
        yield Footer()
        yield ContextMenu(id="ctx-menu")  # hidden overlay; shown on right-click

    def on_mount(self) -> None:
        self.title = f"ster ontology browser - {self.source}"
        self.sub_title = ""
        for tree in self.query(Tree):
            tree.show_root = False
            tree.guide_depth = 3
        self._build_main_tree(self.query_one("#tree", Tree))
        self._build_prop_tree(self.query_one("#prop-tree", Tree))
        self.query_one("#tree", Tree).border_title = "Ontology"
        self.query_one("#prop-tree", Tree).border_title = "Properties"
        self.query_one("#detail", DetailView).border_title = "Details"
        self.query_one("#tree", Tree).focus()
        # Both trees emit a spurious initial NodeHighlighted on mount (the
        # prop-tree's lands on its data-less header → _show(None)), which would
        # clobber the detail pane. Show the overview after the refresh settles so
        # it is the last word; the Ontology node (first row) carries the URI.
        self.call_after_refresh(self._show, detail.OVERVIEW_URI)

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

    def _build_main_tree(self, tree: Tree) -> None:
        """Top pane: Ontology section (classes), Taxonomy section (schemes).

        The Ontology and Taxonomy section nodes carry the overview URI, so
        highlighting either one shows the ontology overview in the detail pane
        (there is no separate Overview leaf).
        """
        tax, root = self.tax, tree.root

        # ── Ontology section (OWL classes) ────────────────────────────────────
        ont_sec = root.add("Ontology", data=detail.OVERVIEW_URI)
        ont_sec.add_leaf("＋ Add class", data=_action_uri("create_owl_class"))
        for uri in data.class_roots(tax, self.lang):
            self._add_class(ont_sec, uri)
        ont_sec.expand()

        # Loose individuals (no class) are nested under the Ontology section.
        loose = data.untyped_individuals(tax, self.lang)
        if loose:
            ind_sec = ont_sec.add(f"{data.ICON['section']} Individuals", data=None)
            for uri in loose:
                self._leaf(ind_sec, uri, "individual")

        # ── Taxonomy section (SKOS concept schemes) ───────────────────────────
        tax_sec = root.add("Taxonomy", data=detail.TAXONOMY_URI)
        tax_sec.add_leaf("＋ Add concept scheme", data=_action_uri("add_scheme"))
        for s_uri in data.scheme_roots(tax, self.lang):
            sec = tax_sec.add(
                f"{data.ICON['scheme']} {data.label_of(tax, s_uri, self.lang)}", data=s_uri
            )
            self._index(s_uri, sec)
            sec.add_leaf("＋ Add concept", data=_action_uri("add_top_concept", s_uri))
            for c_uri in data.concept_children(tax, s_uri, self.lang):
                self._add_concept(sec, c_uri)
            sec.expand()
        tax_sec.expand()
        self._strip_childless_arrows(root)

    def _build_prop_tree(self, tree: Tree) -> None:
        """Bottom pane: properties grouped by kind — Object / Datatype / Annotation
        always shown, plus an orange "Untyped Properties" group for bare
        ``rdf:Property`` entries. Within a group the locally-declared properties come
        first, then predicates merely *used* on the ontology header (e.g.
        ``dcterms:creator``), each flagged with a small ``(ext)`` indicator."""
        tax = self.tax
        if not tax.owl_properties and not tax.ontology_annotations:
            return
        for title, local, external in data.property_groups(tax, self.lang):
            label = (
                f"[orange1]{title}[/orange1]" if title == data.UNTYPED_PROPERTIES_TITLE else title
            )
            sec = tree.root.add(label, data=None)
            for uri in local:
                self._leaf(sec, uri, "property")
            for uri in external:
                self._leaf(sec, uri, "property", suffix="  [dim](ext)[/dim]")
            sec.expand()
        self._strip_childless_arrows(tree.root)

    @staticmethod
    def _strip_childless_arrows(root: TreeNode) -> None:
        """Drop the expand/collapse arrow from every node that has no children.

        An arrow on a childless node misleadingly hints at a drill-down (click /
        Enter to open) when there is nothing below it. Nodes keep their arrow only
        when they actually have a subtree.
        """
        stack = list(root.children)
        while stack:
            node = stack.pop()
            node.allow_expand = bool(node.children)
            stack.extend(node.children)

    # ── interaction ─────────────────────────────────────────────────────────--

    def _show(self, uri: str | None) -> None:
        # _detail_text mirrors the rendered markup (used by tests + as a quick
        # text view); the DetailView builds the composed, focusable widgets.
        self._detail_uri = uri
        clangs = self.configured_langs or [self.lang]
        self._detail_text = (
            detail.render_detail(self.tax, uri, self.lang, clangs) if uri else PLACEHOLDER
        )
        is_overview = uri == detail.OVERVIEW_URI
        activity = self._ontology_activity() if is_overview else None
        lint = self._ontology_lint() if is_overview else None
        view = self.query_one("#detail", DetailView)
        view.update_entity(self.tax, uri, self.lang, activity, lint[0] if lint else None, clangs)
        view.border_title = self._detail_title(uri)

    def _ontology_activity(self) -> dict | None:
        """Git edit-activity for the file (computed once per session, cached)."""
        if self._path is None:
            return None
        if not self._activity_computed:
            from ster.git.manager import file_activity

            self._activity_cache = file_activity(self._path)
            self._activity_computed = True
        return self._activity_cache

    def _ontology_lint(self) -> tuple[dict, list] | None:
        """semanticlint result for the file (computed once per session, cached)."""
        if self._path is None:
            return None
        if not self._lint_computed:
            from ster.lint_runner import lint_overview

            try:
                self._lint_cache = lint_overview(self._path)
            except Exception:  # noqa: BLE001 — a lint failure must never break the view
                self._lint_cache = None
            self._lint_computed = True
        return self._lint_cache

    def _detail_title(self, uri: str | None) -> str:
        """The detail pane's border title — the current entity, or a generic label.

        Entities that have a context menu get a trailing ``⋯`` to hint that quick
        actions are available (right-click, or press ``.``)."""
        if uri is None:
            return "Details"
        if uri == detail.OVERVIEW_URI:
            return "Ontology overview"
        if uri == detail.TAXONOMY_URI:
            return "Taxonomy overview"
        label = data.label_of(self.tax, uri, self.lang) or "Details"
        if edits.context_actions(data.kind_of(self.tax, uri)):
            label += "  ⋯"  # a context menu is available
        return label

    # ── mutation pipeline ───────────────────────────────────────────────────────

    def _rebuild_tree(self) -> None:
        self._uri_nodes = {}
        main = self.query_one("#tree", Tree)
        main.root.remove_children()
        self._build_main_tree(main)
        props = self.query_one("#prop-tree", Tree)
        props.root.remove_children()
        self._build_prop_tree(props)

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
        # The mutation rebuilt the detail rows, destroying the row that had focus —
        # restore it (next refresh) so the keyboard keeps working after a modal.
        self.call_after_refresh(self._restore_focus)

    def _restore_focus(self) -> None:
        """Land focus on a usable widget after a mutation rebuilt the panes."""
        rows = [r for r in self.query("#detail DetailRow") if r.can_focus]
        (rows[0] if rows else self.query_one("#tree", Tree)).focus()

    def on_detail_row_edit_requested(self, message: DetailRow.EditRequested) -> None:
        """An edit-only value row asked to be edited → open the modal → command."""
        self._open_edit_modal(message.field, origin=self.focused)

    def _open_edit_modal(self, field: DetailField, origin: Widget | None = None) -> None:
        """Open the prefilled edit modal for *field* and apply the resulting command.

        On cancel, focus returns to *origin* (the row being edited) so it stays in
        the detail pane instead of jumping back to the tree.
        """
        # A field may target a different entity than the shown one (e.g. the taxonomy
        # overview edits the primary scheme via meta["target_uri"]).
        uri, path = field.meta.get("target_uri") or self._detail_uri, self._path
        if self._service is None or uri is None or path is None:
            self.notify("Read-only session (no file loaded).", severity="warning")
            return

        def _on_submit(value: str | None) -> None:
            if value is None:
                if origin is not None:
                    origin.focus()  # Esc/cancel: keep focus in the detail pane
                return
            command = edits.edit_command(field, uri, path, value)
            if command is None:
                self.notify("This field isn't editable yet.", severity="warning")
                return
            self._apply_command(command)

        # A URI value is renamed fragment-only: lock its namespace, edit the local name.
        if field.meta.get("type") == "uri":
            prefix, fragment = uri_edit.split_namespace(field.value)
            self.push_screen(UriModal(field.display, prefix, fragment), _on_submit)
        else:
            self.push_screen(EditModal(field.display, field.value), _on_submit)

    def on_detail_row_menu_requested(self, message: DetailRow.MenuRequested) -> None:
        """A value row with both edit and delete was activated → Edit/Delete submenu."""
        self._row_menu_field = message.field
        self._row_menu_delete = message.delete_field
        self._row_menu_origin = self.focused  # the row, before the menu grabs focus
        items = [("✎ Edit", "row_edit"), ("⊘ Delete", "row_delete")]
        self.query_one("#ctx-menu", ContextMenu).show(message.field.display, items, message.anchor)

    def _apply_row_delete(self, delete_field: DetailField) -> None:
        """Run the paired removal command for a row's Delete submenu choice."""
        uri, path = self._detail_uri, self._path
        if self._service is None or uri is None or path is None:
            self.notify("Read-only session (no file loaded).", severity="warning")
            return
        command = edits.direct_command(delete_field, uri, path)
        if command is not None:
            self._apply_command(command)

    def on_detail_row_action_requested(self, message: DetailRow.ActionRequested) -> None:
        """An action row was activated → run it (shared with the right-click menu)."""
        self._run_field_action(message.field)

    def _run_field_action(self, field: DetailField) -> None:
        """Dispatch an action *field*: graph view, meta-driven removal, or a flow."""
        action = field.meta.get("action", "")
        if action in ("view_ontology_graph", "view_focused_graph"):
            self._open_graph(action, field)  # a view, not a mutation — no service needed
            return
        if action == "view_lint":
            self._open_lint(field.meta.get("lint_severity"))  # a view — no service needed
            return
        uri, path = self._detail_uri, self._path
        if self._service is None or uri is None or path is None:
            self.notify("Read-only session (no file loaded).", severity="warning")
            return
        if action == "edit_class":
            self._open_class_edit(uri, path)  # full class modal (URI + labels + comments)
            return
        direct = edits.direct_command(field, uri, path)
        if direct is not None:  # meta-driven removal — run immediately, no modal
            self._apply_command(direct)
            return
        opener = self._route_action(action)
        if opener is None:
            self.notify("This action isn't wired up yet.", severity="warning")
            return
        opener(field, uri, path)

    def action_context_menu(self) -> None:
        """'.' → open the context menu for the selected entity, at the tree cursor."""
        if self._detail_uri:
            self.open_context_menu(self._detail_uri, self._tree_cursor_anchor())

    def _tree_cursor_anchor(self) -> tuple[int, int] | None:
        """Screen position of the focused tree's cursor row (for menu anchoring)."""
        tree = self.focused if isinstance(self.focused, Tree) else None
        if tree is None:
            return None
        region = tree.region
        return (region.x + 2, region.y + max(0, tree.cursor_line - tree.scroll_offset.y))

    def open_context_menu(self, uri: str, anchor: tuple[int, int] | None = None) -> None:
        """Right-click / '.' handler: select the node and offer kind-appropriate
        quick actions. *anchor* is the cursor position; the menu pops up there
        (centred when None).
        """
        items = edits.context_actions(data.kind_of(self.tax, uri))
        if not items:
            return
        self._show(uri)  # select it, so the actions target this entity
        label = data.label_of(self.tax, uri, self.lang)
        self.query_one("#ctx-menu", ContextMenu).show(label, items, anchor)

    def on_context_menu_chosen(self, message: ContextMenu.Chosen) -> None:
        """A context-menu action was picked → run it against the selected entity."""
        # Detail-row Edit/Delete submenu (takes priority over the tree-node menu).
        if message.action == "row_edit" and self._row_menu_field is not None:
            field, self._row_menu_field = self._row_menu_field, None
            self._row_menu_delete = None
            self._open_edit_modal(field, origin=self._row_menu_origin)
            return
        if message.action == "row_delete" and self._row_menu_delete is not None:
            delete_field, self._row_menu_delete = self._row_menu_delete, None
            self._row_menu_field = None
            self._apply_row_delete(delete_field)
            return

        uri = self._detail_uri
        if uri is None:
            return
        if message.action == "rename":
            self._rename_entity(uri)
        else:  # synthesise the row this action would come from, then run it
            self._run_field_action(
                DetailField(
                    "ctx", "", "", editable=False, meta={"type": "action", "action": message.action}
                )
            )

    def _rename_entity(self, uri: str) -> None:
        """Open a modal to rename *uri* (cascades across every reference)."""
        if self._service is None or self._path is None:
            self.notify("Read-only session (no file loaded).", severity="warning")
            return
        path = self._path
        field = DetailField("uri", "URI", uri, editable=True, meta={"type": "uri"})

        def _on_submit(value: str | None) -> None:
            if value and value != uri:
                command = edits.edit_command(field, uri, path, value)
                if command is not None:
                    self._apply_command(command)

        prefix, fragment = uri_edit.split_namespace(uri)
        self.push_screen(UriModal("Rename URI", prefix, fragment), _on_submit)

    def _route_action(self, action: str):  # type: ignore[no-untyped-def]
        """Pick the flow opener for *action* — first table whose set contains it."""
        routes = (
            (edits.DELETE_CHOICES, self._confirm_delete),
            (edits.PICKER_ACTIONS, self._pick_relation),
            (edits.META_PICKER_ACTIONS, self._pick_meta_relation),
            (edits.CONVERT_ACTIONS, self._confirm_convert),
            (edits.CHAINED_ACTIONS, self._add_property_value),
            (edits.SCHEME_ACTIONS, self._create_scheme),
            (edits.ONTOLOGY_RENAME_ACTIONS, self._edit_ontology_identity),
            (edits.ANNOTATION_ADD_ACTIONS, self._add_ont_annotation),
            (edits.META_INPUT_ACTIONS, self._open_meta_input),
            (edits.INPUT_ACTIONS, self._open_input),
        )
        return next((opener for collection, opener in routes if action in collection), None)

    def _pool_for(self, kind: str) -> dict:  # type: ignore[type-arg]
        """The candidate entity dict for a picker *kind*."""
        if kind == "concept":
            return self.tax.concepts
        if kind == "individual":
            return self.tax.owl_individuals
        return self.tax.owl_classes

    def _open_picker(self, prompt: str, kind: str, exclude: str, on_pick) -> None:  # type: ignore[no-untyped-def]
        """Show a picker of all *kind* entities (excluding *exclude*) → callback with the URI."""
        candidates = sorted(
            (
                (data.label_of(self.tax, u, self.lang), u)
                for u in self._pool_for(kind)
                if u != exclude
            ),
            key=lambda t: t[0].lower(),
        )
        if not candidates:
            self.notify(f"No other {kind}s to link to.", severity="warning")
            return
        self.push_screen(PickerModal(prompt, candidates, kind_label=kind), on_pick)

    def _run_or_warn(self, command: object | None) -> None:
        """Apply *command*, or warn if the dispatch produced nothing."""
        if command is None:
            self.notify("This action isn't wired up yet.", severity="warning")
            return
        self._apply_command(command)

    _CLASS_CREATE_ACTIONS = frozenset({"create_owl_class", "new_subclass"})

    def _open_input(self, field: DetailField, uri: str, path: Path) -> None:
        """Collect a single text/URI value in a modal, then run its action command."""
        action = field.meta.get("action", "")
        # Creating a class opens the full class modal (URI + labels + comments).
        if action in self._CLASS_CREATE_ACTIONS:
            self._open_class_create(action, uri, path)
            return
        prompt, prefill_kind = edits.INPUT_ACTIONS[action]

        def _on_submit(value: str | None) -> None:
            if value:
                self._run_or_warn(edits.action_command(action, uri, path, value, self.lang))

        # A new URI is minted fragment-only under the locked ontology/scheme base.
        if prefill_kind == "base_uri":
            base = uri_edit.mint_base(self.tax, action, uri)
            self.push_screen(UriModal(prompt, base), _on_submit)
        else:
            self.push_screen(EditModal(prompt, ""), _on_submit)

    def _class_langs(self) -> list[str]:
        return self.configured_langs or [self.lang]

    def _open_class_create(self, action: str, uri: str, path: Path) -> None:
        """Open the full class modal to create a class (top-level or under *uri*)."""
        from ster.core.commands import OwlCreateClass

        from .class_modal import ClassModal

        base = uri_edit.mint_base(self.tax, action, uri)
        parent = uri if action == "new_subclass" else None

        def _on_submit(result: dict | None) -> None:
            if result:
                self._apply_command(
                    OwlCreateClass(
                        path,
                        result["uri"],
                        parent,
                        tuple(result["labels"].items()),
                        tuple(result["comments"].items()),
                    )
                )

        self.push_screen(ClassModal(prefix=base, langs=self._class_langs()), _on_submit)

    def _open_class_edit(self, uri: str, path: Path) -> None:
        """Open the full class modal to edit an existing class (URI / labels / comments)."""
        from ster.core.commands import OwlSaveClass

        from .class_modal import ClassModal

        cls = self.tax.owl_classes.get(uri)
        if cls is None:
            return
        prefix, fragment = uri_edit.split_namespace(uri)
        labels = {lbl.lang: lbl.value for lbl in cls.labels}
        comments = {c.lang: c.value for c in cls.comments}

        def _on_submit(result: dict | None) -> None:
            if result:
                self._apply_command(
                    OwlSaveClass(
                        path,
                        uri,
                        result["uri"],
                        tuple(result["labels"].items()),
                        tuple(result["comments"].items()),
                    )
                )

        self.push_screen(
            ClassModal(
                prefix=prefix,
                fragment=fragment,
                langs=self._class_langs(),
                labels=labels,
                comments=comments,
                title="Edit class",
            ),
            _on_submit,
        )

    def _open_meta_input(self, field: DetailField, uri: str, path: Path) -> None:
        """Edit one existing value (the row's meta names which) via a prefilled modal."""
        action = field.meta.get("action", "")
        prompt, prefill_key = edits.META_INPUT_ACTIONS[action]

        def _on_submit(value: str | None) -> None:
            if value:
                self._run_or_warn(edits.meta_input_command(field, uri, path, value, self.lang))

        # base_uri-kind meta inputs (e.g. add_class_property) mint a new URI fragment-only.
        if prefill_key == "base_uri":
            base = uri_edit.mint_base(self.tax, action, uri)
            self.push_screen(UriModal(prompt, base), _on_submit)
            return

        self.push_screen(EditModal(prompt, field.meta.get(prefill_key, "")), _on_submit)

    def _confirm_delete(self, field: DetailField, uri: str, path: Path) -> None:
        """Ask for the delete mode, then run the destructive command + navigate away."""
        action = field.meta.get("action", "")
        prompt = f"Delete «{data.label_of(self.tax, uri, self.lang)}»?"

        def _on_choice(mode: str | None) -> None:
            if mode is None:
                return
            self._run_or_warn(edits.delete_command(action, uri, path, mode))
            self._show(None)  # the entity is gone — clear the detail pane

        self.push_screen(ChoiceModal(prompt, edits.DELETE_CHOICES[action], danger=True), _on_choice)

    def _confirm_convert(self, field: DetailField, uri: str, path: Path) -> None:
        """Confirm a class↔individual punning conversion, then run it (URI is kept)."""
        action = field.meta.get("action", "")
        cls = self.tax.owl_classes.get(uri)
        parents = tuple(sorted(cls.sub_class_of)) if cls else ()
        target = "class" if action == "individual_to_class" else "individual"
        prompt = f"Convert «{data.label_of(self.tax, uri, self.lang)}» to an OWL {target}?"

        def _on_choice(choice: str | None) -> None:
            if choice is None:
                return
            self._run_or_warn(edits.convert_command(action, uri, path, choice, parents))
            self._show(uri)  # same URI, now a different kind of entity

        self.push_screen(ChoiceModal(prompt, edits.convert_choices(action, parents)), _on_choice)

    def _pick_relation(self, field: DetailField, uri: str, path: Path) -> None:
        """Pick a target entity for a relation action (add superclass/type/broader/related)."""
        action = field.meta.get("action", "")
        prompt, kind = edits.PICKER_ACTIONS[action]

        def _on_pick(target: str | None) -> None:
            if target is not None:
                self._run_or_warn(edits.relation_command(action, uri, path, target))

        self._open_picker(prompt, kind, uri, _on_pick)

    def _pick_meta_relation(self, field: DetailField, uri: str, path: Path) -> None:
        """Pick a replacement entity for a meta-aware value edit (e.g. change object value)."""
        prompt, kind = edits.META_PICKER_ACTIONS[field.meta.get("action", "")]

        def _on_pick(target: str | None) -> None:
            if target is not None:
                self._run_or_warn(edits.meta_relation_command(field, uri, path, target))

        self._open_picker(prompt, kind, uri, _on_pick)

    def _add_property_value(self, field: DetailField, uri: str, path: Path) -> None:
        """Two-step: pick a property, then pick an individual (object) or type a literal."""
        props = sorted(
            ((data.label_of(self.tax, p, self.lang), p) for p in self.tax.owl_properties),
            key=lambda t: t[0].lower(),
        )
        if not props:
            self.notify("No properties defined — create one first.", severity="warning")
            return

        def _on_prop(prop_uri: str | None) -> None:
            if prop_uri is not None:
                self._collect_value_for(uri, path, prop_uri)

        self.push_screen(
            PickerModal("Add a value — pick a property", props, kind_label="property"), _on_prop
        )

    def _collect_value_for(self, uri: str, path: Path, prop_uri: str) -> None:
        """Step 2 of add-value: object properties pick an individual, others type a literal."""
        prop = self.tax.owl_properties.get(prop_uri)
        if prop is not None and prop.prop_type == "ObjectProperty":

            def _on_target(target: str | None) -> None:
                if target is not None:
                    self._apply_command(edits.add_object_value_command(uri, path, prop_uri, target))

            self._open_picker("Pick the value — an individual", "individual", uri, _on_target)
            return

        def _on_literal(value: str | None) -> None:
            if value:
                self._apply_command(edits.add_literal_value_command(uri, path, prop_uri, value))

        self.push_screen(EditModal("Literal value", ""), _on_literal)

    def _edit_ontology_identity(self, field: DetailField, uri: str, path: Path) -> None:
        """Edit the ontology base URI (or its domain), cascading across every entity."""
        from ster.operations import ontology_domain

        is_domain = field.meta.get("action") == "edit_ontology_domain"
        if not is_domain:  # base URI → dedicated separator picker + impact confirm
            self._edit_ontology_uri(path, origin=self.focused)
            return
        prompt = "Ontology domain (host)"
        prefill = field.value or ontology_domain(self.tax)
        origin = self.focused

        def _on_submit(value: str | None) -> None:
            if not value:
                if origin is not None:
                    origin.focus()
                return
            base = self._resolve_domain_base(value)
            if base is not None:
                self._apply_command(edits.ontology_rename_command(path, base))

        self.push_screen(EditModal(prompt, prefill), _on_submit)

    def _resolve_domain_base(self, value: str) -> str | None:
        """The new base URI (with separator) for a host swap, or None if invalid."""
        from ster.operations import count_domain_rename_changes, validate_domain

        err = validate_domain(value)
        if err:
            self.notify(err, severity="error")
            return None
        return count_domain_rename_changes(self.tax, value)[1]  # new_base, sep included

    def _edit_ontology_uri(self, path: Path, origin: Widget | None = None) -> None:
        """Open the ontology-identity modal (domain / path / sep / prefix)."""
        scheme, domain, ont_path, sep, prefix = self._ontology_identity_parts()

        def _on_done(result: dict | None) -> None:
            if result is None:
                if origin is not None:
                    origin.focus()
                return
            self._apply_identity_changes(path, scheme, result, prefix, origin)

        self.push_screen(
            OntologyIdentityModal(domain=domain, path=ont_path, sep=sep, prefix=prefix), _on_done
        )

    def _ontology_identity_parts(self) -> tuple[str, str, str, str, str]:
        """Decompose the ontology URI into (scheme, domain, path, sep, prefix)."""
        from urllib.parse import urlsplit

        from ster.domain.onto import ontology_prefix

        root = (self.tax.ontology_uri or "").rstrip("#/")
        sep = "#"
        for u in list(self.tax.owl_classes) + list(self.tax.owl_individuals):
            if len(u) > len(root) and u.startswith(root) and u[len(root)] in ("#", "/"):
                sep = u[len(root)]
                break
        parts = urlsplit(root)
        return (
            parts.scheme or "https",
            parts.netloc,
            parts.path.strip("/"),
            sep,
            ontology_prefix(self.tax) or "",
        )

    def _apply_identity_changes(
        self, path: Path, scheme: str, result: dict, old_prefix: str, origin: Widget | None
    ) -> None:
        """Recompose the URI; confirm + cascade the rename, then set the prefix."""
        from ster.operations import count_ontology_rename_changes

        new_root = f"{scheme}://{result['domain']}"
        if result["path"]:
            new_root += "/" + result["path"]
        sep = result["sep"]
        old_base, new_base, count = count_ontology_rename_changes(self.tax, new_root, sep)
        prefix_changed = result["prefix"] != (old_prefix or "")

        def _set_prefix() -> None:
            if prefix_changed and result["prefix"]:
                self._apply_command(
                    edits.action_command("edit_ontology_prefix", "", path, result["prefix"])
                )

        if old_base != new_base:  # URI changed → confirm the cascade first
            noun = "entity" if count == 1 else "entities"
            prompt = f"Rename → {new_base}   ·   {count} {noun} updated"

            def _on_confirm(choice: str | None) -> None:
                if choice == "ok":
                    self._apply_command(edits.ontology_rename_command(path, new_root + sep))
                    _set_prefix()
                elif origin is not None:
                    origin.focus()

            self.push_screen(ChoiceModal(prompt, [("Confirm rename", "ok")]), _on_confirm)
        elif prefix_changed:
            _set_prefix()
        elif origin is not None:
            origin.focus()

    def _add_ont_annotation(self, field: DetailField, uri: str, path: Path) -> None:
        """Two-step: pick a predicate from the catalog, then enter the value."""
        from ster.nav.logic import annotation_catalog_options

        options = annotation_catalog_options(self.tax, self.metadata_props)
        if not options:
            self.notify("All known annotation predicates are already present.", severity="warning")
            return

        # PickerModal expects (label, value) — use the display label, value is the predicate URI.
        picker_options = [(label, pred) for pred, label in options]

        def _on_predicate(predicate: str | None) -> None:
            if not predicate:
                return

            def _on_value(value: str | None) -> None:
                if value:
                    from ster.core.commands import OntoSetAnnotation

                    self._apply_command(OntoSetAnnotation(path, predicate, "", value))

            # Derive a short prompt from the label (strip the parenthetical hint).
            label = next((lbl for pred, lbl in options if pred == predicate), predicate)
            short = label.split("  ")[0]
            self.push_screen(EditModal(f"Value for {short}", ""), _on_value)

        self.push_screen(
            PickerModal("Add metadata — pick a predicate", picker_options), _on_predicate
        )

    def _create_scheme(self, field: DetailField, uri: str, path: Path) -> None:
        """Two-step: collect the scheme title, then its URI, and create it."""

        def _on_title(title: str | None) -> None:
            if not title:
                return

            def _on_uri(scheme_uri: str | None) -> None:
                if scheme_uri:
                    self._apply_command(
                        edits.create_scheme_command(path, scheme_uri, title, self.lang)
                    )

            self.push_screen(EditModal("Scheme URI", self.tax.base_uri()), _on_uri)

        self.push_screen(EditModal(f"Scheme title [{self.lang}]", ""), _on_title)

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        uri = event.node.data
        # Action sentinel nodes (＋ Add class / scheme / concept) have no detail
        # panel — clear the pane so the user sees the placeholder until they press Enter.
        if uri and _parse_action_uri(uri) is not None:
            self._show(None)
            return
        self._show(uri)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Enter / click: fire the tree action for sentinel nodes."""
        uri = event.node.data
        if not uri:
            return
        parsed = _parse_action_uri(uri)
        if parsed is None:
            return  # real entity — NodeHighlighted already showed its detail
        action, extra = parsed
        self._dispatch_tree_action(action, extra)

    def _dispatch_tree_action(self, action: str, extra: str) -> None:
        """Run the creation flow for a tree action node."""
        path = self._path
        if path is None:
            self.notify("No file path — save the taxonomy first.", severity="warning")
            return
        # Reuse the exact same field/uri pair as the overview action rows did,
        # so the existing _route_action / _open_input / _create_scheme machinery
        # handles everything without new code.
        synthetic_field = DetailField(
            key=f"tree_action:{action}",
            display=action,
            value="",
            editable=False,
            meta={"action": action},
        )
        # For add_top_concept the extra is the scheme URI (the parent).
        uri = extra if extra else detail.OVERVIEW_URI
        opener = self._route_action(action)
        if opener is not None:
            opener(synthetic_field, uri, path)
        else:
            self.notify(f"Action not wired: {action}", severity="warning")

    def jump_to(self, uri: str) -> None:
        """Expand ancestors, move the cursor to *uri*, and show its detail."""
        node = self._uri_nodes.get(uri)
        if node is None:
            self.notify(f"Not in tree: {uri}", severity="warning")
            return
        # Properties live in their own pane; everything else in the main tree.
        tree_id = "#prop-tree" if uri in self.tax.owl_properties else "#tree"
        tree = self.query_one(tree_id, Tree)
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

    def action_help(self) -> None:
        """Open the keys-and-actions help overlay."""
        self.push_screen(HelpScreen())

    def _open_graph(self, action: str, field: DetailField) -> None:
        """Open the VOWL graph in the browser (whole ontology, or focused on an entity).

        A view, not a mutation: works read-only, opens a daemon-served page +
        browser tab (non-blocking) and reports the URL.
        """
        from ster import viz_vowl

        try:
            if action == "view_focused_graph":
                target = field.meta.get("uri") or self._detail_uri
                if not target:
                    self.notify("No entity to focus the graph on.", severity="warning")
                    return
                url = viz_vowl.open_focused_in_browser(self.tax, target, self._path)
            else:
                url = viz_vowl.open_in_browser(self.tax, self._path)
            self.notify(f"Graph opened in your browser — {url}")
        except Exception as exc:  # surfacing beats crashing the UI for a view action
            self.notify(f"Couldn't open the graph: {exc}", severity="error")

    def _open_lint(self, severity: str | None = None) -> None:
        """Open a modal listing the semanticlint issues of *severity* (a read-only
        view). Selecting an issue that points at a known entity jumps straight to
        it (e.g. a missing-label warning → that class), so it can be fixed in place.
        """
        from .lint_modal import LintModal

        result = self._ontology_lint()
        issues = result[1] if result else []
        if severity:
            issues = [i for i in issues if i.get("severity") == severity]
        kind = {"error": "Errors", "warning": "Warnings"}.get(severity or "", "semanticlint")
        self.push_screen(
            LintModal(issues, set(self._uri_nodes), kind=kind), self._goto_lint_subject
        )

    def _goto_lint_subject(self, subject: str | None) -> None:
        """Callback for the lint modal: navigate to the chosen issue's subject."""
        if subject:
            self.jump_to(subject)

    def action_cycle_theme(self) -> None:
        """Step through the curated theme shortlist (the full list is in the palette)."""
        cycle = [name for name in THEME_CYCLE if name in self.available_themes]
        if not cycle:
            return
        try:
            i = cycle.index(self.theme)
        except ValueError:
            i = -1
        self.theme = cycle[(i + 1) % len(cycle)]
        self.notify(f"Theme: {self.theme}", timeout=2)

    def _active_tree(self) -> Tree:
        """The tree the expand/collapse shortcuts act on: the focused pane when it is
        the properties tree, otherwise the main ontology tree."""
        prop_tree = self.query_one("#prop-tree", Tree)
        if self.focused is prop_tree:
            return prop_tree
        return self.query_one("#tree", Tree)

    def action_expand_all(self) -> None:
        self._active_tree().root.expand_all()

    def action_collapse_all(self) -> None:
        for child in self._active_tree().root.children:
            child.collapse_all()
