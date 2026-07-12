"""Edit modal for an OWL property (object / datatype / annotation).

The shared :class:`~ster.tui.entity_form.EntityFormModal` — URI + rdfs:label /
rdfs:comment per configured language. Domain / range are preserved as-is (edited
via the property's context menu), so this works uniformly for every property kind.
Dismisses with ``{"uri": str, "labels": {lang: value}, "comments": {lang: value}}``,
or ``None`` on cancel.
"""

from __future__ import annotations

from collections.abc import Mapping

from .entity_form import EntityFormModal


class PropertyEditModal(EntityFormModal):
    """Edit a property: URI + rdfs:label / rdfs:comment per configured language."""

    BOX_ID = "propedit-box"
    NEEDS_URI_MSG = "A property needs a URI."

    def __init__(
        self,
        *,
        prefix: str,
        fragment: str = "",
        langs: list[str],
        labels: Mapping[str, str] | None = None,
        comments: Mapping[str, str] | None = None,
        title: str = "Edit property",
    ) -> None:
        super().__init__(
            prefix=prefix,
            fragment=fragment,
            langs=langs,
            labels=labels,
            comments=comments,
            title=title,
        )
