"""P3 — PropertyPresenter: gives an OWL property the consistent Health section.

Leads the property detail (after Identity) with its own actionable gaps —
notably **missing domain / range** — and delegates the rest to the existing
builder. See docs/architecture/detail-presenter.md.
"""

from __future__ import annotations

from ster.metadata_coverage import is_labelled
from ster.nav.logic import DetailField, build_property_detail

from .base import EntityPresenter
from .health import gap_row, health_section, insert_after_identity


class PropertyPresenter(EntityPresenter):
    """OWL property detail with a leading Health & Issues section."""

    def health(self) -> list[DetailField]:
        prop = self.tax.owl_properties.get(self.uri)
        if prop is None:
            return []
        # Same categories on every property; the count is 0 (present) or 1 (missing).
        return health_section(
            [
                gap_row(
                    "prop:gap_label",
                    "missing rdfs:label / skos:prefLabel",
                    int(not is_labelled(prop)),
                ),
                gap_row("prop:gap_domain", "missing rdfs:domain", int(not prop.domains)),
                gap_row("prop:gap_range", "missing rdfs:range", int(not prop.ranges)),
            ]
        )

    def render(self) -> list[DetailField]:
        base = build_property_detail(self.tax, self.uri, self.lang, self.ctx.configured_langs)
        return insert_after_identity(base, self.health()) if base else base
