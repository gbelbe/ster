"""The metadata-catalog editor widget (``_MetaCatalog``): a checklist of offered
predicates plus an add row, as a single Tab stop with its own arrow-key roving."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Collapsible, Input, Static
from textual.widgets._collapsible import CollapsibleTitle

from ster.metadata_coverage import MetaProp

from ..choice_modal import ChoiceModal
from ..focus_group import FocusGroup
from ..local_property_modal import LocalPropertyModal
from ._labels import suggest_label
from ._messages import DeclareAnnotationProperty, EnforceShaclRequested
from ._metadata_widgets import (
    _SEL_MP_LABEL,
    _SEL_MP_URI,
    _SEL_MPROPS,
    _EnforceButton,
    _MetaCheckbox,
    _MetaRow,
)


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
            yield Input(
                placeholder="predicate URI — http://…",  # NOSONAR - placeholder hint text, not a URL
                classes="cfg-mp-uri",
            )
            yield Input(placeholder="label (optional)", classes="cfg-mp-label")
            yield Button("+", classes="cfg-mp-add")
        if self._can_declare and self._base_uri:
            yield Button("Add local annotation property", classes="cfg-mp-new")

    async def add_predicate(self, predicate: str, label: str) -> None:
        """Mount a checkbox for *predicate* (deduped) and auto-save. Shared by the
        library picker and the typed-URI add."""
        if not predicate or predicate in {cb.predicate for cb in self.query(_MetaCheckbox)}:
            return
        await self.query_one(_SEL_MPROPS).mount(_MetaRow(predicate, label))
        self.post_message(self.Changed())

    @on(Button.Pressed, ".cfg-mp-search")
    def _on_search(self, event: Button.Pressed) -> None:
        event.stop()
        from ..annotation_library_modal import AnnotationLibraryModal

        self.app.push_screen(AnnotationLibraryModal(), self._on_library_pick)

    async def _on_library_pick(self, predicate: str | None) -> None:
        """A property was chosen from the library — add it to this catalog."""
        from .. import annotation_library

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
        uri = self.query_one(_SEL_MP_URI, Input).value.strip()
        label = self.query_one(_SEL_MP_LABEL, Input).value.strip()
        present = {cb.predicate for cb in self.query(_MetaCheckbox)}
        if not uri or uri in present:
            return
        await self.query_one(_SEL_MPROPS).mount(_MetaRow(uri, label))
        self.query_one(_SEL_MP_URI, Input).value = ""
        self.query_one(_SEL_MP_LABEL, Input).value = ""
        self.post_message(self.Changed())  # ask the modal to auto-save

    @on(Button.Pressed, ".cfg-mp-add")
    @on(Input.Submitted, f"{_SEL_MP_URI}, {_SEL_MP_LABEL}")
    async def _on_add_or_submit(self, event: Button.Pressed | Input.Submitted) -> None:
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
        await self.query_one(_SEL_MPROPS).mount(_MetaRow(uri, label))
        self.post_message(self.Changed())  # auto-save the catalog
        self.post_message(DeclareAnnotationProperty(uri, label, comment.strip()))

    async def _submit(self) -> None:
        """Add the typed predicate. If it is not a known annotation property, warn
        and ask for confirmation first — *Use it* adds it (declared locally as an
        annotation property when a file is open); Esc/Cancel skips the add."""
        uri = self.query_one(_SEL_MP_URI, Input).value.strip()
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
        uri = self.query_one(_SEL_MP_URI, Input).value.strip()
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
            *self.query(_SEL_MP_URI),
            *self.query(_SEL_MP_LABEL),
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
