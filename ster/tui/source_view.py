"""The right-hand pane's other face: the selected entity as Turtle.

Textual's ``TextArea`` carries syntax highlighting, but only for the grammars
tree-sitter ships — bash, css, go, html, java, javascript, json, markdown,
python, regex, rust, sql, toml, xml, yaml. No RDF among them, which is the same
wall :mod:`ster.tui.sparql_highlight` was written against. A *read-only* pane
does not have to climb it: Pygments has carried a Turtle lexer for years, and
Rich renders it, so this view is a ``Static`` holding a ``Syntax``.

(The trap, since it costs an afternoon to find: Pygments' ``ttl`` alias is
*Tera Term macro*, not Turtle. Ask for ``turtle`` by name.)

Editing is deliberately not here. It needs the regex highlighter and, far more
than that, a way to reconcile arbitrary Turtle against a structured
:class:`~ster.model.Taxonomy` — a different project from showing the text.
"""

from __future__ import annotations

from typing import Any

from rich.syntax import Syntax
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Static

from ..entity_source import EntitySource

PLACEHOLDER = "Select an entity to see its RDF."


class SourceView(VerticalScroll):
    """Read-only Turtle for one entity, with its own statements marked.

    Keyboard model copied from :class:`~ster.tui.detail_view.DetailView` on
    purpose: the two share a slot on the right, and a pane that answers Tab and
    Escape differently depending on which face is showing would be a trap.
    """

    can_focus = True
    # One binding per destination rather than per key: every way out of the pane
    # but Escape means the same thing, and spelling that five times is five
    # places to forget when it changes.
    _LEAVE = "Panels"
    BINDINGS = [
        Binding("escape", "back_to_panel", _LEAVE, show=False),
        Binding("tab,shift+tab,left,right", "leave_to_panel", _LEAVE, show=False),
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._text = ""
        # Where the reader had scrolled each entity, so stepping down the tree
        # and back does not dump them at the top of a file they were mid-way
        # through. Keyed by URI; dropped when the model is rebuilt.
        self._scroll_memory: dict[str, float] = {}
        self._uri: str | None = None

    def compose(self):  # type: ignore[no-untyped-def]
        yield Static(PLACEHOLDER, id="source-body")

    @property
    def text(self) -> str:
        """The Turtle on screen, for the copy action."""
        return self._text

    def _theme_name(self) -> str:
        """A Pygments theme that follows the terminal, not a fixed palette.

        ``ansi_dark`` / ``ansi_light`` draw from the 16 ANSI colours, so the
        pane inherits whatever the user's terminal and Textual theme already
        agreed on instead of importing a second colour scheme beside ster's.
        """
        try:
            return "ansi_dark" if self.app.current_theme.dark else "ansi_light"
        except Exception:  # noqa: BLE001 — a theme is a nicety; never blank the pane
            return "ansi_dark"

    def remember_scroll(self) -> None:
        """Store where the reader is, before the pane is given another entity."""
        if self._uri is not None:
            self._scroll_memory[self._uri] = self.scroll_offset.y

    def forget_scroll(self) -> None:
        """Drop remembered positions — line numbers no longer mean what they meant."""
        self._scroll_memory.clear()

    def show(self, uri: str | None, source: EntitySource | None) -> None:
        """Render *source*, restoring where the reader last was in this entity."""
        self.remember_scroll()
        body = self.query_one("#source-body", Static)
        if uri is None or source is None:
            self._uri, self._text = None, ""
            body.update(PLACEHOLDER)
            return
        self._uri, self._text = uri, source.text
        body.update(
            Syntax(
                source.text,
                "turtle",  # never "ttl" — that alias is a different language
                theme=self._theme_name(),
                line_numbers=True,
                # The entity's own statements, so the inbound half below reads as
                # context rather than as more of the same subject.
                highlight_lines=source.focus_lines,
                word_wrap=True,
                background_color="default",
            )
        )
        self.scroll_to(y=self._scroll_memory.get(uri, 0), animate=False)

    def action_back_to_panel(self) -> None:
        """Escape: leave the pane and re-select the left panel it was reached from."""
        self.app._back_to_panel_selection()  # type: ignore[attr-defined]

    def action_leave_to_panel(self) -> None:
        """Tab / Shift-Tab (and the arrows): back to the exact tree item this came from."""
        self.app._return_to_source_item()  # type: ignore[attr-defined]
