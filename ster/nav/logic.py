"""Pure taxonomy tree / detail logic — no curses dependency."""

from __future__ import annotations

import re as _re
from collections import deque
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path

from ..analysis_base import pct as _pct
from ..analysis_base import pct_bar as _pct_bar
from ..metadata_coverage import is_labelled as _is_labelled
from ..model import LabelType, OntologyAnnotation, Taxonomy
from ..owl_analysis import (
    ONTOLOGY_ISSUE_DISPLAY_NAMES,
    OntologyAnalysis,
    compute_ontology_analysis,
    compute_owl_analysis,
)
from ..taxonomy_analysis import ISSUE_DISPLAY_NAMES, SchemeAnalysis, compute_completions
from ..workspace import TaxonomyWorkspace

# ──────────────────────────── tree helpers ────────────────────────────────────

_ACTION_ADD_SCHEME = "__ster:add_scheme__"  # sentinel URI for action rows
_FILE_URI_PREFIX = "__ster:file::"  # prefix for file-node sentinel URIs
_GLOBAL_URI = "__ster:global__"  # sentinel URI for the global overview panel
_OWL_SECTION_URI = (
    "__ster:owl_classes__"  # legacy: synthetic section header (replaced by ontology root)
)
_OWL_ONTOLOGY_PREFIX = "__ster:owl_ontology::"  # prefix for per-file ontology root nodes
_UNATTACHED_INDS_URI = "__ster:unattached_inds__"  # group node for typeless individuals
SECTION_PROPERTIES = "__ster:section:properties__"  # collapsible Properties section header
_ACTION_ADD_PROPERTY = "__ster:add_property__"  # sentinel URI for "Add property" action row


def _ontology_sentinel(file_path: Path | None) -> str:
    """Return the ontology-root sentinel URI for *file_path*."""
    if file_path is None:
        return f"{_OWL_ONTOLOGY_PREFIX}__"
    return f"{_OWL_ONTOLOGY_PREFIX}{file_path}"


def _is_ontology_sentinel(uri: str) -> bool:
    return uri.startswith(_OWL_ONTOLOGY_PREFIX)


def _file_sentinel(path: Path) -> str:
    return f"{_FILE_URI_PREFIX}{path}"


def _props_section_line(folded: set[str]) -> TreeLine:
    return TreeLine(
        uri=SECTION_PROPERTIES,
        depth=0,
        prefix="",
        is_scheme=True,
        is_folded=SECTION_PROPERTIES in folded,
        label="Properties",
        node_type="section",
    )


def _prop_child_lines(taxonomy: Taxonomy) -> list[TreeLine]:
    """Return sorted property nodes + Add-property action row for the Properties section."""
    from ..model import OWLProperty as _OWLProperty

    def _local(uri: str) -> str:
        return uri.rsplit("/", 1)[-1].rsplit("#", 1)[-1]

    props = sorted(
        [p for p in taxonomy.owl_properties.values() if isinstance(p, _OWLProperty)],
        key=lambda p: _local(p.uri).lower(),
    )
    result: list[TreeLine] = []
    for prop in props:
        result.append(
            TreeLine(
                uri=prop.uri,
                depth=1,
                prefix="├── ",
                node_type="property",
            )
        )
    result.append(
        TreeLine(
            uri=_ACTION_ADD_PROPERTY,
            depth=1,
            prefix="└── ",
            is_action=True,
            label="+ Add property",
            node_type="section",
        )
    )
    return result


@dataclass
class TreeLine:
    uri: str
    depth: int
    prefix: str  # e.g. "│   ├── "
    is_file: bool = False  # file-level root node (multi-file workspace)
    file_path: Path | None = None  # owning file (set for file/scheme/concept rows)
    is_scheme: bool = False
    is_folded: bool = False
    hidden_count: int = 0
    is_action: bool = False  # synthetic row (not a concept/scheme node)
    # "concept" | "class" | "promoted" — set from taxonomy.node_type()
    node_type: str = "concept"
    # When non-empty, the renderer uses this string instead of looking up from taxonomy.
    # Used for synthetic section headers (e.g. the OWL classes section in mixed view).
    label: str = ""


def _count_descendants(taxonomy: Taxonomy, uri: str) -> int:
    """Count total reachable descendants of a concept that exist in taxonomy.concepts."""
    seen: set[str] = set()

    def _count(u: str) -> int:
        if u in seen:
            return 0
        seen.add(u)
        c = taxonomy.concepts.get(u)
        if not c:
            return 0
        existing = [ch for ch in c.narrower if ch in taxonomy.concepts]
        return len(existing) + sum(_count(ch) for ch in existing)

    return _count(uri)


def flatten_tree(
    taxonomy_or_workspace: Taxonomy | TaxonomyWorkspace,
    folded: set[str] | None = None,
) -> list[TreeLine]:
    """Flatten the taxonomy tree into a list of displayable TreeLine objects.

    Accepts either a single Taxonomy (original behaviour) or a
    TaxonomyWorkspace (multi-file: adds file-level root nodes above schemes).
    URIs in *folded* are collapsed; their hidden descendant count is set.
    """
    if isinstance(taxonomy_or_workspace, TaxonomyWorkspace):
        ws = taxonomy_or_workspace
        if len(ws.taxonomies) == 1:
            # Single file in workspace — no file node, same display as before
            tax = next(iter(ws.taxonomies.values()))
            fp = next(iter(ws.taxonomies.keys()))
            return _flatten_taxonomy(tax, folded, file_path=fp)
        return _flatten_workspace(ws, folded)
    return _flatten_taxonomy(taxonomy_or_workspace, folded)


def _flatten_taxonomy(
    taxonomy: Taxonomy,
    folded: set[str] | None = None,
    file_path: Path | None = None,
    scheme_depth: int = 0,
    scheme_prefix: str = "",
    concept_base_depth: int = 0,
    include_owl: bool = True,
) -> list[TreeLine]:
    """Flatten a single Taxonomy into TreeLine rows.

    *scheme_depth* / *scheme_prefix* / *concept_base_depth* let callers
    embed the output inside a parent file node (multi-file workspace).
    Set *include_owl=False* when the caller handles OWL rendering itself
    (e.g. _flatten_mixed) to avoid double-rendering classes and individuals.
    """
    if folded is None:
        folded = set()
    result: list[TreeLine] = []
    _visited_tax: set[str] = set()

    def visit(uri: str, depth: int, prefix: str, is_last: bool) -> None:
        if uri in _visited_tax:
            return
        _visited_tax.add(uri)
        concept = taxonomy.concepts.get(uri)
        if not concept:
            return  # dangling reference — skip silently
        connector = "└── " if is_last else "├── "
        children = concept.narrower
        is_fold = uri in folded and bool(children)
        hidden = _count_descendants(taxonomy, uri) if is_fold else 0
        result.append(
            TreeLine(
                uri=uri,
                depth=depth,
                prefix=prefix + connector,
                is_folded=is_fold,
                hidden_count=hidden,
                file_path=file_path,
                node_type=taxonomy.node_type(uri),
            )
        )
        if not is_fold:
            ext = "    " if is_last else "│   "
            for i, child in enumerate(children):
                visit(child, depth + 1, prefix + ext, i == len(children) - 1)

    # ── OWL class hierarchy ───────────────────────────────────────────────────
    if include_owl and (taxonomy.owl_classes or taxonomy.owl_individuals):
        _cls_children: dict[str, list[str]] = {u: [] for u in taxonomy.owl_classes}
        for uri, cls in taxonomy.owl_classes.items():
            for parent in cls.sub_class_of:
                if parent in _cls_children:
                    _cls_children[parent].append(uri)
        # Nest individuals under their first known parent class
        for ind_uri, ind in taxonomy.owl_individuals.items():
            placed = False
            for t in ind.types:
                if t in _cls_children:
                    _cls_children[t].append(ind_uri)
                    placed = True
                    break
            if not placed:
                # no known class parent → add as pseudo-root so it still renders
                _cls_children[ind_uri] = []
        _child_uris = {
            uri
            for uri, cls in taxonomy.owl_classes.items()
            for p in cls.sub_class_of
            if p in taxonomy.owl_classes
        }
        # individuals nested under a class are also child URIs
        _ind_child_uris = {
            ind_uri
            for ind in taxonomy.owl_individuals.values()
            for t in ind.types
            if t in taxonomy.owl_classes
            for ind_uri in [ind.uri]
        }
        root_classes = [u for u in taxonomy.owl_classes if u not in _child_uris]
        root_inds = [u for u in taxonomy.owl_individuals if u not in _ind_child_uris]

        def visit_class(uri: str, depth: int, prefix: str, is_last: bool) -> None:
            if uri in _visited_tax:
                return
            _visited_tax.add(uri)
            connector = "└── " if is_last else "├── "
            children = _cls_children.get(uri, [])
            is_fold = uri in folded and bool(children)
            node_t = "individual" if uri in taxonomy.owl_individuals else taxonomy.node_type(uri)
            result.append(
                TreeLine(
                    uri=uri,
                    depth=scheme_depth + depth,
                    prefix=scheme_prefix + prefix + connector,
                    is_folded=is_fold,
                    file_path=file_path,
                    node_type=node_t,
                )
            )
            if not is_fold:
                ext = "    " if is_last else "│   "
                for i, child in enumerate(children):
                    visit_class(child, depth + 1, prefix + ext, i == len(children) - 1)

        all_roots = root_classes + root_inds
        for i, uri in enumerate(all_roots):
            visit_class(uri, 0, "", i == len(all_roots) - 1)

    # ── OWL individuals not yet placed (fallback — should be empty after above) ─
    for uri in taxonomy.owl_individuals if include_owl else []:
        if uri in _visited_tax:
            continue
        _visited_tax.add(uri)
        result.append(
            TreeLine(
                uri=uri,
                depth=scheme_depth,
                prefix=scheme_prefix,
                node_type="individual",
                file_path=file_path,
            )
        )

    # ── OWL properties ────────────────────────────────────────────────────────
    for uri in taxonomy.owl_properties if include_owl else []:
        if uri in _visited_tax:
            continue
        _visited_tax.add(uri)
        result.append(
            TreeLine(
                uri=uri,
                depth=scheme_depth,
                prefix=scheme_prefix,
                node_type="property",
                file_path=file_path,
            )
        )

    # ── SKOS concept schemes ──────────────────────────────────────────────────
    for scheme in taxonomy.schemes.values():
        scheme_folded = scheme.uri in folded
        tops = list(scheme.top_concepts)
        hidden_under_scheme = 0
        if scheme_folded:
            for tc in tops:
                if tc in taxonomy.concepts:
                    hidden_under_scheme += 1 + _count_descendants(taxonomy, tc)
        result.append(
            TreeLine(
                uri=scheme.uri,
                depth=scheme_depth,
                prefix=scheme_prefix,
                is_scheme=True,
                is_folded=scheme_folded,
                hidden_count=hidden_under_scheme,
                file_path=file_path,
            )
        )
        if not scheme_folded:
            existing_tops = [u for u in tops if u in taxonomy.concepts]
            for i, uri in enumerate(existing_tops):
                visit(uri, concept_base_depth, scheme_prefix, i == len(existing_tops) - 1)

    return result


def _flatten_workspace(
    workspace: TaxonomyWorkspace,
    folded: set[str] | None = None,
) -> list[TreeLine]:
    """Flatten a multi-file workspace: file nodes > scheme nodes > concepts."""
    if folded is None:
        folded = set()
    result: list[TreeLine] = []

    for file_path, taxonomy in workspace.taxonomies.items():
        file_uri = _file_sentinel(file_path)
        file_folded = file_uri in folded
        hidden_in_file = 0
        if file_folded:
            for scheme in taxonomy.schemes.values():
                hidden_in_file += 1
                for tc in scheme.top_concepts:
                    if tc in taxonomy.concepts:
                        hidden_in_file += 1 + _count_descendants(taxonomy, tc)

        result.append(
            TreeLine(
                uri=file_uri,
                depth=0,
                prefix="",
                is_file=True,
                file_path=file_path,
                is_folded=file_folded,
                hidden_count=hidden_in_file,
            )
        )
        if not file_folded:
            inner = _flatten_taxonomy(
                taxonomy,
                folded,
                file_path=file_path,
                scheme_depth=1,
                scheme_prefix="    ",
                concept_base_depth=1,
            )
            result.extend(inner)

    return result


def _children(taxonomy: Taxonomy, uri: str | None) -> list[str]:
    if uri is None:
        scheme = taxonomy.primary_scheme()
        return list(scheme.top_concepts) if scheme else []
    concept = taxonomy.concepts.get(uri)
    return list(concept.narrower) if concept else []


def _parent_uri(taxonomy: Taxonomy, uri: str | None) -> str | None:
    if uri is None:
        return None
    concept = taxonomy.concepts.get(uri)
    return concept.broader[0] if concept and concept.broader else None


def _breadcrumb(taxonomy: Taxonomy, uri: str | None) -> str:
    if uri is None:
        return "/"
    parts: list[str] = []
    current: str | None = uri
    visited: set[str] = set()
    while current and current not in visited:
        visited.add(current)
        parts.append(taxonomy.uri_to_handle(current) or "?")
        current = _parent_uri(taxonomy, current)
    return "/" + "/".join(f"[{h}]" for h in reversed(parts))


# ──────────────────────────── detail fields ───────────────────────────────────


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


# ──────────────────────────── scheme dashboard helpers ───────────────────────

_SEVERITY_ICONS = {"error": "⊘", "warning": "⚠", "info": "ℹ"}
# _pct_bar and _pct are imported from analysis_base at the top of this file.


# ──────────────────── shared rendering helpers (SKOS + OWL) ──────────────────


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
        if issue.extra.get("attr") and issue.extra.get("target_uri") and entity:
            target_uri = issue.extra["target_uri"]
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
                        "target_uri": target_uri,
                    },
                )
            )
    return fields


# ──────────────────────────── shared section primitives ──────────────────────


def _stat(key: str, label: str, value: str) -> DetailField:
    """Helper for read-only stat rows."""
    return DetailField(key, label, value, editable=False, meta={"type": "stat"})


# ── quality colour — single source of truth for every %-indicator ──────────────
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
        key, label, "", editable=False, meta={"type": "action", "action": action, **extra_meta}
    )


def _add_action_add_field(key: str, label: str, action: str, **extra_meta) -> DetailField:
    """Helper for constructive action rows (green)."""
    return DetailField(
        key, label, "", editable=False, meta={"type": "action_add", "action": action, **extra_meta}
    )


def _add_action_del_field(key: str, label: str, action: str, **extra_meta) -> DetailField:
    """Helper for destructive action rows (red)."""
    return DetailField(
        key, label, "", editable=False, meta={"type": "action_del", "action": action, **extra_meta}
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
            content = _re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", m.group(1))
            result.append((content, True))
            continue
        m = _re.match(r"^[-*+]\s+(.*)", line)
        if m:
            content = _re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", m.group(1))
            result.append(("• " + content, False))
            continue
        stripped = _re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", line)
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
        return fields

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
                f"action:{prefix}add_img", "+ Add schema:image (photo URL)", "add_schema_image"
            )
        )
    if not vids:
        fields.append(
            _add_action_field(
                f"action:{prefix}add_vid",
                "+ Add schema:video (YouTube / Vimeo URL)",
                "add_schema_video",
            )
        )
    if not urls:
        fields.append(
            _add_action_field(
                f"action:{prefix}add_url", "+ Add schema:url (external link)", "add_schema_url"
            )
        )
    for url in imgs:
        short = "…" + url[-34:] if len(url) > 34 else url
        fields.append(
            _add_action_field(
                f"action:{prefix}rmi:{url}",
                f"✗ Remove image: {short}",
                "remove_schema_image",
                url=url,
            )
        )
    for url in vids:
        short = "…" + url[-34:] if len(url) > 34 else url
        fields.append(
            _add_action_field(
                f"action:{prefix}rmv:{url}",
                f"✗ Remove video: {short}",
                "remove_schema_video",
                url=url,
            )
        )
    for url in urls:
        short = "…" + url[-34:] if len(url) > 34 else url
        fields.append(
            _add_action_field(
                f"action:{prefix}rmu:{url}", f"✗ Remove link: {short}", "remove_schema_url", url=url
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


# ──────────────────────────── concept-specific section helpers ────────────────


def _concept_identity_fields(taxonomy: Taxonomy, uri: str, concept, lang: str) -> list[DetailField]:
    """URI + topConceptOf/inScheme (topConceptOf is navigable → scheme detail)."""
    fields = [DetailField("uri", "URI", uri, editable=True, meta={"type": "uri"})]
    if concept.top_concept_of:
        scheme = taxonomy.schemes.get(concept.top_concept_of)
        scheme_label = scheme.title(lang) if scheme else concept.top_concept_of
        fields.append(
            DetailField(
                "top_concept_of",
                "◈ scheme",
                scheme_label,
                editable=False,
                meta={"type": "top_concept_of", "uri": concept.top_concept_of, "nav": True},
            )
        )
    return fields


def _concept_hierarchy_fields(taxonomy: Taxonomy, concept, lang: str) -> list[DetailField]:
    """broader↑, narrower↓, related~ — all navigable."""
    fields = []
    for child_uri in concept.narrower:
        h = taxonomy.uri_to_handle(child_uri) or "?"
        child = taxonomy.concepts.get(child_uri)
        label_str = child.pref_label(lang) if child else child_uri
        fields.append(
            DetailField(
                f"narrower:{child_uri}",
                "↓ narrower",
                f"{label_str}  [{h}]",
                editable=False,
                meta={"type": "relation", "uri": child_uri, "nav": True},
            )
        )
    for p_uri in concept.broader:
        h = taxonomy.uri_to_handle(p_uri) or "?"
        parent = taxonomy.concepts.get(p_uri)
        label_str = parent.pref_label(lang) if parent else p_uri
        fields.append(
            DetailField(
                f"broader:{p_uri}",
                "↑ broader",
                f"{label_str}  [{h}]",
                editable=False,
                meta={"type": "relation", "uri": p_uri, "nav": True},
            )
        )
    for r_uri in concept.related:
        h = taxonomy.uri_to_handle(r_uri) or "?"
        rel = taxonomy.concepts.get(r_uri)
        label_str = rel.pref_label(lang) if rel else r_uri
        fields.append(
            DetailField(
                f"related:{r_uri}",
                "~ related",
                f"{label_str}  [{h}]",
                editable=False,
                meta={"type": "relation", "uri": r_uri, "nav": True},
            )
        )
    return fields


def _subtree_concept_uris(taxonomy: Taxonomy, root_uri: str) -> list[str]:
    """Return all URIs in the subtree rooted at *root_uri* (inclusive, BFS, cycle-safe)."""
    visited: set[str] = set()
    queue: deque[str] = deque([root_uri])
    result: list[str] = []
    while queue:
        uri = queue.popleft()
        if uri in visited or uri not in taxonomy.concepts:
            continue
        visited.add(uri)
        result.append(uri)
        for child in taxonomy.concepts[uri].narrower:
            if child not in visited:
                queue.append(child)
    return result


def _subtree_class_uris(taxonomy: Taxonomy, root_uri: str) -> list[str]:
    """Return all OWL class URIs in the subclass subtree rooted at root_uri (inclusive, BFS, cycle-safe)."""
    children_of: dict[str, list[str]] = {uri: [] for uri in taxonomy.owl_classes}
    for uri, cls in taxonomy.owl_classes.items():
        for parent in cls.sub_class_of:
            if parent in children_of:
                children_of[parent].append(uri)
    visited: set[str] = set()
    queue: deque[str] = deque([root_uri])
    result: list[str] = []
    while queue:
        uri = queue.popleft()
        if uri in visited or uri not in taxonomy.owl_classes:
            continue
        visited.add(uri)
        result.append(uri)
        for child in children_of.get(uri, []):
            if child not in visited:
                queue.append(child)
    return result


def _class_quality_fields(taxonomy: Taxonomy, uri: str, lang: str) -> list[DetailField]:
    """Quality stats (label/comment coverage, instances, property fill) for a class subtree."""
    if uri not in taxonomy.owl_classes:
        return []

    subtree = _subtree_class_uris(taxonomy, uri)
    subtree_set = set(subtree)
    n_classes = len(subtree)

    labeled = sum(1 for u in subtree if taxonomy.owl_classes[u].labels)
    commented = sum(1 for u in subtree if taxonomy.owl_classes[u].comments)
    label_p = _pct(labeled, n_classes)
    comment_p = _pct(commented, n_classes)

    n_subtree_inds = sum(
        1 for ind in taxonomy.owl_individuals.values() if any(t in subtree_set for t in ind.types)
    )

    fields: list[DetailField] = [_sep("Subtree Quality")]
    if n_classes > 1:
        fields.append(_stat("cls:q:n_classes", "classes in subtree", str(n_classes)))
    fields.append(_pct_stat("cls:q:lbl", "rdfs:label", label_p))
    fields.append(_pct_stat("cls:q:cmt", "rdfs:comment", comment_p))
    fields.append(_stat("cls:q:inst:subtree", "instances (subtree)", str(n_subtree_inds)))

    fill_fields: list[DetailField] = []
    for p_uri, prop in sorted(taxonomy.owl_properties.items()):
        if not prop.domains:
            continue
        domain_set = set(prop.domains)
        if not domain_set & subtree_set:
            continue
        domain_inds = [
            ind_uri
            for ind_uri, ind in taxonomy.owl_individuals.items()
            if _effective_types(taxonomy, ind.types) & domain_set
        ]
        if not domain_inds:
            continue
        range_set: set[str] | None = set(prop.ranges) if prop.ranges else None
        filled = 0
        for ind_uri in domain_inds:
            ind = taxonomy.owl_individuals[ind_uri]
            for pv_prop_uri, val_uri in ind.property_values:
                if pv_prop_uri != p_uri:
                    continue
                if range_set is None:
                    filled += 1
                    break
                val_ind = taxonomy.owl_individuals.get(val_uri)
                if val_ind and _effective_types(taxonomy, val_ind.types) & range_set:
                    filled += 1
                    break
        fill_pct = _pct(filled, len(domain_inds))
        lbl = prop.label(lang) or prop.local_name
        fill_fields.append(_pct_stat(f"cls:q:fill:{p_uri}", lbl, fill_pct))

    if fill_fields:
        fields.append(_sep("Property Fill"))
        fields.extend(fill_fields)

    return fields


def _concept_overview_fields(taxonomy: Taxonomy, uri: str, concept) -> list[DetailField]:
    """Overview stats for a concept's subtree — only call when concept.narrower is non-empty."""
    direct = len([u for u in concept.narrower if u in taxonomy.concepts])
    total = _count_descendants(taxonomy, uri)
    # Collect languages present in prefLabels across the subtree
    langs: set[str] = set()
    for sub_uri in _subtree_concept_uris(taxonomy, uri):
        c = taxonomy.concepts.get(sub_uri)
        if c:
            for lbl in c.labels:
                if lbl.type == LabelType.PREF:
                    langs.add(lbl.lang)
    fields = [
        _stat("stat:direct_narrower", "direct narrower", str(direct)),
        _stat("stat:total_descendants", "total descendants", str(total)),
    ]
    if langs:
        fields.append(_stat("stat:subtree_langs", "languages", ", ".join(sorted(langs))))
    return fields


def _concept_completion_fields(taxonomy: Taxonomy, uri: str) -> list[DetailField]:
    """Per-property, per-language completion bars for a concept's subtree (including itself)."""
    uris = _subtree_concept_uris(taxonomy, uri)
    if not uris:
        return []
    completions = compute_completions(taxonomy, uris)
    fields: list[DetailField] = []
    for comp in completions:
        fields.append(_sep(f"Completion — {comp.display_name}"))
        for lg, count in sorted(comp.by_language.items()):
            pct = int(count * 100 / comp.total) if comp.total else 0
            bar = _pct_bar(pct)
            fields.append(
                DetailField(
                    f"ccomp:{comp.property_key}:{lg}",
                    f"[{lg}]",
                    f"{count}/{comp.total}  {bar}  ({pct}%)",
                    editable=False,
                    meta={"type": "stat", "color": _quality_color(pct)},
                )
            )
    return fields


def _concept_mappings_fields(taxonomy: Taxonomy, concept, lang: str) -> list[DetailField]:
    """Existing cross-scheme mapping rows + remove actions."""
    _MAP_DISPLAY = (
        ("exact_match", "⟺ exactMatch"),
        ("close_match", "≈  closeMatch"),
        ("broad_match", "↑  broadMatch"),
        ("narrow_match", "↓  narrowMatch"),
        ("related_match", "↔  relatedMatch"),
    )
    fields = []
    for attr, display in _MAP_DISPLAY:
        for m_uri in getattr(concept, attr):
            mapped = taxonomy.concepts.get(m_uri)
            label_str = mapped.pref_label(lang) if mapped else m_uri
            h = taxonomy.uri_to_handle(m_uri) or "?"
            fields.append(
                DetailField(
                    f"{attr}:{m_uri}",
                    display,
                    f"{label_str}  [{h}]",
                    editable=False,
                    meta={"type": "mapping", "uri": m_uri, "nav": bool(mapped), "attr": attr},
                )
            )
            fields.append(
                DetailField(
                    f"rm_map:{attr}:{m_uri}",
                    "   ✗ Remove link",
                    "",
                    editable=False,
                    meta={"type": "mapping_remove", "uri": m_uri, "attr": attr},
                )
            )
    return fields


def _concept_action_fields(
    lang: str, concept, show_mappings: bool, configured_langs: list[str] | None = None
) -> list[DetailField]:
    """Actions section for a concept."""
    clangs = configured_langs or [lang]
    fields = []
    # Add-label/note actions, one per configured language that's still missing.
    pref_langs = {lbl.lang for lbl in concept.labels if lbl.type == LabelType.PREF}
    fields += _lang_add_actions(
        clangs,
        "action:add_pref",
        "+ Add prefLabel [{lang}]",
        "add_pref_label",
        present=pref_langs,
        green=False,
    )
    # altLabels may repeat per language → offer one for every configured language.
    fields += _lang_add_actions(
        clangs,
        "action:add_alt",
        "+ Add altLabel [{lang}]",
        "add_alt_label",
        green=False,
    )
    fields += _lang_add_actions(
        clangs,
        "action:add_def",
        "+ Add definition [{lang}]",
        "add_def",
        present={d.lang for d in concept.definitions},
        green=False,
    )
    fields += _lang_add_actions(
        clangs,
        "action:add_scope",
        "+ Add scopeNote [{lang}]",
        "add_scope_note",
        present={d.lang for d in concept.scope_notes},
        green=False,
    )
    # Structural actions
    fields.append(_add_action_field("action:add_child", "+ Add narrower concept", "add_narrower"))
    fields.append(
        _add_action_field("action:link_broader", "↑ Link to broader concept", "link_broader")
    )
    fields.append(_add_action_field("action:add_related", "~ Add related concept", "add_related"))
    fields.append(_add_action_field("action:move", "↷ Move under different parent", "move"))
    fields.append(_add_action_field("action:delete", "⊘ Delete this concept", "delete"))
    # Cross-scheme mapping actions
    if show_mappings:
        fields.append(_sep("Cross-scheme mappings"))
        for map_type, label in (
            ("exactMatch", "⟺ exactMatch  — same concept, different vocabulary"),
            ("closeMatch", "≈  closeMatch  — very similar meaning"),
            ("broadMatch", "↑  broadMatch  — target is broader"),
            ("narrowMatch", "↓  narrowMatch — target is narrower"),
            ("relatedMatch", "↔  relatedMatch — associative link"),
        ):
            fields.append(_add_action_field(f"action:map_{map_type}", label, f"map:{map_type}"))
    return fields


# ──────────────────────────── scheme-specific section helpers ─────────────────


def _scheme_settings_fields(scheme, lang: str) -> list[DetailField]:
    """URI and base URI for a scheme."""
    return [
        DetailField("scheme_uri", "URI", scheme.uri, editable=False, meta={"type": "scheme_uri"}),
        DetailField(
            "base_uri",
            "base URI",
            scheme.base_uri or "",
            editable=True,
            meta={"type": "scheme_base_uri"},
        ),
    ]


def _scheme_metadata_fields(scheme) -> list[DetailField]:
    return [
        DetailField(
            "creator", "creator", scheme.creator, editable=True, meta={"type": "scheme_creator"}
        ),
        DetailField(
            "created", "created", scheme.created, editable=True, meta={"type": "scheme_created"}
        ),
        DetailField(
            "languages",
            "declared langs",
            ", ".join(scheme.languages),
            editable=True,
            meta={"type": "scheme_languages"},
        ),
    ]


def _scheme_top_concept_fields(taxonomy: Taxonomy, scheme, lang: str) -> list[DetailField]:
    """Navigable list of top concepts — cross-links into concept detail."""
    fields = []
    for tc_uri in scheme.top_concepts:
        concept = taxonomy.concepts.get(tc_uri)
        if not concept:
            continue
        h = taxonomy.uri_to_handle(tc_uri) or "?"
        label = concept.pref_label(lang)
        n_narrower = len(concept.narrower)
        suffix = f"  ({n_narrower})" if n_narrower else ""
        fields.append(
            DetailField(
                f"tc:{tc_uri}",
                "◈ top concept",
                f"{label}  [{h}]{suffix}",
                editable=False,
                meta={"type": "relation", "uri": tc_uri, "nav": True},
            )
        )
    return fields


def _scheme_stats_fields(scheme_analysis) -> list[DetailField]:
    if scheme_analysis is None:
        return [_stat("stat:pending", "analysis", "pending…")]
    st = scheme_analysis.stats
    return [
        _stat("stat:total", "total concepts", str(st.total_concepts)),
        _stat("stat:top", "top-level", str(st.top_level_concepts)),
        _stat("stat:depth_max", "max depth", str(st.max_depth)),
        _stat("stat:depth_avg", "avg depth", f"{st.avg_depth:.1f}"),
        _stat("stat:langs", "languages", ", ".join(st.languages) if st.languages else "—"),
    ]


def _scheme_completion_fields(scheme_analysis) -> list[DetailField]:
    if scheme_analysis is None or not scheme_analysis.completions:
        return []
    fields: list[DetailField] = []
    for comp in scheme_analysis.completions:
        fields.append(_sep(f"Completion — {comp.display_name}"))
        fields.extend(_coverage_fields(f"comp:{comp.property_key}", comp))
    return fields


def _scheme_issues_fields(scheme_analysis) -> list[DetailField]:
    if scheme_analysis is None:
        return []
    return _issue_nav_fields(scheme_analysis.issues, ISSUE_DISPLAY_NAMES)


def _scheme_action_fields() -> list[DetailField]:
    return [
        _add_action_field("action:add_top_concept", "➕ Add top concept", "add_top_concept"),
    ]


# ──────────────────────────── new public builders ─────────────────────────────


def build_concept_detail(
    taxonomy: Taxonomy,
    uri: str,
    lang: str,
    analysis: dict | None = None,
    show_mappings: bool = False,
    configured_langs: list[str] | None = None,
) -> list[DetailField]:
    """Unified concept detail: Identity → Labels → Notes → Hierarchy → Mappings → Statistics → Actions."""
    concept = taxonomy.concepts.get(uri)
    if not concept:
        return []
    fields: list[DetailField] = []

    # ── Identity ────────────────────────────────────────────────────────────
    fields.append(_sep("Identity"))
    fields.extend(_concept_identity_fields(taxonomy, uri, concept, lang))

    # ── Labels ──────────────────────────────────────────────────────────────
    fields.append(_sep("Labels"))
    fields.extend(
        _section_labels_grouped(concept.labels, "pref", "alt", "prefLabel", "pref", "alt")
    )

    # ── Notes ───────────────────────────────────────────────────────────────
    has_notes = bool(concept.definitions or concept.scope_notes)
    if has_notes:
        fields.append(_sep("Notes"))
        fields.extend(_section_text_list(concept.definitions, "def", "definition", "def"))
        fields.extend(_section_text_list(concept.scope_notes, "scope", "scopeNote", "scope_note"))

    # ── Hierarchy ────────────────────────────────────────────────────────────
    has_hierarchy = bool(concept.narrower or concept.broader or concept.related)
    if has_hierarchy:
        fields.append(_sep("Hierarchy"))
        fields.extend(_concept_hierarchy_fields(taxonomy, concept, lang))

    # ── Mappings ─────────────────────────────────────────────────────────────
    has_mappings = bool(
        concept.exact_match
        or concept.close_match
        or concept.broad_match
        or concept.narrow_match
        or concept.related_match
    )
    if has_mappings:
        fields.append(_sep("Mappings"))
        fields.extend(_concept_mappings_fields(taxonomy, concept, lang))

    # ── Overview + Completion (only if has narrowers) ───────────────────────
    if concept.narrower:
        fields.append(_sep("Overview"))
        fields.extend(_concept_overview_fields(taxonomy, uri, concept))
        fields.extend(_concept_completion_fields(taxonomy, uri))  # includes its own _sep rows

    # ── Rich Content (schema.org) ─────────────────────────────────────────────
    fields.extend(_schema_media_display_fields(concept, "c:"))

    # ── Actions ──────────────────────────────────────────────────────────────
    fields.append(_sep("Actions"))
    fields.extend(_concept_action_fields(lang, concept, show_mappings, configured_langs))
    fields.extend(_schema_media_action_fields(concept, "c:"))

    return fields


def build_scheme_detail(
    taxonomy: Taxonomy,
    scheme_uri: str,
    lang: str,
    analysis: dict | None = None,
    configured_langs: list[str] | None = None,  # accepted for builder-dispatch uniformity
) -> list[DetailField]:
    """Unified scheme detail: Settings → Labels → Notes → Metadata → Top Concepts → Statistics → Completion → Issues → Actions."""
    scheme = taxonomy.schemes.get(scheme_uri)
    if not scheme:
        return []
    scheme_analysis = (analysis or {}).get(scheme_uri)
    fields: list[DetailField] = []

    # display_lang first (no separator before it — tests rely on fields[0])
    fields.append(_display_lang_field(lang))

    # ── Settings ─────────────────────────────────────────────────────────────
    fields.append(_sep("Settings"))
    fields.extend(_scheme_settings_fields(scheme, lang))

    # ── Labels ───────────────────────────────────────────────────────────────
    fields.append(_sep("Labels"))
    fields.extend(_section_pref_labels(scheme.labels, "title", "title", "scheme_title"))
    fields.extend(_section_alt_labels(scheme.labels, "alt_title", "scheme_alt_title"))

    # ── Notes (descriptions) ─────────────────────────────────────────────────
    if scheme.descriptions:
        fields.append(_sep("Notes"))
        fields.extend(_section_text_list(scheme.descriptions, "desc", "description", "scheme_desc"))

    # ── Metadata ─────────────────────────────────────────────────────────────
    fields.append(_sep("Metadata"))
    fields.extend(_scheme_metadata_fields(scheme))

    # ── Top Concepts (navigable) ──────────────────────────────────────────────
    top_fields = _scheme_top_concept_fields(taxonomy, scheme, lang)
    if top_fields:
        fields.append(_sep("Top Concepts"))
        fields.extend(top_fields)

    # ── Statistics ────────────────────────────────────────────────────────────
    fields.append(_sep("Statistics"))
    fields.extend(_scheme_stats_fields(scheme_analysis))

    # ── Completion ────────────────────────────────────────────────────────────
    comp_fields = _scheme_completion_fields(scheme_analysis)
    if comp_fields:
        fields.extend(comp_fields)

    # ── Issues ────────────────────────────────────────────────────────────────
    if scheme_analysis:
        issues = scheme_analysis.issues
        n_err = sum(1 for i in issues if i.severity == "error")
        n_warn = sum(1 for i in issues if i.severity == "warning")
        n_info = sum(1 for i in issues if i.severity == "info")
        summary_parts = []
        if n_err:
            summary_parts.append(f"{n_err} error{'s' if n_err > 1 else ''}")
        if n_warn:
            summary_parts.append(f"{n_warn} warning{'s' if n_warn > 1 else ''}")
        if n_info:
            summary_parts.append(f"{n_info} info")
        sep_label = "Issues — " + ", ".join(summary_parts) if summary_parts else "Issues"
        fields.append(_sep(sep_label))
        fields.extend(_scheme_issues_fields(scheme_analysis))

    # ── Actions ───────────────────────────────────────────────────────────────
    fields.append(_sep("Actions"))
    fields.extend(_scheme_action_fields())

    return fields


# ──────────────────────────── mixed tree (SKOS + OWL) ────────────────────────


def _ontology_display_name(taxonomy: Taxonomy, file_path: Path | None) -> str:
    """Return the display name for an ontology root node."""
    if taxonomy.ontology_label:
        return taxonomy.ontology_label
    if taxonomy.ontology_uri:
        uri = taxonomy.ontology_uri.rstrip("/")
        for sep in ("#", "/"):
            if sep in uri:
                return uri.rsplit(sep, 1)[-1]
        return taxonomy.ontology_uri
    if file_path:
        return file_path.stem
    return "OWL Ontology"


def flatten_mixed_tree(
    taxonomy_or_workspace: Taxonomy | TaxonomyWorkspace,
    folded: set[str] | None = None,
) -> list[TreeLine]:
    """Flatten 'mixed' view: Properties section, then OWL classes, then SKOS concepts.

    OWL-only files (no SKOS schemes): renders the OWL hierarchy directly.
    When both exist: Properties section first, then Classes tree, then Concepts tree.
    """
    if folded is None:
        folded = set()
    if isinstance(taxonomy_or_workspace, TaxonomyWorkspace):
        ws = taxonomy_or_workspace
        if len(ws.taxonomies) == 1:
            tax: Taxonomy | None = next(iter(ws.taxonomies.values()))
            fp = next(iter(ws.taxonomies.keys()))
            assert tax is not None
            inner = _flatten_mixed(tax, folded, file_path=fp)
        else:
            tax = None
            inner = _flatten_workspace_mixed(ws, folded)
        has_owl = any(bool(t.owl_classes) for t in ws.taxonomies.values())
    else:
        tax = taxonomy_or_workspace
        inner = _flatten_mixed(tax, folded)
        has_owl = bool(tax.owl_classes)
    if not has_owl or not inner:
        return inner
    section = _props_section_line(folded)
    children = _prop_child_lines(tax) if tax and SECTION_PROPERTIES not in folded else []
    return [section] + children + inner


def _flatten_mixed(
    taxonomy: Taxonomy,
    folded: set[str] | None = None,
    file_path: Path | None = None,
    scheme_depth: int = 0,
    scheme_prefix: str = "",
    concept_base_depth: int = 0,
) -> list[TreeLine]:
    if folded is None:
        folded = set()

    skos_rows = _flatten_taxonomy(
        taxonomy,
        folded,
        file_path=file_path,
        scheme_depth=scheme_depth,
        scheme_prefix=scheme_prefix,
        concept_base_depth=concept_base_depth,
        include_owl=False,
    )

    # Pure classes: in owl_classes but NOT already shown as SKOS concepts
    pure_class_uris = {uri for uri in taxonomy.owl_classes if uri not in taxonomy.concepts}
    if not pure_class_uris:
        return skos_rows

    # Build children index within pure classes only
    children_of: dict[str, list[str]] = {uri: [] for uri in pure_class_uris}
    roots: list[str] = []
    for uri in pure_class_uris:
        cls = taxonomy.owl_classes[uri]
        parents_in_pure = [p for p in cls.sub_class_of if p in pure_class_uris]
        if parents_in_pure:
            for p in parents_in_pure:
                children_of[p].append(uri)
        else:
            roots.append(uri)
    roots.sort()

    individuals_of = _build_individuals_of(taxonomy)
    owl_rows: list[TreeLine] = []
    _visited_mixed: set[str] = set()

    def visit_class(uri: str, depth: int, prefix: str, is_last: bool) -> None:
        if uri in _visited_mixed:
            return
        _visited_mixed.add(uri)
        connector = "└── " if is_last else "├── "
        children = children_of.get(uri, [])
        inds = individuals_of.get(uri, [])
        has_content = bool(children) or bool(inds)
        is_fold = uri in folded and has_content
        hidden = _count_class_descendants(children_of, uri, individuals_of) if is_fold else 0
        owl_rows.append(
            TreeLine(
                uri=uri,
                depth=depth,
                prefix=prefix + connector,
                is_folded=is_fold,
                hidden_count=hidden,
                file_path=file_path,
                node_type=taxonomy.node_type(uri),
            )
        )
        if not is_fold:
            ext = "    " if is_last else "│   "
            all_children = list(children)
            for i, child in enumerate(all_children):
                is_last_child = i == len(all_children) - 1 and not inds
                visit_class(child, depth + 1, prefix + ext, is_last_child)
            for j, ind_uri in enumerate(inds):
                ind_connector = "└── " if j == len(inds) - 1 else "├── "
                owl_rows.append(
                    TreeLine(
                        uri=ind_uri,
                        depth=depth + 1,
                        prefix=prefix + ext + ind_connector,
                        file_path=file_path,
                        node_type="individual",
                    )
                )

    for i, root_uri in enumerate(roots):
        visit_class(root_uri, concept_base_depth, scheme_prefix, i == len(roots) - 1)

    ontology_name = _ontology_display_name(taxonomy, file_path)
    ont_root = TreeLine(
        uri=_ontology_sentinel(file_path),
        depth=scheme_depth,
        prefix=scheme_prefix,
        is_scheme=True,
        label=ontology_name,
        file_path=file_path,
        node_type="ontology",
    )
    if not skos_rows:
        return [ont_root] + owl_rows
    return [ont_root] + owl_rows + skos_rows


def _flatten_workspace_mixed(
    workspace: TaxonomyWorkspace,
    folded: set[str] | None = None,
) -> list[TreeLine]:
    if folded is None:
        folded = set()
    result: list[TreeLine] = []

    for file_path, taxonomy in workspace.taxonomies.items():
        file_uri = _file_sentinel(file_path)
        file_folded = file_uri in folded
        hidden_in_file = 0
        if file_folded:
            for scheme in taxonomy.schemes.values():
                hidden_in_file += 1
                for tc in scheme.top_concepts:
                    if tc in taxonomy.concepts:
                        hidden_in_file += 1 + _count_descendants(taxonomy, tc)
            hidden_in_file += sum(1 for uri in taxonomy.owl_classes if uri not in taxonomy.concepts)

        result.append(
            TreeLine(
                uri=file_uri,
                depth=0,
                prefix="",
                is_file=True,
                file_path=file_path,
                is_folded=file_folded,
                hidden_count=hidden_in_file,
            )
        )
        if not file_folded:
            inner = _flatten_mixed(
                taxonomy,
                folded,
                file_path=file_path,
                scheme_depth=1,
                scheme_prefix="    ",
                concept_base_depth=1,
            )
            result.extend(inner)

    return result


# ──────────────────────────── ontology tree ──────────────────────────────────


def _count_class_descendants(
    children_of: dict[str, list[str]],
    uri: str,
    individuals_of: dict[str, list[str]] | None = None,
) -> int:
    """Count all reachable OWL class descendants + their individuals (cycle-safe)."""
    seen: set[str] = set()

    def _count(u: str) -> int:
        if u in seen:
            return 0
        seen.add(u)
        kids = children_of.get(u, [])
        ind_count = len(individuals_of.get(u, [])) if individuals_of else 0
        return len(kids) + ind_count + sum(_count(k) for k in kids)

    return _count(uri)


def _effective_types(taxonomy: Taxonomy, individual_types: list[str]) -> set[str]:
    """Return all class URIs reachable via rdfs:subClassOf from an individual's direct types.

    Includes the direct types themselves. Cycle-safe.
    """
    result: set[str] = set()

    def _walk(uri: str) -> None:
        if uri in result:
            return
        result.add(uri)
        cls = taxonomy.owl_classes.get(uri)
        if cls:
            for parent in cls.sub_class_of:
                _walk(parent)

    for t in individual_types:
        _walk(t)
    return result


def _build_individuals_of(taxonomy: Taxonomy) -> dict[str, list[str]]:
    """Return a mapping from class URI → sorted list of individual URIs typed as that class."""
    result: dict[str, list[str]] = {}
    for uri, individual in taxonomy.owl_individuals.items():
        for type_uri in individual.types:
            result.setdefault(type_uri, []).append(uri)
    for uris in result.values():
        uris.sort()
    return result


def flatten_ontology_tree(
    taxonomy_or_workspace: Taxonomy | TaxonomyWorkspace,
    folded: set[str] | None = None,
) -> list[TreeLine]:
    """Flatten the OWL/RDFS class hierarchy into TreeLine rows.

    Uses rdfs:subClassOf instead of skos:broader. Classes with no known
    parent inside the graph are treated as roots. A collapsible Properties
    section header is prepended before the class tree.
    """
    if folded is None:
        folded = set()
    if isinstance(taxonomy_or_workspace, TaxonomyWorkspace):
        ws = taxonomy_or_workspace
        if len(ws.taxonomies) == 1:
            tax = next(iter(ws.taxonomies.values()))
            fp = next(iter(ws.taxonomies.keys()))
            inner = _flatten_ontology(tax, folded, file_path=fp)
        else:
            tax = None
            inner = []
            for fp, t in ws.taxonomies.items():
                inner.extend(_flatten_ontology(t, folded, file_path=fp))
    else:
        tax = taxonomy_or_workspace
        inner = _flatten_ontology(tax, folded)
    if not inner:
        return inner
    section = _props_section_line(folded)
    children = _prop_child_lines(tax) if tax and SECTION_PROPERTIES not in folded else []
    return [section] + children + inner


def _flatten_ontology(
    taxonomy: Taxonomy,
    folded: set[str] | None = None,
    file_path: Path | None = None,
) -> list[TreeLine]:
    if folded is None:
        folded = set()

    # Individuals not typed under any known class
    unattached = sorted(
        uri
        for uri, ind in taxonomy.owl_individuals.items()
        if not any(t in taxonomy.owl_classes for t in ind.types)
    )

    if not taxonomy.owl_classes and not unattached:
        return []

    # Build parent→children index within the known owl_classes
    children_of: dict[str, list[str]] = {uri: [] for uri in taxonomy.owl_classes}
    roots: list[str] = []
    for uri, cls in taxonomy.owl_classes.items():
        parents_in_graph = [p for p in cls.sub_class_of if p in taxonomy.owl_classes]
        if parents_in_graph:
            for parent in parents_in_graph:
                children_of[parent].append(uri)
        else:
            roots.append(uri)
    roots.sort()

    individuals_of = _build_individuals_of(taxonomy)
    result: list[TreeLine] = []
    _visited: set[str] = set()

    def visit(uri: str, depth: int, prefix: str, is_last: bool) -> None:
        if uri in _visited:
            return
        _visited.add(uri)
        connector = "└── " if is_last else "├── "
        children = children_of.get(uri, [])
        inds = individuals_of.get(uri, [])
        has_content = bool(children) or bool(inds)
        is_fold = uri in folded and has_content
        hidden = _count_class_descendants(children_of, uri, individuals_of) if is_fold else 0
        result.append(
            TreeLine(
                uri=uri,
                depth=depth,
                prefix=prefix + connector,
                is_folded=is_fold,
                hidden_count=hidden,
                file_path=file_path,
                node_type=taxonomy.node_type(uri),
            )
        )
        if not is_fold:
            ext = "    " if is_last else "│   "
            all_children = list(children)
            for i, child in enumerate(all_children):
                is_last_child = i == len(all_children) - 1 and not inds
                visit(child, depth + 1, prefix + ext, is_last_child)
            for j, ind_uri in enumerate(inds):
                ind_connector = "└── " if j == len(inds) - 1 else "├── "
                result.append(
                    TreeLine(
                        uri=ind_uri,
                        depth=depth + 1,
                        prefix=prefix + ext + ind_connector,
                        file_path=file_path,
                        node_type="individual",
                    )
                )

    ontology_name = _ontology_display_name(taxonomy, file_path)
    ont_root = TreeLine(
        uri=_ontology_sentinel(file_path),
        depth=0,
        prefix="",
        is_scheme=True,
        label=ontology_name,
        file_path=file_path,
        node_type="ontology",
    )

    # ── Unattached individuals group (depth 1, always first) ─────────────────
    if unattached:
        grp_is_last = not roots
        grp_connector = "└── " if grp_is_last else "├── "
        grp_is_fold = _UNATTACHED_INDS_URI in folded
        n = len(unattached)
        noun = "individual" if n == 1 else "individuals"
        result.append(
            TreeLine(
                uri=_UNATTACHED_INDS_URI,
                depth=1,
                prefix="    " + grp_connector,
                is_folded=grp_is_fold,
                hidden_count=n if grp_is_fold else 0,
                file_path=file_path,
                node_type="unattached_group",
                label=f"Unattached {noun}  ·  {n}",
            )
        )
        if not grp_is_fold:
            child_base = "    " + ("    " if grp_is_last else "│   ")
            for j, ind_uri in enumerate(unattached):
                ind_connector = "└── " if j == n - 1 else "├── "
                result.append(
                    TreeLine(
                        uri=ind_uri,
                        depth=2,
                        prefix=child_base + ind_connector,
                        file_path=file_path,
                        node_type="individual",
                    )
                )

    # ── Root OWL classes ──────────────────────────────────────────────────────
    for i, root_uri in enumerate(roots):
        visit(root_uri, 1, "    ", i == len(roots) - 1)

    return [ont_root] + result


# ──────────────────────────── RDF class detail ───────────────────────────────

_NODE_TYPE_DISPLAY = {
    "promoted": "skos:Concept + owl:Class",
    "class": "owl:Class",
    "concept": "skos:Concept",
}


def _direct_properties(taxonomy: Taxonomy, class_uri: str) -> list:
    """Return OWLProperty objects whose domain includes *class_uri*."""
    from ..model import OWLProperty

    return [
        prop
        for prop in taxonomy.owl_properties.values()
        if class_uri in prop.domains
        if isinstance(prop, OWLProperty)
    ]


def _inherited_properties(taxonomy: Taxonomy, class_uri: str) -> list[tuple]:
    """Walk rdfs:subClassOf upward, collecting (OWLProperty, ancestor_uri) pairs.

    Direct properties are excluded. Each property appears at most once
    (diamond inheritance is de-duplicated).
    """
    direct_uris = {p.uri for p in _direct_properties(taxonomy, class_uri)}
    seen_prop_uris: set[str] = set(direct_uris)
    result: list[tuple] = []
    visited_classes: set[str] = set()

    def _walk(uri: str) -> None:
        if uri in visited_classes:
            return
        visited_classes.add(uri)
        cls = taxonomy.owl_classes.get(uri)
        if not cls:
            return
        for parent_uri in cls.sub_class_of:
            for prop in taxonomy.owl_properties.values():
                if parent_uri in prop.domains and prop.uri not in seen_prop_uris:
                    seen_prop_uris.add(prop.uri)
                    result.append((prop, parent_uri))
            _walk(parent_uri)

    _walk(class_uri)
    return result


def _add_class_property_actions(class_uri: str) -> list[DetailField]:
    """Action rows to define a new property on a class: a relationship, or an
    attribute of each supported datatype. Each row carries the prop_type and
    (for attributes) the datatype range in its meta."""
    from ..operations import SUPPORTED_DATATYPES

    rows = [
        _add_action_add_field(
            "action:add_class_property:rel",
            "+ Add relationship (object property)",
            "add_class_property",
            class_uri=class_uri,
            prop_type="ObjectProperty",
        )
    ]
    for label, range_uri in SUPPORTED_DATATYPES:
        rows.append(
            _add_action_add_field(
                f"action:add_class_property:dt:{range_uri}",
                f"+ Add attribute · {label}",
                "add_class_property",
                class_uri=class_uri,
                prop_type="DatatypeProperty",
                range_uri=range_uri,
            )
        )
    return rows


def build_rdf_class_detail(
    taxonomy: Taxonomy,
    uri: str,
    lang: str,
    configured_langs: list[str] | None = None,
) -> list[DetailField]:
    """Detail panel for an owl:Class / rdfs:Class node."""
    rdf_class = taxonomy.owl_classes.get(uri)
    if not rdf_class:
        return []

    clangs = configured_langs or [lang]
    node_t = taxonomy.node_type(uri)
    fields: list[DetailField] = []

    # ── Identity ────────────────────────────────────────────────────────────
    fields.append(_sep("Identity"))
    fields.append(DetailField("uri", "URI", uri, editable=True, meta={"type": "uri"}))
    fields.append(
        DetailField(
            "node_type",
            "type",
            _NODE_TYPE_DISPLAY.get(node_t, node_t),
            editable=False,
            meta={"type": "stat"},
        )
    )
    fields.append(
        _add_action_field(
            "action:view_focused_graph",
            "⊙ Open Graph Viz",
            "view_focused_graph",
            uri=uri,
        )
    )

    # ── Labels (rdfs:label) — always shown ──────────────────────────────────
    fields.append(_sep("Labels"))
    for lbl in sorted(rdf_class.labels, key=lambda l: l.lang):
        fields.append(
            DetailField(
                f"rdflabel:{lbl.lang}",
                f"label [{lbl.lang}]",
                lbl.value,
                editable=True,
                meta={"type": "rdf_label", "lang": lbl.lang},
            )
        )
    fields.extend(
        _lang_add_actions(
            clangs,
            "action:add_rdf_label",
            "+ Add rdfs:label [{lang}]",
            "add_rdf_label",
            present={lbl.lang for lbl in rdf_class.labels},
        )
    )

    # ── Notes (rdfs:comment) — always shown ─────────────────────────────────
    fields.append(_sep("Notes"))
    for comment in sorted(rdf_class.comments, key=lambda d: d.lang):
        fields.append(
            DetailField(
                f"rdfcomment:{comment.lang}",
                f"comment [{comment.lang}]",
                comment.value,
                editable=True,
                meta={"type": "rdf_comment", "lang": comment.lang},
            )
        )
    fields.extend(
        _lang_add_actions(
            clangs,
            "action:add_rdf_comment",
            "+ Add rdfs:comment [{lang}]",
            "add_rdf_comment",
            present={cmt.lang for cmt in rdf_class.comments},
        )
    )

    # ── Hierarchy — always shown with inline mutations ───────────────────────
    fields.append(_sep("Hierarchy"))
    for parent_uri in rdf_class.sub_class_of:
        parent_cls = taxonomy.owl_classes.get(parent_uri)
        label_str = parent_cls.label(lang) if parent_cls else parent_uri
        fields.append(
            DetailField(
                f"subclassof:{parent_uri}",
                "↑ subClassOf",
                label_str,
                editable=False,
                meta={"type": "rdf_relation", "uri": parent_uri, "nav": bool(parent_cls)},
            )
        )
        parent_lbl = parent_cls.label(lang) if parent_cls else parent_uri
        fields.append(
            _add_action_del_field(
                f"action:rm_super:{parent_uri}",
                f"  ✗ Remove subClassOf {parent_lbl}",
                "remove_superclass",
                parent_uri=parent_uri,
            )
        )
    for eq_uri in rdf_class.equivalent_class:
        eq_cls = taxonomy.owl_classes.get(eq_uri)
        label_str = eq_cls.label(lang) if eq_cls else eq_uri
        fields.append(
            DetailField(
                f"equivclass:{eq_uri}",
                "⟺ equivalentClass",
                label_str,
                editable=False,
                meta={"type": "rdf_relation", "uri": eq_uri, "nav": bool(eq_cls)},
            )
        )
    for dj_uri in rdf_class.disjoint_with:
        dj_cls = taxonomy.owl_classes.get(dj_uri)
        label_str = dj_cls.label(lang) if dj_cls else dj_uri
        fields.append(
            DetailField(
                f"disjoint:{dj_uri}",
                "⊥ disjointWith",
                label_str,
                editable=False,
                meta={"type": "rdf_relation", "uri": dj_uri, "nav": bool(dj_cls)},
            )
        )
    fields.append(
        _add_action_add_field(
            "action:link_super", "↑ Add superclass (subClassOf)", "link_superclass"
        )
    )
    if rdf_class.sub_class_of:
        fields.append(
            _add_action_field(
                "action:move_class", "↷ Move under different superclass", "move_class"
            )
        )

    # ── Subclasses — direct children of this class ───────────────────────────
    fields.append(_sep("Subclasses"))
    for child_uri, child_cls in taxonomy.owl_classes.items():
        if uri not in child_cls.sub_class_of:
            continue
        child_label = child_cls.label(lang) or child_uri
        fields.append(
            DetailField(
                f"subclass:{child_uri}",
                "↓ subclass",
                child_label,
                editable=False,
                meta={"type": "rdf_relation", "uri": child_uri, "nav": True},
            )
        )
    fields.append(_add_action_add_field("action:new_subclass", "↓ New subclass", "new_subclass"))

    # ── Instances ────────────────────────────────────────────────────────────
    fields.append(_sep("Instances"))
    n_direct = sum(1 for ind in taxonomy.owl_individuals.values() if uri in ind.types)
    if n_direct:
        fields.append(_stat("inst:count", "instances", str(n_direct)))
    fields.append(
        _add_action_add_field(
            "action:add_individual",
            "+ New individual of this class",
            "add_individual",
        )
    )

    # ── Properties ───────────────────────────────────────────────────────────
    fields.append(_sep("Properties"))
    direct_props = sorted(_direct_properties(taxonomy, uri), key=lambda p: p.label(lang))
    for prop in direct_props:
        fields.append(
            DetailField(
                f"classprop:{prop.uri}",
                prop.label(lang),
                f"owl:{prop.prop_type}",
                editable=False,
                meta={"type": "class_prop_nav", "uri": prop.uri, "nav": True},
            )
        )
    for prop, parent_uri in _inherited_properties(taxonomy, uri):
        parent_cls = taxonomy.owl_classes.get(parent_uri)
        parent_lbl = parent_cls.label(lang) if parent_cls else parent_uri
        fields.append(
            DetailField(
                f"inherited_prop:{prop.uri}:{parent_uri}",
                f"  → from {parent_lbl}: {prop.label(lang)}",
                f"owl:{prop.prop_type}",
                editable=False,
                meta={"type": "inherited_prop", "uri": prop.uri, "parent_uri": parent_uri},
            )
        )
    fields.extend(_add_class_property_actions(uri))

    # ── Subtree quality stats ────────────────────────────────────────────────
    fields.extend(_class_quality_fields(taxonomy, uri, lang))

    # ── Note (ns1:note markdown) ──────────────────────────────────────────────
    fields.extend(_note_display_fields(rdf_class.note, "cls:"))

    # ── Rich Content (schema.org) ─────────────────────────────────────────────
    fields.extend(_schema_media_display_fields(rdf_class, "cls:"))
    fields.extend(_schema_media_action_fields(rdf_class, "cls:"))

    # ── Danger Zone ──────────────────────────────────────────────────────────
    fields.append(_sep_danger("Danger Zone"))
    fields.append(
        _add_action_field(
            "action:class_to_individual",
            "⇢ Change to individual",
            "class_to_individual",
        )
    )
    fields.append(
        _add_action_del_field("action:delete_class", "⊘ Delete this class", "delete_class")
    )

    return fields


# ──────────────────────────── promoted node detail ───────────────────────────


def build_promoted_detail(
    taxonomy: Taxonomy,
    uri: str,
    lang: str,
    show_mappings: bool = False,
    configured_langs: list[str] | None = None,
) -> list[DetailField]:
    """Detail panel for a node that is both skos:Concept and owl:Class."""
    concept = taxonomy.concepts.get(uri)
    rdf_class = taxonomy.owl_classes.get(uri)
    if not concept:
        return build_rdf_class_detail(taxonomy, uri, lang)
    if not rdf_class:
        return build_concept_detail(taxonomy, uri, lang, show_mappings=show_mappings)

    fields: list[DetailField] = []

    # ── Identity ────────────────────────────────────────────────────────────
    fields.append(_sep("Identity"))
    fields.append(DetailField("uri", "URI", uri, editable=True, meta={"type": "uri"}))
    fields.append(
        DetailField(
            "node_type",
            "type",
            "skos:Concept + owl:Class",
            editable=False,
            meta={"type": "stat"},
        )
    )

    # ── SKOS section ─────────────────────────────────────────────────────────
    fields.append(_sep("SKOS — Concept"))
    fields.extend(
        _section_labels_grouped(concept.labels, "pref", "alt", "prefLabel", "pref", "alt")
    )
    if concept.definitions or concept.scope_notes:
        fields.append(_sep("Notes"))
        fields.extend(_section_text_list(concept.definitions, "def", "definition", "def"))
        fields.extend(_section_text_list(concept.scope_notes, "scope", "scopeNote", "scope_note"))
    if concept.narrower or concept.broader or concept.related:
        fields.append(_sep("SKOS Hierarchy"))
        fields.extend(_concept_hierarchy_fields(taxonomy, concept, lang))

    # ── OWL section ──────────────────────────────────────────────────────────
    fields.append(_sep("OWL — Class"))
    for lbl in sorted(rdf_class.labels, key=lambda l: l.lang):
        fields.append(
            DetailField(
                f"rdflabel:{lbl.lang}",
                f"rdfs:label [{lbl.lang}]",
                lbl.value,
                editable=True,
                meta={"type": "rdf_label", "lang": lbl.lang},
            )
        )
    for comment in sorted(rdf_class.comments, key=lambda d: d.lang):
        fields.append(
            DetailField(
                f"rdfcomment:{comment.lang}",
                f"rdfs:comment [{comment.lang}]",
                comment.value,
                editable=True,
                meta={"type": "rdf_comment", "lang": comment.lang},
            )
        )
    has_owl_hierarchy = bool(
        rdf_class.sub_class_of or rdf_class.equivalent_class or rdf_class.disjoint_with
    )
    if has_owl_hierarchy:
        fields.append(_sep("OWL Hierarchy"))
        for parent_uri in rdf_class.sub_class_of:
            parent_cls = taxonomy.owl_classes.get(parent_uri)
            label_str = parent_cls.label(lang) if parent_cls else parent_uri
            fields.append(
                DetailField(
                    f"subclassof:{parent_uri}",
                    "↑ subClassOf",
                    label_str,
                    editable=False,
                    meta={"type": "rdf_relation", "uri": parent_uri, "nav": bool(parent_cls)},
                )
            )
        for eq_uri in rdf_class.equivalent_class:
            eq_cls = taxonomy.owl_classes.get(eq_uri)
            label_str = eq_cls.label(lang) if eq_cls else eq_uri
            fields.append(
                DetailField(
                    f"equivclass:{eq_uri}",
                    "⟺ equivalentClass",
                    label_str,
                    editable=False,
                    meta={"type": "rdf_relation", "uri": eq_uri, "nav": bool(eq_cls)},
                )
            )
        for dj_uri in rdf_class.disjoint_with:
            dj_cls = taxonomy.owl_classes.get(dj_uri)
            label_str = dj_cls.label(lang) if dj_cls else dj_uri
            fields.append(
                DetailField(
                    f"disjoint:{dj_uri}",
                    "⊥ disjointWith",
                    label_str,
                    editable=False,
                    meta={"type": "rdf_relation", "uri": dj_uri, "nav": bool(dj_cls)},
                )
            )

    # ── Actions ──────────────────────────────────────────────────────────────
    fields.append(_sep("Actions"))
    fields.extend(_concept_action_fields(lang, concept, show_mappings, configured_langs))

    return fields


# ──────────────────────────── individual detail ──────────────────────────────


def build_individual_detail(
    taxonomy: Taxonomy,
    uri: str,
    lang: str,
    configured_langs: list[str] | None = None,
) -> list[DetailField]:
    """Detail panel for an owl:NamedIndividual."""
    individual = taxonomy.owl_individuals.get(uri)
    if not individual:
        return []

    clangs = configured_langs or [lang]
    fields: list[DetailField] = []

    # ── Identity ────────────────────────────────────────────────────────────
    fields.append(_sep("Identity"))
    fields.append(DetailField("uri", "URI", uri, editable=True, meta={"type": "uri"}))
    fields.append(
        DetailField(
            "node_type",
            "type",
            "owl:NamedIndividual",
            editable=False,
            meta={"type": "stat"},
        )
    )

    # ── Labels (rdfs:label) — always shown ──────────────────────────────────
    fields.append(_sep("Labels"))
    for lbl in sorted(individual.labels, key=lambda l: l.lang):
        fields.append(
            DetailField(
                f"ind_label:{lbl.lang}",
                f"label [{lbl.lang}]",
                lbl.value,
                editable=True,
                meta={"type": "ind_label", "lang": lbl.lang},
            )
        )
    fields.extend(
        _lang_add_actions(
            clangs,
            "action:add_ind_label",
            "+ Add rdfs:label [{lang}]",
            "add_ind_label",
            present={lbl.lang for lbl in individual.labels},
        )
    )

    # ── Notes (rdfs:comment) — always shown ─────────────────────────────────
    fields.append(_sep("Notes"))
    for comment in sorted(individual.comments, key=lambda d: d.lang):
        fields.append(
            DetailField(
                f"ind_comment:{comment.lang}",
                f"comment [{comment.lang}]",
                comment.value,
                editable=True,
                meta={"type": "ind_comment", "lang": comment.lang},
            )
        )
    fields.extend(
        _lang_add_actions(
            clangs,
            "action:add_ind_comment",
            "+ Add rdfs:comment [{lang}]",
            "add_ind_comment",
            present={cmt.lang for cmt in individual.comments},
        )
    )

    # ── Class Membership — always shown with inline mutations ────────────────
    fields.append(_sep("Class Membership"))
    for type_uri in sorted(individual.types):
        cls = taxonomy.owl_classes.get(type_uri)
        label_str = cls.label(lang) if cls else type_uri
        h = taxonomy.uri_to_handle(type_uri) or "?"
        fields.append(
            DetailField(
                f"ind_type:{type_uri}",
                "◈ instanceOf",
                f"{label_str}  [{h}]",
                editable=False,
                meta={"type": "rdf_relation", "uri": type_uri, "nav": bool(cls)},
            )
        )
        type_lbl = cls.label(lang) if cls else type_uri
        fields.append(
            _add_action_del_field(
                f"action:rm_ind_type:{type_uri}",
                f"  ✗ Remove instanceOf: {type_lbl}",
                "remove_ind_type",
                type_uri=type_uri,
            )
        )
    fields.append(
        _add_action_add_field(
            "action:add_ind_type",
            "+ Add class membership (rdf:type)",
            "add_ind_type",
        )
    )

    # ── Property Values — all asserted first, then applicable-but-unapplied ──
    has_any_assertion = bool(individual.property_values or individual.literal_values)
    # Track which predicates are already asserted (to suppress empty placeholders)
    asserted_pred_uris: set[str] = {pv[0] for pv in individual.property_values} | {
        lv[0] for lv in individual.literal_values
    }

    # Applicable properties (domain-matching) for the "unapplied" section
    eff_types_display = _effective_types(taxonomy, individual.types)
    applicable_unapplied = [
        (p_uri, prop)
        for p_uri, prop in sorted(taxonomy.owl_properties.items(), key=lambda kv: kv[1].label(lang))
        if p_uri not in asserted_pred_uris
        and (not prop.domains or any(t in prop.domains for t in eff_types_display))
    ]

    if has_any_assertion or applicable_unapplied:
        fields.append(_sep("Property Values"))

    # 1. URI-valued assertions (all of them, regardless of domain)
    # Group by predicate so multi-valued props appear together
    seen_preds_uri: list[str] = []
    for prop_uri, _val_uri in individual.property_values:
        if prop_uri not in seen_preds_uri:
            seen_preds_uri.append(prop_uri)
    for p_uri in seen_preds_uri:
        prop = taxonomy.owl_properties.get(p_uri)
        prop_lbl = prop.label(lang) if prop else p_uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        for _, val_uri in [(pu, vu) for pu, vu in individual.property_values if pu == p_uri]:
            target = taxonomy.owl_individuals.get(val_uri)
            val_lbl = target.label(lang) if target else val_uri
            fields.append(
                DetailField(
                    f"ind_propval:{p_uri}::{val_uri}",
                    f"→ {prop_lbl}",
                    val_lbl,
                    editable=False,
                    meta={
                        "type": "ind_prop_val",
                        "prop_uri": p_uri,
                        "val_uri": val_uri,
                        "nav": bool(target),
                    },
                )
            )
            fields.append(
                _add_action_field(
                    f"action:edit_prop_value:{p_uri}::{val_uri}",
                    f"  ✎ Change → {prop_lbl}: {val_lbl}",
                    "edit_prop_value",
                    prop_uri=p_uri,
                    val_uri=val_uri,
                )
            )
            fields.append(
                _add_action_del_field(
                    f"action:rm_prop_value:{p_uri}::{val_uri}",
                    f"  ✗ Remove → {prop_lbl}: {val_lbl}",
                    "remove_prop_value",
                    prop_uri=p_uri,
                    val_uri=val_uri,
                )
            )

    # 2. Literal-valued assertions
    seen_preds_lit: list[str] = []
    for prop_uri, _, _ in individual.literal_values:
        if prop_uri not in seen_preds_lit:
            seen_preds_lit.append(prop_uri)
    for p_uri in seen_preds_lit:
        prop = taxonomy.owl_properties.get(p_uri)
        prop_lbl = prop.label(lang) if prop else p_uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        for _, val_str, lang_or_dt in [
            (pu, vs, ld) for pu, vs, ld in individual.literal_values if pu == p_uri
        ]:
            display_val = val_str
            if lang_or_dt.startswith("@") and lang_or_dt[1:]:
                display_val = f"{val_str}  [{lang_or_dt[1:]}]"
            fields.append(
                DetailField(
                    f"ind_litval:{p_uri}::{val_str}",
                    f"→ {prop_lbl}",
                    display_val,
                    editable=False,
                    meta={
                        "type": "ind_lit_val",
                        "prop_uri": p_uri,
                        "val_str": val_str,
                        "lang_or_dt": lang_or_dt,
                    },
                )
            )
            fields.append(
                _add_action_field(
                    f"action:edit_lit_value:{p_uri}::{val_str}",
                    f"  ✎ Edit → {prop_lbl}: {val_str}",
                    "edit_literal_value",
                    prop_uri=p_uri,
                    val_str=val_str,
                    lang_or_dt=lang_or_dt,
                )
            )
            fields.append(
                _add_action_del_field(
                    f"action:rm_lit_value:{p_uri}::{val_str}",
                    f"  ✗ Remove → {prop_lbl}: {val_str}",
                    "remove_literal_value",
                    prop_uri=p_uri,
                    val_str=val_str,
                    lang_or_dt=lang_or_dt,
                )
            )

    # 3. Applicable but not yet asserted — shown as "—" placeholders
    for p_uri, prop in applicable_unapplied:
        prop_lbl = prop.label(lang)
        fields.append(
            DetailField(
                f"ind_prop_empty:{p_uri}",
                f"→ {prop_lbl}",
                "—",
                editable=False,
                meta={"type": "stat"},
            )
        )

    if has_any_assertion or applicable_unapplied:
        fields.append(
            _add_action_add_field(
                "action:add_prop_value",
                "+ Add property value",
                "add_prop_value",
            )
        )

    # ── Note (ns1:note markdown) ──────────────────────────────────────────────
    fields.extend(_note_display_fields(individual.note, "ind:"))

    # ── Rich Content (schema.org) ─────────────────────────────────────────────
    fields.extend(_schema_media_display_fields(individual, "ind:"))
    fields.extend(_schema_media_action_fields(individual, "ind:"))

    # ── Danger Zone ──────────────────────────────────────────────────────────
    fields.append(_sep_danger("Danger Zone"))
    fields.append(
        _add_action_field(
            "action:individual_to_class",
            "⇢ Change to class",
            "individual_to_class",
        )
    )
    fields.append(
        _add_action_del_field(
            "action:delete_individual", "⊘ Delete this individual", "delete_individual"
        )
    )

    return fields


# ──────────────────────────── ontology overview ──────────────────────────────


def _ontology_quality_fields(
    taxonomy: Taxonomy,
    analysis: OntologyAnalysis,
    lang: str,
) -> list[DetailField]:
    """Quality stat sections for the ontology overview panel.

    Rendered by the shared _coverage_fields / _issue_nav_fields helpers, so
    any layout or color change there applies here and to the SKOS dashboard.
    """
    fields: list[DetailField] = []
    st = analysis.stats

    # ── Classes ───────────────────────────────────────────────────────────────
    fields.append(_sep("Class Quality"))
    fields.append(_stat("ont:q:classes", "total classes", str(st.total_classes)))
    fields.append(_stat("ont:q:roots", "root classes", str(st.root_classes)))
    fields.append(_stat("ont:q:depth", "max depth", str(st.max_depth)))
    if st.total_classes:
        fields.append(_pct_stat("ont:q:lbl", "rdfs:label", st.label_pct))
        fields.append(_pct_stat("ont:q:cmt", "rdfs:comment", st.comment_pct))

    # ── By level ──────────────────────────────────────────────────────────────
    if analysis.level_summaries:
        fields.append(_sep("By Level"))
        for ls in analysis.level_summaries:
            n = ls.n_classes
            plural = "classes" if n != 1 else "class"
            fields.append(
                _pct_stat(
                    f"ont:q:lvl:{ls.depth}",
                    f"depth {ls.depth}",
                    ls.label_pct,
                    prefix=f"{n} {plural}  ·  ",
                    suffix=" labeled",
                )
            )

    # ── Individuals ───────────────────────────────────────────────────────────
    if st.total_individuals:
        fields.append(_sep("Individual Quality"))
        fields.append(_stat("ont:q:inds", "total", str(st.total_individuals)))
        fields.append(_pct_stat("ont:q:ind_lbl", "labeled", st.individual_label_pct))
        fields.append(_pct_stat("ont:q:ind_typed", "typed", st.individual_typed_pct))

    # ── Properties ────────────────────────────────────────────────────────────
    if st.total_properties:
        fields.append(_sep("Property Quality"))
        fields.append(_stat("ont:q:props", "total", str(st.total_properties)))
        fields.append(_pct_stat("ont:q:prop_lbl", "labeled", st.property_label_pct))
        fields.append(_pct_stat("ont:q:prop_dom", "has domain", st.property_with_domain_pct))
        fields.append(_pct_stat("ont:q:prop_rng", "has range", st.property_with_range_pct))

    # ── Property fill rates ────────────────────────────────────────────────────
    if analysis.property_fill_global:
        fields.append(_sep("Property Fill Rate"))
        for p_uri, fill in sorted(analysis.property_fill_global.items(), key=lambda kv: kv[1]):
            prop = taxonomy.owl_properties.get(p_uri)
            lbl = prop.label(lang) if prop else p_uri
            fill_pct = int(fill * 100)
            fields.append(_pct_stat(f"ont:q:fill:{p_uri}", lbl, fill_pct))

    # ── Issues ────────────────────────────────────────────────────────────────
    fields.append(_sep("Issues"))
    fields.extend(
        _issue_nav_fields(analysis.issues, ONTOLOGY_ISSUE_DISPLAY_NAMES, key_prefix="owl_issue")
    )

    return fields


def _ontology_identity_action_fields(taxonomy: Taxonomy) -> list[DetailField]:
    """Edit-base-URI plus, for http(s) ontologies, edit-domain / edit-prefix actions."""
    actions = [
        _add_action_field("action:edit_ontology_uri", "✎ Edit base URI", "edit_ontology_uri")
    ]
    if (taxonomy.ontology_uri or "").startswith(("http://", "https://")):
        actions.append(
            _add_action_field(
                "action:edit_ontology_domain", "✎ Edit domain", "edit_ontology_domain"
            )
        )
        actions.append(
            _add_action_field(
                "action:edit_ontology_prefix", "✎ Edit prefix", "edit_ontology_prefix"
            )
        )
    return actions


def _tui_ontology_separator(taxonomy: Taxonomy, root: str) -> str:
    """The base-URI separator: the raw trailing #/ if any, else detected from
    existing entity URIs, else ``#``."""
    raw = taxonomy.ontology_uri or ""
    if raw[-1:] in ("#", "/"):
        return raw[-1]
    for u in list(taxonomy.owl_classes) + list(taxonomy.owl_individuals):
        if len(u) > len(root) and u.startswith(root) and u[len(root)] in ("#", "/"):
            return u[len(root)]
    return "#"


def _tui_identity_rows(taxonomy: Taxonomy) -> list[DetailField]:
    """New-TUI overview identity: one line showing the full base URI (with its
    ``#`` / ``/`` separator) and the prefix. Activating it opens the identity
    modal, which edits the domain / path / separator / prefix as independent fields.
    """
    raw = taxonomy.ontology_uri
    if not raw:
        return []
    if not raw.startswith(("http://", "https://")):
        value = raw  # non-http: show as-is, no separator/prefix decomposition
    else:
        from ster.domain.onto import ontology_prefix

        root = raw.rstrip("#/")
        full = root + _tui_ontology_separator(taxonomy, root)
        prefix = ontology_prefix(taxonomy) or ""
        value = f"{full}   ·   prefix: {prefix or 'none'}"
    return [
        DetailField(
            "ont:uri",
            "URI",
            value,
            editable=False,
            meta={"type": "uri", "action": "edit_ontology_uri"},
        )
    ]


def _overview_metadata_fields(taxonomy: Taxonomy, lang: str) -> list[DetailField]:
    """Setup + ontology-metadata rows (URI, identity actions, version, title…)."""
    fields = [_sep("Setup"), _display_lang_field(lang), _sep("Ontology")]
    if taxonomy.ontology_uri:
        fields.append(
            DetailField(
                "ont:uri", "URI", taxonomy.ontology_uri, editable=False, meta={"type": "uri"}
            )
        )
        fields.extend(_ontology_identity_action_fields(taxonomy))
    if taxonomy.version_info:
        fields.append(
            DetailField(
                "ont:version_info",
                "version",
                taxonomy.version_info,
                editable=False,
                meta={"type": "stat"},
            )
        )
    if taxonomy.ontology_label:
        fields.append(
            DetailField(
                "ont:label",
                "label",
                taxonomy.ontology_label,
                editable=True,
                meta={"type": "ont_label"},
            )
        )
    fields.append(
        DetailField(
            "ont:title",
            "dcterms:title",
            taxonomy.ontology_title or "",
            editable=True,
            meta={"type": "ont_title"},
        )
    )
    fields.append(
        DetailField(
            "ont:description",
            "dcterms:description",
            taxonomy.ontology_description or "",
            editable=True,
            meta={"type": "ont_description"},
        )
    )
    return fields


def _overview_action_fields() -> list[DetailField]:
    """Creation / view actions shown on the ontology overview."""
    return [
        _sep("Actions"),
        _add_action_field(
            "action:view_ontology_graph", "⊙ View graph in browser", "view_ontology_graph"
        ),
        _add_action_field("action:create_owl_class", "+ New OWL class", "create_owl_class"),
        _add_action_field(
            "action:create_owl_property", "+ New OWL property", "create_owl_property"
        ),
        _add_action_field("action:add_scheme", "➕ Add concept scheme", "add_scheme"),
    ]


def _overview_domain_prop_rows(
    taxonomy: Taxonomy, lang: str, cls_uri: str, props_by_domain: dict[str, list[str]], depth: int
) -> list[DetailField]:
    """The ``→ property (ranges)`` rows for properties whose domain is *cls_uri*."""
    prop_indent = "  " * (depth + 1)
    rows: list[DetailField] = []
    for p_uri in sorted(props_by_domain.get(cls_uri, [])):
        prop = taxonomy.owl_properties[p_uri]
        ranges = [
            taxonomy.owl_classes[r].label(lang) if r in taxonomy.owl_classes else r
            for r in prop.ranges
        ]
        range_str = f"  ({', '.join(ranges)})" if ranges else ""
        rows.append(
            DetailField(
                f"ovw:prop:{cls_uri}:{p_uri}",
                f"{prop_indent}→ {prop.label(lang)}{range_str}",
                "",
                editable=False,
                meta={"type": "prop_nav", "uri": p_uri, "nav": True},
            )
        )
    return rows


def _overview_class_rows(
    taxonomy: Taxonomy,
    lang: str,
    cls_uri: str,
    depth: int,
    children_map: dict[str, list[str]],
    props_by_domain: dict[str, list[str]],
    folded: set[str],
) -> list[DetailField]:
    """A class row + its domain-property rows, recursing into (unfolded) children."""
    cls = taxonomy.owl_classes[cls_uri]
    children = sorted(children_map.get(cls_uri, []))
    indent = "  " * depth
    if not children:  # leaf class — a plain navigable row
        rows = [
            DetailField(
                f"ovw:cls:{cls_uri}",
                f"{indent}◈ {cls.label(lang)}",
                "",
                editable=False,
                meta={"type": "rdf_relation", "uri": cls_uri, "nav": True},
            )
        ]
        rows.extend(_overview_domain_prop_rows(taxonomy, lang, cls_uri, props_by_domain, depth))
        return rows
    is_folded_cls = cls_uri in folded
    rows = [
        DetailField(
            f"ovw:cls:{cls_uri}",
            f"{indent}{'▶' if is_folded_cls else '▼'} {cls.label(lang)}",
            "",
            editable=False,
            meta={"type": "action", "action": "toggle_class_fold", "uri": cls_uri},
        )
    ]
    if is_folded_cls:
        return rows
    rows.extend(_overview_domain_prop_rows(taxonomy, lang, cls_uri, props_by_domain, depth))
    for child_uri in children:
        rows.extend(
            _overview_class_rows(
                taxonomy, lang, child_uri, depth + 1, children_map, props_by_domain, folded
            )
        )
    return rows


def _overview_class_maps(
    taxonomy: Taxonomy,
) -> tuple[dict[str, list[str]], list[str], dict[str, list[str]]]:
    """(children_map, sorted root classes, props-by-domain) for the overview tree."""
    children_map: dict[str, list[str]] = {uri: [] for uri in taxonomy.owl_classes}
    for cls_uri, cls in taxonomy.owl_classes.items():
        for parent_uri in cls.sub_class_of:
            if parent_uri in taxonomy.owl_classes:
                children_map[parent_uri].append(cls_uri)
    root_classes = sorted(
        uri
        for uri, cls in taxonomy.owl_classes.items()
        if not any(p in taxonomy.owl_classes for p in cls.sub_class_of)
    )
    props_by_domain: dict[str, list[str]] = {}
    for p_uri, prop in taxonomy.owl_properties.items():
        for domain_uri in prop.domains:
            props_by_domain.setdefault(domain_uri, []).append(p_uri)
    return children_map, root_classes, props_by_domain


def _overview_class_hierarchy_fields(
    taxonomy: Taxonomy, lang: str, folded: set[str]
) -> list[DetailField]:
    """The folding class tree with each class's domain properties nested under it."""
    if not taxonomy.owl_classes:
        return []
    children_map, root_classes, props_by_domain = _overview_class_maps(taxonomy)
    fields = [_sep("Classes & Properties")]
    for root_uri in root_classes:
        fields.extend(
            _overview_class_rows(taxonomy, lang, root_uri, 0, children_map, props_by_domain, folded)
        )
    return fields


def _overview_all_property_fields(taxonomy: Taxonomy, lang: str) -> list[DetailField]:
    """A flat list of every property with its domain → range summary."""
    if not taxonomy.owl_properties:
        return []
    fields = [_sep("Properties")]
    for p_uri in sorted(
        taxonomy.owl_properties, key=lambda u: taxonomy.owl_properties[u].label(lang)
    ):
        prop = taxonomy.owl_properties[p_uri]
        domains = [
            taxonomy.owl_classes[d].label(lang) if d in taxonomy.owl_classes else d
            for d in prop.domains
        ]
        ranges = [
            taxonomy.owl_classes[r].label(lang) if r in taxonomy.owl_classes else r
            for r in prop.ranges
        ]
        domain_str = ", ".join(domains) if domains else "—"
        range_str = ", ".join(ranges) if ranges else "—"
        fields.append(
            DetailField(
                f"ovw:allprop:{p_uri}",
                prop.label(lang) or p_uri,
                f"owl:{prop.prop_type}  {domain_str} → {range_str}",
                editable=False,
                meta={"type": "prop_nav", "uri": p_uri, "nav": True},
            )
        )
    return fields


def build_ontology_overview_fields(
    taxonomy: Taxonomy,
    lang: str,
    folded: set[str] | None = None,
) -> list[DetailField]:
    """Detail panel for the ontology root node — assembled from section helpers.

    Shows ontology metadata, creation actions, a class hierarchy with
    fold/unfold, all properties, and subtree quality stats.
    """
    folded = folded if folded is not None else set()
    fields = _overview_metadata_fields(taxonomy, lang)
    fields.extend(_overview_action_fields())
    fields.extend(_overview_class_hierarchy_fields(taxonomy, lang, folded))
    fields.extend(_overview_all_property_fields(taxonomy, lang))
    if taxonomy.owl_classes or taxonomy.owl_individuals or taxonomy.owl_properties:
        analysis = compute_ontology_analysis(taxonomy)
        fields.extend(_ontology_quality_fields(taxonomy, analysis, lang))
    return fields


# ── Annotation catalog for the "Add metadata" picker ─────────────────────────
# Each entry: (full predicate URI, display label shown in the picker).
# When building the picker, already-present predicates are filtered out.

_ANNOTATION_CATALOG: tuple[tuple[str, str], ...] = (
    ("http://purl.org/dc/terms/creator", "dcterms:creator  (author / creator)"),
    ("http://purl.org/dc/terms/contributor", "dcterms:contributor"),
    ("http://purl.org/dc/terms/publisher", "dcterms:publisher"),
    ("http://purl.org/dc/terms/created", "dcterms:created  (xsd:date)"),
    ("http://purl.org/dc/terms/modified", "dcterms:modified  (xsd:date)"),
    ("http://purl.org/dc/terms/license", "dcterms:license  (IRI)"),
    ("http://purl.org/dc/terms/language", "dcterms:language"),
    ("http://www.w3.org/2002/07/owl#imports", "owl:imports  (IRI)"),
    ("http://purl.org/vocab/vann/preferredNamespacePrefix", "vann:preferredNamespacePrefix"),
    ("http://purl.org/vocab/vann/preferredNamespaceUri", "vann:preferredNamespaceUri  (IRI)"),
    ("http://www.w3.org/2000/01/rdf-schema#seeAlso", "rdfs:seeAlso  (IRI)"),
    ("http://xmlns.com/foaf/0.1/homepage", "foaf:homepage  (IRI)"),
    ("http://www.w3.org/2002/07/owl#versionInfo", "owl:versionInfo"),
    ("http://www.w3.org/2002/07/owl#versionIRI", "owl:versionIRI  (IRI)"),
    ("http://www.w3.org/2002/07/owl#priorVersion", "owl:priorVersion  (IRI)"),
    ("http://purl.org/dc/terms/title", "dcterms:title"),
    ("http://purl.org/dc/terms/description", "dcterms:description"),
    ("http://www.w3.org/2000/01/rdf-schema#label", "rdfs:label"),
)

# Predicates whose display label is used in the overview panel header.
_PREDICATE_DISPLAY: dict[str, str] = dict(_ANNOTATION_CATALOG)


def _annotation_display(predicate: str) -> str:
    """Short display name for a predicate — prefixed if known, else local name."""
    if predicate in _PREDICATE_DISPLAY:
        label = _PREDICATE_DISPLAY[predicate]
        return label.split("  ")[0]  # strip the parenthetical hint
    # Fall back to local name heuristic
    return predicate.rsplit("/", 1)[-1].rsplit("#", 1)[-1]


def default_annotation_catalog() -> list[tuple[str, str]]:
    """The built-in ontology-metadata predicate catalog — ``(predicate, label)``
    pairs. Used as the default when no user catalog is configured."""
    return list(_ANNOTATION_CATALOG)


# ── Entity-metadata catalog (classes / properties / individuals) ──────────────
# A separate catalog of descriptive predicates offered on any entity (not the
# ontology node). Same shape as the ontology catalog.

_ENTITY_ANNOTATION_CATALOG: tuple[tuple[str, str], ...] = (
    ("http://www.w3.org/2000/01/rdf-schema#seeAlso", "rdfs:seeAlso  (IRI)"),
    ("http://www.w3.org/2000/01/rdf-schema#isDefinedBy", "rdfs:isDefinedBy  (IRI)"),
    ("http://www.w3.org/2004/02/skos/core#note", "skos:note"),
    ("http://www.w3.org/2004/02/skos/core#example", "skos:example"),
    ("http://purl.org/dc/terms/source", "dcterms:source"),
)


def default_entity_annotation_catalog() -> list[tuple[str, str]]:
    """The built-in entity-metadata predicate catalog — ``(predicate, label)``
    pairs offered on classes / properties / individuals when none is configured."""
    return list(_ENTITY_ANNOTATION_CATALOG)


def annotation_catalog_options(
    taxonomy: Taxonomy, catalog: list[tuple[str, str]] | None = None
) -> list[tuple[str, str]]:
    """Return ``(predicate_uri, display_label)`` pairs available for "Add metadata".

    *catalog* is the configured predicate catalog (built-in default when ``None``);
    predicates already present in ``taxonomy.ontology_annotations`` are filtered out
    so the picker only shows what can still be added.
    """
    cat = catalog if catalog is not None else list(_ANNOTATION_CATALOG)
    present = {a.predicate for a in taxonomy.ontology_annotations}
    return [(pred, label) for pred, label in cat if pred not in present]


def _annotation_rows(annotation: OntologyAnnotation) -> list[DetailField]:
    """One editable value row + one remove-action row for a single annotation."""
    display = _annotation_display(annotation.predicate)
    value_row = DetailField(
        key=f"ann:{annotation.predicate}:{annotation.value}",
        display=display,
        value=annotation.value,
        editable=True,
        meta={
            "type": "ont_annotation",
            "predicate": annotation.predicate,
            "old_value": annotation.value,
            "is_iri": annotation.is_iri,
            "lang": annotation.lang,
        },
    )
    remove_row = DetailField(
        key=f"ann:remove:{annotation.predicate}:{annotation.value}",
        display=f"  ✕ remove {display}",
        value="",
        editable=False,
        meta={
            "type": "action_del",
            "action": "remove_ont_annotation",
            "predicate": annotation.predicate,
            "value": annotation.value,
        },
    )
    return [value_row, remove_row]


def _class_depths(taxonomy: Taxonomy) -> dict[str, int]:
    """Depth of each OWL class = its longest local subClassOf chain (roots = 0)."""
    classes = taxonomy.owl_classes
    cache: dict[str, int] = {}

    def depth(uri: str, seen: frozenset[str]) -> int:
        if uri in cache:
            return cache[uri]
        if uri in seen:  # cycle guard
            return 0
        cls = classes.get(uri)
        parents = [p for p in cls.sub_class_of if p in classes] if cls else []
        cache[uri] = 1 + max((depth(p, seen | {uri}) for p in parents), default=-1)
        return cache[uri]

    return {uri: depth(uri, frozenset()) for uri in classes}


def _bar_stat(key: str, label: str, count: int, total: int) -> DetailField:
    """A coverage row rendered as a block bar + percentage, e.g. '████░░░░  50%'."""
    percent = _pct(count, total)
    return _pct_stat(key, label, percent)


def _stats_classes(taxonomy: Taxonomy) -> list[DetailField]:
    classes = taxonomy.owl_classes
    roots = sum(1 for c in classes.values() if not any(p in classes for p in c.sub_class_of))
    parents = {p for c in classes.values() for p in c.sub_class_of if p in classes}
    leaves = sum(1 for uri in classes if uri not in parents)
    fields = [
        _sep("Classes"),
        _stat("st:classes", "total", str(len(classes))),
        _stat("st:roots", "root classes", str(roots)),
        _stat("st:leaves", "leaf classes", str(leaves)),
    ]
    depths = _class_depths(taxonomy)
    if depths:
        avg = sum(depths.values()) / len(depths)
        fields.append(_stat("st:avg_depth", "avg depth", f"{avg:.1f}"))
        fields.append(_stat("st:max_depth", "max depth", str(max(depths.values()))))
    return fields


def _stats_properties(taxonomy: Taxonomy) -> list[DetailField]:
    props = taxonomy.owl_properties
    obj = sum(1 for p in props.values() if p.prop_type == "ObjectProperty")
    datatype = sum(1 for p in props.values() if p.prop_type == "DatatypeProperty")
    incomplete = sum(1 for p in props.values() if not p.domains or not p.ranges)
    return [
        _sep("Properties"),
        _stat("st:props", "total", str(len(props))),
        _stat("st:obj_props", "object", str(obj)),
        _stat("st:dt_props", "datatype", str(datatype)),
        _stat("st:incomplete_props", "missing domain/range", str(incomplete)),
    ]


def _stats_individuals(taxonomy: Taxonomy) -> list[DetailField]:
    classes = taxonomy.owl_classes
    typed = {t for ind in taxonomy.owl_individuals.values() for t in ind.types}
    unused = sum(1 for uri in classes if uri not in typed)
    return [
        _sep("Individuals"),
        _stat("st:individuals", "total", str(len(taxonomy.owl_individuals))),
        _stat("st:unused", "classes with no individuals", str(unused)),
    ]


def _class_languages(classes: dict) -> list[str]:
    """Sorted list of every language tag appearing on a class label."""
    return sorted({lbl.lang for c in classes.values() for lbl in c.labels if lbl.lang})


def _lang_coverage_rows(classes: dict, langs: list[str], total: int) -> list[DetailField]:
    """One coverage bar per language: how many classes carry a label in it."""
    rows: list[DetailField] = []
    for code in langs:
        covered = sum(1 for c in classes.values() if any(lbl.lang == code for lbl in c.labels))
        rows.append(_bar_stat(f"st:lang_cov:{code}", f"labels · {code}", covered, total))
    return rows


def _stats_quality(
    taxonomy: Taxonomy, configured_langs: list[str] | None = None
) -> list[DetailField]:
    classes = taxonomy.owl_classes
    total = len(classes)
    # Heading + class label/documentation coverage. "labelled" accepts rdfs:label or
    # skos:prefLabel; "documented" is rdfs:comment — each row names its predicate(s).
    fields: list[DetailField] = [_sep("Quality & Coverage")]
    if total:
        labelled = sum(1 for c in classes.values() if _is_labelled(c))
        commented = sum(1 for c in classes.values() if c.comments)
        fields.append(
            _bar_stat("st:label_cov", "labelled (rdfs:label / skos:prefLabel)", labelled, total)
        )
        fields.append(_bar_stat("st:comment_cov", "documented (rdfs:comment)", commented, total))
    # Language coverage — reported over the configured languages when known, else over
    # the languages detected in the data.
    langs = configured_langs if configured_langs is not None else _class_languages(classes)
    summary = str(len(langs)) + (f" ({', '.join(langs)})" if langs else "")
    fields.append(_sep("Languages"))
    fields.append(_stat("st:langs", "languages", summary))
    if total:
        fields.extend(_lang_coverage_rows(classes, langs, total))
    return fields


def _stats_metadata(metadata: dict | None) -> list[DetailField]:
    """The "Metadata coverage" subsection: how completely the configured annotation
    properties are populated (ontology header + entities). Omitted when neither
    percentage is computable (no catalogs configured)."""
    if not metadata:
        return []
    ont, ent = metadata.get("ontology_pct"), metadata.get("entity_pct")
    if ont is None and ent is None:
        return []
    fields: list[DetailField] = [_sep("Metadata coverage")]
    if ont is not None:
        fields.append(_pct_stat("st:meta_ont", "Ontology Metadata", ont))
    if ent is not None:
        fields.append(_pct_stat("st:meta_entity", "Entity Metadata", ent))
    return fields


def _ontology_stats_fields(
    taxonomy: Taxonomy,
    configured_langs: list[str] | None = None,
    metadata: dict | None = None,
) -> list[DetailField]:
    """Global ontology statistics, grouped into visual subject sections."""
    return [
        *_stats_classes(taxonomy),
        *_stats_properties(taxonomy),
        *_stats_individuals(taxonomy),
        *_stats_quality(taxonomy, configured_langs),
        *_stats_metadata(metadata),
    ]


def _errors_color(count: int) -> str:
    """Errors: red when there are any, green when clean."""
    return "red" if count else "green"


def _warnings_color(count: int) -> str:
    """Warnings: < 10 green, 10–49 orange, ≥ 50 red."""
    if count >= 50:
        return "red"
    if count >= 10:
        return "orange"
    return "green"


def _lint_count_field(severity: str, label: str, count: int) -> DetailField:
    """A severity count row, coloured by its own rule (errors / warnings). When
    ``count`` > 0 the row links to a modal listing only that severity's issues
    (``action=view_lint`` + ``lint_severity``); when 0 it is a plain info row."""
    meta: dict = {"action": "view_lint", "lint_severity": severity} if count else {"type": "stat"}
    meta["color"] = (_errors_color if severity == "error" else _warnings_color)(count)
    return DetailField(f"st:lint_{severity}", label, str(count), editable=False, meta=meta)


def _ontology_lint_fields(lint: dict | None) -> list[DetailField]:
    """semanticlint summary — an Errors row and a Warnings row, each linking to a
    severity-filtered issue modal when its count is non-zero.

    *lint* is a ``{severity: count}`` dict (from ``lint_runner.lint_overview``),
    or ``None`` when no file is loaded (the section is then omitted).
    """
    if lint is None:
        return []
    return [
        _sep("Errors and Warnings"),
        _lint_count_field("error", "Errors", lint.get("error", 0)),
        _lint_count_field("warning", "Warnings", lint.get("warning", 0)),
    ]


def _ontology_activity_fields(activity: dict | None) -> list[DetailField]:
    """Git edit-activity rows (from ``git.manager.file_activity``), if available."""
    if not activity:
        return []
    return [
        _sep("Activity"),
        _stat("st:last_edit", "last edited", str(activity["last"])),
        _stat("st:total_edits", "total edits", str(activity["total"])),
        _stat("st:edits_month", "edits (last 30 days)", str(activity["last_month"])),
    ]


def build_tui_ontology_overview_fields(
    taxonomy: Taxonomy,
    lang: str,
    activity: dict | None = None,
    lint: dict | None = None,
    configured_langs: list[str] | None = None,
    metadata: dict | None = None,
) -> list[DetailField]:
    """The ontology overview's detail fields.

    Thin wrapper over :class:`OntologyOverviewPresenter` (the live render path);
    kept so existing callers/tests reach the same presenter-produced fields.
    Imported lazily to avoid a tui→logic import cycle.
    """
    from ster.tui.presenters.context import PresenterContext
    from ster.tui.presenters.overview import OntologyOverviewPresenter

    ctx = PresenterContext(taxonomy, lang, configured_langs, activity, lint, metadata)
    return OntologyOverviewPresenter(ctx, "").render()


def build_tui_taxonomy_overview_fields(taxonomy: Taxonomy, lang: str) -> list[DetailField]:
    """Detail panel for the Taxonomy (SKOS) overview node — New-TUI only.

    Mirrors the ontology overview but with the *taxonomy's* identity and metadata:
    the concept-scheme namespace + prefix, and the scheme's SKOS metadata (title,
    creator, created, languages, descriptions, other annotations).
    """
    scheme = taxonomy.primary_scheme()
    if scheme is None:
        return [_stat("tax:none", "", "No concept scheme in this taxonomy yet.")]

    target = scheme.uri  # scheme-keyed edits route here via meta["target_uri"]

    def _scheme_field(key: str, label: str, value: str, ftype: str) -> DetailField:
        return DetailField(
            key, label, value, editable=True, meta={"type": ftype, "target_uri": target}
        )

    fields: list[DetailField] = [_sep("Metadata")]
    fields.append(_scheme_field("tax:title", "title", scheme.title(lang), "scheme_title"))
    fields.append(_scheme_field("tax:creator", "creator", scheme.creator, "scheme_creator"))
    fields.append(_scheme_field("tax:created", "created", scheme.created, "scheme_created"))
    fields.append(
        _scheme_field("tax:langs", "languages", ", ".join(scheme.languages), "scheme_languages")
    )
    for i, desc in enumerate(scheme.descriptions):
        fields.append(_stat(f"tax:desc:{i}", "description", desc.value))
    for annotation in scheme.annotations:
        fields.append(
            _stat(
                f"tax:ann:{annotation.predicate}",
                _annotation_display(annotation.predicate),
                annotation.value,
            )
        )
    return fields


# ──────────────────────────── OWL property detail ────────────────────────────


def build_property_detail(
    taxonomy: Taxonomy,
    uri: str,
    lang: str,
    configured_langs: list[str] | None = None,
) -> list[DetailField]:
    """Detail panel for an owl:ObjectProperty / DatatypeProperty / etc."""
    prop = taxonomy.owl_properties.get(uri)
    if not prop:
        return []

    clangs = configured_langs or [lang]
    fields: list[DetailField] = []

    # ── Identity ─────────────────────────────────────────────────────────────
    fields.append(_sep("Identity"))
    fields.append(DetailField("uri", "URI", uri, editable=True, meta={"type": "uri"}))
    fields.append(
        DetailField(
            "prop_type",
            "type",
            f"owl:{prop.prop_type}",
            editable=False,
            meta={"type": "stat"},
        )
    )

    # ── Labels ───────────────────────────────────────────────────────────────
    if prop.labels:
        fields.append(_sep("Labels"))
        for lbl in sorted(prop.labels, key=lambda l: l.lang):
            fields.append(
                DetailField(
                    f"prop_label:{lbl.lang}",
                    f"label [{lbl.lang}]",
                    lbl.value,
                    editable=True,
                    meta={"type": "prop_label", "lang": lbl.lang},
                )
            )

    # ── Notes ────────────────────────────────────────────────────────────────
    if prop.comments:
        fields.append(_sep("Notes"))
        for cmt in sorted(prop.comments, key=lambda d: d.lang):
            fields.append(
                DetailField(
                    f"prop_comment:{cmt.lang}",
                    f"comment [{cmt.lang}]",
                    cmt.value,
                    editable=True,
                    meta={"type": "prop_comment", "lang": cmt.lang},
                )
            )

    # ── Signature (domain / range / subPropertyOf / inverseOf) ───────────────
    has_sig = bool(prop.domains or prop.ranges or prop.sub_property_of or prop.inverse_of)
    if has_sig:
        fields.append(_sep("Signature"))
        for d_uri in prop.domains:
            cls = taxonomy.owl_classes.get(d_uri)
            fields.append(
                DetailField(
                    f"prop_domain:{d_uri}",
                    "domain",
                    cls.label(lang) if cls else d_uri,
                    editable=False,
                    meta={"type": "rdf_relation", "uri": d_uri, "nav": bool(cls)},
                )
            )
        for r_uri in prop.ranges:
            cls = taxonomy.owl_classes.get(r_uri)
            fields.append(
                DetailField(
                    f"prop_range:{r_uri}",
                    "range",
                    cls.label(lang) if cls else r_uri,
                    editable=False,
                    meta={"type": "rdf_relation", "uri": r_uri, "nav": bool(cls)},
                )
            )
        for sp_uri in prop.sub_property_of:
            sp = taxonomy.owl_properties.get(sp_uri)
            fields.append(
                DetailField(
                    f"prop_sub:{sp_uri}",
                    "↑ subPropertyOf",
                    sp.label(lang) if sp else sp_uri,
                    editable=False,
                    meta={"type": "prop_nav", "uri": sp_uri, "nav": bool(sp)},
                )
            )
        for inv_uri in prop.inverse_of:
            inv = taxonomy.owl_properties.get(inv_uri)
            fields.append(
                DetailField(
                    f"prop_inv:{inv_uri}",
                    "⟺ inverseOf",
                    inv.label(lang) if inv else inv_uri,
                    editable=False,
                    meta={"type": "prop_nav", "uri": inv_uri, "nav": bool(inv)},
                )
            )

    # ── Note (ns1:note markdown) ──────────────────────────────────────────────
    fields.extend(_note_display_fields(prop.note, "prop:"))

    # ── Actions ──────────────────────────────────────────────────────────────
    fields.append(_sep("Actions"))
    fields.extend(
        _lang_add_actions(
            clangs,
            "action:add_prop_label",
            "+ Add rdfs:label [{lang}]",
            "add_prop_label",
            present={lbl.lang for lbl in prop.labels},
            green=False,
        )
    )
    fields.extend(
        _lang_add_actions(
            clangs,
            "action:add_prop_comment",
            "+ Add rdfs:comment [{lang}]",
            "add_prop_comment",
            present={cmt.lang for cmt in prop.comments},
            green=False,
        )
    )
    fields.append(
        _add_action_field("action:add_prop_domain", "→ Add domain class", "add_prop_domain")
    )
    fields.append(_add_action_field("action:add_prop_range", "→ Add range class", "add_prop_range"))
    for d_uri in prop.domains:
        cls = taxonomy.owl_classes.get(d_uri)
        d_lbl = cls.label(lang) if cls else d_uri
        fields.append(
            _add_action_field(
                f"action:rm_prop_domain:{d_uri}",
                f"✗ Remove domain {d_lbl}",
                "remove_prop_domain",
                domain_uri=d_uri,
            )
        )
    for r_uri in prop.ranges:
        cls = taxonomy.owl_classes.get(r_uri)
        r_lbl = cls.label(lang) if cls else r_uri
        fields.append(
            _add_action_field(
                f"action:rm_prop_range:{r_uri}",
                f"✗ Remove range {r_lbl}",
                "remove_prop_range",
                range_uri=r_uri,
            )
        )
    fields.append(
        _add_action_field("action:delete_property", "⊘ Delete this property", "delete_property")
    )

    return fields


def build_properties_section_fields(taxonomy: Taxonomy, lang: str) -> list[DetailField]:
    """Detail panel for the Properties section header node.

    Shows completeness stats (label / domain / range coverage) and a
    selectable, alphabetically-sorted list of every OWL property.  Selecting
    an item navigates the left tree to that property.
    """
    props = list(taxonomy.owl_properties.values())
    n = len(props)

    fields: list[DetailField] = []

    # ── Overview stats ────────────────────────────────────────────────────────
    fields.append(_sep("Properties"))
    fields.append(_stat("props:total", "total", str(n)))

    n_data = sum(1 for p in props if p.prop_type == "DatatypeProperty")
    n_obj = sum(1 for p in props if p.prop_type == "ObjectProperty")
    n_ann = sum(1 for p in props if p.prop_type == "AnnotationProperty")
    if n_data:
        fields.append(_stat("props:data", "data properties", str(n_data)))
    if n_obj:
        fields.append(_stat("props:obj", "object properties", str(n_obj)))
    if n_ann:
        fields.append(_stat("props:ann", "annotation properties", str(n_ann)))

    # ── Completeness ─────────────────────────────────────────────────────────
    if n:
        fields.append(_sep("Completeness"))
        lbl_pct = _pct(sum(1 for p in props if p.labels), n)
        dom_pct = _pct(sum(1 for p in props if p.domains), n)
        rng_pct = _pct(sum(1 for p in props if p.ranges), n)
        fields.append(_pct_stat("props:cov:label", "rdfs:label", lbl_pct))
        fields.append(_pct_stat("props:cov:domain", "rdfs:domain", dom_pct))
        fields.append(_pct_stat("props:cov:range", "rdfs:range", rng_pct))

    # ── Action (before list so it stays visible) ─────────────────────────────
    fields.append(_sep("Actions"))
    fields.append(
        _add_action_add_field(
            "action:create_owl_property", "+ New OWL property", "create_owl_property"
        )
    )

    # ── Property list ─────────────────────────────────────────────────────────
    if props:
        fields.append(_sep("All properties"))
        for prop in sorted(props, key=lambda p: p.label(lang).lower()):
            display = prop.label(lang)
            tag = f"  [{prop.prop_type[:3]}]" if prop.prop_type else ""
            fields.append(
                DetailField(
                    f"prop_nav:{prop.uri}",
                    display,
                    prop.uri + tag,
                    editable=False,
                    meta={"type": "navigate_property", "uri": prop.uri, "nav": True},
                )
            )

    return fields


# ── Backward-compat aliases ───────────────────────────────────────────────────


def build_detail_fields(
    taxonomy: Taxonomy,
    uri: str,
    lang: str,
    show_mappings: bool = False,
) -> list[DetailField]:
    """Backward-compat alias for build_concept_detail."""
    return build_concept_detail(taxonomy, uri, lang, show_mappings=show_mappings)


def _display_lang_field(lang: str) -> DetailField:
    """Shared 'display language' action field used in every detail panel."""
    return DetailField(
        "display_lang",
        "display language",
        lang,
        editable=False,
        meta={"type": "action", "action": "pick_lang"},
    )


def _available_langs(taxonomy: Taxonomy) -> list[str]:
    """Return sorted list of all language codes present in the taxonomy."""
    langs: set[str] = set()
    scheme = taxonomy.primary_scheme()
    if scheme:
        for lbl in scheme.labels:
            langs.add(lbl.lang)
        for desc in scheme.descriptions:
            langs.add(desc.lang)
        langs.update(scheme.languages)
    for concept in taxonomy.concepts.values():
        for lbl in concept.labels:
            langs.add(lbl.lang)
        for defn in concept.definitions:
            langs.add(defn.lang)
    for cls in taxonomy.owl_classes.values():
        for lbl in cls.labels:
            langs.add(lbl.lang)
    for ind in taxonomy.owl_individuals.values():
        for lbl in ind.labels:
            langs.add(lbl.lang)
    for prop in taxonomy.owl_properties.values():
        for lbl in prop.labels:
            langs.add(lbl.lang)
    return sorted(langs)


# ──────────────────────────── scheme dashboard ────────────────────────────────


def build_scheme_fields(
    taxonomy: Taxonomy,
    lang: str,
    scheme_uri: str | None = None,
) -> list[DetailField]:
    """Compat alias with old arg order: (taxonomy, lang, scheme_uri=None)."""
    if scheme_uri is None:
        scheme = taxonomy.primary_scheme()
        if not scheme:
            return []
        scheme_uri = scheme.uri
    return build_scheme_detail(taxonomy, scheme_uri, lang, analysis=None)


def build_scheme_dashboard_fields(
    taxonomy: Taxonomy,
    analysis: dict[str, SchemeAnalysis] | None,
    scheme_uri: str,
    lang: str,
) -> list[DetailField]:
    """Deprecated alias: use build_scheme_detail instead."""
    return build_scheme_detail(taxonomy, scheme_uri, lang, analysis=analysis)


# ──────────────────────────── global overview ────────────────────────────────


def _load_bearer_token() -> str:
    """Return the persisted bearer token, or a placeholder if not yet created."""
    from ..api_server import _TOKEN_FILE  # noqa: PLC0415

    if _TOKEN_FILE.exists():
        return _TOKEN_FILE.read_text().strip()
    return "(not yet created — launch ster view first)"


_HELP_HINTS: list[tuple[str, str]] = [
    ("↑ ↓  /  j k", "navigate tree"),
    ("Enter", "focus detail panel"),
    ("← / Esc", "back"),
    ("Space", "fold / unfold subtree"),
    ("+ / a / A", "add narrower / child / top concept"),
    ("/", "search"),
    ("m", "move concept"),
    ("b", "add broader link"),
    ("g / G", "jump to first / last"),
    ("?", "full help screen"),
    ("q", "quit"),
]


# ── Individual candidate builder ──────────────────────────────────────────────


def build_individual_candidates_grouped(
    taxonomy: Taxonomy,
    lang: str,
    prop_ranges: list[str],
    exclude_uri: str,
) -> list[tuple[str, str]]:
    """Return grouped (uri, label) candidates for an individual-value picker.

    When *prop_ranges* is non-empty only individuals from those classes and
    their subclasses are included.  When empty every class is searched.
    Header rows have a ``__HDR__:<class_uri>`` sentinel URI and are not
    selectable.  *exclude_uri* is omitted from results (the source individual).
    """
    range_roots: list[str] = list(prop_ranges) if prop_ranges else sorted(taxonomy.owl_classes)

    candidates: list[tuple[str, str]] = []
    added_ind_uris: set[str] = set()
    seen_class_uris: set[str] = set()

    def add_group(class_uri: str, depth: int) -> None:
        if class_uri in seen_class_uris:
            return
        seen_class_uris.add(class_uri)

        cls = taxonomy.owl_classes.get(class_uri)
        cls_lbl = cls.label(lang) if cls else class_uri
        indent = "  " * depth

        sub_uris = sorted(u for u, c in taxonomy.owl_classes.items() if class_uri in c.sub_class_of)
        direct_inds = sorted(
            [
                (uri, ind)
                for uri, ind in taxonomy.owl_individuals.items()
                if uri != exclude_uri and uri not in added_ind_uris and class_uri in ind.types
            ],
            key=lambda kv: kv[1].label(lang),
        )

        if not sub_uris and not direct_inds:
            return

        candidates.append((f"__HDR__:{class_uri}", f"{indent}▸ {cls_lbl}"))

        for sub_uri in sub_uris:
            add_group(sub_uri, depth + 1)

        for i_uri, ind in direct_inds:
            if i_uri not in added_ind_uris:
                h = taxonomy.uri_to_handle(i_uri) or "?"
                lbl = ind.label(lang)
                candidates.append((i_uri, f"{indent}  [{h}]  {lbl}"))
                added_ind_uris.add(i_uri)

    for root in range_roots:
        add_group(root, 0)

    return candidates


def build_global_fields(
    workspace: TaxonomyWorkspace | None,
    analysis: dict[str, SchemeAnalysis] | None,
    lang: str,
    server_url: str = "http://127.0.0.1",
    server_port: int = 8765,
    show_token: bool = False,
    pending_restart: bool = False,
    ontology_slug: str | None = None,
) -> list[DetailField]:
    """Build DetailField list for the global overview panel.

    When *workspace* is None only Local Server Configuration and LLM Setup
    sections are included (used by the standalone config screen).
    """

    fields: list[DetailField] = []

    # ── 1. Local Server Configuration ─────────────────────────────────────────
    fields.append(_sep("Local Server Configuration"))
    if pending_restart:
        fields.append(
            DetailField(
                "server:restart_warning",
                "⚠ restart required",
                "close browser tabs then relaunch ster",
                editable=False,
                meta={"type": "warning"},
            )
        )
    fields.append(
        DetailField(
            "server:url",
            "server URL",
            server_url,
            editable=False,
            meta={"type": "action", "action": "edit_server_url"},
        )
    )
    fields.append(
        DetailField(
            "server:port",
            "port",
            str(server_port),
            editable=False,
            meta={"type": "action", "action": "edit_server_port"},
        )
    )
    _token_value = _load_bearer_token() if show_token else "***"
    fields.append(
        DetailField(
            "server:token",
            "bearer token",
            _token_value,
            editable=False,
            meta={"type": "action", "action": "show_bearer_token"},
        )
    )
    if ontology_slug is not None:
        _host = server_url.rstrip("/")
        fields.append(
            DetailField(
                "ontology:serving_url",
                "ontology serving URL",
                f"{_host}:{server_port}/{ontology_slug}",
                editable=False,
                meta={"type": "stat"},
            )
        )
        fields.append(
            DetailField(
                "ontology:viz_url",
                "VoWL graph URL",
                f"{_host}:{server_port}/viz",
                editable=False,
                meta={"type": "stat"},
            )
        )

    # ── 2. LLM Setup ──────────────────────────────────────────────────────────
    fields.append(_sep("LLM Setup"))
    fields.append(_display_lang_field(lang))
    fields.append(_add_action_field("llm:ai_config", "configure AI model", "open_ai_config"))

    if workspace is None:
        return fields

    # ── 3. Keyboard shortcuts ─────────────────────────────────────────────────
    fields.append(_sep("Keyboard Shortcuts"))
    for keys, desc in _HELP_HINTS:
        fields.append(
            DetailField(
                f"help:{keys}",
                keys,
                desc,
                editable=False,
                meta={"type": "stat"},
            )
        )

    # ── 3. Overview stats ─────────────────────────────────────────────────────
    n_files = len(workspace.taxonomies)
    all_taxes = list(workspace.taxonomies.values())
    n_schemes = sum(len(t.schemes) for t in all_taxes)
    n_concepts = sum(len(t.concepts) for t in all_taxes)
    n_owl = sum(len(t.owl_classes) for t in all_taxes)
    n_promoted = sum(sum(1 for uri in t.owl_classes if uri in t.concepts) for t in all_taxes)
    n_pure = n_owl - n_promoted
    all_langs: set[str] = set()
    for t in all_taxes:
        for c in t.concepts.values():
            for lbl in c.labels:
                if lbl.value:
                    all_langs.add(lbl.lang)

    fields.append(_sep("Overview"))
    fields.append(
        DetailField(
            "g:files", "taxonomy files", str(n_files), editable=False, meta={"type": "stat"}
        )
    )
    if n_schemes:
        fields.append(
            DetailField(
                "g:schemes",
                "concept schemes",
                str(n_schemes),
                editable=False,
                meta={"type": "stat"},
            )
        )
    if n_concepts:
        fields.append(
            DetailField(
                "g:concepts",
                "total concepts",
                str(n_concepts),
                editable=False,
                meta={"type": "stat"},
            )
        )
    if n_owl:
        fields.append(
            DetailField("g:owl", "OWL classes", str(n_owl), editable=False, meta={"type": "stat"})
        )
    fields.append(
        DetailField(
            "g:langs",
            "languages",
            ", ".join(sorted(all_langs)) if all_langs else "—",
            editable=False,
            meta={"type": "stat"},
        )
    )

    # ── 4. OWL classes quality (always shown when classes present) ────────────
    if n_owl:
        max_depth = max(
            (compute_owl_analysis(t).max_depth for t in all_taxes if t.owl_classes),
            default=0,
        )
        missing_lbl = sum(
            sum(1 for cls in t.owl_classes.values() if not cls.labels) for t in all_taxes
        )
        missing_cmt = sum(
            sum(1 for cls in t.owl_classes.values() if not cls.comments) for t in all_taxes
        )
        fields.append(_sep("OWL Classes"))
        if n_promoted:
            fields.append(_stat("owl:promoted", "promoted (concept+class)", str(n_promoted)))
        if n_pure:
            fields.append(_stat("owl:pure", "pure classes", str(n_pure)))
        fields.append(_stat("owl:depth", "max depth", str(max_depth)))
        if missing_lbl:
            fields.append(_stat("owl:miss_lbl", "missing rdfs:label", str(missing_lbl)))
        if missing_cmt:
            fields.append(_stat("owl:miss_cmt", "missing rdfs:comment", str(missing_cmt)))

    # ── 5. Completeness / Quality (SKOS only — skip when no schemes) ──────────
    if n_schemes:
        if analysis:
            agg: dict[str, tuple[str, int, dict[str, int]]] = {}
            for sa in analysis.values():
                for comp in sa.completions:
                    if comp.property_key not in agg:
                        agg[comp.property_key] = (comp.display_name, 0, {})
                    disp, tot, by_lang = agg[comp.property_key]
                    tot += comp.total
                    for lg, cnt in comp.by_language.items():
                        by_lang[lg] = by_lang.get(lg, 0) + cnt
                    agg[comp.property_key] = (disp, tot, by_lang)

            if agg:
                fields.append(_sep("Completeness"))
                for prop_key, (disp, total, by_lang) in agg.items():
                    if total == 0:
                        continue
                    best_lang, best_cnt = (
                        max(by_lang.items(), key=lambda kv: kv[1]) if by_lang else ("—", 0)
                    )
                    best_pct = int(best_cnt * 100 / total) if total else 0
                    bar = _pct_bar(best_pct)
                    lang_parts = []
                    for lg, cnt in sorted(by_lang.items()):
                        pct = int(cnt * 100 / total) if total else 0
                        lang_parts.append(f"[{lg}] {pct}%")
                    value = f"{bar}  " + "  ".join(lang_parts) if lang_parts else f"{bar}"
                    fields.append(
                        DetailField(
                            f"g:comp:{prop_key}",
                            disp,
                            value,
                            editable=False,
                            meta={"type": "stat"},
                        )
                    )

            total_errors = sum(
                sum(1 for i in sa.issues if i.severity == "error") for sa in analysis.values()
            )
            total_warnings = sum(
                sum(1 for i in sa.issues if i.severity == "warning") for sa in analysis.values()
            )
            fields.append(_sep("Quality"))
            if total_errors == 0 and total_warnings == 0:
                fields.append(
                    DetailField(
                        "g:issues:ok", "✓ no issues", "", editable=False, meta={"type": "stat"}
                    )
                )
            else:
                if total_errors:
                    fields.append(
                        DetailField(
                            "g:errors",
                            "⊘ errors",
                            str(total_errors),
                            editable=False,
                            meta={"type": "stat"},
                        )
                    )
                if total_warnings:
                    fields.append(
                        DetailField(
                            "g:warnings",
                            "⚠ warnings",
                            str(total_warnings),
                            editable=False,
                            meta={"type": "stat"},
                        )
                    )
        else:
            fields.append(_sep("Completeness & Quality"))
            fields.append(
                DetailField(
                    "g:pending", "analysis", "loading…", editable=False, meta={"type": "stat"}
                )
            )

    fields.append(_sep("Graph"))
    fields.append(
        _add_action_field(
            "action:view_ontology_graph", "⊙ View graph in browser", "view_ontology_graph"
        )
    )
    return fields


# ──────────────────────────── file dashboard ─────────────────────────────────


def build_file_fields(
    taxonomy: Taxonomy,
    file_path: Path,
    analysis: dict[str, SchemeAnalysis] | None,
    lang: str,
) -> list[DetailField]:
    """Build DetailField list for a file-node detail panel.

    Shows per-file overview (schemes, total concepts), per-scheme stats
    aggregated from analysis, and an action to add a new concept scheme.
    """
    fields: list[DetailField] = []

    # ── 1. File info ──────────────────────────────────────────────────────────
    fields.append(_sep("File"))
    fields.append(
        DetailField("file:name", "filename", file_path.name, editable=False, meta={"type": "stat"})
    )
    fields.append(
        DetailField(
            "file:path",
            "path",
            str(file_path.parent),
            editable=False,
            meta={"type": "stat"},
        )
    )

    # ── 2. Overview ───────────────────────────────────────────────────────────
    n_schemes = len(taxonomy.schemes)
    total_concepts = len(taxonomy.concepts)
    n_owl = len(taxonomy.owl_classes)
    fields.append(_sep("Overview"))
    if n_schemes:
        fields.append(
            DetailField(
                "file:n_schemes",
                "concept schemes",
                str(n_schemes),
                editable=False,
                meta={"type": "stat"},
            )
        )
    if total_concepts:
        fields.append(
            DetailField(
                "file:total",
                "total concepts",
                str(total_concepts),
                editable=False,
                meta={"type": "stat"},
            )
        )
    if n_owl:
        fields.append(
            DetailField(
                "file:owl",
                "OWL classes",
                str(n_owl),
                editable=False,
                meta={"type": "stat"},
            )
        )

    # ── 2b. OWL Classes quality ───────────────────────────────────────────────
    if n_owl:
        owl_stats = compute_owl_analysis(taxonomy)
        fields.append(_sep("OWL Classes"))
        if owl_stats.promoted:
            fields.append(
                _stat("file:owl:promoted", "promoted (concept+class)", str(owl_stats.promoted))
            )
        if owl_stats.pure_classes:
            fields.append(_stat("file:owl:pure", "pure classes", str(owl_stats.pure_classes)))
        fields.append(_stat("file:owl:depth", "max depth", str(owl_stats.max_depth)))
        if owl_stats.missing_label:
            fields.append(
                _stat("file:owl:miss_lbl", "missing rdfs:label", str(owl_stats.missing_label))
            )
        if owl_stats.missing_comment:
            fields.append(
                _stat("file:owl:miss_cmt", "missing rdfs:comment", str(owl_stats.missing_comment))
            )

    # ── 3. Per-scheme stats ───────────────────────────────────────────────────
    for scheme_uri, scheme in taxonomy.schemes.items():
        title = scheme.title(lang) or scheme_uri
        fields.append(_sep(f"Scheme — {title}"))
        scheme_analysis = (analysis or {}).get(scheme_uri)
        if scheme_analysis:
            st = scheme_analysis.stats
            fields.append(
                DetailField(
                    f"file:s:{scheme_uri}:total",
                    "concepts",
                    str(st.total_concepts),
                    editable=False,
                    meta={"type": "stat"},
                )
            )
            fields.append(
                DetailField(
                    f"file:s:{scheme_uri}:top",
                    "top-level",
                    str(st.top_level_concepts),
                    editable=False,
                    meta={"type": "stat"},
                )
            )
            fields.append(
                DetailField(
                    f"file:s:{scheme_uri}:depth",
                    "max depth",
                    str(st.max_depth),
                    editable=False,
                    meta={"type": "stat"},
                )
            )
            fields.append(
                DetailField(
                    f"file:s:{scheme_uri}:langs",
                    "languages",
                    ", ".join(st.languages) if st.languages else "—",
                    editable=False,
                    meta={"type": "stat"},
                )
            )
            n_issues = len(scheme_analysis.issues)
            n_err = sum(1 for i in scheme_analysis.issues if i.severity == "error")
            if n_err:
                issue_str = f"{n_issues} issue{'s' if n_issues > 1 else ''}  ({n_err} error{'s' if n_err > 1 else ''})"
            elif n_issues:
                issue_str = f"{n_issues} warning{'s' if n_issues > 1 else ''}"
            else:
                issue_str = "✓ no issues"
            fields.append(
                DetailField(
                    f"file:s:{scheme_uri}:issues",
                    "issues",
                    issue_str,
                    editable=False,
                    meta={"type": "stat"},
                )
            )
        else:
            fields.append(
                DetailField(
                    f"file:s:{scheme_uri}:pending",
                    "analysis",
                    "pending…",
                    editable=False,
                    meta={"type": "stat"},
                )
            )

    # ── 4. Actions ────────────────────────────────────────────────────────────
    fields.append(_sep("Actions"))
    fields.append(
        DetailField(
            "action:add_scheme",
            "➕ Add concept scheme",
            "",
            editable=False,
            meta={"type": "action", "action": "add_scheme"},
        )
    )
    return fields
