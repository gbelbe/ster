"""Search-and-add picker over the curated annotation-property library.

Reachable from the config modal's Annotation-properties tab. Type an *intent*
("image", "homepage", "video", "definition", "source"…) to filter well-known
annotation predicates; Enter adds the highlighted one. A leading guidance line spells
out the annotation-vs-real distinction so the choice is unambiguous.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from . import annotation_library as lib
from .modal import ModalBase


class AnnotationLibraryModal(ModalBase[str | None]):
    """Filterable list of curated annotation properties; dismisses with the chosen
    predicate URI (or ``None`` on cancel)."""

    DEFAULT_CSS = """
    #annlib-box { width: 80%; max-height: 85%; }
    #annlib-guidance { color: $text-muted; margin-bottom: 1; }
    #annlib-filter { border: round $primary; margin-bottom: 1; }
    #annlib-list { height: auto; max-height: 16; background: $surface; border: none; }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("up", "cursor_up", "Up", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._visible: list[lib.LibraryProp] = lib.all_props()

    def compose(self) -> ComposeResult:
        with Vertical(id="annlib-box", classes="modal-box"):
            yield Static(lib.GUIDANCE, id="annlib-guidance")
            yield Input(
                placeholder="search — e.g. image, homepage, video, definition, source…",
                id="annlib-filter",
            )
            yield OptionList(id="annlib-list")
            yield Static(
                "type to filter    ↑↓ move    enter add    esc cancel", classes="modal-footer"
            )

    def on_mount(self) -> None:
        self.query_one("#annlib-box").border_title = "Add annotation property from library"
        self._populate(lib.all_props())
        self.query_one("#annlib-filter", Input).focus()

    @staticmethod
    def _row(prop: lib.LibraryProp) -> Option:
        text = Text(prop.label, style="bold")
        text.append(f"  {prop.description}")
        text.append(f"   [{prop.ontology} · {prop.category}]", style="dim")
        return Option(text)

    def _populate(self, props: list[lib.LibraryProp]) -> None:
        self._visible = props
        options = self.query_one(OptionList)
        options.clear_options()
        options.add_options([self._row(p) for p in props])
        if props:
            options.highlighted = 0

    def on_input_changed(self, event: Input.Changed) -> None:
        self._populate(lib.search(event.value))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._select_highlighted()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(self._visible[event.option_index].predicate)

    def _select_highlighted(self) -> None:
        idx = self.query_one(OptionList).highlighted
        if idx is not None and 0 <= idx < len(self._visible):
            self.dismiss(self._visible[idx].predicate)

    def action_cursor_down(self) -> None:
        options = self.query_one(OptionList)
        if options.option_count:
            cur = options.highlighted
            options.highlighted = 0 if cur is None else (cur + 1) % options.option_count

    def action_cursor_up(self) -> None:
        options = self.query_one(OptionList)
        if options.option_count:
            cur = options.highlighted
            options.highlighted = options.option_count - 1 if not cur else cur - 1

    def action_cancel(self) -> None:
        self.dismiss(None)
