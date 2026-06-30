"""P2 — ClassPresenter: gives an owl:Class the consistent Health & Issues section.

A first per-entity migration: the class detail now leads (right after Identity)
with the same actionable Health group the overview uses — this class's own gaps
(missing label / comment, no individuals) — and delegates the rest of the panel
to the existing builder. Subsequent steps fold more sections into the hooks.

See docs/architecture/detail-presenter.md.
"""

from __future__ import annotations

from ster.metadata_coverage import is_labelled
from ster.nav.logic import DetailField, _colored, _sep, _stat, build_rdf_class_detail

from .base import EntityPresenter


def _gap(key: str, label: str) -> DetailField:
    """An actionable gap row (always orange — it exists only when something's missing)."""
    return _colored(_stat(key, label, "—"), "orange")


def _insert_after_identity(base: list[DetailField], extra: list[DetailField]) -> list[DetailField]:
    """Splice *extra* in just after the leading Identity section (before its next
    separator), so the entity's URI still heads the panel."""
    nexts = [i for i, f in enumerate(base) if i and f.meta.get("type", "").startswith("separator")]
    idx = nexts[0] if nexts else len(base)
    return base[:idx] + extra + base[idx:]


class ClassPresenter(EntityPresenter):
    """owl:Class / rdfs:Class detail with a leading Health & Issues section."""

    def health(self) -> list[DetailField]:
        cls = self.tax.owl_classes.get(self.uri)
        if cls is None:
            return []
        gaps: list[DetailField] = []
        if not is_labelled(cls):
            gaps.append(_gap("cls:gap_label", "missing rdfs:label / skos:prefLabel"))
        if not cls.comments:
            gaps.append(_gap("cls:gap_comment", "missing rdfs:comment"))
        if not any(self.uri in ind.types for ind in self.tax.owl_individuals.values()):
            gaps.append(_gap("cls:gap_noind", "no individuals"))
        return [_sep("Health & Issues"), *gaps] if gaps else []

    def render(self) -> list[DetailField]:
        base = build_rdf_class_detail(self.tax, self.uri, self.lang, self.ctx.configured_langs)
        health = self.health()
        return _insert_after_identity(base, health) if (base and health) else base
