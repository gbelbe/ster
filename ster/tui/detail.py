"""Group a flat ``DetailField`` list into the sections the Textual DetailView
renders as composable blocks.

``ster.nav.logic.build_*_detail`` emits a flat, separator-delimited list of
``DetailField``; this module turns it into typed ``DetailSection``s. Keeping it
pure (no Textual import) makes the detail seam cheap to unit-test and shared by
every entity view (class, individual, concept, scheme, …).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field as dc_field

from rich.markup import escape as _esc

from ster.model import Taxonomy
from ster.nav.logic import (
    DetailField,
    build_concept_detail,
    build_individual_detail,
    build_property_detail,
    build_rdf_class_detail,
    build_scheme_detail,
)

from . import data

# Field meta["type"] values that start a new section rather than render a row.
_SEPARATORS = frozenset({"separator", "separator_danger"})

# entity kind (data.kind_of) → its DetailField builder. All share (tax, uri, lang).
_BUILDERS: dict[str, Callable[[Taxonomy, str, str], list[DetailField]]] = {
    "class": build_rdf_class_detail,
    "individual": build_individual_detail,
    "property": build_property_detail,
    "concept": build_concept_detail,
    "scheme": build_scheme_detail,
}


@dataclass
class DetailSection:
    """One titled section of a detail view (e.g. "Identity", "Labels")."""

    title: str
    fields: list[DetailField] = dc_field(default_factory=list)
    danger: bool = False  # True for the "Danger Zone" (separator_danger) section


def group_sections(fields: list[DetailField]) -> list[DetailSection]:
    """Split *fields* into sections at separator rows.

    Fields appearing before the first separator form a leading section with an
    empty title. Separator rows themselves are not included in any section's
    ``fields``.
    """
    sections: list[DetailSection] = []
    current: DetailSection | None = None
    for f in fields:
        ftype = f.meta.get("type")
        if ftype in _SEPARATORS:
            current = DetailSection(title=f.display, danger=(ftype == "separator_danger"))
            sections.append(current)
        else:
            if current is None:
                current = DetailSection(title="")
                sections.append(current)
            current.fields.append(f)
    return sections


def build_sections(tax: Taxonomy, uri: str, lang: str = "en") -> list[DetailSection]:
    """Return the grouped detail sections for *uri*, dispatched by entity kind.

    Returns ``[]`` for a uri with no detail builder (e.g. a tree section node).
    """
    builder = _BUILDERS.get(data.kind_of(tax, uri))
    if builder is None:
        return []
    return group_sections(builder(tax, uri, lang))


def _render_row(f: DetailField) -> str:
    """One detail row as Rich markup: 'label: value', or a dim affordance line."""
    if f.value:
        return f"  {_esc(f.display)}: {_esc(f.value)}"
    return f"  [dim]{_esc(f.display)}[/dim]"


def render_detail(tax: Taxonomy, uri: str, lang: str = "en") -> str:
    """Rich-markup detail for *uri*, grouped into titled sections (read-only).

    Replaces the spike's flat ``data.detail_markup`` — this renders the full
    ``build_*_detail`` field model so the Textual detail view shows the same
    labels / hierarchy / properties / actions as the curses panel.
    """
    lines: list[str] = []
    for sec in build_sections(tax, uri, lang):
        if sec.title:
            style = "bold red" if sec.danger else "bold"
            lines.append(f"[{style}]{_esc(sec.title)}[/]")
        lines.extend(_render_row(f) for f in sec.fields)
    return "\n".join(lines)
