"""Entity-detail presenters: a base + per-kind subclasses behind one registry.

See docs/architecture/detail-presenter.md.
"""

from __future__ import annotations

from .base import EntityPresenter, LegacyPresenter
from .context import PresenterContext

# kind (``data.kind_of``) → Presenter subclass. Empty until each kind is migrated
# off its legacy ``build_*`` function; unregistered kinds fall back to a
# LegacyPresenter (see ``ster.tui.detail``).
PRESENTERS: dict[str, type[EntityPresenter]] = {}

__all__ = ["PRESENTERS", "EntityPresenter", "LegacyPresenter", "PresenterContext"]
