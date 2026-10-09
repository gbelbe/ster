"""Binary (pickled) Taxonomy cache: schema-fingerprinted, owner-only, and pruned of
stale entries left behind whenever the model shape changes."""

from __future__ import annotations

import hashlib
import json
import os
import pickle
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

from ..model import Taxonomy

_ENCODING: Final = "utf-8"
_MANIFEST_SUFFIX: Final = ".manifest.json"
_HASH_CHUNK: Final = 1 << 20


def _bin_cache_dir() -> Path:
    """Return the directory for binary taxonomy caches."""
    return Path.home() / ".cache" / "ster" / "bin_cache"


@lru_cache(maxsize=1)
def _model_schema_fingerprint() -> str:
    """A short hash of the code that builds the cached model: every model dataclass, its fields, and the loader.

    Unpickling does not validate the class: a Taxonomy pickled before a field
    existed is restored *without* it, no exception raised, and the first access
    to the missing attribute fails somewhere unrelated — as a 500 from the graph
    server, say. Mixing this into the cache key means a build whose model has
    changed simply looks elsewhere instead of reading the older build's file.

    The shape alone is not enough. It catches a field being added or removed, but
    not a change to the logic that *fills* one — which is the more common kind of
    change, and just as stale. So the source of the model and of the loader goes in
    too: a change to the code that decides what the cached model holds looks
    elsewhere, while a release that touched neither keeps the cache (it used to be
    keyed on the ster version, which discarded a minutes-long load on every upgrade).
    """
    from dataclasses import fields, is_dataclass  # noqa: PLC0415

    from .. import model as _model  # noqa: PLC0415

    shape = [
        f"{name}:{','.join(f.name for f in fields(obj))}"
        for name in sorted(dir(_model))
        if isinstance(obj := getattr(_model, name), type) and is_dataclass(obj)
    ]
    shape.append(f"code:{_loader_source_hash()}")
    return hashlib.md5("|".join(shape).encode(), usedforsecurity=False).hexdigest()[:8]


def _loader_source_hash() -> str:
    """A hash of the model and the store package's source, or the ster version when it cannot be read."""
    package = Path(__file__).resolve().parent
    sources = [package.parent / "model.py", *sorted(package.glob("*.py"))]
    digest = hashlib.sha256()
    try:
        for source in sources:
            digest.update(source.name.encode())
            digest.update(source.read_bytes())
    except OSError:  # a build shipped without its sources: the version is the best stand-in left
        from .._version import __version__  # noqa: PLC0415

        return __version__
    return digest.hexdigest()[:16]


def _cache_stem(path: Path) -> str:
    """The cache filename prefix for *path*, without the schema fingerprint."""
    # Keyed by absolute path hash to avoid collisions and keep it house-trained
    abs_path = str(path.resolve())
    h = hashlib.md5(abs_path.encode(), usedforsecurity=False).hexdigest()[:16]
    # Use stem to keep it somewhat readable in the cache dir
    return f"{path.stem}_{h}"


def _get_bin_cache_path(path: Path) -> Path:
    """Return a unique, safe cache path for the given RDF file and model schema."""
    return _bin_cache_dir() / f"{_cache_stem(path)}_{_model_schema_fingerprint()}.pickle"


def _get_context_cache_path(path: Path, context: list[Path]) -> Path:
    """The cache of *path* with *context* merged in: one per file and list of context files, per model schema.

    The prefix keeps it out of reach of :func:`_prune_stale_schema_caches`, which owns the plain file's caches.
    """
    listed = "\n".join(str(Path(c).resolve()) for c in context)
    key = hashlib.md5(listed.encode(), usedforsecurity=False).hexdigest()[:12]
    return (
        _bin_cache_dir() / f"merged-{_cache_stem(path)}-{key}_{_model_schema_fingerprint()}.pickle"
    )


def _prune_stale_context_caches(path: Path, context: list[Path]) -> None:
    """Delete the merged caches of this file and context list written under a different model schema."""
    keep = _get_context_cache_path(path, context)
    try:
        for stale in keep.parent.glob(f"{keep.name.rsplit('_', 1)[0]}_*.pickle"):
            if stale != keep and not stale.is_symlink():
                stale.unlink(missing_ok=True)
                _manifest_path(stale).unlink(missing_ok=True)
    except OSError:
        pass


def _prune_stale_schema_caches(path: Path) -> None:
    """Delete this file's caches written under a different model schema.

    Without it every release that touches the model leaves an orphan per cached
    file behind, forever. Scoped to one source file's own prefix, so it can never
    reach anything else in the directory.
    """
    keep = _get_bin_cache_path(path)
    try:
        for stale in keep.parent.glob(f"{_cache_stem(path)}_*.pickle"):
            if stale != keep and not stale.is_symlink():
                stale.unlink(missing_ok=True)
    except OSError:  # a read-only or vanished cache dir is not worth failing a load
        pass


def _is_cache_valid(cache_path: Path, source_path: Path) -> bool:
    """Return True if the binary cache is fresh and secure."""
    if not cache_path.is_file() or cache_path.is_symlink():
        return False

    try:
        cache_stat = cache_path.stat()
        if cache_stat.st_mtime <= source_path.stat().st_mtime:
            return False

        # Security: ensure the cache belongs to the current user (owner-only)
        if hasattr(os, "getuid") and cache_stat.st_uid != os.getuid():
            return False
    except OSError:
        return False

    return True


def _manifest_path(cache_path: Path) -> Path:
    """Where the record of the source files behind *cache_path* is kept, beside it."""
    return cache_path.with_name(cache_path.name + _MANIFEST_SUFFIX)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(_HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _source_manifest(sources: list[Path]) -> dict[str, dict[str, Any]]:
    """Size, modification time and content hash of each of *sources*, by absolute path."""
    manifest: dict[str, dict[str, Any]] = {}
    for source in sources:
        path = Path(source)
        stat = path.stat()
        manifest[str(path.resolve())] = {
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "sha256": _file_sha256(path),
        }
    return manifest


def _write_manifest(cache_path: Path, manifest: dict[str, dict[str, Any]]) -> None:
    """Record *manifest* beside *cache_path*, owner-only. Best-effort: without it the cache is simply not trusted."""
    target = _manifest_path(cache_path)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode=0o600)
        with os.fdopen(fd, "w", encoding=_ENCODING) as handle:
            json.dump(manifest, handle)
    except OSError:
        pass


def _read_manifest(cache_path: Path) -> dict[str, dict[str, Any]] | None:
    try:
        data = json.loads(_manifest_path(cache_path).read_text(encoding=_ENCODING))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _unchanged(recorded: Any, path: Path) -> bool:
    """True when *path* still is what *recorded* says: same size and time, else same content."""
    try:
        stat = path.stat()
        if not isinstance(recorded, dict) or stat.st_size != recorded.get("size"):
            return False
        return stat.st_mtime_ns == recorded.get("mtime_ns") or (
            _file_sha256(path) == recorded.get("sha256")
        )
    except OSError:
        return False


def _is_ours(cache_path: Path) -> bool:
    """The cache file exists, is not a link, and belongs to the current user."""
    if not cache_path.is_file() or cache_path.is_symlink():
        return False
    try:
        owner = cache_path.stat().st_uid
    except OSError:
        return False
    return not hasattr(os, "getuid") or owner == os.getuid()


def _is_merged_cache_valid(cache_path: Path, sources: list[Path]) -> bool:
    """True when every file the merged cache was built from, the editable one and each context file, is unchanged.

    Judged by the manifest saved beside the cache, not by timestamps: a file restored with an
    older time but different content must not keep serving the old graph, and a file merely
    touched need not throw a slow rebuild away. A missing or unreadable manifest, a file added,
    removed or gone all make the cache invalid: it can no longer vouch for what it holds.
    """
    if not _is_ours(cache_path):
        return False
    manifest = _read_manifest(cache_path)
    if manifest is None:
        return False
    try:
        wanted = {str(Path(source).resolve()): Path(source) for source in sources}
    except OSError:
        return False
    return manifest.keys() == wanted.keys() and all(
        _unchanged(manifest[key], path) for key, path in wanted.items()
    )


def clear_merged_caches() -> int:
    """Delete every saved binary graph and its manifest; the number of files removed.

    Only the binary-cache folder is touched, so vendored scripts and other files kept
    under ``~/.cache/ster`` stay where they are.
    """
    removed = 0
    try:
        for entry in _bin_cache_dir().iterdir():
            if entry.is_file() or entry.is_symlink():
                entry.unlink(missing_ok=True)
                removed += 1
    except OSError:
        pass
    return removed


def _try_load_cache(cache_path: Path, source_path: Path) -> Taxonomy | None:
    """Attempt to load the taxonomy from the binary cache."""
    try:
        with open(cache_path, "rb") as f:
            # Local trusted cache generated by the tool itself for ~40x speedup.
            # S301 is waived because we verify file ownership and use a private
            # subdirectory in the user's home folder.
            taxonomy = pickle.load(f)  # noqa: S301
        taxonomy.file_path = source_path
        return taxonomy
    except (pickle.UnpicklingError, EOFError, AttributeError, ImportError, OSError):
        return None


def _try_save_cache(cache_path: Path, taxonomy: Taxonomy) -> None:
    """Save the taxonomy to the binary cache with restrictive permissions."""
    try:
        # Ensure private directory (u+rwx)
        cache_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Create file with restrictive permissions (u+rw)
        fd = os.open(cache_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode=0o600)
        with os.fdopen(fd, "wb") as f:
            # S301 is waived because we verify file ownership and use a private
            # subdirectory in the user's home folder.
            pickle.dump(taxonomy, f, protocol=pickle.HIGHEST_PROTOCOL)
    except (pickle.PicklingError, OSError):
        pass
