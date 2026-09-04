"""Concept- and scheme-specific detail-panel sections, plus build_concept_detail / build_scheme_detail."""

from __future__ import annotations

from collections import deque
from typing import Final

from ...analysis_base import pct as _pct
from ...analysis_base import pct_bar as _pct_bar
from ...model import LabelType, Taxonomy
from ...taxonomy_analysis import ISSUE_DISPLAY_NAMES, compute_completions
from . import _fields, _global_, _mixed_tree, _tree

_LIT_LANGUAGES: Final = "languages"
_LIT_RELATION: Final = "relation"


def _concept_identity_fields(
    taxonomy: Taxonomy, uri: str, concept, lang: str
) -> list[_fields.DetailField]:
    """URI + type + topConceptOf/inScheme (topConceptOf is navigable → scheme detail)."""
    from ._rdf_class import _type_field

    fields = [
        _fields.DetailField("uri", "URI", uri, editable=True, meta={"type": "uri"}),
        _type_field(taxonomy, uri),
    ]
    if concept.top_concept_of:
        scheme = taxonomy.schemes.get(concept.top_concept_of)
        scheme_label = scheme.title(lang) if scheme else concept.top_concept_of
        fields.append(
            _fields.DetailField(
                "top_concept_of",
                "◈ scheme",
                scheme_label,
                editable=False,
                meta={"type": "top_concept_of", "uri": concept.top_concept_of, "nav": True},
            )
        )
    return fields


def _concept_hierarchy_fields(taxonomy: Taxonomy, concept, lang: str) -> list[_fields.DetailField]:
    """broader↑, narrower↓, related~ — all navigable."""
    fields = []
    for child_uri in concept.narrower:
        h = taxonomy.uri_to_handle(child_uri) or "?"
        child = taxonomy.concepts.get(child_uri)
        label_str = child.pref_label(lang) if child else child_uri
        fields.append(
            _fields.DetailField(
                f"narrower:{child_uri}",
                "↓ narrower",
                f"{label_str}  [{h}]",
                editable=False,
                meta={"type": _LIT_RELATION, "uri": child_uri, "nav": True},
            )
        )
    for p_uri in concept.broader:
        h = taxonomy.uri_to_handle(p_uri) or "?"
        parent = taxonomy.concepts.get(p_uri)
        label_str = parent.pref_label(lang) if parent else p_uri
        fields.append(
            _fields.DetailField(
                f"broader:{p_uri}",
                "↑ broader",
                f"{label_str}  [{h}]",
                editable=False,
                meta={"type": _LIT_RELATION, "uri": p_uri, "nav": True},
            )
        )
    for r_uri in concept.related:
        h = taxonomy.uri_to_handle(r_uri) or "?"
        rel = taxonomy.concepts.get(r_uri)
        label_str = rel.pref_label(lang) if rel else r_uri
        fields.append(
            _fields.DetailField(
                f"related:{r_uri}",
                "~ related",
                f"{label_str}  [{h}]",
                editable=False,
                meta={"type": _LIT_RELATION, "uri": r_uri, "nav": True},
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


def class_subtree_has_instances(taxonomy: Taxonomy, uri: str) -> bool:
    """True when any individual is typed to a class in *uri*'s subtree — i.e. the class's
    Quality & Coverage box (instance count + property fill) has data to report."""
    subtree = set(_subtree_class_uris(taxonomy, uri))
    return any(subtree & set(ind.types) for ind in taxonomy.owl_individuals.values())


def concept_subtree_has_tagged_individuals(taxonomy: Taxonomy, uri: str) -> bool:
    """True when any individual is tagged (``dct:subject``) to a concept in *uri*'s subtree
    — the concept-side notion of "has individuals" (see the clustering link)."""
    from ster.operations import DCT_SUBJECT  # noqa: PLC0415

    subtree = set(_subtree_concept_uris(taxonomy, uri))
    return any(
        pred == DCT_SUBJECT and val in subtree
        for ind in taxonomy.owl_individuals.values()
        for pred, val in ind.property_values
    )


def _property_fill_count(
    taxonomy: Taxonomy,
    domain_inds: list[str],
    p_uri: str,
    range_set: set[str] | None,
) -> int:
    """How many *domain_inds* have a value for property *p_uri* (within *range_set*, if given)."""
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
            if val_ind and _mixed_tree._effective_types(taxonomy, val_ind.types) & range_set:
                filled += 1
                break
    return filled


def _class_property_fill_field(
    taxonomy: Taxonomy,
    subtree_set: set[str],
    p_uri: str,
    prop,
    lang: str,
) -> _fields.DetailField | None:
    """Fill-rate stat for one property over a class subtree, or None if it doesn't apply."""
    if not prop.domains:
        return None
    domain_set = set(prop.domains)
    if not domain_set & subtree_set:
        return None
    domain_inds = [
        ind_uri
        for ind_uri, ind in taxonomy.owl_individuals.items()
        if _mixed_tree._effective_types(taxonomy, ind.types) & domain_set
    ]
    if not domain_inds:
        return None
    range_set: set[str] | None = set(prop.ranges) if prop.ranges else None
    filled = _property_fill_count(taxonomy, domain_inds, p_uri, range_set)
    fill_pct = _pct(filled, len(domain_inds))
    lbl = prop.label(lang) or prop.local_name
    return _fields._pct_stat(f"cls:q:fill:{p_uri}", lbl, fill_pct)


def _class_property_fill_fields(
    taxonomy: Taxonomy, subtree_set: set[str], lang: str
) -> list[_fields.DetailField]:
    fill_fields: list[_fields.DetailField] = []
    for p_uri, prop in sorted(taxonomy.owl_properties.items()):
        field = _class_property_fill_field(taxonomy, subtree_set, p_uri, prop, lang)
        if field is not None:
            fill_fields.append(field)
    return fill_fields


def _class_quality_fields(taxonomy: Taxonomy, uri: str, lang: str) -> list[_fields.DetailField]:
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

    fields: list[_fields.DetailField] = [_fields._sep("Subtree Quality")]
    if n_classes > 1:
        fields.append(_fields._stat("cls:q:n_classes", "classes in subtree", str(n_classes)))
    fields.append(_fields._pct_stat("cls:q:lbl", _tree._RDFS_LABEL, label_p))
    fields.append(_fields._pct_stat("cls:q:cmt", "rdfs:comment", comment_p))
    fields.append(_fields._stat("cls:q:inst:subtree", "instances (subtree)", str(n_subtree_inds)))

    fill_fields = _class_property_fill_fields(taxonomy, subtree_set, lang)
    if fill_fields:
        fields.append(_fields._sep("Property Fill"))
        fields.extend(fill_fields)

    return fields


def _concept_overview_fields(taxonomy: Taxonomy, uri: str, concept) -> list[_fields.DetailField]:
    """Overview stats for a concept's subtree — only call when concept.narrower is non-empty."""
    direct = len([u for u in concept.narrower if u in taxonomy.concepts])
    total = _tree._count_descendants(taxonomy, uri)
    # Collect languages present in prefLabels across the subtree
    langs: set[str] = set()
    for sub_uri in _subtree_concept_uris(taxonomy, uri):
        c = taxonomy.concepts.get(sub_uri)
        if c:
            for lbl in c.labels:
                if lbl.type == LabelType.PREF:
                    langs.add(lbl.lang)
    fields = [
        _fields._stat("stat:direct_narrower", "direct narrower", str(direct)),
        _fields._stat("stat:total_descendants", "total descendants", str(total)),
    ]
    if langs:
        fields.append(_fields._stat("stat:subtree_langs", _LIT_LANGUAGES, ", ".join(sorted(langs))))
    return fields


def _concept_completion_fields(taxonomy: Taxonomy, uri: str) -> list[_fields.DetailField]:
    """Per-property, per-language completion bars for a concept's subtree (including itself)."""
    uris = _subtree_concept_uris(taxonomy, uri)
    if not uris:
        return []
    completions = compute_completions(taxonomy, uris)
    fields: list[_fields.DetailField] = []
    for comp in completions:
        fields.append(_fields._sep(f"Completion — {comp.display_name}"))
        for lg, count in sorted(comp.by_language.items()):
            pct = int(count * 100 / comp.total) if comp.total else 0
            bar = _pct_bar(pct)
            fields.append(
                _fields.DetailField(
                    f"ccomp:{comp.property_key}:{lg}",
                    f"[{lg}]",
                    f"{count}/{comp.total}  {bar}  ({pct}%)",
                    editable=False,
                    meta={"type": "stat", "color": _fields._quality_color(pct)},
                )
            )
    return fields


def _concept_mappings_fields(taxonomy: Taxonomy, concept, lang: str) -> list[_fields.DetailField]:
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
                _fields.DetailField(
                    f"{attr}:{m_uri}",
                    display,
                    f"{label_str}  [{h}]",
                    editable=False,
                    meta={"type": "mapping", "uri": m_uri, "nav": bool(mapped), "attr": attr},
                )
            )
            fields.append(
                _fields.DetailField(
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
) -> list[_fields.DetailField]:
    """Actions section for a concept."""
    clangs = configured_langs or [lang]
    fields = []
    # Add-label/note actions, one per configured language that's still missing.
    pref_langs = {lbl.lang for lbl in concept.labels if lbl.type == LabelType.PREF}
    fields += _fields._lang_add_actions(
        clangs,
        "action:add_pref",
        "+ Add prefLabel [{lang}]",
        "add_pref_label",
        present=pref_langs,
        green=False,
    )
    # altLabels may repeat per language → offer one for every configured language.
    fields += _fields._lang_add_actions(
        clangs,
        "action:add_alt",
        "+ Add altLabel [{lang}]",
        "add_alt_label",
        green=False,
    )
    fields += _fields._lang_add_actions(
        clangs,
        "action:add_def",
        "+ Add definition [{lang}]",
        "add_def",
        present={d.lang for d in concept.definitions},
        green=False,
    )
    fields += _fields._lang_add_actions(
        clangs,
        "action:add_scope",
        "+ Add scopeNote [{lang}]",
        "add_scope_note",
        present={d.lang for d in concept.scope_notes},
        green=False,
    )
    # Structural actions
    fields.append(
        _fields._add_action_field("action:add_child", "+ Add narrower concept", "add_narrower")
    )
    fields.append(
        _fields._add_action_field(
            "action:link_broader", "↑ Link to broader concept", "link_broader"
        )
    )
    fields.append(
        _fields._add_action_field("action:add_related", "~ Add related concept", "add_related")
    )
    fields.append(_fields._add_action_field("action:move", "↷ Move under different parent", "move"))
    fields.append(_fields._add_action_field("action:delete", "⊘ Delete this concept", "delete"))
    # Cross-scheme mapping actions
    if show_mappings:
        fields.append(_fields._sep("Cross-scheme mappings"))
        for map_type, label in (
            ("exactMatch", "⟺ exactMatch  — same concept, different vocabulary"),
            ("closeMatch", "≈  closeMatch  — very similar meaning"),
            ("broadMatch", "↑  broadMatch  — target is broader"),
            ("narrowMatch", "↓  narrowMatch — target is narrower"),
            ("relatedMatch", "↔  relatedMatch — associative link"),
        ):
            fields.append(
                _fields._add_action_field(f"action:map_{map_type}", label, f"map:{map_type}")
            )
    return fields


def _scheme_settings_fields(
    scheme, _configured_langs: list[str] | None = None
) -> list[_fields.DetailField]:
    """URI and base URI for a scheme."""
    return [
        _fields.DetailField(
            "scheme_uri", "URI", scheme.uri, editable=False, meta={"type": "scheme_uri"}
        ),
        _fields.DetailField(
            "base_uri",
            "base URI",
            scheme.base_uri or "",
            editable=True,
            meta={"type": "scheme_base_uri"},
        ),
    ]


def _scheme_metadata_fields(scheme) -> list[_fields.DetailField]:
    return [
        _fields.DetailField(
            "creator", "creator", scheme.creator, editable=True, meta={"type": "scheme_creator"}
        ),
        _fields.DetailField(
            "created", "created", scheme.created, editable=True, meta={"type": "scheme_created"}
        ),
        _fields.DetailField(
            _LIT_LANGUAGES,
            "declared langs",
            ", ".join(scheme.languages),
            editable=True,
            meta={"type": "scheme_languages"},
        ),
    ]


def _scheme_top_concept_fields(taxonomy: Taxonomy, scheme, lang: str) -> list[_fields.DetailField]:
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
            _fields.DetailField(
                f"tc:{tc_uri}",
                "◈ top concept",
                f"{label}  [{h}]{suffix}",
                editable=False,
                meta={"type": _LIT_RELATION, "uri": tc_uri, "nav": True},
            )
        )
    return fields


def _scheme_stats_fields(scheme_analysis) -> list[_fields.DetailField]:
    if scheme_analysis is None:
        return [_fields._stat("stat:pending", "analysis", "pending…")]
    st = scheme_analysis.stats
    return [
        _fields._stat("stat:total", "total concepts", str(st.total_concepts)),
        _fields._stat("stat:top", "top-level", str(st.top_level_concepts)),
        _fields._stat("stat:depth_max", _tree._MAX_DEPTH, str(st.max_depth)),
        _fields._stat("stat:depth_avg", "avg depth", f"{st.avg_depth:.1f}"),
        _fields._stat(
            "stat:langs", _LIT_LANGUAGES, ", ".join(st.languages) if st.languages else "—"
        ),
    ]


def _scheme_completion_fields(scheme_analysis) -> list[_fields.DetailField]:
    if scheme_analysis is None or not scheme_analysis.completions:
        return []
    fields: list[_fields.DetailField] = []
    for comp in scheme_analysis.completions:
        fields.append(_fields._sep(f"Completion — {comp.display_name}"))
        fields.extend(_fields._coverage_fields(f"comp:{comp.property_key}", comp))
    return fields


def _scheme_issues_fields(scheme_analysis) -> list[_fields.DetailField]:
    if scheme_analysis is None:
        return []
    return _fields._issue_nav_fields(scheme_analysis.issues, ISSUE_DISPLAY_NAMES)


def _scheme_action_fields() -> list[_fields.DetailField]:
    return [
        _fields._add_action_field(
            "action:add_top_concept", "➕ Add top concept", "add_top_concept"
        ),
    ]


def _concept_labels_section(concept, clangs: list[str]) -> list[_fields.DetailField]:
    """prefLabel (essential) + altLabel rows, each with its inline '+ Add …' affordance."""
    fields = _fields._section_labels_grouped(
        concept.labels, "pref", "alt", "prefLabel", "pref", "alt"
    )
    pref_langs = {lbl.lang for lbl in concept.labels if lbl.type == LabelType.PREF}
    fields += _fields.essential_label_affordances("concept", pref_langs, clangs)
    fields += _fields._lang_add_actions(
        clangs, "action:add_alt", "+ Add altLabel [{lang}]", "add_alt_label"
    )
    return fields


def _concept_notes_section(concept, clangs: list[str]) -> list[_fields.DetailField]:
    """definition + scopeNote rows, each with its inline per-language add affordance."""
    fields = _fields._section_text_list(concept.definitions, "def", "definition", "def")
    fields += _fields._lang_add_actions(
        clangs,
        "action:add_def",
        "+ Add definition [{lang}]",
        "add_def",
        present={d.lang for d in concept.definitions},
    )
    fields += _fields._section_text_list(concept.scope_notes, "scope", "scopeNote", "scope_note")
    fields += _fields._lang_add_actions(
        clangs,
        "action:add_scope",
        "+ Add scopeNote [{lang}]",
        "add_scope_note",
        present={d.lang for d in concept.scope_notes},
    )
    return fields


def _concept_has_mappings(concept) -> bool:
    return bool(
        concept.exact_match
        or concept.close_match
        or concept.broad_match
        or concept.narrow_match
        or concept.related_match
    )


def build_concept_detail(
    taxonomy: Taxonomy,
    uri: str,
    lang: str,
    configured_langs: list[str] | None = None,
) -> list[_fields.DetailField]:
    """Unified concept detail (mirrors the class page): Identity → Labels → Notes →
    Hierarchy → Mappings → Overview. Structural edits and Delete live on the context
    menu; each section carries the inline '+ Add …' affordance for what it's missing."""
    concept = taxonomy.concepts.get(uri)
    if not concept:
        return []
    clangs = configured_langs or [lang]

    fields: list[_fields.DetailField] = [_fields._sep("Identity")]
    fields += _concept_identity_fields(taxonomy, uri, concept, lang)
    fields += [_fields._sep("Labels"), *_concept_labels_section(concept, clangs)]
    fields += [_fields._sep("Notes"), *_concept_notes_section(concept, clangs)]

    if concept.narrower or concept.broader or concept.related:
        fields += [_fields._sep("Hierarchy"), *_concept_hierarchy_fields(taxonomy, concept, lang)]
    if _concept_has_mappings(concept):
        fields += [_fields._sep("Mappings"), *_concept_mappings_fields(taxonomy, concept, lang)]
    if concept.narrower:  # Overview + per-property completion bars
        fields += [_fields._sep("Overview"), *_concept_overview_fields(taxonomy, uri, concept)]
        fields += _concept_completion_fields(taxonomy, uri)  # includes its own _fields._sep rows

    fields += _fields._schema_media_display_fields(concept, "c:")
    return fields


def _scheme_issues_summary_label(scheme_analysis) -> str:
    """'Issues — N errors, M warnings' style separator label, or plain 'Issues'."""
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
    return "Issues — " + ", ".join(summary_parts) if summary_parts else "Issues"


def _scheme_issues_section(scheme_analysis) -> list[_fields.DetailField]:
    if not scheme_analysis:
        return []
    sep_label = _scheme_issues_summary_label(scheme_analysis)
    return [_fields._sep(sep_label), *_scheme_issues_fields(scheme_analysis)]


def build_scheme_detail(
    taxonomy: Taxonomy,
    scheme_uri: str,
    lang: str,
    analysis: dict | None = None,
    configured_langs: list[str] | None = None,
) -> list[_fields.DetailField]:
    """Unified scheme detail: Settings → Labels → Notes → Metadata → Top Concepts → Statistics → Completion → Issues → Actions."""
    scheme = taxonomy.schemes.get(scheme_uri)
    if not scheme:
        return []
    scheme_analysis = (analysis or {}).get(scheme_uri)
    fields: list[_fields.DetailField] = []

    # display_lang first (no separator before it — tests rely on fields[0])
    fields.append(_global_._display_lang_field(lang))

    # ── Settings ─────────────────────────────────────────────────────────────
    fields.append(_fields._sep("Settings"))
    fields.extend(_scheme_settings_fields(scheme, configured_langs))

    # ── Labels ───────────────────────────────────────────────────────────────
    fields.append(_fields._sep("Labels"))
    fields.extend(_fields._section_pref_labels(scheme.labels, "title", "title", "scheme_title"))
    fields.extend(_fields._section_alt_labels(scheme.labels, "alt_title", "scheme_alt_title"))

    # ── Notes (descriptions) ─────────────────────────────────────────────────
    if scheme.descriptions:
        fields.append(_fields._sep("Notes"))
        fields.extend(
            _fields._section_text_list(scheme.descriptions, "desc", "description", "scheme_desc")
        )

    # ── Metadata ─────────────────────────────────────────────────────────────
    fields.append(_fields._sep("Metadata"))
    fields.extend(_scheme_metadata_fields(scheme))

    # ── Top Concepts (navigable) ──────────────────────────────────────────────
    top_fields = _scheme_top_concept_fields(taxonomy, scheme, lang)
    if top_fields:
        fields.append(_fields._sep("Top Concepts"))
        fields.extend(top_fields)

    # ── Statistics ────────────────────────────────────────────────────────────
    fields.append(_fields._sep("Statistics"))
    fields.extend(_scheme_stats_fields(scheme_analysis))

    # ── Completion ────────────────────────────────────────────────────────────
    comp_fields = _scheme_completion_fields(scheme_analysis)
    if comp_fields:
        fields.extend(comp_fields)

    # ── Issues ────────────────────────────────────────────────────────────────
    fields.extend(_scheme_issues_section(scheme_analysis))

    # ── Actions ───────────────────────────────────────────────────────────────
    fields.append(_fields._sep("Actions"))
    fields.extend(_scheme_action_fields())

    return fields
