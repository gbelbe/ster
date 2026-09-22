"""The Textual ontology browser & editor app.

Left: a ``Tree`` of Classes (with their individuals nested) / Properties / SKOS
schemes. Right: a progressive-disclosure detail panel. ``/`` (or ctrl+p) opens a
fuzzy command-palette search that jumps to any class / individual / property.

Editing routes through ``TaxonomyService`` (the command/service layer the curses
viewer also uses): activate a detail row (Enter) to edit a value or run an
action; every mutation is validated and written back to the file.

## Package layout — the mixin-composition pattern

``OntologyApp`` is one stateful Textual ``App`` with ~200 methods, too large for
one file but not a natural fit for the module-level-functions split used by
``ster.cli``/``ster.nav.logic``/``ster.viz_vowl`` (see
``docs/architecture/module-layout.md``): it is a single class, not a bag of
free functions. Instead it is split into **mixin classes**, one per business
domain (lifecycle, config, tree building, panels, detail rendering, lint,
rebuild, busy/save, problems, row actions, context menu, editing modals,
ontology identity, tree events, misc actions, source pane, graph view, SHACL,
working file), composed
into the final class right here:

    class OntologyApp(_LifecycleMixin, _ConfigMixin, _TreeBuildMixin, _PanelsMixin, _DetailMixin, _LintMixin, _RebuildMixin, _BusySaveMixin, _ProblemsMixin, _RowActionsMixin, _ContextMenuMixin, _EditingModalsMixin, _OntologyIdentityMixin, _TreeEventsMixin, _ActionsMixin, _SourceMixin, _GraphMixin, _ShaclMixin, _WorkingFileMixin, App):
        ...

This is safe and Textual-native: ``Widget.__init_subclass__`` and
``DOMNode.__init_subclass__`` (in ``textual/widget.py`` / ``textual/dom.py``)
both walk ``cls.__mro__`` to collect ``reactive()`` descriptors and to merge
``BINDINGS``/``CSS`` from *every* base class — so anything declared on a mixin
is picked up automatically by the composed class, no manual merging needed.

Each mixin is a plain class (not inheriting from anything — pure mixin), and
within a method body ``self.foo`` resolves through the normal Python MRO
regardless of which mixin defines ``foo``, so method bodies need no special
qualification to call across mixins. A method only needs a real import when it
references a module-level helper/class/constant that lives in a *different*
file after the split (the ``_constants``/``_helpers``/``_tree_widget``/
``_persistence``/``_entity_search`` support modules below, or a sibling
package like ``ster.tui.detail``).

``CSS``, ``BINDINGS``, ``COMMANDS`` and ``_LOADING_SPINNER`` are genuinely
app-wide, so they stay on the composed ``OntologyApp`` class itself, not on
any one mixin. Every other class-level constant (``_PANEL_IDS``,
``_LINT_DEBOUNCE``, …) moved to the mixin whose methods actually read it —
placement doesn't matter functionally (attribute lookup works the same
through the MRO either way), so it was chosen for readability.

## Backward-compatible re-exports

Every name that used to live directly in ``ster/tui/app.py`` — including the
module-level helpers several tests import or patch directly (``EntitySearch``,
``_add_prop_uri``, ``_nav_hint``, ``_parse_add_prop``, ``_parse_cta``,
``_prop_section_key``, ``_publish_selection``, ``_start_context_server``,
``_READ_ONLY_MESSAGE``) — is re-exported here unchanged, so
``from ster.tui.app import X`` and ``ster.tui.app.X`` keep working. A patch
aimed at one of these names should target the submodule that actually defines
or calls it (e.g. ``ster.tui.app._helpers._start_context_server``), not this
re-export surface — see the individual submodules for where each name lives.
"""

from __future__ import annotations

from textual.app import App
from textual.binding import Binding

from ._actions import _ActionsMixin
from ._busy_save import _BusySaveMixin
from ._config import _ConfigMixin
from ._constants import _READ_ONLY_MESSAGE
from ._context_menu import _ContextMenuMixin
from ._detail import _DetailMixin
from ._editing_modals import _EditingModalsMixin
from ._entity_search import EntitySearch
from ._graph import _GraphMixin
from ._helpers import (
    _add_prop_uri,
    _cta_uri,
    _nav_hint,
    _parse_add_prop,
    _parse_cta,
    _prop_section_key,
    _publish_selection,
    _start_context_server,
)
from ._lifecycle import _LifecycleMixin
from ._lint import _LintMixin
from ._ontology_identity import _OntologyIdentityMixin
from ._panels import _PanelsMixin
from ._persistence import _StorePersistence
from ._problems import _ProblemsMixin
from ._rebuild import _RebuildMixin
from ._row_actions import _RowActionsMixin
from ._shacl import _ShaclMixin
from ._source import _SourceMixin
from ._tree_build import _TreeBuildMixin
from ._tree_events import _TreeEventsMixin
from ._tree_widget import OntologyTree
from ._working_file import _WorkingFileMixin

__all__ = [
    "EntitySearch",
    "OntologyApp",
    "OntologyTree",
    "_READ_ONLY_MESSAGE",
    "_StorePersistence",
    "_add_prop_uri",
    "_cta_uri",
    "_nav_hint",
    "_parse_add_prop",
    "_parse_cta",
    "_prop_section_key",
    "_publish_selection",
    "_start_context_server",
]


class OntologyApp(
    _LifecycleMixin,
    _ConfigMixin,
    _TreeBuildMixin,
    _PanelsMixin,
    _DetailMixin,
    _LintMixin,
    _RebuildMixin,
    _BusySaveMixin,
    _ProblemsMixin,
    _RowActionsMixin,
    _ContextMenuMixin,
    _EditingModalsMixin,
    _OntologyIdentityMixin,
    _TreeEventsMixin,
    _ActionsMixin,
    _SourceMixin,
    _GraphMixin,
    _ShaclMixin,
    _WorkingFileMixin,
    App,
):
    """A modern, themeable ontology browser."""

    _LOADING_SPINNER = "⣾⣽⣻⢿⡿⣟⣯⣷"

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
    #loading {
        layer: overlay;
        width: 100%;
        height: 100%;
        content-align: center middle;
        background: $background 95%;
    }

    /* Checkboxes render a bracketed mark (ster.tui.check.Check): "[ ]" when unchecked,
       "[✓]" when checked — instead of Textual's dim-"X" block whose off state reads like
       a faint mark. These colour that mark app-wide: muted off, bold success on. */
    ToggleButton > .toggle--button { color: $text-muted; }
    ToggleButton.-on > .toggle--button { color: $text-success; text-style: bold; }
    /* And drop the heavy `tall $border` Textual boxes a *focused* checkbox in — that purple
       rectangle overflows inline / carded checkboxes and reads as broken. The focused label
       already highlights (block cursor), which is enough to show which box has focus. */
    ToggleButton:focus { border: none; }
    #body { height: 1fr; }
    #nav { width: 25%; min-width: 24; }

    /* Each pane is a rounded, titled box whose border lights up when focused —
       so you always see which pane you're in and what it holds. */
    .main-tree, #prop-tree, #detail, #source {
        border: round $foreground 40%;
        border-title-color: $foreground 70%;
        background: $surface;
        color: $foreground;
    }
    /* The contextual keyboard hint rides the bottom border of the focused pane only
       (set in code); keep it dim + left-aligned so it reads as a hint, not a second title. */
    .main-tree, #prop-tree, #detail, #source {
        border-subtitle-color: $foreground 55%;
        border-subtitle-align: left;
    }
    /* Accordion: the three left panes (Mixed SKOS/OWL, Ontology, Properties) share the
       column — 1/3 each by default. Clicking a pane expands it and folds the other two to
       their titled border bar; double-clicking a folded pane restores the 1/3 layout. A
       folded pane hides its scrollbars (and the corner square) since it shows only its bar. */
    .main-tree, #prop-tree { height: 1fr; padding: 0 1; }
    #tree.folded, #ont-tree.folded, #prop-tree.folded {
        height: 3;
        overflow: hidden hidden;
        scrollbar-size: 0 0;
    }
    #right { width: 1fr; height: 1fr; }
    #detail { width: 1fr; padding: 1 2; }
    /* The other face of the right slot. Same box as #detail so toggling does not
       move the frame; tighter left padding because the gutter carries line
       numbers and a wide indent would push short Turtle lines off-centre. */
    #source { width: 1fr; padding: 1 1; }
    /* Hovering a left pane lights its border + title, cueing that it's clickable (its header
       row accordions the pane). Focus-within (below) then takes over with the full accent. */
    .main-tree:hover, #prop-tree:hover {
        border: round $primary 60%;
        border-title-color: $primary 80%;
    }
    .main-tree:focus-within, #prop-tree:focus-within, #detail:focus-within, #source:focus-within {
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
    /* Panel layer: the cursor rests on the pane header and *no item is selected*, so the
       row highlight is removed entirely — only the pane border reads as active. */
    OntologyTree.panel-layer > .tree--cursor { background: transparent; text-style: none; color: $foreground; }
    OntologyTree.panel-layer:focus > .tree--cursor { background: transparent; color: $foreground; }

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
        Binding("slash,divide", "command_palette", "Search"),
        Binding("full_stop", "context_menu", "Actions"),
        Binding("e", "expand_all", "Expand all"),
        Binding("c", "collapse_all", "Collapse"),
        Binding("g", "open_graph", "GraphView"),
        Binding("s", "open_query", "SPARQL"),
        Binding("m", "open_map", "Map"),
        Binding("t", "open_timeline", "Timeline"),
        Binding("d", "cycle_theme", "Theme", show=False),  # still works; hint hidden
        Binding("r", "toggle_source", "Source"),
        Binding("f", "working_file", "Working file"),
        Binding("comma", "open_config", "Config"),
        Binding("question_mark", "help", "Help"),
        Binding("exclamation_mark", "problems", "Problems", show=False),
        # Ctrl+C / Cmd+C copy the selection or the focused value (quit stays on q / Ctrl+Q).
        Binding("ctrl+c,super+c", "copy", "Copy", show=False),
        Binding("q", "quit", "Quit"),
    ]

    COMMANDS = App.COMMANDS | {EntitySearch}
