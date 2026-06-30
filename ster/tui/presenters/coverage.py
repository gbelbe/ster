"""Shared Quality & Coverage rows — one source of truth so the ontology overview
and the per-class boxes render identical Health/Completeness labels (each scoped
to its own set of classes). See docs/architecture/detail-presenter.md.
"""

from __future__ import annotations

from ster.metadata_coverage import is_labelled
from ster.model import Taxonomy
from ster.nav.logic import DetailField, _bar_stat, _sep

from .health import gap_row


def class_gap_rows(tax: Taxonomy, class_uris: list[str], prefix: str) -> list[DetailField]:
    """The Health checklist over *class_uris*: unlabelled / undocumented / no-instances
    counts (green at 0, else orange) — same labels everywhere."""
    classes = tax.owl_classes
    typed = {t for ind in tax.owl_individuals.values() for t in ind.types}
    unlabelled = sum(1 for u in class_uris if not is_labelled(classes[u]))
    undocumented = sum(1 for u in class_uris if not classes[u].comments)
    no_individuals = sum(1 for u in class_uris if u not in typed)
    return [
        gap_row(f"{prefix}:gap_unlab", "classes unlabelled", unlabelled),
        gap_row(f"{prefix}:gap_undoc", "classes undocumented", undocumented),
        gap_row(f"{prefix}:gap_noind", "classes with no individuals", no_individuals),
    ]


def class_completeness_section(
    tax: Taxonomy, class_uris: list[str], prefix: str
) -> list[DetailField]:
    """The 'Completeness' section over *class_uris*: labelled / documented coverage bars
    — same labels and format as the ontology overview."""
    classes = tax.owl_classes
    total = len(class_uris)
    if not total:
        return []
    labelled = sum(1 for u in class_uris if is_labelled(classes[u]))
    commented = sum(1 for u in class_uris if classes[u].comments)
    return [
        _sep("Completeness"),
        _bar_stat(f"{prefix}:label_cov", "labelled (rdfs:label / skos:prefLabel)", labelled, total),
        _bar_stat(f"{prefix}:comment_cov", "documented (rdfs:comment)", commented, total),
    ]
