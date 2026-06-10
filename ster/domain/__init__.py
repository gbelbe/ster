"""Domain logic, split by ontology layer.

Each module holds the pure `Taxonomy` mutations/queries for one concern:

- :mod:`ster.domain.onto`  — ontology base URI, domain (host), and prefix

The rest of the layers (skos, owl, cross) are migrated incrementally; until then
they live in :mod:`ster.operations`, which re-exports everything here so call
sites keep importing ``ster.operations``. See docs/architecture/module-layout.md.
"""

from __future__ import annotations
