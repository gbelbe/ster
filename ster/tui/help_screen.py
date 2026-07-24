"""A scrollable keys-and-actions help overlay for the New-TUI.

Opened with ``?`` (see :class:`~ster.tui.app.OntologyApp`). A modal box that lists
navigation, editing, panes and app keys. Arrows scroll; Esc / q / ? close.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Static

from .hint_bar import Hint
from .modal import ModalBase

_HELP = """\
[bold]Navigation — two layers[/bold]
  The left column has three panes (Mixed SKOS/OWL · Ontology · Properties). You are
  either [i]selecting a pane[/i] (its header, no item highlighted) or [i]inside its tree[/i].

  [bold]Panel layer[/bold]  (cursor on a pane header)
  ↑ / ↓        move between panes
  tab / ← →    move between panes
  enter        open the pane — folds the others, selects its head
  space        fold / unfold the pane

  [bold]Item layer[/bold]  (an item is selected — the head counts too)
  ↑ / ↓        move between items in the tree
  → / tab      cross to the detail pane (the head opens its overview)
  esc          back up to the panel layer (select the pane)
  space        fold / unfold the item
  /            fuzzy search — jump to any entity

[bold]Detail pane[/bold]  (a file must be open)
  ↑ / ↓        move between rows and foldable groups
  enter        edit the focused value, or run the focused action row
  space        fold / unfold the group
  tab          toggle back to the tree item it came from
  esc          back up to the panel layer
  action rows  ✎ edit · + add · ↓ subclass · ↑ link · ⊘ delete · ⇢ convert
  in a modal   enter confirm / select · esc cancel

[bold]Clipboard[/bold]
  ctrl+c       copy the focused element — a URI, label, … — to the clipboard
               (or the mouse selection in the detail pane). Use ctrl+c, not
               cmd+c: macOS terminals grab cmd+c for their own copy.

[bold]Panes[/bold]
  Ontology     classes (with their individuals) · overview · schemes
  Properties   every property — its own pane, always visible
  Details      facts + actions for the selected entity

[bold]App[/bold]
  e / c        expand / collapse the whole tree
  d            cycle theme  (/ → "Change theme" previews them all)
  ?            this help
  q            quit
"""


class HelpScreen(ModalBase[None]):
    """Modal cheat-sheet of keys and actions."""

    DEFAULT_CSS = (
        "#help-box { width: 70%; max-width: 80; max-height: 90%; }"  # chrome from ModalBase
    )

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
        Binding("question_mark", "dismiss", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-box", classes="modal-box"):
            yield Static(_HELP)

    def footer_hints(self) -> list[Hint]:
        return [Hint("↑↓", "scroll"), Hint("esc / q / ?", "close", "dismiss")]

    def on_mount(self) -> None:
        box = self.query_one("#help-box")
        box.border_title = "ster · keys & actions"
        box.focus()
