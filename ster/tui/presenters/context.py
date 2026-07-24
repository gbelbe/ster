"""Inputs a presenter needs, bundled so detail-building signatures stop growing.

See docs/architecture/detail-presenter.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from ster.metadata_coverage import MetaProp
from ster.model import Taxonomy


@dataclass(frozen=True)
class PresenterContext:
    """Everything a presenter renders from. Overview-only inputs (``activity`` /
    ``lint`` / ``metadata``) are ``None`` for ordinary entities."""

    tax: Taxonomy
    lang: str = "en"
    configured_langs: list[str] | None = None
    activity: dict | None = None  # git edit activity (overview)
    lint: dict | None = None  # semanticlint severity counts (overview)
    metadata: dict | None = None  # metadata-coverage percentages (overview)
    quality_block: bool = True  # show the overview's Quality & Coverage group (plugin feature)
    entity_metadata_props: list[MetaProp] | None = None  # configured entity-annotation catalog
