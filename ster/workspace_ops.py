"""Cross-scheme SKOS mapping vocabulary — property names and their inverses.

The mapping *actions* now live in the command layer (``Skos{Add,Remove}MappingLink``
applied through ``TaxonomyService``); this module just holds the shared vocabulary
the viewer and commands use to pair a mapping property with its inverse:

  broadMatch   ↔  narrowMatch
  narrowMatch  ↔  broadMatch
  relatedMatch ↔  relatedMatch
  exactMatch   ↔  exactMatch
  closeMatch   ↔  closeMatch
"""

from __future__ import annotations

from typing import Literal

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
