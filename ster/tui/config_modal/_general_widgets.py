"""Small support widgets for the General tab: the masked server-token input and
the two ``FocusGroup`` blocks (local-server fields, configured-languages block)."""

from __future__ import annotations

from textual.widgets import Checkbox, Input

from ..focus_group import FocusGroup


class _SecretInput(Input):
    """An ``Input`` that masks its text, revealing it only while focused."""

    def on_focus(self) -> None:
        self.password = False

    def on_blur(self) -> None:
        self.password = True


class _ServerGroup(FocusGroup):
    """The local-server URL / port / bearer-token fields as one Tab stop."""

    exit_next = "#cfg-langs"
    exit_prev = "#cfg-theme"

    def _items(self) -> list:  # type: ignore[type-arg]
        return list(self.query(Input))


class _LangGroup(FocusGroup):
    """The configured-languages block: the checkboxes *and* the add field/+ button as
    one Tab stop. Space/enter toggles the current checkbox (the rest is inherited)."""

    exit_next = "Tabs"  # last group in the tab → Tab returns to the tab bar
    exit_prev = "#cfg-server"

    def _items(self) -> list:  # type: ignore[type-arg]
        # query (never query_one) so a not-yet-mounted child can't raise.
        return [*self.query(Checkbox), *self.query("#cfg-extra"), *self.query("#cfg-add")]

    def _focus_item(self, item) -> None:  # type: ignore[no-untyped-def]
        for box in self.query(Checkbox):
            box.set_class(box is item, "lang-current")
        # Checkbox → keep focus on the group (so space toggles); field/+ → focus it.
        self.focus() if isinstance(item, Checkbox) else item.focus()

    def _extra_key(self, event) -> bool:  # type: ignore[no-untyped-def]
        return event.key in ("space", "enter") and self._toggle_current()

    def _toggle_current(self) -> bool:
        item = self.current_item()
        if isinstance(item, Checkbox):
            item.value = not item.value
            return True
        return False

    def _clear(self) -> None:
        for box in self.query(Checkbox):
            box.remove_class("lang-current")
