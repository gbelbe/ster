"""Shared Quality & Coverage rows — one source of truth so the ontology overview
and the per-class boxes render identical Health/Completeness labels (each scoped
to its own set of classes). See docs/architecture/detail-presenter.md.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from ster.metadata_coverage import is_labelled
from ster.model import Label, Taxonomy
from ster.nav.logic import DetailField, _bar_stat, _sep, _stat

from .health import gap_row


class _Labelled(Protocol):
    """Anything with an rdfs:label / skos:prefLabel list (RDFClass, Concept, …)."""

    labels: list[Label]


def class_gap_rows(tax: Taxonomy, class_uris: list[str], prefix: str) -> list[DetailField]:
    """The Health checklist over *class_uris*: unlabelled / undocumented counts
    (green at 0, else orange) — same labels everywhere."""
    classes = tax.owl_classes
    unlabelled = sum(1 for u in class_uris if not is_labelled(classes[u]))
    undocumented = sum(1 for u in class_uris if not classes[u].comments)
    return [
        gap_row(f"{prefix}:gap_unlab", "classes unlabelled", unlabelled),
        gap_row(f"{prefix}:gap_undoc", "classes undocumented", undocumented),
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


def _lang_summary(langs: list[str]) -> str:
    return str(len(langs)) + (f" ({', '.join(langs)})" if langs else "")


def languages_section(
    entities: Sequence[_Labelled], prefix: str, configured_langs: list[str] | None = None
) -> list[DetailField]:
    """The 'Languages' subsection: the language set + per-language label coverage over
    *entities* (anything with a ``.labels`` list). Shared by the overview, classes and
    concepts so the label and format stay identical everywhere. When *configured_langs*
    is given it drives the rows; otherwise the languages found on the entities do."""
    total = len(entities)
    if configured_langs is not None:
        langs = list(configured_langs)
    else:
        langs = sorted({lbl.lang for e in entities for lbl in e.labels if lbl.lang})
    fields = [_sep("Languages"), _stat(f"{prefix}:langs", "languages", _lang_summary(langs))]
    for code in langs:
        covered = sum(1 for e in entities if any(lbl.lang == code for lbl in e.labels))
        fields.append(_bar_stat(f"{prefix}:lang_cov:{code}", f"labels · {code}", covered, total))
    return fields
