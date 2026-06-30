"""P5 — ConceptPresenter: the bordered Quality & Coverage box on SKOS concepts.

Like the class presenter, a concept leads (after Identity) with a bordered
'Quality & Coverage' box scoped to its **subtree** (the concept + its narrower
descendants): a Health checklist (concepts without prefLabel / definition) over
the relocated per-property completion bars. See docs/architecture/detail-presenter.md.
"""

from __future__ import annotations

from ster.model import LabelType
from ster.nav.logic import (
    DetailField,
    _concept_completion_fields,
    _subtree_concept_uris,
    build_concept_detail,
)

from .base import EntityPresenter
from .coverage import languages_section
from .health import gap_row, health_section, insert_after_identity, quality_group, strip_sections


def _has_pref_label(concept: object) -> bool:
    return any(lbl.type == LabelType.PREF for lbl in concept.labels)  # type: ignore[attr-defined]


class ConceptPresenter(EntityPresenter):
    """skos:Concept detail with a leading, subtree-scoped Quality & Coverage box."""

    def health(self) -> list[DetailField]:
        if self.uri not in self.tax.concepts:
            return []
        concepts = self.tax.concepts
        subtree = _subtree_concept_uris(self.tax, self.uri)
        no_pref = sum(1 for u in subtree if not _has_pref_label(concepts[u]))
        no_definition = sum(1 for u in subtree if not concepts[u].definitions)
        return health_section(
            [
                gap_row("concept:gap_pref", "concepts without prefLabel", no_pref),
                gap_row("concept:gap_def", "concepts without definition", no_definition),
            ]
        )

    def render(self) -> list[DetailField]:
        base = build_concept_detail(
            self.tax, self.uri, self.lang, configured_langs=self.ctx.configured_langs
        )
        if self.uri not in self.tax.concepts:
            return base
        # Relocate the inline per-property completion bars into the bordered group.
        base = strip_sections(base, prefixes={"Completion —"})
        coverage = _concept_completion_fields(self.tax, self.uri)
        subtree = [self.tax.concepts[u] for u in _subtree_concept_uris(self.tax, self.uri)]
        languages = languages_section(subtree, "concept", self.ctx.configured_langs)
        return insert_after_identity(base, quality_group(self.health(), coverage, languages))
