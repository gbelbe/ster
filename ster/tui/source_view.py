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

from typing import Any, Final

from rich.syntax import Syntax
from rich.text import Text
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static

from ..entity_source import EntitySource, FileBlock

PLACEHOLDER = "Select an entity to see its RDF."

# What the pane draws, in order: ``(kind, text)`` with kind one of
#   "heading" — a part of the pane (own statements / what points here)
#   "file"    — the file the next Turtle block comes from
#   "turtle"  — statements really in that file, highlighted as code
#   "note"    — anything else ster has to say
# Only "turtle" is ever drawn as Turtle. The rest is ster talking about the
# files, so it is drawn in ster's own style: as a `#` comment it would read as
# though the file contained it.
Part = tuple[str, str]

HEADING: Final = "heading"
FILE: Final = "file"
TURTLE: Final = "turtle"
NOTE: Final = "note"


def _turtle_text(text: str, theme: str) -> Text:
    """Turtle highlighted as styled text, not as a Rich ``Syntax`` renderable.

    Textual can only select text in a widget that renders Text or Content; for
    anything else ``Widget.get_selection`` returns None, which is what made the
    pane impossible to select from. ``Syntax.highlight`` gives the same colours
    as plain styled text. No line numbers: they would count lines of this
    snippet, not of the file, and read as a claim about where it sits.
    """
    syntax = Syntax(text, "turtle", theme=theme, background_color="default")  # never "ttl"
    highlighted = syntax.highlight(text)
    highlighted.rstrip()  # in place: highlight() ends every block with a newline
    return highlighted


def _file_parts(blocks: tuple[FileBlock, ...]) -> list[Part]:
    parts: list[Part] = []
    for block in blocks:
        parts.append((FILE, block.file.name if block.file else "(not saved to a file)"))
        parts.append((TURTLE, block.turtle))
    return parts


def _pointing_heading(source: EntitySource) -> str:
    verb = "statement points" if source.incoming == 1 else "statements point"
    heading = f"{source.incoming} {verb} here"
    if source.omitted:
        heading += f" · {source.incoming - source.omitted} shown, {source.omitted} omitted"
    return heading


def source_parts(uri: str, source: EntitySource) -> list[Part]:
    """Everything the pane draws for *uri*, as typed parts."""
    if not source.own and not source.pointing:
        return [(NOTE, f"{uri} is not in the graph")]
    parts: list[Part] = [(HEADING, "Prefixes"), (TURTLE, source.prefixes)]
    parts.append((HEADING, "Own statements"))
    parts += _file_parts(source.own) or [(NOTE, "No statements of its own")]
    if source.pointing:
        parts.append((HEADING, _pointing_heading(source)))
        parts += _file_parts(source.pointing)
    return parts


class SourceView(VerticalScroll):
    """Read-only Turtle for one entity, one block per file, headed in ster's own style.

    Keyboard model copied from :class:`~ster.tui.detail_view.DetailView` on
    purpose: the two share a slot on the right, and a pane that answers Tab and
    Escape differently depending on which face is showing would be a trap.
    """

    can_focus = True
    # One widget per part, so each is a Text Textual can select. Spacing and the
    # code blocks' shading live here rather than in the renderable.
    DEFAULT_CSS = """
    SourceView #source-body { height: auto; }
    SourceView .source-turtle { margin: 0 0 1 2; background: $boost; }
    SourceView .source-file, SourceView .source-note { margin-left: 2; }
    """
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
        self._parts: list[Part] = []

    def compose(self):  # type: ignore[no-untyped-def]
        with Vertical(id="source-body"):
            yield Static(PLACEHOLDER)

    @property
    def text(self) -> str:
        """The Turtle on screen, without ster's headings — what the copy action takes."""
        return self._text

    @property
    def parts(self) -> list[Part]:
        """What the pane is drawing, as ``(kind, text)`` in order."""
        return list(self._parts)

    def _accent(self) -> str:
        """The theme's accent, so ster's own lines match the rest of the app."""
        try:
            return self.app.current_theme.accent or "cyan"
        except Exception:  # noqa: BLE001 — a colour is a nicety; never blank the pane
            return "cyan"

    def _part_widget(self, kind: str, text: str) -> Static:
        """One part as a Static holding Text — the form Textual can select."""
        if kind == TURTLE:
            content = _turtle_text(text, self._theme_name())
        elif kind == HEADING:
            content = Text(f"▌ {text}", style=f"bold {self._accent()}")
        elif kind == FILE:
            content = Text(text, style=f"italic {self._accent()}")
        else:
            content = Text(text, style="italic dim")
        return Static(content, classes=f"source-{kind}")

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
        body = self.query_one("#source-body", Vertical)
        body.remove_children()
        if uri is None or source is None:
            self._uri, self._text, self._parts = None, "", []
            body.mount(Static(PLACEHOLDER))
            return
        self._uri, self._text = uri, source.text
        self._parts = source_parts(uri, source)
        body.mount_all(self._part_widget(kind, text) for kind, text in self._parts)
        # After the new parts are laid out, or the offset lands on the old height.
        offset = self._scroll_memory.get(uri, 0)
        self.call_after_refresh(self.scroll_to, y=offset, animate=False)

    def action_back_to_panel(self) -> None:
        """Escape: leave the pane and re-select the left panel it was reached from."""
        self.app._back_to_panel_selection()  # type: ignore[attr-defined]

    def action_leave_to_panel(self) -> None:
        """Tab / Shift-Tab (and the arrows): back to the exact tree item this came from."""
        self.app._return_to_source_item()  # type: ignore[attr-defined]
