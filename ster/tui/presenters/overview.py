"""P1 — the reorganized OWL ontology-overview dashboard.

Lays the overview out in the canonical order, leading with actionable signals:
Identity → Health & Issues → Completeness → Structure → Metadata → Activity.
Reuses the existing low-level row helpers and stat keys; only the grouping and
section titles change. See docs/architecture/detail-presenter.md.
"""

from __future__ import annotations

from ster.model import Taxonomy
from ster.nav.logic import (
    DetailField,
    _add_action_field,
    _annotation_rows,
    _class_depths,
    _lint_count_field,
    _ontology_activity_fields,
    _sep,
    _sep_group,
    _sep_group_end,
    _stat,
    _stats_metadata,
    _tui_identity_rows,
)

from .base import EntityPresenter
from .coverage import class_completeness_section, languages_section
from .health import gap_row as _gap_row


def _missing_domain_range(tax: Taxonomy) -> int:
    return sum(1 for p in tax.owl_properties.values() if not p.domains or not p.ranges)


def _first_order_class_count(tax: Taxonomy) -> int:
    """First-order classes: those that are no other class's parent (i.e. leaves —
    classes with no subclasses). Everything else is a 'meta class' here."""
    classes = tax.owl_classes
    parents = {p for c in classes.values() for p in c.sub_class_of if p in classes}
    return sum(1 for uri in classes if uri not in parents)


class OntologyOverviewPresenter(EntityPresenter):
    """The OWL overview dashboard: Identity → Metadata → Activity → Structure →
    the bordered Quality & Coverage group."""

    def render(self) -> list[DetailField]:
        fields = [
            *self.identity(),  # 1. URI
            *self.metadata(),  # 2. Metadata (editable annotations)
            *self.actions(),  # 3. Activity
            *self.relations(),  # 4. Structure
        ]
        if self.ctx.quality_block:  # 5. Quality & Coverage box (plugin feature toggle)
            fields += [
                *self.health(),  # Health & Issues …
                *self.completeness(),  # … Completeness / Metadata coverage / Languages
            ]
        return fields

    def identity(self) -> list[DetailField]:
        fields = [_sep("Identity")]
        fields.extend(_tui_identity_rows(self.tax))
        fields.append(
            _add_action_field(
                "action:view_ontology_graph", "⊙ View graph in browser", "view_ontology_graph"
            )
        )
        return fields

    def health(self) -> list[DetailField]:
        """semanticlint counts + structural gaps — the 'what to fix' section.

        Opens the visual 'Quality & Coverage' group. Label/comment gaps live in the
        Completeness rows now (percent + count missing), so Health keeps only the
        genuine issues that aren't a coverage percentage."""
        tax, lint = self.tax, self.ctx.lint
        fields = [_sep_group("Quality & Coverage"), _sep("Health & Issues")]
        if lint is not None:
            fields.append(_lint_count_field("error", "Errors", lint.get("error", 0)))
            fields.append(_lint_count_field("warning", "Warnings", lint.get("warning", 0)))
        fields.append(
            _gap_row(
                "st:incomplete_props", "properties missing domain/range", _missing_domain_range(tax)
            )
        )
        return fields

    def completeness(self) -> list[DetailField]:
        """Coverage bars: labels, docs, metadata, and per-language."""
        classes = self.tax.owl_classes
        fields = class_completeness_section(self.tax, list(classes), "st") or [_sep("Completeness")]
        fields.extend(_stats_metadata(self.ctx.metadata))
        fields.extend(languages_section(list(classes.values()), "st", self.ctx.configured_langs))
        fields.append(_sep_group_end())  # close the 'Quality & Coverage' box
        return fields

    def relations(self) -> list[DetailField]:
        """Structure: class / property / individual counts."""
        tax = self.tax
        total_classes = len(tax.owl_classes)
        first_order = _first_order_class_count(tax)
        fields = [
            _sep("Structure"),
            _stat("st:classes", "classes", str(total_classes)),
            _stat("st:first_order", "Nr of First Order classes", str(first_order)),
            _stat("st:meta_classes", "Nr of Meta Classes", str(total_classes - first_order)),
            _stat("st:props", "properties", str(len(tax.owl_properties))),
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
