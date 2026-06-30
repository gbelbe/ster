"""The Presenter base: one canonical section order for every entity.

``render()`` is a template method — it emits the sections in a fixed order and
drops the empty ones; subclasses override only the hooks that apply to their
kind. ``LegacyPresenter`` adapts the pre-existing ``build_*`` functions so the
seam can be introduced before any kind is migrated (byte-identical output).

See docs/architecture/detail-presenter.md.
"""

from __future__ import annotations

from collections.abc import Callable

from ster.nav.logic import DetailField

from .context import PresenterContext

# The canonical section order; each is an overridable hook returning rows.
_SECTION_HOOKS = (
    "identity",
    "health",
    "completeness",
    "relations",
    "metadata",
    "media",
    "actions",
)


class EntityPresenter:
    """Render an entity as an ordered list of ``DetailField`` sections."""

    def __init__(self, ctx: PresenterContext, uri: str) -> None:
        self.ctx = ctx
        self.uri = uri
        self.tax = ctx.tax
        self.lang = ctx.lang

    def render(self) -> list[DetailField]:
        """Concatenate the canonical sections in order (empty ones contribute nothing)."""
        fields: list[DetailField] = []
        for name in _SECTION_HOOKS:
            fields.extend(getattr(self, name)())
        return fields

    # ── canonical section hooks (override per kind; default: nothing) ─────────
    def identity(self) -> list[DetailField]:
        return []

    def health(self) -> list[DetailField]:
        return []

    def completeness(self) -> list[DetailField]:
        return []

    def relations(self) -> list[DetailField]:
        return []

    def metadata(self) -> list[DetailField]:
        return []

    def media(self) -> list[DetailField]:
        return []

    def actions(self) -> list[DetailField]:
        return []


class LegacyPresenter(EntityPresenter):
    """Adapter over a legacy ``build_*`` function — preserves its exact output."""

    def __init__(
        self,
        ctx: PresenterContext,
        uri: str,
        render_fn: Callable[[PresenterContext, str], list[DetailField]],
    ) -> None:
        super().__init__(ctx, uri)
        self._render_fn = render_fn

    def render(self) -> list[DetailField]:
        return self._render_fn(self.ctx, self.uri)
