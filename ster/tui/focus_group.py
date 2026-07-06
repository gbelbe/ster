"""A reusable single-Tab-stop container with internal arrow-key navigation.

A ``FocusGroup`` is reached as one Tab stop (Tab/Shift+Tab leave the block as a
whole); inside, the four arrow keys rove a cursor across its inner controls. All
shared behaviour lives here, so a new group only declares its content and
neighbours — change a method here and every group changes together.

Extension points (override to specialise; navigation is inherited):
  ``_items``      — the navigable controls, in order.
  ``_focus_item`` — what "landing on" an item does (default: focus it).
  ``_extra_key``  — handle a non-arrow key (e.g. space to toggle); return ``True``.
  ``_clear``      — clear per-item visual state on exit.
Set ``exit_next`` / ``exit_prev`` to the ``#id`` Tab/Shift+Tab jump to.
"""

from __future__ import annotations

from textual.binding import Binding
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Checkbox


class FocusGroup(Vertical):
    """One Tab stop wrapping several controls, navigated with the arrow keys."""

    can_focus = True
    can_focus_children = False  # the inner items aren't Tab stops — arrows reach them
    exit_next: str | None = None  # widget Tab jumps to
    exit_prev: str | None = None  # widget Shift+Tab jumps to

    BINDINGS = [
        Binding("tab", "exit_next", show=False),
        Binding("shift+tab", "exit_prev", show=False),
    ]

    def __init__(self, *children, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(
            *children, **kwargs
        )  # forward mounted children (e.g. FormGroup(*controls))
        self._cursor = 0
        self._active = False  # True once the arrows have entered the items

    # ── override points ───────────────────────────────────────────────────────
    def _items(self) -> list[Widget]:
        return []

    def _focus_item(self, item: Widget) -> None:
        item.focus()

    def _extra_key(self, event) -> bool:  # type: ignore[no-untyped-def]
        return False

    def _clear(self) -> None:
        pass

    # ── shared behaviour ──────────────────────────────────────────────────────
    def current_item(self) -> Widget | None:
        items = self._items()
        return items[self._cursor] if (self._active and items) else None

    def on_key(self, event) -> None:  # type: ignore[no-untyped-def]
        # A focused field also moves its own text cursor on left/right, but we
        # navigate away so that is invisible.
        if event.key in ("down", "right"):
            self._move(1)
            event.stop()
        elif event.key in ("up", "left"):
            self._move(-1)
            event.stop()
        elif self._extra_key(event):
            event.stop()

    def _move(self, delta: int) -> None:
        items = self._items()
        if not items:
            return
        if not self._active:  # first arrow: land on the first/last item, don't skip it
            self._active = True
            self._cursor = 0 if delta > 0 else len(items) - 1
        else:
            self._cursor = (self._cursor + delta) % len(items)
        self._focus_item(items[self._cursor])

    def _reset(self) -> None:
        self._active = False
        self._clear()

    def _exit(self, target: str | None) -> None:
        self._reset()
        if target:
            matches = self.screen.query(target)
            if matches:
                matches.first().focus()

    def action_exit_next(self) -> None:
        self._exit(self.exit_next)

    def action_exit_prev(self) -> None:
        self._exit(self.exit_prev)


class FormGroup(FocusGroup):
    """A ready-to-use :class:`FocusGroup` for a form: wrap any mix of controls
    (checkboxes, inputs, buttons, selects) and it *auto-discovers* the focusable ones
    for arrow-key roving — no subclassing or ``_items`` needed. Up/Down move between
    controls (Left/Right too, except a focused ``Input`` keeps them for editing);
    Space/Enter toggles the current checkbox. Its ``DEFAULT_CSS`` also gives modal form
    controls consistent, borderless rendering, so any new modal reusing ``FormGroup``
    looks and behaves like the rest without extra styling.

    Set ``exit_next`` / ``exit_prev`` for where Tab / Shift+Tab leave to (both default
    to the tab bar, ``Tabs``)."""

    exit_next = "Tabs"
    exit_prev = "Tabs"

    DEFAULT_CSS = """
    FormGroup { height: auto; }
    /* Default checkbox chrome (a heavy box) reads badly stacked in a modal — flatten
       it and mark the roved-to one instead, like the language / catalog groups. */
    FormGroup Checkbox { border: none; background: transparent; height: auto; padding: 0 1; }
    FormGroup Checkbox.fg-current { background: $secondary 30%; text-style: bold; }
    FormGroup Input { border: round $primary; }
    FormGroup Input:focus { border: round $primary; }
    """

    def _items(self) -> list[Widget]:
        # Every focusable descendant, in DOM (visual) order — no per-group list needed.
        return [w for w in self.query(Widget) if w.can_focus]

    def _focus_item(self, item: Widget) -> None:
        for box in self.query(Checkbox):
            box.set_class(box is item, "fg-current")
        if isinstance(item, Checkbox):
            item.scroll_visible()
            self.focus()  # keep focus on the group so Space toggles + arrows always rove
        else:
            item.focus()  # inputs / buttons / selects take focus directly

    def _extra_key(self, event) -> bool:  # type: ignore[no-untyped-def]
        item = self.current_item()
        if event.key in ("space", "enter") and isinstance(item, Checkbox):
            item.value = not item.value
            return True
        return False

    def _clear(self) -> None:
        for box in self.query(Checkbox):
            box.remove_class("fg-current")
