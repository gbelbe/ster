"""Application core for ster — the shared command pipeline every front-end calls.

See docs/architecture/core-service.md. The TUI, HTTP API, and CLI build a
``Command`` and call ``TaxonomyService.execute``; the service owns the single
mutate → (validate) → persist → emit transaction so all front-ends behave
identically.
"""

from __future__ import annotations
