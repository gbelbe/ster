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

    def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(**kwargs)
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
