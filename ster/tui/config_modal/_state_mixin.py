"""``ConfigModal`` mixin: gathering the current state into the result dict, and
the plain auto-save handlers not owned by a specific tab's own mixin."""

from __future__ import annotations

from textual.widgets import Checkbox, Input, Select

from ._metadata_catalog import _MetaCatalog
from ._state import _ModalState


class _StateMixin(_ModalState):
    """Result-gathering and the generic auto-save handlers (Select/Checkbox
    changes) shared across tabs."""

    def _result(self) -> dict:
        configured = [
            box.id.removeprefix("cfg-chk-")  # type: ignore[union-attr]
            for box in self.query("#cfg-boxes Checkbox").results(Checkbox)
            if box.value
        ]
        from ster import plugins

        result = {
            "display": str(self.query_one("#cfg-display", Select).value),
            "theme": str(self.query_one("#cfg-theme", Select).value),
            "configured": configured,
            "metadata_props": self.query_one("#cfg-ont-meta", _MetaCatalog).props(),
            "entity_metadata_props": self.query_one("#cfg-entity-meta", _MetaCatalog).props(),
            "plugins": {
                spec.id: self.query_one(f"#cfg-plugin-{spec.id}", Checkbox).value
                for spec in plugins.all_plugins()
            },
        }
        if self.query("#cfg-tab-semanticlint"):  # the plugin's tab is mounted
            result["semanticlint"] = self._semanticlint_result()
        return result

    def _csv(self, selector: str) -> list[str]:
        """A comma-separated Input's non-empty, stripped entries."""
        return [c.strip() for c in self.query_one(selector, Input).value.split(",") if c.strip()]

    def _save(self) -> None:
        if self._ready:
            self.post_message(self.Changed(self._result()))

    def on_select_changed(self, event: Select.Changed) -> None:
        self._save()  # display or theme changed → apply live + persist

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        self._save()
