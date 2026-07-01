"""Global configuration modal for the Textual TUI.

Opened with a shortcut. Everything auto-saves — there is no Save button; each
change (display language, theme, a toggled/added language) posts a
:class:`ConfigModal.Changed` message that the app applies and persists. Esc closes.

The configured-languages block is a single Tab stop: Tab from it jumps to
"Configure LLM"; inside, the arrow keys move between the checkboxes, the narrow
"add" field and its button. The theme dropdown applies live.
"""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import (
    Button,
    Checkbox,
    Collapsible,
    Input,
    Select,
    Static,
    TabbedContent,
    TabPane,
    Tabs,
)
from textual.widgets._collapsible import CollapsibleTitle

from ster.metadata_coverage import MetaProp

from .choice_modal import ChoiceModal
from .focus_group import FocusGroup
from .llm_group import LlmSetup
from .local_property_modal import LocalPropertyModal
from .modal import ModalBase


class DeclareAnnotationProperty(Message):
    """Ask the app to declare *uri* as a local ``owl:AnnotationProperty``.

    Posted when the user confirms keeping a predicate that is not (yet) a known
    annotation property, or creates a brand-new local one from the config modal.
    The app runs the OWL command(s) — writing *label* / *comment* when given —
    and saves to the open ``.ttl``.
    """

    def __init__(self, uri: str, label: str = "", comment: str = "") -> None:
        super().__init__()
        self.uri = uri
        self.label = label
        self.comment = comment


# Common namespaces → prefix, for suggesting a label when registering a predicate.
_KNOWN_PREFIXES: tuple[tuple[str, str], ...] = (
    ("http://purl.org/dc/terms/", "dcterms"),
    ("http://www.w3.org/2002/07/owl#", "owl"),
    ("http://www.w3.org/2000/01/rdf-schema#", "rdfs"),
    ("http://www.w3.org/2004/02/skos/core#", "skos"),
    ("http://purl.org/vocab/vann/", "vann"),
    ("http://xmlns.com/foaf/0.1/", "foaf"),
    ("http://schema.org/", "schema"),
)


def suggest_label(predicate: str) -> str:
    """A friendly ``prefix:local`` label for *predicate*, or its local name."""
    for namespace, prefix in _KNOWN_PREFIXES:
        if predicate.startswith(namespace):
            return f"{prefix}:{predicate[len(namespace) :]}"
    return predicate.rsplit("/", 1)[-1].rsplit("#", 1)[-1] or predicate


class _MetaCheckbox(Checkbox):
    """A registered ontology-metadata predicate as a checkbox (ticked = offered in
    "Add metadata"). Carries its predicate URI + display label."""

    def __init__(self, predicate: str, label: str) -> None:
        self.label_text = label or suggest_label(predicate)
        super().__init__(self.label_text, value=True, classes="cfg-mp-box")
        self.predicate = predicate


class _SecretInput(Input):
    """An ``Input`` that masks its text, revealing it only while focused."""

    def on_focus(self) -> None:
        self.password = False

    def on_blur(self) -> None:
        self.password = True


class _ServerGroup(FocusGroup):
    """The local-server URL / port / bearer-token fields as one Tab stop."""

    exit_next = "#cfg-langs"
    exit_prev = "#cfg-theme"

    def _items(self) -> list:  # type: ignore[type-arg]
        return list(self.query(Input))


class _LangGroup(FocusGroup):
    """The configured-languages block: the checkboxes *and* the add field/+ button as
    one Tab stop. Space/enter toggles the current checkbox (the rest is inherited)."""

    exit_next = "#llm-mode-select"
    exit_prev = "#cfg-server"

    def _items(self) -> list:  # type: ignore[type-arg]
        # query (never query_one) so a not-yet-mounted child can't raise.
        return [*self.query(Checkbox), *self.query("#cfg-extra"), *self.query("#cfg-add")]

    def _focus_item(self, item) -> None:  # type: ignore[no-untyped-def]
        for box in self.query(Checkbox):
            box.set_class(box is item, "lang-current")
        # Checkbox → keep focus on the group (so space toggles); field/+ → focus it.
        self.focus() if isinstance(item, Checkbox) else item.focus()

    def _extra_key(self, event) -> bool:  # type: ignore[no-untyped-def]
        return event.key in ("space", "enter") and self._toggle_current()

    def _toggle_current(self) -> bool:
        item = self.current_item()
        if isinstance(item, Checkbox):
            item.value = not item.value
            return True
        return False

    def _clear(self) -> None:
        for box in self.query(Checkbox):
            box.remove_class("lang-current")


class _MetaCatalog(FocusGroup):
    """One predicate catalog editor — a checklist of ``_MetaCheckbox`` plus an
    add row (URI + label + ＋) — as a single Tab stop.

    Entered from the group's collapsible header with Right; inside, Up/Down rove the
    checkboxes and the add fields, space toggles the current checkbox, and Left (or
    Up past the top) returns to the header. Tab/Shift+Tab jump to *next_target* /
    *prev_target*. Children are queried by class (scoped to this group), so two
    instances on the same screen stay independent.
    """

    class Changed(Message):
        """A predicate was added to this catalog (toggles bubble Checkbox.Changed)."""

    def __init__(  # type: ignore[no-untyped-def]
        self,
        props: list[MetaProp],
        *,
        prev_target: str = "Tabs",
        next_target: str = "Tabs",
        verifier=None,  # Callable[[str], bool] | None — is the URI an annotation property?
        can_declare: bool = False,  # may we declare it locally on confirm?
        base_uri: str = "",  # ontology base IRI — fixed prefix for new local properties
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._initial = list(props)
        self.exit_prev = prev_target  # Shift+Tab target
        self.exit_next = next_target  # Tab target
        self._verifier = verifier
        self._can_declare = can_declare
        self._base_uri = base_uri

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="cfg-mprops"):
            for mp in self._initial:
                yield _MetaCheckbox(mp.predicate, mp.label)
        with Horizontal(classes="cfg-mp-add-row"):
            yield Input(placeholder="predicate URI — http://…", classes="cfg-mp-uri")
            yield Input(placeholder="label (optional)", classes="cfg-mp-label")
            yield Button("+", classes="cfg-mp-add")
        if self._can_declare and self._base_uri:
            yield Button("Add local annotation property", classes="cfg-mp-new")

    def props(self) -> list[MetaProp]:
        """The ticked predicates as ``(predicate, label)`` :class:`MetaProp` entries."""
        return [
            MetaProp(cb.predicate, cb.label_text) for cb in self.query(_MetaCheckbox) if cb.value
        ]

    async def add_typed(self) -> None:
        """Mount a checkbox for the typed predicate (deduped); clear the fields."""
        uri = self.query_one(".cfg-mp-uri", Input).value.strip()
        label = self.query_one(".cfg-mp-label", Input).value.strip()
        present = {cb.predicate for cb in self.query(_MetaCheckbox)}
        if not uri or uri in present:
            return
        await self.query_one(".cfg-mprops").mount(_MetaCheckbox(uri, label))
        self.query_one(".cfg-mp-uri", Input).value = ""
        self.query_one(".cfg-mp-label", Input).value = ""
        self.post_message(self.Changed())  # ask the modal to auto-save

    @on(Button.Pressed, ".cfg-mp-add")
    async def _on_add(self, event: Button.Pressed) -> None:
        event.stop()
        await self._submit()

    @on(Input.Submitted, ".cfg-mp-uri, .cfg-mp-label")
    async def _on_submit(self, event: Input.Submitted) -> None:
        event.stop()
        await self._submit()

    @on(Button.Pressed, ".cfg-mp-new")
    async def _on_new(self, event: Button.Pressed) -> None:
        event.stop()
        self.app.push_screen(LocalPropertyModal(self._base_uri), self._on_new_property)

    async def _on_new_property(self, result: dict | None) -> None:
        """Result of the create modal — ``{name, label, comment}`` or None on cancel."""
        if not result:
            return
        await self._create_local(
            result.get("name", ""), result.get("label", ""), result.get("comment", "")
        )

    async def _create_local(self, name: str, label: str, comment: str) -> None:
        """Mint a new local annotation property: declare it in the open ``.ttl``
        (label / comment included) and tick it into this catalog."""
        name = name.strip()
        uri = f"{self._base_uri}{name}"
        present = {cb.predicate for cb in self.query(_MetaCheckbox)}
        if not name or uri in present:
            return
        label = label.strip() or name
        await self.query_one(".cfg-mprops").mount(_MetaCheckbox(uri, label))
        self.post_message(self.Changed())  # auto-save the catalog
        self.post_message(DeclareAnnotationProperty(uri, label, comment.strip()))

    async def _submit(self) -> None:
        """Add the typed predicate. If it is not a known annotation property, warn
        and ask for confirmation first — *Use it* adds it (declared locally as an
        annotation property when a file is open); Esc/Cancel skips the add."""
        uri = self.query_one(".cfg-mp-uri", Input).value.strip()
        present = {cb.predicate for cb in self.query(_MetaCheckbox)}
        if not uri or uri in present:
            return
        if self._verifier is None or self._verifier(uri):
            await self.add_typed()
            return
        self.app.push_screen(
            ChoiceModal(
                f"“{uri}” is not defined as an annotation property. "
                "Use it as an annotation property anyway?",
                [("Use as annotation property", "use"), ("Cancel", "cancel")],
            ),
            self._on_unverified_choice,
        )

    async def _on_unverified_choice(self, choice: str | None) -> None:
        """Confirmation result for an unknown predicate (None/`cancel` = skip)."""
        if choice != "use":
            return
        uri = self.query_one(".cfg-mp-uri", Input).value.strip()
        await self.add_typed()  # mounts the checkbox, clears the fields, posts Changed
        if self._can_declare and uri:
            self.post_message(DeclareAnnotationProperty(uri))  # app declares it locally

    # ── focus-group navigation ──────────────────────────────────────────────────
    def _items(self) -> list:  # type: ignore[type-arg]
        return [
            *self.query(_MetaCheckbox),
            *self.query(".cfg-mp-uri"),
            *self.query(".cfg-mp-label"),
            *self.query(".cfg-mp-add"),
            *self.query(".cfg-mp-new"),
        ]

    def _focus_item(self, item) -> None:  # type: ignore[no-untyped-def]
        for box in self.query(_MetaCheckbox):
            box.set_class(box is item, "mp-current")
        if isinstance(item, _MetaCheckbox):
            item.scroll_visible()  # keep the current property in view while roving
            self.focus()  # keep focus on the group so space toggles
        else:
            item.focus()  # the add field / + button

    def on_key(self, event) -> None:  # type: ignore[no-untyped-def]
        """Inside the list: Up/Down rove the items, Left (or Up past the top) returns
        to the group header, and Down past the last item (the ＋ button) moves on to
        the next group. Space/Enter toggle the current checkbox.

        We share the ``on_key`` handler name with :class:`FocusGroup`; Textual would
        otherwise dispatch *both* (its copy maps Left/Right to a move), so every
        handled key calls ``prevent_default()`` to suppress the inherited handler.
        """
        key = event.key
        if key == "down":
            self._rove(1)
        elif key == "up":
            self._rove(-1)
        elif key == "left":
            self._to_header()
        elif key == "right":
            pass  # entering the list is driven from the header; ignore here
        elif not self._extra_key(event):  # space / enter toggle the current checkbox
            return  # not one of ours — let it propagate normally
        event.stop()
        event.prevent_default()  # suppress FocusGroup.on_key (same handler name in the MRO)

    def _rove(self, delta: int) -> None:
        items = self._items()
        if not items:
            return
        if not self._active:  # first arrow lands on the first/last item
            self._active = True
            self._cursor = 0 if delta > 0 else len(items) - 1
        elif self._cursor + delta < 0:  # Up past the top → back to this group's header
            self._to_header()
            return
        elif self._cursor + delta >= len(items):  # Down past the bottom → the next group
            self._exit_to(self.exit_next)
            return
        else:
            self._cursor += delta
        self._focus_item(items[self._cursor])

    def _exit_to(self, selector: str | None) -> None:
        """Leave the list for *selector* — the next group's header, or the tab bar
        for the last group (its ``exit_next`` is ``Tabs``)."""
        self._reset()
        matches = self.screen.query(selector) if selector else None
        if matches:
            matches.first().focus()

    def _enter(self) -> None:
        """Activate this group's cursor on its first item — entered from the header
        with Right."""
        items = self._items()
        if items:
            self._active = True
            self._cursor = 0
            self._focus_item(items[0])

    def _to_header(self) -> None:
        """Leave the item list, returning focus to this group's collapsible header."""
        self._reset()
        node: object = self.parent
        while node is not None and not isinstance(node, Collapsible):
            node = node.parent  # type: ignore[attr-defined]
        if isinstance(node, Collapsible):
            node.query_one(CollapsibleTitle).focus()

    def _extra_key(self, event) -> bool:  # type: ignore[no-untyped-def]
        return event.key in ("space", "enter") and self._toggle_current()

    def _toggle_current(self) -> bool:
        item = self.current_item()
        if isinstance(item, _MetaCheckbox):
            item.value = not item.value
            return True
        return False

    def _clear(self) -> None:
        for box in self.query(_MetaCheckbox):
            box.remove_class("mp-current")


class ConfigModal(ModalBase[None]):
    """Display language + theme + configured languages + an LLM entry (auto-saving)."""

    DEFAULT_CSS = """
    /* A fixed modal size so it doesn't resize when switching tabs. The tabs fill
       it; each pane scrolls if its content is taller than the box. */
    #cfg-box { width: 90%; height: 90%; }
    #cfg-box TabbedContent, #cfg-box ContentSwitcher { height: 1fr; }
    #cfg-box TabPane { height: 1fr; overflow-y: auto; }
    #cfg-box .cfg-label { color: $text-muted; }
    #cfg-box .cfg-hint { color: $text-muted; }
    .cfg-sl-thresh { height: auto; }
    .cfg-sl-label { width: 1fr; content-align: left middle; }
    .cfg-sl-input { width: 14; }
    /* Narrow dropdowns with clean rounded borders (override the dashed `tall`). */
    #cfg-theme { width: 24; margin-bottom: 1; }
    #cfg-display { width: 16; margin-bottom: 1; }
    #cfg-display > SelectCurrent, #cfg-theme > SelectCurrent { border: round $primary; }
    #cfg-display:focus > SelectCurrent, #cfg-theme:focus > SelectCurrent { border: round $primary; }
    #cfg-display SelectOverlay, #cfg-theme SelectOverlay { border: round $primary; }
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
    #cfg-extra { width: 1fr; border: round $primary; }
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
    .cfg-mprops { height: auto; max-height: 12; }
    .cfg-mprops .cfg-mp-box { height: auto; margin-bottom: 1; border: none; background: transparent; }
    .cfg-mprops .cfg-mp-box.mp-current { background: $secondary 30%; text-style: bold; }
    .cfg-mp-add-row { height: auto; margin-top: 1; }
    .cfg-mp-uri { width: 2fr; border: round $primary; }
    .cfg-mp-label { width: 1fr; border: round $primary; margin-left: 1; }
    /* Keep the rounded border on focus — Input's default `:focus` swaps to a `tall`
       border (same specificity as our class rule), which breaks the rounded look. */
    .cfg-mp-uri:focus, .cfg-mp-label:focus { border: round $primary; }
    .cfg-mp-add { width: auto; min-width: 5; margin-left: 1; }
    /* Opens the (separate) create-local-annotation-property modal. */
    .cfg-mp-new { width: auto; min-width: 8; margin-top: 1; }
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
    /* Inline LLM setup block (its own FocusGroup). */
    #cfg-llm {
        border: round $foreground 40%;
        border-title-color: $foreground 70%;
        padding: 0 1;
        margin-bottom: 1;
    }
    #cfg-llm:focus-within { border: round $primary; border-title-color: $primary; }
    """

    BINDINGS = [Binding("escape", "cancel", "Close")]

    class Changed(Message):
        """Posted whenever a setting changes (the modal auto-saves)."""

        def __init__(self, result: dict) -> None:
            super().__init__()
            self.result = result

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
        from ster.api_server import load_server_config, load_token

        self._server_url, self._server_port = load_server_config()
        self._server_token = load_token()
        self._ready = False  # suppress Changed until fully composed

    def compose(self) -> ComposeResult:
        with Vertical(id="cfg-box", classes="modal-box"):
            with TabbedContent():
                with TabPane("General", id="cfg-tab-general"):
                    yield from self._general_tab()
                with TabPane("Annotation properties", id="cfg-tab-props"):
                    yield from self._props_tab()
                with TabPane("Plugins", id="cfg-tab-plugins"):
                    yield from self._plugins_tab()
                from ster import plugins

                if plugins.is_enabled("semanticlint"):
                    with TabPane("Semantic Lint", id="cfg-tab-semanticlint"):
                        yield from self._semanticlint_widgets()
            yield Static(
                "arrows  move     esc  close     (changes save automatically)",
                classes="modal-footer",
            )

    def _plugins_tab(self) -> ComposeResult:
        from ster import plugins

        yield Static(
            "Enable optional in-tree plugins. Each adds its own features (and config).",
            classes="cfg-hint",
        )
        for spec in plugins.all_plugins():
            yield Checkbox(spec.name, value=plugins.is_enabled(spec.id), id=f"cfg-plugin-{spec.id}")
            yield Static(spec.description, classes="cfg-hint")

    #: feature toggles surfaced in the Semantic Lint tab (id suffix → label).
    _SL_FEATURES = (
        ("icons", "Colour entity icons by issue severity"),
        ("detail", "Annotate issues in the detail panel"),
        ("quality_block", "Show the Quality & Coverage block"),
    )
    #: numeric coverage thresholds (0.0–1.0) offered in the Semantic Lint tab.
    _SL_THRESHOLDS = (
        ("min_label_coverage", "Concept prefLabel coverage (QUA001)"),
        ("min_definition_coverage", "Concept definition coverage (QUA002)"),
        ("min_class_label_coverage", "Class label coverage (QUA004)"),
        ("min_property_label_coverage", "Property label coverage (QUA005)"),
    )

    def _semanticlint_widgets(self):  # type: ignore[no-untyped-def]
        """Widgets for the Semantic Lint tab: install status, feature toggles, and the
        global quality thresholds (persisted to ~/.config/ster/quality.json)."""
        from ster.plugins.semanticlint import config, deps

        cfg = config.load_config()
        if not deps.is_installed():
            yield Static(
                "[yellow]semanticlint is not installed.[/] Run: pip install 'ster[semanticlint]'",
                classes="cfg-hint",
            )
        yield Static("Features", classes="cfg-label")
        for name, label in self._SL_FEATURES:
            yield Checkbox(label, value=cfg["features"].get(name, True), id=f"cfg-slfeat-{name}")
        yield Static("Quality thresholds (0.0–1.0)", classes="cfg-label")
        for name, label in self._SL_THRESHOLDS:
            # Build the row explicitly (no `with` block) so this generator also works
            # standalone when the tab is added dynamically via TabbedContent.add_pane.
            yield Horizontal(
                Static(label, classes="cfg-sl-label"),
                Input(
                    value=str(cfg["quality"].get(name, "")),
                    id=f"cfg-slthr-{name}",
                    classes="cfg-sl-input",
                ),
                classes="cfg-sl-thresh",
            )
        yield Static("Required prefLabel languages (comma-separated, QUA003)", classes="cfg-label")
        yield Input(
            value=", ".join(cfg["quality"].get("languages", [])),
            id="cfg-sllangs",
            classes="cfg-sl-input",
        )

    def _general_tab(self) -> ComposeResult:
        yield Static("Display language", classes="cfg-label")
        yield Select(
            [(code, code) for code in self._available],
            value=self._display if self._display in self._available else self._available[0],
            allow_blank=False,
            id="cfg-display",
        )
        yield Static("Display theme", classes="cfg-label")
        yield Select(
            [(name, name) for name in self._themes],
            value=self._theme if self._theme in self._themes else self._themes[0],
            allow_blank=False,
            id="cfg-theme",
        )
        with _ServerGroup(id="cfg-server"):
            with Horizontal(id="cfg-server-line"):
                yield Input(
                    value=self._server_url,
                    placeholder="Server URL — http://127.0.0.1",
                    id="cfg-server-url",
                )
                yield Input(
                    value=str(self._server_port), placeholder="Port — 8765", id="cfg-server-port"
                )
            yield _SecretInput(
                value=self._server_token,
                password=True,
                placeholder="Bearer token (hidden — shown while editing)",
                id="cfg-server-token",
            )
        yield Static(
            "(configured languages — used to add labels & language-dependent properties)",
            classes="cfg-hint",
        )
        with _LangGroup(id="cfg-langs"):
            with Vertical(id="cfg-boxes"):
                for code in self._configured:
                    yield Checkbox(code, value=True, id=f"cfg-chk-{code}")
            with Horizontal(id="cfg-add-row"):
                yield Input(
                    placeholder="add languages, comma-separated — e.g. en, fr, es, de, zh, ar",
                    id="cfg-extra",
                )
                yield Button("+", id="cfg-add")
        yield Static("Configure LLM", classes="cfg-label")
        yield LlmSetup(id="cfg-llm")

    def _props_tab(self) -> ComposeResult:
        with Collapsible(title="Ontology Metadata", collapsed=False, id="cfg-ont-meta-group"):
            yield Static(
                "Offered when adding metadata to the ontology overview.", classes="cfg-hint"
            )
            yield _MetaCatalog(
                self._metadata,
                id="cfg-ont-meta",
                prev_target="#cfg-ont-meta-group CollapsibleTitle",  # Shift+Tab → own header
                next_target="#cfg-entity-meta-group CollapsibleTitle",  # Tab → next group
                verifier=self._annotation_verifier,
                can_declare=self._can_declare,
                base_uri=self._base_uri,
            )
        with Collapsible(title="Entity metadata", collapsed=False, id="cfg-entity-meta-group"):
            yield Static(
                "Offered when adding metadata to a class, property or individual.",
                classes="cfg-hint",
            )
            yield _MetaCatalog(
                self._entity_metadata,
                id="cfg-entity-meta",
                prev_target="#cfg-entity-meta-group CollapsibleTitle",  # Shift+Tab → own header
                next_target="Tabs",  # Tab → tab bar
                verifier=self._annotation_verifier,
                can_declare=self._can_declare,
                base_uri=self._base_uri,
            )

    def _tab_ids(self) -> list[str]:
        """The ids of the currently-mounted tabs, in order (plugin tabs are dynamic)."""
        return [pane.id for pane in self.query(TabPane) if pane.id]

    def on_mount(self) -> None:
        self.query_one("#cfg-box").border_title = "Configuration"
        self.query_one("#cfg-server").border_title = "Local server (ster serve)"
        self.query_one("#cfg-langs").border_title = "Configured languages"
        self.query_one("#cfg-llm").border_title = "LLM"
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

    # ── current state + auto-save ───────────────────────────────────────────────

    def _result(self) -> dict:
        configured = [
            box.id.removeprefix("cfg-chk-")  # type: ignore[union-attr]
            for box in self.query("#cfg-boxes Checkbox").results(Checkbox)
            if box.value
        ]
        from ster import plugins

        result = {
            "display": str(self.query_one("#cfg-display", Select).value),
            "theme": str(self.query_one("#cfg-theme", Select).value),
            "configured": configured,
            "metadata_props": self.query_one("#cfg-ont-meta", _MetaCatalog).props(),
            "entity_metadata_props": self.query_one("#cfg-entity-meta", _MetaCatalog).props(),
            "plugins": {
                spec.id: self.query_one(f"#cfg-plugin-{spec.id}", Checkbox).value
                for spec in plugins.all_plugins()
            },
        }
        if self.query("#cfg-tab-semanticlint"):  # the plugin's tab is mounted
            result["semanticlint"] = self._semanticlint_result()
        return result

    def _semanticlint_result(self) -> dict:
        """The Semantic Lint tab's config (features + thresholds) for persistence."""
        features = {
            name: self.query_one(f"#cfg-slfeat-{name}", Checkbox).value
            for name, _ in self._SL_FEATURES
        }
        quality: dict = {}
        for name, _ in self._SL_THRESHOLDS:
            raw = self.query_one(f"#cfg-slthr-{name}", Input).value.strip()
            try:
                quality[name] = float(raw)
            except ValueError:
                pass  # leave unset → keeps the stored/default value
        langs = self.query_one("#cfg-sllangs", Input).value
        quality["languages"] = [c.strip() for c in langs.split(",") if c.strip()]
        return {"features": features, "quality": quality}

    def _save(self) -> None:
        if self._ready:
            self.post_message(self.Changed(self._result()))

    @on(Select.Changed)
    def _on_select(self, event: Select.Changed) -> None:
        self._save()  # display or theme changed → apply live + persist

    @on(Checkbox.Changed)
    def _on_checkbox(self, event: Checkbox.Changed) -> None:
        self._save()

    @on(Checkbox.Changed, "#cfg-plugin-semanticlint")
    async def _on_semanticlint_toggle(self, event: Checkbox.Changed) -> None:
        """Add / remove the Semantic Lint tab live when the plugin is toggled."""
        tabbed = self.query_one(TabbedContent)
        mounted = bool(self.query("#cfg-tab-semanticlint"))
        if event.value and not mounted:
            pane = TabPane(
                "Semantic Lint", *self._semanticlint_widgets(), id="cfg-tab-semanticlint"
            )
            await tabbed.add_pane(pane)
        elif not event.value and mounted:
            await tabbed.remove_pane("cfg-tab-semanticlint")

    @on(Input.Changed, ".cfg-sl-input")
    def _on_semanticlint_input(self, event: Input.Changed) -> None:
        self._save()  # thresholds / languages changed → persist to quality.json

    @on(Input.Changed, "#cfg-server-url")
    @on(Input.Changed, "#cfg-server-port")
    @on(Input.Changed, "#cfg-server-token")
    def _on_server(self, event: Input.Changed) -> None:
        """Persist the local-server URL / port / bearer token (auto-save)."""
        if not self._ready:
            return
        from ster.api_server import save_server_config, save_token

        url = self.query_one("#cfg-server-url", Input).value.strip()
        port_raw = self.query_one("#cfg-server-port", Input).value.strip()
        if url and port_raw.isdigit():
            save_server_config(url, int(port_raw))
        token = self.query_one("#cfg-server-token", Input).value.strip()
        if token:
            save_token(token)

    @on(Button.Pressed, "#cfg-add")
    async def _on_add(self, event: Button.Pressed) -> None:
        await self._add_typed_languages()

    @on(Input.Submitted, "#cfg-extra")
    async def _on_extra_submit(self, event: Input.Submitted) -> None:
        await self._add_typed_languages()

    async def _add_typed_languages(self) -> None:
        field = self.query_one("#cfg-extra", Input)
        codes = [code.strip() for code in field.value.split(",") if code.strip()]
        container = self.query_one("#cfg-boxes")
        for code in codes:
            if not self.query(f"#cfg-chk-{code}"):
                await container.mount(Checkbox(code, value=True, id=f"cfg-chk-{code}"))
        field.value = ""
        self._save()

    # ── metadata catalogs ───────────────────────────────────────────────────────
    @on(_MetaCatalog.Changed)
    def _on_catalog_changed(self, event: _MetaCatalog.Changed) -> None:
        """A predicate was added to either catalog → auto-save (toggles are handled
        by ``_on_checkbox``)."""
        self._save()

    def action_cancel(self) -> None:
        self.dismiss(None)
