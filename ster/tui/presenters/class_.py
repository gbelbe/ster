"""P2 — ClassPresenter: gives an owl:Class the consistent Health & Issues section.

A first per-entity migration: the class detail now leads (right after Identity)
with the same actionable Health group the overview uses — this class's own gaps
(missing label / comment, no individuals) — and delegates the rest of the panel
to the existing builder. Subsequent steps fold more sections into the hooks.

See docs/architecture/detail-presenter.md.
"""

from __future__ import annotations

from ster.nav.logic import (
    DetailField,
    _class_quality_fields,
    _subtree_class_uris,
    build_rdf_class_detail,
)

from .base import EntityPresenter
from .coverage import class_completeness_section, class_gap_rows
from .health import health_section, insert_after_identity, quality_group, strip_sections


class ClassPresenter(EntityPresenter):
    """owl:Class / rdfs:Class detail with a leading, subtree-scoped Quality & Coverage
    box. It uses the same Health / Completeness rows as the ontology overview
    (presenters.coverage), scoped to the class's subtree, so the two stay aligned —
    plus the class-specific Property Fill detail."""

    def health(self) -> list[DetailField]:
        if self.uri not in self.tax.owl_classes:
            return []
        return health_section(
            class_gap_rows(self.tax, _subtree_class_uris(self.tax, self.uri), "cls")
        )

    def render(self) -> list[DetailField]:
        base = build_rdf_class_detail(self.tax, self.uri, self.lang, self.ctx.configured_langs)
        if self.uri not in self.tax.owl_classes:
            return base
        # Rebuild the quality box from the shared rows; keep only the class-specific
        # Property Fill from the legacy helper.
        base = strip_sections(base, titles={"Subtree Quality", "Property Fill"})
        subtree = _subtree_class_uris(self.tax, self.uri)
        completeness = class_completeness_section(self.tax, subtree, "cls")
        property_fill = strip_sections(
            _class_quality_fields(self.tax, self.uri, self.lang), titles={"Subtree Quality"}
        )
        group = quality_group(self.health(), completeness, property_fill)
        return insert_after_identity(base, group)
