"""Rebuilding only the tree pane(s) a mutation actually touched, rather than the whole tree."""

from __future__ import annotations

from textual.widgets import Tree

from .. import data
from ._constants import _ONTOLOGY_TREE_SELECTOR, _PROPERTY_TREE_SELECTOR, _TREE_SELECTOR
from ._state import _AppState


class _RebuildMixin(_AppState):
    """Mixin: rebuilding only the tree pane(s) a mutation actually touched, rather than the whole tree."""

    def _rebuild_tree(self) -> None:
        """Rebuild both panes (a full refresh — used on load and whenever a mutation could
        have touched either pane)."""
        self._rebuild_main_tree()
        self._rebuild_prop_tree()

    def _rebuild_main_tree(self) -> None:
        """Rebuild both main panes (classes / individuals / schemes / concepts). Their
        ``_uri_nodes`` entries are dropped and re-added; the prop pane is left untouched."""
        self._sync_lint_features()
        self._individuals_by_class, self._untyped_individuals = data.individual_index(
            self.tax, self.lang
        )
        unified = self.query_one(_TREE_SELECTOR, Tree)
        ont = self.query_one(_ONTOLOGY_TREE_SELECTOR, Tree)
        mains = {unified, ont}
        self._uri_nodes = {u: n for u, n in self._uri_nodes.items() if n.tree not in mains}
        unified.root.remove_children()
        ont.root.remove_children()
        self._build_main_trees()

    def _rebuild_prop_tree(self) -> None:
        """Rebuild only the property pane, leaving the (large) main pane untouched — so a
        property edit doesn't pay to rebuild every class/individual node."""
        self._sync_lint_features()
        props = self.query_one(_PROPERTY_TREE_SELECTOR, Tree)
        self._uri_nodes = {u: n for u, n in self._uri_nodes.items() if n.tree is not props}
        props.root.remove_children()
        self._build_prop_tree(props)

    #: entity kinds that live in each pane — used to rebuild only the pane a mutation touched.
    _MAIN_KINDS = frozenset({"class", "individual", "scheme", "concept"})

    def _affected_panes(self, affected_uris: tuple[str, ...], select: str | None) -> set[str]:
        """Which tree pane(s) a mutation touched → subset of ``{"main", "prop"}``.

        Classifies each affected/selected URI by kind. Falls back to **both** panes whenever
        a URI can't be classified (a deleted URI is gone from the taxonomy → kind 'section';
        a rename cascade) — so the tree can never drift from the model on a wrong guess; the
        worst case is simply a full rebuild, exactly as before."""
        candidates = [u for u in (*affected_uris, select) if u]
        if not candidates:
            return {"main", "prop"}
        panes: set[str] = set()
        for uri in candidates:
            kind = data.kind_of(self.tax, uri)
            if kind == "property":
                panes.add("prop")
            elif kind in self._MAIN_KINDS:
                panes.add("main")
            else:  # unknown / deleted → can't tell which pane changed; rebuild both (safe)
                return {"main", "prop"}
        return panes

    def _rebuild_affected(self, affected_uris: tuple[str, ...], select: str | None) -> None:
        """Rebuild only the pane(s) a mutation touched (both when uncertain)."""
        panes = self._affected_panes(affected_uris, select)
        if "main" in panes:
            self._rebuild_main_tree()
        if "prop" in panes:
            self._rebuild_prop_tree()
