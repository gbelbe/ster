"""Pure taxonomy tree / detail logic — no curses dependency."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path

from .model import LabelType, Taxonomy
from .taxonomy_analysis import ISSUE_DISPLAY_NAMES, SchemeAnalysis, compute_completions
from .workspace import TaxonomyWorkspace

# ──────────────────────────── tree helpers ────────────────────────────────────

_ACTION_ADD_SCHEME = "__ster:add_scheme__"  # sentinel URI for action rows
_FILE_URI_PREFIX = "__ster:file::"  # prefix for file-node sentinel URIs
_GLOBAL_URI = "__ster:global__"  # sentinel URI for the global overview panel


def _file_sentinel(path: Path) -> str:
    return f"{_FILE_URI_PREFIX}{path}"


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
) -> list[TreeLine]:
    """Flatten a single Taxonomy into TreeLine rows.

    *scheme_depth* / *scheme_prefix* / *concept_base_depth* let callers
    embed the output inside a parent file node (multi-file workspace).
    """
    if folded is None:
        folded = set()
    result: list[TreeLine] = []

    def visit(uri: str, depth: int, prefix: str, is_last: bool) -> None:
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
            )
        )
        if not is_fold:
            ext = "    " if is_last else "│   "
            for i, child in enumerate(children):
                visit(child, depth + 1, prefix + ext, i == len(children) - 1)

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


def _pct_bar(pct: int, width: int = 8) -> str:
    """Return a compact block progress-bar string, e.g. '████░░░░'."""
    filled = round(pct * width / 100)
    return "█" * filled + "░" * (width - filled)


# ──────────────────────────── shared section primitives ──────────────────────


def _stat(key: str, label: str, value: str) -> DetailField:
    """Helper for read-only stat rows."""
    return DetailField(key, label, value, editable=False, meta={"type": "stat"})


def _add_action_field(key: str, label: str, action: str, **extra_meta) -> DetailField:
    """Helper for action rows."""
    return DetailField(key, label, "", editable=False, meta={"type": "action", "action": action, **extra_meta})


def _section_pref_labels(labels: list, id_prefix: str, display_name: str, meta_type: str) -> list[DetailField]:
    """Shared: emit prefLabel rows sorted by language (no alt labels)."""
    pref = {lbl.lang: lbl.value for lbl in labels if lbl.type == LabelType.PREF}
    return [
        DetailField(f"{id_prefix}:{lg}", f"{display_name} [{lg}]", val, editable=True, meta={"type": meta_type, "lang": lg})
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
            fields.append(DetailField(f"{id_prefix}:{lg}:{idx}", f"altLabel [{lg}]", val, editable=True, meta={"type": meta_type, "lang": lg, "idx": idx}))
    return fields


def _section_labels_grouped(labels: list, pref_prefix: str, alt_prefix: str,
                             pref_display: str, pref_meta: str, alt_meta: str) -> list[DetailField]:
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
            fields.append(DetailField(
                f"{pref_prefix}:{lg}", f"{pref_display} [{lg}]", pref[lg],
                editable=True, meta={"type": pref_meta, "lang": lg},
            ))
        for idx, val in enumerate(alt.get(lg, [])):
            fields.append(DetailField(
                f"{alt_prefix}:{lg}:{idx}", f"  altLabel [{lg}]", val,
                editable=True, meta={"type": alt_meta, "lang": lg, "idx": idx},
            ))
    return fields


def _section_text_list(items: list, id_prefix: str, display_name: str, meta_type: str) -> list[DetailField]:
    """Shared: emit rows for list[Definition]-typed properties (definitions, descriptions, scope_notes)."""
    return [
        DetailField(f"{id_prefix}:{item.lang}", f"{display_name} [{item.lang}]", item.value, editable=True, meta={"type": meta_type, "lang": item.lang})
        for item in sorted(items, key=lambda d: d.lang)
    ]


# ──────────────────────────── concept-specific section helpers ────────────────


def _concept_identity_fields(taxonomy: Taxonomy, uri: str, concept, lang: str) -> list[DetailField]:
    """URI + topConceptOf/inScheme (topConceptOf is navigable → scheme detail)."""
    fields = [DetailField("uri", "URI", uri, editable=False, meta={"type": "uri"})]
    if concept.top_concept_of:
        scheme = taxonomy.schemes.get(concept.top_concept_of)
        scheme_label = scheme.title(lang) if scheme else concept.top_concept_of
        fields.append(DetailField("top_concept_of", "◈ scheme", scheme_label, editable=False,
            meta={"type": "top_concept_of", "uri": concept.top_concept_of, "nav": True}))
    return fields


def _concept_hierarchy_fields(taxonomy: Taxonomy, concept, lang: str) -> list[DetailField]:
    """broader↑, narrower↓, related~ — all navigable."""
    fields = []
    for child_uri in concept.narrower:
        h = taxonomy.uri_to_handle(child_uri) or "?"
        child = taxonomy.concepts.get(child_uri)
        label_str = child.pref_label(lang) if child else child_uri
        fields.append(DetailField(f"narrower:{child_uri}", "↓ narrower", f"{label_str}  [{h}]", editable=False,
            meta={"type": "relation", "uri": child_uri, "nav": True}))
    for p_uri in concept.broader:
        h = taxonomy.uri_to_handle(p_uri) or "?"
        parent = taxonomy.concepts.get(p_uri)
        label_str = parent.pref_label(lang) if parent else p_uri
        fields.append(DetailField(f"broader:{p_uri}", "↑ broader", f"{label_str}  [{h}]", editable=False,
            meta={"type": "relation", "uri": p_uri, "nav": True}))
    for r_uri in concept.related:
        h = taxonomy.uri_to_handle(r_uri) or "?"
        rel = taxonomy.concepts.get(r_uri)
        label_str = rel.pref_label(lang) if rel else r_uri
        fields.append(DetailField(f"related:{r_uri}", "~ related", f"{label_str}  [{h}]", editable=False,
            meta={"type": "relation", "uri": r_uri, "nav": True}))
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
            fields.append(DetailField(
                f"ccomp:{comp.property_key}:{lg}",
                f"[{lg}]",
                f"{count}/{comp.total}  {bar}  ({pct}%)",
                editable=False,
                meta={"type": "stat"},
            ))
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
            fields.append(DetailField(f"{attr}:{m_uri}", display, f"{label_str}  [{h}]", editable=False,
                meta={"type": "mapping", "uri": m_uri, "nav": bool(mapped), "attr": attr}))
            fields.append(DetailField(f"rm_map:{attr}:{m_uri}", "   ✗ Remove link", "", editable=False,
                meta={"type": "mapping_remove", "uri": m_uri, "attr": attr}))
    return fields


def _concept_action_fields(lang: str, concept, show_mappings: bool) -> list[DetailField]:
    """Actions section for a concept."""
    fields = []
    # Add-label/note actions for current lang
    pref_langs = {lbl.lang for lbl in concept.labels if lbl.type == LabelType.PREF}
    def_langs = {d.lang for d in concept.definitions}
    scope_langs = {d.lang for d in concept.scope_notes}
    if lang not in pref_langs:
        fields.append(_add_action_field(f"action:add_pref:{lang}", f"+ Add prefLabel [{lang}]", "add_pref_label", lang=lang))
    fields.append(_add_action_field(f"action:add_alt:{lang}", f"+ Add altLabel [{lang}]", "add_alt_label", lang=lang))
    if lang not in def_langs:
        fields.append(_add_action_field(f"action:add_def:{lang}", f"+ Add definition [{lang}]", "add_def", lang=lang))
    if lang not in scope_langs:
        fields.append(_add_action_field(f"action:add_scope:{lang}", f"+ Add scopeNote [{lang}]", "add_scope_note", lang=lang))
    # Structural actions
    fields.append(_add_action_field("action:add_child", "+ Add narrower concept", "add_narrower"))
    fields.append(_add_action_field("action:link_broader", "↑ Link to broader concept", "link_broader"))
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
        DetailField("base_uri", "base URI", scheme.base_uri or "", editable=True, meta={"type": "scheme_base_uri"}),
    ]


def _scheme_metadata_fields(scheme) -> list[DetailField]:
    return [
        DetailField("creator", "creator", scheme.creator, editable=True, meta={"type": "scheme_creator"}),
        DetailField("created", "created", scheme.created, editable=True, meta={"type": "scheme_created"}),
        DetailField("languages", "declared langs", ", ".join(scheme.languages), editable=True, meta={"type": "scheme_languages"}),
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
        fields.append(DetailField(f"tc:{tc_uri}", "◈ top concept", f"{label}  [{h}]{suffix}", editable=False,
            meta={"type": "relation", "uri": tc_uri, "nav": True}))
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
    fields = []
    for comp in scheme_analysis.completions:
        fields.append(_sep(f"Completion — {comp.display_name}"))
        for lg, count in sorted(comp.by_language.items()):
            pct = int(count * 100 / comp.total) if comp.total else 0
            bar = _pct_bar(pct)
            fields.append(DetailField(f"comp:{comp.property_key}:{lg}", f"[{lg}]", f"{count}/{comp.total}  {bar}  ({pct}%)", editable=False, meta={"type": "stat"}))
    return fields


def _scheme_issues_fields(scheme_analysis) -> list[DetailField]:
    if scheme_analysis is None:
        return []
    issues = scheme_analysis.issues
    if not issues:
        return [DetailField("issues:ok", "✓ no issues", "", editable=False, meta={"type": "stat"})]
    fields = []
    for idx, issue in enumerate(issues):
        icon = _SEVERITY_ICONS.get(issue.severity, "·")
        name = ISSUE_DISPLAY_NAMES.get(issue.issue_key, issue.issue_key)
        meta: dict = {"type": "issue_nav", "severity": issue.severity}
        if issue.concept_uri:
            meta["uri"] = issue.concept_uri
        fields.append(DetailField(f"issue:{idx}", f"{icon} {name}", issue.message, editable=False, meta=meta))
        if issue.extra.get("attr") and issue.extra.get("target_uri") and issue.concept_uri:
            target_uri = issue.extra["target_uri"]
            fields.append(DetailField(f"repair:{idx}", "  ↳ remove link", target_uri, editable=False,
                meta={"type": "repair_mapping", "source_uri": issue.concept_uri, "attr": issue.extra["attr"], "target_uri": target_uri}))
    return fields


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
    fields.extend(_section_labels_grouped(
        concept.labels, "pref", "alt", "prefLabel", "pref", "alt"
    ))

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
    has_mappings = bool(concept.exact_match or concept.close_match or concept.broad_match or concept.narrow_match or concept.related_match)
    if has_mappings:
        fields.append(_sep("Mappings"))
        fields.extend(_concept_mappings_fields(taxonomy, concept, lang))

    # ── Overview + Completion (only if has narrowers) ───────────────────────
    if concept.narrower:
        fields.append(_sep("Overview"))
        fields.extend(_concept_overview_fields(taxonomy, uri, concept))
        fields.extend(_concept_completion_fields(taxonomy, uri))  # includes its own _sep rows

    # ── Actions ──────────────────────────────────────────────────────────────
    fields.append(_sep("Actions"))
    fields.extend(_concept_action_fields(lang, concept, show_mappings))

    return fields


def build_scheme_detail(
    taxonomy: Taxonomy,
    scheme_uri: str,
    lang: str,
    analysis: dict | None = None,
) -> list[DetailField]:
    """Unified scheme detail: Settings → Labels → Notes → Metadata → Top Concepts → Statistics → Completion → Issues → Actions."""
    scheme = taxonomy.schemes.get(scheme_uri)
    if not scheme:
        return []
    scheme_analysis = (analysis or {}).get(scheme_uri)
    fields: list[DetailField] = []

    # display_lang first (no separator before it — tests rely on fields[0])
    fields.append(DetailField("display_lang", "display language", lang, editable=False, meta={"type": "action", "action": "pick_lang"}))

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
        if n_err: summary_parts.append(f"{n_err} error{'s' if n_err > 1 else ''}")
        if n_warn: summary_parts.append(f"{n_warn} warning{'s' if n_warn > 1 else ''}")
        if n_info: summary_parts.append(f"{n_info} info")
        sep_label = "Issues — " + ", ".join(summary_parts) if summary_parts else "Issues"
        fields.append(_sep(sep_label))
        fields.extend(_scheme_issues_fields(scheme_analysis))

    # ── Actions ───────────────────────────────────────────────────────────────
    fields.append(_sep("Actions"))
    fields.extend(_scheme_action_fields())

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


def build_global_fields(
    workspace: TaxonomyWorkspace,
    analysis: dict[str, SchemeAnalysis] | None,
    lang: str,
) -> list[DetailField]:
    """Build DetailField list for the global overview panel.

    Sections: Setup (language), Shortcuts, Overview stats, Completeness, Quality.
    """
    from .taxonomy_analysis import PropertyCompletion  # local to avoid circular

    fields: list[DetailField] = []

    # ── 1. Setup ──────────────────────────────────────────────────────────────
    fields.append(_sep("Setup"))
    fields.append(
        DetailField(
            "display_lang",
            "display language",
            lang,
            editable=False,
            meta={"type": "action", "action": "pick_lang"},
        )
    )

    # ── 2. Keyboard shortcuts ─────────────────────────────────────────────────
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
    fields.append(
        DetailField(
            "g:schemes", "concept schemes", str(n_schemes), editable=False, meta={"type": "stat"}
        )
    )
    fields.append(
        DetailField(
            "g:concepts", "total concepts", str(n_concepts), editable=False, meta={"type": "stat"}
        )
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

    # ── 4. Completeness (aggregated across all schemes) ───────────────────────
    if analysis:
        # Collect all analyses, aggregate completions by property_key
        agg: dict[str, tuple[str, int, dict[str, int]]] = {}  # key → (display, total, by_lang)
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
                # Best completion across languages (highest %)
                best_lang, best_cnt = max(by_lang.items(), key=lambda kv: kv[1]) if by_lang else ("—", 0)
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

        # ── 5. Quality ────────────────────────────────────────────────────────
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
    fields.append(_sep("Overview"))
    fields.append(
        DetailField(
            "file:n_schemes",
            "concept schemes",
            str(n_schemes),
            editable=False,
            meta={"type": "stat"},
        )
    )
    fields.append(
        DetailField(
            "file:total",
            "total concepts",
            str(total_concepts),
            editable=False,
            meta={"type": "stat"},
        )
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
