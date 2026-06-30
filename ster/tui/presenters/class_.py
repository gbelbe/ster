"""P2 — ClassPresenter: gives an owl:Class the consistent Health & Issues section.

A first per-entity migration: the class detail now leads (right after Identity)
with the same actionable Health group the overview uses — this class's own gaps
(missing label / comment, no individuals) — and delegates the rest of the panel
to the existing builder. Subsequent steps fold more sections into the hooks.

See docs/architecture/detail-presenter.md.
"""

from __future__ import annotations

from ster.metadata_coverage import is_labelled
from ster.nav.logic import DetailField, _subtree_class_uris, build_rdf_class_detail

from .base import EntityPresenter
from .health import gap_row, health_section, insert_after_identity


class ClassPresenter(EntityPresenter):
    """owl:Class / rdfs:Class detail with a leading Health & Issues section.

    The checklist always lists the same categories, each a count of affected
    classes *in this class's subtree* (the class + its descendants) — so a leaf
    reports on itself and a root on its whole branch, consistently."""

    def health(self) -> list[DetailField]:
        if self.uri not in self.tax.owl_classes:
            return []
        classes = self.tax.owl_classes
        subtree = _subtree_class_uris(self.tax, self.uri)
        typed = {t for ind in self.tax.owl_individuals.values() for t in ind.types}
        unlabelled = sum(1 for u in subtree if not is_labelled(classes[u]))
        undocumented = sum(1 for u in subtree if not classes[u].comments)
        no_individuals = sum(1 for u in subtree if u not in typed)
        return health_section(
            [
                gap_row("cls:gap_unlab", "unlabelled classes", unlabelled),
                gap_row("cls:gap_undoc", "undocumented classes", undocumented),
                gap_row("cls:gap_noind", "classes with no individuals", no_individuals),
            ]
        )

    def render(self) -> list[DetailField]:
        base = build_rdf_class_detail(self.tax, self.uri, self.lang, self.ctx.configured_langs)
        return insert_after_identity(base, self.health()) if base else base
