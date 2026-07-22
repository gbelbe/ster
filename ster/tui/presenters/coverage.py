"""Shared Quality & Coverage rows — one source of truth so the ontology overview
and the per-class boxes render identical Health/Completeness labels (each scoped
to its own set of classes). See docs/architecture/detail-presenter.md.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from ster.metadata_coverage import is_labelled
from ster.model import Label, Taxonomy
from ster.nav.logic import (
    DetailField,
    _bar_stat,
    _colored,
    _pct,
    _pct_bar,
    _quality_color,
    _sep,
    _stat,
)


class _Labelled(Protocol):
    """Anything with an rdfs:label / skos:prefLabel list (RDFClass, Concept, …)."""

    labels: list[Label]


def _coverage_row(key: str, label: str, present: int, total: int, label_width: int) -> DetailField:
    """One coverage row as a fixed-width table cell set — bar, percent *present*, and
    count *missing* in aligned columns so a section reads like a table. The ':' stays
    right after the label; the alignment padding goes after it (at the value's start).
    Coloured by the percentage."""
    pct = _pct(present, total)
    missing = total - present
    gap = "complete" if not missing else f"{missing} missing"
    pad = " " * (label_width - len(label))  # align value columns after the 'label: '
    value = f"{pad}{_pct_bar(pct)}  {pct:>3}%   {gap:>10}"
    return _colored(_stat(key, label, value), _quality_color(pct))


_COMPLETENESS_ROWS = (
    ("label_cov", "labelled (rdfs:label / skos:prefLabel)"),
    ("comment_cov", "documented (rdfs:comment)"),
)
_COMPLETENESS_WIDTH = max(len(label) for _key, label in _COMPLETENESS_ROWS)


def class_completeness_section(
    tax: Taxonomy, class_uris: list[str], prefix: str
) -> list[DetailField]:
    """The 'Completeness' section over *class_uris*: labelled / documented coverage,
    each shown as percent present + count missing (the merged Health metric), in an
    aligned table."""
    classes = tax.owl_classes
    total = len(class_uris)
    if not total:
        return []
    present = {
        "label_cov": sum(1 for u in class_uris if is_labelled(classes[u])),
        "comment_cov": sum(1 for u in class_uris if classes[u].comments),
    }
    return [
        _sep("Completeness"),
        *(
            _coverage_row(f"{prefix}:{key}", label, present[key], total, _COMPLETENESS_WIDTH)
            for key, label in _COMPLETENESS_ROWS
        ),
    ]


def property_completeness_section(props: Sequence[_Labelled], prefix: str) -> list[DetailField]:
    """The 'Completeness' section over *props* — labelled / documented coverage, mirroring
    :func:`class_completeness_section` but for OWL properties (anything with ``.labels`` and
    ``.comments``)."""
    total = len(props)
    if not total:
        return []
    present = {
        "label_cov": sum(1 for p in props if is_labelled(p)),
        "comment_cov": sum(1 for p in props if getattr(p, "comments", None)),
    }
    return [
        _sep("Completeness"),
        *(
            _coverage_row(f"{prefix}:{key}", label, present[key], total, _COMPLETENESS_WIDTH)
            for key, label in _COMPLETENESS_ROWS
        ),
    ]


def languages_section(
    entities: Sequence[_Labelled], prefix: str, configured_langs: list[str] | None = None
) -> list[DetailField]:
    """The 'Languages' subsection: one per-language label-coverage bar over *entities*
    (anything with a ``.labels`` list). Shared by the overview, classes and concepts so
    the label and format stay identical everywhere. When *configured_langs* is given it
    drives the rows; otherwise the languages found on the entities do. Empty when there
    are no languages."""
    total = len(entities)
    if configured_langs is not None:
        langs = list(configured_langs)
    else:
        langs = sorted({lbl.lang for e in entities for lbl in e.labels if lbl.lang})
    if not langs:
        return []
    fields: list[DetailField] = [_sep("Languages")]
    for code in langs:
        covered = sum(1 for e in entities if any(lbl.lang == code for lbl in e.labels))
        fields.append(_bar_stat(f"{prefix}:lang_cov:{code}", f"labels · {code}", covered, total))
    return fields
