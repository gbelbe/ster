"""ClassPresenter: a subtree-scoped Quality & Coverage box on every owl:Class.

The box (right after Identity) uses the same Completeness / Languages rows as the
ontology overview (presenters.coverage), scoped to the class's subtree, so the two
stay aligned — plus the class-specific Property Fill detail. Label/comment gaps are
carried in the Completeness rows (percent + count missing), so there is no separate
Health section for a class. See docs/architecture/detail-presenter.md.
"""

from __future__ import annotations

from ster.nav.logic import (
    DetailField,
    _class_quality_fields,
    _subtree_class_uris,
    build_rdf_class_detail,
)

from .base import EntityPresenter
from .coverage import class_completeness_section, languages_section
from .health import insert_after_identity, quality_group, strip_sections


class ClassPresenter(EntityPresenter):
    """owl:Class / rdfs:Class detail with a leading, subtree-scoped Quality & Coverage
    box — shown only on classes that have subclasses (a first-order / leaf class has no
    meaningful subtree, so no box). The check is live, so a class that later gains a
    subclass gets the box."""

    def _has_subclasses(self) -> bool:
        return any(self.uri in c.sub_class_of for c in self.tax.owl_classes.values())

    def render(self) -> list[DetailField]:
        base = build_rdf_class_detail(self.tax, self.uri, self.lang, self.ctx.configured_langs)
        if self.uri not in self.tax.owl_classes:
            return base
        # The legacy quality sections move into our box (or are dropped on a leaf).
        base = strip_sections(base, titles={"Subtree Quality", "Property Fill"})
        if not self._has_subclasses():
            return base  # first-order (leaf) class → no Quality & Coverage box
        subtree = _subtree_class_uris(self.tax, self.uri)
        completeness = class_completeness_section(self.tax, subtree, "cls")
        languages = languages_section(
            [self.tax.owl_classes[u] for u in subtree], "cls", self.ctx.configured_langs
        )
        property_fill = strip_sections(
            _class_quality_fields(self.tax, self.uri, self.lang), titles={"Subtree Quality"}
        )
        group = quality_group(completeness, languages, property_fill)
        return insert_after_identity(base, group)
