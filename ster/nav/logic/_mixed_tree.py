"""Mixed SKOS+OWL combined tree building helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from ...model import Taxonomy
from ...workspace import TaxonomyWorkspace
from . import _tree

_LIT_INDIVIDUAL: Final = "individual"


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


def _class_hierarchy(
    taxonomy: Taxonomy, allowed: set[str] | None = None
) -> tuple[dict[str, list[str]], list[str]]:
    class_uris = allowed if allowed is not None else set(taxonomy.owl_classes)
    children_of: dict[str, list[str]] = {uri: [] for uri in class_uris}
    roots: list[str] = []
    for uri in class_uris:
        parents = [
            parent for parent in taxonomy.owl_classes[uri].sub_class_of if parent in class_uris
        ]
        if parents:
            for parent in parents:
                children_of[parent].append(uri)
        else:
            roots.append(uri)
    roots.sort()
    return children_of, roots


def _class_tree_children(
    taxonomy: Taxonomy,
    children_of: dict[str, list[str]],
    folded: set[str],
    file_path: Path | None,
    individuals_of: dict[str, list[str]],
    visited: set[str],
    depth: int,
    prefix: str,
    children: list[str],
    individuals: list[str],
) -> list[_tree.TreeLine]:
    rows: list[_tree.TreeLine] = []
    extension = prefix
    for index, child in enumerate(children):
        child_is_last = index == len(children) - 1 and not individuals
        rows.extend(
            _class_tree_branch(
                taxonomy,
                children_of,
                folded,
                file_path,
                individuals_of,
                visited,
                child,
                depth + 1,
                extension,
                child_is_last,
            )
        )
    for index, individual_uri in enumerate(individuals):
        individual_connector = "└── " if index == len(individuals) - 1 else "├── "
        rows.append(
            _tree.TreeLine(
                uri=individual_uri,
                depth=depth + 1,
                prefix=prefix + extension + individual_connector,
                file_path=file_path,
                node_type=_LIT_INDIVIDUAL,
            )
        )
    return rows


def _class_tree_branch(
    taxonomy: Taxonomy,
    children_of: dict[str, list[str]],
    folded: set[str],
    file_path: Path | None,
    individuals_of: dict[str, list[str]],
    visited: set[str],
    uri: str,
    depth: int,
    prefix: str,
    is_last: bool,
) -> list[_tree.TreeLine]:
    if uri in visited:
        return []
    visited.add(uri)
    children = children_of.get(uri, [])
    individuals = individuals_of.get(uri, [])
    is_folded = uri in folded and bool(children or individuals)
    connector = "└── " if is_last else "├── "
    row = _tree.TreeLine(
        uri=uri,
        depth=depth,
        prefix=prefix + connector,
        is_folded=is_folded,
        hidden_count=_count_class_descendants(children_of, uri, individuals_of) if is_folded else 0,
        file_path=file_path,
        node_type=taxonomy.node_type(uri),
    )
    if is_folded:
        return [row]
    extension = prefix + ("    " if is_last else "│   ")
    return [
        row,
        *_class_tree_children(
            taxonomy,
            children_of,
            folded,
            file_path,
            individuals_of,
            visited,
            depth,
            extension,
            children,
            individuals,
        ),
    ]


def _class_tree_rows(
    taxonomy: Taxonomy,
    children_of: dict[str, list[str]],
    roots: list[str],
    folded: set[str],
    file_path: Path | None,
    depth: int,
    prefix: str,
    individuals_of: dict[str, list[str]],
) -> list[_tree.TreeLine]:
    rows: list[_tree.TreeLine] = []
    visited: set[str] = set()
    for index, root_uri in enumerate(roots):
        rows.extend(
            _class_tree_branch(
                taxonomy,
                children_of,
                folded,
                file_path,
                individuals_of,
                visited,
                root_uri,
                depth,
                prefix,
                index == len(roots) - 1,
            )
        )
    return rows


def flatten_mixed_tree(
    taxonomy_or_workspace: Taxonomy | TaxonomyWorkspace,
    folded: set[str] | None = None,
) -> list[_tree.TreeLine]:
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
    section = _tree._props_section_line(folded)
    children = (
        _tree._prop_child_lines(tax) if tax and _tree.SECTION_PROPERTIES not in folded else []
    )
    return [section] + children + inner


def _flatten_mixed(
    taxonomy: Taxonomy,
    folded: set[str] | None = None,
    file_path: Path | None = None,
    scheme_depth: int = 0,
    scheme_prefix: str = "",
    concept_base_depth: int = 0,
) -> list[_tree.TreeLine]:
    if folded is None:
        folded = set()

    skos_rows = _tree._flatten_taxonomy(
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

    children_of, roots = _class_hierarchy(taxonomy, pure_class_uris)
    individuals_of = _build_individuals_of(taxonomy)
    owl_rows = _class_tree_rows(
        taxonomy,
        children_of,
        roots,
        folded,
        file_path,
        concept_base_depth,
        scheme_prefix,
        individuals_of,
    )

    ontology_name = _ontology_display_name(taxonomy, file_path)
    ont_root = _tree.TreeLine(
        uri=_tree._ontology_sentinel(file_path),
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


def _count_hidden_in_mixed_file(taxonomy: Taxonomy) -> int:
    """Row count hidden under a folded file node in the mixed SKOS+OWL tree."""
    hidden = 0
    for scheme in taxonomy.schemes.values():
        hidden += 1
        for tc in scheme.top_concepts:
            if tc in taxonomy.concepts:
                hidden += 1 + _tree._count_descendants(taxonomy, tc)
    hidden += sum(1 for uri in taxonomy.owl_classes if uri not in taxonomy.concepts)
    return hidden


def _append_workspace_mixed_file(
    file_path: Path,
    taxonomy: Taxonomy,
    folded: set[str],
    result: list[_tree.TreeLine],
) -> None:
    """Append one workspace file's node, and its mixed subtree when unfolded."""
    file_uri = _tree._file_sentinel(file_path)
    file_folded = file_uri in folded
    hidden_in_file = _count_hidden_in_mixed_file(taxonomy) if file_folded else 0

    result.append(
        _tree.TreeLine(
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


def _flatten_workspace_mixed(
    workspace: TaxonomyWorkspace,
    folded: set[str] | None = None,
) -> list[_tree.TreeLine]:
    if folded is None:
        folded = set()
    result: list[_tree.TreeLine] = []

    for file_path, taxonomy in workspace.taxonomies.items():
        _append_workspace_mixed_file(file_path, taxonomy, folded, result)

    return result


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
) -> list[_tree.TreeLine]:
    """Flatten the OWL/RDFS class hierarchy into _tree.TreeLine rows.

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
    section = _tree._props_section_line(folded)
    children = (
        _tree._prop_child_lines(tax) if tax and _tree.SECTION_PROPERTIES not in folded else []
    )
    return [section] + children + inner


def _unattached_individuals_group(
    unattached: list[str],
    roots: list[str],
    folded: set[str],
    file_path: Path | None,
) -> list[_tree.TreeLine]:
    """The 'Unattached individuals' group row + its children (depth 1, always first)."""
    if not unattached:
        return []
    rows: list[_tree.TreeLine] = []
    grp_is_last = not roots
    grp_connector = "└── " if grp_is_last else "├── "
    grp_is_fold = _tree._UNATTACHED_INDS_URI in folded
    n = len(unattached)
    noun = _LIT_INDIVIDUAL if n == 1 else "individuals"
    rows.append(
        _tree.TreeLine(
            uri=_tree._UNATTACHED_INDS_URI,
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
            rows.append(
                _tree.TreeLine(
                    uri=ind_uri,
                    depth=2,
                    prefix=child_base + ind_connector,
                    file_path=file_path,
                    node_type=_LIT_INDIVIDUAL,
                )
            )
    return rows


def _flatten_ontology(
    taxonomy: Taxonomy,
    folded: set[str] | None = None,
    file_path: Path | None = None,
) -> list[_tree.TreeLine]:
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

    children_of, roots = _class_hierarchy(taxonomy)
    individuals_of = _build_individuals_of(taxonomy)
    class_rows = _class_tree_rows(
        taxonomy, children_of, roots, folded, file_path, 1, "    ", individuals_of
    )
    result: list[_tree.TreeLine] = []

    ontology_name = _ontology_display_name(taxonomy, file_path)
    ont_root = _tree.TreeLine(
        uri=_tree._ontology_sentinel(file_path),
        depth=0,
        prefix="",
        is_scheme=True,
        label=ontology_name,
        file_path=file_path,
        node_type="ontology",
    )

    result.extend(_unattached_individuals_group(unattached, roots, folded, file_path))
    result.extend(class_rows)

    return [ont_root] + result
