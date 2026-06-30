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


def test_dispatch_routes_to_registered_presenters_else_legacy() -> None:
    """Migrated kinds use their presenter (overview, class); unmigrated kinds (e.g.
    an individual) and the SKOS overview still route through a LegacyPresenter."""
    from ster.tui.presenters.class_ import ClassPresenter
    from ster.tui.presenters.overview import OntologyOverviewPresenter

    tax = store.load(DEMO)
    ctx = _ctx(tax)
    assert isinstance(detail._presenter_for(ctx, detail.OVERVIEW_URI), OntologyOverviewPresenter)
    from ster.tui.presenters.property_ import PropertyPresenter

    assert isinstance(detail._presenter_for(ctx, ZOO + "Cat"), ClassPresenter)
    assert isinstance(detail._presenter_for(ctx, ZOO + "hasAge"), PropertyPresenter)
    assert isinstance(detail._presenter_for(ctx, detail.TAXONOMY_URI), LegacyPresenter)
    assert isinstance(detail._presenter_for(ctx, ZOO + "Rex"), LegacyPresenter)  # individual


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


# ── P2: ClassPresenter Health section ─────────────────────────────────────────


def test_class_presenter_leads_with_health_gaps() -> None:
    """A class detail gains a Health & Issues section (after Identity) listing its
    own gaps; a fully-specified class shows none."""
    from ster.tui.presenters.class_ import ClassPresenter

    tax = store.load(DEMO)
    fields = ClassPresenter(_ctx(tax), ZOO + "Eagle").render()
    seps = [f.display for f in fields if f.meta.get("type", "").startswith("separator")]
    assert seps[0] == "Identity" and seps[1] == "Health & Issues"  # right after identity
    keys = {f.key for f in fields}
    assert "cls:gap_comment" in keys  # Eagle has no rdfs:comment
    assert "cls:gap_noind" in keys  # …and no individuals
    assert "cls:gap_label" not in keys  # but it IS labelled


def test_class_presenter_omits_health_when_clean() -> None:
    """No Health section when the class has a label, a comment and instances."""
    from ster.model import Definition, Label, OWLIndividual, RDFClass
    from ster.tui.presenters.class_ import ClassPresenter

    tax = store.load(DEMO)
    uri = ZOO + "Tidy"
    tax.owl_classes[uri] = RDFClass(
        uri=uri, labels=[Label("en", "Tidy")], comments=[Definition("en", "A tidy class.")]
    )
    tax.owl_individuals[ZOO + "t1"] = OWLIndividual(uri=ZOO + "t1", types=[uri])
    fields = ClassPresenter(_ctx(tax), uri).render()
    assert "Health & Issues" not in [
        f.display for f in fields if f.meta.get("type", "").startswith("separator")
    ]


# ── P3: PropertyPresenter Health section ──────────────────────────────────────


def test_property_presenter_surfaces_missing_domain_range() -> None:
    """A property detail leads with Health & Issues naming its missing domain/range."""
    from ster.tui.presenters.property_ import PropertyPresenter

    tax = store.load(DEMO)
    fields = PropertyPresenter(_ctx(tax), ZOO + "hasAge").render()  # has domain, no range
    seps = [f.display for f in fields if f.meta.get("type", "").startswith("separator")]
    assert seps[0] == "Identity" and seps[1] == "Health & Issues"
    keys = {f.key for f in fields}
    assert "prop:gap_range" in keys  # hasAge has no rdfs:range
    assert "prop:gap_domain" not in keys  # …but it has a domain


def test_property_presenter_omits_health_when_complete() -> None:
    """A fully-specified property (label + domain + range) shows no Health section."""
    from ster.tui.presenters.property_ import PropertyPresenter

    tax = store.load(DEMO)
    fields = PropertyPresenter(_ctx(tax), ZOO + "hasOwner").render()  # domain + range + label
    assert "Health & Issues" not in [
        f.display for f in fields if f.meta.get("type", "").startswith("separator")
    ]
