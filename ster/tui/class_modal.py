"""A full add / edit modal for an OWL class.

Collects everything basic about a class in one place: the URI (fragment-locked)
plus an ``rdfs:label`` and an ``rdfs:comment`` for every *configured* language.
Just the shared :class:`~ster.tui.entity_form.EntityFormModal` — a class has no
fields beyond the common ones. Dismisses with
``{"uri": str, "labels": {lang: value}, "comments": {lang: value}}`` (every
configured language present, empty when blank), or ``None`` on cancel.
"""

from __future__ import annotations

from collections.abc import Mapping

from .entity_form import EntityFormModal


class ClassModal(EntityFormModal):
    """Add or edit a class: URI + rdfs:label / rdfs:comment per configured language."""

    BOX_ID = "class-box"
    NEEDS_URI_MSG = "A class needs a URI."

    def __init__(
        self,
        *,
        prefix: str,
        fragment: str = "",
        langs: list[str],
        labels: Mapping[str, str] | None = None,
        comments: Mapping[str, str] | None = None,
        title: str = "New class",
    ) -> None:
        super().__init__(
            prefix=prefix,
            fragment=fragment,
            langs=langs,
            labels=labels,
            comments=comments,
            title=title,
        )
