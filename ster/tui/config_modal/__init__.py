"""Global configuration modal for the Textual TUI.

Opened with a shortcut. Everything auto-saves — there is no Save button; each
change (display language, theme, a toggled/added language) posts a
:class:`ConfigModal.Changed` message that the app applies and persists. Esc closes.

The configured-languages block is a single Tab stop: Tab from it returns to the
tab bar; inside, the arrow keys move between the checkboxes, the narrow "add"
field and its button. The theme dropdown applies live.

A single stateful ``ConfigModal`` class doesn't split into free functions the way
a flat-function module does, so — like ``ster.tui.app``'s ``OntologyApp`` — this
package composes it from mixin classes, one per business concern (general
settings, annotation-property catalogs, plugins, Semantic Lint config,
cross-tab navigation, auto-save/result-gathering); see ``_state.py`` for the
typing-only surface that lets one mixin's methods reference attributes/methods
owned by a sibling mixin. The several small standalone widget/message classes
the original module also defined (``_MetaCheckbox``, ``_EnforceButton``,
``_MetaRow``, ``_SecretInput``, ``_ServerGroup``, ``_LangGroup``, ``_MetaCatalog``,
``DeclareAnnotationProperty``, ``EnforceShaclRequested``) each got their own
small home instead, grouped by what they support.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import TabbedContent, TabPane

from ster.metadata_coverage import MetaProp

from ..hint_bar import Hint
from ..modal import ModalBase
from ._general_mixin import _GeneralMixin
from ._general_widgets import _LangGroup as _LangGroup
from ._general_widgets import _SecretInput as _SecretInput
from ._general_widgets import _ServerGroup as _ServerGroup
from ._graphviz_mixin import _GraphVizMixin
from ._labels import suggest_label as suggest_label
from ._messages import DeclareAnnotationProperty as DeclareAnnotationProperty
from ._messages import EnforceShaclRequested as EnforceShaclRequested
from ._metadata_catalog import _MetaCatalog as _MetaCatalog
from ._metadata_widgets import _EnforceButton as _EnforceButton
from ._metadata_widgets import _MetaCheckbox as _MetaCheckbox
from ._metadata_widgets import _MetaRow as _MetaRow
from ._navigation_mixin import _NavigationMixin
from ._percent import _pct_display as _pct_display
from ._percent import _pct_parse as _pct_parse
from ._plugins_mixin import _PluginsMixin
from ._props_mixin import _PropsMixin
from ._semanticlint_mixin import _SemanticLintMixin
from ._state_mixin import _StateMixin

__all__ = [
    "ConfigModal",
    "DeclareAnnotationProperty",
    "EnforceShaclRequested",
    "suggest_label",
    "_EnforceButton",
    "_LangGroup",
    "_MetaCatalog",
    "_MetaCheckbox",
    "_MetaRow",
    "_SecretInput",
    "_ServerGroup",
    "_pct_display",
    "_pct_parse",
]


class ConfigModal(  # type: ignore[misc]
    _GeneralMixin,
    _PropsMixin,
    _GraphVizMixin,
    _PluginsMixin,
    _SemanticLintMixin,
    _NavigationMixin,
    _StateMixin,
    ModalBase[None],
):
    """Display language + theme + configured languages (auto-saving)."""

    DEFAULT_CSS = """
    /* A fixed modal size so it doesn't resize when switching tabs. The tabs fill
       it; each pane scrolls if its content is taller than the box. */
    #cfg-box { width: 90%; height: 90%; }
    #cfg-box TabbedContent, #cfg-box ContentSwitcher { height: 1fr; }
    #cfg-box TabPane { height: 1fr; overflow-y: auto; }
    #cfg-box .cfg-label { color: $text-muted; }
    #cfg-box .cfg-hint { color: $text-muted; }
    /* A tab's leading description line, spaced from the content below it. */
    .cfg-tab-intro { color: $text-muted; margin: 0 0 1 0; }
    /* Plugins tab: one bordered card per plugin (name + description), spaced out. */
    .cfg-plugin-block {
        height: auto;
        border: round $foreground 40%;
        padding: 0 1;
        margin-bottom: 1;
    }
    .cfg-plugin-block .cfg-plugin-desc { color: $text-muted; }
    /* Semantic Lint tab: labelled, bordered sections. */
    .cfg-sl-section {
        height: auto;
        border: round $foreground 40%;
        border-title-color: $foreground 70%;
        padding: 0 1;
        margin-bottom: 1;
    }
    /* Each threshold + its "required in:" row form one tight group, spaced from the next. */
    .cfg-sl-thresh-group { height: auto; margin: 0 0 1 0; }
    /* Single-line rows (flat field, no 3-line border) so the threshold and its
       "required in:" row sit directly adjacent — no blank line between them. */
    .cfg-sl-thresh { height: 1; }
    /* Fixed label width so the fields align in a column right after the names (not pushed
       to the far right), keeping the name, its field and "required in:" visually close. */
    .cfg-sl-label { width: 38; content-align: left middle; }
    .cfg-sl-num { width: 6; height: 1; border: none; padding: 0 1; background: $foreground 10%; }
    .cfg-sl-pct { width: auto; height: 1; content-align: left middle; color: $text-muted; margin-left: 1; }
    .cfg-sl-text { width: 1fr; }
    /* Per-language "required in:" row, tucked directly beneath its threshold. */
    .cfg-sl-langrow { height: 1; }
    .cfg-sl-langcaption { width: auto; color: $text-muted; content-align: left middle; margin-right: 1; }
    .cfg-sl-langbox { width: auto; margin-right: 2; border: none; background: transparent; }
    /* Narrow dropdowns; the rounded Select border is shared from ModalBase. */
    #cfg-theme { width: 24; margin-bottom: 1; }
    #cfg-display { width: 16; margin-bottom: 1; }
    /* The configured-languages block: one titled box holding the checkbox group and
       the add-language row; its border lights up while focus is anywhere inside. */
    #cfg-langs {
        height: auto;
        border: round $foreground 40%;
        border-title-color: $foreground 70%;
        padding: 0 1;
        margin-bottom: 1;
    }
    #cfg-langs:focus-within { border: round $primary; border-title-color: $primary; }
    #cfg-boxes { layout: grid; grid-size: 4; grid-rows: auto; height: auto; }
    #cfg-boxes Checkbox { border: none; background: transparent; width: 100%; }
    #cfg-boxes Checkbox.lang-current { background: $secondary 30%; text-style: bold; }
    /* Add-language row (inside the block): a wide field + a tiny + button. */
    #cfg-add-row { height: auto; margin-top: 1; }
    #cfg-extra { width: 1fr; }  /* Input border shared from ModalBase */
    #cfg-add { width: auto; min-width: 5; margin-left: 1; }
    /* Metadata predicate catalogs (Annotation-properties tab): two foldable groups
       (Ontology Metadata + Entity metadata), each a checklist of predicates (ticked
       = offered in "Add metadata") above an add row. Both share one _MetaCatalog. */
    /* Foldable groups: a plain border, no background fill; the border lights up
       while focus is anywhere inside. */
    #cfg-tab-props Collapsible {
        background: transparent;
        border: round $foreground 40%;
        border-title-color: $foreground 70%;
        margin-bottom: 1;
        padding: 0 1;
    }
    #cfg-tab-props Collapsible:focus-within {
        border: round $primary;
        border-title-color: $primary;
    }
    #cfg-tab-props CollapsibleTitle { background: transparent; }
    #cfg-tab-props CollapsibleTitle:focus { background: $secondary 30%; }
    #cfg-tab-props Contents { background: transparent; }
    _MetaCatalog { height: auto; }
    .cfg-mprops { height: auto; max-height: 18; }
    .cfg-mp-row { height: 1; width: 1fr; }
    .cfg-mp-row.has-enforce { height: 3; }  /* room for the button (Textual buttons are 3 tall) */
    .cfg-mprops .cfg-mp-box { height: 1; width: 1fr; border: none; background: transparent; }
    .cfg-mp-row.has-enforce .cfg-mp-box { height: 3; content-align: left middle; }
    .cfg-mprops .cfg-mp-box.mp-current { background: $secondary 30%; text-style: bold; }
    .cfg-mp-enforce { width: auto; min-width: 24; margin-left: 1; }
    .cfg-mp-add-row { height: auto; margin-top: 1; }
    .cfg-mp-uri { width: 2fr; }  /* rounded Input border (incl. focus) shared from ModalBase */
    .cfg-mp-label { width: 1fr; margin-left: 1; }
    .cfg-mp-add { width: auto; min-width: 5; margin-left: 1; }
    /* Opens the (separate) create-local-annotation-property modal. */
    .cfg-mp-new { width: auto; min-width: 8; margin-top: 1; }
    .cfg-mp-search { width: auto; min-width: 8; margin-top: 1; margin-bottom: 1; }
    /* Local server (ster serve) block: URL / port / bearer token, one Tab stop. */
    #cfg-server {
        height: auto;
        border: round $foreground 40%;
        border-title-color: $foreground 70%;
        padding: 0 1;
        margin-bottom: 1;
    }
    #cfg-server:focus-within { border: round $primary; border-title-color: $primary; }
    #cfg-server Input { border: round $primary; margin-bottom: 1; }
    #cfg-server-line { height: auto; }
    #cfg-server-url { width: 3fr; }      /* URL takes the lion's share */
    #cfg-server-port { width: 1fr; margin-left: 1; }
    #cfg-server-token { width: 1fr; }
    """

    BINDINGS = [Binding("escape", "cancel", "Close")]

    class Changed(Message):
        """Posted whenever a setting changes (the modal auto-saves)."""

        def __init__(self, result: dict) -> None:
            super().__init__()
            self.result = result

    class WriteOntoCi(Message):
        """Ask the app to export the plugin's quality config to the repo's onto-ci.yml."""

    def __init__(
        self,
        display_lang: str,
        configured_langs: list[str],
        available_langs: list[str],
        themes: list[str] | None = None,
        current_theme: str = "ster",
        metadata_props: list[MetaProp] | None = None,
        entity_metadata_props: list[MetaProp] | None = None,
        annotation_verifier=None,  # Callable[[str], bool] | None — URI is an annotation property?
        can_declare: bool = False,  # may a confirmed unknown predicate be declared locally?
        base_uri: str = "",  # ontology base IRI — fixed prefix for new local properties
        project_path=None,
        trace_base_url: str = "",
    ) -> None:
        super().__init__()
        self._display = display_lang
        self._available = sorted({*available_langs, display_lang} - {""}) or [display_lang]
        self._themes = sorted({*(themes or []), current_theme} - {""}) or [current_theme]
        self._theme = current_theme
        self._configured = list(dict.fromkeys(configured_langs))
        self._metadata = list(metadata_props or [])  # ontology-metadata predicate catalog
        self._entity_metadata = list(entity_metadata_props or [])  # entity-metadata catalog
        self._annotation_verifier = annotation_verifier
        self._can_declare = can_declare
        self._base_uri = base_uri
        self._project_path = project_path
        self._trace_base_url = trace_base_url
        from ster.api_server import load_server_config, load_token

        self._server_url, self._server_port = load_server_config()
        self._server_token = load_token()
        self._ready = False  # suppress Changed until fully composed

    def compose(self) -> ComposeResult:
        with Vertical(id="cfg-box", classes="modal-box"), TabbedContent():
            with TabPane("General", id="cfg-tab-general"):
                yield from self._general_tab()
            with TabPane("Annotation properties", id="cfg-tab-props"):
                yield from self._props_tab()
            with TabPane("Graph Viz", id="cfg-tab-graphviz"):
                yield from self._graphviz_tab()
            with TabPane("Plugins", id="cfg-tab-plugins"):
                yield from self._plugins_tab()
            from ster import plugins

            if plugins.is_enabled("semanticlint"):
                with TabPane("Semantic Lint", id="cfg-tab-semanticlint"):
                    yield from self._semanticlint_widgets()
            if plugins.is_enabled("mcp_query_trace"):
                with TabPane("MCP Query Trace", id="cfg-tab-mcp-query-trace"):
                    from ster.plugins.query_trace import TracePanel

                    panel = TracePanel(self._project_path)
                    panel.query_trace_base_url = self._trace_base_url  # type: ignore[attr-defined]
                    yield panel

    def footer_hints(self) -> list[Hint]:
        return [
            Hint("arrows", "move"),
            Hint("esc", "close", "cancel"),
            Hint("↻", "changes save automatically"),
        ]

    def action_cancel(self) -> None:
        self.dismiss(None)
