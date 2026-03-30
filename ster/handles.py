"""Handle generation — pure functions, no external dependencies."""

from __future__ import annotations

import re

from .model import Taxonomy


def extract_local_name(uri: str) -> str:
    """Extract the local name from a URI (after # or last /)."""
    uri = uri.rstrip("/")
    for sep in ("#", "/"):
        if sep in uri:
            return uri.rsplit(sep, 1)[-1]
    return uri


def derive_candidate(local_name: str) -> str:
    """Derive a short uppercase handle candidate from a camelCase/PascalCase name."""
    # Split on camelCase / PascalCase boundaries
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", local_name).split()
    if len(words) >= 2:
        # Acronym from first letters
        return "".join(w[0] for w in words if w).upper()
    # Single word: use up to first 3 characters
    clean = re.sub(r"[^A-Za-z0-9]", "", local_name)
    return clean[:3].upper() if clean else "X"


def handle_for_uri(uri: str, used: set[str]) -> str:
    """Assign a unique handle for a URI, avoiding collisions with `used`."""
    local = extract_local_name(uri)
    base = derive_candidate(local)
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}{suffix}"
        suffix += 1
    return candidate


def assign_handles(taxonomy: Taxonomy) -> None:
    """Populate taxonomy.handle_index with unique handles for all concepts and schemes.

    Handles are assigned in a deterministic order: schemes first, then concepts
    sorted by URI to ensure stable results across reloads.
    """
    used: set[str] = set()
    taxonomy.handle_index.clear()

    for uri in sorted(taxonomy.schemes):
        h = handle_for_uri(uri, used)
        used.add(h)
        taxonomy.handle_index[h] = uri

    for uri in sorted(taxonomy.concepts):
        h = handle_for_uri(uri, used)
        used.add(h)
        taxonomy.handle_index[h] = uri
