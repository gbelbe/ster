"""``ConfigModal`` mixin: the Plugins tab (enable/disable in-tree plugins) and
the live add/remove of the Semantic Lint tab when that plugin is toggled.

See ``_general_mixin`` for why handlers use naming-convention dispatch
(``on_checkbox_changed``) instead of ``@on(...)``.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Checkbox, Static, TabbedContent, TabPane

from ster.tui.check import Check

from ..focus_group import FormGroup
from ._state import _ModalState


class _PluginsMixin(_ModalState):
    """Plugins tab: one card per in-tree plugin, toggled on/off."""

    def _plugins_tab(self) -> ComposeResult:
        from ster import plugins

        yield Static(
            "Enable optional in-tree plugins. Each adds its own features (and config tab).",
            classes="cfg-tab-intro",
        )
        blocks = [
            Vertical(
                Check(spec.name, value=plugins.is_enabled(spec.id), id=f"cfg-plugin-{spec.id}"),
                Static(spec.description, classes="cfg-plugin-desc"),
                classes="cfg-plugin-block",
            )
            for spec in plugins.all_plugins()
        ]
        yield FormGroup(*blocks, id="cfg-plugins-group")  # one Tab stop, arrows rove the cards

    async def on_checkbox_changed(self, event: Checkbox.Changed) -> None:  # noqa: V105
        """Add / remove the Semantic Lint tab live when the plugin is toggled."""
        if event.checkbox.id != "cfg-plugin-semanticlint":
            if event.checkbox.id != "cfg-plugin-mcp":
                return
            tabbed = self.query_one(TabbedContent)
            mounted = bool(self.query("#cfg-tab-mcp"))
            if event.value and not mounted:
                await tabbed.add_pane(
                    TabPane(
                        "MCP",
                        self._trace_panel(),
                        id="cfg-tab-mcp",
                    )
                )
            elif not event.value and mounted:
                await tabbed.remove_pane("cfg-tab-mcp")
            return
        tabbed = self.query_one(TabbedContent)
        mounted = bool(self.query("#cfg-tab-semanticlint"))
        if event.value and not mounted:
            pane = TabPane(
                "Semantic Lint", *self._semanticlint_widgets(), id="cfg-tab-semanticlint"
            )
            await tabbed.add_pane(pane)
        elif not event.value and mounted:
            await tabbed.remove_pane("cfg-tab-semanticlint")

    def _trace_panel(self):
        from ster.plugins.query_trace import TracePanel

        return TracePanel(self._project_path)
