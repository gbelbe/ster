"""Global configuration modal for the Textual TUI.

Opened with a shortcut. Everything auto-saves — there is no Save button; each
change (display language, theme, a toggled/added language) posts a
:class:`ConfigModal.Changed` message that the app applies and persists. Esc closes.

The configured-languages block is a single Tab stop: Tab from it jumps to
"Configure LLM"; inside, the arrow keys move between the checkboxes, the narrow
"add" field and its button. The theme dropdown applies live.
"""

from __future__ import annotations

from typing import Literal

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
from ster.tui.check import Check

from .choice_modal import ChoiceModal
from .focus_group import FocusGroup, FormGroup
from .hint_bar import Hint
from .llm_group import LlmSetup
from .local_property_modal import LocalPropertyModal
from .modal import ModalBase


def _pct_display(value: object) -> str:
    """A stored 0.0–1.0 coverage threshold as a percent string ('' when unset/invalid),
    e.g. ``1.0`` → ``"100"``, ``0.5`` → ``"50"``."""
    if value in (None, ""):
        return ""
    try:
        return f"{float(value) * 100:g}"  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""


def _pct_parse(raw: str) -> float | None:
    """Parse a percent field back to a 0.0–1.0 threshold (clamped); ``None`` when blank
    or non-numeric, so the caller keeps the stored value."""
    text = raw.strip().rstrip("%").strip()
    try:
        return max(0.0, min(1.0, float(text) / 100))
    except ValueError:
        return None


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


class EnforceShaclRequested(Message):
    """Ask the app to write (or remove) a mandatory SHACL rule for an annotation
    property configured in a catalog.

    *scope* is ``"ontology"`` (require it on the ontology node) or ``"entity"``
    (require it on every owl:Class and skos:Concept). *enforce* True writes the
    rule, False removes it. The app owns the ontology file, so it does the I/O.
    """

    def __init__(self, predicate: str, label: str, enforce: bool, scope: str) -> None:
        super().__init__()
        self.predicate = predicate
        self.label = label
        self.enforce = enforce
        self.scope = scope


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


class _MetaCheckbox(Check):
    """A registered ontology-metadata predicate as a checkbox (ticked = offered in
    "Add metadata"). Carries its predicate URI + display label."""

    def __init__(self, predicate: str, label: str) -> None:
        self.label_text = label or suggest_label(predicate)
        super().__init__(self.label_text, value=True, classes="cfg-mp-box")
        self.predicate = predicate


class _EnforceButton(Button):
    """Per-predicate toggle, styled by standard convention: a green (success) '◆ Enforce
    (SHACL rule)' when not enforced, a red (error) '⊘ Delete SHACL rule' when it is — so
    the create vs destructive action reads at a glance from both colour and icon."""

    def __init__(self, predicate: str, enforce: bool = False) -> None:
        self.predicate = predicate
        self._enforce = enforce
        super().__init__(self._text(), variant=self._variant(), classes="cfg-mp-enforce")

    def _text(self) -> str:
        return "⊘ Delete SHACL rule" if self._enforce else "◆ Enforce (SHACL rule)"

    def _variant(self) -> Literal["success", "error"]:
        return "error" if self._enforce else "success"  # red = destructive, green = create

    @property
    def enforce(self) -> bool:
        return self._enforce

    def toggle(self) -> bool:
        """Flip the enforced state, restyle (label + colour), and return the new state."""
        self._enforce = not self._enforce
        self.label = self._text()
        self.variant = self._variant()  # type: ignore[assignment]
        return self._enforce


class _MetaRow(Horizontal):
    """One catalog row: the offered-checkbox, plus its Enforce/Delete SHACL button when
    semanticlint's opt-in ``enforce`` feature is active (else just the checkbox)."""

    def __init__(self, predicate: str, label: str, enforce: bool = False) -> None:
        super().__init__(classes="cfg-mp-row")
        self._predicate, self._label, self._enforce = predicate, label, enforce
        from ster.plugins import semanticlint

        self._show_enforce = semanticlint.enforce_active()
        if self._show_enforce:
            self.add_class("has-enforce")  # taller row + centred checkbox to match the button

    def compose(self) -> ComposeResult:
        yield _MetaCheckbox(self._predicate, self._label)
        if self._show_enforce:
            yield _EnforceButton(self._predicate, self._enforce)


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
        scope: str = "entity",  # "ontology" | "entity" — SHACL enforcement target
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._initial = list(props)
        self.exit_prev = prev_target  # Shift+Tab target
        self.exit_next = next_target  # Tab target
        self._verifier = verifier
        self._can_declare = can_declare
        self._base_uri = base_uri
        self.scope = scope

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="cfg-mprops"):
            for mp in self._initial:
                yield _MetaRow(mp.predicate, mp.label, mp.enforce)
        yield Button("🔍 Search library…", classes="cfg-mp-search")
        yield Static("or add by URI:", classes="cfg-hint")
        with Horizontal(classes="cfg-mp-add-row"):
            yield Input(placeholder="predicate URI — http://…", classes="cfg-mp-uri")
            yield Input(placeholder="label (optional)", classes="cfg-mp-label")
            yield Button("+", classes="cfg-mp-add")
        if self._can_declare and self._base_uri:
            yield Button("Add local annotation property", classes="cfg-mp-new")

    async def add_predicate(self, predicate: str, label: str) -> None:
        """Mount a checkbox for *predicate* (deduped) and auto-save. Shared by the
        library picker and the typed-URI add."""
        if not predicate or predicate in {cb.predicate for cb in self.query(_MetaCheckbox)}:
            return
        await self.query_one(".cfg-mprops").mount(_MetaRow(predicate, label))
        self.post_message(self.Changed())

    @on(Button.Pressed, ".cfg-mp-search")
    def _on_search(self, event: Button.Pressed) -> None:
        event.stop()
        from .annotation_library_modal import AnnotationLibraryModal

        self.app.push_screen(AnnotationLibraryModal(), self._on_library_pick)

    async def _on_library_pick(self, predicate: str | None) -> None:
        """A property was chosen from the library — add it to this catalog."""
        from . import annotation_library

        prop = annotation_library.get(predicate) if predicate else None
        if prop is not None:
            await self.add_predicate(prop.predicate, prop.label)

    def props(self) -> list[MetaProp]:
        """The ticked predicates as :class:`MetaProp` entries, each carrying its row's
        SHACL-enforce state."""
        return [
            MetaProp(cb.predicate, cb.label_text, enforce=self._enforce_of(cb))
            for cb in self.query(_MetaCheckbox)
            if cb.value
        ]

    @staticmethod
    def _enforce_of(cb: _MetaCheckbox) -> bool:
        """The enforce state of the row *cb* belongs to (its sibling button)."""
        row = cb.parent
        if row is None:
            return False
        buttons = list(row.query(_EnforceButton))
        return bool(buttons) and buttons[0].enforce

    @on(Button.Pressed, ".cfg-mp-enforce")
    def _on_enforce(self, event: Button.Pressed) -> None:
        """Toggle a predicate's SHACL enforcement — ask the app to write/remove the rule
        and persist the flag."""
        event.stop()
        button = event.button
        now = button.toggle()  # type: ignore[attr-defined]
        label = suggest_label(button.predicate)  # type: ignore[attr-defined]
        row = button.parent
        if row is not None:
            checkboxes = list(row.query(_MetaCheckbox))
            if checkboxes:
                label = checkboxes[0].label_text
        self.post_message(
            EnforceShaclRequested(button.predicate, label, now, self.scope)  # type: ignore[attr-defined]
        )
        self.post_message(self.Changed())  # persist the enforce flag into the catalog

    async def add_typed(self) -> None:
        """Mount a checkbox for the typed predicate (deduped); clear the fields."""
        uri = self.query_one(".cfg-mp-uri", Input).value.strip()
        label = self.query_one(".cfg-mp-label", Input).value.strip()
        present = {cb.predicate for cb in self.query(_MetaCheckbox)}
        if not uri or uri in present:
            return
        await self.query_one(".cfg-mprops").mount(_MetaRow(uri, label))
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
        await self.query_one(".cfg-mprops").mount(_MetaRow(uri, label))
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
        # Each row contributes its offered-checkbox then its Enforce/Delete button, in
        # order, so Up/Down rove offered → enforce → next row's offered → …
        rows: list = []
        for row in self.query(_MetaRow):
            rows.extend(row.query(_MetaCheckbox))
            rows.extend(row.query(_EnforceButton))
        return [
            *rows,
            *self.query(".cfg-mp-search"),
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
            item.scroll_visible()
            item.focus()  # the enforce button / add field / + button (Enter presses it)

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
        with Vertical(id="cfg-box", classes="modal-box"), TabbedContent():
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

    def footer_hints(self) -> list[Hint]:
        return [
            Hint("arrows", "move"),
            Hint("esc", "close", "cancel"),
            Hint("↻", "changes save automatically"),
        ]

    def _plugins_tab(self) -> ComposeResult:
        from ster import plugins

        yield Static(
            "Enable optional in-tree plugins. Each adds its own features (and config tab).",
            classes="cfg-tab-intro",
        )
        blocks = [
            Vertical(
                Check(spec.name, value=plugins.is_enabled(spec.id), id=f"cfg-plugin-{spec.id}"),
                Static(spec.description, classes="cfg-plugin-desc"),
                classes="cfg-plugin-block",
            )
            for spec in plugins.all_plugins()
        ]
        yield FormGroup(*blocks, id="cfg-plugins-group")  # one Tab stop, arrows rove the cards

    #: feature toggles surfaced in the Semantic Lint tab (id suffix → label).
    _SL_FEATURES = (
        ("icons", "Colour entity icons by issue severity"),
        ("detail", "Annotate issues in the detail panel"),
        ("quality_block", "Show the Quality & Coverage block"),
        ("check_on_open", "Check the file for errors when it opens"),
        ("enforce", "Enforce properties with SHACL rules (author shapes.ttl)"),
    )
    #: numeric coverage thresholds (0.0–1.0) offered in the Semantic Lint tab.
    _SL_THRESHOLDS = (
        ("min_label_coverage", "Concept prefLabel coverage (QUA001)"),
        ("min_definition_coverage", "Concept definition coverage (QUA002)"),
        ("min_class_label_coverage", "Class label coverage (QUA004)"),
        ("min_property_label_coverage", "Property label coverage (QUA005)"),
    )
    #: threshold name → the quality key holding its per-language "required in" list.
    #: Each maps a label-type coverage to per-language requirements sourced from the
    #: configured languages (definition coverage, QUA002, has no language row).
    _SL_LANG_KEYS = {
        "min_label_coverage": "languages",  # QUA001/QUA003 — concept prefLabel
        "min_class_label_coverage": "class_label_languages",  # QUA004 — class rdfs:label
        "min_property_label_coverage": "property_label_languages",  # QUA005 — property rdfs:label
    }

    @staticmethod
    def _sl_section(title: str, *widgets):  # type: ignore[no-untyped-def]
        """A titled, bordered section for the Semantic Lint tab."""
        section = Vertical(*widgets, classes="cfg-sl-section")
        section.border_title = title
        return section

    def _sl_thresholds(self, cfg: dict):  # type: ignore[no-untyped-def]
        """One group per coverage threshold: the ``name  [nn]%`` row and — for label-type
        coverages — its 'required in language' checkbox row, tucked directly beneath."""
        quality = cfg["quality"]
        for name, label in self._SL_THRESHOLDS:
            row = Horizontal(
                Static(label, classes="cfg-sl-label"),
                Input(
                    value=_pct_display(quality.get(name)),
                    id=f"cfg-slthr-{name}",
                    classes="cfg-sl-input cfg-sl-num",
                ),
                Static("%", classes="cfg-sl-pct"),
                classes="cfg-sl-thresh",
            )
            lang_key = self._SL_LANG_KEYS.get(name)
            members = (
                [row, *self._sl_language_row(lang_key, quality.get(lang_key, []))]
                if lang_key
                else [row]
            )
            yield Vertical(*members, classes="cfg-sl-thresh-group")

    def _sl_language_row(self, lang_key: str, required: list):  # type: ignore[no-untyped-def]
        """A 'required in' row for a label type: one checkbox per configured language
        (checked = every entity of this type must carry a label in that language)."""
        if not self._configured:
            yield Static("  (add configured languages in the General tab)", classes="cfg-hint")
            return
        required_set = set(required)
        yield Horizontal(
            Static("required in:", classes="cfg-sl-langcaption"),
            *(
                Check(
                    lang,
                    value=(lang in required_set),
                    id=f"cfg-sllang-{lang_key}-{lang}",
                    classes="cfg-sl-langbox",
                )
                for lang in self._configured
            ),
            classes="cfg-sl-langrow",
        )

    def _semanticlint_widgets(self):  # type: ignore[no-untyped-def]
        """The Semantic Lint tab body: install status + titled bordered sections
        (features, thresholds, check selection, CI export), all inside one FormGroup so
        the arrow keys rove them (one Tab stop, consistent styling).

        Yields a single FormGroup so this also works standalone when the tab is added
        dynamically via TabbedContent.add_pane (no `with` compose-context needed)."""
        from ster.plugins.semanticlint import config, deps

        cfg = config.load_config()
        sections: list = []
        if not deps.is_installed():
            sections.append(
                Static(
                    "[yellow]semanticlint is not installed.[/] Run: pip install 'ster[semanticlint]'",
                    classes="cfg-hint",
                )
            )
        sections.append(
            self._sl_section(
                "Features",
                *(
                    Check(label, value=cfg["features"].get(name, True), id=f"cfg-slfeat-{name}")
                    for name, label in self._SL_FEATURES
                ),
            )
        )
        sections.append(self._sl_section("Quality thresholds (%)", *self._sl_thresholds(cfg)))
        sections.append(
            self._sl_section(
                "Check selection",
                Static("Run only these checks (ids/prefixes)", classes="cfg-label"),
                Input(
                    value=", ".join(cfg["select"]),
                    id="cfg-slselect",
                    classes="cfg-sl-input cfg-sl-text",
                ),
                Static("Ignore these checks (ids/prefixes)", classes="cfg-label"),
                Input(
                    value=", ".join(cfg["ignore"]),
                    id="cfg-slignore",
                    classes="cfg-sl-input cfg-sl-text",
                ),
            )
        )
        sections.append(
            self._sl_section(
                "GitHub Actions CI",
                Static(
                    "onto-ci.yml drives GitHub CI — export the above to align it:",
                    classes="cfg-hint",
                ),
                Button("Write onto-ci.yml", id="cfg-sl-export", classes="cfg-mp-new"),
            )
        )
        yield FormGroup(*sections, id="cfg-sl-group")

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
                    yield Check(code, value=True, id=f"cfg-chk-{code}")
            with Horizontal(id="cfg-add-row"):
                yield Input(
                    placeholder="add languages, comma-separated — e.g. en, fr, es, de, zh, ar",
                    id="cfg-extra",
                )
                yield Button("+", id="cfg-add")
        yield Static("Configure LLM", classes="cfg-label")
        yield LlmSetup(id="cfg-llm")

    def _props_tab(self) -> ComposeResult:
        yield Static(
            "Set up ster's pre-configured menu options — the annotation properties offered "
            "in the “Add metadata” menus for the ontology and for entities.",
            classes="cfg-tab-intro",
        )
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
                scope="ontology",  # enforced on the ontology node
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
                scope="entity",  # enforced on every owl:Class and skos:Concept
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
            pct = _pct_parse(self.query_one(f"#cfg-slthr-{name}", Input).value)
            if pct is not None:  # blank/invalid → leave unset → keeps the stored/default value
                quality[name] = pct
        # Per-language "required in" lists — the checked configured languages per label
        # type (replaces the old comma-separated QUA003 field; scoped to configured langs).
        if self._configured:
            for lang_key in self._SL_LANG_KEYS.values():
                quality[lang_key] = [
                    lang
                    for lang in self._configured
                    if self.query_one(f"#cfg-sllang-{lang_key}-{lang}", Checkbox).value
                ]
        return {
            "features": features,
            "quality": quality,
            "select": self._csv("#cfg-slselect"),
            "ignore": self._csv("#cfg-slignore"),
        }

    def _csv(self, selector: str) -> list[str]:
        """A comma-separated Input's non-empty, stripped entries."""
        return [c.strip() for c in self.query_one(selector, Input).value.split(",") if c.strip()]

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
        self._save()  # thresholds / languages / select / ignore changed → persist

    @on(Button.Pressed, "#cfg-sl-export")
    def _on_semanticlint_export(self, event: Button.Pressed) -> None:
        event.stop()
        self._save()  # ensure quality.json reflects the current inputs first
        self.post_message(self.WriteOntoCi())

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
