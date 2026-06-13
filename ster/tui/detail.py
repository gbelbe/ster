"""Group a flat ``DetailField`` list into the sections the Textual DetailView
renders as composable blocks.

``ster.nav.logic.build_*_detail`` emits a flat, separator-delimited list of
``DetailField``; this module turns it into typed ``DetailSection``s. Keeping it
pure (no Textual import) makes the detail seam cheap to unit-test and shared by
every entity view (class, individual, concept, scheme, …).
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field

from ster.nav.logic import DetailField

# Field meta["type"] values that start a new section rather than render a row.
_SEPARATORS = frozenset({"separator", "separator_danger"})


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
