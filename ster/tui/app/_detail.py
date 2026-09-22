"""Rendering the right-hand detail pane for whatever entity is selected."""

from __future__ import annotations

from .. import data, detail, edits
from ..detail_view import PLACEHOLDER, DetailView
from ._constants import _DETAIL_SELECTOR, _KIND_TITLE
from ._helpers import _publish_selection
from ._state import _AppState


class _DetailMixin(_AppState):
    """Mixin: rendering the right-hand detail pane for whatever entity is selected."""

    def _show(self, uri: str | None) -> None:
        # _detail_text mirrors the rendered markup (used by tests + as a quick
        # text view); the DetailView builds the composed, focusable widgets.
        self._detail_uri = uri
        _publish_selection(uri)  # so the MCP server knows what the user is looking at
        clangs = self.configured_langs or [self.lang]
        self._detail_text = (
            detail.render_detail(self.tax, uri, self.lang, clangs, self.entity_metadata_props)
            if uri
            else PLACEHOLDER
        )
        is_overview = uri == detail.OVERVIEW_URI
        activity = self._ontology_activity() if is_overview else None
        lint = self._ontology_lint()  # whole-file lint (cached); None when plugin inactive
        metadata = self._metadata_coverage() if is_overview else None
        lint_counts = lint[0] if lint else None
        if not is_overview:
            lint_counts = None
        view = self.query_one(_DETAIL_SELECTOR, DetailView)
        view.update_entity(
            self.tax,
            uri,
            self.lang,
            activity,
            lint_counts,  # counts only on the overview
            clangs,
            metadata,
            issue_fields=self._entity_detail_fields(uri),
            quality_block=self._overview_quality_on,
            entity_metadata_props=self.entity_metadata_props,
        )
        view.border_title = self._detail_title(uri)
        # The source face reads the same selection. It is a no-op while the
        # detail face is showing, so navigating costs nothing until asked for.
        self._refresh_source(uri)

    def _metadata_coverage(self) -> dict | None:
        """Ontology/entity metadata-completion percentages vs the configured catalogs."""
        from ster.metadata_coverage import overview_coverage

        return overview_coverage(self.tax, self.metadata_props, self.entity_metadata_props)

    def _ontology_activity(self) -> dict | None:
        """Git edit-activity for the file (computed once per session, cached)."""
        if self._path is None:
            return None
        if not self._activity_computed:
            from ster.git.manager import file_activity

            self._activity_cache = file_activity(self._path)
            self._activity_computed = True
        return self._activity_cache

    def _detail_title(self, uri: str | None) -> str:
        """The detail pane's border title — the current entity, or a generic label.

        Entities that have a context menu get a trailing ``⋯`` to hint that quick
        actions are available (right-click, or press ``.``)."""
        if uri is None:
            return "Details"
        if uri == detail.OVERVIEW_URI:
            return "Ontology overview"
        if uri == detail.TAXONOMY_URI:
            return "Taxonomy overview"
        if uri == detail.PROPERTIES_URI:
            return "Properties overview"
        label = data.label_of(self.tax, uri, self.lang) or "Details"
        kind = data.kind_of(self.tax, uri)
        if self.tax.node_type(uri) == "promoted":  # a pun is both facets — spell it out
            label += " : pun (OWL Class + SKOS Concept)"
        elif type_label := _KIND_TITLE.get(kind):
            label += f" ({type_label})"  # note the resource's type, e.g. 'Person (Class)'
        if edits.context_actions(kind):
            label += "  ⋯"  # a context menu is available
        return label
