"""P1 — the reorganized OWL ontology-overview dashboard.

Lays the overview out in the canonical order, leading with actionable signals:
Identity → Health & Issues → Completeness → Structure → Metadata → Activity.
Reuses the existing low-level row helpers and stat keys; only the grouping and
section titles change. See docs/architecture/detail-presenter.md.
"""

from __future__ import annotations

from ster.metadata_coverage import is_labelled
from ster.model import Taxonomy
from ster.nav.logic import (
    DetailField,
    _add_action_field,
    _annotation_rows,
    _bar_stat,
    _class_depths,
    _class_languages,
    _lang_coverage_rows,
    _lint_count_field,
    _ontology_activity_fields,
    _sep,
    _stat,
    _stats_metadata,
    _tui_identity_rows,
)

from .base import EntityPresenter
from .health import gap_row as _gap_row


def _missing_domain_range(tax: Taxonomy) -> int:
    return sum(1 for p in tax.owl_properties.values() if not p.domains or not p.ranges)


def _classes_without_individuals(tax: Taxonomy) -> int:
    typed = {t for ind in tax.owl_individuals.values() for t in ind.types}
    return sum(1 for uri in tax.owl_classes if uri not in typed)


def _root_leaf_counts(tax: Taxonomy) -> tuple[int, int]:
    """``(root_classes, leaf_classes)`` — roots have no in-ontology parent; leaves
    are no class's parent."""
    classes = tax.owl_classes
    parents = {p for c in classes.values() for p in c.sub_class_of if p in classes}
    roots = sum(1 for c in classes.values() if not (set(c.sub_class_of) & classes.keys()))
    leaves = sum(1 for uri in classes if uri not in parents)
    return roots, leaves


def _prop_type_counts(tax: Taxonomy) -> tuple[int, int]:
    """``(object_props, datatype_props)``."""
    props = tax.owl_properties.values()
    return (
        sum(1 for p in props if p.prop_type == "ObjectProperty"),
        sum(1 for p in props if p.prop_type == "DatatypeProperty"),
    )


class OntologyOverviewPresenter(EntityPresenter):
    """The reorganized OWL overview dashboard."""

    def identity(self) -> list[DetailField]:
        fields = [
            _sep("Actions"),
            _add_action_field(
                "action:view_ontology_graph", "⊙ View graph in browser", "view_ontology_graph"
            ),
            _sep("Identity"),
        ]
        fields.extend(_tui_identity_rows(self.tax))
        return fields

    def health(self) -> list[DetailField]:
        """semanticlint counts + structural gaps — the 'what to fix' section."""
        tax, lint = self.tax, self.ctx.lint
        classes = tax.owl_classes
        fields = [_sep("Health & Issues")]
        if lint is not None:
            fields.append(_lint_count_field("error", "Errors", lint.get("error", 0)))
            fields.append(_lint_count_field("warning", "Warnings", lint.get("warning", 0)))
        undocumented = sum(1 for c in classes.values() if not c.comments)
        unlabelled = sum(1 for c in classes.values() if not is_labelled(c))
        fields.append(
            _gap_row(
                "st:incomplete_props", "properties missing domain/range", _missing_domain_range(tax)
            )
        )
        fields.append(_gap_row("st:gap_undoc", "classes undocumented", undocumented))
        fields.append(_gap_row("st:gap_unlab", "classes unlabelled", unlabelled))
        fields.append(
            _gap_row("st:unused", "classes with no individuals", _classes_without_individuals(tax))
        )
        return fields

    def completeness(self) -> list[DetailField]:
        """Coverage bars: labels, docs, metadata, and per-language."""
        classes = self.tax.owl_classes
        total = len(classes)
        fields = [_sep("Completeness")]
        if total:
            labelled = sum(1 for c in classes.values() if is_labelled(c))
            commented = sum(1 for c in classes.values() if c.comments)
            fields.append(
                _bar_stat("st:label_cov", "labelled (rdfs:label / skos:prefLabel)", labelled, total)
            )
            fields.append(
                _bar_stat("st:comment_cov", "documented (rdfs:comment)", commented, total)
            )
        fields.extend(_stats_metadata(self.ctx.metadata))
        clangs = self.ctx.configured_langs
        langs = clangs if clangs is not None else _class_languages(classes)
        fields.append(_sep("Languages"))
        summary = str(len(langs)) + (f" ({', '.join(langs)})" if langs else "")
        fields.append(_stat("st:langs", "languages", summary))
        if total:
            fields.extend(_lang_coverage_rows(classes, langs, total))
        return fields

    def relations(self) -> list[DetailField]:
        """Structure: class / property / individual counts."""
        tax = self.tax
        roots, leaves = _root_leaf_counts(tax)
        obj, datatype = _prop_type_counts(tax)
        fields = [
            _sep("Structure"),
            _stat("st:classes", "classes", str(len(tax.owl_classes))),
            _stat("st:roots", "root classes", str(roots)),
            _stat("st:leaves", "leaf classes", str(leaves)),
            _stat("st:props", "properties", str(len(tax.owl_properties))),
            _stat("st:obj_props", "object", str(obj)),
            _stat("st:dt_props", "datatype", str(datatype)),
            _stat("st:individuals", "individuals", str(len(tax.owl_individuals))),
        ]
        depths = _class_depths(tax)
        if depths:
            fields.append(_stat("st:max_depth", "max depth", str(max(depths.values()))))
        return fields

    def metadata(self) -> list[DetailField]:
        """Editable ontology metadata annotations + add affordance."""
        fields = [_sep("Metadata")]
        for annotation in self.tax.ontology_annotations:
            fields.extend(_annotation_rows(annotation))
        fields.append(
            _add_action_field("action:add_ont_annotation", "＋ Add metadata", "add_ont_annotation")
        )
        return fields

    def actions(self) -> list[DetailField]:
        return _ontology_activity_fields(self.ctx.activity)
