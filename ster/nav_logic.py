"""Pure taxonomy tree / detail logic — no curses dependency."""
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path

from .model import LabelType, Taxonomy
from .workspace import TaxonomyWorkspace

# ──────────────────────────── tree helpers ────────────────────────────────────

_ACTION_ADD_SCHEME = "__ster:add_scheme__"  # sentinel URI for action rows
_FILE_URI_PREFIX = "__ster:file::"  # prefix for file-node sentinel URIs


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


def build_detail_fields(
    taxonomy: Taxonomy,
    uri: str,
    lang: str,
    show_mappings: bool = False,
) -> list[DetailField]:
    concept = taxonomy.concepts.get(uri)
    if not concept:
        return []

    fields: list[DetailField] = []

    # ── Identity ───────────────────────────────────────────────────────────────
    fields.append(_sep("Identity"))
    fields.append(DetailField("uri", "URI", uri, editable=False, meta={"type": "uri"}))

    if concept.top_concept_of:
        scheme = taxonomy.schemes.get(concept.top_concept_of)
        scheme_label = scheme.title(lang) if scheme else concept.top_concept_of
        fields.append(
            DetailField(
                "top_concept_of",
                "◈ scheme",
                scheme_label,
                editable=False,
                meta={"type": "top_concept_of", "uri": concept.top_concept_of},
            )
        )

    # ── Labels ─────────────────────────────────────────────────────────────────
    fields.append(_sep("Labels"))
    pref: dict[str, str] = {
        lbl.lang: lbl.value for lbl in concept.labels if lbl.type == LabelType.PREF
    }
    for lg, val in sorted(pref.items()):
        fields.append(
            DetailField(
                f"pref:{lg}",
                f"prefLabel [{lg}]",
                val,
                editable=True,
                meta={"type": "pref", "lang": lg},
            )
        )

    alt: dict[str, list[str]] = {}
    for lbl in concept.labels:
        if lbl.type == LabelType.ALT:
            alt.setdefault(lbl.lang, []).append(lbl.value)
    for lg, vals in sorted(alt.items()):
        for idx, val in enumerate(vals):
            fields.append(
                DetailField(
                    f"alt:{lg}:{idx}",
                    f"altLabel [{lg}]",
                    val,
                    editable=True,
                    meta={"type": "alt", "lang": lg, "idx": idx},
                )
            )

    # ── Definition ─────────────────────────────────────────────────────────────
    defs: dict[str, str] = {d.lang: d.value for d in concept.definitions}
    if defs:
        fields.append(_sep("Definition"))
        for lg, val in sorted(defs.items()):
            fields.append(
                DetailField(
                    f"def:{lg}",
                    f"definition [{lg}]",
                    val,
                    editable=True,
                    meta={"type": "def", "lang": lg},
                )
            )

    # ── Hierarchy ──────────────────────────────────────────────────────────────
    has_hierarchy = bool(concept.narrower or concept.broader or concept.related)
    if has_hierarchy:
        fields.append(_sep("Hierarchy"))

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

    # ── Existing cross-scheme mapping links ────────────────────────────────────
    _MAP_DISPLAY = (
        ("exact_match", "⟺ exactMatch"),
        ("close_match", "≈  closeMatch"),
        ("broad_match", "↑  broadMatch"),
        ("narrow_match", "↓  narrowMatch"),
        ("related_match", "↔  relatedMatch"),
    )
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

    # ── Structural actions ─────────────────────────────────────────────────────
    fields.append(_sep("Actions"))
    fields.append(
        DetailField(
            "action:add_child",
            "+ Add narrower concept",
            "",
            editable=False,
            meta={"type": "action", "action": "add_narrower"},
        )
    )
    fields.append(
        DetailField(
            "action:link_broader",
            "↑ Link to broader concept",
            "",
            editable=False,
            meta={"type": "action", "action": "link_broader"},
        )
    )
    fields.append(
        DetailField(
            "action:move",
            "↷ Move under different parent",
            "",
            editable=False,
            meta={"type": "action", "action": "move"},
        )
    )
    fields.append(
        DetailField(
            "action:delete",
            "⊘ Delete this concept",
            "",
            editable=False,
            meta={"type": "action", "action": "delete"},
        )
    )

    # ── Cross-scheme mapping actions (only when multiple schemes loaded) ────────
    if show_mappings:
        fields.append(_sep("Cross-scheme mappings"))
        for map_type, label in (
            ("exactMatch", "⟺ exactMatch  — same concept, different vocabulary"),
            ("closeMatch", "≈  closeMatch  — very similar meaning"),
            ("broadMatch", "↑  broadMatch  — target is broader"),
            ("narrowMatch", "↓  narrowMatch — target is narrower"),
            ("relatedMatch", "↔  relatedMatch — associative link"),
        ):
            fields.append(
                DetailField(
                    f"action:map_{map_type}",
                    label,
                    "",
                    editable=False,
                    meta={"type": "action", "action": f"map:{map_type}"},
                )
            )

    return fields


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


def build_scheme_fields(
    taxonomy: Taxonomy,
    lang: str,
    scheme_uri: str | None = None,
) -> list[DetailField]:
    """Build DetailField list for the ConceptScheme settings panel.

    If *scheme_uri* is given, use that scheme; otherwise fall back to the
    primary (first) scheme.
    """
    if scheme_uri is not None:
        scheme = taxonomy.schemes.get(scheme_uri)
    else:
        scheme = taxonomy.primary_scheme()
    if not scheme:
        return []

    fields: list[DetailField] = []

    # Display language first — action field: Enter opens the language picker
    fields.append(
        DetailField(
            "display_lang",
            "display language",
            lang,
            editable=False,
            meta={"type": "action", "action": "pick_lang"},
        )
    )

    fields.append(
        DetailField("scheme_uri", "URI", scheme.uri, editable=False, meta={"type": "scheme_uri"})
    )
    fields.append(
        DetailField(
            "base_uri",
            "base URI",
            scheme.base_uri or "",
            editable=True,
            meta={"type": "scheme_base_uri"},
        )
    )

    # Titles per language
    pref_titles: dict[str, str] = {
        lbl.lang: lbl.value for lbl in scheme.labels if lbl.type == LabelType.PREF
    }
    for lg, val in sorted(pref_titles.items()):
        fields.append(
            DetailField(
                f"title:{lg}",
                f"title [{lg}]",
                val,
                editable=True,
                meta={"type": "scheme_title", "lang": lg},
            )
        )

    # Descriptions per language
    for desc in sorted(scheme.descriptions, key=lambda d: d.lang):
        fields.append(
            DetailField(
                f"desc:{desc.lang}",
                f"description [{desc.lang}]",
                desc.value,
                editable=True,
                meta={"type": "scheme_desc", "lang": desc.lang},
            )
        )

    fields.append(
        DetailField(
            "creator", "creator", scheme.creator, editable=True, meta={"type": "scheme_creator"}
        )
    )
    fields.append(
        DetailField(
            "created", "created", scheme.created, editable=True, meta={"type": "scheme_created"}
        )
    )
    fields.append(
        DetailField(
            "languages",
            "declared langs",
            ", ".join(scheme.languages),
            editable=True,
            meta={"type": "scheme_languages"},
        )
    )

    # Action: add a top concept to this scheme
    fields.append(
        DetailField(
            "action:add_top_concept",
            "➕ Add top concept",
            "",
            editable=False,
            meta={"type": "action", "action": "add_top_concept"},
        )
    )

    # Action: add a new scheme
    fields.append(
        DetailField(
            "action:add_scheme",
            "➕ Add new scheme",
            "",
            editable=False,
            meta={"type": "action", "action": "add_scheme"},
        )
    )

    return fields
