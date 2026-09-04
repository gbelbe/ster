"""Building the three navigation trees (unified/ontology/properties) from the taxonomy, including deferred (lazy) node materialization for large taxonomies."""

from __future__ import annotations

from typing import Final

from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from ster.nav.logic import DetailField

from .. import data, detail
from ._constants import (
    _CREATABLE_PROP_KINDS,
    _LARGE_TAXONOMY_THRESHOLD,
    _ONTOLOGY_TREE_SELECTOR,
    _PROP_MENU,
    _TREE_SELECTOR,
)
from ._helpers import _add_prop_uri, _prop_section_key
from ._state import _AppState

_LIT_CLASS: Final = "class"
_LIT_CONCEPT: Final = "concept"
_LIT_INDIVIDUAL: Final = "individual"
_LIT_LINKED: Final = "linked"
_LIT_PROMOTED: Final = "promoted"


class _TreeBuildMixin(_AppState):
    """Mixin: building the three navigation trees (unified/ontology/properties) from the taxonomy, including deferred (lazy) node materialization for large taxonomies."""

    def _index(self, uri: str, node: TreeNode) -> None:
        self._uri_nodes.setdefault(uri, node)

    def _node_icon(self, uri: str, kind: str) -> str:
        """The node's leading glyph, coloured red/orange/green by the worst semanticlint
        severity affecting the entity — only when the plugin's icon feature is on, else
        plain. The on/off flag is cached per tree build (not read per node)."""
        icon = data.ICON.get(kind, "")
        if not self._lint_icons_on:
            return icon
        from ster.tui.plugins.semanticlint_ui import hooks

        colour = hooks.icon_colour(self._lint_index.get(uri))
        return f"[{colour}]{icon}[/{colour}]"

    def _sync_lint_features(self) -> None:
        """Refresh cached lint-feature flags before a tree build (one config read,
        rather than one per node)."""
        from ster.plugins import semanticlint
        from ster.plugins.semanticlint import config

        active = semanticlint.is_active()
        self._lint_icons_on = active and config.feature_enabled("icons")
        self._lint_detail_on = active and config.feature_enabled("detail")
        self._lint_quality_on = active and config.feature_enabled("quality_block")
        # The overview's Quality & Coverage group carries non-lint coverage too, so it
        # stays visible when the plugin is off (unreachable toggle → default on); the
        # feature only hides it while the plugin is active and the user turns it off.
        self._overview_quality_on = (not active) or config.feature_enabled("quality_block")

    def _entity_detail_fields(self, uri: str | None) -> list[DetailField]:
        """The plugin's extra detail rows for entity *uri*: a subtree quality summary
        (quality_block feature) followed by the per-entity issue list (detail feature),
        both inserted after Identity. Empty when neither feature applies."""
        return self._entity_quality_fields(uri) + self._entity_issue_fields(uri)

    def _entity_issue_fields(self, uri: str | None) -> list[DetailField]:
        """The 'Quality issues' detail rows for entity *uri* (empty unless the plugin's
        detail feature is on and the entity has issues)."""
        if not (self._lint_detail_on and uri and self._lint_cache):
            return []
        from ster.plugins.semanticlint import report
        from ster.tui.plugins.semanticlint_ui import hooks

        issues = report.issues_by_subject(self._lint_cache[1]).get(uri, [])
        return hooks.issue_fields(issues)

    def _entity_quality_fields(self, uri: str | None) -> list[DetailField]:
        """A subtree-scoped quality summary for a class / concept / individual / property
        (empty for the overview, or when the quality_block feature is off)."""
        if not (self._lint_quality_on and uri and self._lint_cache):
            return []
        if uri in (detail.OVERVIEW_URI, detail.TAXONOMY_URI, detail.PROPERTIES_URI):
            return []  # the overview already carries the global Errors/Warnings rows
        from ster.plugins.semanticlint import report
        from ster.tui.plugins.semanticlint_ui import hooks

        by_subject = report.issues_by_subject(self._lint_cache[1])
        counts: dict[str, int] = {}
        for entity_uri in self._subtree_uris(uri):
            for issue in by_subject.get(entity_uri, []):
                counts[issue["severity"]] = counts.get(issue["severity"], 0) + 1
        return hooks.quality_summary_fields(counts, title="Issues")

    def _subtree_uris(self, uri: str) -> set[str]:
        """Every entity URI in *uri*'s subtree (class / concept hierarchy), else {uri}."""
        from ster.nav.logic import _subtree_class_uris, _subtree_concept_uris

        if uri in self.tax.owl_classes:
            return set(_subtree_class_uris(self.tax, uri))
        if uri in self.tax.concepts:
            return set(_subtree_concept_uris(self.tax, uri))
        return {uri}

    # Trailing glyph on entities that came from a read-only context file, so a row
    # you cannot edit never looks like one you can.
    _LOCK = " [dim]🔒[/dim]"

    def _row_text(self, uri: str, glyph: str, label: str, suffix: str = "") -> str:
        """The rendered text of a tree row — icon, name, and the read-only lock.

        Every row is built here so the lock cannot be forgotten by one of the
        three node-creating paths (leaf, class, concept).
        """
        lock = "" if uri not in self.tax.context_source else self._LOCK
        return f"{self._node_icon(uri, glyph)} {label}{suffix}{lock}"

    def _leaf(self, parent: TreeNode, uri: str, kind: str, suffix: str = "") -> TreeNode:
        text = self._row_text(uri, kind, data.node_name(self.tax, uri, self.lang, kind), suffix)
        node = parent.add_leaf(text, data=uri)
        self._index(uri, node)
        return node

    def _add_individuals(self, parent: TreeNode, uris: list[str]) -> None:
        """Add individual leaves, deferring very large collections until expanded."""
        if len(self.tax.owl_individuals) <= _LARGE_TAXONOMY_THRESHOLD:
            for uri in uris:
                self._leaf(parent, uri, _LIT_INDIVIDUAL)
            return
        group = parent.add(
            f"{data.ICON['section']} Individuals ({len(uris):,})",
            data=None,
            allow_expand=True,
        )
        self._deferred_individuals[id(group)] = (group, uris)
        group.add_leaf("Loading individuals...", data=None)

    def _load_deferred_individuals(self, node: TreeNode) -> None:
        """Replace a deferred group's placeholder with its individual leaves once."""
        deferred = self._deferred_individuals.pop(id(node), None)
        if deferred is None:
            return
        group, uris = deferred
        group.remove_children()
        for uri in uris:
            self._leaf(group, uri, _LIT_INDIVIDUAL)

    def _use_deferred_tree(self) -> bool:
        """Use shallow tree nodes for large progressive startups."""
        return (
            self._progressive_startup and self._entity_count(self.tax) > _LARGE_TAXONOMY_THRESHOLD
        )

    def _defer_tree_node(self, node: TreeNode, kind: str, skip_puns: bool = True) -> None:
        """Add a placeholder so a node's descendants load on expansion."""
        self._deferred_tree_nodes[id(node)] = (node, kind, skip_puns)
        node.add_leaf("Expand to load children...", data=None)

    def _add_class_shallow(self, parent: TreeNode, uri: str, *, skip_puns: bool) -> None:
        label = data.label_of(self.tax, uri, self.lang)
        node = parent.add(f"{self._node_icon(uri, _LIT_CLASS)} {label}", data=uri)
        self._index(uri, node)
        has_children = bool(data.subclasses(self.tax, uri, self.lang))
        has_individuals = bool(self._individuals_by_class.get(uri))
        if has_children or has_individuals:
            self._defer_tree_node(node, _LIT_CLASS, skip_puns)

    def _add_concept_shallow(self, parent: TreeNode, uri: str) -> None:
        kind = self.tax.node_type(uri)
        glyph = kind if kind in (_LIT_PROMOTED, _LIT_LINKED) else _LIT_CONCEPT
        node = parent.add(
            f"{self._node_icon(uri, glyph)} {data.label_of(self.tax, uri, self.lang)}", data=uri
        )
        self._index(uri, node)
        has_children = bool(data.concept_children(self.tax, uri, self.lang))
        if kind == _LIT_PROMOTED:
            has_children = has_children or any(
                self.tax.node_type(child) == _LIT_CLASS
                for child in data.subclasses(self.tax, uri, self.lang)
            )
        elif kind == _LIT_LINKED:
            focus = self.tax.concepts[uri].focus
            assert focus is not None
            has_children = has_children or bool(self._individuals_by_class.get(focus, []))
        has_children = has_children or bool(
            data.concept_tagged_individuals(self.tax, uri, self.lang)
        )
        if has_children:
            self._defer_tree_node(node, _LIT_CONCEPT)

    def _load_deferred_tree_node(self, node: TreeNode) -> None:
        """Replace a hierarchy placeholder with its immediate children."""
        deferred = self._deferred_tree_nodes.pop(id(node), None)
        if deferred is None:
            return
        parent, kind, skip_puns = deferred
        parent.remove_children()
        uri = parent.data
        assert isinstance(uri, str)
        if kind == _LIT_CLASS:
            for child in data.subclasses(self.tax, uri, self.lang):
                if not skip_puns or self.tax.node_type(child) != _LIT_PROMOTED:
                    self._add_class_shallow(parent, child, skip_puns=skip_puns)
            self._add_individuals(parent, self._individuals_by_class.get(uri, []))
            return
        for child in data.concept_children(self.tax, uri, self.lang):
            self._add_concept_shallow(parent, child)
        self._add_concept_owl_facet(parent, uri, self.tax.node_type(uri))
        self._add_individuals(parent, data.concept_tagged_individuals(self.tax, uri, self.lang))

    def _add_class(self, parent: TreeNode, uri: str, *, skip_puns: bool = True) -> None:
        """Render an OWL class node with its subclasses + individuals. In the Ontology pane
        (``skip_puns=False``) the full OWL hierarchy shows — a pun's class facet is a real
        owl:Class, so it belongs here too. In the Mixed pane's bridge (``skip_puns=True``) a
        pun subclass is left out, since it renders on the SKOS spine instead."""
        if self._use_deferred_tree():
            self._add_class_shallow(parent, uri, skip_puns=skip_puns)
            return
        label = data.label_of(self.tax, uri, self.lang)
        node = parent.add(self._row_text(uri, _LIT_CLASS, label), data=uri)
        self._index(uri, node)
        for sub in data.subclasses(self.tax, uri, self.lang):
            if not skip_puns or self.tax.node_type(sub) != _LIT_PROMOTED:
                self._add_class(node, sub, skip_puns=skip_puns)
        self._add_individuals(node, self._individuals_by_class.get(uri, []))

    def _add_concept(self, parent: TreeNode, uri: str) -> None:
        if self._use_deferred_tree():
            self._add_concept_shallow(parent, uri)
            return
        kind = self.tax.node_type(uri)  # "concept", "promoted" (pun), or "linked" (foaf:focus)
        glyph = kind if kind in (_LIT_PROMOTED, _LIT_LINKED) else _LIT_CONCEPT
        label = data.label_of(self.tax, uri, self.lang)
        node = parent.add(self._row_text(uri, glyph, label), data=uri)
        self._index(uri, node)
        for child in data.concept_children(self.tax, uri, self.lang):
            self._add_concept(node, child)
        self._add_concept_owl_facet(node, uri, kind)
        for ind in data.concept_tagged_individuals(self.tax, uri, self.lang):
            self._leaf(node, ind, _LIT_INDIVIDUAL)  # dct:subject-tagged individuals cluster here

    def _add_concept_owl_facet(self, node: TreeNode, uri: str, kind: str) -> None:
        """Render a concept's OWL facet beneath it: a pun's bridged pure-OWL subclasses, or
        a linked concept's focus-class individuals."""
        if kind == _LIT_PROMOTED:  # bridge: pull the pun's pure-OWL subclasses into the SKOS spine
            for sub in data.subclasses(self.tax, uri, self.lang):
                if self.tax.node_type(sub) == _LIT_CLASS:
                    self._add_class(node, sub)
        elif kind == _LIT_LINKED:  # a foaf:focus link surfaces the linked class's individuals here
            focus = self.tax.concepts[uri].focus
            assert focus is not None  # node_type == "linked" ⇒ focus is set
            for ind in self._individuals_by_class.get(focus, []):
                self._leaf(node, ind, _LIT_INDIVIDUAL)

    def _build_main_trees(self) -> None:
        """Build both stacked main panes — the unified SKOS/OWL tree (#tree) on top and
        the OWL ontology tree (#ont-tree) below — then size them to their content.

        The unified pane is built first so that a pun (which renders in both panes) has its
        ``_uri_nodes`` entry land on its **spine** node — the concept's natural home, where
        selection/navigation should go (``_index`` keeps the first node seen for a URI)."""
        self._deferred_individuals.clear()
        self._deferred_tree_nodes.clear()
        self._build_unified_tree(self.query_one(_TREE_SELECTOR, Tree))
        self._build_ontology_tree(self.query_one(_ONTOLOGY_TREE_SELECTOR, Tree))
        self._apply_layout()

    def _build_unified_tree(self, tree: Tree) -> None:
        """Top pane: the unified SKOS/OWL spine — concept schemes with their concepts
        (and puns, which hang on the SKOS spine). Its header node carries the taxonomy
        overview URI, so selecting it shows the overview in the detail pane."""
        tax, root = self.tax, tree.root
        tax_sec = root.add("Unified tree (SKOS/OWL)", data=detail.TAXONOMY_URI)
        self._index(detail.TAXONOMY_URI, tax_sec)  # focusable (e.g. after deleting a scheme)
        for s_uri in data.scheme_roots(tax, self.lang):
            # A whole scheme can come from a context file, so it carries the lock too.
            sec = tax_sec.add(
                self._row_text(s_uri, "scheme", data.label_of(tax, s_uri, self.lang)), data=s_uri
            )
            self._index(s_uri, sec)
            for c_uri in data.concept_children(tax, s_uri, self.lang):
                self._add_concept(sec, c_uri)
            sec.expand()
        if not tax_sec.children:  # no scheme yet → nudge the user to start
            self._cta(tax_sec, "＋ Add concept scheme", "add_scheme")
        tax_sec.expand()
        self._strip_childless_arrows(root)
        tax_sec.allow_expand = False  # header drives the accordion, not a tree fold → no arrow

    def _build_ontology_tree(self, tree: Tree) -> None:
        """Second pane: the full OWL class hierarchy (including puns — a promoted concept
        appears here as a class as well as in the spine) plus loose, unclassified
        individuals. Its header node carries the ontology overview URI."""
        tax, root = self.tax, tree.root
        ont_sec = root.add("Ontology", data=detail.OVERVIEW_URI)
        self._index(detail.OVERVIEW_URI, ont_sec)  # focusable (e.g. after deleting a root class)
        for uri in data.class_roots(tax, self.lang):
            self._add_class(ont_sec, uri, skip_puns=False)  # full OWL view: puns are classes too

        loose = self._untyped_individuals
        if loose:
            ind_sec = ont_sec.add(f"{data.ICON['section']} Individuals", data=None)
            self._add_individuals(ind_sec, loose)
        if not ont_sec.children:  # nothing here yet → nudge the user to start
            self._cta(ont_sec, "＋ Add class", "create_owl_class")
        ont_sec.expand()
        self._strip_childless_arrows(root)
        ont_sec.allow_expand = False  # header drives the accordion, not a tree fold → no arrow

    def _build_prop_tree(self, tree: Tree) -> None:
        """Bottom pane: properties grouped by kind — Object / Datatype / Annotation
        always shown, plus an orange "Untyped Properties" group for bare
        ``rdf:Property`` entries. Within a group the locally-declared properties come
        first, then predicates merely *used* on the ontology header (e.g.
        ``dcterms:creator``), each flagged with a small ``(ext)`` indicator."""
        tax = self.tax
        # A "Properties" header node is the pane's main entity — selecting it shows the
        # properties overview (all-properties stats + quality). The kind groups nest under it.
        prop_sec = tree.root.add("Properties", data=detail.PROPERTIES_URI)
        self._index(detail.PROPERTIES_URI, prop_sec)
        kind_by_title = {title: kind for kind, title in data.PROPERTY_CATEGORIES}
        for title, local, external in data.property_groups(tax, self.lang):
            label = (
                f"[orange1]{title}[/orange1]" if title == data.UNTYPED_PROPERTIES_TITLE else title
            )
            # Each typed header (Object / Datatype / Annotation) is right-clickable to add a
            # property of that kind (sentinel data); left-click / Enter still just expands it.
            kind = kind_by_title.get(title)
            sec = prop_sec.add(label, data=self._prop_header_data(kind))
            # Index the section under a focus key so a deleted property can land on it.
            self._index(_prop_section_key(kind or "Property"), sec)
            for uri in local:
                self._leaf(sec, uri, "property")
            for uri in external:
                self._leaf(sec, uri, "property", suffix="  [dim](ext)[/dim]")
            if kind in _CREATABLE_PROP_KINDS and not sec.children:  # empty type → nudge to add one
                self._cta(sec, _PROP_MENU[kind][1], _PROP_MENU[kind][2])
            sec.expand()
        prop_sec.expand()
        self._strip_childless_arrows(tree.root)
        prop_sec.allow_expand = False  # header drives the accordion, not a tree fold → no arrow

    @staticmethod
    def _prop_header_data(kind: str | None) -> str | None:
        """The right-click 'add property' sentinel for a creatable header kind (Object /
        Datatype / Annotation), or None for the catch-all Untyped Properties group."""
        if kind is not None and kind in _CREATABLE_PROP_KINDS:
            return _add_prop_uri(kind)
        return None

    @staticmethod
    def _strip_childless_arrows(root: TreeNode) -> None:
        """Drop the expand/collapse arrow from every node that has no children.

        An arrow on a childless node misleadingly hints at a drill-down (click /
        Enter to open) when there is nothing below it. Nodes keep their arrow only
        when they actually have a subtree.
        """
        stack = list(root.children)
        while stack:
            node = stack.pop()
            node.allow_expand = bool(node.children)
            stack.extend(node.children)
