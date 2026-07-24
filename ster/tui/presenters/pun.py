"""PunPresenter — the detail view for a pun (an entity that is *both* a skos:Concept and
an owl:Class, sharing one URI).

A pun otherwise renders with the class presenter alone, hiding its whole SKOS side. This
presenter keeps the class view (with its Quality box) and folds the concept facet into the
matching sections — a badge up top, SKOS prefLabels/altLabels merged into Labels, SKOS
definitions/scope notes into Notes, and the SKOS Hierarchy + Mappings appended — so both
facets are visible in one synthetic view. See docs/architecture/detail-presenter.md.
"""

from __future__ import annotations

from ster.nav.logic import DetailField, _sep, build_concept_detail

from .class_ import ClassPresenter


def _is_sep(field: DetailField) -> bool:
    return field.meta.get("type", "").startswith("separator")


def _section_body(fields: list[DetailField], title: str) -> list[DetailField]:
    """The rows of the section titled *title* (between its separator and the next)."""
    out: list[DetailField] = []
    capturing = False
    for f in fields:
        if _is_sep(f):
            capturing = f.display == title
            continue
        if capturing:
            out.append(f)
    return out


def _whole_section(fields: list[DetailField], title: str) -> list[DetailField]:
    """The section titled *title* including its separator, or [] when it has no rows."""
    body = _section_body(fields, title)
    return [_sep(title), *body] if body else []


def _append_to_section(
    base: list[DetailField], title: str, extra: list[DetailField]
) -> list[DetailField]:
    """Splice *extra* in at the end of the section titled *title* (before the next
    separator), or append the section when it isn't present."""
    if not extra:
        return base
    start = next((i for i, f in enumerate(base) if _is_sep(f) and f.display == title), None)
    if start is None:
        return [*base, _sep(title), *extra]
    end = next((j for j in range(start + 1, len(base)) if _is_sep(base[j])), len(base))
    return base[:end] + extra + base[end:]


class PunPresenter(ClassPresenter):
    """A pun's detail: the class view + Quality box, with the concept facet folded in."""

    def render(self) -> list[DetailField]:
        base = super().render()  # the full class view, including the Quality & Coverage box
        skos = build_concept_detail(
            self.tax, self.uri, self.lang, configured_langs=self.ctx.configured_langs
        )
        # Merge the concept facet into the matching class sections; Mappings (SKOS-only)
        # rides just after the merged Hierarchy.
        base = _append_to_section(base, "Labels", _section_body(skos, "Labels"))
        base = _append_to_section(base, "Notes", _section_body(skos, "Notes"))
        return _append_to_section(
            base, "Hierarchy", _section_body(skos, "Hierarchy") + _whole_section(skos, "Mappings")
        )
