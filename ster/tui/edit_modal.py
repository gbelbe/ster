"""A reusable modal text editor for the Textual TUI.

The editor **auto-saves**: **Esc** closes and keeps the current content (the single-line
``Input`` also accepts **Enter**). The ✕ / click-away discards instead. In ``multiline``
mode (or when the value already contains newlines) it grows into a larger Markdown editor —
**Ctrl+R** toggles a rendered preview, **Ctrl+K** wraps a link, and pasting a URL
auto-inserts ``[url](url)`` (so you never have to type the brackets). The app persists the
saved value asynchronously, so applying an edit is snappy.

``push_screen(EditModal(...), callback)`` delivers the value on close, or ``None`` when
discarded (✕ / click-away).
"""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Input, Markdown, TextArea

from .hint_bar import Hint
from .modal import ModalBase
from .urls import autolink_urls, is_url


class MarkdownEditArea(TextArea):
    """A Markdown ``TextArea`` that auto-links (when :attr:`autolink`): pasting a URL
    inserts ``[url](url)``, and Ctrl+K wraps the selection (or drops a ``[text](url)``
    skeleton) — no brackets to type."""

    BINDINGS = [Binding("ctrl+k", "insert_link", "Insert link", show=False)]

    autolink = True  # per-instance; set False for literal-value editors (may be a bare URL)

    async def _on_paste(self, event: events.Paste) -> None:
        text = event.text.strip()
        if self.autolink and is_url(text):
            event.stop()
            self.insert(f"[{text}]({text})")  # bare URL → editable Markdown link
        else:
            await super()._on_paste(event)

    def action_insert_link(self) -> None:
        self.insert_link()

    def insert_link(self) -> None:
        """Wrap the selection as ``[selection](url)``; with no selection, insert a
        ``[text](url)`` skeleton at the cursor."""
        selection = self.selected_text
        if selection:
            self.replace(f"[{selection}](url)", self.selection.start, self.selection.end)
        else:
            self.insert("[text](url)")


def _markdown_textarea(value: str, autolink: bool) -> TextArea:
    """A soft-wrapping Markdown editor, falling back to plain text when tree-sitter
    highlighting is unavailable — editing must always work."""
    try:
        area = MarkdownEditArea(value, language="markdown", soft_wrap=True, id="edit-area")
    except Exception:  # noqa: BLE001 — highlighting is best-effort; never block editing
        area = MarkdownEditArea(value, soft_wrap=True, id="edit-area")
    area.autolink = autolink
    return area


class EditModal(ModalBase[str | None]):
    """Modal text editor. Auto-saves: Esc closes and keeps the content (single-line also
    accepts Enter); ✕ / click-away discards. *multiline* (or a value containing newlines)
    opens the larger Markdown editor with preview + insert-link. The app persists the saved
    value asynchronously.
    """

    DEFAULT_CSS = """
    #edit-box { width: 60%; }                       /* chrome comes from ModalBase */
    #edit-box.multiline { width: 82%; height: 75%; }
    /* Input's default border is `tall` (dashed in some fonts); id beats Input:focus. */
    #edit-input { border: round $primary; }
    #edit-area { height: 1fr; border: round $primary; }
    #edit-preview { height: 1fr; border: round $primary; padding: 0 1; display: none; }
    /* Swap the editor and the rendered preview via a class on the box. */
    #edit-box.preview #edit-area { display: none; }
    #edit-box.preview #edit-preview { display: block; }
    """

    # The editor auto-saves: Esc closes *and* keeps the current content (Enter also saves the
    # single-line input). The ✕ / click-away discards. The save is persisted asynchronously by
    # the app, so applying an edit is snappy and focus stays on the edited property row.
    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("ctrl+r", "toggle_preview", "Preview"),
    ]

    def __init__(
        self, prompt: str, value: str = "", *, multiline: bool = False, autolink: bool = False
    ) -> None:
        super().__init__()
        self._prompt = prompt
        self._multiline = multiline or ("\n" in value)
        self._autolink = autolink and self._multiline
        # Prose fields link their existing bare URLs on open; literal fields keep them raw.
        self._value = autolink_urls(value) if self._autolink else value

    def compose(self) -> ComposeResult:
        classes = "modal-box multiline" if self._multiline else "modal-box"
        with Vertical(id="edit-box", classes=classes):
            if self._multiline:
                yield _markdown_textarea(self._value, self._autolink)
                with VerticalScroll(id="edit-preview"):
                    yield Markdown(id="edit-preview-md")
            else:
                yield Input(value=self._value, id="edit-input")

    def footer_hints(self) -> list[Hint]:
        if self._multiline:
            return [
                Hint("ctrl+k", "insert link", "insert_link"),
                Hint("ctrl+r", "preview Markdown", "toggle_preview"),
                Hint("esc", "close", "close"),
            ]
        return [Hint("esc", "close", "close")]

    def on_mount(self) -> None:
        # A Markdown-capable editor advertises itself in the title.
        title = f"{self._prompt} - (Markdown Editor)" if self._multiline else self._prompt
        self.query_one("#edit-box").border_title = title
        (self.query_one(TextArea) if self._multiline else self.query_one(Input)).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)  # single-line: Enter saves

    def action_close(self) -> None:
        # Esc / the Close chip auto-saves the current content. In the multi-line editor Enter
        # inserts a newline, so Esc is the way out; single-line also accepts Enter (above).
        self.dismiss(
            self.query_one(TextArea).text if self._multiline else self.query_one(Input).value
        )

    def action_insert_link(self) -> None:
        if self._multiline:  # the chip mirrors the TextArea's Ctrl+K
            self.query_one(MarkdownEditArea).insert_link()

    def action_toggle_preview(self) -> None:
        """Toggle the rendered-Markdown preview against the editor (multi-line only)."""
        if not self._multiline:
            return
        box = self.query_one("#edit-box")
        if box.has_class("preview"):
            box.remove_class("preview")
            self.query_one(TextArea).focus()
        else:
            self.query_one("#edit-preview-md", Markdown).update(self.query_one(TextArea).text)
            box.add_class("preview")
