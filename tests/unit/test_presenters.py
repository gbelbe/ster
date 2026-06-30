"""P0 scaffold: the Presenter base, registry, and detail.py dispatch seam.

See docs/architecture/detail-presenter.md.
"""

from __future__ import annotations

from pathlib import Path

from ster import store
from ster.nav.logic import DetailField
from ster.tui import detail
from ster.tui.presenters import EntityPresenter, LegacyPresenter, PresenterContext

DEMO = Path(__file__).resolve().parents[2] / "ster" / "tui" / "demo.ttl"
ZOO = "https://example.org/zoo/"


def _ctx(tax) -> PresenterContext:  # noqa: ANN001
    return PresenterContext(tax=tax, lang="en")


def test_render_emits_canonical_section_order() -> None:
    """render() concatenates the seven hooks in their fixed order; empty ones add nothing."""

    class _Probe(EntityPresenter):
        def identity(self):
            return [DetailField("identity", "", "", editable=False)]

        def health(self):
            return []  # empty → contributes nothing

        def completeness(self):
            return [DetailField("completeness", "", "", editable=False)]

        def relations(self):
            return [DetailField("relations", "", "", editable=False)]

        def metadata(self):
            return [DetailField("metadata", "", "", editable=False)]

        def media(self):
            return []

        def actions(self):
            return [DetailField("actions", "", "", editable=False)]

    keys = [f.key for f in _Probe(_ctx(store.load(DEMO)), ZOO).render()]
    assert keys == ["identity", "completeness", "relations", "metadata", "actions"]


def test_base_presenter_renders_nothing_by_default() -> None:
    assert EntityPresenter(_ctx(store.load(DEMO)), ZOO).render() == []


def test_legacy_presenter_delegates_to_its_render_fn() -> None:
    tax = store.load(DEMO)
    marker = [DetailField("x", "", "", editable=False)]
    seen: dict = {}

    def _fn(ctx, uri):  # noqa: ANN001
        seen["ctx"], seen["uri"] = ctx, uri
        return marker

    out = LegacyPresenter(_ctx(tax), ZOO + "Cat", _fn).render()
    assert out is marker
    assert seen["uri"] == ZOO + "Cat" and seen["ctx"].tax is tax


def test_dispatch_falls_back_to_legacy_for_unmigrated_kinds() -> None:
    """Kinds without a dedicated presenter (and the SKOS overview) route through a
    LegacyPresenter; the ontology overview has its own presenter (P1)."""
    from ster.tui.presenters.overview import OntologyOverviewPresenter

    tax = store.load(DEMO)
    ctx = _ctx(tax)
    assert isinstance(detail._presenter_for(ctx, detail.OVERVIEW_URI), OntologyOverviewPresenter)
    assert isinstance(detail._presenter_for(ctx, detail.TAXONOMY_URI), LegacyPresenter)
    assert isinstance(detail._presenter_for(ctx, ZOO + "Cat"), LegacyPresenter)


def test_registered_presenter_takes_priority_over_legacy(monkeypatch) -> None:
    """A kind present in PRESENTERS is instantiated instead of the legacy fallback."""
    sentinel = [DetailField("registered", "", "", editable=False)]

    class _ClassPresenter(EntityPresenter):
        def identity(self):
            return sentinel

    monkeypatch.setitem(detail.PRESENTERS, "class", _ClassPresenter)
    tax = store.load(DEMO)
    presenter = detail._presenter_for(_ctx(tax), ZOO + "Cat")
    assert isinstance(presenter, _ClassPresenter)
    assert presenter.render() == sentinel


def test_overview_routes_through_its_presenter() -> None:
    """detail._fields_for for the overview yields exactly OntologyOverviewPresenter's
    render — the seam delegates rather than duplicating."""
    from ster.tui.presenters.context import PresenterContext
    from ster.tui.presenters.overview import OntologyOverviewPresenter

    tax = store.load(DEMO)
    via_seam = detail._fields_for(tax, detail.OVERVIEW_URI, "en")
    direct = OntologyOverviewPresenter(PresenterContext(tax, "en"), "").render()
    assert [(f.key, f.display) for f in via_seam] == [(f.key, f.display) for f in direct]
