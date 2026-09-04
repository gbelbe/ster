"""Tree flattening: SKOS taxonomy trees, the mixed SKOS+OWL tree, and the pure OWL ontology tree."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...model import Taxonomy
from ...workspace import TaxonomyWorkspace

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

_MARKDOWN_EMPHASIS_RE = r"\*{1,2}([^*]+)\*{1,2}"

_RDFS_LABEL = "rdfs:label"

_MAX_DEPTH = "max depth"


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
    from ...model import OWLProperty as _OWLProperty

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


def _visit_skos_concept(
    taxonomy: Taxonomy,
    folded: set[str],
    file_path: Path | None,
    visited: set[str],
    result: list[TreeLine],
    uri: str,
    depth: int,
    prefix: str,
    is_last: bool,
) -> None:
    """Recursively append *uri* and its SKOS narrower concepts to *result*."""
    if uri in visited:
        return
    visited.add(uri)
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
            _visit_skos_concept(
                taxonomy,
                folded,
                file_path,
                visited,
                result,
                child,
                depth + 1,
                prefix + ext,
                i == len(children) - 1,
            )


def _owl_class_children(taxonomy: Taxonomy) -> dict[str, list[str]]:
    """Class → [child class/individual URI] adjacency for the OWL tree."""
    cls_children: dict[str, list[str]] = {u: [] for u in taxonomy.owl_classes}
    for uri, cls in taxonomy.owl_classes.items():
        for parent in cls.sub_class_of:
            if parent in cls_children:
                cls_children[parent].append(uri)
    # Nest individuals under their first known parent class
    for ind_uri, ind in taxonomy.owl_individuals.items():
        placed = False
        for t in ind.types:
            if t in cls_children:
                cls_children[t].append(ind_uri)
                placed = True
                break
        if not placed:
            # no known class parent → add as pseudo-root so it still renders
            cls_children[ind_uri] = []
    return cls_children


def _owl_class_roots(taxonomy: Taxonomy) -> list[str]:
    """Class/individual URIs never nested under a parent (tree roots)."""
    child_uris = {
        uri
        for uri, cls in taxonomy.owl_classes.items()
        for p in cls.sub_class_of
        if p in taxonomy.owl_classes
    }
    # individuals nested under a class are also child URIs
    ind_child_uris = {
        ind_uri
        for ind in taxonomy.owl_individuals.values()
        for t in ind.types
        if t in taxonomy.owl_classes
        for ind_uri in [ind.uri]
    }
    root_classes = [u for u in taxonomy.owl_classes if u not in child_uris]
    root_inds = [u for u in taxonomy.owl_individuals if u not in ind_child_uris]
    return root_classes + root_inds


def _visit_owl_class(
    taxonomy: Taxonomy,
    cls_children: dict[str, list[str]],
    folded: set[str],
    file_path: Path | None,
    scheme_depth: int,
    scheme_prefix: str,
    visited: set[str],
    result: list[TreeLine],
    uri: str,
    depth: int,
    prefix: str,
    is_last: bool,
) -> None:
    """Recursively append *uri* and its OWL class/individual children to *result*."""
    if uri in visited:
        return
    visited.add(uri)
    connector = "└── " if is_last else "├── "
    children = cls_children.get(uri, [])
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
            _visit_owl_class(
                taxonomy,
                cls_children,
                folded,
                file_path,
                scheme_depth,
                scheme_prefix,
                visited,
                result,
                child,
                depth + 1,
                prefix + ext,
                i == len(children) - 1,
            )


def _append_owl_class_tree(
    taxonomy: Taxonomy,
    folded: set[str],
    file_path: Path | None,
    scheme_depth: int,
    scheme_prefix: str,
    visited: set[str],
    result: list[TreeLine],
) -> None:
    """Append the OWL class/individual hierarchy, rooted at its top-level classes."""
    if not (taxonomy.owl_classes or taxonomy.owl_individuals):
        return
    cls_children = _owl_class_children(taxonomy)
    all_roots = _owl_class_roots(taxonomy)
    for i, uri in enumerate(all_roots):
        _visit_owl_class(
            taxonomy,
            cls_children,
            folded,
            file_path,
            scheme_depth,
            scheme_prefix,
            visited,
            result,
            uri,
            0,
            "",
            i == len(all_roots) - 1,
        )


def _append_unplaced_owl_individuals(
    taxonomy: Taxonomy,
    scheme_depth: int,
    scheme_prefix: str,
    file_path: Path | None,
    visited: set[str],
    result: list[TreeLine],
) -> None:
    """Fallback: individuals not nested under any class (should be empty after the tree pass)."""
    for uri in taxonomy.owl_individuals:
        if uri in visited:
            continue
        visited.add(uri)
        result.append(
            TreeLine(
                uri=uri,
                depth=scheme_depth,
                prefix=scheme_prefix,
                node_type="individual",
                file_path=file_path,
            )
        )


def _append_owl_properties(
    taxonomy: Taxonomy,
    scheme_depth: int,
    scheme_prefix: str,
    file_path: Path | None,
    visited: set[str],
    result: list[TreeLine],
) -> None:
    for uri in taxonomy.owl_properties:
        if uri in visited:
            continue
        visited.add(uri)
        result.append(
            TreeLine(
                uri=uri,
                depth=scheme_depth,
                prefix=scheme_prefix,
                node_type="property",
                file_path=file_path,
            )
        )


def _append_skos_schemes(
    taxonomy: Taxonomy,
    folded: set[str],
    file_path: Path | None,
    scheme_depth: int,
    scheme_prefix: str,
    concept_base_depth: int,
    visited: set[str],
    result: list[TreeLine],
) -> None:
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
                _visit_skos_concept(
                    taxonomy,
                    folded,
                    file_path,
                    visited,
                    result,
                    uri,
                    concept_base_depth,
                    scheme_prefix,
                    i == len(existing_tops) - 1,
                )


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
    visited: set[str] = set()

    if include_owl:
        _append_owl_class_tree(
            taxonomy, folded, file_path, scheme_depth, scheme_prefix, visited, result
        )
        _append_unplaced_owl_individuals(
            taxonomy, scheme_depth, scheme_prefix, file_path, visited, result
        )
        _append_owl_properties(taxonomy, scheme_depth, scheme_prefix, file_path, visited, result)

    _append_skos_schemes(
        taxonomy,
        folded,
        file_path,
        scheme_depth,
        scheme_prefix,
        concept_base_depth,
        visited,
        result,
    )

    return result


def _count_hidden_in_file(taxonomy: Taxonomy) -> int:
    """Row count hidden under a folded file node: every scheme plus its concept subtrees."""
    hidden = 0
    for scheme in taxonomy.schemes.values():
        hidden += 1
        for tc in scheme.top_concepts:
            if tc in taxonomy.concepts:
                hidden += 1 + _count_descendants(taxonomy, tc)
    return hidden


def _append_workspace_file(
    file_path: Path,
    taxonomy: Taxonomy,
    folded: set[str],
    result: list[TreeLine],
) -> None:
    """Append one workspace file's node, and its taxonomy subtree when unfolded."""
    file_uri = _file_sentinel(file_path)
    file_folded = file_uri in folded
    hidden_in_file = _count_hidden_in_file(taxonomy) if file_folded else 0

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


def _flatten_workspace(
    workspace: TaxonomyWorkspace,
    folded: set[str] | None = None,
) -> list[TreeLine]:
    """Flatten a multi-file workspace: file nodes > scheme nodes > concepts."""
    if folded is None:
        folded = set()
    result: list[TreeLine] = []

    for file_path, taxonomy in workspace.taxonomies.items():
        _append_workspace_file(file_path, taxonomy, folded, result)

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
