"""``ConfigModal`` mixin: the Plugins tab (enable/disable in-tree plugins) and
the live add/remove of the Semantic Lint tab when that plugin is toggled.

See ``_general_mixin`` for why handlers use naming-convention dispatch
(``on_checkbox_changed``) instead of ``@on(...)``.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.markup import escape
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
                *self._plugin_problem(spec.id),
                classes="cfg-plugin-block",
            )
            for spec in plugins.all_plugins()
        ]
        yield FormGroup(*blocks, id="cfg-plugins-group")  # one Tab stop, arrows rove the cards

    def _plugin_problem(self, plugin_id: str) -> list[Static]:
        """A warning line under a plugin's card when its package is missing, with the command that fixes it.

        Shown whether or not the plugin is on: switching on a plugin that cannot run used to do nothing and say nothing.
        """
        from ster import plugins

        problem = plugins.missing_dependency(plugin_id)
        return (
            [Static(f"[yellow]{escape(problem)}[/]", classes="cfg-plugin-desc")] if problem else []
        )

    async def on_checkbox_changed(self, event: Checkbox.Changed) -> None:  # noqa: V105
        """Add / remove the Semantic Lint tab live when the plugin is toggled; say so when it cannot run."""
        self._warn_when_plugin_cannot_run(event)
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

    def _warn_when_plugin_cannot_run(self, event: Checkbox.Changed) -> None:
        """A toast when a plugin was just switched on and its package is not installed."""
        from ster import plugins

        prefix = "cfg-plugin-"
        card = event.checkbox.id or ""
        if not (event.value and card.startswith(prefix)):
            return
        if problem := plugins.missing_dependency(card.removeprefix(prefix)):
            self.notify(problem, severity="warning", timeout=15)

    def _trace_panel(self):
        from ster.plugins.query_trace import TracePanel

        return TracePanel(self._project_path)
