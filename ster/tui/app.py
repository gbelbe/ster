"""The Textual ontology browser & editor app.

Left: a `Tree` of Classes (with their individuals nested) / Properties / SKOS
schemes. Right: a progressive-disclosure detail panel. `/` (or ctrl+p) opens a
fuzzy command-palette search that jumps to any class / individual / property.

Editing routes through ``TaxonomyService`` (the command/service layer the curses
viewer also uses): activate a detail row (Enter) to edit a value or run an
action; every mutation is validated and written back to the file.
"""

from __future__ import annotations

import threading
from functools import partial
from pathlib import Path

from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.command import Hit, Hits, Provider
from textual.containers import Horizontal, Vertical
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Footer, Header, Static, Tree
from textual.widgets.tree import TreeNode

from ster.metadata_coverage import MetaProp
from ster.model import Taxonomy
from ster.nav.logic import DetailField, prop_comment

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

# Shared suffix for the tree's sentinel node data (property-header "add" sentinels).
_ACTION_SUFFIX = "__"

# Human-readable resource type shown in the detail-pane title (e.g. "Person (Class)").
_KIND_TITLE = {
    "class": "Class",
    "individual": "Individual",
    "property": "Property",
    "scheme": "Concept scheme",
    "concept": "Concept",
}


# A property-section header's ``data``: distinct from an action sentinel so left-click /
# Enter just expands it, while right-click offers "add a property of this kind".
_ADD_PROP_PREFIX = "__addprop:"


def _add_prop_uri(prop_type: str) -> str:
    return f"{_ADD_PROP_PREFIX}{prop_type}{_ACTION_SUFFIX}"


def _prop_section_key(prop_type: str) -> str:
    """Stable focus key for a property-tree section (Object / Datatype / …), so a deleted
    top-level property can land the cursor on its section. The three OWL kinds map straight
    across; anything else falls to the 'Untyped Properties' section."""
    known = {"ObjectProperty", "DatatypeProperty", "AnnotationProperty"}
    return f"__ster:propsection:{prop_type if prop_type in known else 'Property'}__"


def _parse_add_prop(uri: str | None) -> str | None:
    """The property type of an "add property here" section sentinel, else None."""
    if uri and uri.startswith(_ADD_PROP_PREFIX) and uri.endswith(_ACTION_SUFFIX):
        return uri[len(_ADD_PROP_PREFIX) : -len(_ACTION_SUFFIX)]
    return None


# The three OWL property kinds a header can create (the catch-all "Untyped Properties"
# group cannot). Object properties open the full modal; the other two a lightweight one.
# prop_type → (menu title, add-item label, create action, modal title).
_PROP_MENU: dict[str, tuple[str, str, str, str]] = {
    "ObjectProperty": (
        "Object properties",
        "＋ Add object property",
        "create_object_property",
        "New object property",
    ),
    "DatatypeProperty": (
        "Datatype properties",
        "＋ Add datatype property",
        "create_datatype_property",
        "New datatype property",
    ),
    "AnnotationProperty": (
        "Annotation properties",
        "＋ Add annotation property",
        "create_annotation_property",
        "New annotation property",
    ),
}
_CREATABLE_PROP_KINDS = frozenset(_PROP_MENU)
# create action → prop_type (reverse lookup for the context-menu dispatch).
_PROP_CREATE_ACTIONS: dict[str, str] = {row[2]: kind for kind, row in _PROP_MENU.items()}


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
        """Right-click a node → open its context menu, and suppress the default toggle so
        right-click never folds/unfolds the tree. ``prevent_default`` stops the base
        ``Tree._on_click`` (which would otherwise toggle/select) from running; left-click
        doesn't prevent it, so it keeps the default expand/collapse + select behaviour."""
        if event.button != 3:  # 3 = right button — left-click is Tree's default
            return
        event.prevent_default()  # right-click must not reach Tree._on_click (no toggle/select)
        style = getattr(event, "style", None)
        line = style.meta.get("line") if style is not None else None  # the clicked tree line
        if line is None:
            line = self.hover_line
        node = self.get_node_at_line(line) if line is not None and line >= 0 else None
        uri = node.data if node else None
        if uri:
            self.cursor_line = line  # select the right-clicked node visually
            self.app.open_context_menu(uri, (event.screen_x, event.screen_y))  # type: ignore[attr-defined]

    def watch_hover_line(self, previous_line: int, line: int) -> None:
        """Show a property's rdfs:comment as a tooltip while the mouse hovers its row."""
        node = self.get_node_at_line(line) if line is not None and line >= 0 else None
        uri = node.data if node is not None else None
        self.tooltip = self._hover_comment(uri) if uri else None

    def _hover_comment(self, uri: str) -> str | None:
        """The rdfs:comment of the property at *uri* (else None) — no tooltip for other kinds."""
        prop = self.app.tax.owl_properties.get(uri)  # type: ignore[attr-defined]
        if prop is None or not prop.comments:
            return None
        return prop_comment(prop, self.app.lang)  # type: ignore[attr-defined]


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
    /* Sub-sections (property-type groups) nest under their section: the header and its
       rows are indented so they read as subcategories of e.g. "Properties", with an extra
       line break above each subtitle to set the groups apart. */
    .section-header.sub-header { padding-left: 2; margin-top: 2; color: $text-muted; }
    .detail-row.sub-row { padding-left: 3; }
    /* A visual group: a bordered, titled box enclosing its clustered sections. */
    .detail-group {
        height: auto;
        border: round $secondary;
        border-title-color: $secondary;
        padding: 0 1;
        margin: 1 0;
    }
    .detail-group .section-header:first-of-type { margin-top: 0; }
    /* Inherited-properties disclosure: no extra gap, subtle title. */
    .detail-collapsible { margin: 1 0 0 0; border: none; padding-top: 0; }
    .detail-collapsible CollapsibleTitle { color: $text-muted; }
    .detail-row { padding: 0 1; margin-bottom: 1; }  /* a little air between property lines */
    .detail-row:focus { background: $primary 20%; }
    /* $boost is a translucent overlay → invisible on light themes; use a solid
       accent tint so the mouse-over highlight shows in every theme. */
    .detail-row:hover { background: $secondary 20%; }
    /* Information-only rows are not interactive — no hover affordance. */
    .detail-row.info-row:hover { background: transparent; }
    /* The leading "» Open Graph View" action — highlighted so it reads as the
       primary quick action for the entity. */
    .detail-row.graph-action { color: $secondary; text-style: bold; margin-bottom: 1; }
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
    /* Bottom-right status overlay: the current display language. */
    #lang-indicator {
        layer: overlay;
        dock: bottom;
        width: auto;
        height: 1;
        offset-x: 100%;          /* push to the right edge … */
        constrain: inside none;  /* … then pull fully back into view */
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    /* Bottom-left busy overlay: a spinner + what's happening (Saving… / Checking…). */
    #busy {
        layer: overlay;
        dock: bottom;
        width: auto;
        height: 1;
        background: $surface;
        color: $accent;
        text-style: bold;
        padding: 0 1;
        display: none;   /* shown only while an activity is running */
    }
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
        Binding("g", "open_graph", "GraphView"),
        Binding("s", "open_query", "SPARQL"),
        Binding("d", "cycle_theme", "Theme", show=False),  # still works; hint hidden
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
        open_query: bool = False,
    ) -> None:
        super().__init__()
        self._open_query_on_start = open_query
        self._browser_ready = False  # overview shown + first lint computed + tree recoloured
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
        # Semanticlint result (counts, issues) + a uri→worst-severity index for O(1)
        # per-entity lookups (icon colours, detail annotations). Recomputed in the
        # background after edits when the plugin is active.
        self._lint_cache: tuple[dict, list] | None = None
        self._lint_computed = False
        self._lint_index: dict[str, str] = {}
        self._lint_icons_on = False  # cached (plugin + 'icons' feature on)
        self._lint_detail_on = False  # cached (plugin + 'detail' feature on)
        self._lint_quality_on = False  # cached (plugin + 'quality_block' feature on)
        self._overview_quality_on = True  # overview Quality & Coverage group visible
        # The value row whose Edit/Delete submenu is open (set while it is shown).
        self._row_menu_field: DetailField | None = None
        self._row_menu_delete: DetailField | None = None
        self._row_menu_origin: Widget | None = None  # row to refocus after the submenu
        # Persist off the UI thread (the slow part of an edit); the lock serialises writes
        # and each save writes the latest authority, so the disk converges to it.
        self._save_lock = threading.Lock()
        self._save_dirty = False
        self._lint_timer: Timer | None = None  # debounce handle for the heavy re-lint
        self._activities: dict[str, str] = {}  # running background jobs → label (Saving/Checking)
        self._busy_timer: Timer | None = None  # spinner animation handle
        self._spinner_frame = 0
        # The detail row (by field key) that was being edited, so focus lands back on it
        # after a mutation rebuilds the pane — not on the first row / tree.
        self._pending_focus_key: str | None = None

    def _load_metadata_props(self) -> list[MetaProp]:
        """The configured ontology-metadata predicate catalog (built-in defaults
        when the user has never customised it)."""
        from ster.nav.logic import default_annotation_catalog
        from ster.nav.prefs import load_metadata_props

        return load_metadata_props() or default_annotation_catalog()

    def _load_entity_metadata_props(self) -> list[MetaProp]:
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

    def on_config_modal_write_onto_ci(self, message) -> None:  # type: ignore[no-untyped-def]
        """Export the plugin's quality config to the repo's onto-ci.yml (aligns CI)."""
        if self._path is None:
            self.notify("No file open — can't locate the repo.", severity="warning")
            return
        from ster.plugins.semanticlint import config

        path = config.write_onto_ci(self._path.parent)
        self.notify(f"Wrote {path.name} (aligned with quality.json).")

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

    #: SHACL enforcement targets for the entity-metadata catalog (user decision:
    #: classes and concepts only — not individuals or properties).
    _ENTITY_SHACL_TARGETS = (
        ("http://www.w3.org/2002/07/owl#Class", "every class"),
        ("http://www.w3.org/2004/02/skos/core#Concept", "every concept"),
    )

    def on_enforce_shacl_requested(self, message) -> None:  # type: ignore[no-untyped-def]
        """A config-tab enforce button toggled → write (or remove) the SHACL rule(s)
        making an annotation property mandatory, then re-lint."""
        import datetime

        from ster.plugins.semanticlint import shapes_author as shacl

        if self._path is None:
            self.notify("Read-only session — open the ontology first.", severity="warning")
            return
        targets = self._shacl_targets(message.scope)
        if not targets:
            self.notify("No ontology node to enforce on.", severity="warning")
            return
        shapes_path = shacl.shapes_path_for(self._path)
        if message.enforce:
            today = datetime.date.today().isoformat()
            rules = [
                self._annotation_rule(t, t_label, message.predicate, message.label, today)
                for t, t_label in targets
            ]
            shacl.append_rules(shapes_path, rules)
            self.notify(f"Enforced “{message.label}” via SHACL.")
        else:
            iris = [shacl.shape_iri(t, message.predicate) for t, _ in targets]
            shacl.remove_rules(shapes_path, iris)
            self.notify(f"Removed the SHACL rule for “{message.label}”.")
        self._invalidate_lint()
        self._refresh_lint_async()

    def _shacl_targets(self, scope: str) -> list[tuple[str, str]]:
        """(target_uri, label) pairs for a catalog *scope*: the ontology node, or every
        class + concept."""
        if scope == "ontology":
            ont = self.tax.ontology_uri
            return [(ont, "the ontology")] if ont else []
        return list(self._ENTITY_SHACL_TARGETS)

    def _annotation_rule(
        self, target: str, target_label: str, predicate: str, label: str, date: str
    ):  # type: ignore[no-untyped-def]
        """Build the mandatory rule for *predicate* on *target* — a node rule for the
        ontology, else a class rule."""
        from ster.plugins.semanticlint import shapes_author as shacl

        if target == self.tax.ontology_uri:
            return shacl.mandatory_on_node_rule(
                target, predicate, node_label=target_label, prop_label=label, date=date
            )
        return shacl.mandatory_property_rule(
            target, predicate, target_label=target_label, prop_label=label, date=date
        )

    def _apply_config(self, result: dict) -> None:
        """Apply + persist the chosen languages and theme. Re-renders the detail
        whenever the configured set changes (so new add-label rows appear), and
        offers to purge data for any language that was removed."""
        new_lang = result["display"] or self.lang
        display_changed = new_lang != self.lang
        removed = sorted(set(self.configured_langs) - set(result["configured"]))
        langs_changed = set(self.configured_langs) != set(result["configured"])
        # An entity-metadata catalog edit changes the overview's coverage %, so refresh
        # the detail (but not the tree — icons don't depend on the catalog).
        entity_meta_changed = self._entity_meta_changed(result)
        plugins_changed = self._apply_plugins(result)  # persists + invalidates lint cache
        self.configured_langs = result["configured"]  # exact selection (may be empty)
        self.lang = new_lang
        self._update_lang_indicator()
        self._apply_theme(result)
        self._persist_config(result, new_lang)
        self._refresh_after_config(
            result, display_changed, langs_changed, plugins_changed, entity_meta_changed
        )
        for lang in removed:
            self._maybe_purge_language(lang)

    def _refresh_after_config(
        self,
        result: dict,
        display_changed: bool,
        langs_changed: bool,
        plugins_changed: bool,
        entity_meta_changed: bool,
    ) -> None:
        """Repaint tree / detail / lint to reflect an applied config change."""
        if display_changed:
            self.search_rows = data.search_rows(self.tax, self.lang)
        if display_changed or plugins_changed:
            # A plugin toggle flips the lint-feature flags — rebuild so icon colours
            # (and their absence) repaint instead of lingering from the last build.
            self._rebuild_tree()
        if "semanticlint" in result:  # thresholds / feature toggles changed → re-lint
            self._invalidate_lint()
            self._refresh_lint_async()
        elif display_changed or langs_changed or plugins_changed or entity_meta_changed:
            self._show(self._detail_uri)  # reflect configured-language rows / lint UI / coverage

    def _apply_plugins(self, result: dict) -> bool:
        """Persist plugin enable-states from the config result. Returns True when any
        changed — a signal to invalidate the lint cache and re-render the detail (lint
        rows appear/disappear)."""
        from ster import plugins

        changed = False
        for plugin_id, enabled in result.get("plugins", {}).items():
            if plugins.is_enabled(plugin_id) != bool(enabled):
                plugins.set_enabled(plugin_id, bool(enabled))
                changed = True
        if changed:
            self._invalidate_lint()  # force a recompute with the new active state
        return changed

    def _apply_theme(self, result: dict) -> None:
        """Live-preview the chosen theme when it is one we know."""
        theme = result.get("theme")
        if theme and theme in self.available_themes:
            self.theme = theme

    def _entity_meta_changed(self, result: dict) -> bool:
        """True when the config result carries an entity-metadata catalog that differs
        from the current one — a signal to refresh the overview's coverage rows."""
        return "entity_metadata_props" in result and (
            list(result["entity_metadata_props"]) != self.entity_metadata_props
        )

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
            self.metadata_props = list(result["metadata_props"])
            save_metadata_props(self.metadata_props)
        if "entity_metadata_props" in result:  # the entity-metadata catalog (global)
            self.entity_metadata_props = list(result["entity_metadata_props"])
            save_entity_metadata_props(self.entity_metadata_props)
        if "semanticlint" in result:  # the plugin's global quality config
            from ster.plugins.semanticlint import config

            config.save_config(result["semanticlint"])
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
        yield Static("", id="lang-indicator")  # bottom-right status: selected language
        yield Static("", id="busy")  # bottom-left status: Saving… / Checking… spinner
        yield ContextMenu(id="ctx-menu")  # hidden overlay; shown on right-click

    def on_mount(self) -> None:
        self.title = f"ster ontology browser - {self.source}"
        self.sub_title = ""
        for tree in self.query(Tree):
            tree.show_root = False
            tree.guide_depth = 3
        self._sync_lint_features()  # cache icon-colour on/off before the first build
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
        self.call_after_refresh(self._initial_show)
        self._update_lang_indicator()

    def _initial_show(self) -> None:
        """First paint. Opening straight into the query workspace skips the browser's
        overview + lint + tree-recolour (none of it is needed to run SPARQL) — that runs
        lazily the first time the browser is actually shown, so the query screen appears
        without waiting on a full semanticlint pass over a large ontology."""
        if self._open_query_on_start:  # home-menu "Query" opens straight into the query screen
            self.action_open_query()
            return
        self._ensure_browser_ready()

    def _ensure_browser_ready(self) -> None:
        """Show the overview (which computes the first lint result), then recolour the tree.
        Idempotent — the browser's first paint, deferred when we open into the query screen."""
        if self._browser_ready:
            return
        self._browser_ready = True
        self._show(detail.OVERVIEW_URI)
        if self._lint_icons_on:
            self._rebuild_tree()

    def action_open_query(self) -> None:
        """Open the SPARQL query workspace over the live taxonomy. On close, make sure the
        browser behind it is painted (it may have been deferred when we opened into query)."""
        from .query_screen import QueryScreen

        self.push_screen(QueryScreen(self.tax), lambda _result: self._ensure_browser_ready())

    def _update_lang_indicator(self) -> None:
        """Refresh the bottom-right status with the current display language."""
        indicators = self.query("#lang-indicator")
        if indicators:
            indicators.first(Static).update(f"selected language: {self.lang}")

    # ── tree building ─────────────────────────────────────────────────────────

    def _index(self, uri: str, node: TreeNode) -> None:
        self._uri_nodes.setdefault(uri, node)

    def _node_icon(self, uri: str, kind: str) -> str:
        """The node's leading glyph, coloured red/orange/green by the worst semanticlint
        severity affecting the entity — only when the plugin's icon feature is on, else
        plain. The on/off flag is cached per tree build (not read per node)."""
        icon = data.ICON.get(kind, "")
        if not self._lint_icons_on:
            return icon
        from ster.tui.plugins.semanticlint_ui import hooks

        colour = hooks.icon_colour(self._lint_index.get(uri))
        return f"[{colour}]{icon}[/{colour}]"

    def _sync_lint_features(self) -> None:
        """Refresh cached lint-feature flags before a tree build (one config read,
        rather than one per node)."""
        from ster.plugins import semanticlint
        from ster.plugins.semanticlint import config

        active = semanticlint.is_active()
        self._lint_icons_on = active and config.feature_enabled("icons")
        self._lint_detail_on = active and config.feature_enabled("detail")
        self._lint_quality_on = active and config.feature_enabled("quality_block")
        # The overview's Quality & Coverage group carries non-lint coverage too, so it
        # stays visible when the plugin is off (unreachable toggle → default on); the
        # feature only hides it while the plugin is active and the user turns it off.
        self._overview_quality_on = (not active) or config.feature_enabled("quality_block")

    def _entity_detail_fields(self, uri: str | None) -> list[DetailField]:
        """The plugin's extra detail rows for entity *uri*: a subtree quality summary
        (quality_block feature) followed by the per-entity issue list (detail feature),
        both inserted after Identity. Empty when neither feature applies."""
        return self._entity_quality_fields(uri) + self._entity_issue_fields(uri)

    def _entity_issue_fields(self, uri: str | None) -> list[DetailField]:
        """The 'Quality issues' detail rows for entity *uri* (empty unless the plugin's
        detail feature is on and the entity has issues)."""
        if not (self._lint_detail_on and uri and self._lint_cache):
            return []
        from ster.plugins.semanticlint import report
        from ster.tui.plugins.semanticlint_ui import hooks

        issues = report.issues_by_subject(self._lint_cache[1]).get(uri, [])
        return hooks.issue_fields(issues)

    def _entity_quality_fields(self, uri: str | None) -> list[DetailField]:
        """A subtree-scoped quality summary for a class / concept / individual / property
        (empty for the overview, or when the quality_block feature is off)."""
        if not (self._lint_quality_on and uri and self._lint_cache):
            return []
        if uri in (detail.OVERVIEW_URI, detail.TAXONOMY_URI):
            return []  # the overview already carries the global Errors/Warnings rows
        from ster.plugins.semanticlint import report
        from ster.tui.plugins.semanticlint_ui import hooks

        by_subject = report.issues_by_subject(self._lint_cache[1])
        counts: dict[str, int] = {}
        for entity_uri in self._subtree_uris(uri):
            for issue in by_subject.get(entity_uri, []):
                counts[issue["severity"]] = counts.get(issue["severity"], 0) + 1
        return hooks.quality_summary_fields(counts, title="Issues")

    def _subtree_uris(self, uri: str) -> set[str]:
        """Every entity URI in *uri*'s subtree (class / concept hierarchy), else {uri}."""
        from ster.nav.logic import _subtree_class_uris, _subtree_concept_uris

        if uri in self.tax.owl_classes:
            return set(_subtree_class_uris(self.tax, uri))
        if uri in self.tax.concepts:
            return set(_subtree_concept_uris(self.tax, uri))
        return {uri}

    def _leaf(self, parent: TreeNode, uri: str, kind: str, suffix: str = "") -> TreeNode:
        text = (
            f"{self._node_icon(uri, kind)} {data.node_name(self.tax, uri, self.lang, kind)}{suffix}"
        )
        node = parent.add_leaf(text, data=uri)
        self._index(uri, node)
        return node

    def _add_class(self, parent: TreeNode, uri: str) -> None:
        label = data.label_of(self.tax, uri, self.lang)
        node = parent.add(f"{self._node_icon(uri, 'class')} {label}", data=uri)
        self._index(uri, node)
        for sub in data.subclasses(self.tax, uri, self.lang):
            self._add_class(node, sub)
        for ind in data.individuals_of(self.tax, uri, self.lang):
            self._leaf(node, ind, "individual")

    def _add_concept(self, parent: TreeNode, uri: str) -> None:
        label = data.label_of(self.tax, uri, self.lang)
        node = parent.add(f"{self._node_icon(uri, 'concept')} {label}", data=uri)
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
        self._index(detail.OVERVIEW_URI, ont_sec)  # focusable (e.g. after deleting a root class)
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
        self._index(detail.TAXONOMY_URI, tax_sec)  # focusable (e.g. after deleting a scheme)
        for s_uri in data.scheme_roots(tax, self.lang):
            sec = tax_sec.add(
                f"{data.ICON['scheme']} {data.label_of(tax, s_uri, self.lang)}", data=s_uri
            )
            self._index(s_uri, sec)
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
        kind_by_title = {title: kind for kind, title in data.PROPERTY_CATEGORIES}
        for title, local, external in data.property_groups(tax, self.lang):
            label = (
                f"[orange1]{title}[/orange1]" if title == data.UNTYPED_PROPERTIES_TITLE else title
            )
            # Each typed header (Object / Datatype / Annotation) is right-clickable to add a
            # property of that kind (sentinel data); left-click / Enter still just expands it.
            kind = kind_by_title.get(title)
            sec = tree.root.add(label, data=self._prop_header_data(kind))
            # Index the section under a focus key so a deleted property can land on it.
            self._index(_prop_section_key(kind or "Property"), sec)
            for uri in local:
                self._leaf(sec, uri, "property")
            for uri in external:
                self._leaf(sec, uri, "property", suffix="  [dim](ext)[/dim]")
            sec.expand()
        self._strip_childless_arrows(tree.root)

    @staticmethod
    def _prop_header_data(kind: str | None) -> str | None:
        """The right-click 'add property' sentinel for a creatable header kind (Object /
        Datatype / Annotation), or None for the catch-all Untyped Properties group."""
        if kind is not None and kind in _CREATABLE_PROP_KINDS:
            return _add_prop_uri(kind)
        return None

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
        lint = self._ontology_lint()  # whole-file lint (cached); None when plugin inactive
        metadata = self._metadata_coverage() if is_overview else None
        view = self.query_one("#detail", DetailView)
        view.update_entity(
            self.tax,
            uri,
            self.lang,
            activity,
            (lint[0] if lint else None) if is_overview else None,  # counts only on the overview
            clangs,
            metadata,
            issue_fields=self._entity_detail_fields(uri),
            quality_block=self._overview_quality_on,
        )
        view.border_title = self._detail_title(uri)

    def _metadata_coverage(self) -> dict | None:
        """Ontology/entity metadata-completion percentages vs the configured catalogs."""
        from ster.metadata_coverage import overview_coverage

        return overview_coverage(self.tax, self.metadata_props, self.entity_metadata_props)

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
        """semanticlint result for the file (computed once per session, cached).

        ``None`` when the semanticlint plugin is disabled / not installed, so no lint
        colours, rows or modal appear — ster behaves as standard."""
        from ster.plugins import semanticlint

        if self._path is None or not semanticlint.is_active():
            return None
        if not self._lint_computed:
            self._set_lint(self._compute_lint())
        return self._lint_cache

    def _compute_lint(self) -> tuple[dict, list] | None:
        """Return the semanticlint result, from the md5+config disk cache when the file is
        unchanged, else compute (blocking, ~2 s on a large ontology) and cache it. ``None``
        on any failure — a lint error must never break the view."""
        path = self._path
        if path is None:
            return None
        try:
            # Imported inside the try: a present-but-broken semanticlint (import raises)
            # must degrade to "no lint", never crash the view — the import itself can
            # fail, not just the computation.
            from ster.plugins.semanticlint import config, lint_cache
            from ster.plugins.semanticlint.runner import lint_overview

            cfg_hash = lint_cache.config_hash(config.load_config())
            return lint_cache.get_or_compute(path, cfg_hash, compute=lambda: lint_overview(path))
        except Exception:  # noqa: BLE001
            return None

    def _set_lint(self, result: tuple[dict, list] | None) -> None:
        """Store a fresh lint result + rebuild the uri→worst-severity index."""
        from ster.plugins.semanticlint import report

        self._lint_cache = result
        self._lint_computed = True
        self._lint_index = report.worst_by_subject(result[1]) if result else {}

    #: seconds of edit inactivity before the (heavy) re-lint fires — comfortably longer
    #: than a large-file background save, so the file-based lint reads the fresh state.
    _LINT_DEBOUNCE = 1.5

    def _schedule_lint(self) -> None:
        """Debounce the heavy re-lint: recompute only after a lull, so a burst of edits
        triggers one lint pass instead of one per edit (each ~2 s on a large ontology)."""
        if self._lint_timer is not None:
            self._lint_timer.stop()
        self._lint_timer = self.set_timer(self._LINT_DEBOUNCE, self._refresh_lint_async)

    def _refresh_lint_async(self) -> None:
        """Recompute lint off the UI thread (when the plugin is active), then recolour
        the tree and refresh the open detail. No-op otherwise."""
        from ster.plugins import semanticlint

        if self._path is None or not semanticlint.is_active():
            self._set_lint(None)
            return
        self._begin_activity("lint", "Checking")  # spinner while the background check runs
        self.run_worker(
            self._lint_worker, thread=True, exclusive=True, group="lint", name="ster-lint"
        )

    def _lint_worker(self) -> None:
        result = self._compute_lint()
        self.call_from_thread(self._on_lint_ready, result)

    def _on_lint_ready(self, result: tuple[dict, list] | None) -> None:
        """Apply a background lint result on the UI thread: recolour + refresh.

        The debounced lint lands a second or two *after* an edit, when focus is back on a
        detail row. ``_show`` rebuilds (and so destroys) that row, which would drop focus to
        the tree — so we remember the focused row and restore it after the rebuild."""
        self._end_activity("lint")  # the background check finished → clear its spinner
        self._set_lint(result)
        focused = self.focused
        keep_key = focused.field.key if isinstance(focused, DetailRow) else None
        self._rebuild_tree()
        if self._detail_uri:
            # Re-reveal the current entity so the recolour rebuild doesn't collapse
            # ancestors / reset the cursor (without stealing focus from a detail row).
            self._reveal_in_tree(self._detail_uri, focus=False)
            self._show(self._detail_uri)
            if keep_key is not None:  # keep the cursor on the row the user was on
                self._pending_focus_key = keep_key
                self.call_after_refresh(self._restore_focus)

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
        kind = data.kind_of(self.tax, uri)
        type_label = _KIND_TITLE.get(kind)
        if type_label:
            label += f" ({type_label})"  # note the resource's type, e.g. 'Person (Class)'
        if edits.context_actions(kind):
            label += "  ⋯"  # a context menu is available
        return label

    # ── mutation pipeline ───────────────────────────────────────────────────────

    def _rebuild_tree(self) -> None:
        """Rebuild both panes (a full refresh — used on load and whenever a mutation could
        have touched either pane)."""
        self._rebuild_main_tree()
        self._rebuild_prop_tree()

    def _rebuild_main_tree(self) -> None:
        """Rebuild only the main pane (classes / individuals / schemes / concepts). Its
        ``_uri_nodes`` entries are dropped and re-added; the prop pane is left untouched."""
        self._sync_lint_features()
        main = self.query_one("#tree", Tree)
        self._uri_nodes = {u: n for u, n in self._uri_nodes.items() if n.tree is not main}
        main.root.remove_children()
        self._build_main_tree(main)

    def _rebuild_prop_tree(self) -> None:
        """Rebuild only the property pane, leaving the (large) main pane untouched — so a
        property edit doesn't pay to rebuild every class/individual node."""
        self._sync_lint_features()
        props = self.query_one("#prop-tree", Tree)
        self._uri_nodes = {u: n for u, n in self._uri_nodes.items() if n.tree is not props}
        props.root.remove_children()
        self._build_prop_tree(props)

    #: entity kinds that live in each pane — used to rebuild only the pane a mutation touched.
    _MAIN_KINDS = frozenset({"class", "individual", "scheme", "concept"})

    def _affected_panes(self, affected_uris: tuple[str, ...], select: str | None) -> set[str]:
        """Which tree pane(s) a mutation touched → subset of ``{"main", "prop"}``.

        Classifies each affected/selected URI by kind. Falls back to **both** panes whenever
        a URI can't be classified (a deleted URI is gone from the taxonomy → kind 'section';
        a rename cascade) — so the tree can never drift from the model on a wrong guess; the
        worst case is simply a full rebuild, exactly as before."""
        candidates = [u for u in (*affected_uris, select) if u]
        if not candidates:
            return {"main", "prop"}
        panes: set[str] = set()
        for uri in candidates:
            kind = data.kind_of(self.tax, uri)
            if kind == "property":
                panes.add("prop")
            elif kind in self._MAIN_KINDS:
                panes.add("main")
            else:  # unknown / deleted → can't tell which pane changed; rebuild both (safe)
                return {"main", "prop"}
        return panes

    def _rebuild_affected(self, affected_uris: tuple[str, ...], select: str | None) -> None:
        """Rebuild only the pane(s) a mutation touched (both when uncertain)."""
        panes = self._affected_panes(affected_uris, select)
        if "main" in panes:
            self._rebuild_main_tree()
        if "prop" in panes:
            self._rebuild_prop_tree()

    # ── busy indicator (Saving… / Checking…) ──────────────────────────────────
    _SPINNER = "⣾⣽⣻⢿⡿⣟⣯⣷"

    def _begin_activity(self, name: str, label: str) -> None:
        """Show a spinner + *label* (e.g. 'Saving') for a running background job *name*."""
        self._activities[name] = label
        self._refresh_busy()

    def _end_activity(self, name: str) -> None:
        """Clear a finished background job; hides the overlay when none remain."""
        if self._activities.pop(name, None) is not None:
            self._refresh_busy()

    def _refresh_busy(self) -> None:
        """Match the busy overlay + spinner timer to the set of running jobs."""
        try:
            widget = self.query_one("#busy", Static)
        except Exception:  # noqa: BLE001 — a job scheduled before the UI mounts
            return
        if not self._activities:
            widget.display = False
            widget.update("")
            if self._busy_timer is not None:
                self._busy_timer.stop()
                self._busy_timer = None
            return
        widget.display = True
        self._render_busy()
        if self._busy_timer is None:  # animate while off-thread work runs (UI thread is free)
            self._busy_timer = self.set_interval(0.1, self._render_busy)

    def _render_busy(self) -> None:
        """Paint the current spinner frame + every running job's label."""
        self._spinner_frame = (self._spinner_frame + 1) % len(self._SPINNER)
        labels = " · ".join(f"{lbl}…" for lbl in self._activities.values())
        self.query_one("#busy", Static).update(f"{self._SPINNER[self._spinner_frame]} {labels}")

    def _apply_command(
        self, command: object, select: str | None = None, *, focus_tree: bool = False
    ) -> None:
        """Execute *command* via TaxonomyService, then refresh tax + tree + detail.

        The tree highlight lands on the *resulting* entity: a freshly created one when
        *select* names it (reveal the mutation), otherwise the current entity — restored
        after the rebuild so it never jumps to the top. Focus stays in the detail pane;
        the tree cursor moves without stealing keyboard focus (unlike ``jump_to``).

        ``focus_tree`` instead lands keyboard focus on the entity's *tree* node — used when
        the edited row is being deleted, so the user is one Tab/arrow from the detail pane
        rather than stranded on a row that no longer exists.
        """
        if self._service is None or self._path is None:
            self.notify("Read-only session (no file loaded).", severity="warning")
            return
        result = self._service.execute(command, persist=False)  # type: ignore[arg-type]
        if not result.ok:
            self.notify(result.error or "Command failed.", severity="error")
            return
        # The service swapped a fresh authority taxonomy into the workspace.
        self.tax = self._workspace.taxonomies[self._path]
        self.search_rows = data.search_rows(self.tax, self.lang)
        self._invalidate_lint()  # the edit may fix/introduce issues
        self._rebuild_affected(result.affected_uris, select)  # rebuild only the touched pane(s)
        # A freshly created entity (select) is revealed; anything else keeps the
        # highlight on the current entity — following it if the edit renamed its URI.
        target = select if (select is not None and select in self._uri_nodes) else self._detail_uri
        if target is not None and target in self._uri_nodes:
            self._reveal_in_tree(target, focus=focus_tree)  # focus the tree node on delete
        self._show(target)
        if focus_tree:
            self._pending_focus_key = None  # the row is gone; we deliberately left the pane
        else:
            # The mutation rebuilt the detail rows, destroying the row that had focus —
            # restore it (next refresh) so the keyboard keeps working after a modal.
            self.call_after_refresh(self._restore_focus)
        self._schedule_save()  # persist off the UI thread → the window stays responsive
        self._schedule_lint()  # debounce: one lint after a lull, not one per edit

    def _schedule_save(self) -> None:
        """Persist the current authority to disk on a background worker (the slow part of
        an edit). Serialised by ``_save_lock``; a later edit's save supersedes an earlier."""
        if self._service is None or self._path is None:
            return
        self._save_dirty = True
        self._begin_activity("save", "Saving")  # spinner until the worker finishes
        self.run_worker(
            self._save_worker, thread=True, exclusive=True, group="ster-save", name="ster-save"
        )

    def _save_worker(self) -> None:
        from ster import store

        try:
            with self._save_lock:
                self._save_dirty = False  # cleared first: a concurrent edit re-marks it
                tax, path = self.tax, self._path
                if path is not None:
                    store.save(tax, path)
        finally:
            self.call_from_thread(self._end_activity, "save")  # clear the spinner on the UI thread

    def _flush_save(self) -> None:
        """Synchronously persist any unsaved edit — called on quit so a backgrounded save
        can never be lost."""
        from ster import store

        with self._save_lock:
            if self._save_dirty and self._path is not None:
                store.save(self.tax, self._path)
                self._save_dirty = False

    def on_unmount(self) -> None:
        """Flush a pending background save when the app closes."""
        self._flush_save()

    def _invalidate_lint(self) -> None:
        """Drop the cached lint so the next access (or the async worker) recomputes."""
        self._lint_cache = None
        self._lint_computed = False
        self._lint_index = {}

    def _restore_focus(self) -> None:
        """Land focus back on the row that was being edited after a mutation rebuilt the
        panes (so the cursor stays put), falling back to the first row, then the tree.

        A mutation destroys the old row widgets, so we re-find by field key. Value rows
        embed the value in their key (``…::<value>``); when an edit changes the value the
        key changes too, so we also try the stable stem before that separator."""
        rows = [r for r in self.query("#detail DetailRow") if r.can_focus]
        if not rows:
            self.query_one("#tree", Tree).focus()
            return
        key, self._pending_focus_key = self._pending_focus_key, None
        target = self._row_for_focus_key(rows, key) if key else None
        (target or rows[0]).focus()

    @staticmethod
    def _row_for_focus_key(rows: list, key: str):  # type: ignore[no-untyped-def]
        """The row matching *key* exactly, else one sharing its stable ``…::``-stem."""
        exact = next((r for r in rows if r.field.key == key), None)
        if exact is not None:
            return exact
        stem = key.rsplit("::", 1)[0] + "::" if "::" in key else None
        return next((r for r in rows if stem and r.field.key.startswith(stem)), None)

    def _refocus_edited_row(self) -> None:
        """Focus back the row that was being edited after a *cancel* — value edits open
        from the row's menu (which held focus), so Textual can't restore the row itself."""
        rows = [r for r in self.query("#detail DetailRow") if r.can_focus]
        key, self._pending_focus_key = self._pending_focus_key, None
        target = self._row_for_focus_key(rows, key) if (rows and key) else None
        if target is not None:
            target.focus()

    def on_detail_row_edit_requested(self, message: DetailRow.EditRequested) -> None:
        """An edit-only value row asked to be edited → open the modal → command."""
        self._pending_focus_key = message.field.key  # refocus this row after the edit
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
                self._pending_focus_key = None
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
            self.push_screen(
                EditModal(
                    field.display,
                    field.value,
                    multiline=edits.is_long_text(field),
                    autolink=edits.is_prose(field),
                ),
                _on_submit,
            )

    def on_detail_row_menu_requested(self, message: DetailRow.MenuRequested) -> None:
        """A value row with both edit and delete was activated → Edit/Delete submenu."""
        self._row_menu_field = message.field
        self._row_menu_delete = message.delete_field
        self._row_menu_origin = self.focused  # the row, before the menu grabs focus
        self._pending_focus_key = message.field.key  # refocus this row after edit/delete
        items = [("✎ Edit", "row_edit"), ("⊘ Delete", "row_delete")]
        self.query_one("#ctx-menu", ContextMenu).show(message.field.display, items, message.anchor)

    def _apply_row_delete(self, delete_field: DetailField, *, label: str | None = None) -> None:
        """Confirm, then run the paired removal command for a row's Delete submenu choice.

        On confirm the row is gone, so focus lands on the entity's tree node (``focus_tree``)
        — one Tab/arrow back to the detail pane; on cancel it stays on the edited row."""
        uri, path = self._detail_uri, self._path
        if self._service is None or uri is None or path is None:
            self.notify("Read-only session (no file loaded).", severity="warning")
            return
        command = edits.direct_command(delete_field, uri, path)
        if command is None:
            return
        prompt = f"Delete «{label or delete_field.display}»?"

        def _on_choice(choice: str | None) -> None:
            if choice is None:
                self._refocus_edited_row()  # cancel → stay on the edited row
                return
            self._apply_command(command, focus_tree=True)

        self.push_screen(ChoiceModal(prompt, [("Delete", "ok")], danger=True), _on_choice)

    def on_detail_row_action_requested(self, message: DetailRow.ActionRequested) -> None:
        """An action row was activated → run it (shared with the right-click menu)."""
        self._pending_focus_key = message.field.key  # refocus this row after the action
        self._run_field_action(message.field)

    #: (uri, path) entity actions that open a dedicated flow — dispatched by name so
    #: adding one is a table row, not another branch in _run_field_action.
    _ENTITY_ACTION_HANDLERS = {
        "edit_class": "_open_class_edit",  # full class modal (URI + labels + comments)
        "edit_individual": "_open_individual_edit",  # full individual modal
        "enforce_shacl": "_enforce_shacl",  # write a mandatory SHACL rule, then re-lint
        "unenforce_shacl": "_unenforce_shacl",  # remove the property's SHACL rule
    }

    def _run_field_action(self, field: DetailField) -> None:
        """Dispatch an action *field*: graph view, meta-driven removal, or a flow."""
        action = field.meta.get("action", "")
        if self._run_view_action(action, field):  # read-only views need no service
            return
        uri, path = self._detail_uri, self._path
        if self._service is None or uri is None or path is None:
            self.notify("Read-only session (no file loaded).", severity="warning")
            return
        if action == "edit_property":  # the field names the property (not the shown class)
            self._open_property_edit(field.meta.get("uri", ""), path)
            return
        handler = self._ENTITY_ACTION_HANDLERS.get(action)
        if handler is not None:
            getattr(self, handler)(uri, path)
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

    def _run_view_action(self, action: str, field: DetailField) -> bool:
        """Handle read-only view actions (graph, lint) that need no service. Returns
        True when *action* was one of them (and has been handled)."""
        if action in ("view_ontology_graph", "view_focused_graph"):
            self._open_graph(action, field)
            return True
        if action == "view_lint":
            self._open_lint(field.meta.get("lint_severity"))
            return True
        return False

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
        prop_type = _parse_add_prop(uri)
        if prop_type is not None:  # a property-tree header → "＋ Add <kind> property"
            title, add_label, action, _modal = _PROP_MENU[prop_type]
            self.query_one("#ctx-menu", ContextMenu).show(title, [(add_label, action)], anchor)
            return
        if uri == detail.OVERVIEW_URI:  # the Ontology section → "＋ Add class"
            self._show_section_menu(uri, "Ontology", ("＋ Add class", "create_owl_class"), anchor)
            return
        if uri == detail.TAXONOMY_URI:  # the Taxonomy section → "＋ Add concept scheme"
            self._show_section_menu(
                uri, "Taxonomy", ("＋ Add concept scheme", "add_scheme"), anchor
            )
            return
        items = self._filter_plugin_actions(edits.context_actions(data.kind_of(self.tax, uri)))
        items = self._filter_class_actions(uri, items)
        if not items:
            return
        self._show(uri)  # select it, so the actions target this entity
        label = data.label_of(self.tax, uri, self.lang)
        self.query_one("#ctx-menu", ContextMenu).show(label, items, anchor)

    def _show_section_menu(
        self, uri: str, title: str, item: tuple[str, str], anchor: tuple[int, int] | None
    ) -> None:
        """Select a section node (Ontology / Taxonomy) so its create action has the right
        target, then pop its single-item context menu."""
        self._show(uri)
        self.query_one("#ctx-menu", ContextMenu).show(title, [item], anchor)

    #: context-menu actions that belong to an opt-in plugin feature (SHACL enforce).
    _ENFORCE_ACTIONS = frozenset({"enforce_shacl", "unenforce_shacl"})

    def _filter_plugin_actions(self, items: list[tuple[str, str]]) -> list[tuple[str, str]]:
        """Hide plugin-gated actions when their feature is off — the SHACL enforce/remove
        items only appear when semanticlint's ``enforce`` feature is active."""
        from ster.plugins import semanticlint

        if semanticlint.enforce_active():
            return items
        return [(lbl, act) for lbl, act in items if act not in self._ENFORCE_ACTIONS]

    def _filter_class_actions(
        self, uri: str, items: list[tuple[str, str]]
    ) -> list[tuple[str, str]]:
        """Hide '↑ Add superclass' on non-top-level classes — only a root class (no
        rdfs:subClassOf parent) may gain a superclass from the menu."""
        cls = self.tax.owl_classes.get(uri)
        if cls is None or not cls.sub_class_of:  # not a class, or a top-level class → keep all
            return items
        return [(lbl, act) for lbl, act in items if act != "link_superclass"]

    def on_context_menu_chosen(self, message: ContextMenu.Chosen) -> None:
        """A context-menu action was picked → run it against the selected entity."""
        # Detail-row Edit/Delete submenu (takes priority over the tree-node menu).
        if message.action == "row_edit" and self._row_menu_field is not None:
            field, self._row_menu_field = self._row_menu_field, None
            self._row_menu_delete = None
            # Value rows carry an edit *action* (a picker for object values / class
            # membership, a text modal for literals) — dispatch it; plain editable rows
            # (labels, comments, URI) open the generic edit modal.
            if field.meta.get("action"):
                self._run_field_action(field)
            else:
                self._open_edit_modal(field, origin=self._row_menu_origin)
            return
        if message.action == "row_delete" and self._row_menu_delete is not None:
            delete_field, self._row_menu_delete = self._row_menu_delete, None
            menu_field, self._row_menu_field = self._row_menu_field, None
            label = menu_field.display if menu_field is not None else delete_field.display
            self._apply_row_delete(delete_field, label=label)
            return

        prop_type = _PROP_CREATE_ACTIONS.get(message.action)
        if prop_type is not None:  # "＋ Add <kind> property" from a property-tree header
            self._open_property_create(prop_type)
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
                    # select=value so the highlight + detail follow the entity to its new
                    # URI (the old one is gone, so restoring _detail_uri would lose it).
                    self._apply_command(command, select=value)

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

    def _run_or_warn(self, command: object | None, select: str | None = None) -> None:
        """Apply *command*, or warn if the dispatch produced nothing."""
        if command is None:
            self.notify("This action isn't wired up yet.", severity="warning")
            return
        self._apply_command(command, select=select)

    _CLASS_CREATE_ACTIONS = frozenset({"create_owl_class", "new_subclass"})

    def _open_input(self, field: DetailField, uri: str, path: Path) -> None:
        """Collect a single text/URI value in a modal, then run its action command."""
        action = field.meta.get("action", "")
        # Creating a class / individual opens its full modal (URI + labels + …).
        if action in self._CLASS_CREATE_ACTIONS:
            self._open_class_create(action, uri, path)
            return
        if action == "add_individual":
            self._open_individual_create(uri, path)
            return
        prompt, prefill_kind = edits.INPUT_ACTIONS[action]
        # For a URI-minting action the created entity's URI *is* the typed value,
        # so navigate to it once the tree rebuilds (make the create visible).
        mints = prefill_kind == "base_uri"

        def _on_submit(value: str | None) -> None:
            if value:
                self._run_or_warn(
                    edits.action_command(action, uri, path, value, self.lang),
                    select=value if mints else None,
                )

        # A new URI is minted fragment-only under the locked ontology/scheme base.
        if mints:
            base = uri_edit.mint_base(self.tax, action, uri)
            self.push_screen(UriModal(prompt, base), _on_submit)
        else:
            self.push_screen(
                EditModal(
                    prompt, "", multiline=edits.is_long_text(field), autolink=edits.is_prose(field)
                ),
                _on_submit,
            )

    def _class_langs(self) -> list[str]:
        return self.configured_langs or [self.lang]

    def _open_property_create(self, prop_type: str) -> None:
        """Open the create modal for a property-tree header. Object properties get the full
        modal (domain + range pickers); datatype / annotation get the lightweight one."""
        if prop_type == "ObjectProperty":
            self._open_object_property_create()
        else:
            self._open_simple_property_create(prop_type)

    def _open_simple_property_create(self, prop_type: str) -> None:
        """Datatype / annotation properties → a lightweight modal (URI + labels/comments;
        no domain/range — add those afterwards via the property's own menu) → create command."""
        from ster.core.commands import OwlCreateProperty

        from .entity_form import EntityFormModal

        path = self._path
        if self._service is None or path is None:
            self.notify("Read-only session (no file loaded).", severity="warning")
            return
        base = uri_edit.mint_base(self.tax, "create_owl_property", detail.OVERVIEW_URI)
        modal_title = _PROP_MENU[prop_type][3]

        def _on_submit(result: dict | None) -> None:
            if result:
                self._apply_command(
                    OwlCreateProperty(
                        path,
                        result["uri"],
                        tuple(result["labels"].items()),
                        tuple(result["comments"].items()),
                        prop_type=prop_type,
                    ),
                    select=result["uri"],
                )

        self.push_screen(
            EntityFormModal(prefix=base, langs=self._class_langs(), title=modal_title),
            _on_submit,
        )

    def _open_object_property_create(self) -> None:
        """Right-click on the Object Properties header → full add modal (URI + labels /
        comments per configured language + domain + range) → create command."""
        from ster.core.commands import OwlCreateProperty

        from .object_property_modal import ObjectPropertyModal

        path = self._path
        if self._service is None or path is None:
            self.notify("Read-only session (no file loaded).", severity="warning")
            return
        base = uri_edit.mint_base(self.tax, "create_owl_property", detail.OVERVIEW_URI)
        classes = sorted(
            ((data.label_of(self.tax, u, self.lang), u) for u in self.tax.owl_classes),
            key=lambda t: t[0].lower(),
        )

        def _on_submit(result: dict | None) -> None:
            if result:
                self._apply_command(
                    OwlCreateProperty(
                        path,
                        result["uri"],
                        tuple(result["labels"].items()),
                        tuple(result["comments"].items()),
                        result["domain"],
                        result["range"],
                    ),
                    select=result["uri"],
                )

        self.push_screen(
            ObjectPropertyModal(prefix=base, langs=self._class_langs(), classes=classes),
            _on_submit,
        )

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
                    ),
                    select=result["uri"],
                )

        self.push_screen(ClassModal(prefix=base, langs=self._class_langs()), _on_submit)

    # ── add / edit individual (full modal, mirroring the class flow) ────────────

    @staticmethod
    def _split_values(values: dict) -> tuple[tuple, tuple]:  # type: ignore[type-arg]
        """Split the modal's ``{prop: (kind, value)}`` into (object, literal) pairs,
        dropping empties."""
        obj: list[tuple[str, str]] = []
        lit: list[tuple[str, str]] = []
        for prop_uri, (kind, value) in values.items():
            if value:
                (obj if kind == "object" else lit).append((prop_uri, value))
        return tuple(obj), tuple(lit)

    def _individual_candidates(self, range_uri: str | None) -> list[tuple[str, str]]:
        """Existing individuals typed as *range_uri* (or a subclass) — the object-property
        dropdown options, sorted by label."""
        if not range_uri or range_uri not in self.tax.owl_classes:
            return []
        subtree = self._subtree_uris(range_uri)
        out = [
            (data.label_of(self.tax, u, self.lang), u)
            for u, ind in self.tax.owl_individuals.items()
            if subtree & set(ind.types)
        ]
        return sorted(out, key=lambda t: t[0].lower())

    def _individual_prop_fields(self, class_uri: str) -> list:
        """Build the modal's property rows from the class's direct + inherited properties."""
        from ster.nav.logic import suggested_properties

        from .individual_modal import PropField

        fields = []
        for sp in suggested_properties(self.tax, class_uri, self.lang):
            label = sp.label
            if sp.inherited_from:
                label += f"  (from {data.label_of(self.tax, sp.inherited_from, self.lang)})"
            candidates = self._individual_candidates(sp.range_uri) if sp.kind == "object" else []
            fields.append(
                PropField(
                    prop_uri=sp.prop_uri, label=label, kind=sp.kind, candidates=tuple(candidates)
                )
            )
        return fields

    def _open_individual_create(self, class_uri: str, path: Path) -> None:
        """Open the full individual modal to create an instance of *class_uri*."""
        from ster.core.commands import OwlCreateIndividualFull

        from .individual_modal import IndividualModal

        base = uri_edit.mint_base(self.tax, "add_individual", class_uri)

        def _on_submit(result: dict | None) -> None:
            if result:
                obj_values, lit_values = self._split_values(result["values"])
                self._apply_command(
                    OwlCreateIndividualFull(
                        path,
                        result["uri"],
                        class_uri,
                        tuple(result["labels"].items()),
                        tuple(result["comments"].items()),
                        obj_values,
                        lit_values,
                    ),
                    select=result["uri"],
                )

        self.push_screen(
            IndividualModal(
                prefix=base,
                langs=self._class_langs(),
                type_label=data.label_of(self.tax, class_uri, self.lang),
                prop_fields=self._individual_prop_fields(class_uri),
            ),
            _on_submit,
        )

    def _open_individual_edit(self, uri: str, path: Path) -> None:
        """Open the full individual modal to edit an existing individual (URI / labels /
        comments). Types and property values stay managed via the per-row actions."""
        from ster.core.commands import OwlSaveIndividual

        from .individual_modal import IndividualModal

        ind = self.tax.owl_individuals.get(uri)
        if ind is None:
            return
        prefix, fragment = uri_edit.split_namespace(uri)
        labels = {lbl.lang: lbl.value for lbl in ind.labels}
        comments = {c.lang: c.value for c in ind.comments}
        type_label = ", ".join(data.label_of(self.tax, t, self.lang) for t in ind.types)

        def _on_submit(result: dict | None) -> None:
            if result:
                self._apply_command(
                    OwlSaveIndividual(
                        path,
                        uri,
                        result["uri"],
                        tuple(result["labels"].items()),
                        tuple(result["comments"].items()),
                    ),
                    select=result["uri"],
                )

        self.push_screen(
            IndividualModal(
                prefix=prefix,
                fragment=fragment,
                langs=self._class_langs(),
                type_label=type_label,
                labels=labels,
                comments=comments,
                title="Edit individual",
            ),
            _on_submit,
        )

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
                    ),
                    select=result["uri"],  # keep the highlight on the (possibly renamed) class
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

    def _open_property_edit(self, prop_uri: str, path: Path) -> None:
        """Open the edit modal for a property (URI + labels/comments per language) → save.
        Its domain / range are preserved (edited via the property context menu)."""
        from ster.core.commands import OwlSaveProperty

        from .property_edit_modal import PropertyEditModal

        prop = self.tax.owl_properties.get(prop_uri)
        if prop is None:
            return
        prefix, fragment = uri_edit.split_namespace(prop_uri)
        labels = {lbl.lang: lbl.value for lbl in prop.labels}
        comments = {c.lang: c.value for c in prop.comments}
        domains, ranges = tuple(prop.domains), tuple(prop.ranges)  # preserved as-is

        def _on_submit(result: dict | None) -> None:
            if result:
                self._apply_command(
                    OwlSaveProperty(
                        path,
                        prop_uri,
                        result["uri"],
                        tuple(result["labels"].items()),
                        tuple(result["comments"].items()),
                        domains,
                        ranges,
                    ),
                    select=result["uri"],  # highlight follows the (possibly renamed) property
                )

        self.push_screen(
            PropertyEditModal(
                prefix=prefix,
                fragment=fragment,
                langs=self._class_langs(),
                labels=labels,
                comments=comments,
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
            else:
                self._refocus_edited_row()  # cancel → stay on the edited row

        # base_uri-kind meta inputs (e.g. add_class_property) mint a new URI fragment-only.
        if prefill_key == "base_uri":
            base = uri_edit.mint_base(self.tax, action, uri)
            self.push_screen(UriModal(prompt, base), _on_submit)
            return

        self.push_screen(
            EditModal(
                prompt,
                field.meta.get(prefill_key, ""),
                multiline=edits.is_long_text(field),
                autolink=edits.is_prose(field),
            ),
            _on_submit,
        )

    def _confirm_delete(self, field: DetailField, uri: str, path: Path) -> None:
        """Ask for the delete mode, then run the delete and land the cursor on the deleted
        entity's parent (its super-class / broader / super-property / section / Ontology …)."""
        action = field.meta.get("action", "")
        prompt = f"Delete «{data.label_of(self.tax, uri, self.lang)}»?"

        def _on_choice(mode: str | None) -> None:
            if mode is None:
                return
            target = self._delete_focus_target(uri)  # capture before the tree is rebuilt
            self._run_or_warn(edits.delete_command(action, uri, path, mode))
            self._focus_after_delete(target)

        self.push_screen(ChoiceModal(prompt, edits.DELETE_CHOICES[action], danger=True), _on_choice)

    def _delete_focus_target(self, uri: str) -> str | None:
        """The tree node to focus after *uri* is deleted: its parent in the hierarchy. The
        property tree is flat, so a sub-property points at its parent property and a
        top-level property at its section; everything else uses its tree parent (which is
        the super-class / broader concept / scheme / Ontology / Taxonomy node)."""
        prop = self.tax.owl_properties.get(uri)
        if prop is not None:
            for parent_prop in prop.sub_property_of:  # a sub-property → its parent property
                if parent_prop in self._uri_nodes:
                    return parent_prop
            return _prop_section_key(prop.prop_type)  # top-level → its section
        node = self._uri_nodes.get(uri)
        parent = node.parent if node is not None else None
        return parent.data if parent is not None else None

    def _focus_after_delete(self, target: str | None) -> None:
        """Move the cursor onto *target* (the deleted entity's parent), keeping it expanded so
        the former-sibling list stays unfolded; clear the pane when there is no parent."""
        node = self._uri_nodes.get(target) if target else None
        if node is None:
            self._show(None)
            return
        node.expand()  # keep the (former sibling) list unfolded — e.g. a class's individuals
        self._reveal_in_tree(target, focus=True)  # type: ignore[arg-type]
        self._show(target)

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
            else:
                self._refocus_edited_row()  # cancel → stay on the edited row

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

        self.push_screen(EditModal("Literal value", "", multiline=True), _on_literal)

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
        # Property-tree headers ("Object/Datatype/Annotation Properties") carry an add
        # sentinel and have no detail panel — clear the pane so the placeholder shows.
        if uri and _parse_add_prop(uri) is not None:
            self._show(None)
            return
        if uri == self._detail_uri:
            # Re-highlighting the entity already shown (e.g. a programmatic cursor move
            # after a mutation) must not rebuild the detail — that would drop the focus
            # _restore_focus just placed on a row. The explicit _show already refreshed it.
            return
        self._show(uri)

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

    def action_help(self) -> None:
        """Open the keys-and-actions help overlay."""
        self.push_screen(HelpScreen())

    def _open_graph(self, action: str, field: DetailField) -> None:
        """Detail-pane / context-menu graph action → the shared graph opener."""
        if action == "view_focused_graph":
            target = field.meta.get("uri") or self._detail_uri
            if not target:
                self.notify("No entity to focus the graph on.", severity="warning")
                return
            self._show_graph(target)
        else:
            self._show_graph(None)

    def action_open_graph(self) -> None:
        """The 'g' shortcut: open (or update) the graph from the tree selection —
        focused on the selected OWL class/individual, else the whole-ontology graph."""
        self._show_graph(self._graph_focus_target())

    def _graph_focus_target(self) -> str | None:
        """The entity to centre the graph on for 'g': the selected class or individual,
        else None (overview, property, concept or nothing → the global graph)."""
        uri = self._detail_uri
        if uri and (uri in self.tax.owl_classes or uri in self.tax.owl_individuals):
            return uri
        return None

    def _show_graph(self, target: str | None) -> None:
        """Open (or update) the VOWL graph in the browser — focused on *target* when
        given, else the whole ontology.

        A view, not a mutation. When the live-server port is already held by a previous
        graph window/process, reclaim it (close that process) and open — no prompt, since
        re-opening the graph should simply replace the old window — see
        :meth:`_reclaim_port_and_open`.
        """
        from ster import viz_vowl

        if not viz_vowl.is_live_server():
            holder = viz_vowl.port_holder()
            if holder is not None:
                self._reclaim_port_and_open(holder, target)
                return
        self._open_graph_now(target)

    def _open_graph_now(self, target: str | None) -> None:
        """Open the graph browser tab now (the live server when the port is free, else the
        static offline snapshot), reporting the URL or any failure."""
        from ster import viz_vowl

        try:
            if target is not None:
                url = viz_vowl.open_focused_in_browser(self.tax, target, self._path)
            else:
                url = viz_vowl.open_in_browser(self.tax, self._path)
            self.notify(f"Graph opened in your browser — {url}")
        except Exception as exc:  # surfacing beats crashing the UI for a view action
            self.notify(f"Couldn't open the graph: {exc}", severity="error")

    def _reclaim_port_and_open(self, holder: tuple[int, str], target: str | None) -> None:
        """A previous graph window/process holds the live-server port — close it, then
        open the graph. No prompt: re-opening the graph just replaces the old window. If
        the process can't be closed, ``_open_graph_now`` still opens a read-only snapshot
        (the port is busy), so the view always appears — it never hangs on a modal."""
        from ster import viz_vowl

        pid, _desc = holder
        if viz_vowl.free_port(pid):
            self.notify(f"Closed the previous graph window (PID {pid}).")
        else:
            self.notify(
                f"Couldn't close the previous graph process (PID {pid}) — "
                "opening a read-only snapshot instead.",
                severity="warning",
            )
        self._open_graph_now(target)

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

    def _enforce_shacl(self, prop_uri: str, path: Path) -> None:
        """Write a SHACL rule making *prop_uri* mandatory on each of its domain classes
        into the sibling ``<stem>.shapes.ttl`` (idempotent), then refresh the lint so the
        rule is enforced live. Warns when the property has no domain to attach it to."""
        import datetime

        from ster.plugins.semanticlint import shapes_author as shacl

        prop = self.tax.owl_properties.get(prop_uri)
        if prop is None:
            self.notify("Not an OWL property.", severity="warning")
            return
        if not prop.domains:
            self.notify(
                "This property has no domain — nothing to make it mandatory on.",
                severity="warning",
            )
            return
        prop_label = prop.label(self.lang) or prop.local_name
        today = datetime.date.today().isoformat()
        rules = [
            shacl.mandatory_property_rule(
                dom,
                prop_uri,
                target_label=data.label_of(self.tax, dom, self.lang),
                prop_label=prop_label,
                date=today,
            )
            for dom in prop.domains
        ]
        written = shacl.append_rules(shacl.shapes_path_for(path), rules)
        if not written:
            self.notify(f"“{prop_label}” is already enforced.")
            return
        self.notify(f"Enforced “{prop_label}” as mandatory — {len(written)} SHACL rule(s).")
        self._invalidate_lint()
        self._refresh_lint_async()  # the new rule takes effect on the next lint pass

    def _unenforce_shacl(self, prop_uri: str, path: Path) -> None:
        """Remove the SHACL rule(s) that make *prop_uri* mandatory (one per domain) from
        the sibling ``<stem>.shapes.ttl``, then refresh the lint."""
        from ster.plugins.semanticlint import shapes_author as shacl

        prop = self.tax.owl_properties.get(prop_uri)
        if prop is None:
            self.notify("Not an OWL property.", severity="warning")
            return
        iris = [shacl.shape_iri(dom, prop_uri) for dom in prop.domains]
        removed = shacl.remove_rules(shacl.shapes_path_for(path), iris)
        prop_label = prop.label(self.lang) or prop.local_name
        if not removed:
            self.notify(f"No SHACL rule to remove for “{prop_label}”.")
            return
        self.notify(f"Removed the SHACL rule for “{prop_label}” — {len(removed)} rule(s).")
        self._invalidate_lint()
        self._refresh_lint_async()

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
