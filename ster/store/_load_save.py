"""Public load/save entry points: parse-with-cache orchestration, read-only context
merging, and atomic writes."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from pathlib import Path

from rdflib import RDF, Graph, URIRef
from rdflib.namespace import OWL, RDFS, SKOS

from ..handles import assign_handles
from ..model import Taxonomy
from . import _to_graph
from ._cache import (
    _get_bin_cache_path,
    _get_context_cache_path,
    _is_cache_valid,
    _is_merged_cache_valid,
    _prune_stale_context_caches,
    _prune_stale_schema_caches,
    _source_manifest,
    _try_load_cache,
    _try_save_cache,
    _write_manifest,
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


_MAIN_SHARE = 10  # percent of a load with context that the editable file accounts for
_ALMOST_DONE = 99  # percent while the handles are assigned and the merged result is cached
_READING_END = 50  # percent reached once every context file has been read for its schema


def _scaled(
    callback: Callable[[int, str], None] | None, start: int, share: int
) -> Callable[[int, str], None] | None:
    """*callback* seen through a window: a 0-100 report becomes *start* to *start* + *share*."""
    if callback is None:
        return None
    return lambda percent, message: callback(start + percent * share // 100, message)


class _ContextProgress:
    """Spreads the merging of context files over the progress bar, by file size.

    Reading a file and merging it each take a share of the bar, so it moves with the work instead of sitting at
    the 100% the editable file reached while the rest still had to be read.
    """

    def __init__(self, callback: Callable[[int, str], None] | None, files: list[Path]) -> None:
        self._callback = callback
        self._names = [Path(f).name for f in files]
        sizes = [max(_size_of(Path(f)), 1) for f in files]
        self._total = sum(sizes)
        self._done_before = [sum(sizes[:i]) for i in range(len(sizes))]

    def starting(self, step: str, index: int, first: int, last: int) -> None:
        """Say that file *index* is about to be *step*-ed; the bar is at the share of bytes already done."""
        done = self._done_before[index] / self._total
        _report_progress(
            self._callback,
            first + int((last - first) * done),
            f"{step} context {index + 1}/{len(self._names)}: {self._names[index]}",
        )


def _size_of(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _merge_all_context(
    taxonomy: Taxonomy, context: list[Path], progress_callback: Callable[[int, str], None] | None
) -> None:
    """Read every context file once for its schema, then merge each one in, reporting as it goes."""
    progress = _ContextProgress(progress_callback, context)
    # Snapshot before any merging. A triple the editable file already asserts
    # is its own even when a context file asserts it too, so the diff below
    # can never mark it as another file's and strip it on save.
    _report_progress(progress_callback, _MAIN_SHARE, "Reading the editable file's schema")
    base_triples = frozenset(_to_graph.taxonomy_to_graph(taxonomy))
    parsed: dict[Path, Graph] = {}
    schema_graph = _context_schema_graph(taxonomy, context, parsed, progress)
    for index, other in enumerate(context):
        progress.starting("Merging", index, _READING_END, 100)
        _merge_context(
            taxonomy, Path(other), base_triples, schema_graph, parsed.pop(Path(other), None)
        )
    # Deliberately *not* re-normalising the hierarchy here. A context concept
    # declaring broader on an editable one would gain the reciprocal narrower
    # on that editable entity — and saving would then write a synthesised
    # `narrower` into the user's file, pointing at an entity that does not
    # exist when the file is opened on its own. The graph reads broader from
    # the child, so cross-file links already draw; only the tree, which walks
    # narrower downward, does not yet show them.
    _report_progress(progress_callback, _ALMOST_DONE, "Assigning handles")
    assign_handles(taxonomy)


def _load_merged_cache(path: Path, context: list[Path]) -> Taxonomy | None:
    """The taxonomy of *path* with *context* merged in, from the cache, when nothing it was built from has changed."""
    _prune_stale_context_caches(path, context)
    cache_path = _get_context_cache_path(path, context)
    if not _is_merged_cache_valid(cache_path, [path, *context]):
        return None
    return _try_load_cache(cache_path, path)


def _manifest_of(sources: list[Path]) -> dict[str, dict] | None:
    """What *sources* are right now, or None when one cannot be read (the load itself will say why)."""
    try:
        return _source_manifest(sources)
    except OSError:
        return None


def _save_merged_cache(path: Path, context: list[Path], taxonomy: Taxonomy, manifest) -> None:
    """Save the merged *taxonomy* and, when the files could be read, the manifest that vouches for it."""
    cache_path = _get_context_cache_path(path, context)
    _try_save_cache(cache_path, taxonomy)
    if manifest is not None:
        _write_manifest(cache_path, manifest)


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
    loads of large files IF the source file hasn't changed. With *context* there is
    a second cache of the merged result, valid only while the editable file and every
    context file still match the manifest saved with it (size, time, then content), so
    reopening a project does not read its context files again. Caching can be disabled by setting STER_NO_CACHE=1 in the environment.
    """
    path = Path(path)
    # With context files the editable file is only the first tenth of the work; reporting it as the whole
    # would show 100% while the files merged in afterwards still had to be read.
    report = _scaled(progress_callback, 0, _MAIN_SHARE) if context else progress_callback
    _report_progress(report, 0, "Starting")
    use_cache = os.environ.get("STER_NO_CACHE") != "1"
    if context and use_cache and (merged := _load_merged_cache(path, context)) is not None:
        _report_progress(progress_callback, 100, "Loaded from cache")
        return merged
    # Taken before anything is read, so a file edited while the load runs is seen as changed next time.
    manifest = _manifest_of([path, *context]) if context and use_cache else None
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
        _report_progress(report, 5, "Parsing RDF")
        _report_progress(report, 45, "Building model")
        taxonomy = _parse_to_taxonomy(path)
        taxonomy.file_path = path
        _report_progress(report, 80, "Assigning handles")
        assign_handles(taxonomy)
        if use_cache:
            _try_save_cache(cache_path, taxonomy)
            _report_progress(report, 95, "Updating cache")
        _report_progress(report, 100, "Ready")
    else:
        _report_progress(report, 100, "Loaded from cache")

    # Merged after the cache is written, so the cache stays a faithful copy of
    # this file alone and never depends on which context happened to be loaded.
    if context:
        _merge_all_context(taxonomy, context, progress_callback)
        if use_cache:
            _report_progress(progress_callback, _ALMOST_DONE, "Updating cache")
            _save_merged_cache(path, context, taxonomy, manifest)
    return taxonomy


def _merge_statements_onto(existing: object, incoming: object) -> None:
    """Add *incoming*'s list-valued statements to *existing*, skipping duplicates.

    A context file routinely says things about an entity the editable file
    defines — a competitor set records ``LeroyMerlin ownedBy group-adeo`` and
    ``bu-leroy-merlin-fr competesWith bu-castorama-fr``, statements about our own
    entities that belong with the rival data rather than with ours. Skipping the
    whole entity because its URI was already known dropped every one of them: on
    the retail ontology, 55 triples across 21 subjects, so "which brands does
    Adeo own" answered from half the graph and every reciprocal competesWith
    edge was missing.

    Only list fields are merged, and only by adding. A scalar the editable file
    set (``note``, ``prop_type``, ``is_functional``) is left alone: the file the
    user can act on owns its own values, and a context file must not overwrite
    them. Ordering is preserved so a round-trip stays stable.
    """
    from dataclasses import fields as dataclass_fields  # noqa: PLC0415

    for field in dataclass_fields(existing):  # type: ignore[arg-type]
        current = getattr(existing, field.name, None)
        addition = getattr(incoming, field.name, None)
        if not isinstance(current, list) or not isinstance(addition, list):
            continue
        seen = {_hashable(v) for v in current}
        for value in addition:
            key = _hashable(value)
            if key not in seen:
                seen.add(key)
                current.append(value)


def _hashable(value: object) -> object:
    """A comparable key for a statement value — dataclasses are not hashable."""
    from dataclasses import asdict, is_dataclass  # noqa: PLC0415

    if is_dataclass(value) and not isinstance(value, type):
        return repr(sorted(asdict(value).items()))
    return value


_RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"  # NOSONAR - RDF predicate IRI
_RDFS_COMMENT = "http://www.w3.org/2000/01/rdf-schema#comment"  # NOSONAR - RDF predicate IRI


def _entity_holding(taxonomy: Taxonomy, uri: str, attribute: str) -> object | None:
    """The first entity registered under *uri* that can hold *attribute*.

    Registry order matters only for a punned URI — a brand that is both a class
    and an individual. Taking the first match keeps the statement in one place
    rather than emitting it twice, and the order is fixed so a round-trip is
    stable.
    """
    for registry in _ENTITY_REGISTRIES:
        entity = getattr(taxonomy, registry).get(uri)
        if entity is not None and _can_hold(entity, attribute):
            return entity
    return None


def _can_hold(entity: object, attribute: str) -> bool:
    """Whether *entity* can take a promoted value in *attribute* without changing it.

    ``labels`` is the trap: on a Concept or ConceptScheme it holds SKOS labels,
    written back as ``skos:prefLabel`` / ``dcterms:title``. An ``rdfs:label``
    filed there comes out as a different statement — one the writer cannot
    match against the recorded ``rdfs:label`` to strip, so saving leaked the
    context file's label into the editable file. Left unpromoted, it stays
    context residue: read, queryable, and still ``rdfs:label``.
    """
    from ..model import Concept, ConceptScheme  # noqa: PLC0415

    if attribute == "labels" and isinstance(entity, (Concept, ConceptScheme)):
        return False
    return isinstance(getattr(entity, attribute, None), list)


def _promoted_value(predicate: str, obj: object) -> tuple[str, object]:
    """Where a residue statement belongs on an entity, and in what shape.

    One table rather than a branch per case: the four kinds differ only in which
    list they land in and how the value is spelled. Label and Definition are
    dataclasses, so ``in`` deduplicates without a comparison written by hand.
    """
    from ..model import Definition, Label  # noqa: PLC0415

    if isinstance(obj, URIRef):
        return "property_values", (predicate, str(obj))
    lang = getattr(obj, "language", None) or ""
    if predicate == _RDFS_LABEL:
        return "labels", Label(lang=lang, value=str(obj))
    if predicate == _RDFS_COMMENT:
        return "comments", Definition(lang=lang, value=str(obj))
    return "literal_values", (predicate, str(obj), lang)


def _promote_one(taxonomy: Taxonomy, triple: tuple) -> bool:
    """Attach one residue triple to the entity it describes; False if it cannot be."""
    attribute, value = _promoted_value(str(triple[1]), triple[2])
    entity = _entity_holding(taxonomy, str(triple[0]), attribute)
    if entity is None:
        return False
    bucket = getattr(entity, attribute)
    if value not in bucket:
        bucket.append(value)
    return True


def _promote_residue(taxonomy: Taxonomy, residue: list, path: Path) -> list:
    """Attach a context file's residue to entities it talks about; return the rest.

    Loaded on its own, a file that only *references* an entity gives ster nothing
    to model: ``bu-leroy-merlin-fr competesWith bu-castorama-fr`` carries no
    rdf:type for its subject, so no individual is built and the triple falls to
    residue. Merged next to the file that *does* define that subject, it stops
    being unmodellable — the entity is right there — and leaving it as residue
    would keep it out of every query for no reason.

    Literals count, not only object properties. A vocabulary file split out from
    the data it describes is made almost entirely of ``rdfs:label`` and
    ``rdfs:comment``; promoting only URI objects would leave that whole way of
    splitting a project invisible.

    Anything with no entity to attach to, or no field able to hold it, stays
    residue and round-trips untouched. Each promotion is recorded against *path*
    so the writer knows the statement belongs to that file and not to the one
    that happens to define its subject.
    """
    rest = []
    for triple in residue:
        if _promote_one(taxonomy, triple):
            # Verbatim, not stringified: the writer removes this exact term from
            # the emitted graph, and a literal's language tag and datatype are
            # part of its identity.
            taxonomy.context_statements.setdefault(path, []).append(tuple(triple[:3]))
        else:
            rest.append(triple)
    return rest


def _record_contributed(
    taxonomy: Taxonomy, other: Taxonomy, path: Path, base_triples: frozenset
) -> None:
    """Record every triple *other* contributes that the editable file does not assert.

    ``_merge_statements_onto`` puts a context file's statements on an entity the
    editable file defines, which is what makes them queryable — but that entity
    *is* written on save, so without this the statements migrate into the user's
    file. Recording them here lets the writer take them out again, the same way
    promoted residue is already handled.

    Diffed against *base_triples* rather than taken wholesale: a triple both files
    assert belongs to the editable one too, and stripping it would delete the
    user's own data.
    """
    # Residue is excluded: _promote_residue records what it attaches and
    # context_residue keeps the rest, so a triple stays in exactly one place.
    residue = {tuple(t[:3]) for t in (other.residue or [])}
    contributed = [
        t for t in _to_graph.taxonomy_to_graph(other) if t not in base_triples and t not in residue
    ]
    if contributed:
        taxonomy.context_statements.setdefault(path, []).extend(contributed)


def _read_context_file(path: Path, schema_graph: Graph | None, parsed: Graph | None) -> Taxonomy:
    """The model of one context file: on its own, or classified by the schema of all of them when *schema_graph* is given.

    *parsed* is the file as the schema pass already read it, so that it is not parsed a second time.
    """
    if schema_graph is None:
        return load(path)
    source = parsed if parsed is not None else _parse_graph(path)
    merged = Graph()
    for triple in schema_graph:
        merged.add(triple)
    for triple in source:
        merged.add(triple)
    return graph_to_taxonomy(merged)


def _merge_context(
    taxonomy: Taxonomy,
    path: Path,
    base_triples: frozenset,
    schema_graph: Graph | None = None,
    parsed: Graph | None = None,
) -> None:
    """Merge *path* into *taxonomy* read-only, recording where each entity came from.

    An entity the editable file does not define is taken whole and marked as
    coming from *path*. An entity it *does* define keeps its own identity — the
    definition the user can act on is the one they must see — but the context
    file's statements about it are added, because a file that says something new
    about a known entity is the ordinary case, not an error.

    The context file's residue is carried too, keyed by file. Nothing reads it
    yet; it is captured here because the alternative is discovering later that a
    file's unmodelled triples were dropped at merge and never existed to write
    back — the retail competitor set alone carries 66 of them.
    """
    other = _read_context_file(path, schema_graph, parsed)
    taxonomy.context_files.append(path)
    _record_contributed(taxonomy, other, path, base_triples)
    for registry in _ENTITY_REGISTRIES:
        target = getattr(taxonomy, registry)
        for uri, entity in getattr(other, registry).items():
            if uri in target:
                _merge_statements_onto(target[uri], entity)
                continue
            target[uri] = entity
            taxonomy.context_source[uri] = path
    # A residue triple the editable file also asserts is the editable file's, as
    # in _record_contributed. Left in, it would be credited to *path* — and if
    # promoted, recorded in context_statements, which the writer strips from
    # the editable file on save.
    residue = [t for t in other.residue if tuple(t[:3]) not in base_triples]
    kept = _promote_residue(taxonomy, residue, path)
    if kept:
        taxonomy.context_residue.setdefault(path, []).extend(kept)
    for prefix, namespace in other.namespace_bindings.items():
        taxonomy.namespace_bindings.setdefault(prefix, namespace)


def _context_schema_graph(
    taxonomy: Taxonomy,
    context: list[Path],
    parsed: dict[Path, Graph] | None = None,
    progress: _ContextProgress | None = None,
) -> Graph:
    """Build schema declarations needed to classify context-only instances.

    Each file read is kept in *parsed*, when given, for the merge that follows: a file is parsed once, not twice.
    """
    source = _to_graph.taxonomy_to_graph(taxonomy)
    schema = Graph()
    schema_types = {
        str(OWL.Class),
        str(RDFS.Class),
        str(OWL.ObjectProperty),
        str(OWL.DatatypeProperty),
        str(OWL.AnnotationProperty),
    }
    schema_subjects = {
        subject
        for subject in source.subjects(RDF.type, None)
        if str(next(source.objects(subject, RDF.type), "")) in schema_types
    }
    for subject in schema_subjects:
        schema.add((subject, RDF.type, next(source.objects(subject, RDF.type))))
    for subject, predicate, obj in source:
        if predicate in (RDFS.domain, RDFS.range, RDFS.subClassOf):
            schema.add((subject, predicate, obj))
    for index, path in enumerate(context):
        if progress is not None:
            progress.starting("Reading", index, _MAIN_SHARE, _READING_END)
        source = _parse_graph(Path(path))
        if parsed is not None:
            parsed[Path(path)] = source
        context_schema_types = {*schema_types, str(SKOS.ConceptScheme)}
        subjects = {
            str(subject)
            for subject in source.subjects(RDF.type, None)
            if any(str(kind) in context_schema_types for kind in source.objects(subject, RDF.type))
        }
        for subject, predicate, obj in source:
            if str(subject) in subjects or predicate in (RDFS.domain, RDFS.range, RDFS.subClassOf):
                schema.add((subject, predicate, obj))
    return schema


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


def _drop_other_files_statements(graph: object, taxonomy: Taxonomy, path: Path) -> None:
    """Remove statements that belong to a *different* file than the one being written.

    Merging makes a context file's statements visible on the entity they talk
    about, which is what makes them queryable — but the entity is defined in the
    editable file, so a plain serialisation of the model writes them there too.
    On the retail ontology that silently moved 51 triples out of the competitor
    file and into the main one: no data lost, and the separation the two files
    exist for quietly dissolved.

    Removed from the emitted graph rather than from the model, so the taxonomy
    the application is still using is untouched.
    """
    for other, statements in taxonomy.context_statements.items():
        if other == path:
            continue
        for triple in statements:
            graph.remove(triple)  # type: ignore[attr-defined]


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
    _drop_other_files_statements(g, taxonomy, path)
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
