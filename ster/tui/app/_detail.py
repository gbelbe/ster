"""Rendering the right-hand detail pane for whatever entity is selected."""

from __future__ import annotations

from .. import data, detail, edits
from ..detail_view import PLACEHOLDER, DetailView
from ._constants import _DETAIL_SELECTOR, _KIND_TITLE
from ._helpers import _publish_selection
from ._state import _AppState

DETAIL_SETTLE_S = 0.12  # moves closer together than this are one sweep: the panel waits for its end


class _DetailMixin(_AppState):
    """Mixin: rendering the right-hand detail pane for whatever entity is selected."""

    def _defer_show(self, uri: str | None) -> None:
        """Select *uri* now, draw its detail when the cursor stops moving.

        While someone holds an arrow key the cursor crosses many entities and every detail panel but
        the last is thrown away unread. What the app and the MCP server see as the selection moves at
        once; the panel (the expensive part) is built once, after ``DETAIL_SETTLE_S`` without another
        move. Anything that calls :meth:`_show` itself draws immediately and cancels the wait.
        """
        self._detail_uri = uri
        _publish_selection(uri)
        self._cancel_pending_show()
        self._pending_show = (uri,)
        self._show_timer = self.set_timer(DETAIL_SETTLE_S, self._flush_show)

    def _cancel_pending_show(self) -> None:
        timer = getattr(self, "_show_timer", None)
        if timer is not None:
            timer.stop()
        self._show_timer = None
        self._pending_show = None

    def _flush_show(self) -> None:
        pending = self._pending_show
        self._show_timer = None
        self._pending_show = None
        if pending is not None:
            self._show(pending[0])

    def _show(self, uri: str | None) -> None:
        # _detail_text mirrors the rendered markup (used by tests + as a quick
        # text view); the DetailView builds the composed, focusable widgets.
        self._cancel_pending_show()  # a draw now supersedes one that was waiting
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
        """Ontology/entity metadata-completion percentages vs the configured catalogs.

        Walking every entity costs ~130 ms on a large graph, and the overview is redrawn on each visit,
        so the answer is kept. It is only reused while nothing it depends on has changed: the very
        taxonomy object (an edit or reload swaps in a new one), the configured catalogs, and the size
        of each entity table (a belt for any in-place change). ``_invalidate_lint`` drops it too, as it
        does the lint, at every place the model or the settings change.
        """
        from ster.metadata_coverage import overview_coverage

        key = (
            tuple(self.metadata_props or ()),
            tuple(self.entity_metadata_props or ()),
            len(self.tax.owl_classes),
            len(self.tax.owl_properties),
            len(self.tax.owl_individuals),
            len(self.tax.ontology_annotations),
        )
        cached = getattr(self, "_coverage_cache", None)
        if cached is not None and cached[0] is self.tax and cached[1] == key:
            return cached[2]
        result = overview_coverage(self.tax, self.metadata_props, self.entity_metadata_props)
        self._coverage_cache = (self.tax, key, result)
        return result

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
