"""Binary (pickled) Taxonomy cache: schema-fingerprinted, owner-only, and pruned of
stale entries left behind whenever the model shape changes."""

from __future__ import annotations

import hashlib
import os
import pickle
from functools import lru_cache
from pathlib import Path

from ..model import Taxonomy


def _bin_cache_dir() -> Path:
    """Return the directory for binary taxonomy caches."""
    return Path.home() / ".cache" / "ster" / "bin_cache"


@lru_cache(maxsize=1)
def _model_schema_fingerprint() -> str:
    """A short hash of this build: every model dataclass, its fields, and the version.

    Unpickling does not validate the class: a Taxonomy pickled before a field
    existed is restored *without* it, no exception raised, and the first access
    to the missing attribute fails somewhere unrelated — as a 500 from the graph
    server, say. Mixing this into the cache key means a build whose model has
    changed simply looks elsewhere instead of reading the older build's file.

    The shape alone is not enough. It catches a field being added or removed, but
    not a change to the logic that *fills* one — which is the more common kind of
    change, and just as stale. A fix to how the residue is computed left every
    field name untouched, so every run went on reading the pre-fix taxonomy; a
    user upgrading ster would have kept the old behaviour until their file
    changed.

    So the version goes in too. It cannot be forgotten: a release has a distinct
    version by construction, and a development build carries its commit hash.
    """
    from dataclasses import fields, is_dataclass  # noqa: PLC0415

    from .. import model as _model  # noqa: PLC0415
    from .._version import __version__  # noqa: PLC0415

    shape = [
        f"{name}:{','.join(f.name for f in fields(obj))}"
        for name in sorted(dir(_model))
        if isinstance(obj := getattr(_model, name), type) and is_dataclass(obj)
    ]
    shape.append(f"ster:{__version__}")
    return hashlib.md5("|".join(shape).encode(), usedforsecurity=False).hexdigest()[:8]


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


def _is_merged_cache_valid(cache_path: Path, sources: list[Path]) -> bool:
    """True when the merged cache is newer than every file that went into it, the editable one and each context file.

    A file that cannot be read, or has gone, makes the cache invalid: it can no longer vouch for what it holds.
    """
    try:
        newest = max(Path(source).stat().st_mtime for source in sources)
    except (OSError, ValueError):
        return False
    return _is_cache_valid_after(cache_path, newest)


def _is_cache_valid_after(cache_path: Path, newest_source_mtime: float) -> bool:
    """The cache file is ours, private, and written after *newest_source_mtime*."""
    if not cache_path.is_file() or cache_path.is_symlink():
        return False
    try:
        stat = cache_path.stat()
    except OSError:
        return False
    if stat.st_mtime <= newest_source_mtime:
        return False
    return not hasattr(os, "getuid") or stat.st_uid == os.getuid()


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
