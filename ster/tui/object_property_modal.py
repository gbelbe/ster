"""Add modal for an OWL object property.

The shared :class:`~ster.tui.entity_form.EntityFormModal` (URI + rdfs:label /
rdfs:comment per configured language) plus optional ``rdfs:domain`` and
``rdfs:range`` class pickers. Dismisses with the base dict extended by
``{"domain": uri | None, "range": uri | None}``, or ``None`` on cancel.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from textual.app import ComposeResult
from textual.widgets import Select, Static

from .entity_form import EntityFormModal


class ObjectPropertyModal(EntityFormModal):
    """Create an object property: URI + labels/comments per language + domain + range."""

    BOX_ID = "objprop-box"
    NEEDS_URI_MSG = "An object property needs a URI."

    def __init__(
        self,
        *,
        prefix: str,
        fragment: str = "",
        langs: list[str],
        classes: Sequence[tuple[str, str]] = (),  # (label, uri) options for domain/range
        labels: Mapping[str, str] | None = None,
        comments: Mapping[str, str] | None = None,
        title: str = "New object property",
    ) -> None:
        super().__init__(
            prefix=prefix,
            fragment=fragment,
            langs=langs,
            labels=labels,
            comments=comments,
            title=title,
        )
        self._class_options = list(classes)

    def _extra_fields(self) -> ComposeResult:
        self._domain = Select(self._class_options, prompt="(optional) domain class", id="op-domain")
        self._range = Select(self._class_options, prompt="(optional) range class", id="op-range")
        yield Static("rdfs:domain", classes="cm-label")
        yield self._domain
        yield Static("rdfs:range", classes="cm-label")
        yield self._range

    def _augment_result(self, result: dict) -> dict:
        result["domain"] = self._selected(self._domain)
        result["range"] = self._selected(self._range)
        return result

    @staticmethod
    def _selected(select: Select) -> str | None:
        """The chosen class URI, or None when nothing is picked (the blank sentinel)."""
        value = select.value
        return value if isinstance(value, str) else None
