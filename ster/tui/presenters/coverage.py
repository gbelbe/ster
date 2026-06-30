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
    """One coverage row as a fixed-width table cell set — label, bar, percent
    *present*, and count *missing* in aligned columns so a section reads like a table.
    The label/percent/missing are padded; coloured by the percentage."""
    pct = _pct(present, total)
    missing = total - present
    gap = "complete" if not missing else f"{missing} missing"
    value = f"{_pct_bar(pct)}  {pct:>3}%   {gap:>10}"
    return _colored(_stat(key, label.ljust(label_width), value), _quality_color(pct))


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
