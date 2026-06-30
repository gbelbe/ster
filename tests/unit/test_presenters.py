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


def _health_by_key(fields: list) -> dict:
    return {f.key: f for f in fields}


def test_class_presenter_health_is_a_stable_subtree_checklist() -> None:
    """Every class shows the same Health categories (after Identity), each a count of
    affected classes in its subtree — green at 0, else orange."""
    from ster.tui.presenters.class_ import ClassPresenter

    tax = store.load(DEMO)
    fields = ClassPresenter(_ctx(tax), ZOO + "Eagle").render()  # leaf: subtree is itself
    seps = [f.display for f in fields if f.meta.get("type", "").startswith("separator")]
    assert seps[0] == "Identity" and seps[1] == "Health & Issues"
    by_key = _health_by_key(fields)
    # all three categories are always present with a numeric count
    assert by_key["cls:gap_unlab"].value == "0"  # Eagle is labelled
    assert by_key["cls:gap_unlab"].meta["color"] == "green"
    assert by_key["cls:gap_undoc"].value == "1"  # no rdfs:comment
    assert by_key["cls:gap_undoc"].meta["color"] == "orange"
    assert by_key["cls:gap_noind"].value == "1"  # no individuals


def test_class_health_counts_over_the_whole_subtree() -> None:
    """A root class counts gaps across its descendants, not just itself."""
    from ster.tui.presenters.class_ import ClassPresenter

    tax = store.load(DEMO)
    by_key = _health_by_key(ClassPresenter(_ctx(tax), ZOO + "Animal").render())
    assert int(by_key["cls:gap_undoc"].value) >= 3  # several undocumented classes below Animal
    assert by_key["cls:gap_unlab"].value == "0"  # all labelled


def test_class_health_all_green_when_subtree_is_clean() -> None:
    """A clean leaf still shows the checklist — all zeros, all green."""
    from ster.model import Definition, Label, OWLIndividual, RDFClass
    from ster.tui.presenters.class_ import ClassPresenter

    tax = store.load(DEMO)
    uri = ZOO + "Tidy"
    tax.owl_classes[uri] = RDFClass(
        uri=uri, labels=[Label("en", "Tidy")], comments=[Definition("en", "A tidy class.")]
    )
    tax.owl_individuals[ZOO + "t1"] = OWLIndividual(uri=ZOO + "t1", types=[uri])
    by_key = _health_by_key(ClassPresenter(_ctx(tax), uri).render())
    assert {by_key[k].value for k in ("cls:gap_unlab", "cls:gap_undoc", "cls:gap_noind")} == {"0"}
    assert all(
        by_key[k].meta["color"] == "green"
        for k in ("cls:gap_unlab", "cls:gap_undoc", "cls:gap_noind")
    )


# ── P3: PropertyPresenter Health section ──────────────────────────────────────


def test_property_presenter_health_is_a_stable_checklist() -> None:
    """A property shows the same three facet categories, each 0 (present) or 1 (missing)."""
    from ster.tui.presenters.property_ import PropertyPresenter

    tax = store.load(DEMO)
    by_key = _health_by_key(PropertyPresenter(_ctx(tax), ZOO + "hasAge").render())  # no range
    assert (
        by_key["prop:gap_domain"].value == "0"
        and by_key["prop:gap_domain"].meta["color"] == "green"
    )
    assert (
        by_key["prop:gap_range"].value == "1" and by_key["prop:gap_range"].meta["color"] == "orange"
    )
    assert by_key["prop:gap_label"].value == "0"


def test_property_health_all_green_when_complete() -> None:
    """A fully-specified property still shows the checklist — all zeros, all green."""
    from ster.tui.presenters.property_ import PropertyPresenter

    tax = store.load(DEMO)
    by_key = _health_by_key(PropertyPresenter(_ctx(tax), ZOO + "hasOwner").render())
    assert {by_key[k].value for k in ("prop:gap_label", "prop:gap_domain", "prop:gap_range")} == {
        "0"
    }
