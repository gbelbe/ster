"""A scrollable keys-and-actions help overlay for the New-TUI.

Opened with ``?`` (see :class:`~ster.tui.app.OntologyApp`). A modal box that lists
navigation, editing, panes and app keys. Arrows scroll; Esc / q / ? close.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Static

from .modal import ModalBase

_HELP = """\
[bold]Navigation[/bold]
  ↑ / ↓        move between items (wraps around the ends)
  → / ←        enter the detail pane / back to the tree
  tab          cycle the panes
  /            fuzzy search — jump to any entity
  e / c        expand / collapse the class tree

[bold]Editing[/bold]  (a file must be open)
  enter        edit the focused value, or run the focused action row
  action rows  ✎ edit · + add · ↓ subclass · ↑ link · ⊘ delete · ⇢ convert
  in a modal   enter confirm / select · esc cancel

[bold]Panes[/bold]
  Ontology     classes (with their individuals) · overview · schemes
  Properties   every property — its own pane, always visible
  Details      facts + actions for the selected entity

[bold]App[/bold]
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
            yield Static("↑↓ scroll     esc / q / ?  close", classes="modal-footer")

    def on_mount(self) -> None:
        box = self.query_one("#help-box")
        box.border_title = "ster · keys & actions"
        box.focus()
