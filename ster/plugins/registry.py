"""The static registry of in-tree plugins (lightweight metadata only).

A :class:`PluginSpec` carries just what the config UI needs to *list* a plugin and
what the loader needs to lazily *find* its implementation — never the implementation
itself. Registering a plugin here must not import its heavy modules or any optional
third-party dependency, so importing this module stays cheap and side-effect-free.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PluginSpec:
    """Metadata describing one optional in-tree plugin.

    ``id`` is the stable key used in prefs and lazy imports; ``dependency`` is the
    pip requirement the plugin needs (``""`` when it has no extra dependency), used
    by the plugin's own dependency guard / on-demand install flow.
    """

    id: str
    name: str
    description: str
    dependency: str = ""


# The single source of truth for which plugins exist. Order = display order.
_PLUGINS: tuple[PluginSpec, ...] = (
    PluginSpec(
        id="semanticlint",
        name="Semantic Lint",
        description=(
            "Live ontology quality checks: colour entity icons by issue severity, "
            "annotate problems in the detail panel, and show a quality & coverage "
            "overview — the same checks CI runs, surfaced as you edit."
        ),
        dependency="semanticlint>=0.2",
    ),
)


def all_plugins() -> list[PluginSpec]:
    """Every registered plugin, in display order."""
    return list(_PLUGINS)


def get(plugin_id: str) -> PluginSpec | None:
    """The spec for *plugin_id*, or ``None`` when unknown."""
    return next((spec for spec in _PLUGINS if spec.id == plugin_id), None)
