"""P2 — ClassPresenter: gives an owl:Class the consistent Health & Issues section.

A first per-entity migration: the class detail now leads (right after Identity)
with the same actionable Health group the overview uses — this class's own gaps
(missing label / comment, no individuals) — and delegates the rest of the panel
to the existing builder. Subsequent steps fold more sections into the hooks.

See docs/architecture/detail-presenter.md.
"""

from __future__ import annotations

from ster.metadata_coverage import is_labelled
from ster.nav.logic import DetailField, build_rdf_class_detail

from .base import EntityPresenter
from .health import gap_row, health_section, insert_after_identity


class ClassPresenter(EntityPresenter):
    """owl:Class / rdfs:Class detail with a leading Health & Issues section."""

    def health(self) -> list[DetailField]:
        cls = self.tax.owl_classes.get(self.uri)
        if cls is None:
            return []
        gaps: list[DetailField] = []
        if not is_labelled(cls):
            gaps.append(gap_row("cls:gap_label", "missing rdfs:label / skos:prefLabel"))
        if not cls.comments:
            gaps.append(gap_row("cls:gap_comment", "missing rdfs:comment"))
        if not any(self.uri in ind.types for ind in self.tax.owl_individuals.values()):
            gaps.append(gap_row("cls:gap_noind", "no individuals"))
        return health_section(gaps)

    def render(self) -> list[DetailField]:
        base = build_rdf_class_detail(self.tax, self.uri, self.lang, self.ctx.configured_langs)
        return insert_after_identity(base, self.health()) if base else base
