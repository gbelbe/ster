"""``ConfigModal`` mixin: the Graph Viz tab — the thresholds at which the graph
viewer starts holding detail back, and its auto-save handler.

Every setting here is a node count, and every one exists because the right
number depends on the ontology and on the machine looking at it: a 200-class
vocabulary on a laptop is not a 20,000-individual dataset on a workstation.
The defaults live in :data:`ster.api_server.GRAPH_VIZ_DEFAULTS` and are what a
fresh install uses.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Collapsible, Input, Static

from ._state import _ModalState

# id → (label, hint). Order is the order they appear, grouped below.
_FIELDS: dict[str, tuple[str, str]] = {
    "classCollapse": (
        "Classes / concepts before scoping",
        "Above this many, the first view shows root classes and top concepts only; "
        "the rest arrive when you expand one.",
    ),
    "individualCollapse": (
        "Individuals before collapsing",
        "Above this many, individuals are replaced by a count on their class.",
    ),
    "classExpand": (
        "Individuals per expansion",
        "Most a single class hands back when you open it. The node then reads "
        "“200 of 1477” so nothing is hidden silently.",
    ),
    "lodEdges": (
        "Nodes before hiding edge labels",
        "Above this many nodes, relation names and arrowheads stop being drawn.",
    ),
    "lodNodes": (
        "Nodes before hiding node labels",
        "Above this many nodes, node labels stop being drawn and nodes shrink to "
        "dots. Clicking one still names it.",
    ),
}

_LOAD_FIELDS = ("classCollapse", "individualCollapse", "classExpand")
_DRAW_FIELDS = ("lodEdges", "lodNodes")

_GRAPHVIZ_INPUT_IDS = frozenset(f"cfg-gv-{key}" for key in _FIELDS)


class _GraphVizMixin(_ModalState):
    """Graph Viz tab: how much the graph viewer draws before it holds back."""

    def _graphviz_tab(self) -> ComposeResult:
        from ster.api_server import load_graph_viz_config

        values = load_graph_viz_config()
        yield Static(
            "How much of a graph the viewer draws before it starts holding detail back. "
            "Every value is a number of nodes. Changes apply the next time a graph is opened.",
            classes="cfg-tab-intro",
        )
        with Collapsible(title="How much is loaded", collapsed=False, id="cfg-gv-load-group"):
            yield from self._graphviz_fields(_LOAD_FIELDS, values)
        with Collapsible(title="How much is drawn", collapsed=False, id="cfg-gv-draw-group"):
            yield from self._graphviz_fields(_DRAW_FIELDS, values)

    def _graphviz_fields(self, keys: tuple[str, ...], values: dict[str, int]) -> ComposeResult:
        for key in keys:
            label, hint = _FIELDS[key]
            yield Static(label, classes="cfg-label")
            yield Static(hint, classes="cfg-hint")
            yield Input(
                value=str(values[key]),
                placeholder="a whole number of nodes",
                id=f"cfg-gv-{key}",
                type="integer",
            )

    def on_input_changed(self, event: Input.Changed) -> None:
        """Persist the graph-viewer thresholds (auto-save).

        A field mid-edit is routinely empty or zero, which would mean "collapse
        everything"; those are skipped rather than saved, so clearing a box to
        retype it cannot write a value nobody asked for.
        """
        if event.input.id not in _GRAPHVIZ_INPUT_IDS or not self._ready:
            return
        from ster.api_server import save_graph_viz_config

        values: dict[str, int] = {}
        for key in _FIELDS:
            raw = self.query_one(f"#cfg-gv-{key}", Input).value.strip()
            if raw.isdigit() and int(raw) > 0:
                values[key] = int(raw)
        if values:
            save_graph_viz_config(values)
