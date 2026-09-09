"""Public load/save entry points: parse-with-cache orchestration, read-only context
merging, and atomic writes."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from pathlib import Path

from ..handles import assign_handles
from ..model import Taxonomy
from . import _to_graph
from ._cache import (
    _get_bin_cache_path,
    _is_cache_valid,
    _prune_stale_schema_caches,
    _try_load_cache,
    _try_save_cache,
)
from ._format import _detect_format
from ._from_graph import _capture_residue, _taxonomy_from_index, graph_to_taxonomy
from ._graph_io import _DATASET_FORMATS, _native_index, _parse_graph

_ENTITY_REGISTRIES = ("schemes", "concepts", "owl_classes", "owl_individuals", "owl_properties")


def _report_progress(
    callback: Callable[[int, str], None] | None, percent: int, message: str
) -> None:
    """Report a coarse load phase without making progress callbacks mandatory."""
    if callback is not None:
        callback(percent, message)


def _parse_to_taxonomy(path: Path) -> Taxonomy:
    """Build the taxonomy for *path*, in Rust when possible and rdflib otherwise."""
    try:
        fmt = _detect_format(path)
    except ValueError:
        fmt = ""
    if fmt and fmt not in _DATASET_FORMATS and (native := _native_index(fmt, path)) is not None:
        parsed, ns_graph = native
        taxonomy = _taxonomy_from_index(parsed, ns_graph)
        # The index the native parser builds is keyed by URIRef subject, so it
        # cannot say what it dropped — a blank-node class expression never
        # reaches it. Residue therefore has to be measured against the file
        # itself, which costs one rdflib parse the fast path had avoided. That
        # is the price of not losing data, and the binary cache means it is paid
        # once per edit rather than once per open.
        _capture_residue(taxonomy, _parse_graph(path))
        return taxonomy
    return graph_to_taxonomy(_parse_graph(path))


def load(
    path: str | Path,
    progress_callback: Callable[[int, str], None] | None = None,
    context: list[Path] | None = None,
) -> Taxonomy:
    """Parse an RDF file and return a fully handle-annotated Taxonomy.

    *context* names further files to merge in **read-only**, so the connected
    graph is visible while exactly one file stays writable. Their entities are
    recorded in ``Taxonomy.context_source`` and excluded when saving.

    Uses a binary cache file in ~/.cache/ster/bin_cache to speed up subsequent
    loads of large files IF the source file hasn't changed. Caching can be
    disabled by setting STER_NO_CACHE=1 in the environment.
    """
    path = Path(path)
    _report_progress(progress_callback, 0, "Starting")
    use_cache = os.environ.get("STER_NO_CACHE") != "1"
    cache_path = _get_bin_cache_path(path)

    if use_cache:
        # Unconditionally, not just on a miss: a hit still means any cache of this
        # file under a different model schema is dead weight, and one glob is
        # nothing beside a parse. Otherwise an orphan survives every load.
        _prune_stale_schema_caches(path)

    taxonomy = (
        _try_load_cache(cache_path, path)
        if use_cache and _is_cache_valid(cache_path, path)
        else None
    )
    if taxonomy is None:
        _report_progress(progress_callback, 5, "Parsing RDF")
        _report_progress(progress_callback, 45, "Building model")
        taxonomy = _parse_to_taxonomy(path)
        taxonomy.file_path = path
        _report_progress(progress_callback, 80, "Assigning handles")
        assign_handles(taxonomy)
        if use_cache:
            _try_save_cache(cache_path, taxonomy)
            _report_progress(progress_callback, 95, "Updating cache")
        _report_progress(progress_callback, 100, "Ready")
    else:
        _report_progress(progress_callback, 100, "Loaded from cache")

    # Merged after the cache is written, so the cache stays a faithful copy of
    # this file alone and never depends on which context happened to be loaded.
    for other in context or ():
        _merge_context(taxonomy, Path(other))
    if context:
        # Deliberately *not* re-normalising the hierarchy here. A context concept
        # declaring broader on an editable one would gain the reciprocal narrower
        # on that editable entity — and saving would then write a synthesised
        # `narrower` into the user's file, pointing at an entity that does not
        # exist when the file is opened on its own. The graph reads broader from
        # the child, so cross-file links already draw; only the tree, which walks
        # narrower downward, does not yet show them.
        assign_handles(taxonomy)
    return taxonomy


def _merge_context(taxonomy: Taxonomy, path: Path) -> None:
    """Merge *path* into *taxonomy* read-only, recording where each entity came from.

    A URI already present is kept as-is: the editable definition is the one the
    user can act on, so it must be the one they see.
    """
    other = load(path)
    for registry in _ENTITY_REGISTRIES:
        target = getattr(taxonomy, registry)
        for uri, entity in getattr(other, registry).items():
            if uri in target:
                continue
            target[uri] = entity
            taxonomy.context_source[uri] = path
    for prefix, namespace in other.namespace_bindings.items():
        taxonomy.namespace_bindings.setdefault(prefix, namespace)


def source_files(taxonomy: Taxonomy) -> list[Path]:
    """Every file this taxonomy was read from — the writable one first.

    Anything that re-reads the source rather than the model needs this, not
    ``file_path``: the map's geometry lookup and the SPARQL endpoint both parse
    the file again (a Concept models no ``wgs:lat``, so a rebuilt model has no
    coordinates to place). Reading only ``file_path`` there silently halves the
    graph — the context entities are in the model, visible in the tree, and then
    absent from the map.

    Derived from ``context_source`` rather than passed alongside, so a taxonomy
    stays sufficient on its own and every front-end gets the same answer without
    plumbing the list through separately.
    """
    files = [taxonomy.file_path] if taxonomy.file_path is not None else []
    seen = set(files)
    for path in taxonomy.context_source.values():
        if path not in seen:
            seen.add(path)
            files.append(path)
    return files


def is_editable(taxonomy: Taxonomy, uri: str) -> bool:
    """False only for entities that came from a read-only context file.

    An unknown URI is editable: it belongs to whatever is about to be written.
    """
    return uri not in taxonomy.context_source


def save(taxonomy: Taxonomy, path: str | Path) -> None:
    """Serialize a Taxonomy back to an RDF file (format detected from extension).

    The write is atomic: the serialized data goes to a sibling temp file that is
    fsync'd and then ``os.replace``-d onto *path*. A crash or a concurrent reader
    never observes a truncated file, and a failed write leaves the previous file
    intact (no partial overwrite, no leftover temp file).
    """
    path = Path(path)
    fmt = _detect_format(path)
    g = _to_graph.taxonomy_to_graph(taxonomy)
    data = g.serialize(format=fmt)
    _atomic_write_text(path, data)


def _atomic_write_text(path: Path, data: str) -> None:
    """Write *data* to *path* atomically via a sibling temp file + os.replace."""
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
