"""Cross-taxonomy operations — mapping links between ConceptSchemes.

When both concepts are in the **same** ConceptScheme, use the normal
``operations`` module (broader/narrower).  Use this module when the source
and target belong to **different** ConceptSchemes (even in the same file).

SKOS mapping properties and their inverses
──────────────────────────────────────────
  broadMatch   ↔  narrowMatch
  narrowMatch  ↔  broadMatch
  relatedMatch ↔  relatedMatch
  exactMatch   ↔  exactMatch
  closeMatch   ↔  closeMatch

Each ``add_mapping`` call writes the assertion in the source concept's
taxonomy and the inverse in the target concept's taxonomy.  Both may be
the same file (same-file cross-scheme mapping).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from .exceptions import SkostaxError
from .workspace import TaxonomyWorkspace

MappingType = Literal["broadMatch", "narrowMatch", "relatedMatch", "exactMatch", "closeMatch"]

# Python attribute names for each SKOS mapping property
_ATTR: dict[str, str] = {
    "broadMatch": "broad_match",
    "narrowMatch": "narrow_match",
    "relatedMatch": "related_match",
    "exactMatch": "exact_match",
    "closeMatch": "close_match",
}

# Inverse of each mapping property
_INVERSE: dict[str, str] = {
    "broadMatch": "narrowMatch",
    "narrowMatch": "broadMatch",
    "relatedMatch": "relatedMatch",
    "exactMatch": "exactMatch",
    "closeMatch": "closeMatch",
}


def add_mapping(
    workspace: TaxonomyWorkspace,
    source_uri: str,
    target_uri: str,
    mapping_type: MappingType,
) -> tuple[Path, Path]:
    """Add *mapping_type* from *source_uri* to *target_uri*, plus its inverse.

    Returns ``(source_file, target_file)`` — both paths may be the same.
    Raises ``SkostaxError`` if either concept is not found in the workspace.
    """
    src_info = workspace.concept_for(source_uri)
    tgt_info = workspace.concept_for(target_uri)
    if src_info is None:
        raise SkostaxError(f"Source concept not found: {source_uri!r}")
    if tgt_info is None:
        raise SkostaxError(f"Target concept not found: {target_uri!r}")

    src_file, src_concept = src_info
    tgt_file, tgt_concept = tgt_info

    src_list: list[str] = getattr(src_concept, _ATTR[mapping_type])
    if target_uri not in src_list:
        src_list.append(target_uri)

    inv_attr = _ATTR[_INVERSE[mapping_type]]
    tgt_list: list[str] = getattr(tgt_concept, inv_attr)
    if source_uri not in tgt_list:
        tgt_list.append(source_uri)

    return src_file, tgt_file


def remove_mapping(
    workspace: TaxonomyWorkspace,
    source_uri: str,
    target_uri: str,
    mapping_type: MappingType,
) -> tuple[Path, Path]:
    """Remove *mapping_type* from *source_uri* to *target_uri*, plus its inverse."""
    src_info = workspace.concept_for(source_uri)
    tgt_info = workspace.concept_for(target_uri)
    if src_info is None:
        raise SkostaxError(f"Source concept not found: {source_uri!r}")
    if tgt_info is None:
        raise SkostaxError(f"Target concept not found: {target_uri!r}")

    src_file, src_concept = src_info
    tgt_file, tgt_concept = tgt_info

    src_list: list[str] = getattr(src_concept, _ATTR[mapping_type])
    if target_uri in src_list:
        src_list.remove(target_uri)

    inv_attr = _ATTR[_INVERSE[mapping_type]]
    tgt_list: list[str] = getattr(tgt_concept, inv_attr)
    if source_uri in tgt_list:
        tgt_list.remove(source_uri)

    return src_file, tgt_file
