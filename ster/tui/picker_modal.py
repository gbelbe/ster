"""A reusable, filterable modal entity picker for the Textual TUI.

Relation actions (add a superclass, re-parent, set a type, relate concepts, …)
need the user to choose an existing entity. ``push_screen(PickerModal(...),
callback)`` shows the candidates and returns the chosen value (a URI), or
``None`` on cancel.

Type to filter the list (harlequin-style ``exact → prefix → fuzzy`` ranking);
the entity *kind* is shown dimmed beside each candidate. Focus stays on the
filter box, so you can type and arrow/select without switching widgets.
"""

from __future__ import annotations

import re

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Input, OptionList
from textual.widgets.option_list import Option

from .hint_bar import Hint
from .modal import ModalBase

_FUZZY_CAP = 20  # stop adding fuzzy matches once we already have this many hits


def rank_options(options: list[tuple[str, str]], query: str) -> list[tuple[str, str]]:
    """Filter+rank ``(label, value)`` options for *query*: exact → prefix → fuzzy.

    Buckets are disjoint (so no de-duping needed); fuzzy matches are a gap-tolerant
    subsequence of the query, added shortest-label-first and only while there are
    fewer than ``_FUZZY_CAP`` hits so far. Empty query returns everything.
    """
    q = query.strip().lower()
    if not q:
        return list(options)
    exact: list[tuple[str, str]] = []
    prefix: list[tuple[str, str]] = []
    rest: list[tuple[str, str]] = []
    for label, value in options:
        low = label.lower()
        if low == q:
            exact.append((label, value))
        elif low.startswith(q):
            prefix.append((label, value))
        else:
            rest.append((label, value))
    ranked = exact + prefix
    if len(ranked) < _FUZZY_CAP:
        pattern = re.compile(".*?".join(re.escape(c) for c in q))
        fuzzy = sorted(
            (lv for lv in rest if pattern.search(lv[0].lower())), key=lambda lv: len(lv[0])
        )
        ranked += fuzzy
    return ranked


class PickerModal(ModalBase[str | None]):
    """Filterable single-select list of (label, value) candidates."""

    DEFAULT_CSS = """
    #picker-box { width: 70%; max-height: 80%; }   /* box chrome from ModalBase */
    #picker-filter { border: none; padding: 0; margin-bottom: 1; background: $surface; }
    /* no border on the list (the box frames it); avoids OptionList's dashed `tall` border */
    #picker-list { height: auto; max-height: 16; background: $surface; border: none; }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("up", "cursor_up", "Up", show=False),
    ]

    def __init__(self, prompt: str, options: list[tuple[str, str]], kind_label: str = "") -> None:
        super().__init__()
        self._prompt = prompt
        self._options = options
        self._kind_label = kind_label
        self._visible: list[tuple[str, str]] = list(options)

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-box", classes="modal-box"):
            yield Input(placeholder="type to filter…", id="picker-filter")
            yield OptionList(id="picker-list")

    def footer_hints(self) -> list[Hint]:
        return [
            Hint("type", "to filter"),
            Hint("↑↓", "move"),
            Hint("⏎", "select", "confirm"),
            Hint("esc", "cancel", "cancel"),
        ]

    def action_confirm(self) -> None:
        self._select_highlighted()

    def on_mount(self) -> None:
        self.query_one("#picker-box").border_title = self._prompt
        self._populate(self._options)
        self.query_one("#picker-filter", Input).focus()  # type to filter straight away

    def _option(self, label: str, value: str) -> Option:
        if not self._kind_label:
            return Option(label)
        text = Text(label)
        text.append(f"   {self._kind_label}", style="dim")
        return Option(text)

    def _populate(self, ranked: list[tuple[str, str]]) -> None:
        self._visible = ranked
        options = self.query_one(OptionList)
        options.clear_options()
        options.add_options([self._option(label, value) for label, value in ranked])
        if ranked:
            options.highlighted = 0

    def on_input_changed(self, event: Input.Changed) -> None:
        self._populate(rank_options(self._options, event.value))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._select_highlighted()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(self._visible[event.option_index][1])

    def _select_highlighted(self) -> None:
        idx = self.query_one(OptionList).highlighted
        if idx is not None and 0 <= idx < len(self._visible):
            self.dismiss(self._visible[idx][1])

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
