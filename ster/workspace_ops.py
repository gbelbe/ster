"""Cross-scheme SKOS mapping vocabulary — property names, their Python attributes,
and their inverses. The single source of this correspondence: ``ster/store``
(RDF <-> Taxonomy), ``ster/domain/skos.py`` (mutating a mapping link) and
``ster/taxonomy_analysis.py`` (broken-mapping detection) all read it from here
instead of each repeating their own copy of the same five rows.

  broadMatch   ↔  narrowMatch
  narrowMatch  ↔  broadMatch
  relatedMatch ↔  relatedMatch
  exactMatch   ↔  exactMatch
  closeMatch   ↔  closeMatch
"""

from __future__ import annotations

from typing import Literal

MappingType = Literal["broadMatch", "narrowMatch", "relatedMatch", "exactMatch", "closeMatch"]

# Python attribute name for each SKOS mapping property.
ATTR: dict[str, str] = {
    "broadMatch": "broad_match",
    "narrowMatch": "narrow_match",
    "relatedMatch": "related_match",
    "exactMatch": "exact_match",
    "closeMatch": "close_match",
}

# Inverse SKOS property for each SKOS mapping property.
INVERSE: dict[str, str] = {
    "broadMatch": "narrowMatch",
    "narrowMatch": "broadMatch",
    "relatedMatch": "relatedMatch",
    "exactMatch": "exactMatch",
    "closeMatch": "closeMatch",
}
