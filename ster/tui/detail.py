"""Group a flat ``DetailField`` list into the sections the Textual DetailView
renders as composable blocks.

``ster.nav.logic.build_*_detail`` emits a flat, separator-delimited list of
``DetailField``; this module turns it into typed ``DetailSection``s. Keeping it
pure (no Textual import) makes the detail seam cheap to unit-test and shared by
every entity view (class, individual, concept, scheme, …).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field as dc_field

from rich.markup import escape as _esc

from ster.model import Taxonomy
from ster.nav.logic import (
    DetailField,
    build_concept_detail,
    build_individual_detail,
    build_property_detail,
    build_rdf_class_detail,
    build_scheme_detail,
    build_tui_taxonomy_overview_fields,
)

from . import data
from .presenters import PRESENTERS, EntityPresenter, LegacyPresenter, PresenterContext
from .presenters.overview import OntologyOverviewPresenter

# Sentinel "uris" for the overview nodes (no real entity behind them).
OVERVIEW_URI = "__ster:overview__"  # the Ontology (OWL) overview
TAXONOMY_URI = "__ster:taxonomy__"  # the Taxonomy (SKOS) overview

# Field meta["type"] values that start a new section rather than render a row.
_SEPARATORS = frozenset(
    {
        "separator",
        "separator_danger",
        "separator_group",
        "separator_collapsible",
        "separator_group_end",
    }
)

# entity kind (data.kind_of) → its DetailField builder. All accept the keyword
# ``configured_langs`` (the languages whose label/description add rows to offer).
_BUILDERS: dict[str, Callable[..., list[DetailField]]] = {
    "class": build_rdf_class_detail,
    "individual": build_individual_detail,
    "property": build_property_detail,
    "concept": build_concept_detail,
    "scheme": build_scheme_detail,
}


@dataclass
class DetailSection:
    """One titled section of a detail view (e.g. "Identity", "Labels")."""

    title: str
    fields: list[DetailField] = dc_field(default_factory=list)
    danger: bool = False  # True for the "Danger Zone" (separator_danger) section
    group: bool = False  # opens a bordered group box (separator_group)
    collapsible: bool = False  # opens a collapsed-by-default disclosure group
    group_end: bool = False  # closes the current group box (separator_group_end)


def group_sections(fields: list[DetailField]) -> list[DetailSection]:
    """Split *fields* into sections at separator rows.

    Fields appearing before the first separator form a leading section with an
    empty title. Separator rows themselves are not included in any section's
    ``fields``.
    """
    sections: list[DetailSection] = []
    current: DetailSection | None = None
    for f in fields:
        ftype = f.meta.get("type")
        if ftype in _SEPARATORS:
            current = DetailSection(
                title=f.display,
                danger=(ftype == "separator_danger"),
                group=(ftype == "separator_group"),
                collapsible=(ftype == "separator_collapsible"),
                group_end=(ftype == "separator_group_end"),
            )
            sections.append(current)
        else:
            if current is None:
                current = DetailSection(title="")
                sections.append(current)
            current.fields.append(f)
    return sections


# ── legacy field builders, adapted to the (ctx, uri) presenter signature ──────
# Each kind keeps its existing build_* function until it gets a dedicated
# presenter; LegacyPresenter wraps these so output stays byte-identical.


def _taxonomy_render(ctx: PresenterContext, _uri: str) -> list[DetailField]:
    return build_tui_taxonomy_overview_fields(ctx.tax, ctx.lang)


def _entity_render(ctx: PresenterContext, uri: str) -> list[DetailField]:
    builder = _BUILDERS.get(data.kind_of(ctx.tax, uri))
    return builder(ctx.tax, uri, ctx.lang, configured_langs=ctx.configured_langs) if builder else []


def _presenter_for(ctx: PresenterContext, uri: str) -> EntityPresenter:
    """The presenter for *uri*: a registered subclass, else a LegacyPresenter
    wrapping the kind's existing build_* function."""
    if uri == OVERVIEW_URI:
        return OntologyOverviewPresenter(ctx, uri)
    if uri == TAXONOMY_URI:
        return LegacyPresenter(ctx, uri, _taxonomy_render)
    presenter_cls = PRESENTERS.get(data.kind_of(ctx.tax, uri))
    if presenter_cls is not None:
        return presenter_cls(ctx, uri)
    return LegacyPresenter(ctx, uri, _entity_render)


def _fields_for(
    tax: Taxonomy,
    uri: str,
    lang: str,
    activity: dict | None = None,
    lint: dict | None = None,
    configured_langs: list[str] | None = None,
    metadata: dict | None = None,
    quality_block: bool = True,
) -> list[DetailField]:
    """The flat DetailField list for *uri*, via its presenter."""
    ctx = PresenterContext(
        tax=tax,
        lang=lang,
        configured_langs=configured_langs,
        activity=activity,
        lint=lint,
        metadata=metadata,
        quality_block=quality_block,
    )
    return _presenter_for(ctx, uri).render()


def _is_create(f: DetailField) -> bool:
    """True for a constructive (＋ Add…) action row."""
    return f.meta.get("type") == "action_add" or f.display.lstrip().startswith("＋")


def _creates_first(fields: list[DetailField]) -> list[DetailField]:
    """Stable-reorder a section's fields so its ＋ Add… action sits first.

    Keeps the create affordance visible at the top of its section (e.g. "＋ Add
    metadata" right under the "Metadata" title) without scrolling past the values.
    """
    creates = [f for f in fields if _is_create(f)]
    rest = [f for f in fields if not _is_create(f)]
    return creates + rest


def build_sections(
    tax: Taxonomy,
    uri: str,
    lang: str = "en",
    activity: dict | None = None,
    lint: dict | None = None,
    configured_langs: list[str] | None = None,
    metadata: dict | None = None,
    quality_block: bool = True,
) -> list[DetailSection]:
    """Return the grouped detail sections for *uri*, dispatched by entity kind.

    Within each section the constructive ＋ Add… action is hoisted to the top
    (see ``_creates_first``). Returns ``[]`` for a uri with no detail builder.
    """
    fields = _fields_for(tax, uri, lang, activity, lint, configured_langs, metadata, quality_block)
    # The "Hierarchy" section is dropped from OWL class details only (concepts keep
    # their narrower/broader/related hierarchy).
    extra: frozenset[str] = (
        frozenset({"Hierarchy"}) if data.kind_of(tax, uri) == "class" else frozenset()
    )
    sections = group_sections(_declutter(fields, extra))
    for sec in sections:
        sec.fields = _creates_first(sec.fields)
    return sections


# Sections / actions hidden from every entity detail view. Delete & convert stay
# reachable on the right-click context menu; these just declutter the detail panel.
_HIDDEN_SECTIONS = frozenset({"Note (markdown)", "Danger Zone"})
_HIDDEN_ACTIONS = frozenset(
    {"add_schema_image", "add_schema_video", "add_schema_url", "add_class_property"}
)


def _declutter(
    fields: list[DetailField], extra_hidden: frozenset[str] | set[str] = frozenset()
) -> list[DetailField]:
    """Drop the Note (markdown) and Danger Zone sections (plus any *extra_hidden*
    section titles) and the ``+ Add schema:*`` actions from the flat field list."""
    hidden = _HIDDEN_SECTIONS | extra_hidden
    out: list[DetailField] = []
    skipping = False
    for f in fields:
        if f.meta.get("type", "").startswith("separator"):
            skipping = f.display in hidden  # skip the section + its rows
        if skipping or f.meta.get("action") in _HIDDEN_ACTIONS:
            continue
        out.append(f)
    return out


def field_markup(f: DetailField) -> str:
    """One detail field as Rich markup (no indent): 'label: value', or a dim
    affordance line for action/empty rows. Shared by the flat render and the
    composed DetailView row widgets."""
    if f.value:
        sep = " " if f.meta.get("plain_value") else ": "
        return f"{_esc(f.display)}{sep}{_esc(f.value)}"
    return f"[dim]{_esc(f.display)}[/dim]"


def _render_row(f: DetailField) -> str:
    return f"  {field_markup(f)}"


def render_detail(
    tax: Taxonomy, uri: str, lang: str = "en", configured_langs: list[str] | None = None
) -> str:
    """Rich-markup detail for *uri*, grouped into titled sections (read-only).

    Replaces the spike's flat ``data.detail_markup`` — this renders the full
    ``build_*_detail`` field model so the Textual detail view shows the same
    labels / hierarchy / properties / actions as the curses panel.
    """
    lines: list[str] = []
    for sec in build_sections(tax, uri, lang, configured_langs=configured_langs):
        if sec.title:
            style = "bold red" if sec.danger else "bold underline" if sec.group else "bold"
            lines.append(f"[{style}]{_esc(sec.title)}[/]")
        lines.extend(_render_row(f) for f in sec.fields)
    return "\n".join(lines)
