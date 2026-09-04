"""Shared DetailField primitives: separators, action fields, essential-label and entity-metadata affordances, label/note/media sections used by every *_detail builder below."""

from __future__ import annotations

import re as _re
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Final

from ...analysis_base import pct as _pct
from ...analysis_base import pct_bar as _pct_bar
from ...metadata_coverage import MetaProp
from ...metadata_coverage import entity_predicates as _entity_predicates
from ...model import LabelType, OntologyAnnotation
from . import _tree

_LIT_ACTION: Final = "action"
_LIT_ACTION_COLON: Final = "action:"
_LIT_TARGET_URI: Final = "target_uri"


@dataclass
class DetailField:
    key: str
    display: str
    value: str
    editable: bool
    meta: dict = dc_field(default_factory=dict)


def _sep(label: str) -> DetailField:
    """Create a non-selectable section-separator row."""
    return DetailField(
        f"sep:{label}",
        label,
        "",
        editable=False,
        meta={"type": "separator"},
    )


def _sep_sub(label: str) -> DetailField:
    """A *sub-section* separator: an indented sub-header nested under the preceding section
    (e.g. the Annotation / Object / Datatype property groups under 'Properties')."""
    return DetailField(
        f"sepsub:{label}",
        label,
        "",
        editable=False,
        meta={"type": "separator_sub"},
    )


def _sep_group(label: str) -> DetailField:
    """Open a visual *group*: the sections up to the matching :func:`_sep_group_end`
    are wrapped in one bordered, titled box (e.g. 'Quality & Coverage' over Health /
    Completeness / Languages)."""
    return DetailField(
        f"sep_group:{label}",
        label,
        "",
        editable=False,
        meta={"type": "separator_group"},
    )


def _sep_collapsible(label: str) -> DetailField:
    """Open a *collapsible* group (collapsed by default): the sections up to the matching
    :func:`_sep_group_end` are tucked behind a disclosure titled *label* (e.g.
    'N inherited properties')."""
    return DetailField(
        f"sep_collapsible:{label}",
        label,
        "",
        editable=False,
        meta={"type": "separator_collapsible"},
    )


def _sep_group_end() -> DetailField:
    """Close the visual group opened by the preceding :func:`_sep_group`."""
    return DetailField(
        "sep_group_end", "", "", editable=False, meta={"type": "separator_group_end"}
    )


_SEVERITY_ICONS = {"error": "⊘", "warning": "⚠", "info": "ℹ"}


def _coverage_fields(key_prefix: str, comp: object) -> list[DetailField]:
    """Coverage bar rows for any Coverage or PropertyCompletion object.

    Works with both SKOS (PropertyCompletion) and OWL (Coverage) objects
    via duck typing: requires .by_language, .total attributes.
    Change this function to update coverage display for both layers at once.
    """
    fields: list[DetailField] = []
    for lg, count in sorted(getattr(comp, "by_language", {}).items()):
        total = getattr(comp, "total", 0)
        p = _pct(count, total)
        bar = _pct_bar(p)
        fields.append(
            DetailField(
                f"{key_prefix}:{lg}",
                f"[{lg}]",
                f"{count}/{total}  {bar}  ({p}%)",
                editable=False,
                meta={"type": "stat", "color": _quality_color(p)},
            )
        )
    return fields


def _issue_nav_fields(
    issues: list,
    display_names: dict[str, str],
    key_prefix: str = "issue",
) -> list[DetailField]:
    """Issue rows for any Issue or TaxonomyIssue list.

    Works with both SKOS (TaxonomyIssue.entity_uri) and OWL (Issue.entity_uri)
    via the shared .entity_uri interface.
    Change this function to update issue display for both layers at once.
    """
    if not issues:
        return [
            DetailField(
                f"{key_prefix}:ok", "✓ no issues", "", editable=False, meta={"type": "stat"}
            )
        ]
    fields: list[DetailField] = []
    for idx, issue in enumerate(issues):
        icon = _SEVERITY_ICONS.get(issue.severity, "·")
        name = display_names.get(issue.issue_key, issue.issue_key)
        entity = issue.entity_uri
        meta: dict = {"type": "issue_nav", "severity": issue.severity}
        if entity:
            meta["uri"] = entity
        fields.append(
            DetailField(
                f"{key_prefix}:{idx}",
                f"{icon} {name}",
                issue.message,
                editable=False,
                meta=meta,
            )
        )
        if issue.extra.get("attr") and issue.extra.get(_LIT_TARGET_URI) and entity:
            target_uri = issue.extra[_LIT_TARGET_URI]
            fields.append(
                DetailField(
                    f"repair:{idx}",
                    "  ↳ remove link",
                    target_uri,
                    editable=False,
                    meta={
                        "type": "repair_mapping",
                        "source_uri": entity,
                        "attr": issue.extra["attr"],
                        _LIT_TARGET_URI: target_uri,
                    },
                )
            )
    return fields


def _stat(key: str, label: str, value: str) -> DetailField:
    """Helper for read-only stat rows."""
    return DetailField(key, label, value, editable=False, meta={"type": "stat"})


# Change these thresholds (or the colour names, mapped to CSS in app.py) once and
# every quality / completeness / coverage percentage re-colours at the same time.
def _quality_color(pct: int) -> str:
    """Global rule: < 50 % red, 50–79 % orange, ≥ 80 % green."""
    if pct >= 80:
        return "green"
    if pct >= 50:
        return "orange"
    return "red"


def _colored(field: DetailField, color: str) -> DetailField:
    """Tag a row with a quality colour (``red`` / ``orange`` / ``green``)."""
    field.meta["color"] = color
    return field


def _pct_stat(key: str, label: str, pct: int, *, prefix: str = "", suffix: str = "") -> DetailField:
    """The canonical percentage-indicator row — block bar + percent, coloured by
    :func:`_quality_color`. Every %-indicator routes through here (or through
    ``_colored(..., _quality_color(pct))`` when its value needs a custom layout)
    so colours and thresholds live in one place."""
    value = f"{prefix}{_pct_bar(pct)}  {pct}%{suffix}"
    return _colored(_stat(key, label, value), _quality_color(pct))


def _add_action_field(key: str, label: str, action: str, **extra_meta) -> DetailField:
    """Helper for action rows."""
    return DetailField(
        key,
        label,
        "",
        editable=False,
        meta={"type": _LIT_ACTION, _LIT_ACTION: action, **extra_meta},
    )


def _add_action_add_field(key: str, label: str, action: str, **extra_meta) -> DetailField:
    """Helper for constructive action rows (green)."""
    return DetailField(
        key,
        label,
        "",
        editable=False,
        meta={"type": "action_add", _LIT_ACTION: action, **extra_meta},
    )


def _add_action_del_field(key: str, label: str, action: str, **extra_meta) -> DetailField:
    """Helper for destructive action rows (red)."""
    return DetailField(
        key,
        label,
        "",
        editable=False,
        meta={"type": "action_del", _LIT_ACTION: action, **extra_meta},
    )


def _lang_add_actions(
    configured_langs: list[str],
    key_prefix: str,
    label_tmpl: str,
    action: str,
    *,
    present: set[str] | None = None,
    green: bool = True,
) -> list[DetailField]:
    """A "+ Add … [lang]" affordance for each *configured* language.

    With *present* given, only languages missing from it get a row (e.g. one
    label per language); without it, every configured language gets one (e.g.
    altLabels, which may repeat per language). *green* picks the constructive
    (``action_add``) vs plain (``action``) row style.
    """
    factory = _add_action_add_field if green else _add_action_field
    return [
        factory(f"{key_prefix}:{lang}", label_tmpl.format(lang=lang), action, lang=lang)
        for lang in configured_langs
        if present is None or lang not in present
    ]


@dataclass(frozen=True)
class _EssentialLabel:
    """The primary human label an entity of a given kind should carry."""

    label_tmpl: str  # e.g. "+ Add rdfs:label [{lang}]"
    action: str  # the add-action name its handler dispatches on
    key_prefix: str  # DetailField key prefix


_ADD_RDFS_LABEL = "+ Add rdfs:label [{lang}]"

_ADD_RDFS_COMMENT = "+ Add rdfs:comment [{lang}]"

_ESSENTIAL_LABEL: dict[str, _EssentialLabel] = {
    "class": _EssentialLabel(_ADD_RDFS_LABEL, "add_rdf_label", "action:add_rdf_label"),
    "individual": _EssentialLabel(_ADD_RDFS_LABEL, "add_ind_label", "action:add_ind_label"),
    "property": _EssentialLabel(_ADD_RDFS_LABEL, "add_prop_label", "action:add_prop_label"),
    "concept": _EssentialLabel(
        "+ Add skos:prefLabel [{lang}]", "add_pref_label", "action:add_pref"
    ),
}


def essential_label_affordances(
    kind: str, present_langs: set[str], configured_langs: list[str] | None
) -> list[DetailField]:
    """A '+ Add <primary label> [lang]' affordance for each configured language the
    entity of this *kind* is missing. Empty for kinds without an essential label."""
    spec = _ESSENTIAL_LABEL.get(kind)
    if spec is None:
        return []
    return _lang_add_actions(
        configured_langs or [],
        spec.key_prefix,
        spec.label_tmpl,
        spec.action,
        present=present_langs,
    )


def configured_annotation_affordances(
    entity: object, catalog: list[MetaProp] | None
) -> list[DetailField]:
    """A '+ Add <prefix:local>' affordance for each configured annotation predicate the
    *entity* does not yet carry. Empty when no catalog is configured."""
    if not catalog:
        return []
    present = _entity_predicates(entity)
    rows: list[DetailField] = []
    for mp in catalog:
        if mp.predicate in present:
            continue
        from ._overview import _annotation_display

        label = mp.label or _annotation_display(mp.predicate)
        rows.append(
            _add_action_field(
                f"action:add_entity_meta:{mp.predicate}",
                f"+ Add {label}",
                "add_entity_annotation",
                predicate=mp.predicate,
                is_iri="IRI" in mp.label,  # catalog labels flag IRI-valued predicates
            )
        )
    return rows


def _entity_annotation_rows(annotation: OntologyAnnotation) -> list[DetailField]:
    """One editable value row + its paired remove row for a single entity annotation."""
    from ._overview import _annotation_display

    display = _annotation_display(annotation.predicate)
    value_row = DetailField(
        f"eann:{annotation.predicate}:{annotation.value}",
        display,
        annotation.value,
        editable=True,
        meta={
            "type": "entity_annotation",
            "predicate": annotation.predicate,
            "old_value": annotation.value,
            "is_iri": annotation.is_iri,
            "lang": annotation.lang,
        },
    )
    remove_row = DetailField(
        f"eann:remove:{annotation.predicate}:{annotation.value}",
        f"  ✕ remove {display}",
        "",
        editable=False,
        meta={
            "type": "action_del",
            _LIT_ACTION: "remove_entity_annotation",
            "predicate": annotation.predicate,
            "value": annotation.value,
        },
    )
    return [value_row, remove_row]


def entity_metadata_section(entity: object, catalog: list[MetaProp] | None) -> list[DetailField]:
    """The 'Metadata' section for an OWL entity: existing catalogued annotations (editable +
    remove) followed by a '+ Add …' affordance for each configured predicate it lacks. Empty
    when nothing configured is present or addable. Individuals keep their annotation values
    under Property Values, so only their missing-predicate affordances surface here."""
    if not catalog:
        return []
    catalog_preds = {mp.predicate for mp in catalog}
    rows: list[DetailField] = []
    for a in getattr(entity, "annotations", []):
        if a.predicate in catalog_preds:
            rows += _entity_annotation_rows(a)
    rows += configured_annotation_affordances(entity, catalog)
    return [_sep("Metadata"), *rows] if rows else []


def _sep_danger(label: str) -> DetailField:
    """Create a non-selectable danger-zone section-separator row (red bold)."""
    return DetailField(
        f"sep_danger:{label}",
        label,
        "",
        editable=False,
        meta={"type": "separator_danger"},
    )


def render_note_markdown(text: str) -> list[tuple[str, bool]]:
    """Parse markdown text, return (rendered_line, is_bold) pairs.

    Applies minimal terminal-friendly transformations:
    - Headings (#+ text) → strip prefix, mark bold
    - Bullets (- / * / + item) → bullet character
    - **text** / *text* → strip markers
    """
    result: list[tuple[str, bool]] = []
    for line in text.split("\n"):
        m = _re.match(r"^#{1,6}\s+(.*)", line)
        if m:
            content = _re.sub(_tree._MARKDOWN_EMPHASIS_RE, r"\1", m.group(1))
            result.append((content, True))
            continue
        m = _re.match(r"^[-*+]\s+(.*)", line)
        if m:
            content = _re.sub(_tree._MARKDOWN_EMPHASIS_RE, r"\1", m.group(1))
            result.append(("• " + content, False))
            continue
        stripped = _re.sub(_tree._MARKDOWN_EMPHASIS_RE, r"\1", line)
        result.append((stripped, False))
    return result


def _note_display_fields(note: str, key_prefix: str) -> list[DetailField]:
    """Detail panel rows for the ns1:note markdown annotation field.

    Only the first (title) line is shown as a preview; the full note opens in
    the editor via the "Open note" action.
    """
    fields: list[DetailField] = [_sep("Note (markdown)")]
    if not note:
        fields.append(
            DetailField(
                f"{key_prefix}note_empty",
                "note",
                "(empty)",
                editable=False,
                meta={"type": "stat"},
            )
        )
        fields.append(
            _add_action_add_field(f"{key_prefix}action:edit_note", "✎ Edit note", "edit_note")
        )
    else:
        lines = render_note_markdown(note)
        first_line, is_bold = lines[0]
        fields.append(
            DetailField(
                f"{key_prefix}note_line:0",
                "",
                first_line,
                editable=False,
                meta={"type": "note_line", "bold": is_bold},
            )
        )
        extra = len(lines) - 1
        if extra > 0:
            fields.append(
                DetailField(
                    f"{key_prefix}note_more",
                    "",
                    f"… {extra} more line{'s' if extra != 1 else ''}",
                    editable=False,
                    meta={"type": "note_more"},
                )
            )
        fields.append(
            _add_action_add_field(f"{key_prefix}action:open_note", "⊕ Open note", "edit_note")
        )
        fields.append(
            _add_action_del_field(f"{key_prefix}action:delete_note", "✗ Delete note", "delete_note")
        )
    return fields


def _schema_media_display_fields(entity: object, prefix: str) -> list[DetailField]:
    """Display rows for schema:image / schema:video / schema:url if any are set."""
    imgs = getattr(entity, "schema_images", [])
    vids = getattr(entity, "schema_videos", [])
    urls = getattr(entity, "schema_urls", [])
    if not (imgs or vids or urls):
        return []
    fields: list[DetailField] = [_sep("Rich Content")]
    for url in imgs:
        short = url if len(url) <= 52 else "…" + url[-51:]
        fields.append(
            DetailField(
                f"{prefix}img:{url}",
                "img",
                short,
                editable=False,
                meta={"type": "schema_image_val", "url": url},
            )
        )
    for url in vids:
        short = url if len(url) <= 52 else "…" + url[-51:]
        fields.append(
            DetailField(
                f"{prefix}vid:{url}",
                "video",
                short,
                editable=False,
                meta={"type": "schema_video_val", "url": url},
            )
        )
    for url in urls:
        short = url if len(url) <= 52 else "…" + url[-51:]
        fields.append(
            DetailField(
                f"{prefix}url:{url}",
                "link",
                short,
                editable=False,
                meta={"type": "schema_url_val", "url": url},
            )
        )
    return fields


def _schema_media_action_fields(entity: object, prefix: str) -> list[DetailField]:
    """Add / remove action rows for schema media. Add actions only shown when no value exists."""
    imgs = getattr(entity, "schema_images", [])
    vids = getattr(entity, "schema_videos", [])
    urls = getattr(entity, "schema_urls", [])
    fields: list[DetailField] = []
    if not imgs:
        fields.append(
            _add_action_field(
                f"{_LIT_ACTION_COLON}{prefix}add_img",
                "+ Add schema:image (photo URL)",
                "add_schema_image",
            )
        )
    if not vids:
        fields.append(
            _add_action_field(
                f"{_LIT_ACTION_COLON}{prefix}add_vid",
                "+ Add schema:video (YouTube / Vimeo URL)",
                "add_schema_video",
            )
        )
    if not urls:
        fields.append(
            _add_action_field(
                f"{_LIT_ACTION_COLON}{prefix}add_url",
                "+ Add schema:url (external link)",
                "add_schema_url",
            )
        )
    for url in imgs:
        short = "…" + url[-34:] if len(url) > 34 else url
        fields.append(
            _add_action_field(
                f"{_LIT_ACTION_COLON}{prefix}rmi:{url}",
                f"✗ Remove image: {short}",
                "remove_schema_image",
                url=url,
            )
        )
    for url in vids:
        short = "…" + url[-34:] if len(url) > 34 else url
        fields.append(
            _add_action_field(
                f"{_LIT_ACTION_COLON}{prefix}rmv:{url}",
                f"✗ Remove video: {short}",
                "remove_schema_video",
                url=url,
            )
        )
    for url in urls:
        short = "…" + url[-34:] if len(url) > 34 else url
        fields.append(
            _add_action_field(
                f"{_LIT_ACTION_COLON}{prefix}rmu:{url}",
                f"✗ Remove link: {short}",
                "remove_schema_url",
                url=url,
            )
        )
    return fields


def _section_pref_labels(
    labels: list, id_prefix: str, display_name: str, meta_type: str
) -> list[DetailField]:
    """Shared: emit prefLabel rows sorted by language (no alt labels)."""
    pref = {lbl.lang: lbl.value for lbl in labels if lbl.type == LabelType.PREF}
    return [
        DetailField(
            f"{id_prefix}:{lg}",
            f"{display_name} [{lg}]",
            val,
            editable=True,
            meta={"type": meta_type, "lang": lg},
        )
        for lg, val in sorted(pref.items())
    ]


def _section_alt_labels(labels: list, id_prefix: str, meta_type: str) -> list[DetailField]:
    """Shared: emit altLabel rows sorted by language (standalone, no grouping)."""
    alt: dict[str, list[str]] = {}
    for lbl in labels:
        if lbl.type == LabelType.ALT:
            alt.setdefault(lbl.lang, []).append(lbl.value)
    fields = []
    for lg, vals in sorted(alt.items()):
        for idx, val in enumerate(vals):
            fields.append(
                DetailField(
                    f"{id_prefix}:{lg}:{idx}",
                    f"altLabel [{lg}]",
                    val,
                    editable=True,
                    meta={"type": meta_type, "lang": lg, "idx": idx},
                )
            )
    return fields


def _section_labels_grouped(
    labels: list,
    pref_prefix: str,
    alt_prefix: str,
    pref_display: str,
    pref_meta: str,
    alt_meta: str,
) -> list[DetailField]:
    """Emit prefLabel rows each followed immediately by their language's altLabels.

    Languages that have only altLabels (no pref) are appended at the end.
    Key format: pref ``{pref_prefix}:{lg}``, alt ``{alt_prefix}:{lg}:{idx}``
    """
    pref: dict[str, str] = {}
    alt: dict[str, list[str]] = {}
    for lbl in labels:
        if lbl.type == LabelType.PREF:
            pref[lbl.lang] = lbl.value
        elif lbl.type == LabelType.ALT:
            alt.setdefault(lbl.lang, []).append(lbl.value)

    all_langs = sorted(set(pref) | set(alt))
    fields: list[DetailField] = []
    for lg in all_langs:
        if lg in pref:
            fields.append(
                DetailField(
                    f"{pref_prefix}:{lg}",
                    f"{pref_display} [{lg}]",
                    pref[lg],
                    editable=True,
                    meta={"type": pref_meta, "lang": lg},
                )
            )
        for idx, val in enumerate(alt.get(lg, [])):
            fields.append(
                DetailField(
                    f"{alt_prefix}:{lg}:{idx}",
                    f"  altLabel [{lg}]",
                    val,
                    editable=True,
                    meta={"type": alt_meta, "lang": lg, "idx": idx},
                )
            )
    return fields


def _section_text_list(
    items: list, id_prefix: str, display_name: str, meta_type: str
) -> list[DetailField]:
    """Shared: emit rows for list[Definition]-typed properties (definitions, descriptions, scope_notes)."""
    return [
        DetailField(
            f"{id_prefix}:{item.lang}",
            f"{display_name} [{item.lang}]",
            item.value,
            editable=True,
            meta={"type": meta_type, "lang": item.lang},
        )
        for item in sorted(items, key=lambda d: d.lang)
    ]
