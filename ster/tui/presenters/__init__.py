"""Entity-detail presenters: a base + per-kind subclasses behind one registry.

See docs/architecture/detail-presenter.md.
"""

from __future__ import annotations

from .base import EntityPresenter, LegacyPresenter
from .class_ import ClassPresenter
from .context import PresenterContext
from .property_ import PropertyPresenter

# kind (``data.kind_of``) → Presenter subclass. Unregistered kinds fall back to a
# LegacyPresenter wrapping their legacy ``build_*`` function (see ``ster.tui.detail``).
PRESENTERS: dict[str, type[EntityPresenter]] = {
    "class": ClassPresenter,
    "property": PropertyPresenter,
}

__all__ = [
    "PRESENTERS",
    "ClassPresenter",
    "EntityPresenter",
    "LegacyPresenter",
    "PresenterContext",
    "PropertyPresenter",
]
