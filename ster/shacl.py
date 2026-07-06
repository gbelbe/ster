"""SHACL business-rule writer.

ster authors SHACL rules into a sibling ``<stem>.shapes.ttl`` file that the
semanticlint plugin already auto-discovers and enforces (``*.shapes.ttl`` next to
the ontology). This module is the single place that *writes* SHACL — turtle text
plus idempotent file append — so semanticlint stays the only SHACL *reader* and a
library change touches one file.

Every rule is preceded by a dated comment explaining what it enforces, so the
generated file stays readable and auditable.
"""

from __future__ import annotations

import re
from pathlib import Path

#: semanticlint discovers any ``*.shapes.ttl`` sibling — match that suffix exactly.
SHAPES_SUFFIX = ".shapes.ttl"
_SH = "http://www.w3.org/ns/shacl#"
_SH_PREFIX = f"@prefix sh: <{_SH}> ."


def shapes_path_for(ontology_path: Path) -> Path:
    """The sibling ``<stem>.shapes.ttl`` file for *ontology_path* (e.g. ``zoo.ttl`` →
    ``zoo.shapes.ttl``), which semanticlint picks up and enforces."""
    return ontology_path.with_name(ontology_path.stem + SHAPES_SUFFIX)


def _local(uri: str) -> str:
    """The last path/fragment segment of *uri*, for building readable shape IRIs."""
    return uri.rstrip("/#").rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def shape_iri(target_uri: str, prop_uri: str) -> str:
    """The deterministic shape IRI for the (target, property) pair — a URN, independent
    of the date — so re-enforcing is idempotent and un-enforcing can find the rule."""
    return f"urn:ster:shape:{_local(target_uri)}:{_local(prop_uri)}:required"


def _rule(target_kw: str, target_uri: str, prop_uri: str, comment: str) -> tuple[str, str]:
    """A shape block requiring *prop_uri* (minCount 1) on *target_uri*, targeted by
    *target_kw* (``sh:targetClass`` or ``sh:targetNode``) and led by *comment*."""
    iri = shape_iri(target_uri, prop_uri)
    block = (
        f"{comment}\n"
        f"<{iri}> a sh:NodeShape ;\n"
        f"    {target_kw} <{target_uri}> ;\n"
        f"    sh:property [ sh:path <{prop_uri}> ; sh:minCount 1 ] .\n"
    )
    return iri, block


def mandatory_property_rule(
    target_uri: str,
    prop_uri: str,
    *,
    target_label: str,
    prop_label: str,
    date: str,
) -> tuple[str, str]:
    """A SHACL rule making *prop_uri* mandatory (``sh:minCount 1``) on every instance of
    class *target_uri* (``sh:targetClass``). Returns ``(shape_iri, turtle_block)``."""
    comment = (
        f'# ster {date}: every {target_label} must have "{prop_label}" (required, minCount 1).'
    )
    return _rule("sh:targetClass", target_uri, prop_uri, comment)


def mandatory_on_node_rule(
    node_uri: str,
    prop_uri: str,
    *,
    node_label: str,
    prop_label: str,
    date: str,
) -> tuple[str, str]:
    """A SHACL rule making *prop_uri* mandatory on the single resource *node_uri*
    (``sh:targetNode``) — e.g. the ontology node. Returns ``(shape_iri, turtle_block)``."""
    comment = f'# ster {date}: {node_label} must have "{prop_label}" (required, minCount 1).'
    return _rule("sh:targetNode", node_uri, prop_uri, comment)


def append_rules(shapes_path: Path, rules: list[tuple[str, str]]) -> list[str]:
    """Append the *rules* (``(shape_iri, turtle_block)`` pairs) to *shapes_path*, skipping
    any whose shape IRI is already present (idempotent). Creates the file with an
    ``sh:`` prefix header when it does not yet exist. Returns the IRIs actually written.
    """
    existing = shapes_path.read_text(encoding="utf-8") if shapes_path.exists() else ""
    to_write: list[tuple[str, str]] = []
    seen: set[str] = set()
    for iri, block in rules:
        if iri in seen or f"<{iri}>" in existing:
            continue  # already enforced (in the file or earlier in this batch)
        seen.add(iri)
        to_write.append((iri, block))
    if not to_write:
        return []
    parts: list[str] = []
    if _SH_PREFIX not in existing:
        parts.append(f"{_SH_PREFIX}\n")
    parts.extend(f"\n{block}" for _, block in to_write)
    with shapes_path.open("a", encoding="utf-8") as fh:
        fh.write("".join(parts))
    return [iri for iri, _ in to_write]


def remove_rules(shapes_path: Path, shape_iris: list[str]) -> list[str]:
    """Delete the comment+shape block for each IRI in *shape_iris* from *shapes_path*
    (used when un-enforcing). Leaves every other block untouched and is a no-op when a
    named IRI (or the file) is absent. Returns the IRIs actually removed."""
    if not shapes_path.exists() or not shape_iris:
        return []
    targets = set(shape_iris)
    text = shapes_path.read_text(encoding="utf-8")
    blocks = re.split(r"\n\s*\n", text.strip("\n"))  # blank-line-separated paragraphs
    kept: list[str] = []
    removed: list[str] = []
    for block in blocks:
        hit = next((iri for iri in targets if f"<{iri}>" in block), None)
        if hit is not None:
            removed.append(hit)
        else:
            kept.append(block)
    if not removed:
        return []
    shapes_path.write_text("\n\n".join(kept) + "\n", encoding="utf-8")
    return removed
