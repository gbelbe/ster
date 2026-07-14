"""Clickable keyboard-shortcut hints shared by every modal.

A modal declares its shortcuts as :class:`Hint`s (via ``ModalBase.footer_hints``);
``ModalBase`` renders them as a :class:`HintBar` docked at the bottom of the box.
An *actionable* hint (one carrying a screen ``action``) renders as a bordered,
Tab-focusable chip that runs its action on Enter or click; a purely informational
hint (navigation, "type to filter") renders as a plain, borderless label.

Defining this here — and mounting it from ``ModalBase`` — means every current and
future modal gets the clickable shortcut bar for free, just by listing its hints.
"""

from __future__ import annotations

from dataclasses import dataclass

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Static


@dataclass(frozen=True)
class Hint:
    """One footer shortcut. ``action`` names a screen action to run when the chip is
    activated (Enter / click); ``None`` marks a non-actionable, informational hint."""

    key: str
    label: str
    action: str | None = None

    @property
    def actionable(self) -> bool:
        return self.action is not None


class HintChip(Static):
    """A bordered, focusable, clickable shortcut chip — Enter or click runs its action."""

    can_focus = True
    BINDINGS = [Binding("enter", "activate", "Activate")]

    def __init__(self, hint: Hint) -> None:
        super().__init__(f"{hint.key}  {hint.label}", classes="hint-chip")
        self._action = hint.action

    async def action_activate(self) -> None:
        await self._run()

    async def on_click(self, event: events.Click) -> None:
        event.stop()
        await self._run()

    async def _run(self) -> None:
        if self._action:
            await self.screen.run_action(self._action)


class HintLabel(Static):
    """A plain, borderless, non-focusable informational hint (e.g. '↑↓ move')."""

    def __init__(self, hint: Hint) -> None:
        super().__init__(f"{hint.key}  {hint.label}", classes="hint-label")


class HintBar(Horizontal):
    """The row of shortcut chips / labels docked at the bottom of a modal box."""

    def __init__(self, hints: list[Hint]) -> None:
        super().__init__(classes="hint-bar")
        self._hints = hints

    def compose(self) -> ComposeResult:
        for hint in self._hints:
            yield HintChip(hint) if hint.actionable else HintLabel(hint)
